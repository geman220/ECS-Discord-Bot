# app/tasks/tasks_notification_reminders.py

"""
Automated Notification Reminder Tasks
=====================================

Celery tasks for automated RSVP and match reminders using the
unified NotificationOrchestrator.

Tasks:
- send_rsvp_reminders: Legacy RSVP reminder window task (may be unused)
- send_match_reminders_daily: Day-before digest (one DM per player per day,
  even if they have multiple matches). Yes responders get a confirmation;
  non-responders get an RSVP chase. Maybe and No responders are skipped.

Schedule (via celery beat):
- Match reminders: Daily at 6 PM Pacific for next-day matches

Timezone note: all date math uses `pacific_today()` / `pacific_now()` from
`app.utils.pacific_time`. The league is local to Seattle — Pacific is the
only timezone that matters. See that module for why naive `date.today()`
misbehaves inside our UTC containers.
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from app.decorators import celery_task
from app.utils.pacific_time import pacific_now, pacific_today, pacific_datetime

logger = logging.getLogger(__name__)


@celery_task(max_retries=3, default_retry_delay=300)
def send_rsvp_reminders(self, session):
    """
    Send RSVP reminders for upcoming matches.

    Targets players who haven't responded to RSVP for matches
    happening in 3-5 days.

    Run daily at 9 AM Pacific via celery beat.
    """
    from app.models import Match
    from app.services.notification_orchestrator import orchestrator

    try:
        today = pacific_today()
        reminder_start = today + timedelta(days=3)
        reminder_end = today + timedelta(days=5)

        matches = session.query(Match).filter(
            Match.date >= reminder_start,
            Match.date <= reminder_end,
            Match.is_special_week == False,
            Match.week_type.in_(['REGULAR', 'PLAYOFF'])
        ).all()

        logger.info(f"Found {len(matches)} matches for RSVP reminders")

        total_reminders = 0

        for match in matches:
            non_responders = _get_non_responding_players(match)
            if not non_responders:
                continue

            user_ids = [u.id for u in non_responders if u.id]
            if not user_ids:
                continue

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


@celery_task(max_retries=3, default_retry_delay=300)
def send_match_reminders_daily(self, session):
    """
    Send one consolidated DM per player covering every match they have tomorrow.

    Audience and tone depend on RSVP state per-match:
      - Responded 'yes'            -> confirmation ("see you there")
      - No response                -> chase ("please RSVP or tell your coach")
      - Responded 'no' or 'maybe'  -> skipped

    A player with two matches tomorrow gets ONE DM listing both. If some are
    confirmed and some are unanswered, the DM mixes both.

    - Skips players who have already received this reminder (MatchReminderLog dedup)
    - Orchestrator enforces per-user preferences (match_reminder_notifications)

    Run daily at 6 PM Pacific via celery beat.
    """
    from app.models import Match, EcsFcMatch
    from app.models.communication import MatchReminderLog
    from app.services.notification_orchestrator import orchestrator

    try:
        target_date = pacific_today() + timedelta(days=1)
        batch_id = str(uuid.uuid4())

        pub_matches = session.query(Match).filter(
            Match.date == target_date,
            Match.is_special_week == False,
            Match.week_type.in_(['REGULAR', 'PLAYOFF'])
        ).all()

        ecs_fc_matches = session.query(EcsFcMatch).filter(
            EcsFcMatch.match_date == target_date,
            EcsFcMatch.status == 'SCHEDULED'
        ).all()

        logger.info(
            f"Daily match reminder for {target_date}: "
            f"{len(pub_matches)} pub + {len(ecs_fc_matches)} ECS FC matches"
        )

        # Group match summaries by user_id. Each entry is a full roster-player
        # view of the match annotated with their RSVP status.
        user_digests = defaultdict(list)

        for match in pub_matches:
            responses = _get_rsvp_responses(match, 'pub')
            if match.home_team:
                for player in match.home_team.players:
                    if not player.user:
                        continue
                    status = _reminder_audience_status(responses.get(player.id))
                    if status is None:
                        continue
                    info = _pub_match_info(
                        match, opponent=match.away_team.name if match.away_team else 'TBD'
                    )
                    info['rsvp_status'] = status
                    user_digests[player.user.id].append(info)
            if match.away_team:
                for player in match.away_team.players:
                    if not player.user:
                        continue
                    status = _reminder_audience_status(responses.get(player.id))
                    if status is None:
                        continue
                    info = _pub_match_info(
                        match, opponent=match.home_team.name if match.home_team else 'TBD'
                    )
                    info['rsvp_status'] = status
                    user_digests[player.user.id].append(info)

        for ecs_match in ecs_fc_matches:
            responses = _get_rsvp_responses(ecs_match, 'ecs_fc')
            if not ecs_match.team:
                continue
            for player in ecs_match.team.players:
                if not player.user:
                    continue
                status = _reminder_audience_status(responses.get(player.id))
                if status is None:
                    continue
                info = _ecs_fc_match_info(ecs_match)
                info['rsvp_status'] = status
                user_digests[player.user.id].append(info)

        if not user_digests:
            logger.info("No eligible players for daily match reminder")
            return {'success': True, 'total_reminders': 0, 'batch_id': batch_id}

        # Dedup against the audit log at (user, match) granularity — rerunning
        # the task (e.g., retry, manual trigger) won't double-DM.
        already_sent = _get_already_reminded(
            session, target_date, list(user_digests.keys()), reminder_type='daily'
        )

        sent_count = 0
        skipped_dedup = 0

        for user_id, matches in user_digests.items():
            matches = [
                m for m in matches
                if (user_id, m['match_id'], m['match_type']) not in already_sent
            ]
            if not matches:
                skipped_dedup += 1
                continue

            matches.sort(key=lambda m: m['time_sort'])

            result = orchestrator.send_match_reminders_digest(
                user_id=user_id,
                matches=matches,
                target_date=target_date,
            )

            delivered = (
                result['push']['success'] > 0 or
                result['discord']['success'] > 0 or
                result['email']['success'] > 0 or
                result['in_app']['created'] > 0
            )
            status = 'sent' if delivered else 'failed'
            for m in matches:
                session.add(MatchReminderLog(
                    user_id=user_id,
                    match_id=m['match_id'],
                    match_type=m['match_type'],
                    reminder_type='daily',
                    target_date=target_date,
                    delivery_status=status,
                    batch_id=batch_id,
                ))

            if delivered:
                sent_count += 1

        logger.info(
            f"Daily match reminders complete: {sent_count} players notified, "
            f"{skipped_dedup} skipped (already reminded), batch_id={batch_id}"
        )
        return {
            'success': True,
            'total_reminders': sent_count,
            'skipped_dedup': skipped_dedup,
            'batch_id': batch_id,
        }

    except Exception as e:
        logger.error(f"Error in send_match_reminders_daily: {e}", exc_info=True)
        raise self.retry(exc=e)


# ============================================================================
# Per-match info builders — these produce the dicts consumed by the
# orchestrator's send_match_reminders_digest.
# ============================================================================

def _pub_match_info(match, opponent: str) -> dict:
    return {
        'match_id': match.id,
        'match_type': 'pub',
        'opponent': opponent,
        'time_sort': match.time,  # time object for sort key
        'time_str': match.time.strftime('%I:%M %p').lstrip('0') if match.time else 'TBD',
        'location': match.location or 'TBD',
    }


def _ecs_fc_match_info(match) -> dict:
    return {
        'match_id': match.id,
        'match_type': 'ecs_fc',
        'opponent': match.opponent_name or 'TBD',
        'time_sort': match.match_time,
        'time_str': match.match_time.strftime('%I:%M %p').lstrip('0') if match.match_time else 'TBD',
        'location': match.location or 'TBD',
    }


def _get_rsvp_responses(match, match_type: str) -> dict:
    """Return {player_id: response_string} for all RSVP rows on this match."""
    availability = match.availability if match_type == 'pub' else match.availabilities
    return {
        a.player_id: a.response
        for a in (availability or [])
        if a.player_id
    }


def _reminder_audience_status(response):
    """
    Map an RSVP response to the reminder audience bucket, or None to skip.

    - None (no row) or 'no_response' -> 'no_response' (chase them)
    - 'yes'                          -> 'yes'         (confirm)
    - 'no' / 'maybe' / anything else -> None           (skip)
    """
    if response == 'yes':
        return 'yes'
    if response in (None, '', 'no_response'):
        return 'no_response'
    return None


def _get_already_reminded(session, target_date, user_ids, reminder_type: str) -> set:
    """Return set of (user_id, match_id, match_type) already logged as sent."""
    from app.models.communication import MatchReminderLog
    if not user_ids:
        return set()
    rows = session.query(
        MatchReminderLog.user_id,
        MatchReminderLog.match_id,
        MatchReminderLog.match_type,
    ).filter(
        MatchReminderLog.user_id.in_(user_ids),
        MatchReminderLog.target_date == target_date,
        MatchReminderLog.reminder_type == reminder_type,
        MatchReminderLog.delivery_status == 'sent',
    ).all()
    return {(r.user_id, r.match_id, r.match_type) for r in rows}


def _get_non_responding_players(match):
    """Get users who haven't RSVPed for a match."""
    responded_player_ids = set(
        a.player_id for a in match.availability
        if a.player_id and a.response in ('yes', 'no', 'maybe')
    )

    home_players = match.home_team.players if match.home_team else []
    away_players = match.away_team.players if match.away_team else []
    all_players = list(home_players) + list(away_players)

    non_responders = []
    for player in all_players:
        if player.id not in responded_player_ids and player.user:
            non_responders.append(player.user)

    return non_responders


# ============================================================================
# MANUAL TRIGGER TASKS (for admin use)
# ============================================================================

@celery_task()
def send_match_reminder_for_match(self, session, match_id: int, match_type: str = 'pub'):
    """
    Manually trigger a match reminder for a single match. Sends one DM per
    eligible player (yes responders get confirmation, no-responders get a
    chase). Maybe and No responders are skipped.

    Args:
        match_id: The match ID
        match_type: 'pub' for pub-league Match, 'ecs_fc' for EcsFcMatch
    """
    from app.models import Match, EcsFcMatch
    from app.models.communication import MatchReminderLog
    from app.services.notification_orchestrator import orchestrator

    try:
        batch_id = str(uuid.uuid4())

        if match_type == 'ecs_fc':
            match = session.query(EcsFcMatch).get(match_id)
            if not match:
                return {'success': False, 'error': 'EcsFcMatch not found'}
            target_date = match.match_date
            responses = _get_rsvp_responses(match, 'ecs_fc')
            roster = [(p, _ecs_fc_match_info(match))
                      for p in (match.team.players if match.team else [])]
        else:
            match = session.query(Match).get(match_id)
            if not match:
                return {'success': False, 'error': 'Match not found'}
            target_date = match.date
            responses = _get_rsvp_responses(match, 'pub')
            roster = []
            if match.home_team:
                roster.extend(
                    (p, _pub_match_info(match, opponent=match.away_team.name if match.away_team else 'TBD'))
                    for p in match.home_team.players
                )
            if match.away_team:
                roster.extend(
                    (p, _pub_match_info(match, opponent=match.home_team.name if match.home_team else 'TBD'))
                    for p in match.away_team.players
                )

        sent = 0
        for player, info in roster:
            if not player.user:
                continue
            status = _reminder_audience_status(responses.get(player.id))
            if status is None:
                continue
            info = {**info, 'rsvp_status': status}

            result = orchestrator.send_match_reminders_digest(
                user_id=player.user.id,
                matches=[info],
                target_date=target_date,
            )
            delivered = (
                result['push']['success'] > 0 or
                result['discord']['success'] > 0 or
                result['email']['success'] > 0 or
                result['in_app']['created'] > 0
            )
            session.add(MatchReminderLog(
                user_id=player.user.id,
                match_id=info['match_id'],
                match_type=info['match_type'],
                reminder_type='manual',
                target_date=target_date,
                delivery_status='sent' if delivered else 'failed',
                batch_id=batch_id,
            ))
            if delivered:
                sent += 1

        return {'success': True, 'sent': sent, 'batch_id': batch_id}

    except Exception as e:
        logger.error(f"Error sending match reminder for {match_id}: {e}")
        return {'success': False, 'error': str(e)}


@celery_task()
def send_rsvp_reminder_for_match(self, session, match_id: int):
    """Manually trigger RSVP reminder for a specific pub-league match."""
    from app.models import Match
    from app.services.notification_orchestrator import orchestrator

    try:
        match = session.query(Match).get(match_id)
        if not match:
            return {'success': False, 'error': 'Match not found'}

        non_responders = _get_non_responding_players(match)
        if not non_responders:
            return {'success': True, 'message': 'All players have responded'}

        user_ids = [u.id for u in non_responders if u.id]
        if not user_ids:
            return {'success': True, 'message': 'No users to notify'}

        opponent = match.away_team.name if match.home_team else match.home_team.name
        match_date = match.date.strftime('%A, %B %d')
        days_until = (match.date - pacific_today()).days

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

@celery_task(max_retries=3, default_retry_delay=300)
def send_league_event_reminders(self, session, days_ahead: int = 2, event_types: list = None):
    """
    Send Discord reminders for upcoming league events.

    Run Friday at 5 PM Pacific for weekend PLOP reminders.
    """
    import asyncio
    from app.models.calendar import LeagueEvent
    from app.services.discord_service import get_discord_service

    try:
        today = pacific_today()
        reminder_end = today + timedelta(days=days_ahead)

        query = session.query(LeagueEvent).filter(
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

        events_by_type = {}
        for event in events:
            event_type = event.event_type or 'other'
            events_by_type.setdefault(event_type, []).append(event)

        discord_service = get_discord_service()
        posted_count = 0

        for event_type, type_events in events_by_type.items():
            for event in type_events:
                try:
                    event_date = event.start_datetime
                    day_name = event_date.strftime('%A')
                    date_str = event_date.strftime('%B %d')
                    time_str = event_date.strftime('%I:%M %p').lstrip('0')

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


@celery_task(max_retries=3, default_retry_delay=300)
def send_dynamic_event_reminders(self, session):
    """
    Send Discord reminders for league events based on each event's
    `reminder_days_before` setting.

    Run hourly to catch events at the right time.
    """
    import asyncio
    from app.models.calendar import LeagueEvent
    from app.services.discord_service import get_discord_service

    try:
        today = pacific_today()
        now = pacific_now()

        events_needing_reminder = session.query(LeagueEvent).filter(
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
                event_date = event.start_datetime.date()
                days_before = event.reminder_days_before or 2
                reminder_date = event_date - timedelta(days=days_before)

                if today < reminder_date:
                    continue

                checked_count += 1
                event_datetime = event.start_datetime
                day_name = event_datetime.strftime('%A')
                date_str = event_datetime.strftime('%B %d')
                time_str = event_datetime.strftime('%I:%M %p').lstrip('0')
                end_time_str = ''
                if event.end_datetime:
                    end_time_str = event.end_datetime.strftime('%I:%M %p').lstrip('0')

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
                    # Store the wall-clock timestamp of when the reminder went out.
                    event.reminder_sent_at = now.replace(tzinfo=None)
                    session.add(event)
                    posted_count += 1
                    logger.info(f"Posted reminder for '{event.title}' on {date_str} (event on {event_date})")

            except Exception as e:
                logger.error(f"Error posting reminder for event {event.id}: {e}")

        logger.info(f"Dynamic event reminders complete: {posted_count} posted, {checked_count} checked")
        return {
            'success': True,
            'posted_count': posted_count,
            'checked_count': checked_count,
            'total_pending': len(events_needing_reminder)
        }

    except Exception as e:
        logger.error(f"Error in send_dynamic_event_reminders: {e}", exc_info=True)
        raise self.retry(exc=e)
