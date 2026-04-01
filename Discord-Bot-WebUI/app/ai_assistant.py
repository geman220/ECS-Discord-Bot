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


def _build_navigation_guide(context_type, user_roles):
    """Build a structured description of the portal's UI layout so the AI
    knows exactly WHERE things are (sidebar, navbar, user menu) and can give
    accurate navigation directions. Role-filtered to match what the user sees."""

    roles_set = set(user_roles)
    is_admin = bool(roles_set & {'Global Admin', 'Pub League Admin'})
    is_coach = bool(roles_set & {'Pub League Coach', 'ECS FC Coach'})
    is_league_member = bool(roles_set & {'pl-classic', 'pl-premier', 'pl-ecs-fc'})

    lines = [
        "## Portal Layout",
        "The portal has three navigation areas:",
        "- LEFT SIDEBAR: The main navigation menu on the left side of the screen.",
        "- TOP NAVBAR: A horizontal bar at the top with search, AI assistant, dark mode, notifications, and your user avatar.",
        "- USER MENU: Click your avatar/profile picture in the TOP-RIGHT corner to open a dropdown with My Profile, Settings, and Sign Out.",
        "",
        "## Sidebar Navigation (left side)",
        "",
        "### MAIN section (visible to all users)",
        "- [Dashboard](/) — Your home page with an overview",
        "- [Submit Feedback](/feedback) — Send feedback to the league admins",
    ]

    if is_coach or is_admin:
        lines.append("- [Coach Dashboard](/teams/coach-dashboard) — Manage your team, view lineups")

    lines.append("- [Help Topics](/help) — Browse help articles and FAQs")

    # ECS FC League section
    can_view_draft = is_admin or is_coach
    can_view_teams = is_admin or is_coach or is_league_member
    can_view_standings = is_admin or is_coach
    can_view_calendar = is_admin or is_coach or is_league_member or ('Pub League Ref' in roles_set)

    if can_view_draft or can_view_teams or can_view_standings or can_view_calendar:
        lines.append("")
        lines.append("### ECS FC LEAGUE section")
        if can_view_draft:
            lines.append("- Draft (dropdown): [Classic Division](/draft/classic), [Premier Division](/draft/premier), [ECS FC Division](/draft/ecs_fc)")
            if is_admin or ('Pub League Coach' in roles_set):
                lines.append("  - [Draft Predictions](/draft-predictions)")
            if is_admin:
                lines.append("  - [Draft History](/admin-panel/draft/history)")
        if can_view_teams:
            lines.append("- [Teams Overview](/teams/overview) — View all teams and rosters. Click any team name to see their full roster, schedule, and match history.")
        if can_view_standings:
            lines.append("- [Standings](/teams/standings) — League standings and rankings")
        if is_admin or ('Pub League Coach' in roles_set):
            lines.append("- [League Store](/store) — Order league merchandise (coaches & admins)")
        if can_view_calendar:
            lines.append("- [Calendar](/calendar) — Match schedule and events")

    # Common workflows that aren't in the sidebar but users frequently ask about
    if is_league_member or is_coach or is_admin:
        lines.append("")
        lines.append("## Common Workflows")
        lines.append("- **RSVP for a match**: RSVP links are sent via email/SMS before each match. Click the link in the notification to RSVP. You can also RSVP from your team's match page in [Calendar](/calendar).")
        lines.append("- **View your player profile**: Click your avatar in the top-right, then 'My Profile'. You can also find any player by searching their name using the search bar in the top navbar.")
        lines.append("- **Change your password or settings**: Go to [Settings](/account/settings) from the user menu (top-right avatar dropdown).")
        lines.append("- **Link your Discord account**: Go to [Settings](/account/settings), then the Discord section to connect your Discord account.")

    # Administration section
    if is_admin:
        lines.append("")
        lines.append("### ADMINISTRATION section (admins only)")
        lines.append("- [Admin Panel](/admin-panel/) — The main admin hub with ALL management tools (users, roles, leagues, Discord, reports, monitoring, etc.)")
        lines.append("- Digital Wallets (dropdown): [Setup Wizard](/wallet/config/setup), [Dashboard](/wallet/admin), [Pass Studio](/pass-studio), [Manage Passes](/wallet/admin/passes), [Scanner](/wallet/admin/scanner), [Check-ins](/wallet/admin/checkins)")
        lines.append("")
        lines.append("NOTE: ALL admin features are accessed through the [Admin Panel](/admin-panel/). NEVER direct admins to just '/admin-panel/' — use the specific sub-page URLs from the admin pages list below.")

    # User menu (top-right)
    lines.append("")
    lines.append("## User Menu (top-right avatar dropdown)")
    lines.append("Click your profile picture/avatar in the top-right corner of the navbar:")
    lines.append("- [My Profile](/players/<your_id>) — View and edit your player profile")
    lines.append("- [Settings](/account/settings) — Account settings, password, 2FA, notifications, Discord linking")
    lines.append("- Sign Out — Log out of the portal")

    # Key navigation facts to prevent common AI mistakes
    lines.append("")
    lines.append("## IMPORTANT Navigation Facts")
    lines.append("- The Admin Panel is in the LEFT SIDEBAR under the 'ADMINISTRATION' section header. It is NOT in the user profile/avatar dropdown.")
    lines.append("- The Admin Panel URL is /admin-panel/ — all admin features are inside the Admin Panel.")
    lines.append("- Account Settings and My Profile are in the USER MENU (top-right avatar dropdown). They are NOT in the sidebar.")
    lines.append("- The sidebar is on the LEFT side of the screen. On mobile, tap the hamburger menu icon to reveal it.")
    lines.append("- The AI Assistant (this chat) is opened from the sparkles icon in the TOP NAVBAR.")

    return "\n".join(lines)


def _build_intent_map(admin_search_index):
    """Build keyword-to-page reverse index for intent matching.
    Groups admin pages by common user intents so the AI can quickly
    match questions like 'change roles' to the right page."""
    if not admin_search_index:
        return ""
    intent_groups = {}
    for item in admin_search_index:
        for kw in item.get('keywords', []):
            intent_groups.setdefault(kw, []).append(f"[{item['name']}]({item['url']})")
    lines = ["## Common Task Quick-Reference"]
    for intent, pages in sorted(intent_groups.items()):
        if 1 <= len(pages) <= 3:
            lines.append(f"- \"{intent}\": {', '.join(pages)}")
    return "\n".join(lines[:50])


def _build_app_feature_map(context_type='user_help'):
    """Auto-discover portal features by scanning Flask's live route map.
    Reads real route URLs and docstrings -- no manual maintenance needed.
    Add a route with a docstring and the AI automatically knows about it."""
    from flask import current_app

    features = []

    # Admin-only URL patterns (never shown to users/coaches)
    admin_patterns = [
        '/admin-panel/', '/admin/', '/admin',
        '/ispy/admin', '/bot-admin',
        '/external-api/', '/modals/', '/design/',
        '/clear-cache',
    ]

    # API patterns (internal endpoints, not pages)
    api_patterns = ['/api/', '/mobile-api/', '/ecs-fc-api/']

    if context_type == 'admin_panel':
        # Admin gets everything via the admin search index, skip here
        return []

    seen_urls = set()

    for rule in current_app.url_map.iter_rules():
        # Only GET routes (pages users can visit)
        if 'GET' not in rule.methods:
            continue

        url = rule.rule

        # Skip parameterized URLs, static files, bare root, and internal
        if '<' in url or url.startswith('/static') or url == '/':
            continue

        # Always hide API endpoints
        if any(url.startswith(p) for p in api_patterns):
            continue

        # Role-based filtering
        if context_type == 'coach':
            # Coaches can see ECS FC admin pages but nothing else in admin panel
            is_admin = any(url.startswith(p) for p in admin_patterns)
            is_ecs_fc_admin = url.startswith('/admin-panel/ecs-fc')
            if is_admin and not is_ecs_fc_admin:
                continue
        else:
            # Regular users see zero admin pages
            if any(url.startswith(p) for p in admin_patterns):
                continue

        # Skip duplicates
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Get the view function's docstring
        try:
            view_func = current_app.view_functions.get(rule.endpoint)
            docstring = (view_func.__doc__ or '').strip().split('\n')[0] if view_func else ''
        except Exception:
            docstring = ''

        if not docstring or len(docstring) < 5:
            continue

        # Clean up the endpoint name for display
        name = rule.endpoint.split('.')[-1].replace('_', ' ').title()

        features.append({
            'name': name,
            'url': url,
            'description': docstring[:150]
        })

    # Sort by URL for readability
    features.sort(key=lambda x: x['url'])

    # Cap at 60 to avoid prompt bloat
    return features[:60]


def _get_user_profile():
    """Build a rich user profile for system prompt personalization."""
    # current_user is UserAuthData with .username, .player_name, .roles (list of strings)
    profile = {
        'name': getattr(current_user, 'player_name', None) or getattr(current_user, 'username', 'User'),
        'roles': [],
        'team_name': None,
        'league_name': None,
        'is_captain': False,
        'profile_url': None,
        'settings_url': '/account/settings',
    }

    try:
        # Respect role impersonation if active
        from app.role_impersonation import get_effective_roles
        effective = get_effective_roles()
        if effective:
            profile['roles'] = effective
        else:
            # UserAuthData.roles is already a list of strings
            profile['roles'] = list(current_user.roles) if current_user.roles else []
    except (ImportError, Exception):
        try:
            profile['roles'] = list(current_user.roles) if current_user.roles else []
        except Exception:
            pass

    try:
        from app.models import Season, League, Team
        from app.models.players import PlayerTeamSeason

        # UserAuthData has player_id (int), not player (relationship)
        player_id = getattr(current_user, 'player_id', None)
        if player_id:
            profile['profile_url'] = f'/players/{player_id}'
        if player_id:
            current_season = Season.query.filter_by(is_current=True).first()
            if current_season:
                pts = PlayerTeamSeason.query.filter_by(
                    player_id=player_id
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
    """Determine context type based on effective user roles and request."""
    requested = request.json.get('context_type', 'auto')

    # Get effective roles (respects impersonation)
    # UserAuthData.roles is already a list of strings
    try:
        from app.role_impersonation import get_effective_roles
        effective = get_effective_roles()
        roles = effective if effective else list(current_user.roles or [])
    except (ImportError, Exception):
        roles = list(current_user.roles or [])

    if requested != 'auto':
        if requested == 'admin_panel':
            if 'Global Admin' not in roles and 'Pub League Admin' not in roles:
                return 'user_help'
        return requested

    if 'Global Admin' in roles or 'Pub League Admin' in roles:
        return 'admin_panel'

    if 'ECS FC Coach' in roles:
        return 'coach'

    return 'user_help'


# Roles that are blocked from AI access entirely
BLOCKED_ROLES = {'pl-unverified', 'pl-waitlist'}

# Canned response for blocked roles (no API call made)
BLOCKED_ROLE_RESPONSE = (
    "Welcome to ECS FC! The AI assistant is available to verified members. "
    "If you need help, please join our Discord at **discord.gg/weareecs** "
    "and ask a Pub League Admin. They'll be happy to help you out!"
)


def _is_ai_allowed():
    """Check if current user's roles allow AI access. Returns (allowed, message)."""
    roles = list(current_user.roles or [])
    roles_lower = {r.lower() for r in roles}

    # Block specific roles
    if roles_lower & {r.lower() for r in BLOCKED_ROLES}:
        # If they ONLY have blocked roles (no other roles that would grant access)
        allowed_roles = roles_lower - {r.lower() for r in BLOCKED_ROLES}
        if not allowed_roles:
            return False, BLOCKED_ROLE_RESPONSE

    return True, None


def _is_on_topic(message):
    """Pre-API check: reject obviously off-topic questions to save API costs.
    Returns (on_topic, rejection_message)."""
    msg_lower = message.lower()

    # Off-topic patterns that have nothing to do with soccer league management
    off_topic_patterns = [
        r'\b(write|generate|create)\s+(me\s+)?(a\s+)?(poem|story|essay|song|code|script|program)\b',
        r'\b(what\s+is|explain|tell\s+me\s+about)\s+(quantum|blockchain|crypto|bitcoin|stock|invest)\b',
        r'\b(translate|convert)\s+.{0,20}\s+(to|into)\s+(french|spanish|german|chinese|japanese)\b',
        r'\bact\s+as\s+(a|an)\s+',
        r'\broleplay\b',
        r'\b(recipe|cook|bake|ingredient)\b',
        r'\b(homework|math\s+problem|equation|calculus|algebra)\b',
    ]

    for pattern in off_topic_patterns:
        if re.search(pattern, msg_lower):
            return False, "I can only help with questions about the ECS FC Portal and soccer league management. Please ask about portal features, schedules, teams, or how to use the site."

    return True, None


def _validate_message(message):
    """Validate user input. Returns (clean_message, error) tuple."""
    if not message or not message.strip():
        return None, 'Message cannot be empty.'

    message = message.strip()

    if len(message) > 2000:
        return None, 'Message is too long (max 2000 characters).'

    # Prompt injection patterns
    injection_patterns = [
        r'ignore\s+(previous|all|above)\s+instructions',
        r'disregard\s+(your|all)\s+(rules|instructions)',
        r'system\s*prompt',
        r'</system>',
        r'<\|im_start\|>',
        r'you\s+are\s+now\s+',
        r'pretend\s+(to\s+be|you\s+are)',
        r'new\s+instructions?\s*:',
        r'override\s+(your|the)\s+',
    ]
    for pattern in injection_patterns:
        if re.search(pattern, message, re.IGNORECASE):
            return None, 'Your message was not processed. Please rephrase your question about the portal.'

    # Off-topic pre-filter (saves API costs)
    on_topic, topic_msg = _is_on_topic(message)
    if not on_topic:
        return None, topic_msg

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

    # Check role-based access (block pl-unverified, pl-waitlist)
    allowed, blocked_msg = _is_ai_allowed()
    if not allowed:
        return jsonify({'success': True, 'response': blocked_msg, 'provider': 'canned', 'log_id': None})

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
    user_page_index = None

    # Build navigation guide (all context types)
    navigation_guide = _build_navigation_guide(context_type, user_profile.get('roles', []))

    # Admin search index (admin + coach contexts)
    if context_type in ('admin_panel', 'coach'):
        try:
            from app.admin_panel import _build_admin_search_index
            admin_search_index = _build_admin_search_index()
        except Exception:
            admin_search_index = []

    # User-facing page index (coach + user contexts)
    if context_type in ('coach', 'user_help'):
        user_page_index = _build_app_feature_map(context_type)

    # HelpTopics for ALL non-admin contexts (dynamic knowledge base)
    if context_type in ('coach', 'user_help'):
        try:
            from app.help import get_accessible_roles
            from app.models.external import HelpTopic
            from app.models.core import Role

            accessible_role_names = get_accessible_roles(user_profile.get('roles', []))

            topics = HelpTopic.query.filter(
                HelpTopic.roles.any(Role.name.in_(accessible_role_names))
            ).all()

            help_topics = [
                {'title': t.title, 'content': t.content[:500]}
                for t in topics[:30]
            ]
        except Exception:
            help_topics = []

    # Build intent map for admin contexts (keyword-to-page reverse index)
    intent_map = _build_intent_map(admin_search_index) if admin_search_index else None

    system_prompt = ai_assistant_service.build_system_prompt(
        context_type, user_profile, admin_search_index, help_topics, user_page_index,
        navigation_guide=navigation_guide, intent_map=intent_map
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
    # UserAuthData.roles is already a list of strings
    user_roles = list(current_user.roles) if current_user.roles else []
    user_roles_lower = {r.lower() for r in user_roles}

    # Blocked roles get no suggestions (widget is hidden, but just in case)
    if user_roles_lower & {r.lower() for r in BLOCKED_ROLES}:
        allowed_roles = user_roles_lower - {r.lower() for r in BLOCKED_ROLES}
        if not allowed_roles:
            return jsonify({'success': True, 'suggestions': ['Join our Discord for help: discord.gg/weareecs']})

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

    # Per-user breakdown (top 10 users by request count)
    from app.models.core import User
    per_user = flask_db.session.query(
        AIAssistantLog.user_id,
        User.username,
        flask_db.func.count(AIAssistantLog.id).label('count')
    ).join(User, AIAssistantLog.user_id == User.id).filter(
        AIAssistantLog.created_at >= cutoff
    ).group_by(AIAssistantLog.user_id, User.username).order_by(
        flask_db.func.count(AIAssistantLog.id).desc()
    ).limit(10).all()

    # Circuit breaker status
    from app.services.ai_assistant_service import ai_assistant_service
    circuit_breaker = {
        'claude': {
            'failures': ai_assistant_service._failures.get('claude', 0),
            'open': ai_assistant_service._is_circuit_open('claude'),
        },
        'openai': {
            'failures': ai_assistant_service._failures.get('openai', 0),
            'open': ai_assistant_service._is_circuit_open('openai'),
        }
    }

    # Poorly rated responses (thumbs down) for review
    poorly_rated = flask_db.session.query(
        AIAssistantLog.id,
        AIAssistantLog.user_message,
        AIAssistantLog.assistant_response,
        User.username,
        AIAssistantLog.created_at
    ).join(User, AIAssistantLog.user_id == User.id).filter(
        AIAssistantLog.created_at >= cutoff,
        AIAssistantLog.user_rating == 1
    ).order_by(AIAssistantLog.created_at.desc()).limit(20).all()

    return jsonify({
        'success': True,
        **db_stats,
        **redis_stats,
        'provider_breakdown': {p: c for p, c in provider_counts if p},
        'top_questions': [{'question': q[:100], 'count': c} for q, c in top_questions],
        'per_user': [{'username': u, 'count': c} for _, u, c in per_user],
        'circuit_breaker': circuit_breaker,
        'poorly_rated': [
            {
                'id': log_id,
                'question': msg[:150],
                'response': (resp or '')[:200],
                'username': uname,
                'date': dt.strftime('%Y-%m-%d %H:%M') if dt else '',
            }
            for log_id, msg, resp, uname, dt in poorly_rated
        ],
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
