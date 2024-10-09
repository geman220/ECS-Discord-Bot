# app/blueprints.py

import email


def register_blueprints(app):
    from app.auth import auth as auth_bp
    from app.publeague import publeague as publeague_bp
    from app.draft import draft as draft_bp
    from app.players import players_bp
    from app.main import main as main_bp
    from app.teams import teams_bp
    from app.bot_admin import bot_admin_bp
    from app.availability_api import availability_bp
    from app.admin_routes import admin_bp
    from app.match_pages import match_pages
    from app.account import account_bp
    from app.email import email_bp
    from app.feedback import feedback_bp
    from app.user_management import user_management_bp
    from app.calendar import calendar_bp
    from app.sms_rsvp import sms_rsvp_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(publeague_bp, url_prefix='/publeague')
    app.register_blueprint(draft_bp, url_prefix='/draft')
    app.register_blueprint(players_bp, url_prefix='/players')
    app.register_blueprint(teams_bp, url_prefix='/teams')
    app.register_blueprint(availability_bp, url_prefix='/api')
    app.register_blueprint(account_bp, url_prefix='/account')
    app.register_blueprint(match_pages)
    app.register_blueprint(bot_admin_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(email_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(sms_rsvp_bp)
    app.register_blueprint(user_management_bp)