# app/routes/substitute_rsvp.py

"""
Substitute RSVP Routes

Public routes for substitute players to respond to sub requests.
All routes require login for security.
"""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from app.services.substitute_rsvp_service import get_rsvp_service

logger = logging.getLogger(__name__)

substitute_rsvp_bp = Blueprint('substitute_rsvp', __name__, url_prefix='/sub-rsvp')


@substitute_rsvp_bp.route('/<token>')
@login_required
def view_rsvp(token):
    """
    View RSVP request with match details.
    Requires login - user must be the player associated with the token.
    """
    rsvp_service = get_rsvp_service()

    # Validate the token
    is_valid, response, error = rsvp_service.validate_token(token)

    if not is_valid:
        if response and response.responded_at:
            # Already responded - show the result
            details = rsvp_service.get_request_details(response)
            return render_template(
                'substitute_rsvp_flowbite.html',
                already_responded=True,
                response=response,
                details=details,
                error=None
            )
        else:
            flash(error or 'Invalid or expired token', 'error')
            return redirect(url_for('main.index'))

    # Verify the logged-in user matches the player
    if not current_user.player or current_user.player.id != response.player_id:
        flash('You are not authorized to respond to this request', 'error')
        return redirect(url_for('main.index'))

    # Get request details for display
    details = rsvp_service.get_request_details(response)

    return render_template(
        'substitute_rsvp_flowbite.html',
        token=token,
        response=response,
        details=details,
        already_responded=False,
        error=None
    )


@substitute_rsvp_bp.route('/<token>/respond', methods=['POST'])
@login_required
def submit_rsvp(token):
    """
    Process RSVP response (yes/no).
    """
    rsvp_service = get_rsvp_service()

    # Get form data
    is_available = request.form.get('is_available') == 'yes'
    response_text = request.form.get('response_text', '').strip() or None

    # Process the response
    result = rsvp_service.process_response(
        token=token,
        user_id=current_user.id,
        is_available=is_available,
        response_text=response_text
    )

    if result['success']:
        flash(result['message'], 'success')
    else:
        flash(result['message'], 'error')

    # Redirect back to the RSVP page to show confirmation
    return redirect(url_for('substitute_rsvp.view_rsvp', token=token))


@substitute_rsvp_bp.route('/<token>/status')
@login_required
def rsvp_status(token):
    """
    Get RSVP status as JSON (for AJAX updates).
    """
    rsvp_service = get_rsvp_service()

    is_valid, response, error = rsvp_service.validate_token(token)

    if not is_valid and not response:
        return jsonify({'error': error or 'Invalid token'}), 404

    # Verify the logged-in user matches the player
    if not current_user.player or current_user.player.id != response.player_id:
        return jsonify({'error': 'Unauthorized'}), 403

    details = rsvp_service.get_request_details(response)

    return jsonify({
        'success': True,
        'already_responded': response.responded_at is not None,
        'is_available': response.is_available,
        'details': details
    })
