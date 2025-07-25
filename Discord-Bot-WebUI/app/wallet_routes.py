"""
Apple Wallet Pass Routes

This module provides Flask routes for Apple Wallet pass generation,
download, and management functionality.
"""

import logging
from flask import Blueprint, request, send_file, jsonify, render_template, flash, redirect, url_for, abort
from flask_login import login_required, current_user
from datetime import datetime
from io import BytesIO

from app.models import Player, User
from app.wallet_pass import create_pass_for_player, validate_pass_configuration
from app.decorators import role_required
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

wallet_bp = Blueprint('wallet', __name__, url_prefix='/wallet')


@wallet_bp.route('/pass/<int:user_id>')
@login_required
def get_wallet_pass(user_id):
    """
    Generate and download Apple Wallet pass for a user's membership
    
    Args:
        user_id: User ID to generate pass for
        
    Returns:
        .pkpass file download or error page
    """
    try:
        # Security check - users can only download their own pass unless admin
        if not safe_current_user.has_role('Global Admin') and safe_current_user.id != user_id:
            logger.warning(f"User {safe_current_user.id} attempted to access pass for user {user_id}")
            abort(403)
        
        # Get user and their player profile
        user = User.query.get_or_404(user_id)
        player = user.player
        
        if not player:
            flash('No player profile found for this user.', 'error')
            return redirect(url_for('main.index'))
        
        # Check if player is eligible for a pass
        if not player.is_current_player:
            flash('Player is not currently active and cannot generate a membership pass.', 'error')
            return redirect(url_for('account.profile'))
        
        # Generate the pass
        logger.info(f"Generating wallet pass for user {user.email} (player: {player.name})")
        
        pass_data = create_pass_for_player(player.id)
        
        # Create filename
        filename = f"{player.name.replace(' ', '_')}_ecsfc_membership.pkpass"
        
        return send_file(
            pass_data,
            mimetype="application/vnd.apple.pkpass",
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"Error generating wallet pass for user {user_id}: {str(e)}")
        flash('Error generating membership pass. Please try again later.', 'error')
        return redirect(url_for('account.profile'))


@wallet_bp.route('/pass/player/<int:player_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_wallet_pass_by_player(player_id):
    """
    Admin route to generate wallet pass directly by player ID
    
    Args:
        player_id: Player ID to generate pass for
        
    Returns:
        .pkpass file download or error page
    """
    try:
        player = Player.query.get_or_404(player_id)
        
        # Check if player is eligible
        if not player.is_current_player:
            flash(f'Player {player.name} is not currently active.', 'error')
            return redirect(url_for('admin.wallet_management'))
        
        logger.info(f"Admin {safe_current_user.email} generating wallet pass for player {player.name}")
        
        pass_data = create_pass_for_player(player.id)
        filename = f"{player.name.replace(' ', '_')}_ecsfc_membership.pkpass"
        
        return send_file(
            pass_data,
            mimetype="application/vnd.apple.pkpass",
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"Error generating wallet pass for player {player_id}: {str(e)}")
        flash('Error generating membership pass. Please try again later.', 'error')
        return redirect(url_for('admin.wallet_management'))


@wallet_bp.route('/api/pass/validate/<int:player_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def validate_pass_eligibility(player_id):
    """
    API endpoint to validate if a player is eligible for a wallet pass
    
    Args:
        player_id: Player ID to check
        
    Returns:
        JSON response with eligibility status
    """
    try:
        player = Player.query.get_or_404(player_id)
        
        eligibility = {
            'eligible': False,
            'reasons': [],
            'player_name': player.name,
            'player_id': player.id
        }
        
        # Check eligibility criteria
        if not player.is_current_player:
            eligibility['reasons'].append('Player is not currently active')
        
        if not player.user:
            eligibility['reasons'].append('Player has no associated user account')
        
        if not player.primary_team:
            eligibility['reasons'].append('Player is not assigned to a team')
        
        if len(eligibility['reasons']) == 0:
            eligibility['eligible'] = True
            eligibility['team_name'] = player.primary_team.name if player.primary_team else None
            eligibility['league_name'] = player.league.name if player.league else None
        
        return jsonify(eligibility)
        
    except Exception as e:
        logger.error(f"Error validating pass eligibility for player {player_id}: {str(e)}")
        return jsonify({'error': 'Validation failed'}), 500


@wallet_bp.route('/config/status')
@login_required
@role_required(['Global Admin'])
def wallet_config_status():
    """
    API endpoint to check wallet pass system configuration status
    
    Returns:
        JSON response with configuration status and any issues
    """
    try:
        status = validate_pass_configuration()
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"Error checking wallet configuration: {str(e)}")
        return jsonify({'error': 'Configuration check failed'}), 500


# Apple Wallet Web Service endpoints for pass updates
@wallet_bp.route('/v1/devices/<device_id>/registrations/<pass_type_id>')
@wallet_bp.route('/v1/devices/<device_id>/registrations/<pass_type_id>/<serial_number>')
def wallet_web_service_register(device_id, pass_type_id, serial_number=None):
    """
    Apple Wallet web service endpoint for device registration
    
    This endpoint is called by Apple Wallet when a user adds a pass to their wallet.
    It's used to register the device for push notifications when the pass needs updating.
    """
    logger.info(f"Wallet service registration: device={device_id}, pass_type={pass_type_id}, serial={serial_number}")
    
    # For now, return success - in a full implementation you'd store device tokens
    # and use them to send push notifications when passes need updating
    return jsonify({'status': 'registered'}), 200


@wallet_bp.route('/v1/passes/<pass_type_id>/<serial_number>')
def wallet_web_service_get_pass(pass_type_id, serial_number):
    """
    Apple Wallet web service endpoint to get updated pass data
    
    This endpoint is called when Apple Wallet checks for pass updates.
    """
    logger.info(f"Wallet service pass request: pass_type={pass_type_id}, serial={serial_number}")
    
    try:
        # Extract player ID from serial number (format: ecsfc-{uuid})
        # You'd implement logic here to check if the pass needs updating
        # and return the updated pass if needed
        
        # For now, return 304 (not modified) - pass hasn't changed
        return '', 304
        
    except Exception as e:
        logger.error(f"Error in wallet web service: {str(e)}")
        return jsonify({'error': 'Service error'}), 500


@wallet_bp.route('/v1/devices/<device_id>/registrations/<pass_type_id>/<serial_number>', methods=['DELETE'])
def wallet_web_service_unregister(device_id, pass_type_id, serial_number):
    """
    Apple Wallet web service endpoint for device unregistration
    
    Called when a user removes a pass from their wallet.
    """
    logger.info(f"Wallet service unregistration: device={device_id}, pass_type={pass_type_id}, serial={serial_number}")
    
    # Clean up device registration - implement as needed
    return '', 200


@wallet_bp.route('/v1/log')
def wallet_web_service_log():
    """
    Apple Wallet web service log endpoint
    
    Apple Wallet can send error logs to this endpoint.
    """
    try:
        log_data = request.get_json()
        logger.info(f"Wallet service log: {log_data}")
        return '', 200
    except Exception as e:
        logger.error(f"Error processing wallet log: {str(e)}")
        return '', 200  # Always return success for logging