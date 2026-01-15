# app/admin/wallet/location_routes.py

"""
Wallet Location Management Routes

Handles partner venue/location management for location-based notifications.
Apple Wallet supports up to 10 locations per pass.
"""

import logging
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required

from app.core import db
from app.utils.db_utils import transactional
from app.models.wallet_config import WalletLocation, WalletSubgroup
from app.decorators import role_required

from . import wallet_config_bp

logger = logging.getLogger(__name__)


# =============================================================================
# LOCATIONS
# =============================================================================

@wallet_config_bp.route('/locations')
@login_required
@role_required(['Global Admin'])
def locations():
    """Location management page"""
    try:
        all_locations = WalletLocation.query.order_by(
            WalletLocation.display_order, WalletLocation.name
        ).all()

        return render_template(
            'admin/wallet_config/locations_flowbite.html',
            locations=all_locations
        )

    except Exception as e:
        logger.error(f"Error loading locations page: {str(e)}", exc_info=True)
        flash('Error loading locations page.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/locations/add', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def add_location():
    """Add a new partner location"""
    try:
        location = WalletLocation(
            name=request.form.get('name'),
            latitude=float(request.form.get('latitude')),
            longitude=float(request.form.get('longitude')),
            relevant_text=request.form.get('relevant_text') or request.form.get('name'),
            address=request.form.get('address'),
            city=request.form.get('city'),
            state=request.form.get('state'),
            applies_to=request.form.get('applies_to', 'all'),
            location_type=request.form.get('location_type', 'partner_bar'),
            is_active=request.form.get('is_active') == 'on'
        )
        db.session.add(location)

        flash(f'Location "{location.name}" added successfully.', 'success')
        return redirect(url_for('wallet_config.locations'))

    except Exception as e:
        logger.error(f"Error adding location: {str(e)}", exc_info=True)
        flash(f'Error adding location: {str(e)}', 'error')
        return redirect(url_for('wallet_config.locations'))


@wallet_config_bp.route('/locations/<int:location_id>/edit', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def edit_location(location_id):
    """Edit an existing location"""
    try:
        location = WalletLocation.query.get_or_404(location_id)

        location.name = request.form.get('name', location.name)
        location.latitude = float(request.form.get('latitude', location.latitude))
        location.longitude = float(request.form.get('longitude', location.longitude))
        location.relevant_text = request.form.get('relevant_text', location.relevant_text)
        location.address = request.form.get('address')
        location.city = request.form.get('city')
        location.state = request.form.get('state')
        location.applies_to = request.form.get('applies_to', 'all')
        location.location_type = request.form.get('location_type', 'partner_bar')
        location.is_active = request.form.get('is_active') == 'on'

        flash(f'Location "{location.name}" updated successfully.', 'success')
        return redirect(url_for('wallet_config.locations'))

    except Exception as e:
        logger.error(f"Error updating location: {str(e)}", exc_info=True)
        flash(f'Error updating location: {str(e)}', 'error')
        return redirect(url_for('wallet_config.locations'))


@wallet_config_bp.route('/locations/<int:location_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def delete_location(location_id):
    """Delete a location"""
    try:
        location = WalletLocation.query.get_or_404(location_id)
        name = location.name
        db.session.delete(location)

        flash(f'Location "{name}" deleted successfully.', 'success')
        return redirect(url_for('wallet_config.locations'))

    except Exception as e:
        logger.error(f"Error deleting location: {str(e)}", exc_info=True)
        flash(f'Error deleting location: {str(e)}', 'error')
        return redirect(url_for('wallet_config.locations'))


@wallet_config_bp.route('/locations/<int:location_id>/toggle', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def toggle_location(location_id):
    """Toggle location active status"""
    try:
        location = WalletLocation.query.get_or_404(location_id)
        location.is_active = not location.is_active

        status = 'activated' if location.is_active else 'deactivated'
        flash(f'Location "{location.name}" {status}.', 'success')
        return redirect(url_for('wallet_config.locations'))

    except Exception as e:
        logger.error(f"Error toggling location: {str(e)}", exc_info=True)
        flash(f'Error toggling location: {str(e)}', 'error')
        return redirect(url_for('wallet_config.locations'))


# =============================================================================
# SUBGROUPS (ECS Supporter Subgroups)
# =============================================================================

@wallet_config_bp.route('/subgroups')
@login_required
@role_required(['Global Admin'])
def subgroups():
    """Subgroup management page for ECS supporter subgroups"""
    try:
        all_subgroups = WalletSubgroup.query.order_by(
            WalletSubgroup.display_order, WalletSubgroup.name
        ).all()

        return render_template(
            'admin/wallet_config/subgroups_flowbite.html',
            subgroups=all_subgroups
        )

    except Exception as e:
        logger.error(f"Error loading subgroups page: {str(e)}", exc_info=True)
        flash('Error loading subgroups page.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/subgroups/add', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def add_subgroup():
    """Add a new subgroup"""
    try:
        code = request.form.get('code', '').lower().replace(' ', '_').replace('-', '_')
        subgroup = WalletSubgroup(
            code=code,
            name=request.form.get('name'),
            description=request.form.get('description'),
            is_active=request.form.get('is_active') == 'on'
        )
        db.session.add(subgroup)

        flash(f'Subgroup "{subgroup.name}" added successfully.', 'success')
        return redirect(url_for('wallet_config.subgroups'))

    except Exception as e:
        logger.error(f"Error adding subgroup: {str(e)}", exc_info=True)
        flash(f'Error adding subgroup: {str(e)}', 'error')
        return redirect(url_for('wallet_config.subgroups'))


@wallet_config_bp.route('/subgroups/<int:subgroup_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def delete_subgroup(subgroup_id):
    """Delete a subgroup"""
    try:
        subgroup = WalletSubgroup.query.get_or_404(subgroup_id)
        name = subgroup.name
        db.session.delete(subgroup)

        flash(f'Subgroup "{name}" deleted successfully.', 'success')
        return redirect(url_for('wallet_config.subgroups'))

    except Exception as e:
        logger.error(f"Error deleting subgroup: {str(e)}", exc_info=True)
        flash(f'Error deleting subgroup: {str(e)}', 'error')
        return redirect(url_for('wallet_config.subgroups'))


# =============================================================================
# API ENDPOINTS
# =============================================================================

@wallet_config_bp.route('/api/locations')
@login_required
@role_required(['Global Admin'])
def api_get_locations():
    """Get all locations as JSON"""
    locations = WalletLocation.query.order_by(WalletLocation.display_order).all()
    return jsonify([loc.to_dict() for loc in locations])


@wallet_config_bp.route('/api/subgroups')
@login_required
@role_required(['Global Admin'])
def api_get_subgroups():
    """Get all subgroups as JSON"""
    subgroups = WalletSubgroup.query.order_by(WalletSubgroup.display_order).all()
    return jsonify([s.to_dict() for s in subgroups])
