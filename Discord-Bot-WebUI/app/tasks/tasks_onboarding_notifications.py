# app/tasks/tasks_onboarding_notifications.py

"""
Onboarding approval-gate Discord notifications.

Consumers of the Discord-onboarding config keys (admin_panel/routes/
discord_management.py):

- onboarding_approval_notify_channel — channel NAME the bot posts to when a
  new signup lands in the approval queue, and where the periodic reminder
  posts. Empty = feature off.
- onboarding_reminder_window — '24h'/'48h'/'72h'/'1w'/'2w'/'never': the weekly
  reminder mentions signups pending longer than this. 'never' = off.

The same channel also receives Account Recovery pings
(notify_discord_relink_request) — a member locked out of the portal because
they lost their Discord account is the same admin's problem as the approval
queue, and needs a faster response.

Posts go through the bot REST API's generic channel-message endpoint
(POST {BOT_API_URL}/api/channels/message). Every task here is best-effort:
any failure logs and moves on — approval and login flows must never depend
on Discord being reachable.
"""

import logging
from datetime import datetime, timedelta

import requests

from web_config import Config
from app.decorators import celery_task
from app.models import User
from app.models.admin_config import AdminConfig

logger = logging.getLogger(__name__)

APPROVALS_PATH = '/admin-panel/users/approvals'
ACCOUNT_RECOVERY_PATH = '/admin-panel/discord/account-recovery'

REMINDER_WINDOW_HOURS = {'24h': 24, '48h': 48, '72h': 72, '1w': 168, '2w': 336}
REMINDER_WINDOW_LABELS = {
    '24h': '24 hours', '48h': '48 hours', '72h': '72 hours',
    '1w': 'a week', '2w': 'two weeks',
}


def _portal_url(path):
    from flask import current_app
    base = (current_app.config.get('BASE_URL') or 'https://portal.ecsfc.com').rstrip('/')
    return f'{base}{path}'


def _approvals_url():
    return _portal_url(APPROVALS_PATH)


def _post_channel_message(channel_name, content):
    """Post plain text to a named channel via the bot REST API."""
    resp = requests.post(
        f'{Config.BOT_API_URL}/api/channels/message',
        json={'channel_name': channel_name, 'content': content},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


@celery_task
def notify_pending_approval(self, session, user_id):
    """Announce a new approval-queue signup in the configured channel.

    Dispatched (with a short countdown so the registration commit lands first)
    from the web, Discord, and waitlist registration paths. No-op unless
    onboarding_approval_notify_channel is set and the user is still pending.
    """
    channel = (AdminConfig.get_setting('onboarding_approval_notify_channel', '') or '').strip()
    if not channel:
        return {'skipped': 'no notify channel configured'}

    user = session.query(User).get(user_id)
    if not user:
        return {'skipped': f'user {user_id} not found'}
    if user.is_approved or user.approval_status != 'pending':
        return {'skipped': 'user no longer pending'}

    name = None
    if getattr(user, 'player', None) and user.player and user.player.name:
        name = user.player.name
    name = name or user.username or user.email or f'user #{user.id}'

    league = (user.preferred_league or '').replace('_', ' ').strip()
    league_bit = f' ({league})' if league and league != 'not sure' else ''

    content = (
        f'New signup waiting for approval: **{name}**{league_bit}\n'
        f'{_approvals_url()}'
    )
    try:
        result = _post_channel_message(channel, content)
        return {'posted': True, 'channel': result.get('channel_name', channel)}
    except Exception as e:
        logger.warning(f'Could not post approval notification to #{channel}: {e}')
        return {'posted': False, 'error': str(e)}


@celery_task
def remind_pending_approvals(self, session):
    """Weekly beat task: nudge the notify channel about stale pending signups.

    Posts at most once per run (scheduled Mondays), and only when at least one
    user has been pending longer than onboarding_reminder_window. 'never', a
    missing channel, or an empty queue all no-op.
    """
    window = AdminConfig.get_setting('onboarding_reminder_window', 'never')
    hours = REMINDER_WINDOW_HOURS.get(window)
    if not hours:
        return {'skipped': f'reminder window is {window!r}'}

    channel = (AdminConfig.get_setting('onboarding_approval_notify_channel', '') or '').strip()
    if not channel:
        return {'skipped': 'no notify channel configured'}

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    stale = session.query(User).filter(
        User.is_approved.is_(False),
        User.approval_status == 'pending',
        User.created_at <= cutoff,
    ).order_by(User.created_at.asc()).all()

    # Waitlisted members stay 'pending' by design until a spot opens — they
    # would make this reminder fire every single day all season. Only nudge
    # about signups an admin can actually act on now.
    stale = [u for u in stale
             if not any(r.name == 'pl-waitlist' for r in (u.roles or []))]

    if not stale:
        return {'skipped': 'no signups pending longer than the window'}

    def _display(u):
        if getattr(u, 'player', None) and u.player and u.player.name:
            return u.player.name
        return u.username or u.email or f'user #{u.id}'

    names = [_display(u) for u in stale[:10]]
    listed = ', '.join(f'**{n}**' for n in names)
    if len(stale) > len(names):
        listed += f' and {len(stale) - len(names)} more'

    plural = 's have' if len(stale) != 1 else ' has'
    window_label = REMINDER_WINDOW_LABELS.get(window, window)
    content = (
        f'{len(stale)} signup{plural} been waiting for approval for over {window_label}: {listed}\n'
        f'{_approvals_url()}'
    )
    try:
        _post_channel_message(channel, content)
        return {'posted': True, 'pending_count': len(stale)}
    except Exception as e:
        logger.warning(f'Could not post approval reminder to #{channel}: {e}')
        return {'posted': False, 'error': str(e)}


@celery_task
def notify_discord_relink_request(self, session, request_id):
    """Announce a stranded member in the Account Recovery queue.

    Fires when a Discord login is REFUSED because the account it claims is
    already linked to a different Discord ID -- almost always someone who
    lost access to their old Discord and made a new one. They cannot get
    back in without an admin, and Discord is the only door, so the ping
    matters more than the usual approval notice.

    Only dispatched for NEW requests; retries by the same stranded member
    bump the existing row silently instead of re-pinging.

    Shares onboarding_approval_notify_channel -- an admin watching the
    approvals channel is the same person who resolves these. Best-effort:
    never allowed to affect the login path that queued it.
    """
    from app.models import DiscordRelinkRequest, DiscordRelinkStatus

    channel = (AdminConfig.get_setting('onboarding_approval_notify_channel', '') or '').strip()
    if not channel:
        return {'skipped': 'no notify channel configured'}

    relink_request = session.query(DiscordRelinkRequest).get(request_id)
    if not relink_request:
        return {'skipped': f'relink request {request_id} not found'}
    if relink_request.status != DiscordRelinkStatus.PENDING:
        return {'skipped': 'request already resolved'}

    # Name the person if we know who they claim to be -- "Gregg can't get in"
    # is actionable in a way that a bare Discord ID is not.
    who = None
    if relink_request.candidate_player is not None:
        who = relink_request.candidate_player.name
    who = who or relink_request.requested_discord_username or 'Someone'

    if relink_request.blocked_reason == 'email_history_ambiguous':
        detail = 'we matched more than one account, so someone has to confirm which is theirs'
    else:
        detail = 'looks like they lost their old Discord and made a new one'

    content = (
        f"**{who}** is locked out of the portal — {detail}.\n"
        f"Review and relink: {_portal_url(ACCOUNT_RECOVERY_PATH)}"
    )
    try:
        result = _post_channel_message(channel, content)
        return {'posted': True, 'channel': result.get('channel_name', channel)}
    except Exception as e:
        logger.warning(f'Could not post relink notification to #{channel}: {e}')
        return {'posted': False, 'error': str(e)}
