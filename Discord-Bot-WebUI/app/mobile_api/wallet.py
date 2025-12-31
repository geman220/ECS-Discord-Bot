# app/api/wallet.py

"""
Wallet/Membership Pass API Endpoints

Handles digital membership pass operations including:
- Pass generation
- Pass download
- Pass validation
- Pass refresh
- Apple Wallet integration
"""

import hashlib
import logging
import uuid
from datetime import datetime

from flask import jsonify, request, send_file, make_response
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User, Player, Season
from app.models.wallet import WalletPass

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/membership/pass', methods=['GET'])
@jwt_required()
def get_membership_pass_info():
    """
    Get current user's membership pass - Flutter app expects specific format.

    Returns:
        JSON with membership pass data in camelCase format
    """
    try:
        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())

            # Get user and player
            user = session_db.query(User).get(current_user_id)
            if not user:
                return jsonify({"msg": "User not found"}), 404

            player = session_db.query(Player).filter_by(user_id=current_user_id).first()
            if not player:
                return jsonify({"msg": "No membership pass found"}), 404

            # Check eligibility
            eligible = player.is_current_player and player.user and player.user.is_authenticated
            has_team = (player.primary_team is not None) or (hasattr(player, 'teams') and player.teams and len(player.teams) > 0)

            if not (eligible and has_team):
                return jsonify({"msg": "User must be assigned to a team"}), 400

            # Get team and league info
            team_name = "ECS FC"
            if player.primary_team:
                team_name = player.primary_team.name
            elif hasattr(player, 'teams') and player.teams and len(player.teams) > 0:
                team_name = player.teams[0].name

            league_name = player.league.name if player.league else "Pub League"

            # Get current season
            current_season = session_db.query(Season).filter_by(
                league_type='Pub League',
                is_current=True
            ).first()
            season_name = current_season.name if current_season else "Spring 2025"

            # Generate barcode value (unique identifier)
            barcode_data = f"ECS-{player.id}-{team_name}-{season_name}-{uuid.uuid4().hex[:8]}"
            barcode_hash = hashlib.md5(barcode_data.encode()).hexdigest()[:12].upper()
            barcode_value = f"ECS2025{barcode_hash}"

            # Build profile picture URL
            profile_picture_url = None
            if player.profile_picture_url:
                if player.profile_picture_url.startswith('http'):
                    profile_picture_url = player.profile_picture_url
                else:
                    profile_picture_url = f"{request.host_url.rstrip('/')}{player.profile_picture_url}"

            # Build logo URL (team kit)
            logo_url = None
            if player.primary_team and hasattr(player.primary_team, 'kit_url') and player.primary_team.kit_url:
                if player.primary_team.kit_url.startswith('http'):
                    logo_url = player.primary_team.kit_url
                else:
                    logo_url = f"{request.host_url.rstrip('/')}{player.primary_team.kit_url}"

            # Return in exact Flutter app format (camelCase)
            now = datetime.utcnow()

            response_data = {
                "id": str(player.id),
                "userId": str(current_user_id),
                "playerName": player.name,
                "teamName": team_name,
                "division": league_name,
                "season": season_name,
                "status": "active" if player.is_current_player else "inactive",
                "barcodeValue": barcode_value,
                "barcodeFormat": "qr",
                "profilePictureUrl": profile_picture_url,
                "logoUrl": logo_url,
                "expiresAt": None,  # Set expiration logic as needed
                "createdAt": now.isoformat() + "Z",
                "updatedAt": now.isoformat() + "Z"
            }

            return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Error getting membership pass info: {str(e)}")
        return jsonify({"msg": "Internal server error"}), 500


@mobile_api_v2.route('/membership/pass/generate', methods=['POST'])
@jwt_required()
def generate_membership_pass():
    """
    Generate a new membership pass for the current user.

    Returns:
        JSON with new membership pass data in Flutter format
    """
    try:
        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())
            data = request.get_json() or {}

            # Get user and player
            user = session_db.query(User).get(current_user_id)
            if not user:
                return jsonify({"msg": "User not found"}), 404

            player = session_db.query(Player).filter_by(user_id=current_user_id).first()
            if not player:
                return jsonify({"msg": "No membership pass found"}), 404

            # Check eligibility
            if not player.is_current_player:
                return jsonify({"msg": "User must be assigned to a team"}), 400

            has_team = (player.primary_team is not None) or (hasattr(player, 'teams') and player.teams and len(player.teams) > 0)
            if not has_team:
                return jsonify({"msg": "User must be assigned to a team"}), 400

            # Get team and league info
            team_name = "ECS FC"
            if player.primary_team:
                team_name = player.primary_team.name
            elif hasattr(player, 'teams') and player.teams and len(player.teams) > 0:
                team_name = player.teams[0].name

            league_name = player.league.name if player.league else "Pub League"

            # Get current season
            current_season = session_db.query(Season).filter_by(
                league_type='Pub League',
                is_current=True
            ).first()
            season_name = current_season.name if current_season else "Spring 2025"

            # Generate NEW barcode value (fresh generation)
            barcode_data = f"ECS-{player.id}-{team_name}-{season_name}-{uuid.uuid4().hex[:8]}-{datetime.utcnow().timestamp()}"
            barcode_hash = hashlib.md5(barcode_data.encode()).hexdigest()[:12].upper()
            preferred_format = data.get('barcode_format', 'qr')
            barcode_value = f"ECS2025{barcode_hash}"

            # Build profile picture URL
            profile_picture_url = None
            if player.profile_picture_url:
                if player.profile_picture_url.startswith('http'):
                    profile_picture_url = player.profile_picture_url
                else:
                    profile_picture_url = f"{request.host_url.rstrip('/')}{player.profile_picture_url}"

            # Build logo URL (team kit)
            logo_url = None
            if player.primary_team and hasattr(player.primary_team, 'kit_url') and player.primary_team.kit_url:
                if player.primary_team.kit_url.startswith('http'):
                    logo_url = player.primary_team.kit_url
                else:
                    logo_url = f"{request.host_url.rstrip('/')}{player.primary_team.kit_url}"

            # Generate Apple Wallet pass in background
            try:
                from app.wallet_pass import create_pass_for_player
                logger.info(f"Generating wallet pass via mobile API for user {user.email} (player: {player.name})")
                create_pass_for_player(player.id)  # Generate but don't return file here
            except Exception as wallet_error:
                logger.warning(f"Apple Wallet pass generation failed (continuing with mobile pass): {str(wallet_error)}")

            # Return new pass data in Flutter format (Status 201 for created)
            now = datetime.utcnow()
            response_data = {
                "id": str(player.id + 1000),  # New ID for generated pass
                "userId": str(current_user_id),
                "playerName": player.name,
                "teamName": team_name,
                "division": league_name,
                "season": season_name,
                "status": "active",
                "barcodeValue": barcode_value,
                "barcodeFormat": preferred_format,
                "profilePictureUrl": profile_picture_url,
                "logoUrl": logo_url,
                "expiresAt": None,
                "createdAt": now.isoformat() + "Z",
                "updatedAt": now.isoformat() + "Z"
            }

            return jsonify(response_data), 201

    except Exception as e:
        logger.error(f"Error generating membership pass via mobile API: {str(e)}")
        return jsonify({"msg": "Internal server error"}), 500


@mobile_api_v2.route('/membership/pass/download', methods=['GET'])
@jwt_required()
def download_membership_pass():
    """
    Download the Apple Wallet .pkpass file for the current user.

    Returns:
        Binary .pkpass file for download
    """
    try:
        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())

            # Get user and player
            user = session_db.query(User).get(current_user_id)
            if not user:
                return jsonify({"error": "User not found"}), 404

            player = session_db.query(Player).filter_by(user_id=current_user_id).first()
            if not player:
                return jsonify({"error": "Player profile not found"}), 404

            # Check eligibility
            if not player.is_current_player:
                return jsonify({
                    "error": "Player is not currently active and cannot download a membership pass"
                }), 403

            # Generate and return the pass file
            from app.wallet_pass import create_pass_for_player
            logger.info(f"Downloading wallet pass via mobile API for user {user.email} (player: {player.name})")

            pass_data = create_pass_for_player(player.id)
            filename = f"{player.name.replace(' ', '_')}_ecsfc_membership.pkpass"

            return send_file(
                pass_data,
                mimetype="application/vnd.apple.pkpass",
                as_attachment=True,
                download_name=filename
            )

    except Exception as e:
        logger.error(f"Error downloading membership pass via mobile API: {str(e)}")
        return jsonify({"error": f"Failed to download membership pass: {str(e)}"}), 500


@mobile_api_v2.route('/membership/wallet/pass', methods=['GET'])
@jwt_required()
def get_wallet_pass_info():
    """
    Get wallet pass info for mobile apps (both iOS and Android).

    Returns:
        JSON with wallet pass URLs for both platforms:
        {
            "passUrl": "...",
            "downloadUrl": "...",
            "passTypeIdentifier": "...",
            "serialNumber": "...",
            "appleWallet": {
                "available": true,
                "downloadUrl": "..."
            },
            "googleWallet": {
                "available": true/false,
                "saveUrl": "..." or null,
                "configured": true/false
            }
        }
    """
    try:
        from app.wallet_pass.services.pass_service import pass_service

        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())

            user = session_db.query(User).get(current_user_id)
            if not user:
                return jsonify({"msg": "User not found"}), 404

            player = session_db.query(Player).filter_by(user_id=current_user_id).first()
            if not player or not player.is_current_player:
                return jsonify({"msg": "No membership pass found"}), 404

            base_url = request.host_url.rstrip('/')

            # Check Google Wallet configuration
            google_config = pass_service.get_google_config_status()
            google_available = google_config.get('configured', False)

            # Check if user has a wallet pass for Google URL generation
            google_save_url = None
            if google_available:
                wallet_pass = session_db.query(WalletPass).filter(
                    WalletPass.user_id == current_user_id,
                    WalletPass.status == 'active'
                ).first()
                if wallet_pass:
                    try:
                        google_save_url = pass_service.generate_google_pass_url(wallet_pass)
                    except Exception as e:
                        logger.warning(f"Could not generate Google Wallet URL: {e}")

            response_data = {
                # Legacy fields for backwards compatibility
                "passUrl": f"{base_url}/api/v1/wallet/pass/{current_user_id}",
                "downloadUrl": f"{base_url}/api/v1/membership/wallet/pass/download",
                "passTypeIdentifier": "pass.com.weareecs.membership",
                "serialNumber": str(player.id),
                # New platform-specific fields
                "appleWallet": {
                    "available": True,
                    "downloadUrl": f"{base_url}/api/v1/membership/wallet/pass/download"
                },
                "googleWallet": {
                    "available": google_available,
                    "configured": google_available,
                    "saveUrl": google_save_url,
                    "endpointUrl": f"{base_url}/api/v1/membership/wallet/google/pass" if google_available else None
                }
            }

            return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Error getting wallet pass info: {str(e)}")
        return jsonify({"msg": "Internal server error"}), 500


@mobile_api_v2.route('/membership/wallet/pass/download', methods=['GET'])
@jwt_required()
def download_wallet_pass_file():
    """
    Download the actual .pkpass file for Apple Wallet (iOS only).

    Returns:
        Binary .pkpass file
    """
    try:
        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())

            user = session_db.query(User).get(current_user_id)
            if not user:
                return jsonify({"msg": "User not found"}), 404

            player = session_db.query(Player).filter_by(user_id=current_user_id).first()
            if not player or not player.is_current_player:
                return jsonify({"msg": "No membership pass found"}), 404

            # Generate and return the Apple Wallet .pkpass file
            from app.wallet_pass import create_pass_for_player
            logger.info(f"Downloading Apple Wallet pass for user {user.email} (player: {player.name})")

            pass_data = create_pass_for_player(player.id)
            filename = f"{player.name.replace(' ', '_')}_ecsfc_membership.pkpass"

            return send_file(
                pass_data,
                mimetype="application/vnd.apple.pkpass",
                as_attachment=True,
                download_name=filename
            )

    except Exception as e:
        logger.error(f"Error downloading wallet pass: {str(e)}")
        return jsonify({"msg": "Internal server error"}), 500


@mobile_api_v2.route('/membership/wallet/google/pass', methods=['GET'])
@jwt_required()
def get_google_wallet_pass():
    """
    Get Google Wallet pass save URL for Android apps.

    Returns:
        JSON with Google Wallet save URL:
        {
            "saveUrl": "https://pay.google.com/gp/v/save/...",
            "platform": "google",
            "available": true
        }
    """
    try:
        from app.wallet_pass.services.pass_service import pass_service
        from app.wallet_pass.generators import GOOGLE_WALLET_AVAILABLE

        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())

            user = session_db.query(User).get(current_user_id)
            if not user:
                return jsonify({"msg": "User not found"}), 404

            player = session_db.query(Player).filter_by(user_id=current_user_id).first()
            if not player or not player.is_current_player:
                return jsonify({"msg": "No membership pass found"}), 404

            # Check if Google Wallet is configured
            google_config = pass_service.get_google_config_status()
            if not google_config.get('configured'):
                return jsonify({
                    "available": False,
                    "platform": "google",
                    "msg": "Google Wallet is not configured",
                    "missing": google_config.get('missing', [])
                }), 503

            # Find or create wallet pass for this user
            wallet_pass = session_db.query(WalletPass).filter(
                WalletPass.user_id == current_user_id,
                WalletPass.status == 'active'
            ).first()

            if not wallet_pass:
                # User doesn't have a pass in the new system yet
                # Return info so app can prompt them to generate one
                return jsonify({
                    "available": True,
                    "platform": "google",
                    "hasPass": False,
                    "msg": "No wallet pass found. Please generate a pass first."
                }), 404

            # Generate Google Wallet save URL
            try:
                save_url = pass_service.generate_google_pass_url(wallet_pass)

                return jsonify({
                    "available": True,
                    "platform": "google",
                    "hasPass": True,
                    "saveUrl": save_url,
                    "memberName": wallet_pass.member_name,
                    "passType": wallet_pass.pass_type.name if wallet_pass.pass_type else "Membership"
                }), 200

            except ImportError as e:
                logger.error(f"Google Wallet library not installed: {e}")
                return jsonify({
                    "available": False,
                    "platform": "google",
                    "msg": "Google Wallet library not installed"
                }), 503

    except Exception as e:
        logger.error(f"Error getting Google Wallet pass: {str(e)}")
        return jsonify({"msg": "Internal server error"}), 500


@mobile_api_v2.route('/membership/pass/validate', methods=['POST'])
@jwt_required()
def validate_membership_pass():
    """
    Validate a barcode for membership pass verification.

    Request Body:
        {
            "barcode": "ECS2025ABCD1234"
        }

    Returns:
        JSON with validation result
    """
    try:
        with managed_session() as session_db:
            data = request.get_json()
            if not data or 'barcode' not in data:
                return jsonify({"msg": "Missing barcode"}), 400

            barcode = data['barcode']

            # Look up the wallet pass by barcode data
            wallet_pass = session_db.query(WalletPass).filter(
                WalletPass.barcode_data == barcode
            ).first()

            if not wallet_pass:
                return jsonify({
                    "valid": False,
                    "msg": "Pass not found"
                }), 200

            # Check if pass is valid (not expired, not voided)
            if not wallet_pass.is_valid:
                reason = "Pass is not active"
                if wallet_pass.status == 'voided':
                    reason = "Pass has been voided"
                elif wallet_pass.is_expired:
                    reason = "Pass has expired"

                return jsonify({
                    "valid": False,
                    "msg": reason,
                    "memberName": wallet_pass.member_name,
                    "passType": wallet_pass.pass_type.name if wallet_pass.pass_type else None
                }), 200

            # Return valid pass information
            return jsonify({
                "valid": True,
                "memberName": wallet_pass.member_name,
                "teamName": wallet_pass.team_name or "N/A",
                "passType": wallet_pass.pass_type.name if wallet_pass.pass_type else "Membership",
                "validUntil": wallet_pass.valid_until.isoformat() if wallet_pass.valid_until else None,
                "status": wallet_pass.status,
                "serialNumber": wallet_pass.serial_number
            }), 200

    except Exception as e:
        logger.error(f"Error validating barcode: {str(e)}")
        return jsonify({"msg": "Internal server error"}), 500


@mobile_api_v2.route('/membership/pass/refresh', methods=['PUT'])
@jwt_required()
def refresh_membership_pass():
    """
    Refresh/update membership pass data.

    Returns:
        Updated pass data or 304 if no changes
    """
    try:
        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())

            # Get user and player
            user = session_db.query(User).get(current_user_id)
            if not user:
                return jsonify({"msg": "User not found"}), 404

            player = session_db.query(Player).filter_by(user_id=current_user_id).first()
            if not player:
                return jsonify({"msg": "No membership pass found"}), 404

            # Get team and league info
            team_name = "ECS FC"
            if player.primary_team:
                team_name = player.primary_team.name
            elif hasattr(player, 'teams') and player.teams and len(player.teams) > 0:
                team_name = player.teams[0].name

            league_name = player.league.name if player.league else "Pub League"

            # Get current season
            current_season = session_db.query(Season).filter_by(
                league_type='Pub League',
                is_current=True
            ).first()
            season_name = current_season.name if current_season else "Spring 2025"

            # Generate barcode value
            barcode_data = f"ECS-{player.id}-{team_name}-{season_name}-{uuid.uuid4().hex[:8]}"
            barcode_hash = hashlib.md5(barcode_data.encode()).hexdigest()[:12].upper()
            barcode_value = f"ECS2025{barcode_hash}"

            # Build URLs
            profile_picture_url = None
            if player.profile_picture_url:
                if player.profile_picture_url.startswith('http'):
                    profile_picture_url = player.profile_picture_url
                else:
                    profile_picture_url = f"{request.host_url.rstrip('/')}{player.profile_picture_url}"

            logo_url = None
            if player.primary_team and hasattr(player.primary_team, 'kit_url') and player.primary_team.kit_url:
                if player.primary_team.kit_url.startswith('http'):
                    logo_url = player.primary_team.kit_url
                else:
                    logo_url = f"{request.host_url.rstrip('/')}{player.primary_team.kit_url}"

            # Return updated pass data
            now = datetime.utcnow()

            response_data = {
                "id": str(player.id),
                "userId": str(current_user_id),
                "playerName": player.name,
                "teamName": team_name,
                "division": league_name,
                "season": season_name,
                "status": "active" if player.is_current_player else "inactive",
                "barcodeValue": barcode_value,
                "barcodeFormat": "qr",
                "profilePictureUrl": profile_picture_url,
                "logoUrl": logo_url,
                "expiresAt": None,
                "createdAt": now.isoformat() + "Z",
                "updatedAt": now.isoformat() + "Z"
            }

            return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Error refreshing membership pass: {str(e)}")
        return jsonify({"msg": "Internal server error"}), 500


# PUBLIC Apple Wallet pass serving route (NO JWT required - Apple Wallet calls this)

@mobile_api_v2.route('/wallet/pass/<int:user_id>', methods=['GET'])
def serve_apple_wallet_pass(user_id):
    """
    PUBLIC route to serve .pkpass files directly to Apple Wallet.

    This route is called by Apple Wallet and CANNOT have JWT authentication
    because Apple Wallet doesn't send authorization headers.

    URL: /api/v1/wallet/pass/2 (clean URL, no .pkpass extension)
    """
    try:
        with managed_session() as session_db:
            # Get user and player (without JWT - Apple Wallet can't authenticate)
            user = session_db.query(User).get(user_id)
            if not user:
                logger.warning(f"Apple Wallet requested pass for non-existent user {user_id}")
                return "Pass not found", 404

            player = session_db.query(Player).filter_by(user_id=user_id).first()
            if not player:
                logger.warning(f"Apple Wallet requested pass for user {user_id} with no player profile")
                return "Pass not available", 404

            # Check if player is eligible (basic check for public route)
            if not player.is_current_player:
                logger.warning(f"Apple Wallet requested pass for inactive player {player.name} (user {user_id})")
                return "Pass expired", 410  # Gone - pass no longer valid

            # Generate and serve the .pkpass file
            from app.wallet_pass import create_pass_for_player
            logger.info(f"Serving Apple Wallet pass to Apple Wallet for user {user.email} (player: {player.name})")

            pass_data = create_pass_for_player(player.id)

            # Create response with proper headers for Apple Wallet
            response = make_response(pass_data.getvalue())
            response.headers['Content-Type'] = 'application/vnd.apple.pkpass'
            response.headers['Content-Disposition'] = f'attachment; filename="{player.name.replace(" ", "_")}_ecsfc_membership.pkpass"'

            # Add caching headers for Apple Wallet
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'

            return response

    except Exception as e:
        logger.error(f"Error serving Apple Wallet pass for user {user_id}: {str(e)}")
        return "Internal server error", 500
