# app/admin_panel/routes/surveys/distribute.py

"""
Survey Distribution Routes

Channel fan-out for a survey:
  - web link        (token URL; generated, no send)
  - email           reuses the email-broadcast pipeline (in-house)
  - discord_embed    bot posts an embed + "Take Survey" link button
  - native_poll      bot posts a native Discord poll (single choice question)
  - push             push-campaign service deep-links to the survey

Pages
  GET  /admin-panel/surveys/<id>/distribute

JSON API
  GET  /admin-panel/api/surveys/<id>/public-url
  POST /admin-panel/api/surveys/<id>/preview-audience    {filter_criteria}
  POST /admin-panel/api/surveys/<id>/send/email          {filter_criteria, subject?}
  POST /admin-panel/api/surveys/<id>/send/discord-embed  {channel_id, tag_role_ids?}
  POST /admin-panel/api/surveys/<id>/send/push           {target_type, target_ids?}
  POST /admin-panel/api/surveys/<id>/send/native-poll    {channel_id, duration_hours?}
"""

import logging
import requests
from datetime import datetime

from flask import render_template, request, jsonify, g, url_for
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from web_config import Config
from app.core import db
from app.models import Season, Team, League, Role
from app.models.surveys import Survey, SurveyDistribution
from app.models.discord_polls import DiscordPoll
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.services.survey_service import survey_service
from app.services.email_broadcast_service import email_broadcast_service

logger = logging.getLogger(__name__)

_ROLES = ['Global Admin', 'Pub League Admin']


def public_survey_url(survey):
    """Absolute public URL for taking a survey (token-based)."""
    return url_for('survey_public.take_survey', token=survey.access_token, _external=True)


def _record_distribution(session, survey, channel, **kwargs):
    dist = SurveyDistribution(
        survey_id=survey.id, channel=channel, created_by=current_user.id, **kwargs
    )
    session.add(dist)
    session.flush()
    return dist


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/surveys/<int:survey_id>/distribute')
@login_required
@role_required(_ROLES)
def survey_distribute(survey_id):
    """Distribution page: pick channels + audience, see the web link."""
    survey = Survey.query.get_or_404(survey_id)

    teams = Team.query.join(League, Team.league_id == League.id).join(
        Season, League.season_id == Season.id
    ).filter(Season.is_current == True, Team.is_active == True).order_by(Team.name).all()
    leagues = League.query.join(Season, League.season_id == Season.id).filter(
        Season.is_current == True
    ).order_by(League.name).all()
    roles = Role.query.order_by(Role.name).all()

    return render_template(
        'admin_panel/surveys/survey_distribute_flowbite.html',
        survey=survey,
        public_url=public_survey_url(survey),
        distributions=survey.distributions.order_by(SurveyDistribution.created_at.desc()).all(),
        teams=teams,
        leagues=leagues,
        roles=roles,
        page_title=f'Distribute: {survey.title}',
    )


# ---------------------------------------------------------------------------
# Helpers / shared JSON API
# ---------------------------------------------------------------------------

def _is_pub_league_channel(c):
    """Heuristic: this server's Pub League channels sit under a 'Pub League'
    category or use the pl- / pl_ name prefix (e.g. #pl-announcements)."""
    cat = (c.get('category') or '').lower()
    name = (c.get('name') or '').lower()
    return 'pub league' in cat or name.startswith('pl-') or name.startswith('pl_')


@admin_panel_bp.route('/api/surveys/discord-channels', methods=['GET'])
@login_required
@role_required(_ROLES)
def survey_discord_channels():
    """Live list of Pub League Discord channels, fetched from the bot.

    Degrades gracefully (200 + empty list) if the bot is unavailable so the UI
    can fall back to manual channel-ID entry.
    """
    try:
        bot_url = f"{Config.BOT_API_URL.rstrip('/')}/api/discord/channels"
        resp = requests.get(bot_url, timeout=10)
        if resp.status_code >= 400:
            return jsonify({'success': False, 'channels': [], 'error': 'Bot returned an error'})
        all_ch = (resp.json() if resp.content else {}).get('channels', [])
        pl = [c for c in all_ch if _is_pub_league_channel(c)]
        # If naming didn't match (different server layout), show all so the
        # picker is never empty — but flag that it isn't filtered.
        return jsonify({'success': True, 'channels': pl or all_ch, 'filtered': bool(pl)})
    except requests.RequestException:
        return jsonify({'success': False, 'channels': [], 'error': 'Bot unreachable'})


@admin_panel_bp.route('/api/surveys/<int:survey_id>/public-url', methods=['GET'])
@login_required
@role_required(_ROLES)
def survey_public_url_json(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    return jsonify({'success': True, 'url': public_survey_url(survey)})


@admin_panel_bp.route('/api/surveys/<int:survey_id>/preview-audience', methods=['POST'])
@login_required
@role_required(_ROLES)
def survey_preview_audience(survey_id):
    """Resolve a recipient count for the chosen targeting filter."""
    try:
        Survey.query.get_or_404(survey_id)
        filter_criteria = (request.get_json(force=True) or {}).get('filter_criteria') or {}
        recipients = survey_service.resolve_recipients(g.db_session, filter_criteria)
        description = survey_service.build_filter_description(g.db_session, filter_criteria)
        return jsonify({'success': True, 'count': len(recipients), 'description': description})
    except Exception as e:
        logger.error(f"Error previewing audience for survey {survey_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Channel: EMAIL  (reuses the proven email-broadcast pipeline, in-house)
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/api/surveys/<int:survey_id>/send/email', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def survey_send_email(survey_id):
    """Email the survey link to a resolved audience via the broadcast engine."""
    try:
        survey = Survey.query.get_or_404(survey_id)
        data = request.get_json(force=True) or {}
        filter_criteria = data.get('filter_criteria')
        if not filter_criteria or not filter_criteria.get('type'):
            return jsonify({'success': False, 'error': 'Audience is required.'}), 400

        url = public_survey_url(survey)
        subject = (data.get('subject') or f'{survey.title} — we want your feedback').strip()
        body_html = (
            f'<p>Hi {{first_name}},</p>'
            f'<p>{(survey.description or "Please take a moment to complete this survey.")}</p>'
            f'<p style="margin:24px 0;">'
            f'<a href="{url}" style="background:#1a472a;color:#fff;padding:12px 20px;'
            f'border-radius:8px;text-decoration:none;font-weight:600;">Take the survey</a></p>'
            f'<p style="font-size:12px;color:#666;">Or paste this link: {url}</p>'
        )

        session = db.session
        campaign = email_broadcast_service.create_campaign(session, {
            'name': f'Survey: {survey.title}',
            'subject': subject,
            'body_html': body_html,
            'send_mode': 'individual',  # personalized {first_name}
            'force_send': False,
            'filter_criteria': filter_criteria,
            'filter_description': email_broadcast_service.build_filter_description(session, filter_criteria),
        }, current_user.id)

        if campaign.total_recipients == 0:
            return jsonify({'success': False, 'error': 'No recipients matched the audience.'}), 400

        dist = _record_distribution(
            g.db_session, survey, 'email',
            target_criteria=filter_criteria,
            target_description=campaign.filter_description,
            total_recipients=campaign.total_recipients,
            status='sending',
        )
        session.commit()

        from app.tasks.tasks_email_broadcast import send_email_broadcast
        result = send_email_broadcast.delay(campaign.id)
        dist.celery_task_id = getattr(result, 'id', None)

        if survey.status == 'draft':
            survey_service.open_survey(g.db_session, survey)

        return jsonify({'success': True, 'recipients': campaign.total_recipients,
                        'distribution_id': dist.id})
    except Exception as e:
        logger.error(f"Error emailing survey {survey_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Channel: DISCORD EMBED  (bot posts an embed + "Take Survey" link button)
# Requires bot endpoint: POST {BOT_API_URL}/api/discord/post-survey-embed
#   payload: {channel_id, title, description, url, button_label, tag_role_ids}
#   returns: {success, message_id, message_url}
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/api/surveys/<int:survey_id>/send/discord-embed', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def survey_send_discord_embed(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    data = request.get_json(force=True) or {}
    channel_id = str(data.get('channel_id') or '').strip()
    if not channel_id:
        return jsonify({'success': False, 'error': 'A Discord channel ID is required.'}), 400

    tag_role_ids = [str(r) for r in (data.get('tag_role_ids') or [])]
    payload = {
        'channel_id': channel_id,
        'title': survey.title[:256],
        'description': (survey.description or 'Tap below to take the survey.')[:2000],
        'url': public_survey_url(survey),
        'button_label': 'Take Survey',
        'tag_role_ids': tag_role_ids,
    }
    bot_url = f"{Config.BOT_API_URL.rstrip('/')}/api/discord/post-survey-embed"
    try:
        resp = requests.post(bot_url, json=payload, timeout=15)
    except requests.RequestException:
        logger.exception("Discord bot unreachable at %s", bot_url)
        return jsonify({'success': False, 'error': 'Discord bot unreachable.'}), 502

    if resp.status_code >= 400:
        return jsonify({'success': False, 'error': f'Discord rejected the post ({resp.status_code}).'}), 502

    body = resp.json() if resp.content else {}
    dist = _record_distribution(
        g.db_session, survey, 'discord_embed',
        discord_channel_id=channel_id,
        discord_message_id=str(body.get('message_id') or '') or None,
        discord_message_url=body.get('message_url'),
        status='sent', sent_at=datetime.utcnow(),
    )
    if survey.status == 'draft':
        survey_service.open_survey(g.db_session, survey)
    return jsonify({'success': True, 'distribution_id': dist.id,
                    'message_url': body.get('message_url')})


# ---------------------------------------------------------------------------
# Channel: NATIVE DISCORD POLL  (single-question single/multi choice surveys)
# Reuses the existing bot post-poll endpoint + DiscordPoll tracking.
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/api/surveys/<int:survey_id>/send/native-poll', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def survey_send_native_poll(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    data = request.get_json(force=True) or {}
    channel_id = str(data.get('channel_id') or '').strip()
    if not channel_id:
        return jsonify({'success': False, 'error': 'A Discord channel ID is required.'}), 400

    # Native polls map to exactly one choice question.
    choice_qs = [q for q in survey.questions if q.question_type in ('single_choice', 'multi_choice')]
    if len(choice_qs) != 1:
        return jsonify({'success': False,
                        'error': 'Native polls need exactly one single/multi-choice question.'}), 400
    question = choice_qs[0]
    options = [{'text': o.label[:55], 'emoji': None} for o in question.options][:10]
    if len(options) < 2:
        return jsonify({'success': False, 'error': 'The question needs at least 2 options.'}), 400

    duration_hours = int(data.get('duration_hours') or 48)
    payload = {
        'channel_id': channel_id,
        'tag_role_ids': [str(r) for r in (data.get('tag_role_ids') or [])],
        'question': question.prompt[:300],
        'answers': options,
        'duration_hours': max(1, min(168, duration_hours)),
        'allow_multiselect': question.question_type == 'multi_choice',
    }
    bot_url = f"{Config.BOT_API_URL.rstrip('/')}/api/discord/post-poll"
    try:
        resp = requests.post(bot_url, json=payload, timeout=15)
    except requests.RequestException:
        logger.exception("Discord bot unreachable at %s", bot_url)
        return jsonify({'success': False, 'error': 'Discord bot unreachable.'}), 502
    if resp.status_code >= 400:
        return jsonify({'success': False, 'error': f'Discord rejected the poll ({resp.status_code}).'}), 502

    body = resp.json() if resp.content else {}
    message_id = str(body.get('message_id') or '')
    expires_raw = body.get('expires_at')
    try:
        expires_at = datetime.fromisoformat(expires_raw.replace('Z', '+00:00')).replace(tzinfo=None) \
            if expires_raw else datetime.utcnow()
    except (TypeError, ValueError, AttributeError):
        expires_at = datetime.utcnow()

    poll = DiscordPoll(
        discord_message_id=message_id or f'survey-{survey.id}-{question.id}',
        channel_id=channel_id,
        channel_key='survey',
        title=question.prompt[:300],
        # Discord assigns answer IDs in insertion order starting at 1 (matches
        # the availability-poll convention + the vote callback's answer_id).
        options=[{'answer_id': i, 'text': o['text'], 'emoji': o['emoji']}
                 for i, o in enumerate(options, start=1)],
        poll_kind='generic',
        duration_hours=payload['duration_hours'],
        allow_multiselect=payload['allow_multiselect'],
        created_by_user_id=current_user.id,
        expires_at=expires_at,
        discord_message_url=body.get('message_url'),
    )
    g.db_session.add(poll)
    g.db_session.flush()

    dist = _record_distribution(
        g.db_session, survey, 'native_poll',
        discord_channel_id=channel_id,
        discord_message_id=message_id or None,
        discord_message_url=body.get('message_url'),
        discord_poll_id=poll.id,
        status='sent', sent_at=datetime.utcnow(),
    )
    if survey.status == 'draft':
        survey_service.open_survey(g.db_session, survey)
    return jsonify({'success': True, 'distribution_id': dist.id,
                    'message_url': body.get('message_url')})


# ---------------------------------------------------------------------------
# Channel: PUSH  (push-campaign service deep-links to the survey)
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/api/surveys/<int:survey_id>/send/push', methods=['POST'])
@login_required
@role_required(_ROLES)
def survey_send_push(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    data = request.get_json(force=True) or {}
    target_type = data.get('target_type', 'all')
    target_ids = data.get('target_ids')
    try:
        from app.services.push_campaign_service import PushCampaignService
        svc = PushCampaignService(session=g.db_session)
        campaign = svc.create_campaign(
            name=f'Survey: {survey.title}',
            title=survey.title[:50],
            body=(survey.description or 'Tap to take the survey.')[:150],
            target_type=target_type,
            target_ids=target_ids,
            created_by=current_user.id,
            action_url=public_survey_url(survey),
            send_immediately=True,
        )
        result = svc.send_campaign_now(campaign.id)

        dist = _record_distribution(
            g.db_session, survey, 'push',
            target_description=f'Push: {target_type}',
            total_recipients=getattr(campaign, 'target_count', 0) or 0,
            status='sent', sent_at=datetime.utcnow(),
        )
        g.db_session.commit()
        if survey.status == 'draft':
            survey_service.open_survey(g.db_session, survey)
        return jsonify({'success': True, 'distribution_id': dist.id, 'result': result})
    except Exception as e:
        logger.error(f"Error sending push for survey {survey_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
