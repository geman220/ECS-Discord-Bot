# app/ai_assistant.py

"""
AI Assistant Blueprint

Routes for the AI-powered help assistant:
- POST /api/ai-assistant/ask - Main question endpoint
- GET /api/ai-assistant/suggestions - Contextual suggestion chips
- GET /api/ai-assistant/usage - Current user's rate limit status
- POST /api/ai-assistant/rate - Rate a response (thumbs up/down)
- GET /api/ai-assistant/admin/metrics - Admin usage dashboard page
- GET /api/ai-assistant/admin/metrics/data - Admin metrics JSON
"""

import logging
import re
import time

from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user

from app.decorators import role_required

logger = logging.getLogger(__name__)

ai_assistant_bp = Blueprint('ai_assistant', __name__, url_prefix='/api/ai-assistant')


def _get_user_profile():
    """Build a rich user profile for system prompt personalization."""
    profile = {
        'name': current_user.name or current_user.username,
        'roles': [],
        'team_name': None,
        'league_name': None,
        'is_captain': False,
    }

    try:
        profile['roles'] = [r.name for r in current_user.roles]
    except Exception:
        pass

    try:
        from app.models import Season, League, Team
        from app.models.players import PlayerTeamSeason

        current_season = Season.query.filter_by(is_current=True).first()
        if current_season and hasattr(current_user, 'player') and current_user.player:
            pts = PlayerTeamSeason.query.filter_by(
                player_id=current_user.player.id
            ).join(Team).join(League).filter(
                League.season_id == current_season.id
            ).first()

            if pts and pts.team:
                profile['team_name'] = pts.team.name
                if pts.team.league:
                    profile['league_name'] = pts.team.league.name
                profile['is_captain'] = getattr(pts, 'is_captain', False)
    except Exception:
        pass

    return profile


def _get_context_type():
    """Determine context type based on user roles and request."""
    requested = request.json.get('context_type', 'auto')

    if requested != 'auto':
        # Validate: non-admins can't request admin_panel context
        if requested == 'admin_panel':
            if not (current_user.has_role('Global Admin') or current_user.has_role('Pub League Admin')):
                return 'user_help'
        return requested

    # Auto-detect based on roles
    if current_user.has_role('Global Admin') or current_user.has_role('Pub League Admin'):
        page_url = request.json.get('current_page_url', '')
        if '/admin-panel' in page_url:
            return 'admin_panel'
        return 'admin_panel'

    if current_user.has_role('ECS FC Coach'):
        return 'coach'

    return 'user_help'


def _validate_message(message):
    """Validate user input. Returns (clean_message, error) tuple."""
    if not message or not message.strip():
        return None, 'Message cannot be empty.'

    message = message.strip()

    if len(message) > 2000:
        return None, 'Message is too long (max 2000 characters).'

    # Basic prompt injection patterns
    injection_patterns = [
        r'ignore\s+(previous|all|above)\s+instructions',
        r'disregard\s+(your|all)\s+(rules|instructions)',
        r'system\s*prompt',
        r'</system>',
        r'<\|im_start\|>',
    ]
    for pattern in injection_patterns:
        if re.search(pattern, message, re.IGNORECASE):
            return None, 'Your message was not processed. Please rephrase your question.'

    return message, None


@ai_assistant_bp.route('/ask', methods=['POST'])
@login_required
def ask():
    """Main AI assistant endpoint."""
    from app.models.admin_config import AdminConfig
    from app.services.ai_rate_limiter import ai_rate_limiter
    from app.services.ai_assistant_service import ai_assistant_service
    from app.models.ai_assistant import AIAssistantLog

    # Check if AI is enabled
    if not AdminConfig.get_setting('ai_assistant_enabled', True):
        return jsonify({'success': False, 'message': 'The AI assistant is currently disabled.'}), 503

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request.'}), 400

    user_message = data.get('message', '')
    conversation_history = data.get('conversation_history', [])
    current_page_url = data.get('current_page_url', '')

    # Validate input
    clean_message, error = _validate_message(user_message)
    if error:
        AIAssistantLog.log_interaction(
            user_id=current_user.id, context_type='rejected',
            user_message=user_message[:500], was_rejected=True, rejection_reason=error
        )
        return jsonify({'success': False, 'message': error}), 400

    # Rate limit check
    is_admin = current_user.has_role('Global Admin')
    allowed, limit_message = ai_rate_limiter.check_rate_limit(current_user.id, is_admin)
    if not allowed:
        AIAssistantLog.log_interaction(
            user_id=current_user.id, context_type='rate_limited',
            user_message=clean_message[:500], was_rejected=True, rejection_reason='rate_limited'
        )
        return jsonify({'success': False, 'message': limit_message, 'rate_limited': True}), 429

    # Determine context and build system prompt
    context_type = _get_context_type()
    user_profile = _get_user_profile()

    # Get contextual knowledge
    admin_search_index = None
    help_topics = None

    if context_type in ('admin_panel', 'coach'):
        try:
            from app.admin_panel import _build_admin_search_index
            from flask import current_app
            with current_app.test_request_context():
                admin_search_index = _build_admin_search_index()
        except Exception:
            admin_search_index = []

    if context_type == 'user_help':
        try:
            from app.help import get_accessible_roles
            from app.models.external import HelpTopic
            from app.core import db

            user_roles = [r.name for r in current_user.roles]
            accessible = get_accessible_roles(user_roles)

            topics = HelpTopic.query.filter(
                HelpTopic.roles.any(db.and_(True))
            ).all()

            help_topics = [
                {'title': t.title, 'content': t.content[:300]}
                for t in topics[:20]
            ]
        except Exception:
            help_topics = []

    system_prompt = ai_assistant_service.build_system_prompt(
        context_type, user_profile, admin_search_index, help_topics
    )

    # Call the AI
    start_time = time.time()
    result = ai_assistant_service.ask(
        system_prompt, clean_message, conversation_history,
        max_tokens=int(AdminConfig.get_setting('ai_assistant_max_tokens', 1024))
    )
    response_time_ms = round((time.time() - start_time) * 1000, 1)

    # Canary detection: if the AI leaked the system prompt canary token, sanitize and log
    response_text = result.get('response', '')
    if 'CANARY_ECS_7f3a9b2c' in response_text:
        logger.warning(f"CANARY TOKEN LEAKED in AI response for user {current_user.id} - possible prompt extraction attack")
        response_text = 'I can only help with questions about using the ECS FC Portal. Please ask me about portal features, navigation, or league management.'
        result['response'] = response_text
        result['error'] = True

    # Track usage
    ai_rate_limiter.increment(current_user.id)
    estimated_cost = ai_rate_limiter.track_cost(
        result.get('input_tokens', 0),
        result.get('output_tokens', 0),
        result.get('provider', 'claude'),
        result.get('model', '')
    )

    # Log the interaction
    log = AIAssistantLog.log_interaction(
        user_id=current_user.id,
        context_type=context_type,
        user_message=clean_message,
        assistant_response=result.get('response', '')[:5000],
        current_page_url=current_page_url,
        input_tokens=result.get('input_tokens'),
        output_tokens=result.get('output_tokens'),
        estimated_cost_usd=estimated_cost,
        response_time_ms=response_time_ms,
        provider=result.get('provider'),
        model_used=result.get('model'),
        was_rejected=result.get('error', False),
    )

    return jsonify({
        'success': True,
        'response': result.get('response', ''),
        'provider': result.get('provider'),
        'log_id': log.id if log else None,
    })


@ai_assistant_bp.route('/suggestions')
@login_required
def suggestions():
    """Get contextual suggestion chips based on user role and current page."""
    page_url = request.args.get('page', '')
    user_roles = [r.name for r in current_user.roles]

    if any(r in user_roles for r in ['Global Admin', 'Pub League Admin']):
        if '/admin-panel' in page_url:
            chips = [
                'How do I create a new season?',
                'Where are pending user approvals?',
                'How do I send a push notification?',
                'Where can I manage team rosters?',
            ]
        else:
            chips = [
                'How do I navigate the admin panel?',
                'What reports are available?',
                'How do I manage users?',
            ]
    elif 'ECS FC Coach' in user_roles:
        chips = [
            'How do I report a match?',
            'Where is my team schedule?',
            'How do I manage substitutes?',
        ]
    else:
        chips = [
            'How do I RSVP for a match?',
            'Where can I see my schedule?',
            'How do I update my profile?',
        ]

    return jsonify({'success': True, 'suggestions': chips})


@ai_assistant_bp.route('/usage')
@login_required
def usage():
    """Get current user's rate limit status."""
    from app.services.ai_rate_limiter import ai_rate_limiter
    stats = ai_rate_limiter.get_user_usage(current_user.id)
    return jsonify({'success': True, **stats})


@ai_assistant_bp.route('/rate', methods=['POST'])
@login_required
def rate_response():
    """Rate an AI response (thumbs up/down)."""
    from app.models.ai_assistant import AIAssistantLog
    from app.core import db

    data = request.get_json()
    log_id = data.get('log_id')
    rating = data.get('rating')  # 1 or 5

    if not log_id or rating not in (1, 5):
        return jsonify({'success': False, 'message': 'Invalid rating.'}), 400

    log = AIAssistantLog.query.filter_by(id=log_id, user_id=current_user.id).first()
    if not log:
        return jsonify({'success': False, 'message': 'Log not found.'}), 404

    log.user_rating = rating
    db.session.commit()

    return jsonify({'success': True})


# =============================================================================
# ADMIN DASHBOARD
# =============================================================================

@ai_assistant_bp.route('/admin/metrics')
@login_required
@role_required(['Global Admin'])
def admin_metrics():
    """AI Assistant admin dashboard page."""
    return render_template('admin_panel/ai_assistant/metrics_flowbite.html')


@ai_assistant_bp.route('/admin/metrics/data')
@login_required
@role_required(['Global Admin'])
def admin_metrics_data():
    """AI Assistant admin metrics JSON endpoint."""
    from app.models.ai_assistant import AIAssistantLog
    from app.services.ai_rate_limiter import ai_rate_limiter

    period = request.args.get('period', '30')
    days = int(period) if period.isdigit() else 30

    db_stats = AIAssistantLog.get_usage_stats(days=days)
    redis_stats = ai_rate_limiter.get_global_stats()

    # Provider breakdown
    from app.core import db as flask_db
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)

    provider_counts = flask_db.session.query(
        AIAssistantLog.provider,
        flask_db.func.count(AIAssistantLog.id)
    ).filter(
        AIAssistantLog.created_at >= cutoff,
        AIAssistantLog.was_rejected == False
    ).group_by(AIAssistantLog.provider).all()

    # Top questions
    top_questions = flask_db.session.query(
        AIAssistantLog.user_message,
        flask_db.func.count(AIAssistantLog.id).label('count')
    ).filter(
        AIAssistantLog.created_at >= cutoff,
        AIAssistantLog.was_rejected == False
    ).group_by(AIAssistantLog.user_message).order_by(
        flask_db.func.count(AIAssistantLog.id).desc()
    ).limit(10).all()

    return jsonify({
        'success': True,
        **db_stats,
        **redis_stats,
        'provider_breakdown': {p: c for p, c in provider_counts if p},
        'top_questions': [{'question': q[:100], 'count': c} for q, c in top_questions],
    })


@ai_assistant_bp.route('/admin/config', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def admin_config_update():
    """Update AI assistant configuration."""
    from app.models.admin_config import AdminConfig, AdminAuditLog

    data = request.get_json()
    updates = []

    config_keys = {
        'ai_assistant_enabled': 'boolean',
        'ai_assistant_primary_provider': 'string',
        'ai_assistant_claude_model': 'string',
        'ai_assistant_openai_model': 'string',
        'ai_assistant_rate_limit_per_hour': 'integer',
        'ai_assistant_rate_limit_per_day': 'integer',
        'ai_assistant_global_rate_limit_per_day': 'integer',
        'ai_assistant_monthly_budget_usd': 'string',
        'ai_assistant_max_tokens': 'integer',
    }

    for key, dtype in config_keys.items():
        if key in data:
            old = AdminConfig.get_setting(key)
            new_val = data[key]
            AdminConfig.set_setting(
                key, new_val,
                description=f'AI Assistant: {key}',
                category='ai_assistant',
                data_type=dtype,
                user_id=current_user.id
            )
            if str(old) != str(new_val):
                updates.append(f'{key}: {old} -> {new_val}')

    if updates:
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='update_ai_assistant_config',
            resource_type='ai_assistant',
            resource_id='config',
            new_value='; '.join(updates),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

    return jsonify({'success': True, 'message': f'Updated {len(updates)} settings.'})
