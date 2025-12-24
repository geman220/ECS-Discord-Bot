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
