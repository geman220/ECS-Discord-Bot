# app/admin_panel/routes/user_management/coach_engagement.py

"""
Coach Engagement Routes

Admin dashboard surfacing which coaches are actually doing the work (reporting
matches, setting lineups, checking RSVPs, talking in their team channel) vs.
coaches in name only — so coaching slots can be balanced and chosen better.
Also exposes community-level Discord channel usage.
"""

import logging
import os

import requests
from flask import render_template, request, jsonify, flash, redirect, url_for, g
from flask_login import login_required

from app.admin_panel import admin_panel_bp
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.admin_panel.routes.user_management.coach_engagement_helpers import (
    get_coach_engagement,
    get_discord_channel_metrics,
    get_coach_history,
)
from app.services.coach_channels import (
    list_classifiable_channels, set_channel_role, clear_channel_role,
)

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/users/coach-engagement')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def coach_engagement():
    """Coach engagement + community Discord dashboard."""
    try:
        season_id = request.args.get('season_id', type=int)
        league_name = request.args.get('league') or None
        session = g.db_session
        engagement = get_coach_engagement(session, season_id=season_id, league_name=league_name)
        discord_metrics = get_discord_channel_metrics(
            session, season_id=engagement.get('season', {}).get('id') if engagement.get('season') else None)
        return render_template(
            'admin_panel/users/coach_engagement_flowbite.html',
            engagement=engagement,
            discord_metrics=discord_metrics,
        )
    except Exception as e:
        logger.error(f"Error loading coach engagement: {e}", exc_info=True)
        flash('Coach engagement unavailable. Check application logs for details.', 'error')
        return redirect(url_for('admin_panel.user_analytics'))


@admin_panel_bp.route('/users/coach-engagement/coach/<int:player_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def coach_history(player_id):
    """Cross-season participation timeline for a single coach."""
    try:
        history = get_coach_history(g.db_session, player_id)
        if not history:
            flash('Coach not found.', 'error')
            return redirect(url_for('admin_panel.coach_engagement'))
        return render_template(
            'admin_panel/users/coach_history_flowbite.html', history=history)
    except Exception as e:
        logger.error(f"Error loading coach history: {e}", exc_info=True)
        flash('Coach history unavailable. Check application logs for details.', 'error')
        return redirect(url_for('admin_panel.coach_engagement'))


@admin_panel_bp.route('/users/coach-engagement/review', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def coach_attention_review():
    """Mark / unmark a coach as reviewed in the support queue (per season)."""
    from flask_login import current_user
    from app.models import CoachAttentionReview
    season_id = request.form.get('season_id', type=int)
    player_id = request.form.get('player_id', type=int)
    action = request.form.get('action', 'review')
    if not season_id or not player_id:
        flash('Missing coach or season.', 'error')
        return redirect(url_for('admin_panel.coach_engagement'))

    existing = g.db_session.query(CoachAttentionReview).filter_by(
        season_id=season_id, player_id=player_id).first()
    if action == 'unreview':
        if existing:
            g.db_session.delete(existing)
        flash('Moved back to the attention queue.', 'success')
    else:
        if not existing:
            g.db_session.add(CoachAttentionReview(
                season_id=season_id, player_id=player_id, reviewed_by=current_user.id))
        flash('Marked reviewed — cleared from the queue for this season.', 'success')
    return redirect(url_for('admin_panel.coach_engagement',
                            season_id=season_id, league=request.form.get('league') or None))


@admin_panel_bp.route('/users/coach-engagement/channels')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def coach_channels():
    """Manage which Discord channels count as coaches channels (and their cohort)."""
    try:
        channels = list_classifiable_channels(g.db_session)
        return render_template(
            'admin_panel/users/coach_channels_flowbite.html', channels=channels)
    except Exception as e:
        logger.error(f"Error loading coach channels: {e}", exc_info=True)
        flash('Channel manager unavailable — has the discord_channel_role table been created?', 'error')
        return redirect(url_for('admin_panel.coach_engagement'))


@admin_panel_bp.route('/users/coach-engagement/channels/set', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional(max_retries=2)
def coach_channels_set():
    """Classify or clear a single channel. Form: channel_id, role ('' clears), channel_name."""
    channel_id = (request.form.get('channel_id') or '').strip()
    role = (request.form.get('role') or '').strip()
    channel_name = (request.form.get('channel_name') or '').strip() or None
    if not channel_id:
        flash('Missing channel.', 'error')
        return redirect(url_for('admin_panel.coach_channels'))

    if role:
        ok, msg = set_channel_role(g.db_session, channel_id, role, channel_name)
    else:
        ok, msg = clear_channel_role(g.db_session, channel_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('admin_panel.coach_channels'))


@admin_panel_bp.route('/users/community-analytics')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def community_analytics():
    """Pub-league Discord community analytics — channel activity & participation."""
    try:
        days = request.args.get('days', default=90, type=int)
        if days not in (30, 90, 180, 365):
            days = 90
        metrics = get_discord_channel_metrics(g.db_session, days=days)
        return render_template(
            'admin_panel/users/community_analytics_flowbite.html',
            metrics=metrics, window_days=days)
    except Exception as e:
        logger.error(f"Error loading community analytics: {e}", exc_info=True)
        flash('Community analytics unavailable. Check application logs for details.', 'error')
        return redirect(url_for('admin_panel.coach_engagement'))


@admin_panel_bp.route('/users/community-analytics/backfill', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def community_analytics_backfill():
    """Trigger the bot's one-time chat-history backfill (admin-panel button)."""
    try:
        days = (request.get_json(silent=True) or {}).get('days', 120)
        bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
        resp = requests.post(
            f"{bot_api_url}/api/bot/backfill-chat-history",
            json={'days': days}, timeout=10)
        if resp.status_code == 200:
            return jsonify(resp.json())
        return jsonify({'success': False,
                        'message': f'Bot API returned {resp.status_code}'}), 502
    except requests.RequestException as e:
        logger.error(f"Backfill trigger failed to reach bot API: {e}")
        return jsonify({'success': False, 'message': 'Could not reach the bot.'}), 502
    except Exception as e:
        logger.error(f"Error triggering backfill: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to start backfill.'}), 500


@admin_panel_bp.route('/users/community-analytics/backfill/status')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def community_analytics_backfill_status():
    """Proxy the bot's backfill status so the page can poll for completion."""
    try:
        bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
        resp = requests.get(
            f"{bot_api_url}/api/bot/backfill-chat-history/status", timeout=10)
        if resp.status_code == 200:
            return jsonify({'success': True, **resp.json()})
        return jsonify({'success': False, 'message': f'Bot API returned {resp.status_code}'}), 502
    except requests.RequestException as e:
        logger.error(f"Backfill status failed to reach bot API: {e}")
        return jsonify({'success': False, 'message': 'Could not reach the bot.'}), 502
    except Exception as e:
        logger.error(f"Error fetching backfill status: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to fetch status.'}), 500


@admin_panel_bp.route('/users/coach-engagement/data')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def coach_engagement_data():
    """JSON feed for the coach engagement dashboard (season switch / export)."""
    try:
        season_id = request.args.get('season_id', type=int)
        league_name = request.args.get('league') or None
        session = g.db_session
        engagement = get_coach_engagement(session, season_id=season_id, league_name=league_name)
        season_for_discord = engagement.get('season', {}).get('id') if engagement.get('season') else None
        discord_metrics = get_discord_channel_metrics(session, season_id=season_for_discord)
        return jsonify({'success': True, 'engagement': engagement, 'discord_metrics': discord_metrics})
    except Exception as e:
        logger.error(f"Error loading coach engagement data: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to load coach engagement data'}), 500
