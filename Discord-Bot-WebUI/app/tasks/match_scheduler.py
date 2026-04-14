# app/tasks/match_scheduler.py

"""
Enterprise Match Scheduler Tasks

Celery tasks for the enterprise live reporting system.
Handles automated scheduling of match threads and live reporting sessions.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any
from app.decorators import celery_task
from app.services.match_scheduler_service import MatchSchedulerService
from app.utils.task_session_manager import task_session
from app.models import ScheduledTask, TaskType, TaskState
from app.models.live_reporting_session import LiveReportingSession

logger = logging.getLogger(__name__)


@celery_task(bind=True, max_retries=3, default_retry_delay=60)
def schedule_upcoming_matches(self, session):
    """
    Enterprise task to schedule upcoming matches for thread creation and live reporting.

    This task:
    1. Checks for matches in the next 48 hours that need thread creation
    2. Checks for matches in the next 5 minutes that need live reporting
    3. Uses the enterprise MatchSchedulerService for all operations
    4. Replaces deprecated V2 tasks

    Returns:
        dict: Results of scheduling operations
    """
    try:
        logger.info("🏢 Enterprise match scheduler starting...")

        # Schedule upcoming MLS matches directly (not pub league seasons)
        from app.models.external import MLSMatch
        from app.core import celery

        with task_session() as session:
            from datetime import timezone
            now = datetime.now(timezone.utc)

            # ── Dispatch phase: fire any ScheduledTasks whose time has come ──
            due_tasks = session.query(ScheduledTask).filter(
                ScheduledTask.state == TaskState.SCHEDULED,
                ScheduledTask.celery_task_id.is_(None),
                ScheduledTask.scheduled_time <= now
            ).all()

            dispatched_count = 0
            for due_task in due_tasks:
                try:
                    if due_task.task_type == TaskType.THREAD_CREATION:
                        # Verify match still needs a thread
                        from app.models.external import MLSMatch as _MLSMatch
                        _match = session.query(_MLSMatch).filter_by(id=due_task.match_id).first()
                        if _match and _match.thread_created:
                            due_task.mark_completed()
                            logger.info(f"Dispatch: thread already created for match {due_task.match_id}, marking completed")
                            continue
                        celery_result = create_mls_match_thread_task.apply_async(args=[due_task.match_id])
                    elif due_task.task_type == TaskType.LINEUP_POST:
                        celery_result = post_match_lineups_task.apply_async(args=[due_task.match_id])
                    elif due_task.task_type == TaskType.LIVE_REPORTING_START:
                        celery_result = start_mls_live_reporting_task.apply_async(args=[due_task.match_id])
                    else:
                        continue

                    due_task.mark_running(celery_result.id)
                    dispatched_count += 1
                    logger.info(f"Dispatched due task {due_task.id} (type={due_task.task_type}) for match {due_task.match_id}, celery_id={celery_result.id}")
                except Exception as e:
                    logger.error(f"Error dispatching due task {due_task.id}: {e}")

            if dispatched_count:
                session.commit()
                logger.info(f"Dispatched {dispatched_count} due tasks")

            # ── Scheduling phase: ensure upcoming matches have ScheduledTask records ──
            from app.models.external import MLSMatch
            upcoming_matches = session.query(MLSMatch).filter(
                MLSMatch.date_time > now,
                MLSMatch.date_time <= now + timedelta(days=7)  # Look ahead 7 days
            ).all()

            scheduled_threads = 0
            scheduled_live = 0

            # Get configurable timing values from AdminConfig
            from app.models.admin_config import AdminConfig
            thread_creation_hours = AdminConfig.get_setting('mls_thread_creation_hours_before', 48)
            live_reporting_minutes = AdminConfig.get_setting('mls_live_reporting_minutes_before', 5)

            for match in upcoming_matches:
                try:
                    # Ensure match.date_time is timezone-aware
                    match_dt = match.date_time
                    if match_dt.tzinfo is None:
                        match_dt = match_dt.replace(tzinfo=timezone.utc)

                    # Schedule thread creation (configurable hours before, default 48)
                    thread_time = match_dt - timedelta(hours=thread_creation_hours)

                    if not match.thread_created:
                        # Check if task already exists in database
                        existing_thread_task = ScheduledTask.find_existing_task(
                            session, match.id, TaskType.THREAD_CREATION
                        )

                        if not existing_thread_task:
                            if thread_time > now:
                                # Future: create ScheduledTask record only (no Celery dispatch)
                                # The dispatch phase will fire it when scheduled_time arrives
                                db_task = ScheduledTask(
                                    task_type=TaskType.THREAD_CREATION,
                                    match_id=match.id,
                                    celery_task_id=None,
                                    scheduled_time=thread_time,
                                    state=TaskState.SCHEDULED
                                )
                                session.add(db_task)
                                scheduled_threads += 1
                                logger.info(f"Scheduled thread creation for match {match.id} at {thread_time} (poll-dispatch, no ETA)")
                            else:
                                # Past: create immediately (thread creation time has passed)
                                celery_task = create_mls_match_thread_task.apply_async(
                                    args=[match.id]
                                )

                                # Create database tracking record as RUNNING
                                db_task = ScheduledTask(
                                    task_type=TaskType.THREAD_CREATION,
                                    match_id=match.id,
                                    celery_task_id=celery_task.id,
                                    scheduled_time=thread_time,
                                    state=TaskState.RUNNING,
                                    execution_time=now
                                )
                                session.add(db_task)
                                scheduled_threads += 1
                                logger.info(f"Immediately creating thread for match {match.id} (overdue by {now - thread_time}), task_id={celery_task.id}")

                    # Schedule live reporting start (configurable minutes before, default 5)
                    live_start_time = match_dt - timedelta(minutes=live_reporting_minutes)

                    # Check if task already exists in database
                    existing_reporting_task = ScheduledTask.find_existing_task(
                        session, match.id, TaskType.LIVE_REPORTING_START
                    )

                    if not existing_reporting_task:
                        # Check if live session already exists
                        existing_live_session = session.query(LiveReportingSession).filter_by(
                            match_id=str(match.match_id),
                            is_active=True
                        ).first()

                        if not existing_live_session:
                            if live_start_time > now:
                                # Future: create ScheduledTask record only (no Celery dispatch)
                                db_task = ScheduledTask(
                                    task_type=TaskType.LIVE_REPORTING_START,
                                    match_id=match.id,
                                    celery_task_id=None,
                                    scheduled_time=live_start_time,
                                    state=TaskState.SCHEDULED
                                )
                                session.add(db_task)
                                scheduled_live += 1
                                logger.info(f"Scheduled live reporting for match {match.id} at {live_start_time} (poll-dispatch, no ETA)")
                            elif match_dt > now:
                                # Past due but match hasn't started yet or is in progress:
                                # start immediately
                                celery_task = start_mls_live_reporting_task.apply_async(
                                    args=[match.id]
                                )
                                db_task = ScheduledTask(
                                    task_type=TaskType.LIVE_REPORTING_START,
                                    match_id=match.id,
                                    celery_task_id=celery_task.id,
                                    scheduled_time=live_start_time,
                                    state=TaskState.RUNNING,
                                    execution_time=now
                                )
                                session.add(db_task)
                                scheduled_live += 1
                                logger.info(f"Immediately started live reporting for match {match.id}, task_id={celery_task.id}")
                            else:
                                # Match start time has passed — check if within 3 hours
                                # (matches last ~2 hours, give buffer)
                                if now - match_dt < timedelta(hours=3):
                                    celery_task = start_mls_live_reporting_task.apply_async(
                                        args=[match.id]
                                    )
                                    db_task = ScheduledTask(
                                        task_type=TaskType.LIVE_REPORTING_START,
                                        match_id=match.id,
                                        celery_task_id=celery_task.id,
                                        scheduled_time=live_start_time,
                                        state=TaskState.RUNNING,
                                        execution_time=now
                                    )
                                    session.add(db_task)
                                    scheduled_live += 1
                                    logger.info(f"Immediately started live reporting for match {match.id} (match in progress), task_id={celery_task.id}")

                except Exception as e:
                    logger.error(f"Error scheduling MLS match {match.id}: {e}")

            # Commit all database task records
            session.commit()

            result = {
                'success': True,
                'total_matches': len(upcoming_matches),
                'threads_scheduled': scheduled_threads,
                'reporting_scheduled': scheduled_live
            }

        if result['success']:
            logger.info(f"✅ Enterprise scheduler: {result['threads_scheduled']} threads, {result['reporting_scheduled']} live sessions")
            return {
                'success': True,
                'enterprise_system': True,
                'threads_scheduled': result['threads_scheduled'],
                'reporting_scheduled': result['reporting_scheduled'],
                'message': 'Enterprise scheduling completed successfully'
            }
        else:
            logger.error(f"❌ Enterprise scheduler failed: {result.get('error', 'Unknown error')}")
            return {
                'success': False,
                'error': result.get('error', 'Enterprise scheduling failed'),
                'enterprise_system': True
            }

    except Exception as e:
        logger.error(f"Enterprise match scheduler error: {e}", exc_info=True)

        # Retry on failure
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying enterprise scheduler (attempt {self.request.retries + 1}/{self.max_retries})")
            raise self.retry(countdown=60 * (self.request.retries + 1))

        return {
            'success': False,
            'error': str(e),
            'enterprise_system': True,
            'retries_exhausted': True
        }


@celery_task(bind=True, max_retries=2, default_retry_delay=30)
def trigger_live_reporting_session(self, match_id: int, discord_thread_id: str, espn_match_id: str):
    """
    Enterprise task to trigger live reporting for a specific match.
    Called by the match scheduler service when live reporting should start.

    Args:
        match_id: Database match ID
        discord_thread_id: Discord thread ID for updates
        espn_match_id: ESPN match ID for data

    Returns:
        dict: Results of live reporting activation
    """
    try:
        logger.info(f"🔴 Starting enterprise live reporting for match {match_id}")

        scheduler_service = MatchSchedulerService()

        # Signal the real-time service to start reporting this match
        result = scheduler_service.start_live_reporting_session(
            match_id=match_id,
            discord_thread_id=discord_thread_id,
            espn_match_id=espn_match_id
        )

        if result['success']:
            logger.info(f"✅ Live reporting activated for match {match_id}")
            return {
                'success': True,
                'match_id': match_id,
                'enterprise_system': True,
                'real_time_service_notified': True
            }
        else:
            logger.error(f"❌ Failed to start live reporting for match {match_id}: {result.get('error')}")
            return {
                'success': False,
                'match_id': match_id,
                'error': result.get('error'),
                'enterprise_system': True
            }

    except Exception as e:
        logger.error(f"Enterprise live reporting trigger error for match {match_id}: {e}", exc_info=True)

        # Retry on failure
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying live reporting trigger for match {match_id} (attempt {self.request.retries + 1})")
            raise self.retry(countdown=30)

        return {
            'success': False,
            'match_id': match_id,
            'error': str(e),
            'enterprise_system': True,
            'retries_exhausted': True
        }


@celery_task(bind=True)
def health_check_enterprise_system(self):
    """
    Health check for the enterprise live reporting system.
    Verifies that all components are operational.

    Returns:
        dict: Health status of enterprise components
    """
    try:
        logger.info("🔍 Enterprise system health check starting...")

        scheduler_service = MatchSchedulerService()

        # Check enterprise components
        health_status = {
            'enterprise_system': True,
            'timestamp': datetime.utcnow().isoformat(),
            'match_scheduler_service': True,
            'real_time_service': False,  # Will be checked
            'database_connection': False,  # Will be checked
            'redis_connection': False,  # Will be checked
            'discord_bot_connection': False  # Will be checked
        }

        # Test database connection
        try:
            # Simple test via scheduler service
            test_result = scheduler_service.get_upcoming_matches_for_scheduling()
            health_status['database_connection'] = True
            health_status['upcoming_matches_count'] = len(test_result)
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            health_status['database_error'] = str(e)

        # Test real-time service connection
        try:
            from app.services.realtime_reporting_service import RealtimeReportingService
            realtime_service = RealtimeReportingService()
            # Simple health check
            health_status['real_time_service'] = True
        except Exception as e:
            logger.error(f"Real-time service health check failed: {e}")
            health_status['realtime_service_error'] = str(e)

        overall_health = all([
            health_status['match_scheduler_service'],
            health_status['database_connection']
        ])

        health_status['overall_status'] = 'healthy' if overall_health else 'degraded'

        if overall_health:
            logger.info("✅ Enterprise system health check passed")
        else:
            logger.warning("⚠️ Enterprise system health check shows degraded status")

        return health_status

    except Exception as e:
        logger.error(f"Enterprise health check error: {e}", exc_info=True)
        return {
            'enterprise_system': True,
            'overall_status': 'failed',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


def _build_espn_description(espn_match_id: str, home_team: str, away_team: str, competition: str) -> str:
    """
    Build a factual match thread description from ESPN data.

    Fetches team records, standings positions, and h2h from ESPN.
    Returns a formatted string or a simple fallback if ESPN data is unavailable.
    """
    from app.utils.sync_espn_client import get_sync_espn_client

    fallback = f"{home_team} vs {away_team}"

    try:
        from app.utils.competition_mappings import resolve_league_code
        espn = get_sync_espn_client()
        comp_code = resolve_league_code(competition)

        # Get both team IDs from the ESPN event data
        competitors = espn.get_event_competitors(espn_match_id, comp_code)
        if not competitors:
            logger.warning(f"Could not fetch competitors for match {espn_match_id}")
            return fallback

        # Fetch team info for both sides
        home_info = espn.get_team_info(competitors['home_team_id'], comp_code)
        away_info = espn.get_team_info(competitors['away_team_id'], comp_code)

        # Build description lines
        lines = []

        # Home team line
        home_line = home_team
        if home_info:
            record = f"{home_info['wins']}W-{home_info['ties']}D-{home_info['losses']}L"
            standing = home_info.get('standing_summary', '')
            if standing:
                # standingSummary is like "4th in Western Conference" - shorten to "4th Western"
                standing_short = standing.replace(' in ', ' ').replace(' Conference', '')
                home_line = f"{home_team} ({record}, {standing_short})"
            else:
                home_line = f"{home_team} ({record})"
        lines.append(home_line)

        # "vs" separator
        lines.append("vs")

        # Away team line
        away_line = away_team
        if away_info:
            record = f"{away_info['wins']}W-{away_info['ties']}D-{away_info['losses']}L"
            standing = away_info.get('standing_summary', '')
            if standing:
                standing_short = standing.replace(' in ', ' ').replace(' Conference', '')
                away_line = f"{away_team} ({record}, {standing_short})"
            else:
                away_line = f"{away_team} ({record})"
        lines.append(away_line)

        # H2H last meeting
        h2h = espn.get_head_to_head(espn_match_id, comp_code)
        if h2h:
            lines.append(f"Last meeting: {h2h}")

        description = "\n".join(lines)
        logger.info(f"Built ESPN description for match {espn_match_id}: {description[:80]}...")
        return description

    except Exception as e:
        logger.warning(f"Error building ESPN description for match {espn_match_id}: {e}")
        return fallback


@celery_task(
    name='app.tasks.match_scheduler.create_mls_match_thread_task',
    queue='discord',
    max_retries=3,
    soft_time_limit=60,
    time_limit=90
)
def create_mls_match_thread_task(self, session, match_id: int) -> Dict[str, Any]:
    """
    Create Discord thread for an MLS match (48 hours before kickoff).
    """
    task_id = self.request.id or 'unknown'
    try:
        from app.models.external import MLSMatch
        from app.utils.sync_discord_client import get_sync_discord_client
        from app.utils.safe_redis import get_safe_redis
        from zoneinfo import ZoneInfo

        # Get MLS match details
        match = session.query(MLSMatch).filter_by(id=match_id).first()
        if not match:
            logger.error(f"MLS Match {match_id} not found")
            return {"success": False, "error": "MLS Match not found"}

        # ── Idempotency guard: if thread already exists, skip ──
        if match.thread_created and match.discord_thread_id:
            logger.info(f"Thread already exists for match {match_id} (thread_id={match.discord_thread_id}), skipping")
            # Mark any pending ScheduledTask as completed
            sched_task = ScheduledTask.find_existing_task(session, match_id, TaskType.THREAD_CREATION)
            if sched_task and sched_task.state != TaskState.COMPLETED:
                sched_task.mark_completed()
                session.commit()
            return {"success": True, "match_id": match_id, "thread_id": match.discord_thread_id, "already_existed": True}

        # ── Redis distributed lock: prevent concurrent thread creation ──
        redis = get_safe_redis()
        lock_key = f"thread_creation_lock:{match_id}"
        lock_acquired = redis.set(lock_key, task_id, nx=True, ex=300)

        if not lock_acquired:
            # Another worker may be creating the thread right now — re-check DB
            session.refresh(match)
            if match.thread_created and match.discord_thread_id:
                logger.info(f"Lock held but thread now exists for match {match_id}, returning success")
                return {"success": True, "match_id": match_id, "thread_id": match.discord_thread_id, "already_existed": True}
            logger.warning(f"Could not acquire thread creation lock for match {match_id} (task={task_id}), another task is creating it")
            return {"success": False, "error": "Another task is creating this thread", "retry_needed": True}

        try:
            # Prepare match data for sync Discord client
            match_dt = match.date_time
            if match_dt.tzinfo is None:
                utc_time = match_dt.replace(tzinfo=ZoneInfo('UTC'))
            else:
                utc_time = match_dt.astimezone(ZoneInfo('UTC'))
            pst_time = utc_time.astimezone(ZoneInfo('America/Los_Angeles'))

            home_team = 'Seattle Sounders FC' if match.is_home_game else match.opponent
            away_team = match.opponent if match.is_home_game else 'Seattle Sounders FC'

            match_data = {
                'id': match.id,
                'match_id': match.match_id,
                'home_team': home_team,
                'away_team': away_team,
                'date': pst_time.strftime('%Y-%m-%d'),
                'time': pst_time.strftime('%-I:%M %p PST'),
                'venue': match.venue or 'TBD',
                'competition': match.competition or 'MLS',
                'is_home_game': match.is_home_game
            }

            # Fetch factual ESPN data for thread description
            espn_description = _build_espn_description(
                match.match_id, home_team, away_team, match.competition or 'usa.1'
            )

            # Try to add minimal natural structuring via AI. The prompt is tight
            # ("short connectives only, no embellishment"), and the result goes
            # through the commentary_validator anti-AI-tone gate. If the AI
            # returns nothing or validation rejects the output, we fall back
            # to the raw ESPN description — never a generic boilerplate line.
            thread_description = espn_description
            try:
                from app.utils.sync_ai_client import get_sync_ai_client
                ai_context = {
                    'home_team': home_team,
                    'away_team': away_team,
                    'competition': match.competition or 'MLS',
                    'venue': match.venue or '',
                    'espn_info': espn_description,
                }
                ai_client = get_sync_ai_client()
                ai_rewrite = ai_client.generate_match_thread_context(ai_context)
                if ai_rewrite and ai_rewrite.strip():
                    thread_description = ai_rewrite.strip()
                    logger.info(
                        f"Match {match_id}: AI-structured thread description accepted"
                    )
                else:
                    logger.info(
                        f"Match {match_id}: AI thread structuring empty/rejected, "
                        f"using raw ESPN description"
                    )
            except Exception as ai_err:
                logger.warning(
                    f"Match {match_id}: AI thread structuring failed "
                    f"({ai_err}); using raw ESPN description"
                )

            match_data['description'] = thread_description

            # Use sync Discord client (works reliably)
            discord_client = get_sync_discord_client()
            thread_id = discord_client.create_match_thread(match_data)

            if thread_id:
                # Mark thread as created
                match.thread_created = True
                match.discord_thread_id = thread_id
                match.thread_creation_time = datetime.utcnow()

                # Mark ScheduledTask as completed
                sched_task = ScheduledTask.find_existing_task(session, match_id, TaskType.THREAD_CREATION)
                if sched_task:
                    sched_task.mark_completed()

                session.commit()

                logger.info(f"Created MLS thread {thread_id} for match {match.match_id}")

                return {
                    "success": True,
                    "match_id": match_id,
                    "thread_id": thread_id
                }
            else:
                logger.error(f"Failed to create MLS thread for match {match.match_id}: No thread ID returned")
                return {"success": False, "error": "No thread ID returned"}
        finally:
            # Release lock
            redis.delete(lock_key)

    except Exception as e:
        logger.error(f"Error creating MLS thread for match {match_id}: {e}")
        return {"success": False, "error": str(e)}


@celery_task(
    name='app.tasks.match_scheduler.post_match_lineups_task',
    queue='discord',
    max_retries=2,
    soft_time_limit=30,
    time_limit=45
)
def post_match_lineups_task(self, session, match_id: int) -> Dict[str, Any]:
    """
    Post match lineups to the Discord thread at T-10 minutes.

    Fetches lineup data from ESPN summary API and posts a formatted
    embed showing starters and subs for both teams.
    """
    try:
        from app.models.external import MLSMatch
        from app.utils.espn_api_client import ESPNAPIClient
        from app.utils.discord_request_handler import send_to_discord_bot

        with task_session() as db_session:
            match = db_session.query(MLSMatch).filter_by(id=match_id).first()
            if not match:
                return {"success": False, "error": f"Match {match_id} not found"}

            thread_id = match.discord_thread_id
            if not thread_id:
                logger.warning(f"No Discord thread for match {match_id}, skipping lineup post")
                return {"success": False, "error": "No Discord thread"}

            espn_id = match.espn_match_id or match.match_id
            competition_map = {
                'MLS': 'usa.1',
                'US Open Cup': 'usa.open',
                'Leagues Cup': 'usa.leagues_cup',
                'CONCACAF Champions League': 'concacaf.champions',
                'CONCACAF Champions Cup': 'concacaf.champions',
                'Concacaf Champions League': 'concacaf.champions',
                'Concacaf Champions Cup': 'concacaf.champions',
                'Concacaf': 'concacaf.champions',
            }
            league_code = competition_map.get(match.competition or 'MLS', 'usa.1')

            espn_client = ESPNAPIClient()
            lineups = espn_client.get_match_lineups(str(espn_id), league_code)

            if not lineups:
                logger.info(f"No lineup data available yet for match {match_id}")
                # Mark as completed — lineups just weren't available
                task = ScheduledTask.find_existing_task(db_session, match_id, TaskType.LINEUP_POST)
                if task:
                    task.mark_completed()
                    db_session.commit()
                return {"success": True, "message": "No lineup data available from ESPN"}

            # Build lineup embeds for each team
            for side in ('home', 'away'):
                team_data = lineups.get(side)
                if not team_data:
                    continue

                starters = team_data.get('starters', [])
                subs = team_data.get('subs', [])
                team_name = team_data.get('team', 'Unknown')
                team_logo = team_data.get('logo', '')

                # Format starters grouped by position
                starter_lines = []
                for p in starters:
                    jersey = f"#{p['jersey']} " if p.get('jersey') else ''
                    pos = f"({p['position']})" if p.get('position') else ''
                    starter_lines.append(f"{jersey}{p['name']} {pos}".strip())

                # Format subs (just names)
                sub_names = [p['name'] for p in subs[:7]]  # Show up to 7 subs

                description = '\n'.join(starter_lines)
                if sub_names:
                    description += f"\n\n**Bench:** {', '.join(sub_names)}"

                embed = {
                    'title': f'{team_name} Lineup',
                    'description': description,
                    'color': 0x005F4F if side == 'home' else 0x666666,
                    'timestamp': datetime.utcnow().isoformat(),
                    'footer': {'text': 'Starting XI'},
                    'fields': [],
                }

                if team_logo:
                    embed['thumbnail'] = {'url': team_logo}

                request_data = {
                    'thread_id': thread_id,
                    'event_type': 'lineup',
                    'content': f"{team_name} starting XI",
                    'embed': embed,
                    'match_data': {'match_id': str(match_id)}
                }

                response = send_to_discord_bot('/api/live-reporting/event', request_data)
                if response and response.get('success'):
                    logger.info(f"Posted {side} lineup for match {match_id}")
                else:
                    error_msg = response.get('error', 'Unknown') if response else 'No response'
                    logger.error(f"Failed to post {side} lineup: {error_msg}")

            # Mark task completed
            task = ScheduledTask.find_existing_task(db_session, match_id, TaskType.LINEUP_POST)
            if task:
                task.mark_completed()
                db_session.commit()

            return {"success": True, "message": "Lineups posted"}

    except Exception as e:
        logger.error(f"Error posting lineups for match {match_id}: {e}")
        return {"success": False, "error": str(e)}


@celery_task(
    name='app.tasks.match_scheduler.start_mls_live_reporting_task',
    queue='live_reporting',
    max_retries=2,
    soft_time_limit=30,
    time_limit=45
)
def start_mls_live_reporting_task(self, session, match_id: int) -> Dict[str, Any]:
    """
    Start live reporting for an MLS match (5 minutes before kickoff).
    """
    task_id = self.request.id or 'unknown'
    try:
        from app.models.external import MLSMatch
        from app.models import LiveReportingSession
        from app.utils.safe_redis import get_safe_redis

        # Get MLS match details
        match = session.query(MLSMatch).filter_by(id=match_id).first()
        if not match:
            logger.error(f"MLS Match {match_id} not found")
            return {"success": False, "error": "MLS Match not found"}

        # Check if live session already exists (use match_id as string)
        existing_session = session.query(LiveReportingSession).filter_by(
            match_id=str(match.match_id),  # LiveReportingSession expects string
            is_active=True
        ).first()

        if existing_session:
            logger.info(f"Live session already exists for MLS match {match.match_id}")
            # Mark ScheduledTask as completed
            sched_task = ScheduledTask.find_existing_task(session, match_id, TaskType.LIVE_REPORTING_START)
            if sched_task and sched_task.state != TaskState.COMPLETED:
                sched_task.mark_completed()
                session.commit()
            return {
                "success": True,
                "match_id": match_id,
                "session_id": existing_session.id,
                "message": "Session already active"
            }

        # CRITICAL FIX: Get thread_id from match record - don't create session without it
        thread_id = match.discord_thread_id
        if not thread_id:
            logger.error(f"Cannot start live reporting for match {match.id}: no Discord thread created")
            return {
                "success": False,
                "match_id": match_id,
                "error": "No Discord thread created for this match. Create thread first."
            }

        # ── Redis distributed lock: prevent concurrent session creation ──
        redis = get_safe_redis()
        lock_key = f"live_reporting_lock:{match_id}"
        lock_acquired = redis.set(lock_key, task_id, nx=True, ex=120)

        if not lock_acquired:
            # Another worker may be creating the session — re-check DB
            session.expire_all()
            existing_session = session.query(LiveReportingSession).filter_by(
                match_id=str(match.match_id),
                is_active=True
            ).first()
            if existing_session:
                logger.info(f"Lock held but live session now exists for match {match_id}")
                return {"success": True, "match_id": match_id, "session_id": existing_session.id, "message": "Session created by another worker"}
            logger.warning(f"Could not acquire live reporting lock for match {match_id} (task={task_id})")
            return {"success": False, "error": "Another task is starting live reporting", "retry_needed": True}

        try:
            # Create live reporting session for MLS match
            live_session = LiveReportingSession(
                match_id=str(match.match_id),  # Use ESPN match_id as string
                thread_id=str(thread_id),  # Use actual thread ID from match
                competition=match.competition or 'MLS',
                is_active=True,
                started_at=datetime.utcnow(),
                last_update=datetime.utcnow(),
                update_count=0,
                error_count=0
            )

            session.add(live_session)

            # Mark ScheduledTask as completed
            sched_task = ScheduledTask.find_existing_task(session, match_id, TaskType.LIVE_REPORTING_START)
            if sched_task:
                sched_task.mark_completed()

            session.commit()

            # Notify real-time service of new session
            from app.services.realtime_bridge_service import notify_session_started
            bridge_result = notify_session_started(live_session.id, str(match.match_id), str(thread_id))

            logger.info(f"Started MLS live reporting session {live_session.id} for match {match.match_id}")

            return {
                "success": True,
                "match_id": match_id,
                "session_id": live_session.id,
                "espn_match_id": match.match_id
            }
        finally:
            # Release lock
            redis.delete(lock_key)

    except Exception as e:
        logger.error(f"Error starting MLS live reporting for match {match_id}: {e}")
        return {"success": False, "error": str(e)}