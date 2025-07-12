# app/admin/blueprint.py

"""
Shared admin blueprint for all admin routes.
This prevents circular imports by providing a single source for the admin blueprint.
"""

from flask import Blueprint

admin_bp = Blueprint('admin', __name__)

# Import and register ECS FC sub routes
from app.admin.ecs_fc_sub_routes import ecs_fc_subs_bp
admin_bp.register_blueprint(ecs_fc_subs_bp)

# Import and register substitute pool routes
from app.admin.substitute_pool_routes import substitute_pool_bp
admin_bp.register_blueprint(substitute_pool_bp)

# Import main admin routes to register them with this blueprint
from app import admin_routes

# Import draft history routes (no separate blueprint needed, uses admin_bp directly)
from app.admin import draft_history_routes

# Import Discord onboarding routes
from app.admin.discord_onboarding_routes import discord_onboarding
admin_bp.register_blueprint(discord_onboarding)

# Import message configuration routes
from app.admin.message_config_routes import message_config
admin_bp.register_blueprint(message_config)