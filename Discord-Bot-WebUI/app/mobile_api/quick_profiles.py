# app/mobile_api/quick_profiles.py

"""
Quick Profiles Mobile API Endpoints

Provides API endpoints for managing quick profiles (tryout player profiles):
- Create quick profiles (admin)
- List quick profiles (admin)
- Delete quick profiles (admin)
- Link to existing players (admin)
- Check for duplicates (admin)
- Validate claim codes (public - for registration flow)

All admin endpoints require Pub League Admin or Global Admin role.
"""

import logging
import re
from datetime import datetime
from difflib import SequenceMatcher

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required
from app.core.session_manager import managed_session
from app.models import Player, User, QuickProfile, QuickProfileStatus
from app.players_helpers import save_quick_profile_picture

logger = logging.getLogger(__name__)

# Admin roles allowed to access these endpoints
ADMIN_ROLES = ['Pub League Admin', 'Global Admin']

# Similarity threshold for duplicate detection (0.85 = 85% match)
SIMILARITY_THRESHOLD = 0.85


def calculate_name_similarity(name1, name2):
    """Calculate similarity ratio between two names."""
    return SequenceMatcher(None, name1.lower(), name2.lower()).ratio()


def find_similar_profiles(session, player_name, threshold=SIMILARITY_THRESHOLD):
    """
    Find existing players and quick profiles with similar names.

    Args:
        session: Database session
        player_name: Name to check
        threshold: Similarity threshold (0.0 to 1.0)

    Returns:
        List of dictionaries with duplicate info
    """
    duplicates = []

    # Check existing players
    players = session.query(Player).filter(Player.is_current_player == True).all()
    for player in players:
        similarity = calculate_name_similarity(player_name, player.name)
        if similarity >= threshold:
            teams = [team.name for team in player.teams[:3]]  # Max 3 teams
            duplicates.append({
                'id': player.id,
                'name': player.name,
                'type': 'player',
                'similarity': round(similarity, 2),
                'profile_picture_url': player.profile_picture_url,
                'teams': teams
            })

    # Check existing quick profiles (pending only)
    quick_profiles = session.query(QuickProfile).filter(
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

    # Sort by similarity (highest first)
    duplicates.sort(key=lambda x: x['similarity'], reverse=True)
    return duplicates[:10]  # Max 10 results


# ==================== Check Duplicates ====================

@mobile_api_v2.route('/quick-profiles/check-duplicates', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def check_duplicates():
    """
    Check for existing players/profiles with similar names before creating.

    Expected JSON:
        player_name: Name to check for duplicates

    Returns:
        JSON with has_duplicates flag and list of potential matches
    """
    data = request.get_json()
    if not data:
        return jsonify({
            'success': False,
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': 'Missing request data'
            }
        }), 400

    player_name = data.get('player_name', '').strip()
    if not player_name:
        return jsonify({
            'success': False,
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': 'Player name is required',
                'field': 'player_name'
            }
        }), 400

    with managed_session() as session:
        duplicates = find_similar_profiles(session, player_name)

        return jsonify({
            'has_duplicates': len(duplicates) > 0,
            'duplicates': duplicates
        }), 200


# ==================== Create Quick Profile ====================

@mobile_api_v2.route('/quick-profiles', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def create_quick_profile():
    """
    Create a new quick profile for a tryout player.

    Expected JSON:
        player_name: Full name (required, max 100 chars)
        photo_base64: Base64 encoded image (required, PNG/JPG/WebP, max 5MB)
        notes: Admin notes (optional)
        jersey_number: Preferred number 1-99 (optional)
        jersey_size: S, M, L, XL, XXL (optional)
        pronouns: he/him, she/her, they/them, or custom (optional)

    Returns:
        JSON with profile id, claim_code, and expires_at
    """
    data = request.get_json()
    if not data:
        return jsonify({
            'success': False,
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': 'Missing request data'
            }
        }), 400

    # Validate required fields
    player_name = data.get('player_name', '').strip()
    if not player_name:
        return jsonify({
            'success': False,
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': 'Player name is required',
                'field': 'player_name'
            }
        }), 400

    if len(player_name) > 100:
        return jsonify({
            'success': False,
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': 'Player name must be 100 characters or less',
                'field': 'player_name'
            }
        }), 400

    photo_base64 = data.get('photo_base64', '')
    if not photo_base64:
        return jsonify({
            'success': False,
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': 'Photo is required',
                'field': 'photo_base64'
            }
        }), 400

    # Optional fields
    notes = data.get('notes', '').strip() or None
    jersey_number = data.get('jersey_number')
    jersey_size = data.get('jersey_size', '').strip() or None
    pronouns = data.get('pronouns', '').strip() or None

    # Validate jersey_number if provided
    if jersey_number is not None:
        try:
            jersey_number = int(jersey_number)
            if jersey_number < 1 or jersey_number > 99:
                return jsonify({
                    'success': False,
                    'error': {
                        'code': 'VALIDATION_ERROR',
                        'message': 'Jersey number must be between 1 and 99',
                        'field': 'jersey_number'
                    }
                }), 400
        except (ValueError, TypeError):
            return jsonify({
                'success': False,
                'error': {
                    'code': 'VALIDATION_ERROR',
                    'message': 'Invalid jersey number',
                    'field': 'jersey_number'
                }
            }), 400

    # Validate jersey_size if provided
    valid_sizes = ['S', 'M', 'L', 'XL', 'XXL']
    if jersey_size and jersey_size.upper() not in valid_sizes:
        return jsonify({
            'success': False,
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': f'Invalid jersey size. Valid options: {", ".join(valid_sizes)}',
                'field': 'jersey_size'
            }
        }), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        try:
            # Create the quick profile
            profile = QuickProfile.create(
                player_name=player_name,
                profile_picture_url=None,  # Will be set after saving image
                created_by_user_id=current_user_id,
                notes=notes,
                jersey_number=jersey_number,
                jersey_size=jersey_size.upper() if jersey_size else None,
                pronouns=pronouns
            )

            session.add(profile)
            session.flush()  # Get the ID for the image filename

            # Save the profile picture
            try:
                picture_url = save_quick_profile_picture(
                    photo_base64,
                    profile.id,
                    player_name
                )
                profile.profile_picture_url = picture_url
            except ValueError as e:
                session.rollback()
                return jsonify({
                    'success': False,
                    'error': {
                        'code': 'INVALID_IMAGE',
                        'message': str(e),
                        'field': 'photo_base64'
                    }
                }), 400

            session.commit()

            # Check for potential duplicates to include in response
            duplicates = find_similar_profiles(session, player_name)
            # Exclude the profile we just created
            duplicates = [d for d in duplicates if not (d['type'] == 'quick_profile' and d['id'] == profile.id)]

            logger.info(f"Quick profile {profile.id} created by user {current_user_id} with code {profile.claim_code}")

            return jsonify({
                'success': True,
                'id': profile.id,
                'claim_code': profile.claim_code,
                'expires_at': profile.expires_at.isoformat(),
                'potential_duplicates': duplicates
            }), 201

        except Exception as e:
            session.rollback()
            logger.error(f"Error creating quick profile: {str(e)}", exc_info=True)
            return jsonify({
                'success': False,
                'error': {
                    'code': 'SERVER_ERROR',
                    'message': 'Failed to create quick profile'
                }
            }), 500


# ==================== List Quick Profiles ====================

@mobile_api_v2.route('/quick-profiles', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def list_quick_profiles():
    """
    List all quick profiles with optional filters.

    Query parameters:
        status: Filter by status (pending, claimed, linked, expired)
        search: Search by player name (partial match)
        limit: Max results (default 50, max 100)
        offset: Pagination offset

    Returns:
        JSON with total count and list of profiles
    """
    # Get filter parameters
    status = request.args.get('status', '').strip().lower()
    search = request.args.get('search', '').strip()
    limit = min(request.args.get('limit', 50, type=int), 100)
    offset = request.args.get('offset', 0, type=int)

    with managed_session() as session:
        query = session.query(QuickProfile)

        # Filter by status
        if status:
            valid_statuses = [s.value for s in QuickProfileStatus]
            if status not in valid_statuses:
                return jsonify({
                    'success': False,
                    'error': {
                        'code': 'VALIDATION_ERROR',
                        'message': f'Invalid status. Valid options: {", ".join(valid_statuses)}',
                        'field': 'status'
                    }
                }), 400
            query = query.filter(QuickProfile.status == status)

        # Search by name
        if search:
            query = query.filter(QuickProfile.player_name.ilike(f'%{search}%'))

        # Get total count
        total = query.count()

        # Order by created_at descending and paginate
        profiles = query.order_by(QuickProfile.created_at.desc())\
            .offset(offset).limit(limit).all()

        return jsonify({
            'success': True,
            'total': total,
            'profiles': [p.to_dict() for p in profiles]
        }), 200


# ==================== Delete Quick Profile ====================

@mobile_api_v2.route('/quick-profiles/<int:profile_id>', methods=['DELETE'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def delete_quick_profile(profile_id: int):
    """
    Delete a quick profile.

    Args:
        profile_id: ID of the profile to delete

    Returns:
        JSON with success status

    Note: Cannot delete profiles that have already been claimed.
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        profile = session.query(QuickProfile).get(profile_id)

        if not profile:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'NOT_FOUND',
                    'message': 'Quick profile not found'
                }
            }), 404

        if profile.status == QuickProfileStatus.CLAIMED.value:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'ALREADY_CLAIMED',
                    'message': 'Cannot delete a profile that has been claimed'
                }
            }), 400

        session.delete(profile)
        session.commit()

        logger.info(f"Quick profile {profile_id} deleted by user {current_user_id}")

        return jsonify({
            'success': True,
            'message': 'Quick profile deleted'
        }), 200


# ==================== Link to Existing Player ====================

@mobile_api_v2.route('/quick-profiles/<int:profile_id>/link', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def link_quick_profile(profile_id: int):
    """
    Manually link a quick profile to an existing player.

    Args:
        profile_id: ID of the quick profile to link

    Expected JSON:
        player_id: ID of the existing player to link to
        overwrite_photo: If true, replace player's existing photo (default: false)

    Returns:
        JSON with success status and updated player info
    """
    data = request.get_json()
    if not data:
        return jsonify({
            'success': False,
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': 'Missing request data'
            }
        }), 400

    player_id = data.get('player_id')
    if not player_id:
        return jsonify({
            'success': False,
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': 'Player ID is required',
                'field': 'player_id'
            }
        }), 400

    overwrite_photo = data.get('overwrite_photo', False)
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        profile = session.query(QuickProfile).get(profile_id)
        if not profile:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'NOT_FOUND',
                    'message': 'Quick profile not found'
                }
            }), 404

        if profile.status != QuickProfileStatus.PENDING.value:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'ALREADY_CLAIMED',
                    'message': f'Cannot link profile with status: {profile.status}'
                }
            }), 400

        player = session.query(Player).get(player_id)
        if not player:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'NOT_FOUND',
                    'message': 'Player not found'
                }
            }), 404

        admin_user = session.query(User).get(current_user_id)

        try:
            profile.link_to_player(player, admin_user, overwrite_photo=overwrite_photo)
            session.commit()

            logger.info(f"Quick profile {profile_id} linked to player {player_id} by user {current_user_id}")

            return jsonify({
                'success': True,
                'message': 'Quick profile linked to player',
                'player': {
                    'id': player.id,
                    'name': player.name,
                    'profile_picture_url': player.profile_picture_url
                }
            }), 200

        except ValueError as e:
            return jsonify({
                'success': False,
                'error': {
                    'code': 'LINK_FAILED',
                    'message': str(e)
                }
            }), 400


# ==================== Validate Claim Code (Public) ====================

@mobile_api_v2.route('/quick-profiles/validate-code', methods=['POST'])
def validate_claim_code():
    """
    Validate a claim code (public endpoint - no auth required).

    Used during registration flow to check if a claim code is valid
    and preview the profile data.

    Expected JSON:
        claim_code: 6-character claim code

    Returns:
        JSON with validation result and profile preview if valid
    """
    data = request.get_json()
    if not data:
        return jsonify({
            'valid': False,
            'reason': 'invalid_format',
            'message': 'Missing request data'
        }), 200  # Return 200 with invalid flag

    claim_code = data.get('claim_code', '').strip().upper()

    # Validate format
    if not claim_code or len(claim_code) != 6 or not claim_code.isalnum():
        return jsonify({
            'valid': False,
            'reason': 'invalid_format',
            'message': 'Claim code must be 6 alphanumeric characters'
        }), 200

    with managed_session() as session:
        profile = QuickProfile.find_by_code(claim_code)

        if not profile:
            return jsonify({
                'valid': False,
                'reason': 'not_found',
                'message': 'Invalid claim code'
            }), 200

        if profile.status == QuickProfileStatus.CLAIMED.value:
            return jsonify({
                'valid': False,
                'reason': 'already_claimed',
                'message': 'This code has already been used'
            }), 200

        if profile.status == QuickProfileStatus.LINKED.value:
            return jsonify({
                'valid': False,
                'reason': 'already_claimed',
                'message': 'This code has already been linked to a player'
            }), 200

        if profile.status == QuickProfileStatus.EXPIRED.value or datetime.utcnow() > profile.expires_at:
            return jsonify({
                'valid': False,
                'reason': 'expired',
                'message': f'This code expired on {profile.expires_at.strftime("%b %d, %Y")}'
            }), 200

        # Valid - return preview data
        return jsonify({
            'valid': True,
            'player_name': profile.player_name,
            'has_photo': bool(profile.profile_picture_url),
            'has_notes': bool(profile.notes),
            'expires_at': profile.expires_at.isoformat()
        }), 200


# ==================== Search Players (for linking) ====================

@mobile_api_v2.route('/quick-profiles/search-players', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def search_players_for_linking():
    """
    Search for existing players to link a quick profile to.

    Query parameters:
        q: Search query (partial match on name)
        limit: Max results (default 20, max 50)

    Returns:
        JSON list of matching players with basic info
    """
    search = request.args.get('q', '').strip()
    limit = min(request.args.get('limit', 20, type=int), 50)

    if len(search) < 2:
        return jsonify({
            'success': True,
            'players': []
        }), 200

    with managed_session() as session:
        players = session.query(Player).filter(
            Player.name.ilike(f'%{search}%'),
            Player.is_current_player == True
        ).order_by(Player.name).limit(limit).all()

        return jsonify({
            'success': True,
            'players': [{
                'id': p.id,
                'name': p.name,
                'profile_picture_url': p.profile_picture_url,
                'teams': [t.name for t in p.teams[:2]]
            } for p in players]
        }), 200


# ==================== Send Claim Code via Email ====================

@mobile_api_v2.route('/quick-profiles/<int:profile_id>/send-email', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def send_claim_code_email(profile_id: int):
    """
    Send claim code to player via email.

    Args:
        profile_id: ID of the quick profile

    Optional JSON body:
        email: Override stored email address

    Returns:
        JSON with success status
    """
    from flask import current_app

    with managed_session() as session:
        profile = session.query(QuickProfile).get(profile_id)

        if not profile:
            return jsonify({
                'success': False,
                'message': 'Quick profile not found'
            }), 404

        if profile.status != QuickProfileStatus.PENDING.value:
            return jsonify({
                'success': False,
                'message': 'Can only send codes for pending profiles'
            }), 400

        # Get email from request or profile
        data = request.get_json() or {}
        email = data.get('email', '').strip() or profile.email

        if not email:
            return jsonify({
                'success': False,
                'message': 'No email address provided'
            }), 400

        # Update stored email if provided in request
        if data.get('email'):
            profile.email = email

        try:
            from app.email import send_email

            # Generate registration URL with claim code
            base_url = current_app.config.get('BASE_URL', 'https://portal.ecsfc.com')
            register_url = f"{base_url}/claim?code={profile.claim_code}"

            subject = "Your ECS FC Registration Code"
            body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #1a472a;">Welcome to ECS FC!</h2>
                    <p>Hi {profile.player_name},</p>
                    <p>You've been given a registration code to join ECS FC. Use the code below to complete your registration:</p>
                    <div style="background: #f5f5f5; padding: 20px; text-align: center; margin: 20px 0; border-radius: 8px;">
                        <p style="margin: 0 0 10px 0; color: #666;">Your Registration Code:</p>
                        <h1 style="margin: 0; color: #1a472a; font-family: monospace; letter-spacing: 4px; font-size: 32px;">{profile.claim_code}</h1>
                    </div>
                    <p>Or click the button below to register directly:</p>
                    <div style="text-align: center; margin: 20px 0;">
                        <a href="{register_url}" style="background: #1a472a; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Complete Registration</a>
                    </div>
                    <p style="color: #666; font-size: 14px;">This code expires on {profile.expires_at.strftime('%B %d, %Y')}.</p>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                    <p style="color: #999; font-size: 12px;">ECS FC - Emerald City Supporters Football Club</p>
                </div>
            </body>
            </html>
            """

            result = send_email(email, subject, body)

            if result:
                logger.info(f"Claim code email sent to {email} for profile {profile_id}")
                return jsonify({
                    'success': True,
                    'message': f'Claim code sent to {email}'
                }), 200
            else:
                logger.error(f"Failed to send claim code email to {email}")
                return jsonify({
                    'success': False,
                    'message': 'Failed to send email'
                }), 500

        except Exception as e:
            logger.error(f"Error sending claim code email: {str(e)}", exc_info=True)
            return jsonify({
                'success': False,
                'message': 'Failed to send email'
            }), 500


# ==================== Send Claim Code via SMS ====================

@mobile_api_v2.route('/quick-profiles/<int:profile_id>/send-sms', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def send_claim_code_sms(profile_id: int):
    """
    Send claim code to player via SMS.

    Args:
        profile_id: ID of the quick profile

    Optional JSON body:
        phone_number: Override stored phone number

    Returns:
        JSON with success status
    """
    from flask import current_app

    with managed_session() as session:
        profile = session.query(QuickProfile).get(profile_id)

        if not profile:
            return jsonify({
                'success': False,
                'message': 'Quick profile not found'
            }), 404

        if profile.status != QuickProfileStatus.PENDING.value:
            return jsonify({
                'success': False,
                'message': 'Can only send codes for pending profiles'
            }), 400

        # Get phone from request or profile
        data = request.get_json() or {}
        phone = data.get('phone_number', '').strip() or data.get('phone', '').strip() or profile.phone_number

        if not phone:
            return jsonify({
                'success': False,
                'message': 'No phone number provided'
            }), 400

        # Normalize phone number
        phone_digits = re.sub(r'\D', '', phone)
        if len(phone_digits) == 10:
            phone = f"+1{phone_digits}"
        elif len(phone_digits) == 11 and phone_digits.startswith('1'):
            phone = f"+{phone_digits}"
        elif not phone.startswith('+'):
            phone = f"+{phone_digits}"

        # Update stored phone if provided in request
        if data.get('phone_number') or data.get('phone'):
            profile.phone_number = phone

        try:
            from app.sms_helpers import send_sms

            # Generate registration URL with claim code
            base_url = current_app.config.get('BASE_URL', 'https://portal.ecsfc.com')
            register_url = f"{base_url}/claim?code={profile.claim_code}"

            message = f"""Hi {profile.player_name}! Your ECS FC code is: {profile.claim_code}

Register at: {register_url}

Code expires: {profile.expires_at.strftime('%b %d')}"""

            success, result = send_sms(phone, message)

            if success:
                logger.info(f"Claim code SMS sent to {phone} for profile {profile_id}")
                return jsonify({
                    'success': True,
                    'message': f'Claim code sent via SMS'
                }), 200
            else:
                logger.error(f"Failed to send claim code SMS to {phone}: {result}")
                return jsonify({
                    'success': False,
                    'message': 'Failed to send SMS'
                }), 500

        except Exception as e:
            logger.error(f"Error sending claim code SMS: {str(e)}", exc_info=True)
            return jsonify({
                'success': False,
                'message': 'Failed to send SMS'
            }), 500
