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


def _resolve_member_barcode(session_db, user_id, player, team_name, season_name):
    """Return the stable barcode value for a member.

    Prefers WalletPass.barcode_data when an active row exists for the user
    (format: ECSFC-{TYPE}-{SHORT_SERIAL}). Falls back to a deterministic
    synthetic value when no WalletPass row exists yet so legacy clients
    still get the same QR string across calls — never includes uuid/timestamp,
    which historically rotated the value on every fetch and broke any
    server-side token lookup.
    """
    existing = session_db.query(WalletPass).filter(
        WalletPass.user_id == user_id,
        WalletPass.status == 'active'
    ).first()
    if existing and existing.barcode_data:
        return existing.barcode_data
    seed = f"ECS-{player.id}-{team_name}-{season_name}"
    barcode_hash = hashlib.md5(seed.encode()).hexdigest()[:12].upper()
    return f"ECS2025{barcode_hash}"


def _pass_team_name(session_db, player, viewer_user_id, default="ECS FC"):
    """Team name for pass display, honoring the make_teams_public reveal gate:
    a hidden current Premier/Classic team reads as 'Unassigned' for
    non-coach/non-admin viewers."""
    team = player.primary_team
    if team is None and getattr(player, 'teams', None):
        team = player.teams[0] if len(player.teams) > 0 else None
    if team is None:
        return default
    from app.services.team_visibility import is_current_pub_league_team, mobile_user_can_view_teams
    if is_current_pub_league_team(team) and not mobile_user_can_view_teams(session_db, viewer_user_id):
        return "Unassigned"
    return team.name


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
            team_name = _pass_team_name(session_db, player, current_user_id)

            league_name = player.league.name if player.league else "Pub League"

            # Get current season
            current_season = session_db.query(Season).filter_by(
                league_type='Pub League',
                is_current=True
            ).first()
            season_name = current_season.name if current_season else "Spring 2025"

            barcode_value = _resolve_member_barcode(session_db, current_user_id, player, team_name, season_name)

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


@mobile_api_v2.route('/membership/pass/reset-code', methods=['POST'])
@jwt_required()
def reset_membership_pass_code():
    """Rotate the credentials on the user's active wallet pass.

    Issues a fresh `barcode_data` (the QR coaches scan), `download_token`
    (the public download URL), and `authentication_token` (the PassKit
    web service auth). Old installed pass on Apple Wallet becomes inert
    — Wallet will no longer be able to update it because the new auth
    token doesn't match. Any existing `WalletPassDevice` rows for the
    pass are wiped so the user starts fresh after re-adding.

    Returns the new pass info (same shape as `GET /membership/pass`) so
    the app can immediately offer "Add to Apple Wallet" with the rotated
    URL.
    """
    try:
        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())
            user = session_db.query(User).get(current_user_id)
            if not user:
                return jsonify({"msg": "User not found"}), 404
            player = session_db.query(Player).filter_by(user_id=current_user_id).first()
            if not player or not player.is_current_player:
                return jsonify({"msg": "No active membership pass to reset"}), 404

            from app.models.wallet import WalletPass, WalletPassDevice
            wallet_pass = session_db.query(WalletPass).filter(
                WalletPass.user_id == current_user_id,
                WalletPass.status == 'active'
            ).first()
            if not wallet_pass:
                return jsonify({"msg": "No active membership pass to reset"}), 404

            # Rotate identity tokens. serial_number → new barcode_data via
            # generate_barcode_data() which keys off serial.
            wallet_pass.serial_number = WalletPass.generate_serial_number()
            wallet_pass.download_token = WalletPass.generate_download_token()
            wallet_pass.authentication_token = WalletPass.generate_token()
            wallet_pass.barcode_data = wallet_pass.generate_barcode_data()
            wallet_pass.apple_pass_generated = False
            wallet_pass.google_pass_generated = False
            wallet_pass.version = (wallet_pass.version or 0) + 1
            wallet_pass.updated_at = datetime.utcnow()

            # Old installed pass on the user's device can no longer authenticate
            # to PassKit web service — drop the device registrations so the
            # post-reset re-install starts from a clean slate.
            session_db.query(WalletPassDevice).filter_by(
                wallet_pass_id=wallet_pass.id
            ).delete()
            session_db.commit()

            base_url = request.host_url.rstrip('/')
            new_apple_url = f"{base_url}/wallet/pass/by-token/{wallet_pass.download_token}"

            logger.info(
                f"Reset Code: rotated wallet pass {wallet_pass.id} for user {current_user_id} — "
                f"new barcode {wallet_pass.barcode_data}"
            )

            return jsonify({
                "id": str(wallet_pass.id),
                "userId": str(current_user_id),
                "playerName": wallet_pass.member_name,
                "barcodeValue": wallet_pass.barcode_data,
                "barcodeFormat": "qr",
                "passUrl": new_apple_url,
                "appleWallet": {
                    "available": True,
                    "downloadUrl": new_apple_url,
                },
                "message": "Pass reset. Add to Apple Wallet again to install the refreshed pass.",
            }), 200

    except Exception as e:
        logger.error(f"Reset Code failed: {e}", exc_info=True)
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
            team_name = _pass_team_name(session_db, player, current_user_id)

            league_name = player.league.name if player.league else "Pub League"

            # Get current season
            current_season = session_db.query(Season).filter_by(
                league_type='Pub League',
                is_current=True
            ).first()
            season_name = current_season.name if current_season else "Spring 2025"

            preferred_format = data.get('barcode_format', 'qr')
            barcode_value = _resolve_member_barcode(session_db, current_user_id, player, team_name, season_name)

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
        return jsonify({"error": "Failed to download membership pass: Internal Server Error"}), 500


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

            # Look up the user's active WalletPass once — used for token-authenticated
            # Apple Wallet URL and Google Wallet save URL.
            wallet_pass = session_db.query(WalletPass).filter(
                WalletPass.user_id == current_user_id,
                WalletPass.status == 'active'
            ).first()

            # Apple Wallet / Safari can't send Authorization or X-API-Key
            # headers, so the URL we hand back must live OUTSIDE /api/v1/.
            # The /wallet/pass/by-token/<token> route is unauthenticated;
            # the download_token (256 bits of entropy) is the security boundary.
            #
            # Without a WalletPass row we have no token — return None for the
            # Apple URLs; Flutter renders a "Generate pass first" CTA in that
            # case rather than try to open a 401.
            if wallet_pass:
                apple_pass_url = f"{base_url}/wallet/pass/by-token/{wallet_pass.download_token}"
            else:
                apple_pass_url = None

            # Check Google Wallet configuration
            google_config = pass_service.get_google_config_status()
            google_available = google_config.get('configured', False)

            # Generate Google Wallet save URL if both Google is configured and we have a pass row.
            # The save URL is a pay.google.com/gp/v/save/<jwt> URL signed by Google's
            # Pass API — already self-authenticating, no app headers needed.
            google_save_url = None
            if google_available and wallet_pass:
                try:
                    google_save_url = pass_service.generate_google_pass_url(wallet_pass)
                except Exception as e:
                    logger.warning(f"Could not generate Google Wallet URL: {e}")

            response_data = {
                # Legacy fields for backwards compatibility — also point to the
                # public route so Safari/Wallet can open them directly.
                "passUrl": apple_pass_url,
                "downloadUrl": apple_pass_url,
                "passTypeIdentifier": "pass.com.ecsfc.membership",
                "serialNumber": wallet_pass.serial_number if wallet_pass else str(player.id),
                # Platform-specific fields
                "appleWallet": {
                    "available": apple_pass_url is not None,
                    "downloadUrl": apple_pass_url,
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


@mobile_api_v2.route('/membership/wallet/pass/refresh-push', methods=['POST'])
@jwt_required()
def trigger_wallet_pass_refresh_push():
    """Force a PassKit push to all of the caller's registered devices.

    Flutter calls this after server-side state changes (player updates,
    Reset Code, etc.) to nudge Apple Wallet into re-fetching the pass.
    No body. Returns per-platform send counts.
    """
    try:
        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())
            wallet_pass = session_db.query(WalletPass).filter(
                WalletPass.user_id == current_user_id,
                WalletPass.status == 'active'
            ).first()
            if not wallet_pass:
                return jsonify({"msg": "No active wallet pass for user"}), 404

            from app.wallet_pass.services.push_service import trigger_wallet_refresh
            result = trigger_wallet_refresh(wallet_pass, commit=False)
            session_db.commit()
            return jsonify({
                'success': bool(result.get('any_success')),
                'apple': result.get('apple'),
                'google': result.get('google'),
            }), 200
    except Exception as e:
        logger.error(f"Error triggering wallet pass refresh push: {e}", exc_info=True)
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
            # Pre-reveal: don't echo a hidden Pub League team back to the scanner
            from app.services.team_visibility import request_viewer_can_view_teams
            shown_team_name = wallet_pass.team_name or "N/A"
            if wallet_pass.team_name and not request_viewer_can_view_teams(session_db):
                from app.models import Team, League, Season
                is_hidden_team = (
                    session_db.query(Team.id)
                    .join(League, Team.league_id == League.id)
                    .join(Season, League.season_id == Season.id)
                    .filter(
                        Team.name == wallet_pass.team_name,
                        League.name.in_(('Premier', 'Classic')),
                        Season.is_current == True  # noqa: E712
                    ).first()
                )
                if is_hidden_team:
                    shown_team_name = "N/A"

            return jsonify({
                "valid": True,
                "memberName": wallet_pass.member_name,
                "teamName": shown_team_name,
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
            team_name = _pass_team_name(session_db, player, current_user_id)

            league_name = player.league.name if player.league else "Pub League"

            # Get current season
            current_season = session_db.query(Season).filter_by(
                league_type='Pub League',
                is_current=True
            ).first()
            season_name = current_season.name if current_season else "Spring 2025"

            barcode_value = _resolve_member_barcode(session_db, current_user_id, player, team_name, season_name)

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


# PUBLIC Apple Wallet pass serving routes (NO JWT — Apple Wallet can't send Authorization headers)


@mobile_api_v2.route('/wallet/pass/by-token/<token>', methods=['GET'])
def serve_apple_wallet_pass_by_token(token):
    """
    Serve a .pkpass authenticated by per-pass signed token.

    Replaces the user_id-keyed route. The token (43 chars, secrets.token_urlsafe(32))
    lives on WalletPass.download_token so knowing a sequential user_id no longer
    grants pass access. Apple Wallet still can't send Authorization headers, but the
    token in the URL provides 256+ bits of entropy per pass.
    """
    try:
        with managed_session() as session_db:
            wallet_pass = session_db.query(WalletPass).filter_by(
                download_token=token,
                status='active'
            ).first()
            if not wallet_pass or not wallet_pass.player_id:
                return "Pass not found", 404

            player = session_db.query(Player).get(wallet_pass.player_id)
            if not player or not player.is_current_player:
                return "Pass expired", 410

            from app.wallet_pass import create_pass_for_player
            logger.info(f"Serving Apple Wallet pass via token for player {player.name}")
            pass_data = create_pass_for_player(player.id)

            response = make_response(pass_data.getvalue())
            response.headers['Content-Type'] = 'application/vnd.apple.pkpass'
            response.headers['Content-Disposition'] = (
                f'attachment; filename="{player.name.replace(" ", "_")}_ecsfc_membership.pkpass"'
            )
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response

    except Exception as e:
        logger.error(f"Error serving Apple Wallet pass by token: {str(e)}")
        return "Internal server error", 500


@mobile_api_v2.route('/wallet/pass/<int:user_id>', methods=['GET'])
def serve_apple_wallet_pass(user_id):
    """
    LEGACY user_id-keyed route. Kept alive temporarily so already-installed passes
    can still update — Apple Wallet apps re-fetch from the URL embedded in the
    pass at install time, and rotating that URL would orphan existing passes.

    New passes should use /wallet/pass/by-token/<token>. Plan: deprecate after one
    season's worth of passes have rotated through.
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
