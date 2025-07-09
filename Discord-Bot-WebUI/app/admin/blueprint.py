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