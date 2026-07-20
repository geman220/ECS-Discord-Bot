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
from app.utils.log_sanitizer import mask_code

logger = logging.getLogger(__name__)

# Admin roles allowed to access these endpoints
ADMIN_ROLES = ['Pub League Admin', 'Global Admin']

# Read-only visibility for the waiting room / NAD board: coaches may VIEW a
# quick profile's detail (jersey#, intake note) but not create/link/delete/edit.
COACH_VIEW_ROLES = ['Pub League Admin', 'Global Admin', 'Pub League Coach']

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

    player_name = (data.get('player_name') or '').strip()
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
    player_name = (data.get('player_name') or '').strip()
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

    # Optional fields. Use `(data.get(x) or '')` rather than `data.get(x, '')`:
    # the Flutter client sends explicit JSON null for empty optional fields, and
    # the two-arg default only kicks in when the key is ABSENT — a present-but-null
    # value returns None and .strip() crashes (was 500ing every field creation).
    notes = (data.get('notes') or '').strip() or None
    jersey_number = data.get('jersey_number')
    jersey_size = (data.get('jersey_size') or '').strip() or None
    pronouns = (data.get('pronouns') or '').strip() or None
    email = (data.get('email') or '').strip() or None
    phone_number = (data.get('phone_number') or data.get('phone') or '').strip() or None

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

    # Light contact validation for parity with the web route — we auto-send the
    # claim code to whatever is captured here, so don't store an unsendable address.
    if email and '@' not in email:
        return jsonify({
            'success': False,
            'error': {'code': 'VALIDATION_ERROR', 'message': 'Invalid email address', 'field': 'email'}
        }), 400
    if phone_number:
        phone_digits = re.sub(r'\D', '', phone_number)
        if len(phone_digits) < 10:
            return jsonify({
                'success': False,
                'error': {'code': 'VALIDATION_ERROR', 'message': 'Phone number must have at least 10 digits', 'field': 'phone_number'}
            }), 400
        phone_number = phone_digits

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
                pronouns=pronouns,
                email=email,
                phone_number=phone_number
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

            logger.info(f"Quick profile {profile.id} created by user {current_user_id} with code {mask_code(profile.claim_code)}")

            # Capture response essentials now — the profile is committed, so nothing
            # below may raise a 500: a post-commit failure would surface an error for
            # a profile that actually exists (orphan; admin retries -> duplicate).
            from app.services.quick_profile_notifications import (
                defer_claim_code_send, build_claim_url,
            )
            profile_id = profile.id
            claim_code = profile.claim_code
            claim_url = build_claim_url(profile)  # ready to encode into a QR
            expires_at_iso = profile.expires_at.isoformat()

            # Auto-deliver the claim code if the admin captured contact info in the
            # field. Email is free, SMS costs money — prefer email; only text when
            # there's a phone AND no email.
            will_email = bool(email)
            will_sms = bool(phone_number) and not email
            if will_email or will_sms:
                defer_claim_code_send(profile_id, via_email=will_email, via_sms=will_sms)

            # Duplicate hint is best-effort — must never fail an already-committed create.
            try:
                duplicates = find_similar_profiles(session, player_name)
                duplicates = [d for d in duplicates if not (d['type'] == 'quick_profile' and d['id'] == profile_id)]
            except Exception as dup_err:
                logger.warning(f"Duplicate lookup failed post-create for profile {profile_id}: {dup_err}")
                duplicates = []

            return jsonify({
                'success': True,
                'id': profile_id,
                'claim_code': claim_code,
                'claim_url': claim_url,
                'expires_at': expires_at_iso,
                'sent_email': will_email,
                'sent_sms': will_sms,
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


# ==================== Get One Quick Profile ====================

@mobile_api_v2.route('/quick-profiles/<int:profile_id>', methods=['GET'])
@jwt_required()
@jwt_role_required(COACH_VIEW_ROLES)
def get_quick_profile(profile_id: int):
    """
    Get a single quick profile by id.

    Mirrors the web admin get-details route so the mobile client's
    QuickProfileRepository.getQuickProfile(id) has a real endpoint (the list
    already carries the full profile, but the client calls this path directly).

    Readable by coaches too (waiting-room / NAD-board scouting), so they can see
    a prospect's jersey#/intake note; create/link/delete/photo stay admin-only.

    Returns:
        JSON with the full profile dict (+ linked_player if it was claimed/linked).
    """
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

        data = profile.to_dict()

        if profile.claimed_by_player:
            data['linked_player'] = {
                'id': profile.claimed_by_player.id,
                'name': profile.claimed_by_player.name,
                'profile_picture_url': profile.claimed_by_player.profile_picture_url
            }

        return jsonify({'success': True, 'profile': data}), 200


# ==================== Update Quick Profile Photo ====================

@mobile_api_v2.route('/quick-profiles/<int:profile_id>/photo', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def update_quick_profile_photo(profile_id: int):
    """
    Replace a quick profile's photo (admin only). Lets admins re-take a field
    profile picture from the waiting room without deleting/recreating the profile.

    Supports two formats (same as the admin player picture endpoint):
        1. Multipart form data with a 'file' field
        2. Base64 JSON: {"photo_base64": "data:image/png;base64,..."} (also
           accepts "cropped_image_data" for parity with the player endpoint)

    Only PENDING profiles can be re-photographed; once claimed/linked the photo
    lives on the real Player row (use the player photo endpoint).

    Returns:
        JSON with the new profile_picture_url.
    """
    content_type = request.content_type or ''

    if 'multipart/form-data' in content_type:
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': {'code': 'VALIDATION_ERROR', 'message': 'No file provided', 'field': 'file'}
            }), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': {'code': 'VALIDATION_ERROR', 'message': 'No file selected', 'field': 'file'}
            }), 400

        allowed_extensions = {'png', 'jpg', 'jpeg', 'webp'}
        file_ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if file_ext not in allowed_extensions:
            return jsonify({
                'success': False,
                'error': {'code': 'INVALID_IMAGE',
                          'message': f'Invalid file type. Allowed: {", ".join(sorted(allowed_extensions))}',
                          'field': 'file'}
            }), 400

        import base64
        file_data = file.read()
        if len(file_data) > 5 * 1024 * 1024:
            return jsonify({
                'success': False,
                'error': {'code': 'INVALID_IMAGE', 'message': 'File too large. Maximum size: 5MB', 'field': 'file'}
            }), 400
        mime_type = file.content_type or f'image/{file_ext}'
        image_data = f"data:{mime_type};base64,{base64.b64encode(file_data).decode('utf-8')}"
    else:
        data = request.get_json() or {}
        image_data = data.get('photo_base64') or data.get('cropped_image_data')
        if not image_data:
            return jsonify({
                'success': False,
                'error': {'code': 'VALIDATION_ERROR', 'message': 'Missing photo data', 'field': 'photo_base64'}
            }), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        profile = session.query(QuickProfile).get(profile_id)
        if not profile:
            return jsonify({
                'success': False,
                'error': {'code': 'NOT_FOUND', 'message': 'Quick profile not found'}
            }), 404

        if profile.status != QuickProfileStatus.PENDING.value:
            return jsonify({
                'success': False,
                'error': {'code': 'ALREADY_CLAIMED',
                          'message': 'Can only update photos for pending profiles'}
            }), 400

        try:
            picture_url = save_quick_profile_picture(image_data, profile.id, profile.player_name)
            profile.profile_picture_url = picture_url
            session.commit()
        except ValueError as e:
            session.rollback()
            return jsonify({
                'success': False,
                'error': {'code': 'INVALID_IMAGE', 'message': str(e), 'field': 'photo_base64'}
            }), 400
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating quick profile {profile_id} photo: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': {'code': 'SERVER_ERROR', 'message': 'Failed to update photo'}
            }), 500

        logger.info(f"Quick profile {profile_id} photo updated by user {current_user_id}")
        return jsonify({
            'success': True,
            'message': 'Photo updated',
            'profile_picture_url': picture_url
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

    claim_code = (data.get('claim_code') or '').strip().upper()

    # Validate format
    if not claim_code or len(claim_code) != 6 or not claim_code.isalnum():
        return jsonify({
            'valid': False,
            'reason': 'invalid_format',
            'message': 'Claim code must be 6 alphanumeric characters'
        }), 200

    with managed_session() as session:
        # Load on the managed session so is_valid()'s EXPIRED-status write
        # (if the code has lapsed) persists here instead of on db.session.
        profile = QuickProfile.find_by_code(claim_code, session=session)

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
        email = (data.get('email') or '').strip() or profile.email

        if not email:
            return jsonify({
                'success': False,
                'message': 'No email address provided'
            }), 400

        # Persist the address the deferred task will send to. Delivery is deferred
        # to a Celery task that fires AFTER this session commits, so the email
        # provider HTTP call never runs inside the open transaction.
        profile.email = email

        from app.services.quick_profile_notifications import defer_claim_code_send
        defer_claim_code_send(profile.id, via_email=True, via_sms=False)

        logger.info(f"Claim code email queued to {email} for profile {profile_id}")
        return jsonify({
            'success': True,
            'message': f'Claim code queued to {email}'
        }), 200


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
        phone = (data.get('phone_number') or '').strip() or (data.get('phone') or '').strip() or profile.phone_number

        if not phone:
            return jsonify({
                'success': False,
                'message': 'No phone number provided'
            }), 400

        # Persist canonical digits-only (the task re-derives +E.164 at send time,
        # so every writer stores the number the same way). Delivery is deferred to
        # a Celery task firing AFTER commit — no SMS HTTP call inside the txn.
        phone_digits = re.sub(r'\D', '', phone)
        if len(phone_digits) < 10:
            return jsonify({
                'success': False,
                'message': 'Invalid phone number'
            }), 400
        profile.phone_number = phone_digits

        from app.services.quick_profile_notifications import defer_claim_code_send
        defer_claim_code_send(profile.id, via_email=False, via_sms=True)

        logger.info(f"Claim code SMS queued for profile {profile_id}")
        return jsonify({
            'success': True,
            'message': 'Claim code queued via SMS'
        }), 200
