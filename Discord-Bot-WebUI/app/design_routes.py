# app/design_routes.py

"""
Design System Routes

This module defines routes related to the design system, including the design guide.
"""

from flask import Blueprint, render_template
from flask_login import login_required
from app.decorators import role_required
from app.utils.user_helpers import safe_current_user

design = Blueprint('design', __name__)


@design.route('/design-guide', endpoint='design_guide', methods=['GET'])
@login_required
@role_required('Global Admin')  # Restrict access to admins
def design_guide():
    """
    Render the design system guide page for developers.
    
    This page provides guidance on using the ECS Soccer League Design System
    consistently throughout the application.
    
    Returns:
        Rendered template of the design guide.
    """
    return render_template('design-guide_flowbite.html', title='Design System Guide')