# app/init/blueprints.py

"""
Blueprint Registration

Register all Flask blueprints for modular functionality.
"""

import logging
import os

logger = logging.getLogger(__name__)


def init_blueprints(app, csrf):
    """
    Register blueprints with the Flask application.

    Args:
        app: The Flask application instance.
        csrf: The CSRF protection instance.
    """
    # Import all blueprints
    blueprints = _import_blueprints()

    # Register core blueprints
    _register_core_blueprints(app, blueprints)

    # Register API blueprints
    _register_api_blueprints(app, blueprints, csrf)

    # Register admin blueprints
    _register_admin_blueprints(app, blueprints, csrf)

    # Register wallet blueprints
    _register_wallet_blueprints(app, blueprints, csrf)

    # Register additional blueprints
    _register_additional_blueprints(app, blueprints, csrf)

    # Initialize enterprise systems
    _init_enterprise_systems(app)


def _import_blueprints():
    """Import all blueprint modules and return as a dict."""
    # Auth - modular package
    from app.auth import auth as auth_bp, register_auth_routes
    register_auth_routes()

    from app.publeague import publeague as publeague_bp
    from app.draft_enhanced import draft_enhanced as draft_enhanced_bp
    from app.players import players_bp
    from app.main import main as main_bp
    from app.teams import teams_bp
    from app.bot_admin import bot_admin_bp
    from app.availability_api import availability_bp
    from app.admin.blueprint import admin_bp
    from app.match_pages import match_pages
    from app.account import account_bp
    from app.email import email_bp
    from app.feedback import feedback_bp
    from app.user_management import user_management_bp
    from app.calendar import calendar_bp
    from app.sms_rsvp import sms_rsvp_bp
    from app.match_api import match_api
    from app.monitoring import monitoring_bp
    from app.user_api import user_bp
    from app.help import help_bp
    from app.search import search_bp
    from app.mobile_api.predictions import predictions_api
    from app.design_routes import design as design_bp
    from app.modals import modals as modals_bp
    from app.clear_cache import clear_cache_bp
    from app.external_api import external_api_bp
    from app.auto_schedule_routes import auto_schedule_bp
    from app.role_impersonation import role_impersonation_bp
    from app.ecs_fc_api import ecs_fc_api
    from app.ecs_fc_routes import ecs_fc_routes
    from app.admin.substitute_pool_routes import substitute_pool_bp
    from app.admin.redis_routes import redis_bp
    from app.batch_api import batch_bp
    from app.store import store_bp
    from app.draft_predictions_routes import draft_predictions_bp
    from app.wallet_routes import wallet_bp
    from app.admin.wallet import wallet_admin_bp, wallet_config_bp, pass_studio_bp
    from app.admin.notification_admin_routes import notification_admin_bp
    from app.wallet_pass.routes import public_wallet_bp, webhook_bp, validation_bp
    from app.admin_panel import admin_panel_bp
    from app.routes.notifications import notifications_bp
    from app.routes.navbar_notifications import navbar_notifications_bp
    from app.routes.messages import messages_bp, messages_pages_bp
    from app.api_smart_sync import smart_sync_bp
    from app.routes.health import health_bp
    from app.routes.admin_live_reporting import admin_live_bp
    from app.routes.calendar import calendar_bp as calendar_api_bp
    from app.routes.substitute_rsvp import substitute_rsvp_bp
    from app.legal_routes import legal_bp
    from app.pub_league import pub_league_bp
    from app.routes.app_links import app_links_bp

    return {
        'auth_bp': auth_bp,
        'publeague_bp': publeague_bp,
        'draft_enhanced_bp': draft_enhanced_bp,
        'players_bp': players_bp,
        'main_bp': main_bp,
        'teams_bp': teams_bp,
        'bot_admin_bp': bot_admin_bp,
        'availability_bp': availability_bp,
        'admin_bp': admin_bp,
        'match_pages': match_pages,
        'account_bp': account_bp,
        'email_bp': email_bp,
        'feedback_bp': feedback_bp,
        'user_management_bp': user_management_bp,
        'calendar_bp': calendar_bp,
        'sms_rsvp_bp': sms_rsvp_bp,
        'match_api': match_api,
        'monitoring_bp': monitoring_bp,
        'user_bp': user_bp,
        'help_bp': help_bp,
        'search_bp': search_bp,
        'predictions_api': predictions_api,
        'design_bp': design_bp,
        'modals_bp': modals_bp,
        'clear_cache_bp': clear_cache_bp,
        'external_api_bp': external_api_bp,
        'auto_schedule_bp': auto_schedule_bp,
        'role_impersonation_bp': role_impersonation_bp,
        'ecs_fc_api': ecs_fc_api,
        'ecs_fc_routes': ecs_fc_routes,
        'substitute_pool_bp': substitute_pool_bp,
        'redis_bp': redis_bp,
        'batch_bp': batch_bp,
        'store_bp': store_bp,
        'draft_predictions_bp': draft_predictions_bp,
        'wallet_bp': wallet_bp,
        'wallet_admin_bp': wallet_admin_bp,
        'wallet_config_bp': wallet_config_bp,
        'pass_studio_bp': pass_studio_bp,
        'notification_admin_bp': notification_admin_bp,
        'public_wallet_bp': public_wallet_bp,
        'webhook_bp': webhook_bp,
        'validation_bp': validation_bp,
        'admin_panel_bp': admin_panel_bp,
        'notifications_bp': notifications_bp,
        'navbar_notifications_bp': navbar_notifications_bp,
        'messages_bp': messages_bp,
        'messages_pages_bp': messages_pages_bp,
        'smart_sync_bp': smart_sync_bp,
        'health_bp': health_bp,
        'admin_live_bp': admin_live_bp,
        'calendar_api_bp': calendar_api_bp,
        'substitute_rsvp_bp': substitute_rsvp_bp,
        'legal_bp': legal_bp,
        'pub_league_bp': pub_league_bp,
        'app_links_bp': app_links_bp,
    }


def _register_core_blueprints(app, bp):
    """Register core application blueprints."""
    app.register_blueprint(bp['health_bp'], url_prefix='/api')
    app.register_blueprint(bp['auth_bp'], url_prefix='/auth')
    app.register_blueprint(bp['publeague_bp'], url_prefix='/publeague')
    app.register_blueprint(bp['draft_enhanced_bp'], url_prefix='/draft')
    app.register_blueprint(bp['players_bp'], url_prefix='/players')
    app.register_blueprint(bp['teams_bp'], url_prefix='/teams')
    app.register_blueprint(bp['availability_bp'], url_prefix='/api')
    app.register_blueprint(bp['batch_bp'])
    app.register_blueprint(bp['account_bp'], url_prefix='/account')
    app.register_blueprint(bp['match_pages'])
    app.register_blueprint(bp['bot_admin_bp'])
    app.register_blueprint(bp['main_bp'])
    app.register_blueprint(bp['admin_bp'])
    app.register_blueprint(bp['feedback_bp'])
    app.register_blueprint(bp['email_bp'])
    app.register_blueprint(bp['calendar_bp'])
    app.register_blueprint(bp['sms_rsvp_bp'])
    app.register_blueprint(bp['match_api'], url_prefix='/api')
    app.register_blueprint(bp['user_management_bp'])


def _register_api_blueprints(app, bp, csrf):
    """Register API blueprints."""
    # Mobile API - modular package
    from app.mobile_api import init_mobile_api
    init_mobile_api(app, csrf)

    # Mobile substitute API
    from app.routes.mobile_substitute_api import mobile_substitute_api
    app.register_blueprint(mobile_substitute_api, url_prefix='/api/v1')
    csrf.exempt(mobile_substitute_api)

    app.register_blueprint(bp['user_bp'], url_prefix='/api')
    app.register_blueprint(bp['predictions_api'], url_prefix='/api')

    # Monitoring - modular package
    from app.monitoring import register_monitoring_routes
    register_monitoring_routes()
    app.register_blueprint(bp['monitoring_bp'])

    app.register_blueprint(bp['help_bp'], url_prefix='/help')
    app.register_blueprint(bp['search_bp'])
    app.register_blueprint(bp['design_bp'], url_prefix='/design')
    app.register_blueprint(bp['modals_bp'], url_prefix='/modals')
    app.register_blueprint(bp['clear_cache_bp'])
    app.register_blueprint(bp['external_api_bp'])
    app.register_blueprint(bp['auto_schedule_bp'], url_prefix='/auto-schedule')
    app.register_blueprint(bp['role_impersonation_bp'])
    app.register_blueprint(bp['ecs_fc_api'])
    app.register_blueprint(bp['ecs_fc_routes'])  # ECS FC web routes (match details, report)
    app.register_blueprint(bp['substitute_pool_bp'])
    app.register_blueprint(bp['redis_bp'])
    app.register_blueprint(bp['store_bp'])
    app.register_blueprint(bp['draft_predictions_bp'])
    app.register_blueprint(bp['notifications_bp'])
    app.register_blueprint(bp['navbar_notifications_bp'])  # In-app notifications for navbar
    # Exempt navbar notifications from CSRF - presence refresh is a background heartbeat
    csrf.exempt(bp['navbar_notifications_bp'])

    # Register rate limit exemptions for high-frequency presence endpoints
    from app.routes.navbar_notifications import register_rate_limit_exemptions
    register_rate_limit_exemptions(app)
    app.register_blueprint(bp['messages_bp'])  # Direct messaging API
    app.register_blueprint(bp['messages_pages_bp'])  # Messages inbox page
    app.register_blueprint(bp['smart_sync_bp'])
    csrf.exempt(bp['smart_sync_bp'])
    app.register_blueprint(bp['admin_live_bp'])

    # Calendar API (enhanced calendar with league events and iCal subscriptions)
    app.register_blueprint(bp['calendar_api_bp'])
    # Exempt the iCal feed endpoint from CSRF (needs to be accessible by calendar clients)
    csrf.exempt(bp['calendar_api_bp'])


def _register_admin_blueprints(app, bp, csrf):
    """Register admin-related blueprints."""
    app.register_blueprint(bp['notification_admin_bp'])
    app.register_blueprint(bp['admin_panel_bp'])

    # Playoff management
    from app.playoff_routes import playoff_bp, api_playoffs_bp
    app.register_blueprint(playoff_bp)
    app.register_blueprint(api_playoffs_bp)

    # Cache admin
    from app.cache_admin_routes import cache_admin_bp
    app.register_blueprint(cache_admin_bp)

    # Enterprise RSVP
    from app.api_enterprise_rsvp import enterprise_rsvp_bp
    app.register_blueprint(enterprise_rsvp_bp)

    # Observability
    from app.api_observability import observability_bp
    app.register_blueprint(observability_bp)

    # Mobile analytics
    from app.api_mobile_analytics import mobile_analytics_bp
    app.register_blueprint(mobile_analytics_bp)

    # Team notifications
    from app.api_team_notifications import team_notifications_bp
    app.register_blueprint(team_notifications_bp)

    # Duplicate management
    from app.admin.duplicate_management_routes import duplicate_management
    app.register_blueprint(duplicate_management)

    # Pub League Orders admin
    from app.admin.pub_league_orders_routes import pub_league_orders_admin_bp
    app.register_blueprint(pub_league_orders_admin_bp)

    # AI Prompt Management
    from app.routes.ai_prompts import ai_prompts_bp
    app.register_blueprint(ai_prompts_bp)

    # AI Enhancement Routes
    from app.routes.ai_enhancement_routes import ai_enhancement_bp
    app.register_blueprint(ai_enhancement_bp)
    csrf.exempt(ai_enhancement_bp)

    # Security Status Routes
    try:
        app.logger.info("🔧 Attempting to import Security Status Blueprint...")
        from app.routes.security_status import security_status_bp
        app.logger.info("🔧 Security Status Blueprint imported, registering routes...")
        app.register_blueprint(security_status_bp, url_prefix='')
        app.logger.info("✅ Security Status Blueprint registered successfully")

        security_routes = []
        for rule in app.url_map.iter_rules():
            if rule.endpoint and rule.endpoint.startswith('security_status.'):
                security_routes.append(f"{rule.rule} -> {rule.endpoint}")
        if security_routes:
            app.logger.info(f"🔧 Security routes registered: {security_routes}")
        else:
            app.logger.warning("⚠️ No security routes found after registration")

    except ImportError as ie:
        app.logger.error(f"❌ Import error for Security Status Blueprint: {ie}")
    except Exception as e:
        app.logger.error(f"❌ Failed to register Security Status Blueprint: {e}")


def _register_wallet_blueprints(app, bp, csrf):
    """Register wallet-related blueprints."""
    # Ensure wallet database schema is up to date
    try:
        from app.models.wallet import ensure_wallet_columns
        with app.app_context():
            ensure_wallet_columns()
    except Exception as e:
        logger.warning(f"Could not ensure wallet columns (may be first run): {e}")

    app.register_blueprint(bp['wallet_bp'])
    app.register_blueprint(bp['wallet_admin_bp'])
    app.register_blueprint(bp['wallet_config_bp'])
    app.register_blueprint(bp['pass_studio_bp'])
    app.register_blueprint(bp['public_wallet_bp'])
    app.register_blueprint(bp['webhook_bp'])
    app.register_blueprint(bp['validation_bp'])
    csrf.exempt(bp['webhook_bp'])
    csrf.exempt(bp['validation_bp'])

    # Register Apple Wallet web service routes
    try:
        from app.wallet_pass.services.push_service import register_apple_wallet_routes
        register_apple_wallet_routes(app)
        apple_wallet_bp = app.blueprints.get('apple_wallet')
        if apple_wallet_bp:
            csrf.exempt(apple_wallet_bp)
    except Exception as e:
        logger.warning(f"Could not register Apple Wallet routes: {e}")


def _register_additional_blueprints(app, bp, csrf):
    """Register any additional blueprints not covered elsewhere."""
    # Substitute RSVP (public-facing RSVP pages for subs)
    app.register_blueprint(bp['substitute_rsvp_bp'])

    # Legal pages (Privacy Policy, Terms of Service) - public routes
    app.register_blueprint(bp['legal_bp'])

    # Pub League order linking (WooCommerce order → player activation → wallet pass)
    app.register_blueprint(bp['pub_league_bp'])

    # App Links (iOS Universal Links and Android App Links configuration)
    app.register_blueprint(bp['app_links_bp'])


def _init_enterprise_systems(app):
    """Initialize enterprise systems on app startup."""
    try:
        if not app.config.get('TESTING') and not os.environ.get('CELERY_WORKER'):
            logger.info("🚀 Enterprise RSVP system ready for initialization")
            logger.info("✅ Enterprise RSVP endpoints are active and ready")
        else:
            logger.info("ℹ️ Skipping enterprise RSVP initialization in worker process")
    except Exception as e:
        logger.error(f"❌ Enterprise RSVP initialization error: {e}")
