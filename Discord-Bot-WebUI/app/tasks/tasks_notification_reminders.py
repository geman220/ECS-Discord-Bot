# app/tasks/tasks_notification_reminders.py

"""
Automated Notification Reminder Tasks
=====================================

Celery tasks for automated RSVP and match reminders using the
unified NotificationOrchestrator.

Tasks:
- send_rsvp_reminders: Send RSVP reminders for upcoming matches
- send_match_reminders: Send match reminders (day before, 2 hours before)
- process_notification_queue: Process any queued notifications

Schedule (via celery beat):
- RSVP reminders: Daily at 9 AM for matches in next 3-5 days
- Match reminders: Daily at 6 PM for next-day matches
- Same-day reminders: Hourly check for matches in next 2-4 hours
"""

import logging
from datetime import datetime, timedelta
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_rsvp_reminders(self):
    """
    Send RSVP reminders for upcoming matches.

    Targets players who haven't responded to RSVP for matches
    happening in 3-5 days.

    Run daily at 9 AM via celery beat.
    """
    from app import create_app
    from app.core import db
    from app.models import Match, Team, Player, Availability, User
    from app.services.notification_orchestrator import orchestrator
    from datetime import date

    app = create_app()
    with app.app_context():
        try:
            today = date.today()
            reminder_start = today + timedelta(days=3)
            reminder_end = today + timedelta(days=5)

            # Get matches in the reminder window
            matches = Match.query.filter(
                Match.date >= reminder_start,
                Match.date <= reminder_end,
                Match.is_special_week == False,  # Skip BYE/FUN weeks
                Match.week_type.in_(['REGULAR', 'PLAYOFF'])
            ).all()

            logger.info(f"Found {len(matches)} matches for RSVP reminders")

            total_reminders = 0

            for match in matches:
                # Get players who haven't responded
                non_responders = _get_non_responding_players(match)

                if not non_responders:
                    continue

                user_ids = [u.id for u in non_responders if u.id]
                if not user_ids:
                    continue

                # Get opponent name
                opponent = match.away_team.name if match.home_team else match.home_team.name
                match_date = match.date.strftime('%A, %B %d')
                days_until = (match.date - today).days

                result = orchestrator.send_rsvp_reminder(
                    match_id=match.id,
                    user_ids=user_ids,
                    opponent=opponent,
                    match_date=match_date,
                    days_until=days_until
                )

                total_reminders += result['in_app']['created']
                logger.info(
                    f"RSVP reminder for match {match.id}: "
                    f"{result['in_app']['created']} in-app, {result['push']['success']} push"
                )

            logger.info(f"RSVP reminders complete: {total_reminders} total notifications sent")
            return {'success': True, 'total_reminders': total_reminders}

        except Exception as e:
            logger.error(f"Error in send_rsvp_reminders: {e}", exc_info=True)
            raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_match_reminders_daily(self):
    """
    Send match reminders for tomorrow's matches.

    Targets all players on teams with matches tomorrow.
    Run daily at 6 PM via celery beat.
    """
    from app import create_app
    from app.core import db
    from app.models import Match, Team, Player, User
    from app.services.notification_orchestrator import orchestrator
    from datetime import date

    app = create_app()
    with app.app_context():
        try:
            tomorrow = date.today() + timedelta(days=1)

            # Get tomorrow's matches
            matches = Match.query.filter(
                Match.date == tomorrow,
                Match.is_special_week == False,
                Match.week_type.in_(['REGULAR', 'PLAYOFF'])
            ).all()

            logger.info(f"Found {len(matches)} matches for tomorrow reminders")

            total_reminders = 0

            for match in matches:
                # Get all players from both teams
                home_players = _get_team_players_with_users(match.home_team)
                away_players = _get_team_players_with_users(match.away_team)

                # Send to home team
                if home_players:
                    home_user_ids = [p.user.id for p in home_players if p.user]
                    if home_user_ids:
                        result = orchestrator.send_match_reminder(
                            match_id=match.id,
                            user_ids=home_user_ids,
                            opponent=match.away_team.name,
                            match_time=match.time.strftime('%I:%M %p') if match.time else 'TBD',
                            location=match.location or 'TBD',
                            hours_until=24
                        )
                        total_reminders += result['in_app']['created']

                # Send to away team
                if away_players:
                    away_user_ids = [p.user.id for p in away_players if p.user]
                    if away_user_ids:
                        result = orchestrator.send_match_reminder(
                            match_id=match.id,
                            user_ids=away_user_ids,
                            opponent=match.home_team.name,
                            match_time=match.time.strftime('%I:%M %p') if match.time else 'TBD',
                            location=match.location or 'TBD',
                            hours_until=24
                        )
                        total_reminders += result['in_app']['created']

            logger.info(f"Daily match reminders complete: {total_reminders} notifications sent")
            return {'success': True, 'total_reminders': total_reminders}

        except Exception as e:
            logger.error(f"Error in send_match_reminders_daily: {e}", exc_info=True)
            raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def send_match_reminders_urgent(self):
    """
    Send urgent match reminders for matches starting in 2-4 hours.

    High-priority reminders for same-day matches.
    Run hourly via celery beat.
    """
    from app import create_app
    from app.core import db
    from app.models import Match, Team, Player
    from app.services.notification_orchestrator import orchestrator
    from datetime import date

    app = create_app()
    with app.app_context():
        try:
            now = datetime.utcnow()
            today = date.today()

            # Get today's matches
            matches = Match.query.filter(
                Match.date == today,
                Match.is_special_week == False
            ).all()

            total_reminders = 0

            for match in matches:
                # Calculate hours until match
                if not match.time:
                    continue

                match_datetime = datetime.combine(match.date, match.time)
                hours_until = (match_datetime - now).total_seconds() / 3600

                # Only send for matches 2-4 hours away
                if not (2 <= hours_until <= 4):
                    continue

                hours_until_int = int(hours_until)

                # Get all players from both teams
                home_players = _get_team_players_with_users(match.home_team)
                away_players = _get_team_players_with_users(match.away_team)

                # Send to home team
                if home_players:
                    home_user_ids = [p.user.id for p in home_players if p.user]
                    if home_user_ids:
                        result = orchestrator.send_match_reminder(
                            match_id=match.id,
                            user_ids=home_user_ids,
                            opponent=match.away_team.name,
                            match_time=match.time.strftime('%I:%M %p') if match.time else 'TBD',
                            location=match.location or 'TBD',
                            hours_until=hours_until_int
                        )
                        total_reminders += result['in_app']['created']

                # Send to away team
                if away_players:
                    away_user_ids = [p.user.id for p in away_players if p.user]
                    if away_user_ids:
                        result = orchestrator.send_match_reminder(
                            match_id=match.id,
                            user_ids=away_user_ids,
                            opponent=match.home_team.name,
                            match_time=match.time.strftime('%I:%M %p') if match.time else 'TBD',
                            location=match.location or 'TBD',
                            hours_until=hours_until_int
                        )
                        total_reminders += result['in_app']['created']

            logger.info(f"Urgent match reminders complete: {total_reminders} notifications sent")
            return {'success': True, 'total_reminders': total_reminders}

        except Exception as e:
            logger.error(f"Error in send_match_reminders_urgent: {e}", exc_info=True)
            raise self.retry(exc=e)


def _get_non_responding_players(match):
    """Get users who haven't RSVPed for a match."""
    from app.models import Availability, Player, User

    # Get all player IDs who have responded
    responded_player_ids = set(
        a.player_id for a in match.availability
        if a.player_id and a.response in ('yes', 'no', 'maybe')
    )

    # Get players from both teams
    home_players = match.home_team.players if match.home_team else []
    away_players = match.away_team.players if match.away_team else []
    all_players = list(home_players) + list(away_players)

    # Filter to those who haven't responded and have user accounts
    non_responders = []
    for player in all_players:
        if player.id not in responded_player_ids and player.user:
            non_responders.append(player.user)

    return non_responders


def _get_team_players_with_users(team):
    """Get players from a team who have linked user accounts."""
    if not team or not team.players:
        return []
    return [p for p in team.players if p.user]


# ============================================================================
# MANUAL TRIGGER TASKS (for admin use)
# ============================================================================

@shared_task(bind=True)
def send_match_reminder_for_match(self, match_id: int, hours_until: int = 24):
    """
    Manually trigger match reminder for a specific match.

    Args:
        match_id: The match ID
        hours_until: Hours until match (for message customization)
    """
    from app import create_app
    from app.core import db
    from app.models import Match
    from app.services.notification_orchestrator import orchestrator

    app = create_app()
    with app.app_context():
        try:
            match = Match.query.get(match_id)
            if not match:
                logger.error(f"Match {match_id} not found")
                return {'success': False, 'error': 'Match not found'}

            results = []

            # Send to home team
            home_players = _get_team_players_with_users(match.home_team)
            if home_players:
                home_user_ids = [p.user.id for p in home_players if p.user]
                if home_user_ids:
                    result = orchestrator.send_match_reminder(
                        match_id=match.id,
                        user_ids=home_user_ids,
                        opponent=match.away_team.name,
                        match_time=match.time.strftime('%I:%M %p') if match.time else 'TBD',
                        location=match.location or 'TBD',
                        hours_until=hours_until
                    )
                    results.append({'team': 'home', **result})

            # Send to away team
            away_players = _get_team_players_with_users(match.away_team)
            if away_players:
                away_user_ids = [p.user.id for p in away_players if p.user]
                if away_user_ids:
                    result = orchestrator.send_match_reminder(
                        match_id=match.id,
                        user_ids=away_user_ids,
                        opponent=match.home_team.name,
                        match_time=match.time.strftime('%I:%M %p') if match.time else 'TBD',
                        location=match.location or 'TBD',
                        hours_until=hours_until
                    )
                    results.append({'team': 'away', **result})

            return {'success': True, 'results': results}

        except Exception as e:
            logger.error(f"Error sending match reminder for {match_id}: {e}")
            return {'success': False, 'error': str(e)}


@shared_task(bind=True)
def send_rsvp_reminder_for_match(self, match_id: int):
    """
    Manually trigger RSVP reminder for a specific match.

    Args:
        match_id: The match ID
    """
    from app import create_app
    from app.core import db
    from app.models import Match
    from app.services.notification_orchestrator import orchestrator
    from datetime import date

    app = create_app()
    with app.app_context():
        try:
            match = Match.query.get(match_id)
            if not match:
                logger.error(f"Match {match_id} not found")
                return {'success': False, 'error': 'Match not found'}

            non_responders = _get_non_responding_players(match)
            if not non_responders:
                return {'success': True, 'message': 'All players have responded'}

            user_ids = [u.id for u in non_responders if u.id]
            if not user_ids:
                return {'success': True, 'message': 'No users to notify'}

            opponent = match.away_team.name if match.home_team else match.home_team.name
            match_date = match.date.strftime('%A, %B %d')
            days_until = (match.date - date.today()).days

            result = orchestrator.send_rsvp_reminder(
                match_id=match.id,
                user_ids=user_ids,
                opponent=opponent,
                match_date=match_date,
                days_until=days_until
            )

            return {'success': True, **result}

        except Exception as e:
            logger.error(f"Error sending RSVP reminder for {match_id}: {e}")
            return {'success': False, 'error': str(e)}


# ============================================================================
# LEAGUE EVENT REMINDERS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_league_event_reminders(self, days_ahead: int = 2, event_types: list = None):
    """
    Send Discord reminders for upcoming league events.

    Posts reminders to the announcements channel for events happening
    in the next few days. Particularly useful for PLOP reminders on Fridays.

    Args:
        days_ahead: Number of days to look ahead (default: 2 for Fri->Sun)
        event_types: List of event types to remind about (default: all)

    Run Friday at 5 PM for weekend PLOP reminders.
    """
    import asyncio
    from app import create_app
    from app.models.calendar import LeagueEvent
    from app.services.discord_service import get_discord_service
    from datetime import date

    app = create_app()
    with app.app_context():
        try:
            today = date.today()
            reminder_end = today + timedelta(days=days_ahead)

            # Query upcoming events
            query = LeagueEvent.query.filter(
                LeagueEvent.is_active == True,
                LeagueEvent.start_datetime >= datetime.combine(today, datetime.min.time()),
                LeagueEvent.start_datetime <= datetime.combine(reminder_end, datetime.max.time())
            )

            if event_types:
                query = query.filter(LeagueEvent.event_type.in_(event_types))

            events = query.order_by(LeagueEvent.start_datetime).all()

            logger.info(f"Found {len(events)} upcoming events for reminders")

            if not events:
                return {'success': True, 'message': 'No upcoming events', 'count': 0}

            # Group events by type for cleaner announcements
            events_by_type = {}
            for event in events:
                event_type = event.event_type or 'other'
                if event_type not in events_by_type:
                    events_by_type[event_type] = []
                events_by_type[event_type].append(event)

            # Post reminders to Discord
            discord_service = get_discord_service()
            posted_count = 0

            for event_type, type_events in events_by_type.items():
                for event in type_events:
                    try:
                        # Format reminder message
                        event_date = event.start_datetime
                        day_name = event_date.strftime('%A')
                        date_str = event_date.strftime('%B %d')
                        time_str = event_date.strftime('%I:%M %p').lstrip('0')

                        # Build reminder embed
                        result = asyncio.run(
                            discord_service.post_event_reminder(
                                title=event.title,
                                event_type=event.event_type,
                                date_str=f"{day_name}, {date_str}",
                                time_str=time_str,
                                location=event.location,
                                description=event.description
                            )
                        )

                        if result:
                            posted_count += 1
                            logger.info(f"Posted reminder for {event.title} on {date_str}")

                    except Exception as e:
                        logger.error(f"Error posting reminder for event {event.id}: {e}")

            logger.info(f"League event reminders complete: {posted_count} reminders posted")
            return {'success': True, 'count': posted_count, 'events': len(events)}

        except Exception as e:
            logger.error(f"Error in send_league_event_reminders: {e}", exc_info=True)
            raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_dynamic_event_reminders(self):
    """
    Send Discord reminders for league events based on each event's settings.

    This task is DYNAMIC - it checks each event's `reminder_days_before` setting
    to determine when to send the reminder. Each event only gets ONE reminder.

    Logic:
    - Find events where send_reminder=True and reminder_sent_at is NULL
    - For each event, check if today >= (event_date - reminder_days_before)
    - If so, send reminder and mark reminder_sent_at

    Examples:
    - Party on Jan 15 with reminder_days_before=2: reminded on Jan 13
    - PLOP on Feb 22 with reminder_days_before=2: reminded on Feb 20
    - Meeting on Mar 5 with reminder_days_before=1: reminded on Mar 4

    Run hourly to catch events at the right time.
    """
    import asyncio
    from app import create_app
    from app.core import db
    from app.models.calendar import LeagueEvent
    from app.services.discord_service import get_discord_service
    from datetime import date
    from sqlalchemy import func

    app = create_app()
    with app.app_context():
        try:
            today = date.today()
            now = datetime.utcnow()

            # Find events that:
            # 1. Are active
            # 2. Have send_reminder enabled
            # 3. Haven't been reminded yet (reminder_sent_at IS NULL)
            # 4. Haven't happened yet (start_datetime >= today)
            # 5. Are within their reminder window
            events_needing_reminder = LeagueEvent.query.filter(
                LeagueEvent.is_active == True,
                LeagueEvent.send_reminder == True,
                LeagueEvent.reminder_sent_at.is_(None),
                LeagueEvent.start_datetime >= datetime.combine(today, datetime.min.time())
            ).all()

            logger.info(f"Checking {len(events_needing_reminder)} events for reminder eligibility")

            if not events_needing_reminder:
                return {'success': True, 'message': 'No events need reminders', 'count': 0}

            discord_service = get_discord_service()
            posted_count = 0
            checked_count = 0

            for event in events_needing_reminder:
                try:
                    # Calculate when reminder should be sent
                    event_date = event.start_datetime.date()
                    days_before = event.reminder_days_before or 2
                    reminder_date = event_date - timedelta(days=days_before)

                    # Check if it's time to remind (today >= reminder_date)
                    if today < reminder_date:
                        # Not time yet for this event
                        continue

                    checked_count += 1
                    event_datetime = event.start_datetime
                    day_name = event_datetime.strftime('%A')
                    date_str = event_datetime.strftime('%B %d')
                    time_str = event_datetime.strftime('%I:%M %p').lstrip('0')
                    end_time_str = ''
                    if event.end_datetime:
                        end_time_str = event.end_datetime.strftime('%I:%M %p').lstrip('0')

                    # Use PLOP-specific format for PLOP events
                    if event.event_type == 'plop':
                        result = asyncio.run(
                            discord_service.post_plop_reminder(
                                date_str=f"{day_name}, {date_str}",
                                time_str=time_str,
                                end_time_str=end_time_str,
                                location=event.location or 'TBD'
                            )
                        )
                    else:
                        # Generic event reminder
                        result = asyncio.run(
                            discord_service.post_event_reminder(
                                title=event.title,
                                event_type=event.event_type,
                                date_str=f"{day_name}, {date_str}",
                                time_str=time_str,
                                location=event.location,
                                description=event.description
                            )
                        )

                    if result:
                        # Mark as reminded so we don't remind again
                        event.reminder_sent_at = now
                        db.session.add(event)
                        posted_count += 1
                        logger.info(f"Posted reminder for '{event.title}' on {date_str} (event on {event_date})")

                except Exception as e:
                    logger.error(f"Error posting reminder for event {event.id}: {e}")

            # Commit all reminder_sent_at updates
            if posted_count > 0:
                db.session.commit()

            logger.info(f"Dynamic event reminders complete: {posted_count} posted, {checked_count} checked")
            return {
                'success': True,
                'posted_count': posted_count,
                'checked_count': checked_count,
                'total_pending': len(events_needing_reminder)
            }

        except Exception as e:
            logger.error(f"Error in send_dynamic_event_reminders: {e}", exc_info=True)
            db.session.rollback()
            raise self.retry(exc=e)
