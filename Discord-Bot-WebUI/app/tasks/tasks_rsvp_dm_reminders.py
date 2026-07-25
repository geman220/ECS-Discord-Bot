# app/tasks/tasks_rsvp_dm_reminders.py

"""
RSVP Reminder Task (Tiered Notifications)
==========================================

Reminds players who haven't RSVP'd for upcoming matches.

Uses the NotificationOrchestrator's tiered delivery system:
    Push > Discord > Email > SMS (only highest-priority channel per user)

Discord DMs are handled specially with interactive RSVP buttons
instead of the orchestrator's plain-text DMs.

WHEN THIS RUNS
--------------
There is no beat entry for this task any more. It is driven by an automation
rule (trigger 'rsvp_not_responded', key 'rsvp_dm_reminder') at
/admin-panel/communication/automations, which owns the schedule, the lookahead
window, how many times one match may be chased, and every string that goes out.
The engine's hourly pass dispatches it; see automation_service._dispatch_native.

That means: if the rule is switched off or deleted, RSVP reminders stop. That is
the point of moving it, but it is also the failure mode to check first if
players say the reminders went quiet.

Every option still defaults to the old hardcoded behaviour (Thursday noon
Pacific, 4-day lookahead, one reminder per match, the original copy), so calling
this with no arguments -- from a shell, a test, or a hand-queued task -- behaves
exactly as it did before.
"""

import logging
import re
import time
import uuid
from datetime import timedelta

import requests

from app.decorators import celery_task
from app.utils.pacific_time import pacific_today

logger = logging.getLogger(__name__)

# The behaviour the hardcoded Thursday beat had, kept as the fallback for every
# caller that does not pass options. The seeded automation rule carries the same
# values, so switching to the rule changes nothing until an admin edits it.
DEFAULT_OPTIONS = {
    'lookahead_days': 4,
    'max_reminders_per_match': 1,
    'title': 'RSVP Reminder',
    'message_template': 'Please RSVP for {team} vs {opponent} on {date} at {time}',
    'dm_description': "You haven't RSVP'd for the following match(es). "
                      "Use the buttons below to respond!",
    'dm_footer': 'Click a button to RSVP, or Snooze to pause reminders',
}


def _resolve_options(options):
    """Merge caller options over the defaults, clamping the numeric knobs."""
    opts = dict(DEFAULT_OPTIONS)
    opts.update({k: v for k, v in (options or {}).items() if v is not None})

    def _clamp(key, lo, hi):
        try:
            opts[key] = max(lo, min(hi, int(opts[key])))
        except (TypeError, ValueError):
            opts[key] = DEFAULT_OPTIONS[key]

    # Mirrors TRIGGER_FIELD_SPECS in app/models/automation.py. Clamped again here
    # because this task is also callable directly, where nothing validated them.
    _clamp('lookahead_days', 1, 14)
    _clamp('max_reminders_per_match', 1, 5)
    return opts


def _render_line(template, match_info):
    """Fill the per-match tokens in an admin-authored message line.

    Unknown tokens are left alone rather than raising: a typo like {oponent}
    should ship visibly in the message, not take the whole weekly send down.
    """
    values = {
        'team': match_info.get('team_name', ''),
        'opponent': match_info.get('opponent_name', ''),
        'date': match_info.get('match_date', ''),
        'time': match_info.get('match_time', ''),
        'location': match_info.get('location', ''),
    }
    return re.sub(r'\{(\w+)\}',
                  lambda m: str(values.get(m.group(1), m.group(0))),
                  template or '')


def _finish_run(session, run_id, results):
    """Write the outcome back onto the AutomationRun that dispatched this.

    The engine leaves a native run in 'sending' precisely because only this task
    knows how many people it reached -- it resolves its own audience. The shared
    helper owns the status handoff; see automation_run_report for why it is not
    as simple as setting 'sent'.
    """
    from app.services.automation_run_report import report_native_run
    report_native_run(
        session, run_id,
        sent=results.get('orchestrator', 0) + results.get('discord_dm', 0),
        failed=results.get('failed', 0),
        nobody_message=('Nobody needed a reminder — everyone with a match in the '
                        'window had already responded, snoozed, or been reminded '
                        'the maximum number of times.'),
    )


@celery_task(max_retries=2, default_retry_delay=300)
def send_rsvp_dm_reminders(self, session, options=None, run_id=None):
    """
    Send tiered RSVP reminders to players who haven't RSVP'd.

    For push/email/sms: uses the orchestrator (tiered, so only the highest
    enabled channel fires). Discord is excluded from the orchestrator because
    we send interactive button DMs instead of plain text.

    Args:
        options: schedule-independent settings from the automation rule --
                 lookahead_days, max_reminders_per_match and the copy. Omitted
                 means DEFAULT_OPTIONS, i.e. the original hardcoded behaviour.
        run_id:  AutomationRun to report back to, when dispatched by a rule.
    """
    from app.models import Match, EcsFcMatch, Player
    from app.models.communication import RsvpDmReminderLog
    from app.services import rsvp_snooze_service
    from app.services.notification_orchestrator import (
        orchestrator, NotificationPayload, NotificationType
    )
    from web_config import Config

    opts = _resolve_options(options)

    try:
        batch_id = str(uuid.uuid4())
        today = pacific_today()
        window_end = today + timedelta(days=opts['lookahead_days'])
        bot_api_url = Config.BOT_API_URL

        # Clean up expired snoozes. Pass the task's session — there's no request
        # context here, so without it the service would fall back to db.session
        # while this task commits its own, and the cleanup DELETE would be lost.
        rsvp_snooze_service.cleanup_expired(session=session)
        snoozed_ids = rsvp_snooze_service.get_all_snoozed_player_ids(session=session)

        # Collect non-responders: player_id -> {player, matches}
        player_data = {}
        pub_count = _collect_pub_league_non_responders(session, today, window_end, snoozed_ids, player_data)
        ecs_count = _collect_ecs_fc_non_responders(session, today, window_end, snoozed_ids, player_data)

        # Repeat cap: COUNT how many reminders this player has already had about
        # this match and drop it once the cap is reached. This used to be a plain
        # "have we ever sent one?" set, which made the reminder strictly
        # once-per-match with no way to chase a persistent non-responder. A cap of
        # 1 reproduces that exactly, so the default behaviour is unchanged.
        #
        # Only 'sent' rows count. A 'failed' or 'dm_disabled' attempt did not
        # reach anybody, so it must not burn one of their reminders.
        # Scoped to the matches actually in the window. The previous version read
        # EVERY 'sent' row in the table on every run, which grows without bound
        # across seasons -- and transaction hold time is the scarce resource here.
        from sqlalchemy import func as _sa_func
        cap = opts['max_reminders_per_match']
        window_match_ids = {m['match_id']
                            for d in player_data.values() for m in d['matches']}
        sent_counts = {}
        if window_match_ids:
            sent_counts = {
                (row.player_id, row.match_id, row.match_type): row.n
                for row in session.query(
                    RsvpDmReminderLog.player_id,
                    RsvpDmReminderLog.match_id,
                    RsvpDmReminderLog.match_type,
                    _sa_func.count(RsvpDmReminderLog.id).label('n')
                ).filter(
                    RsvpDmReminderLog.delivery_status == 'sent',
                    RsvpDmReminderLog.match_id.in_(window_match_ids)
                ).group_by(
                    RsvpDmReminderLog.player_id,
                    RsvpDmReminderLog.match_id,
                    RsvpDmReminderLog.match_type
                ).all()
            }
        dedup_skipped = 0
        for player_id in list(player_data.keys()):
            original = player_data[player_id]['matches']
            filtered = [
                m for m in original
                if sent_counts.get((player_id, m['match_id'], m['match_type']), 0) < cap
            ]
            if not filtered:
                del player_data[player_id]
                dedup_skipped += len(original)
            else:
                dedup_skipped += len(original) - len(filtered)
                player_data[player_id]['matches'] = filtered

        logger.info(
            f"RSVP reminders: {pub_count} pub + {ecs_count} ECS FC non-responders "
            f"in the next {opts['lookahead_days']}d, {len(player_data)} unique players "
            f"(skipped {dedup_skipped} already reminded {cap}x)"
        )

        if not player_data:
            results = {'batch_id': batch_id, 'orchestrator': 0, 'discord_dm': 0,
                       'failed': 0, 'skipped': 0}
            _finish_run(session, run_id, results)
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
                            match_users[key] = {'user_ids': [], 'player_ids': [], 'match': m}
                        match_users[key]['user_ids'].append(user.id)
                        match_users[key]['player_ids'].append(player.id)
            elif tier == 'push':
                # Orchestrator handles push
                for m in data['matches']:
                    key = (m['match_type'], m['match_id'])
                    if key not in match_users:
                        match_users[key] = {'user_ids': [], 'player_ids': [], 'match': m}
                    match_users[key]['user_ids'].append(user.id)
                    match_users[key]['player_ids'].append(player.id)
                # Shared tier: also send Discord DM with buttons if available
                if shared_tier and player.discord_id and getattr(user, 'discord_notifications', True):
                    discord_dm_players.append(data)
            elif tier in ('email', 'sms'):
                # Orchestrator handles these tiers
                for m in data['matches']:
                    key = (m['match_type'], m['match_id'])
                    if key not in match_users:
                        match_users[key] = {'user_ids': [], 'player_ids': [], 'match': m}
                    match_users[key]['user_ids'].append(user.id)
                    match_users[key]['player_ids'].append(player.id)
            else:
                results['skipped'] += 1

        # Send orchestrator notifications per match (tiered, discord excluded)
        for key, info in match_users.items():
            m = info['match']
            days_until = _days_until_match(m, today)
            try:
                orchestrator.send(NotificationPayload(
                    notification_type=NotificationType.RSVP_REMINDER,
                    title=opts['title'],
                    message=_render_line(opts['message_template'], m),
                    user_ids=info['user_ids'],
                    data={'match_id': m['match_id'], 'match_type': m['match_type']},
                    priority='high' if days_until <= 1 else 'normal',
                    action_url='/schedule',
                    force_discord=False,  # We handle Discord separately (buttons)
                    # tiered=True is the default - push > email > sms
                ))
                results['orchestrator'] += len(info['user_ids'])
                # Log one row per player so the repeat cap can count these too.
                # Without this the cap only ever governed Discord users.
                for pid in info['player_ids']:
                    session.add(RsvpDmReminderLog(
                        player_id=pid,
                        match_id=m['match_id'],
                        match_type=m['match_type'],
                        discord_id=None,
                        channel='orchestrator',
                        delivery_status='sent',
                        batch_id=batch_id
                    ))
            except Exception as e:
                logger.error(f"Orchestrator notification failed for match {key}: {e}")
                results['failed'] += len(info['user_ids'])

        # Step 2: Custom Discord DMs with interactive buttons
        if bot_api_url and discord_dm_players:
            for data in discord_dm_players:
                player = data['player']
                matches = data['matches']

                status, error = _send_reminder_dm(
                    bot_api_url, player.discord_id, matches, opts
                )

                for m in matches:
                    session.add(RsvpDmReminderLog(
                        player_id=player.id,
                        match_id=m['match_id'],
                        match_type=m['match_type'],
                        discord_id=player.discord_id,
                        channel='discord',
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
        _finish_run(session, run_id, results)
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

    # Pre-reveal (make_teams_public off): these DMs literally name the
    # player's team ("Please RSVP for {team} vs {opponent}"). Skip hidden
    # Pub League matches entirely until the reveal.
    from app.services.team_visibility import teams_are_public, is_current_pub_league_team
    hide_pre_reveal = not teams_are_public()

    count = 0
    for match in matches:
        if hide_pre_reveal and (is_current_pub_league_team(match.home_team)
                                or is_current_pub_league_team(match.away_team)):
            continue

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


def _send_reminder_dm(bot_api_url, discord_id, matches, opts=None):
    """Send a reminder DM via the bot REST API (with interactive buttons).

    The embed copy travels in the payload so an admin can change it without a
    bot redeploy. All three copy fields are OPTIONAL on the bot side: an older
    bot ignores them and falls back to the strings baked into
    rsvp_reminder_views.py, which are the same text as DEFAULT_OPTIONS here. So
    a webapp deploy that lands before the bot redeploy still sends correctly, it
    just ignores copy edits until the bot catches up.
    """
    opts = opts or DEFAULT_OPTIONS
    try:
        payload = {
            'discord_id': discord_id,
            'title': opts.get('title') or None,
            'description': opts.get('dm_description') or None,
            'footer': opts.get('dm_footer') or None,
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


@celery_task(max_retries=2, default_retry_delay=120)
def send_coach_rsvp_reminder(self, session, match_id, player_ids, custom_message=None,
                             match_type='pub_league'):
    """Send a coach-initiated RSVP nudge to specific players for ONE match.

    The coach-facing "send reminder" endpoints (app/teams.py and
    app/mobile_api/coach_rsvp.py) used to build a message, increment a counter and
    return "Reminder sent to N players" WITHOUT dispatching anything — coaches were
    chasing RSVPs into the void. Those endpoints now hand off to this task.

    Runs in Celery, not in the request: it makes an HTTP call to the bot API, which
    must never happen inside an open web transaction (see the PgBouncer transaction
    budget). Uses the same tiered orchestrator + interactive-button Discord DM path as
    the scheduled Thursday reminder, so a player gets one nudge on their best channel.

    Deliberately NOT deduped against RsvpDmReminderLog: this is an explicit human
    action, so a coach asking twice should send twice. Rows are logged with
    reminder_type-style batch tracking so the manual sends stay auditable.
    """
    from app.models import Match, EcsFcMatch, Player, User
    from app.models.communication import RsvpDmReminderLog
    from app.services import rsvp_snooze_service
    from app.services.notification_orchestrator import (
        orchestrator, NotificationPayload, NotificationType
    )
    from web_config import Config

    if not player_ids:
        return {'success': True, 'sent': 0, 'reason': 'no recipients'}

    try:
        batch_id = str(uuid.uuid4())
        bot_api_url = Config.BOT_API_URL

        if match_type == 'ecs_fc':
            match = session.query(EcsFcMatch).get(match_id)
        else:
            match = session.query(Match).get(match_id)
        if not match:
            return {'success': False, 'error': f'match {match_id} not found'}

        # Respect an active snooze/break exactly like the scheduled reminder does —
        # a coach nudge must not punch through a player's opt-out.
        rsvp_snooze_service.cleanup_expired(session=session)
        snoozed_ids = rsvp_snooze_service.get_all_snoozed_player_ids(session=session)
        targets = [
            p for p in session.query(Player).filter(Player.id.in_(player_ids)).all()
            if p.id not in snoozed_ids
        ]
        snoozed_out = len(player_ids) - len(targets)
        if not targets:
            return {'success': True, 'sent': 0, 'snoozed': snoozed_out}

        info = _coach_reminder_match_info(session, match, match_type)
        body = custom_message or (
            f"Please RSVP for {info['team_name']} vs {info['opponent_name']} "
            f"on {info['match_date']} at {info['match_time']}"
        )

        results = {'batch_id': batch_id, 'orchestrator': 0, 'discord_dm': 0,
                   'failed': 0, 'snoozed': snoozed_out}

        # Tier 1: push / email / sms via the orchestrator (Discord excluded — below).
        user_ids = [p.user_id for p in targets if p.user_id]
        if user_ids:
            try:
                orchestrator.send(NotificationPayload(
                    notification_type=NotificationType.RSVP_REMINDER,
                    title="RSVP Reminder from your coach",
                    message=body,
                    user_ids=user_ids,
                    data={'match_id': match_id, 'match_type': match_type},
                    priority='high',
                    action_url='/schedule',
                    force_discord=False,
                ))
                results['orchestrator'] = len(user_ids)
            except Exception as e:
                logger.error(f"Coach RSVP reminder orchestrator failed (match {match_id}): {e}")
                results['failed'] += len(user_ids)

        # Tier 2: interactive Discord DMs with RSVP buttons.
        if bot_api_url:
            for player in targets:
                if not player.discord_id:
                    continue
                user = session.query(User).get(player.user_id) if player.user_id else None
                if user is not None and not getattr(user, 'discord_notifications', True):
                    continue

                status, error = _send_reminder_dm(bot_api_url, player.discord_id, [info])
                session.add(RsvpDmReminderLog(
                    player_id=player.id,
                    match_id=match_id,
                    # Log the same match_type the scheduled reminder does ('pub'/'ecs_fc'),
                    # so the two share one convention in this column.
                    match_type=info['match_type'],
                    discord_id=player.discord_id,
                    channel='discord',
                    delivery_status=status,
                    error_message=error,
                    batch_id=batch_id,
                ))
                # Note these rows DO count toward the automation's "most
                # reminders per match" cap. A coach nudge and an automated nudge
                # about the same match are the same message to the player, so
                # spending one of their reminders is the intended behaviour.
                if status == 'sent':
                    results['discord_dm'] += 1
                else:
                    results['failed'] += 1
                time.sleep(0.3)
        else:
            logger.warning("BOT_API_URL not configured - coach RSVP reminder sent without Discord DMs")

        results['success'] = True
        results['sent'] = results['orchestrator'] + results['discord_dm']
        logger.info(
            f"Coach RSVP reminder for match {match_id}: orchestrator={results['orchestrator']}, "
            f"discord_dm={results['discord_dm']}, failed={results['failed']}, "
            f"snoozed={snoozed_out}, batch_id={batch_id}"
        )
        return results

    except Exception as e:
        logger.error(f"Error in send_coach_rsvp_reminder (match {match_id}): {e}", exc_info=True)
        raise self.retry(exc=e)


def _coach_reminder_match_info(session, match, match_type):
    """Shape one match into the dict `_send_reminder_dm` expects."""
    if match_type == 'ecs_fc':
        team = match.team
        return {
            'match_type': 'ecs_fc',
            'match_id': match.id,
            'team_name': team.name if team else 'Your team',
            'opponent_name': match.opponent_name or 'TBD',
            'match_date': match.match_date.strftime('%A, %B %d') if match.match_date else 'TBD',
            'match_time': match.match_time.strftime('%I:%M %p') if match.match_time else 'TBD',
            'location': match.location or 'TBD',
        }
    return {
        # 'pub', NOT 'pub_league' — the bot's DM label and button custom_id key on
        # 'pub' (rsvp_reminder_views.py), exactly as the scheduled Thursday reminder
        # sends it. Using 'pub_league' here made every coach nudge render as an
        # "ECS FC Match".
        'match_type': 'pub',
        'match_id': match.id,
        'team_name': match.home_team.name if match.home_team else 'Your team',
        'opponent_name': match.away_team.name if match.away_team else 'TBD',
        'match_date': match.date.strftime('%A, %B %d') if match.date else 'TBD',
        'match_time': match.time.strftime('%I:%M %p') if match.time else 'TBD',
        'location': match.location or 'TBD',
    }
