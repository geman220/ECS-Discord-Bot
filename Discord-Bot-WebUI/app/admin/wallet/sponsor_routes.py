# app/admin/wallet/sponsor_routes.py

"""
Wallet Sponsor Management Routes

Handles sponsor management for wallet passes.
Sponsors can appear on the back of passes or in auxiliary fields.
"""

import logging
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required

from app.core import db
from app.models.wallet_config import WalletSponsor
from app.decorators import role_required

from . import wallet_config_bp

logger = logging.getLogger(__name__)


# =============================================================================
# SPONSORS
# =============================================================================

@wallet_config_bp.route('/sponsors')
@login_required
@role_required(['Global Admin'])
def sponsors():
    """Sponsor management page"""
    try:
        all_sponsors = WalletSponsor.query.order_by(
            WalletSponsor.display_order, WalletSponsor.name
        ).all()

        return render_template(
            'admin/wallet_config/sponsors_flowbite.html',
            sponsors=all_sponsors
        )

    except Exception as e:
        logger.error(f"Error loading sponsors page: {str(e)}", exc_info=True)
        flash('Error loading sponsors page.', 'error')
        return redirect(url_for('wallet_config.dashboard'))


@wallet_config_bp.route('/sponsors/add', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def add_sponsor():
    """Add a new sponsor"""
    try:
        sponsor = WalletSponsor(
            name=request.form.get('name'),
            display_name=request.form.get('display_name') or request.form.get('name'),
            description=request.form.get('description'),
            website_url=request.form.get('website_url'),
            applies_to=request.form.get('applies_to', 'all'),
            display_location=request.form.get('display_location', 'back'),
            sponsor_type=request.form.get('sponsor_type', 'partner'),
            is_active=request.form.get('is_active') == 'on'
        )
        db.session.add(sponsor)
        db.session.commit()

        flash(f'Sponsor "{sponsor.name}" added successfully.', 'success')
        return redirect(url_for('wallet_config.sponsors'))

    except Exception as e:
        logger.error(f"Error adding sponsor: {str(e)}", exc_info=True)
        flash(f'Error adding sponsor: {str(e)}', 'error')
        return redirect(url_for('wallet_config.sponsors'))


@wallet_config_bp.route('/sponsors/<int:sponsor_id>/edit', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def edit_sponsor(sponsor_id):
    """Edit an existing sponsor"""
    try:
        sponsor = WalletSponsor.query.get_or_404(sponsor_id)

        sponsor.name = request.form.get('name', sponsor.name)
        sponsor.display_name = request.form.get('display_name', sponsor.display_name)
        sponsor.description = request.form.get('description')
        sponsor.website_url = request.form.get('website_url')
        sponsor.applies_to = request.form.get('applies_to', 'all')
        sponsor.display_location = request.form.get('display_location', 'back')
        sponsor.sponsor_type = request.form.get('sponsor_type', 'partner')
        sponsor.is_active = request.form.get('is_active') == 'on'

        db.session.commit()

        flash(f'Sponsor "{sponsor.name}" updated successfully.', 'success')
        return redirect(url_for('wallet_config.sponsors'))

    except Exception as e:
        logger.error(f"Error updating sponsor: {str(e)}", exc_info=True)
        flash(f'Error updating sponsor: {str(e)}', 'error')
        return redirect(url_for('wallet_config.sponsors'))


@wallet_config_bp.route('/sponsors/<int:sponsor_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_sponsor(sponsor_id):
    """Delete a sponsor"""
    try:
        sponsor = WalletSponsor.query.get_or_404(sponsor_id)
        name = sponsor.name
        db.session.delete(sponsor)
        db.session.commit()

        flash(f'Sponsor "{name}" deleted successfully.', 'success')
        return redirect(url_for('wallet_config.sponsors'))

    except Exception as e:
        logger.error(f"Error deleting sponsor: {str(e)}", exc_info=True)
        flash(f'Error deleting sponsor: {str(e)}', 'error')
        return redirect(url_for('wallet_config.sponsors'))


@wallet_config_bp.route('/sponsors/<int:sponsor_id>/toggle', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def toggle_sponsor(sponsor_id):
    """Toggle sponsor active status"""
    try:
        sponsor = WalletSponsor.query.get_or_404(sponsor_id)
        sponsor.is_active = not sponsor.is_active
        db.session.commit()

        status = 'activated' if sponsor.is_active else 'deactivated'
        flash(f'Sponsor "{sponsor.name}" {status}.', 'success')
        return redirect(url_for('wallet_config.sponsors'))

    except Exception as e:
        logger.error(f"Error toggling sponsor: {str(e)}", exc_info=True)
        flash(f'Error toggling sponsor: {str(e)}', 'error')
        return redirect(url_for('wallet_config.sponsors'))


# =============================================================================
# API ENDPOINTS
# =============================================================================

@wallet_config_bp.route('/api/sponsors')
@login_required
@role_required(['Global Admin'])
def api_get_sponsors():
    """Get all sponsors as JSON"""
    sponsors = WalletSponsor.query.order_by(WalletSponsor.display_order).all()
    return jsonify([s.to_dict() for s in sponsors])
