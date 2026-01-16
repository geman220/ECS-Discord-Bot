# app/admin_panel/routes/quick_profiles.py

"""
Admin Panel Quick Profiles Management Routes

This module provides admin functionality for managing quick profiles
(temporary profiles for tryout players):
- View all quick profiles with filtering
- Create new quick profiles
- Delete quick profiles
- Link quick profiles to existing players
- Check for duplicate names

Quick profiles allow admins to create temporary profiles for walk-in players
who don't have accounts yet. Players receive a claim code to link their
profile later during Discord registration.
"""

import logging
from datetime import datetime
from difflib import SequenceMatcher

from flask import render_template, request, jsonify, flash, redirect, url_for, g
from flask_login import login_required, current_user
from sqlalchemy import func

from .. import admin_panel_bp
from app.core import db
from app.models import Player, User, QuickProfile, QuickProfileStatus
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.players_helpers import save_quick_profile_picture

logger = logging.getLogger(__name__)

# Roles allowed to manage quick profiles
ADMIN_ROLES = ['Pub League Admin', 'Global Admin']

# Similarity threshold for duplicate detection
SIMILARITY_THRESHOLD = 0.85


def calculate_name_similarity(name1, name2):
    """Calculate similarity ratio between two names."""
    return SequenceMatcher(None, name1.lower(), name2.lower()).ratio()


def find_similar_profiles(player_name, threshold=SIMILARITY_THRESHOLD):
    """Find existing players and quick profiles with similar names."""
    duplicates = []

    # Check existing players
    players = Player.query.filter(Player.is_current_player == True).all()
    for player in players:
        similarity = calculate_name_similarity(player_name, player.name)
        if similarity >= threshold:
            teams = [team.name for team in player.teams[:3]]
            duplicates.append({
                'id': player.id,
                'name': player.name,
                'type': 'player',
                'similarity': round(similarity, 2),
                'profile_picture_url': player.profile_picture_url,
                'teams': teams
            })

    # Check existing quick profiles (pending only)
    quick_profiles = QuickProfile.query.filter(
        QuickProfile.status == QuickProfileStatus.PENDING.value
    ).all()
    for qp in quick_profiles:
        similarity = calculate_name_similarity(player_name, qp.player_name)
        if similarity >= threshold:
            duplicates.append({
                'id': qp.id,
                'name': qp.player_name,
                'type': 'quick_profile',
                'similarity': round(similarity, 2),
                'status': qp.status,
                'claim_code': qp.claim_code
            })

    duplicates.sort(key=lambda x: x['similarity'], reverse=True)
    return duplicates[:10]


# ==================== Main Dashboard ====================

@admin_panel_bp.route('/quick-profiles')
@login_required
@role_required(ADMIN_ROLES)
def quick_profiles_management():
    """Quick profiles management dashboard."""
    try:
        # Get filter parameters
        status_filter = request.args.get('status', '')
        search = request.args.get('search', '').strip()

        # Base query
        query = QuickProfile.query

        # Apply filters
        if status_filter:
            query = query.filter(QuickProfile.status == status_filter)
        if search:
            query = query.filter(QuickProfile.player_name.ilike(f'%{search}%'))

        # Get profiles ordered by creation date
        profiles = query.order_by(QuickProfile.created_at.desc()).all()

        # Get statistics
        stats = {
            'pending': QuickProfile.query.filter(
                QuickProfile.status == QuickProfileStatus.PENDING.value
            ).count(),
            'claimed': QuickProfile.query.filter(
                QuickProfile.status == QuickProfileStatus.CLAIMED.value
            ).count(),
            'linked': QuickProfile.query.filter(
                QuickProfile.status == QuickProfileStatus.LINKED.value
            ).count(),
            'expired': QuickProfile.query.filter(
                QuickProfile.status == QuickProfileStatus.EXPIRED.value
            ).count(),
        }

        return render_template(
            'admin_panel/quick_profiles/management_flowbite.html',
            profiles=profiles,
            stats=stats,
            status_filter=status_filter,
            search=search
        )

    except Exception as e:
        logger.error(f"Error loading quick profiles management: {e}", exc_info=True)
        flash('Error loading quick profiles. Please try again.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


# ==================== Check Duplicates ====================

@admin_panel_bp.route('/quick-profiles/check-duplicates', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def check_quick_profile_duplicates():
    """Check for potential duplicate names before creating a profile."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Missing request data'}), 400

    player_name = data.get('player_name', '').strip()
    if not player_name:
        return jsonify({'success': False, 'error': 'Player name is required'}), 400

    duplicates = find_similar_profiles(player_name)

    return jsonify({
        'success': True,
        'has_duplicates': len(duplicates) > 0,
        'duplicates': duplicates
    })


# ==================== Create Quick Profile ====================

@admin_panel_bp.route('/quick-profiles/create', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
@transactional
def create_quick_profile():
    """Create a new quick profile."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Missing request data'}), 400

    # Validate required fields
    player_name = data.get('player_name', '').strip()
    if not player_name:
        return jsonify({'success': False, 'error': 'Player name is required'}), 400

    if len(player_name) > 100:
        return jsonify({'success': False, 'error': 'Player name must be 100 characters or less'}), 400

    photo_base64 = data.get('photo_base64', '')
    if not photo_base64:
        return jsonify({'success': False, 'error': 'Photo is required'}), 400

    # Optional fields
    notes = data.get('notes', '').strip() or None
    jersey_number = data.get('jersey_number')
    jersey_size = data.get('jersey_size', '').strip() or None
    pronouns = data.get('pronouns', '').strip() or None

    # Validate jersey_number
    if jersey_number is not None:
        try:
            jersey_number = int(jersey_number)
            if jersey_number < 1 or jersey_number > 99:
                return jsonify({'success': False, 'error': 'Jersey number must be between 1 and 99'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid jersey number'}), 400

    # Validate jersey_size
    valid_sizes = ['S', 'M', 'L', 'XL', 'XXL']
    if jersey_size and jersey_size.upper() not in valid_sizes:
        return jsonify({'success': False, 'error': f'Invalid jersey size. Valid: {", ".join(valid_sizes)}'}), 400

    # Optional contact info
    email = data.get('email', '').strip() or None
    phone_number = data.get('phone_number', '').strip() or None

    # Basic email validation
    if email and '@' not in email:
        return jsonify({'success': False, 'error': 'Invalid email address'}), 400

    # Basic phone validation (strip non-digits for storage)
    if phone_number:
        import re
        phone_digits = re.sub(r'\D', '', phone_number)
        if len(phone_digits) < 10:
            return jsonify({'success': False, 'error': 'Phone number must have at least 10 digits'}), 400
        phone_number = phone_digits

    try:
        session = g.db_session

        # Create the profile
        profile = QuickProfile.create(
            player_name=player_name,
            profile_picture_url=None,
            created_by_user_id=current_user.id,
            notes=notes,
            jersey_number=jersey_number,
            jersey_size=jersey_size.upper() if jersey_size else None,
            pronouns=pronouns,
            email=email,
            phone_number=phone_number
        )

        session.add(profile)
        session.flush()

        # Save the picture
        try:
            picture_url = save_quick_profile_picture(photo_base64, profile.id, player_name)
            profile.profile_picture_url = picture_url
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400

        # Log the action
        audit_log = AdminAuditLog(
            user_id=current_user.id,
            action='create_quick_profile',
            resource_type='quick_profile',
            resource_id=profile.id,
            details={'player_name': player_name, 'claim_code': profile.claim_code}
        )
        session.add(audit_log)

        logger.info(f"Quick profile {profile.id} created by {current_user.username} with code {profile.claim_code}")

        return jsonify({
            'success': True,
            'id': profile.id,
            'claim_code': profile.claim_code,
            'expires_at': profile.expires_at.isoformat()
        }), 201

    except Exception as e:
        logger.error(f"Error creating quick profile: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to create quick profile'}), 500


# ==================== Delete Quick Profile ====================

@admin_panel_bp.route('/quick-profiles/<int:profile_id>/delete', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
@transactional
def delete_quick_profile(profile_id):
    """Delete a quick profile."""
    try:
        session = g.db_session
        profile = session.query(QuickProfile).get(profile_id)

        if not profile:
            return jsonify({'success': False, 'error': 'Quick profile not found'}), 404

        if profile.status == QuickProfileStatus.CLAIMED.value:
            return jsonify({'success': False, 'error': 'Cannot delete a claimed profile'}), 400

        claim_code = profile.claim_code
        player_name = profile.player_name

        session.delete(profile)

        # Log the action
        audit_log = AdminAuditLog(
            user_id=current_user.id,
            action='delete_quick_profile',
            resource_type='quick_profile',
            resource_id=profile_id,
            details={'player_name': player_name, 'claim_code': claim_code}
        )
        session.add(audit_log)

        logger.info(f"Quick profile {profile_id} deleted by {current_user.username}")

        return jsonify({'success': True, 'message': 'Quick profile deleted'})

    except Exception as e:
        logger.error(f"Error deleting quick profile: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to delete quick profile'}), 500


# ==================== Link to Existing Player ====================

@admin_panel_bp.route('/quick-profiles/<int:profile_id>/link', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
@transactional
def link_quick_profile(profile_id):
    """Link a quick profile to an existing player."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Missing request data'}), 400

    player_id = data.get('player_id')
    if not player_id:
        return jsonify({'success': False, 'error': 'Player ID is required'}), 400

    overwrite_photo = data.get('overwrite_photo', False)

    try:
        session = g.db_session
        profile = session.query(QuickProfile).get(profile_id)

        if not profile:
            return jsonify({'success': False, 'error': 'Quick profile not found'}), 404

        if profile.status != QuickProfileStatus.PENDING.value:
            return jsonify({'success': False, 'error': f'Cannot link profile with status: {profile.status}'}), 400

        player = session.query(Player).get(player_id)
        if not player:
            return jsonify({'success': False, 'error': 'Player not found'}), 404

        # Link the profile
        profile.link_to_player(player, current_user, overwrite_photo=overwrite_photo)

        # Log the action
        audit_log = AdminAuditLog(
            user_id=current_user.id,
            action='link_quick_profile',
            resource_type='quick_profile',
            resource_id=profile_id,
            details={'player_id': player_id, 'player_name': player.name}
        )
        session.add(audit_log)

        logger.info(f"Quick profile {profile_id} linked to player {player_id} by {current_user.username}")

        return jsonify({
            'success': True,
            'message': 'Quick profile linked to player',
            'player': {
                'id': player.id,
                'name': player.name,
                'profile_picture_url': player.profile_picture_url
            }
        })

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error linking quick profile: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to link quick profile'}), 500


# ==================== Search Players (for linking) ====================

@admin_panel_bp.route('/quick-profiles/search-players')
@login_required
@role_required(ADMIN_ROLES)
def search_players_for_quick_profile():
    """Search for existing players to link a quick profile to."""
    search = request.args.get('q', '').strip()

    if len(search) < 2:
        return jsonify({'success': True, 'players': []})

    players = Player.query.filter(
        Player.name.ilike(f'%{search}%'),
        Player.is_current_player == True
    ).order_by(Player.name).limit(20).all()

    return jsonify({
        'success': True,
        'players': [{
            'id': p.id,
            'name': p.name,
            'profile_picture_url': p.profile_picture_url,
            'teams': [t.name for t in p.teams[:2]]
        } for p in players]
    })


# ==================== Get Profile Details ====================

@admin_panel_bp.route('/quick-profiles/<int:profile_id>')
@login_required
@role_required(ADMIN_ROLES)
def get_quick_profile_details(profile_id):
    """Get detailed information about a quick profile."""
    profile = QuickProfile.query.get(profile_id)

    if not profile:
        return jsonify({'success': False, 'error': 'Quick profile not found'}), 404

    data = profile.to_dict()

    # Add linked player info if applicable
    if profile.claimed_by_player:
        data['linked_player'] = {
            'id': profile.claimed_by_player.id,
            'name': profile.claimed_by_player.name,
            'profile_picture_url': profile.claimed_by_player.profile_picture_url
        }

    return jsonify({'success': True, 'profile': data})


# ==================== Send Claim Code via Email ====================

@admin_panel_bp.route('/quick-profiles/<int:profile_id>/send-email', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def send_quick_profile_email(profile_id):
    """Send claim code to player via email."""
    from flask import current_app

    data = request.get_json() or {}
    profile = QuickProfile.query.get(profile_id)

    if not profile:
        return jsonify({'success': False, 'error': 'Quick profile not found'}), 404

    if profile.status != QuickProfileStatus.PENDING.value:
        return jsonify({'success': False, 'error': 'Profile is no longer pending'}), 400

    # Use provided email or stored email
    email = data.get('email', '').strip() or profile.email
    if not email or '@' not in email:
        return jsonify({'success': False, 'error': 'Valid email address required'}), 400

    # Update stored email if different
    if email != profile.email:
        profile.email = email

    try:
        from app.email import send_email

        # Generate registration URL with claim code (uses /claim route for QR code compatibility)
        base_url = current_app.config.get('BASE_URL', 'https://ecsfc.com')
        register_url = f"{base_url}/claim?code={profile.claim_code}"

        # Send email
        subject = "Your ECS FC Registration Code"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a5f2a;">Welcome to ECS FC!</h2>

                <p>Hi {profile.player_name},</p>

                <p>You've been added to our system. Use the code below to complete your registration:</p>

                <div style="background: #f5f5f5; border-radius: 8px; padding: 20px; text-align: center; margin: 20px 0;">
                    <p style="margin: 0 0 10px 0; font-size: 14px; color: #666;">Your Registration Code:</p>
                    <p style="font-size: 32px; font-weight: bold; letter-spacing: 4px; margin: 0; color: #1a5f2a;">{profile.claim_code}</p>
                </div>

                <p><strong>To register:</strong></p>
                <ol>
                    <li>Click <a href="{register_url}" style="color: #1a5f2a;">this link</a> or go to {base_url}</li>
                    <li>Authenticate with Discord</li>
                    <li>Your profile will be automatically linked</li>
                </ol>

                <p style="background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; padding: 10px; font-size: 14px;">
                    <strong>Note:</strong> This code expires on {profile.expires_at.strftime('%B %d, %Y')}.
                </p>

                <p style="margin-top: 30px; font-size: 14px; color: #666;">
                    See you on the pitch!<br>
                    <strong>ECS FC</strong>
                </p>
            </div>
        </body>
        </html>
        """

        result = send_email(email, subject, body)

        if result:
            logger.info(f"Claim code email sent to {email} for profile {profile_id}")
            return jsonify({'success': True, 'message': f'Email sent to {email}'})
        else:
            logger.error(f"Failed to send claim code email to {email}")
            return jsonify({'success': False, 'error': 'Failed to send email'}), 500

    except Exception as e:
        logger.error(f"Error sending claim code email: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to send email'}), 500


# ==================== Send Claim Code via SMS ====================

@admin_panel_bp.route('/quick-profiles/<int:profile_id>/send-sms', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def send_quick_profile_sms(profile_id):
    """Send claim code to player via SMS."""
    from flask import current_app

    data = request.get_json() or {}
    profile = QuickProfile.query.get(profile_id)

    if not profile:
        return jsonify({'success': False, 'error': 'Quick profile not found'}), 404

    if profile.status != QuickProfileStatus.PENDING.value:
        return jsonify({'success': False, 'error': 'Profile is no longer pending'}), 400

    # Use provided phone or stored phone
    import re
    phone = data.get('phone_number', '').strip() or profile.phone_number
    if phone:
        phone = re.sub(r'\D', '', phone)

    if not phone or len(phone) < 10:
        return jsonify({'success': False, 'error': 'Valid phone number required (at least 10 digits)'}), 400

    # Format for Twilio (US numbers need +1)
    if len(phone) == 10:
        phone = f"+1{phone}"
    elif not phone.startswith('+'):
        phone = f"+{phone}"

    # Update stored phone if different
    if phone != profile.phone_number:
        profile.phone_number = re.sub(r'\D', '', phone)

    try:
        from app.sms_helpers import send_sms

        # Generate registration URL with claim code (uses /claim route for QR code compatibility)
        base_url = current_app.config.get('BASE_URL', 'https://ecsfc.com')
        register_url = f"{base_url}/claim?code={profile.claim_code}"

        # SMS message (keep it short with opt-out)
        message = (
            f"Hi {profile.player_name}! Your ECS FC registration code is: {profile.claim_code}\n\n"
            f"Register at: {register_url}\n\n"
            f"Code expires: {profile.expires_at.strftime('%b %d')}\n\n"
            f"Reply STOP to opt out."
        )

        success, result = send_sms(phone, message)

        if success:
            logger.info(f"Claim code SMS sent to {phone} for profile {profile_id}")
            return jsonify({'success': True, 'message': f'SMS sent to {phone}'})
        else:
            logger.error(f"Failed to send claim code SMS to {phone}: {result}")
            return jsonify({'success': False, 'error': f'Failed to send SMS: {result}'}), 500

    except Exception as e:
        logger.error(f"Error sending claim code SMS: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to send SMS'}), 500


# ==================== Update Contact Info ====================

@admin_panel_bp.route('/quick-profiles/<int:profile_id>/update-contact', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
@transactional
def update_quick_profile_contact(profile_id):
    """Update email/phone for a quick profile."""
    import re

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Missing request data'}), 400

    session = g.db_session
    profile = session.query(QuickProfile).get(profile_id)

    if not profile:
        return jsonify({'success': False, 'error': 'Quick profile not found'}), 404

    email = data.get('email', '').strip() or None
    phone_number = data.get('phone_number', '').strip() or None

    if email and '@' not in email:
        return jsonify({'success': False, 'error': 'Invalid email address'}), 400

    if phone_number:
        phone_digits = re.sub(r'\D', '', phone_number)
        if len(phone_digits) < 10:
            return jsonify({'success': False, 'error': 'Phone number must have at least 10 digits'}), 400
        phone_number = phone_digits

    profile.email = email
    profile.phone_number = phone_number

    logger.info(f"Quick profile {profile_id} contact updated by {current_user.username}")

    return jsonify({
        'success': True,
        'email': profile.email,
        'phone_number': profile.phone_number
    })
