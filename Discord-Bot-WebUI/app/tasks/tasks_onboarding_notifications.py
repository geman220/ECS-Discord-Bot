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

Posts go through the bot REST API's generic channel-message endpoint
(POST {BOT_API_URL}/api/channels/message). Both tasks are best-effort: any
failure logs and moves on — approval flow must never depend on Discord.
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

REMINDER_WINDOW_HOURS = {'24h': 24, '48h': 48, '72h': 72, '1w': 168, '2w': 336}
REMINDER_WINDOW_LABELS = {
    '24h': '24 hours', '48h': '48 hours', '72h': '72 hours',
    '1w': 'a week', '2w': 'two weeks',
}


def _approvals_url():
    from flask import current_app
    base = (current_app.config.get('BASE_URL') or 'https://portal.ecsfc.com').rstrip('/')
    return f'{base}{APPROVALS_PATH}'


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
