# app/tasks/match_scheduler.py

"""
Enterprise Match Scheduler Tasks

Celery tasks for the enterprise live reporting system.
Handles automated scheduling of match threads and live reporting sessions.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from app.services.live_reporting_event_log import record_event as _log_event
from app.decorators import celery_task
from app.services.match_scheduler_service import MatchSchedulerService
from app.utils.task_session_manager import task_session
from app.models import ScheduledTask, TaskType, TaskState
from app.models.live_reporting_session import LiveReportingSession

logger = logging.getLogger(__name__)


@celery_task(max_retries=2, default_retry_delay=300)
def auto_import_espn_matches(self, session):
    """
    Daily catch-up import of newly-confirmed Sounders fixtures from ESPN.

    Fetches upcoming (fixture=true) matches across every competition in
    COMPETITION_MAPPINGS and inserts any that aren't already in MLSMatch.
    Existing matches are skipped (dedup by ESPN match_id), so this is safe to
    run repeatedly.

    Why this exists: knockout / playoff fixtures (Leagues Cup, MLS Cup,
    US Open Cup, CONCACAF, etc.) only appear at ESPN once Sounders advance and
    the bracket is drawn. Without this, an admin has to remember to re-click
    "Fetch ESPN" during a cup/playoff run or the match never enters the DB.
    This is NOT playoff-specific — it picks up any newly-confirmed fixture in
    any competition (including rescheduled regular-season games).

    Thread creation / live reporting is NOT scheduled here — inserting the row
    is enough. The every-10-min `schedule_upcoming_matches` beat job picks up
    any MLSMatch inside its 7-day window and schedules those tasks.
    """
    from datetime import timezone
    from app.api_utils import async_to_sync, extract_match_details
    from app.services.espn_service import get_espn_service
    from app.db_utils import insert_mls_match
    from app.utils.competition_mappings import COMPETITION_MAPPINGS
    from app.models.external import MLSMatch

    espn_service = get_espn_service()
    now = datetime.now(timezone.utc)
    imported = []
    errors = 0

    for competition_name, competition_code in COMPETITION_MAPPINGS.items():
        try:
            team_endpoint = f"sports/soccer/{competition_code}/teams/9726/schedule?fixture=true"
            team_data = async_to_sync(espn_service.fetch_data(endpoint=team_endpoint))
            if not team_data or 'events' not in team_data:
                continue

            for event in team_data['events']:
                try:
                    match_details = extract_match_details(event)

                    # Dedup: skip anything already imported.
                    existing = session.query(MLSMatch).filter_by(
                        match_id=match_details['match_id']
                    ).first()
                    if existing:
                        continue

                    # fixture=true should only return upcoming games, but guard
                    # against a stray past event anyway.
                    match_dt = match_details['date_time']
                    if match_dt.tzinfo is None:
                        match_dt = match_dt.replace(tzinfo=timezone.utc)
                    if match_dt < now:
                        continue

                    match = insert_mls_match(
                        session,
                        match_details['match_id'],
                        match_details['opponent'],
                        match_details['date_time'],
                        match_details['is_home_game'],
                        match_details['match_summary_link'],
                        match_details['match_stats_link'],
                        match_details['match_commentary_link'],
                        match_details['venue'],
                        competition_code,
                        espn_match_id=match_details['match_id'],
                        broadcast=match_details.get('broadcast')
                    )
                    session.commit()

                    if match:
                        imported.append({
                            'match_id': match_details['match_id'],
                            'opponent': match_details['opponent'],
                            'competition': competition_name,
                            'date_time': match_details['date_time'].isoformat(),
                        })
                        logger.info(
                            f"Auto-imported new {competition_name} match vs "
                            f"{match_details['opponent']} on {match_details['date_time']}"
                        )

                except Exception as e:
                    session.rollback()
                    errors += 1
                    logger.error(f"Error auto-importing ESPN event: {e}")
                    continue

        except Exception as e:
            errors += 1
            logger.error(f"Error fetching {competition_name} for auto-import: {e}")
            continue

    if imported:
        logger.info(f"ESPN auto-import: added {len(imported)} new match(es)")
    return {
        'success': True,
        'imported_count': len(imported),
        'imported': imported,
        'errors': errors,
    }


def _ensure_prematch_task(session, match_id, task_type, post_time, match_dt, now, already_posted):
    """
    Ensure a re-dispatchable ScheduledTask row exists for a one-shot pre-match
    post (build-up / lineup), driven off the durable posted flag.

    Returns True if a row was created or re-armed (for counting), False otherwise.

    Idempotency contract: the post itself is guarded by the durable
    `buildup_posted`/`lineups_posted` flag on MLSMatch, set only after a
    confirmed Discord send. That lets this stay simple and aggressive about
    retrying:
      - already posted → do nothing (flag is the source of truth).
      - match already started → do nothing (too late; dispatch phase expires any
        leftover SCHEDULED row).
      - a live row (SCHEDULED/RUNNING) already exists → leave it (in flight).
      - only dead rows (FAILED/EXPIRED, or a stale COMPLETED with the flag still
        false) → re-arm the most recent one to SCHEDULED so the dispatch phase
        fires it again. This is what makes a transient Discord/ESPN outage a
        delayed post instead of a MISSED post, without ever double-posting.
    """
    if already_posted or match_dt <= now:
        return False

    active = session.query(ScheduledTask).filter(
        ScheduledTask.match_id == match_id,
        ScheduledTask.task_type == task_type,
        ScheduledTask.state.in_([TaskState.SCHEDULED, TaskState.RUNNING])
    ).first()
    if active:
        return False

    dead = session.query(ScheduledTask).filter(
        ScheduledTask.match_id == match_id,
        ScheduledTask.task_type == task_type
    ).order_by(ScheduledTask.id.desc()).first()

    if dead:
        prior_state = dead.state
        dead.state = TaskState.SCHEDULED
        dead.celery_task_id = None
        dead.scheduled_time = post_time
        logger.info(f"Re-armed {task_type} for match {match_id} (prior attempt was {prior_state}, still unposted)")
    else:
        session.add(ScheduledTask(
            task_type=task_type,
            match_id=match_id,
            celery_task_id=None,
            scheduled_time=post_time,
            state=TaskState.SCHEDULED
        ))
        logger.info(f"Scheduled {task_type} for match {match_id} at {post_time} (poll-dispatch)")
    return True


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

            # ── Scheduling phase: ensure upcoming matches have ScheduledTask records ──
            # This phase only CREATES rows — it never calls apply_async. All
            # dispatching happens in the dispatch phase below, which claims each
            # row (commit) before firing it, so a crash + Celery retry of this
            # task can never double-post. (Root cause of the 2026-07-16
            # build-up/lineup spam: apply_async before commit, then the task
            # retried at +1/+3/+6 min and re-dispatched everything each time.)
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
            # Lineup post: 30min default. ESPN typically publishes 30-60min
            # before kickoff; if not ready, the task self-retries every 5min.
            lineup_post_minutes = AdminConfig.get_setting('mls_lineup_post_minutes_before', 30)
            # Build-up post (form + H2H): 3h before kickoff by default.
            buildup_post_hours = AdminConfig.get_setting('mls_buildup_post_hours_before', 3)

            scheduled_lineups = 0
            scheduled_buildups = 0

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
                            # Create the row only — overdue rows (thread_time in
                            # the past) are fired by the dispatch phase below in
                            # this same run.
                            db_task = ScheduledTask(
                                task_type=TaskType.THREAD_CREATION,
                                match_id=match.id,
                                celery_task_id=None,
                                scheduled_time=thread_time,
                                state=TaskState.SCHEDULED
                            )
                            session.add(db_task)
                            scheduled_threads += 1
                            logger.info(f"Scheduled thread creation for match {match.id} at {thread_time} (poll-dispatch)")

                    # Schedule lineup + build-up posts. These stay re-dispatchable
                    # until they actually post (durable *_posted flag) or the match
                    # starts — a prior FAILED/EXPIRED row (e.g. Discord was down) is
                    # re-armed rather than dead-ending, so a transient blip can't
                    # make us MISS the post. The flag guard inside each task makes
                    # re-dispatch safe: it can never double-post. Bound is kickoff,
                    # enforced here (match_dt > now) and by the dispatch phase, which
                    # expires any pre-match row once the match has started.
                    lineup_time = match_dt - timedelta(minutes=lineup_post_minutes)
                    if _ensure_prematch_task(
                        session, match.id, TaskType.LINEUP_POST, lineup_time,
                        match_dt, now, already_posted=match.lineups_posted
                    ):
                        scheduled_lineups += 1

                    buildup_time = match_dt - timedelta(hours=buildup_post_hours)
                    if _ensure_prematch_task(
                        session, match.id, TaskType.BUILDUP_POST, buildup_time,
                        match_dt, now, already_posted=match.buildup_posted
                    ):
                        scheduled_buildups += 1

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
                            # Create the row unless the match ended long ago
                            # (matches last ~2 hours, give buffer). Overdue rows
                            # are fired by the dispatch phase below in this run.
                            if match_dt > now or now - match_dt < timedelta(hours=3):
                                db_task = ScheduledTask(
                                    task_type=TaskType.LIVE_REPORTING_START,
                                    match_id=match.id,
                                    celery_task_id=None,
                                    scheduled_time=live_start_time,
                                    state=TaskState.SCHEDULED
                                )
                                session.add(db_task)
                                scheduled_live += 1
                                logger.info(f"Scheduled live reporting for match {match.id} at {live_start_time} (poll-dispatch)")

                except Exception as e:
                    # Roll back so a failed match can't poison the session and
                    # sink the commit below (loses only uncommitted row adds —
                    # they get recreated next beat run).
                    session.rollback()
                    logger.error(f"Error scheduling MLS match {match.id}: {e}")

            # Commit all database task records
            session.commit()

            # ── Dispatch phase: fire any ScheduledTasks whose time has come ──
            # Each row is claimed (state=RUNNING, committed) BEFORE apply_async,
            # so a crash or Celery retry of this task can never re-dispatch a
            # post that already fired.
            due_tasks = session.query(ScheduledTask).filter(
                ScheduledTask.state == TaskState.SCHEDULED,
                ScheduledTask.celery_task_id.is_(None),
                ScheduledTask.scheduled_time <= now
            ).all()

            dispatched_count = 0
            for due_task in due_tasks:
                try:
                    _match = session.query(MLSMatch).filter_by(id=due_task.match_id).first()
                    _dt = _match.date_time if _match else None
                    if _dt is not None and _dt.tzinfo is None:
                        _dt = _dt.replace(tzinfo=timezone.utc)

                    # Skip work that no longer makes sense.
                    if due_task.task_type == TaskType.THREAD_CREATION and _match and _match.thread_created:
                        due_task.mark_completed()
                        session.commit()
                        logger.info(f"Dispatch: thread already created for match {due_task.match_id}, marking completed")
                        continue
                    if due_task.task_type in (TaskType.BUILDUP_POST, TaskType.LINEUP_POST):
                        if _dt is None or _dt <= now:
                            due_task.mark_expired()
                            due_task.last_error = 'match already started — pre-match post skipped'
                            session.commit()
                            continue

                    # Claim before dispatch.
                    due_task.mark_running()
                    session.commit()
                except Exception as e:
                    session.rollback()
                    logger.error(f"Error claiming due task {due_task.id}: {e}")
                    continue

                try:
                    if due_task.task_type == TaskType.THREAD_CREATION:
                        celery_result = create_mls_match_thread_task.apply_async(args=[due_task.match_id])
                    elif due_task.task_type == TaskType.BUILDUP_POST:
                        celery_result = post_match_buildup_task.apply_async(args=[due_task.match_id])
                    elif due_task.task_type == TaskType.LINEUP_POST:
                        celery_result = post_match_lineups_task.apply_async(args=[due_task.match_id])
                    elif due_task.task_type == TaskType.LIVE_REPORTING_START:
                        celery_result = start_mls_live_reporting_task.apply_async(args=[due_task.match_id])
                    else:
                        due_task.mark_expired()
                        due_task.last_error = f"unknown task type {due_task.task_type}"
                        session.commit()
                        continue

                    due_task.celery_task_id = celery_result.id
                    session.commit()
                    dispatched_count += 1
                    logger.info(f"Dispatched due task {due_task.id} (type={due_task.task_type}) for match {due_task.match_id}, celery_id={celery_result.id}")
                except Exception as e:
                    # Broker hiccup — release the claim so the next beat run retries.
                    session.rollback()
                    logger.error(f"Error dispatching due task {due_task.id}: {e}")
                    try:
                        due_task.state = TaskState.SCHEDULED
                        due_task.last_error = f"dispatch failed: {e}"
                        session.commit()
                    except Exception:
                        session.rollback()

            if dispatched_count:
                logger.info(f"Dispatched {dispatched_count} due tasks")

            result = {
                'success': True,
                'total_matches': len(upcoming_matches),
                'threads_scheduled': scheduled_threads,
                'reporting_scheduled': scheduled_live,
                'lineups_scheduled': scheduled_lineups,
                'buildups_scheduled': scheduled_buildups,
                'dispatched': dispatched_count,
            }

        if result['success']:
            logger.info(
                f"✅ Enterprise scheduler: {result['threads_scheduled']} threads, "
                f"{result['buildups_scheduled']} build-ups, "
                f"{result['lineups_scheduled']} lineups, "
                f"{result['reporting_scheduled']} live sessions"
            )
            return {
                'success': True,
                'enterprise_system': True,
                'threads_scheduled': result['threads_scheduled'],
                'lineups_scheduled': result['lineups_scheduled'],
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


def _build_espn_description(
    espn_match_id: str,
    home_team: str,
    away_team: str,
    competition: str,
    match_date: Optional[str] = None,
) -> str:
    """
    Build a factual match thread description from ESPN data.

    Fetches team records, standings positions, and h2h from ESPN.
    Returns a formatted string or a simple fallback if ESPN data is unavailable.

    Args:
        espn_match_id: ESPN event id
        home_team / away_team: display names used in the fallback
        competition: display name or ESPN league code
        match_date: optional YYYYMMDD string. Required for future fixtures
            since ESPN's default scoreboard only returns today's matches.
    """
    from app.utils.sync_espn_client import get_sync_espn_client

    fallback = f"{home_team} vs {away_team}"

    try:
        from app.utils.competition_mappings import resolve_league_code
        espn = get_sync_espn_client()
        comp_code = resolve_league_code(competition)

        # Get both team IDs from the ESPN event data (scoped to the match date
        # so the scoreboard actually contains a future/past fixture).
        competitors = espn.get_event_competitors(
            espn_match_id, comp_code, match_date=match_date
        )
        if not competitors:
            logger.warning(
                f"Could not fetch competitors for match {espn_match_id} "
                f"(league={comp_code}, date={match_date})"
            )
            _log_event(
                stage="espn_event", outcome="fallback",
                match_id=str(espn_match_id),
                message=f"Thread ESPN lookup: no competitors for {comp_code} date={match_date}; using bare fallback",
                context={"league": comp_code, "date": match_date},
            )
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
        _log_event(
            stage="espn_event", outcome="ok",
            match_id=str(espn_match_id),
            message=f"Thread ESPN description: {description[:160]}",
            context={"league": comp_code, "date": match_date},
        )
        return description

    except Exception as e:
        logger.warning(f"Error building ESPN description for match {espn_match_id}: {e}")
        _log_event(
            stage="espn_event", outcome="error",
            match_id=str(espn_match_id),
            message=f"Thread ESPN description error: {e}",
        )
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

            # Fetch factual ESPN data for thread description. Pass match_date
            # in ESPN's YYYYMMDD format so the scoreboard query actually
            # includes this future fixture (ESPN's default scoreboard only
            # returns same-day matches).
            match_date_str = utc_time.strftime('%Y%m%d')
            espn_description = _build_espn_description(
                match.match_id, home_team, away_team,
                match.competition or 'usa.1',
                match_date=match_date_str,
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
                    _log_event(
                        stage="ai", outcome="ok",
                        match_id=str(match.match_id),
                        message=f"Thread AI ok: {thread_description[:160]}",
                        context={"home": home_team, "away": away_team},
                    )
                else:
                    logger.info(
                        f"Match {match_id}: AI thread structuring empty/rejected, "
                        f"using raw ESPN description"
                    )
                    _log_event(
                        stage="ai", outcome="fallback",
                        match_id=str(match.match_id),
                        message="Thread AI rejected/empty — using raw ESPN description",
                        context={"home": home_team, "away": away_team},
                    )
            except Exception as ai_err:
                logger.warning(
                    f"Match {match_id}: AI thread structuring failed "
                    f"({ai_err}); using raw ESPN description"
                )
                _log_event(
                    stage="ai", outcome="error",
                    match_id=str(match.match_id),
                    message=f"Thread AI error: {ai_err}",
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
                _log_event(
                    stage="post", outcome="ok",
                    match_id=str(match.match_id),
                    message=f"Match thread created: {home_team} vs {away_team} (thread {thread_id})",
                    context={
                        "thread_id": str(thread_id),
                        "home": home_team, "away": away_team,
                    },
                )

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
                _log_event(
                    stage="post", outcome="error",
                    match_id=str(match.match_id),
                    message="Match thread creation: bot returned no thread id",
                )
                return {"success": False, "error": "No thread ID returned"}
        finally:
            # Release lock
            redis.delete(lock_key)

    except Exception as e:
        logger.error(f"Error creating MLS thread for match {match_id}: {e}")
        _log_event(
            stage="post", outcome="error",
            match_id=str(match_id),
            message=f"Match thread creation exception: {e}",
        )
        return {"success": False, "error": str(e)}


@celery_task(
    name='app.tasks.match_scheduler.post_match_lineups_task',
    queue='discord',
    max_retries=6,  # 6 retries × 5 min = covers up to 30 min waiting for ESPN
    default_retry_delay=300,
    soft_time_limit=30,
    time_limit=45
)
def post_match_lineups_task(self, session, match_id: int) -> Dict[str, Any]:
    """
    Post match lineups to the Discord thread.

    Fetches lineup data from ESPN summary API and posts a formatted embed
    showing starters and subs for both teams. Self-retries every 5min if
    ESPN hasn't published lineups yet (they typically appear 30-60min before
    kickoff but the exact timing varies). Gives up once the match has
    started, since pre-match lineup posts after kickoff are pointless.
    """
    from celery.exceptions import Retry
    try:
        from datetime import timezone
        from app.models.external import MLSMatch, MlsPostMarker
        from app.utils.espn_api_client import ESPNAPIClient
        from app.utils.discord_request_handler import send_to_discord_bot

        with task_session() as db_session:
            match = db_session.query(MLSMatch).filter_by(id=match_id).first()
            if not match:
                return {"success": False, "error": f"Match {match_id} not found"}

            # ── Fast idempotency gate: the denormalized flag means both sides
            # already posted. The per-side durable markers below are the real
            # arbiter and handle partial-completion; this just short-circuits. ──
            if match.lineups_posted:
                logger.info(f"Lineups already posted for match {match_id}, skipping")
                task = ScheduledTask.find_existing_task(db_session, match_id, TaskType.LINEUP_POST)
                if task:
                    task.mark_completed()
                    db_session.commit()
                return {"success": True, "message": "Lineups already posted", "already_posted": True}

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

            # Determine whether the match has already started — used to decide
            # if we should retry or give up on a no-lineups response.
            match_dt = match.date_time
            if match_dt and match_dt.tzinfo is None:
                match_dt = match_dt.replace(tzinfo=timezone.utc)
            match_started = match_dt and match_dt <= datetime.now(timezone.utc)

            if not lineups:
                attempt = (self.request.retries or 0) + 1
                task = ScheduledTask.find_existing_task(db_session, match_id, TaskType.LINEUP_POST)

                # If the match hasn't started yet AND we have retries left, wait
                # 5 more minutes and try again — ESPN often publishes lineups
                # closer to kickoff than the T-30 min default.
                if not match_started and self.request.retries < self.max_retries:
                    logger.info(
                        f"No lineup data yet for match {match_id} "
                        f"(attempt {attempt}/{self.max_retries + 1}), retrying in 5min"
                    )
                    if task:
                        task.last_error = f"Awaiting ESPN lineups (attempt {attempt})"
                        db_session.commit()
                    raise self.retry(countdown=300)

                # Match started or we exhausted retries — give up cleanly.
                reason = "match started before lineups published" if match_started else "no lineups after retries"
                logger.warning(f"Lineup post for match {match_id} abandoned: {reason}")
                if task:
                    task.mark_expired()
                    task.last_error = reason
                    db_session.commit()
                return {"success": False, "message": reason}

            # Post each side independently, tracked by its own durable marker
            # (`lineup:{id}:home` / `:away`). Per-side markers mean a retry
            # re-sends ONLY the side still missing — never the one already up —
            # so a partial failure (one team's send errored) self-heals without
            # duplicating the other. `needed` = sides ESPN actually gave us data
            # for; `done` = sides now confirmed posted (this run or a prior one).
            needed_sides = []
            done_sides = []
            for side in ('home', 'away'):
                team_data = lineups.get(side)
                if not team_data:
                    continue
                needed_sides.append(side)

                dedup_key = f"lineup:{match_id}:{side}"
                if MlsPostMarker.exists(db_session, dedup_key):
                    done_sides.append(side)
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
                    'timestamp': datetime.now(timezone.utc).isoformat(),
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
                    'match_data': {'match_id': str(match_id)},
                    'idempotency_key': dedup_key,
                }

                response = send_to_discord_bot('/api/live-reporting/event', request_data)
                if response and response.get('success'):
                    # Durable marker recorded only after a confirmed send.
                    MlsPostMarker.record(db_session, dedup_key, match_id, 'lineup')
                    done_sides.append(side)
                    logger.info(f"Posted {side} lineup for match {match_id}")
                else:
                    error_msg = response.get('error', 'Unknown') if response else 'No response'
                    logger.error(f"Failed to post {side} lineup: {error_msg}")

            task = ScheduledTask.find_existing_task(db_session, match_id, TaskType.LINEUP_POST)

            # All sides ESPN gave us are now posted → done.
            if needed_sides and set(done_sides) >= set(needed_sides):
                match.lineups_posted = True
                if task:
                    task.mark_completed()
                db_session.commit()
                return {"success": True, "message": f"Lineups posted ({', '.join(done_sides)})"}

            # A side is still missing (its send failed). Retry — the markers make
            # this re-send only the missing side, so it can't duplicate.
            missing = [s for s in needed_sides if s not in done_sides]
            if self.request.retries < self.max_retries:
                logger.warning(f"Lineup post incomplete for match {match_id} (missing {missing}), retrying in 2min")
                if task:
                    task.last_error = f"Awaiting Discord for lineup sides: {missing}"
                db_session.commit()
                raise self.retry(countdown=120)

            # Retries exhausted with a side still missing — leave the flag false
            # so the beat scheduler re-arms and keeps trying until kickoff.
            if task:
                task.mark_failed(f"Lineup sides still missing after retries: {missing}")
                db_session.commit()
            return {"success": False, "error": f"Lineup sides missing: {missing}"}

    except Retry:
        # Celery's retry mechanism — must propagate, not swallow
        raise
    except Exception as e:
        logger.error(f"Error posting lineups for match {match_id}: {e}")
        return {"success": False, "error": str(e)}


@celery_task(
    name='app.tasks.match_scheduler.post_match_buildup_task',
    queue='discord',
    max_retries=2,
    default_retry_delay=300,
    soft_time_limit=45,
    time_limit=60
)
def post_match_buildup_task(self, session, match_id: int) -> Dict[str, Any]:
    """
    Post a pre-match build-up to the Discord thread (default T-3h): team
    records/standing + last meeting (reuses _build_espn_description), recent
    form (WWLDW), venue, and a live kickoff countdown. Factual, no AI — fills
    the dead air between thread creation (T-48h) and lineups (T-30m).
    """
    from celery.exceptions import Retry
    try:
        from datetime import timezone
        from zoneinfo import ZoneInfo
        from app.models.external import MLSMatch, MlsPostMarker
        from app.utils.espn_api_client import ESPNAPIClient
        from app.utils.competition_mappings import resolve_league_code
        from app.utils.discord_request_handler import send_to_discord_bot

        with task_session() as db_session:
            match = db_session.query(MLSMatch).filter_by(id=match_id).first()
            if not match:
                return {"success": False, "error": f"Match {match_id} not found"}

            # ── Idempotency guard: durable flag survives any scheduler/session
            # rollback, so duplicate dispatches can never double-post. ──
            if match.buildup_posted:
                logger.info(f"Build-up already posted for match {match_id}, skipping")
                task = ScheduledTask.find_existing_task(db_session, match_id, TaskType.BUILDUP_POST)
                if task:
                    task.mark_completed()
                    db_session.commit()
                return {"success": True, "message": "Build-up already posted", "already_posted": True}

            thread_id = match.discord_thread_id
            if not thread_id:
                logger.warning(f"No Discord thread for match {match_id}, skipping build-up post")
                return {"success": False, "error": "No Discord thread"}

            home_team = 'Seattle Sounders FC' if match.is_home_game else match.opponent
            away_team = match.opponent if match.is_home_game else 'Seattle Sounders FC'
            espn_id = str(match.espn_match_id or match.match_id)
            competition = match.competition or 'MLS'
            league_code = resolve_league_code(competition)

            match_dt = match.date_time
            if match_dt and match_dt.tzinfo is None:
                match_dt = match_dt.replace(tzinfo=timezone.utc)
            match_date_str = match_dt.astimezone(ZoneInfo('UTC')).strftime('%Y%m%d') if match_dt else None

            # Records / standing / H2H (reuses the thread-description builder)
            espn_description = _build_espn_description(
                match.match_id, home_team, away_team, competition, match_date=match_date_str
            )

            # Recent form + venue (best-effort; don't fail the post if unavailable)
            home_form = away_form = ''
            venue = match.venue or ''
            try:
                data = ESPNAPIClient().get_match_data(espn_id, league_code)
                if data:
                    home_form = data.get('home_form', '') or ''
                    away_form = data.get('away_form', '') or ''
                    venue = venue or data.get('venue', '')
            except Exception as form_err:
                logger.info(f"Build-up: form lookup failed for match {match_id}: {form_err}")

            def _fmt_form(f):
                return ' '.join(list(f)) if f else ''

            fields = []
            if home_form or away_form:
                lines = []
                if home_form:
                    lines.append(f"{home_team}: {_fmt_form(home_form)}")
                if away_form:
                    lines.append(f"{away_team}: {_fmt_form(away_form)}")
                fields.append({'name': 'Recent Form', 'value': '\n'.join(lines), 'inline': False})
            if venue:
                fields.append({'name': 'Venue', 'value': str(venue)[:1024], 'inline': True})
            fields.append({'name': 'Competition', 'value': str(competition)[:1024], 'inline': True})
            if match_dt:
                unix = int(match_dt.timestamp())
                fields.append({'name': 'Kickoff', 'value': f"<t:{unix}:F> (<t:{unix}:R>)", 'inline': False})

            embed = {
                'title': 'Matchday Build-Up',
                'description': espn_description,
                'color': 0x005F4F,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'footer': {'text': f'{home_team} vs {away_team}'},
                'fields': fields,
            }

            # Stable idempotency key: the bot dedupes concurrent/redelivered
            # sends on (thread_id, key); the durable marker below is the
            # cross-restart backstop. Together they guarantee at-most-once.
            dedup_key = f"buildup:{match_id}"

            # Durable dedup: if a marker already exists this build-up posted on a
            # prior attempt (that we may have crashed before recording the flag).
            if MlsPostMarker.exists(db_session, dedup_key):
                logger.info(f"Build-up marker present for match {match_id}, skipping")
                match.buildup_posted = True
                task = ScheduledTask.find_existing_task(db_session, match_id, TaskType.BUILDUP_POST)
                if task:
                    task.mark_completed()
                db_session.commit()
                return {"success": True, "message": "Build-up already posted", "already_posted": True}

            request_data = {
                'thread_id': thread_id,
                'event_type': 'buildup',
                'content': f"{home_team} vs {away_team}",
                'embed': embed,
                'match_data': {'match_id': str(match_id)},
                'idempotency_key': dedup_key,
            }

            response = send_to_discord_bot('/api/live-reporting/event', request_data)
            task = ScheduledTask.find_existing_task(db_session, match_id, TaskType.BUILDUP_POST)
            if response and response.get('success'):
                logger.info(f"Posted build-up for match {match_id}")
                # Record the durable marker FIRST (its own commit), then the
                # denormalized flag — order chosen so a crash can't leave a
                # posted-but-unmarked state that would re-post.
                MlsPostMarker.record(db_session, dedup_key, match_id, 'buildup')
                match.buildup_posted = True
                if task:
                    task.mark_completed()
                db_session.commit()
                return {"success": True, "message": "Build-up posted"}

            # Nothing landed in Discord — retry. Safe because no embed posted
            # (and if one somehow did, the marker/idempotency key dedupes it).
            error_msg = response.get('error', 'Unknown') if response else 'No response'
            logger.error(f"Failed to post build-up for match {match_id}: {error_msg}")
            if self.request.retries < self.max_retries:
                logger.warning(f"Retrying build-up post for match {match_id} in 2min")
                raise self.retry(countdown=120)
            if task:
                task.mark_failed(error_msg)
                db_session.commit()
            return {"success": False, "error": error_msg}

    except Retry:
        # Celery's retry mechanism — must propagate, not swallow
        raise
    except Exception as e:
        logger.error(f"Error posting build-up for match {match_id}: {e}")
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