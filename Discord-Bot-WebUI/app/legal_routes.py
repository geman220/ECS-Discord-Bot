"""
Legal Routes Module

This module provides public routes for legal pages like Privacy Policy and Terms of Service.
These routes are accessible without authentication.
"""

from flask import Blueprint, render_template

legal_bp = Blueprint('legal', __name__)


@legal_bp.route('/privacy')
def privacy_policy():
    """Display the privacy policy page."""
    return render_template('legal/privacy_policy.html')


@legal_bp.route('/terms')
def terms_of_service():
    """Display the terms of service page."""
    return render_template('legal/terms_of_service.html')


# Alias routes for app store requirements
@legal_bp.route('/privacy-policy')
def privacy_policy_alias():
    """Alias for /privacy for app store compatibility."""
    return render_template('legal/privacy_policy.html')


@legal_bp.route('/terms-of-service')
def terms_of_service_alias():
    """Alias for /terms for app store compatibility."""
    return render_template('legal/terms_of_service.html')
