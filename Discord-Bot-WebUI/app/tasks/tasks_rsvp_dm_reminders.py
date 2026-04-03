# app/tasks/tasks_rsvp_dm_reminders.py

"""
RSVP Reminder Task (Tiered Notifications)
==========================================

Celery beat task that runs Thursday at noon PST.
Reminds players who haven't RSVP'd for upcoming matches.

Uses the NotificationOrchestrator's tiered delivery system:
    Push > Discord > Email > SMS (only highest-priority channel per user)

Discord DMs are handled specially with interactive RSVP buttons
instead of the orchestrator's plain-text DMs.

Schedule: Thursday 12:00 PM PST (America/Los_Angeles)
"""

import logging
import time
import uuid
from datetime import date, timedelta

import requests

from app.decorators import celery_task

logger = logging.getLogger(__name__)


@celery_task(max_retries=2, default_retry_delay=300)
def send_rsvp_dm_reminders(self, session):
    """
    Send tiered RSVP reminders to players who haven't RSVP'd.

    For push/email/sms: uses the orchestrator (tiered, so only the highest
    enabled channel fires). Discord is excluded from the orchestrator because
    we send interactive button DMs instead of plain text.
    """
    from app.models import Match, EcsFcMatch, Player
    from app.models.communication import RsvpDmReminderLog
    from app.services import rsvp_snooze_service
    from app.services.notification_orchestrator import (
        orchestrator, NotificationPayload, NotificationType
    )
    from web_config import Config

    try:
        batch_id = str(uuid.uuid4())
        today = date.today()
        window_end = today + timedelta(days=4)
        bot_api_url = Config.BOT_API_URL

        # Clean up expired snoozes
        rsvp_snooze_service.cleanup_expired()
        snoozed_ids = rsvp_snooze_service.get_all_snoozed_player_ids()

        # Collect non-responders: player_id -> {player, matches}
        player_data = {}
        pub_count = _collect_pub_league_non_responders(session, today, window_end, snoozed_ids, player_data)
        ecs_count = _collect_ecs_fc_non_responders(session, today, window_end, snoozed_ids, player_data)

        # Dedup: remove matches where a reminder was already sent successfully
        already_reminded = set(
            (row.player_id, row.match_id, row.match_type)
            for row in session.query(
                RsvpDmReminderLog.player_id,
                RsvpDmReminderLog.match_id,
                RsvpDmReminderLog.match_type
            ).filter(
                RsvpDmReminderLog.delivery_status == 'sent'
            ).all()
        )
        dedup_skipped = 0
        for player_id in list(player_data.keys()):
            original = player_data[player_id]['matches']
            filtered = [
                m for m in original
                if (player_id, m['match_id'], m['match_type']) not in already_reminded
            ]
            if not filtered:
                del player_data[player_id]
                dedup_skipped += len(original)
            else:
                dedup_skipped += len(original) - len(filtered)
                player_data[player_id]['matches'] = filtered

        logger.info(
            f"RSVP reminders: {pub_count} pub + {ecs_count} ECS FC non-responders, "
            f"{len(player_data)} unique players (skipped {dedup_skipped} already-reminded)"
        )

        if not player_data:
            return {'success': True, 'total': 0}

        results = {
            'batch_id': batch_id,
            'orchestrator': 0, 'discord_dm': 0, 'failed': 0, 'skipped': 0
        }

        # For each match, determine which users get orchestrator notifications
        # and which get custom Discord DMs with buttons.
        #
        # Strategy: send the orchestrator notification (tiered, discord excluded)
        # for users with accounts, then send custom Discord DMs separately
        # to users whose highest tier IS discord.

        # Step 1: Orchestrator handles push/email/sms tiers (NOT discord)
        # Group by match for orchestrator calls
        match_users = {}  # (match_type, match_id) -> {user_ids, match_info}
        discord_dm_players = []  # players whose tier is discord

        # Check if push+discord shared tier is active (alpha testing mode)
        shared_tier = getattr(orchestrator, 'push_discord_shared_tier', False)

        for player_id, data in player_data.items():
            player = data['player']
            user = player.user

            if not user:
                # No user account - can only do Discord DM
                if player.discord_id:
                    discord_dm_players.append(data)
                else:
                    results['skipped'] += 1
                continue

            # Determine this user's tier to decide routing
            tier = _determine_player_tier(session, user, player)

            if tier == 'discord':
                # We handle Discord ourselves with buttons
                discord_dm_players.append(data)
                # Shared tier: also send push if available
                if shared_tier and _has_push(session, user):
                    for m in data['matches']:
                        key = (m['match_type'], m['match_id'])
                        if key not in match_users:
                            match_users[key] = {'user_ids': [], 'match': m}
                        match_users[key]['user_ids'].append(user.id)
            elif tier == 'push':
                # Orchestrator handles push
                for m in data['matches']:
                    key = (m['match_type'], m['match_id'])
                    if key not in match_users:
                        match_users[key] = {'user_ids': [], 'match': m}
                    match_users[key]['user_ids'].append(user.id)
                # Shared tier: also send Discord DM with buttons if available
                if shared_tier and player.discord_id and getattr(user, 'discord_notifications', True):
                    discord_dm_players.append(data)
            elif tier in ('email', 'sms'):
                # Orchestrator handles these tiers
                for m in data['matches']:
                    key = (m['match_type'], m['match_id'])
                    if key not in match_users:
                        match_users[key] = {'user_ids': [], 'match': m}
                    match_users[key]['user_ids'].append(user.id)
            else:
                results['skipped'] += 1

        # Send orchestrator notifications per match (tiered, discord excluded)
        for key, info in match_users.items():
            m = info['match']
            days_until = _days_until_match(m, today)
            try:
                orchestrator.send(NotificationPayload(
                    notification_type=NotificationType.RSVP_REMINDER,
                    title="RSVP Reminder",
                    message=(
                        f"Please RSVP for {m['team_name']} vs {m['opponent_name']} "
                        f"on {m['match_date']} at {m['match_time']}"
                    ),
                    user_ids=info['user_ids'],
                    data={'match_id': m['match_id'], 'match_type': m['match_type']},
                    priority='high' if days_until <= 1 else 'normal',
                    action_url='/schedule',
                    force_discord=False,  # We handle Discord separately (buttons)
                    # tiered=True is the default - push > email > sms
                ))
                results['orchestrator'] += len(info['user_ids'])
            except Exception as e:
                logger.error(f"Orchestrator notification failed for match {key}: {e}")
                results['failed'] += len(info['user_ids'])

        # Step 2: Custom Discord DMs with interactive buttons
        if bot_api_url and discord_dm_players:
            for data in discord_dm_players:
                player = data['player']
                matches = data['matches']

                status, error = _send_reminder_dm(
                    bot_api_url, player.discord_id, matches
                )

                for m in matches:
                    session.add(RsvpDmReminderLog(
                        player_id=player.id,
                        match_id=m['match_id'],
                        match_type=m['match_type'],
                        discord_id=player.discord_id,
                        delivery_status=status,
                        error_message=error,
                        batch_id=batch_id
                    ))

                if status == 'sent':
                    results['discord_dm'] += 1
                else:
                    results['failed'] += 1

                time.sleep(0.5)

        elif not bot_api_url and discord_dm_players:
            logger.warning("BOT_API_URL not configured - skipping Discord DMs")
            results['failed'] += len(discord_dm_players)

        logger.info(
            f"RSVP reminders complete: orchestrator={results['orchestrator']}, "
            f"discord_dm={results['discord_dm']}, failed={results['failed']}, "
            f"skipped={results['skipped']}, batch_id={batch_id}"
        )
        results['success'] = True
        return results

    except Exception as e:
        logger.error(f"Error in send_rsvp_dm_reminders: {e}", exc_info=True)
        raise self.retry(exc=e)


def _has_push(session, user):
    """Check if a user has active push notification tokens."""
    from app.models.notifications import UserFCMToken
    return session.query(UserFCMToken).filter_by(
        user_id=user.id, is_active=True
    ).first() is not None


def _determine_player_tier(session, user, player):
    """
    Determine highest-priority notification channel for a player.

    Mirrors the orchestrator's _determine_tier but works with model objects
    instead of the preferences dict.

    Returns: 'push', 'discord', 'email', 'sms', or None
    """
    rsvp_enabled = getattr(user, 'rsvp_reminder_notifications', True)
    if not rsvp_enabled:
        return None

    # 1. Push
    if getattr(user, 'push_notifications', True):
        from app.models.notifications import UserFCMToken
        has_tokens = session.query(UserFCMToken).filter_by(
            user_id=user.id, is_active=True
        ).first() is not None
        if has_tokens:
            return 'push'

    # 2. Discord
    if getattr(user, 'discord_notifications', True) and player.discord_id:
        return 'discord'

    # 3. Email
    if getattr(user, 'email_notifications', True) and user.email:
        return 'email'

    # 4. SMS (last resort)
    if getattr(user, 'sms_notifications', True):
        if getattr(player, 'is_phone_verified', False) and getattr(player, 'sms_consent_given', False):
            return 'sms'

    return None


def _days_until_match(match_info, today):
    """Parse match_date string back to calculate days until match."""
    # match_date is formatted like "Saturday, April 5" - approximate with window
    return 3  # Conservative default since exact parsing is fragile


def _collect_pub_league_non_responders(session, today, window_end, snoozed_ids, player_data):
    """Find pub league players who haven't RSVP'd for upcoming matches."""
    from sqlalchemy.orm import joinedload
    from app.models import Match

    matches = session.query(Match).filter(
        Match.date >= today,
        Match.date <= window_end,
        Match.is_special_week == False,
        Match.week_type.in_(['REGULAR', 'PLAYOFF'])
    ).options(
        joinedload(Match.home_team),
        joinedload(Match.away_team),
        joinedload(Match.availability)
    ).all()

    count = 0
    for match in matches:
        responded_ids = {
            a.player_id for a in match.availability
            if a.player_id and a.response in ('yes', 'no', 'maybe')
        }

        home_players = match.home_team.players if match.home_team else []
        away_players = match.away_team.players if match.away_team else []

        for player in list(home_players) + list(away_players):
            if player.id in responded_ids or player.id in snoozed_ids:
                continue

            if match.home_team and player in match.home_team.players:
                team_name = match.home_team.name
                opponent_name = match.away_team.name if match.away_team else 'TBD'
            else:
                team_name = match.away_team.name if match.away_team else 'Unknown'
                opponent_name = match.home_team.name if match.home_team else 'TBD'

            match_info = {
                'match_type': 'pub',
                'match_id': match.id,
                'player_id': player.id,
                'team_name': team_name,
                'opponent_name': opponent_name,
                'match_date': match.date.strftime('%A, %B %d'),
                'match_time': match.time.strftime('%I:%M %p') if match.time else 'TBD',
                'location': match.location or 'TBD'
            }

            if player.id not in player_data:
                player_data[player.id] = {'player': player, 'matches': []}
            player_data[player.id]['matches'].append(match_info)
            count += 1

    return count


def _collect_ecs_fc_non_responders(session, today, window_end, snoozed_ids, player_data):
    """Find ECS FC players who haven't RSVP'd for upcoming matches."""
    from sqlalchemy.orm import joinedload
    from app.models import EcsFcMatch

    matches = session.query(EcsFcMatch).filter(
        EcsFcMatch.match_date >= today,
        EcsFcMatch.match_date <= window_end,
        EcsFcMatch.status == 'SCHEDULED'
    ).options(
        joinedload(EcsFcMatch.availabilities)
    ).all()

    count = 0
    for match in matches:
        responded_ids = {
            a.player_id for a in match.availabilities
            if a.player_id and a.response in ('yes', 'no', 'maybe')
        }

        team = match.team
        if not team:
            continue

        for player in team.players:
            if player.id in responded_ids or player.id in snoozed_ids:
                continue

            match_info = {
                'match_type': 'ecs_fc',
                'match_id': match.id,
                'player_id': player.id,
                'team_name': team.name,
                'opponent_name': match.opponent_name or 'TBD',
                'match_date': match.match_date.strftime('%A, %B %d'),
                'match_time': match.match_time.strftime('%I:%M %p') if match.match_time else 'TBD',
                'location': match.location or 'TBD'
            }

            if player.id not in player_data:
                player_data[player.id] = {'player': player, 'matches': []}
            player_data[player.id]['matches'].append(match_info)
            count += 1

    return count


def _send_reminder_dm(bot_api_url, discord_id, matches):
    """Send a reminder DM via the bot REST API (with interactive buttons)."""
    try:
        payload = {
            'discord_id': discord_id,
            'matches': [
                {
                    'match_type': m['match_type'],
                    'match_id': m['match_id'],
                    'team_name': m['team_name'],
                    'opponent_name': m['opponent_name'],
                    'match_date': m['match_date'],
                    'match_time': m['match_time'],
                    'location': m['location']
                }
                for m in matches
            ]
        }

        resp = requests.post(
            f"{bot_api_url}/api/rsvp/send_reminder_dm",
            json=payload,
            timeout=10
        )

        if resp.status_code == 200:
            return (resp.json().get('status', 'sent'), None)
        elif resp.status_code == 403:
            return ('dm_disabled', resp.json().get('detail', 'DMs disabled'))
        else:
            return ('failed', f"Bot API returned {resp.status_code}: {resp.text[:200]}")

    except requests.Timeout:
        return ('failed', 'Bot API timeout')
    except requests.ConnectionError:
        return ('failed', 'Bot API connection error')
    except Exception as e:
        return ('failed', str(e)[:200])


@celery_task()
def send_rsvp_dm_reminders_manual(self, session):
    """Manual trigger for RSVP DM reminders (for admin testing)."""
    result = send_rsvp_dm_reminders.delay()
    return {'task_id': result.id, 'status': 'dispatched'}
