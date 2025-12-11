# app/wallet_pass/services/push_service.py

"""
Wallet Pass Push Notification Service

Handles push updates for wallet passes across platforms:
- Apple Wallet: Uses APNs (Apple Push Notification service) with JWT token-based auth
- Google Wallet: Uses Google Wallet API to update objects directly
"""

import os
import json
import logging
import time
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

from app.core import db
from app.models.wallet import WalletPass, WalletPassDevice, WalletPassType

logger = logging.getLogger(__name__)

# Apple Push Notification service settings
APNS_USE_SANDBOX = os.getenv('APNS_USE_SANDBOX', 'true').lower() == 'true'
APNS_SANDBOX_HOST = 'api.sandbox.push.apple.com'
APNS_PRODUCTION_HOST = 'api.push.apple.com'

# APNs authentication mode: 'token' (recommended) or 'certificate'
APNS_AUTH_MODE = os.getenv('APNS_AUTH_MODE', 'token')

# Try to import Apple push notification library
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("httpx not installed. Apple push notifications will not be available.")

# Try to import JWT library for token-based auth
try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logger.warning("PyJWT not installed. Token-based APNs auth will not be available.")

# Try to import Google Wallet library
try:
    from app.wallet_pass.generators.google import GooglePassGenerator, GooglePassConfig, GOOGLE_WALLET_AVAILABLE
except ImportError:
    GOOGLE_WALLET_AVAILABLE = False


class PushService:
    """
    Service for sending push updates to wallet passes.

    Handles both Apple Wallet (via APNs) and Google Wallet (via API updates).

    APNs Authentication:
    - Token-based (recommended): Uses JWT signed with .p8 key file
    - Certificate-based (legacy): Uses .pem certificate files
    """

    def __init__(self):
        self._apple_client = None
        self._jwt_token = None
        self._jwt_token_time = 0
        # JWT tokens are valid for 1 hour, refresh after 50 minutes
        self._jwt_token_lifetime = 50 * 60

    def _get_apns_jwt_token(self) -> Optional[str]:
        """
        Generate or return cached JWT token for APNs authentication.

        Token is cached and refreshed before expiry (APNs tokens valid for 1 hour).

        Loads configuration from:
        1. Database (WalletCertificate with type='apns_key') - preferred, set via wizard UI
        2. Environment variables (APNS_KEY_ID, APNS_KEY_PATH, APNS_TEAM_ID) - fallback

        Returns:
            JWT token string, or None if unable to generate
        """
        if not JWT_AVAILABLE:
            logger.error("PyJWT not installed - cannot use token-based auth")
            return None

        # Return cached token if still valid
        current_time = time.time()
        if self._jwt_token and (current_time - self._jwt_token_time) < self._jwt_token_lifetime:
            return self._jwt_token

        # Try to get config from database first (uploaded via wizard)
        key_id = None
        key_path = None
        team_id = None

        try:
            from app.models.wallet_asset import WalletCertificate
            apns_cert = WalletCertificate.get_active_by_type('apns_key', platform='apple')
            if apns_cert:
                key_id = apns_cert.apns_key_id
                team_id = apns_cert.team_identifier
                # Use standard location where asset_service copies the key
                key_path = 'app/wallet_pass/certs/apns_key.p8'
                logger.debug(f"Using APNs config from database: key_id={key_id}, team_id={team_id}")
        except Exception as e:
            logger.warning(f"Could not load APNs config from database: {e}")

        # Fall back to environment variables
        if not key_id:
            key_id = os.getenv('APNS_KEY_ID')
        if not key_path:
            key_path = os.getenv('APNS_KEY_PATH')
        if not team_id:
            team_id = os.getenv('APNS_TEAM_ID') or os.getenv('WALLET_TEAM_ID')

        if not all([key_id, key_path, team_id]):
            logger.error(f"Missing APNs token config: key_id={bool(key_id)}, key_path={bool(key_path)}, team_id={bool(team_id)}")
            return None

        if not os.path.exists(key_path):
            logger.error(f"APNs key file not found: {key_path}")
            return None

        try:
            # Read the private key
            with open(key_path, 'r') as f:
                private_key = f.read()

            # Create JWT token
            token_time = int(current_time)
            token = jwt.encode(
                {
                    'iss': team_id,
                    'iat': token_time
                },
                private_key,
                algorithm='ES256',
                headers={
                    'alg': 'ES256',
                    'kid': key_id
                }
            )

            self._jwt_token = token
            self._jwt_token_time = current_time
            logger.info(f"Generated new APNs JWT token (team: {team_id}, key: {key_id})")
            return token

        except Exception as e:
            logger.error(f"Failed to generate APNs JWT token: {e}")
            return None

    # =========================================================================
    # Apple Wallet Push Notifications
    # =========================================================================

    def send_apple_push_update(self, wallet_pass: WalletPass) -> Dict[str, Any]:
        """
        Send push notification to Apple Wallet for a pass update.

        This tells Apple devices to check for a pass update.
        The device will then call back to our server to get the updated pass.

        Args:
            wallet_pass: WalletPass that was updated

        Returns:
            Dict with success status and details
        """
        result = {
            'platform': 'apple',
            'sent': 0,
            'failed': 0,
            'errors': []
        }

        if not HTTPX_AVAILABLE:
            result['errors'].append("httpx library not installed")
            return result

        # Get all registered devices for this pass
        devices = WalletPassDevice.query.filter_by(
            wallet_pass_id=wallet_pass.id,
            platform='apple'
        ).all()

        if not devices:
            logger.debug(f"No Apple devices registered for pass {wallet_pass.serial_number}")
            return result

        # Determine APNs host
        apns_host = APNS_SANDBOX_HOST if APNS_USE_SANDBOX else APNS_PRODUCTION_HOST

        # Prepare authentication based on mode
        auth_mode = APNS_AUTH_MODE.lower()
        jwt_token = None
        cert_path = None
        key_path = None

        if auth_mode == 'token':
            # Token-based authentication (recommended)
            jwt_token = self._get_apns_jwt_token()
            if not jwt_token:
                result['errors'].append("Failed to generate APNs JWT token")
                return result
            logger.debug(f"Using token-based APNs auth")
        else:
            # Certificate-based authentication (legacy)
            cert_path = os.getenv('APPLE_WALLET_CERTIFICATE_PATH')
            key_path = os.getenv('APPLE_WALLET_KEY_PATH')

            if not cert_path or not key_path:
                result['errors'].append("Apple certificate paths not configured")
                return result

            if not os.path.exists(cert_path) or not os.path.exists(key_path):
                result['errors'].append("Apple certificate files not found")
                return result
            logger.debug(f"Using certificate-based APNs auth")

        # Send push to each device
        for device in devices:
            try:
                success = self._send_apns_push(
                    push_token=device.push_token,
                    apns_host=apns_host,
                    jwt_token=jwt_token,
                    cert_path=cert_path,
                    key_path=key_path
                )
                if success:
                    result['sent'] += 1
                else:
                    result['failed'] += 1
            except Exception as e:
                result['failed'] += 1
                result['errors'].append(f"Device {device.id}: {str(e)}")
                logger.error(f"Error sending Apple push to device {device.id}: {e}")

        logger.info(
            f"Apple push for pass {wallet_pass.serial_number}: "
            f"sent={result['sent']}, failed={result['failed']}"
        )

        return result

    def _send_apns_push(
        self,
        push_token: str,
        apns_host: str,
        jwt_token: Optional[str] = None,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None
    ) -> bool:
        """
        Send APNs push notification for a pass update.

        Apple Wallet passes use empty payload pushes - the notification
        just tells the device to request an update from our server.

        Supports both token-based (JWT) and certificate-based authentication.

        Args:
            push_token: Device push token
            apns_host: APNs hostname
            jwt_token: JWT token for token-based auth (preferred)
            cert_path: Path to certificate file (for cert-based auth)
            key_path: Path to key file (for cert-based auth)

        Returns:
            True if successful
        """
        if not HTTPX_AVAILABLE:
            return False

        url = f"https://{apns_host}/3/device/{push_token}"

        # Apple Wallet passes use an empty payload
        payload = {}

        # Build headers
        headers = {
            'apns-topic': os.getenv('APPLE_WALLET_PASS_TYPE_ID', 'pass.com.weareecs.membership'),
            'apns-push-type': 'background',
            'apns-priority': '5'
        }

        try:
            if jwt_token:
                # Token-based authentication
                headers['authorization'] = f'bearer {jwt_token}'

                with httpx.Client(
                    http2=True,
                    timeout=30.0
                ) as client:
                    response = client.post(
                        url,
                        json=payload,
                        headers=headers
                    )
            else:
                # Certificate-based authentication
                if not cert_path or not key_path:
                    logger.error("Certificate paths required for cert-based auth")
                    return False

                with httpx.Client(
                    http2=True,
                    cert=(cert_path, key_path),
                    timeout=30.0
                ) as client:
                    response = client.post(
                        url,
                        json=payload,
                        headers=headers
                    )

            if response.status_code == 200:
                logger.debug(f"APNs push successful for token {push_token[:16]}...")
                return True
            else:
                logger.warning(f"APNs returned status {response.status_code}: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error sending APNs push: {e}")
            raise

    # =========================================================================
    # Google Wallet Updates
    # =========================================================================

    def send_google_update(self, wallet_pass: WalletPass) -> Dict[str, Any]:
        """
        Update a Google Wallet pass object.

        Google Wallet passes are updated by calling the API to modify
        the pass object. Changes are reflected immediately on devices.

        Args:
            wallet_pass: WalletPass that was updated

        Returns:
            Dict with success status and details
        """
        result = {
            'platform': 'google',
            'success': False,
            'error': None
        }

        if not GOOGLE_WALLET_AVAILABLE:
            result['error'] = "Google Wallet library not installed"
            return result

        if not wallet_pass.google_pass_generated:
            result['error'] = "Pass has not been generated for Google Wallet"
            return result

        try:
            # Get pass type for generator
            pass_type = wallet_pass.pass_type

            # Create generator
            generator = GooglePassGenerator(pass_type)

            # Re-generate the pass (this updates the existing object)
            save_url = generator.generate(wallet_pass)

            # Update tracking
            wallet_pass.google_pass_url = save_url
            wallet_pass.version += 1
            db.session.commit()

            result['success'] = True
            result['url'] = save_url

            logger.info(f"Updated Google Wallet pass for {wallet_pass.member_name}")

        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Error updating Google Wallet pass: {e}")

        return result

    # =========================================================================
    # Combined Updates
    # =========================================================================

    def send_update_to_all_platforms(self, wallet_pass: WalletPass) -> Dict[str, Any]:
        """
        Send update notifications to all platforms where the pass exists.

        Args:
            wallet_pass: WalletPass that was updated

        Returns:
            Dict with results for each platform
        """
        results = {
            'apple': None,
            'google': None,
            'any_success': False
        }

        # Update Apple Wallet
        if wallet_pass.apple_pass_generated:
            results['apple'] = self.send_apple_push_update(wallet_pass)
            if results['apple']['sent'] > 0:
                results['any_success'] = True

        # Update Google Wallet
        if wallet_pass.google_pass_generated:
            results['google'] = self.send_google_update(wallet_pass)
            if results['google']['success']:
                results['any_success'] = True

        return results

    def update_pass_status(
        self,
        wallet_pass: WalletPass,
        new_status: str,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update a pass's status and notify all platforms.

        Args:
            wallet_pass: WalletPass to update
            new_status: New status value
            reason: Optional reason for the status change

        Returns:
            Dict with update results
        """
        # Update the pass
        wallet_pass.status = new_status
        wallet_pass.version += 1

        if new_status == 'voided' and reason:
            wallet_pass.voided_at = datetime.utcnow()
            wallet_pass.voided_reason = reason

        db.session.commit()

        # Send updates to platforms
        return self.send_update_to_all_platforms(wallet_pass)

    def update_pass_design(self, pass_type: WalletPassType) -> Dict[str, Any]:
        """
        Update all passes of a type when the design changes.

        When pass type settings (colors, logo, etc.) change,
        this updates all affected passes on user devices.

        Args:
            pass_type: WalletPassType that was updated

        Returns:
            Dict with summary of update results
        """
        results = {
            'total_passes': 0,
            'apple_updated': 0,
            'google_updated': 0,
            'errors': []
        }

        # Get all active passes for this type
        passes = WalletPass.query.filter_by(
            pass_type_id=pass_type.id,
            status='active'
        ).all()

        results['total_passes'] = len(passes)

        for wallet_pass in passes:
            try:
                update_result = self.send_update_to_all_platforms(wallet_pass)

                if update_result['apple'] and update_result['apple']['sent'] > 0:
                    results['apple_updated'] += 1

                if update_result['google'] and update_result['google']['success']:
                    results['google_updated'] += 1

            except Exception as e:
                results['errors'].append(f"Pass {wallet_pass.serial_number}: {str(e)}")
                logger.error(f"Error updating pass {wallet_pass.serial_number}: {e}")

        logger.info(
            f"Design update for {pass_type.name}: "
            f"total={results['total_passes']}, "
            f"apple={results['apple_updated']}, "
            f"google={results['google_updated']}"
        )

        return results


# =========================================================================
# Apple Wallet Webservice Endpoints
# =========================================================================
# These endpoints must be registered in the Flask app for Apple Wallet
# push updates to work. They handle device registration and pass delivery.

def _extract_db_serial(serial_number: str) -> str:
    """
    Extract the database serial number from the Apple Wallet serial number.

    The serial number in the pass is prefixed with "ecsfc-{pass_type_code}-"
    but in the database it's stored without the prefix (just the UUID).

    Example: "ecsfc-ecs_membership-75062d35-19d9-4b16-8132-88b0ca58ef19"
             -> Returns: "75062d35-19d9-4b16-8132-88b0ca58ef19"
    """
    import re

    # UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (36 chars with hyphens)
    if len(serial_number) > 36 and serial_number.startswith('ecsfc-'):
        # Extract the UUID part (last 36 chars)
        potential_uuid = serial_number[-36:]
        # Verify it looks like a UUID (8-4-4-4-12 pattern)
        if re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', potential_uuid):
            return potential_uuid

    return serial_number


def _find_wallet_pass(serial_number: str):
    """Find a wallet pass by serial number, handling both prefixed and raw formats."""
    db_serial = _extract_db_serial(serial_number)

    wallet_pass = WalletPass.query.filter_by(serial_number=db_serial).first()
    if not wallet_pass and db_serial != serial_number:
        # Also try with full serial in case it was stored that way
        wallet_pass = WalletPass.query.filter_by(serial_number=serial_number).first()

    return wallet_pass, db_serial


def register_apple_wallet_routes(app):
    """
    Register Apple Wallet webservice routes.

    These are required for Apple Wallet push updates:
    - Device registration
    - Pass delivery
    - Pass updates
    """
    from flask import Blueprint, request, jsonify, make_response

    apple_wallet_bp = Blueprint('apple_wallet', __name__, url_prefix='/v1')

    @apple_wallet_bp.route('/devices/<device_library_id>/registrations/<pass_type_id>/<serial_number>', methods=['POST'])
    def register_device(device_library_id, pass_type_id, serial_number):
        """Register a device for pass updates."""
        try:
            # Validate authorization
            auth_header = request.headers.get('Authorization', '')
            logger.info(f"Device registration attempt: serial={serial_number}, auth_header_present={bool(auth_header)}")

            if not auth_header.startswith('ApplePass '):
                logger.warning(f"Registration failed: Invalid auth header format. Got: {auth_header[:20] if auth_header else 'empty'}...")
                return make_response('', 401)

            auth_token = auth_header[10:]  # Remove 'ApplePass ' prefix
            logger.info(f"Auth token from header: {auth_token[:8]}...")

            # Find the pass (handles prefixed serial numbers)
            wallet_pass, db_serial = _find_wallet_pass(serial_number)
            if db_serial != serial_number:
                logger.info(f"Extracted UUID from serial: {serial_number} -> {db_serial}")

            if not wallet_pass:
                logger.warning(f"Registration failed: Pass not found with serial_number={db_serial} or {serial_number}")
                return make_response('', 401)

            logger.info(f"Found pass: id={wallet_pass.id}, stored_token={wallet_pass.authentication_token[:8] if wallet_pass.authentication_token else 'NONE'}...")

            # Validate token
            if wallet_pass.authentication_token != auth_token:
                logger.warning(f"Registration failed: Token mismatch. Header token: {auth_token[:8]}..., DB token: {wallet_pass.authentication_token[:8] if wallet_pass.authentication_token else 'NONE'}...")
                return make_response('', 401)

            # Get push token from request body
            data = request.get_json() or {}
            push_token = data.get('pushToken')

            if not push_token:
                return make_response('', 400)

            # Register device
            device = WalletPassDevice.find_or_create(
                wallet_pass_id=wallet_pass.id,
                device_library_id=device_library_id,
                push_token=push_token,
                platform='apple'
            )
            db.session.add(device)
            db.session.commit()

            logger.info(f"Device registered for pass {serial_number}")
            return make_response('', 201)

        except Exception as e:
            logger.error(f"Error registering device: {e}")
            return make_response('', 500)

    @apple_wallet_bp.route('/devices/<device_library_id>/registrations/<pass_type_id>/<serial_number>', methods=['DELETE'])
    def unregister_device(device_library_id, pass_type_id, serial_number):
        """Unregister a device from pass updates."""
        try:
            # Validate authorization
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('ApplePass '):
                return make_response('', 401)

            auth_token = auth_header[10:]

            # Find the pass (handles prefixed serial numbers)
            wallet_pass, _ = _find_wallet_pass(serial_number)
            if not wallet_pass:
                return make_response('', 401)

            # Validate token
            if wallet_pass.authentication_token != auth_token:
                return make_response('', 401)

            # Find and delete device registration
            device = WalletPassDevice.query.filter_by(
                wallet_pass_id=wallet_pass.id,
                device_library_id=device_library_id
            ).first()

            if device:
                db.session.delete(device)
                db.session.commit()

            logger.info(f"Device unregistered from pass {serial_number}")
            return make_response('', 200)

        except Exception as e:
            logger.error(f"Error unregistering device: {e}")
            return make_response('', 500)

    @apple_wallet_bp.route('/devices/<device_library_id>/registrations/<pass_type_id>', methods=['GET'])
    def get_serial_numbers(device_library_id, pass_type_id):
        """Get serial numbers for passes registered to a device."""
        try:
            # Get passes for this device
            devices = WalletPassDevice.query.filter_by(
                device_library_id=device_library_id,
                platform='apple'
            ).all()

            if not devices:
                return make_response('', 204)

            # Get serial numbers and last updated time
            serial_numbers = []
            last_updated = None

            for device in devices:
                wallet_pass = device.wallet_pass
                if wallet_pass:
                    serial_numbers.append(wallet_pass.serial_number)
                    if last_updated is None or wallet_pass.updated_at > last_updated:
                        last_updated = wallet_pass.updated_at

            # Check if we should filter by passesUpdatedSince
            passes_updated_since = request.args.get('passesUpdatedSince')
            if passes_updated_since:
                # Filter to only passes updated after the given time
                # (simplified implementation)
                pass

            return jsonify({
                'serialNumbers': serial_numbers,
                'lastUpdated': last_updated.isoformat() if last_updated else None
            })

        except Exception as e:
            logger.error(f"Error getting serial numbers: {e}")
            return make_response('', 500)

    @apple_wallet_bp.route('/passes/<pass_type_id>/<serial_number>', methods=['GET'])
    def get_pass(pass_type_id, serial_number):
        """Get the latest version of a pass."""
        try:
            from app.wallet_pass.services.pass_service import pass_service
            from flask import send_file

            # Validate authorization
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('ApplePass '):
                return make_response('', 401)

            auth_token = auth_header[10:]

            # Find the pass (handles prefixed serial numbers)
            wallet_pass, _ = _find_wallet_pass(serial_number)
            if not wallet_pass:
                return make_response('', 401)

            # Validate token
            if wallet_pass.authentication_token != auth_token:
                return make_response('', 401)

            # Generate and return the pass
            pass_file, filename, mimetype = pass_service.get_pass_download(wallet_pass, 'apple')

            response = make_response(send_file(
                pass_file,
                mimetype=mimetype,
                as_attachment=True,
                download_name=filename
            ))
            response.headers['Last-Modified'] = wallet_pass.updated_at.strftime('%a, %d %b %Y %H:%M:%S GMT')
            return response

        except Exception as e:
            logger.error(f"Error getting pass: {e}")
            return make_response('', 500)

    @apple_wallet_bp.route('/log', methods=['POST'])
    def log_messages():
        """Receive log messages from Apple Wallet (optional)."""
        try:
            data = request.get_json() or {}
            logs = data.get('logs', [])

            for log_entry in logs:
                logger.info(f"Apple Wallet log: {log_entry}")

            return make_response('', 200)

        except Exception as e:
            logger.error(f"Error processing Apple Wallet logs: {e}")
            return make_response('', 500)

    app.register_blueprint(apple_wallet_bp)
    logger.info("Registered Apple Wallet webservice routes")


# Singleton instance
push_service = PushService()
