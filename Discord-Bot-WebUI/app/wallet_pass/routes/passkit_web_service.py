# app/wallet_pass/routes/passkit_web_service.py

"""
Apple PassKit Web Service implementation.

Apple Wallet polls these endpoints to keep installed passes in sync. The
spec lives at:
https://developer.apple.com/library/archive/documentation/PassKit/Reference/PassKit_WebService/WebService.html

Mounted at ROOT (no /api/v1/, no /wallet/) because the embedded
`webServiceURL` in pass.json is `https://portal.ecsfc.com` and Apple
appends `/v1/...` to that base. Apple Wallet can't send custom auth
headers either, so the blueprint sits outside any middleware-gated path.

    POST    /v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}/{serialNumber}
    GET     /v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}?passesUpdatedSince=<tag>
    GET     /v1/passes/{passTypeIdentifier}/{serialNumber}
    DELETE  /v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}/{serialNumber}
    POST    /v1/log

Auth: per-pass `Authorization: ApplePass <authentication_token>` header,
where the token is `WalletPass.authentication_token`. (Different from
`download_token` used by /wallet/pass/by-token/<token>.)

Push trigger: when a pass's data changes, call
`trigger_wallet_refresh(wallet_pass)` — that bumps version, updates
`updated_at`, and sends an empty APNs push to every registered device.
The device then comes back through GET /v1/passes/... to fetch the new
.pkpass.
"""

import logging
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime

from flask import Blueprint, request, jsonify, make_response

from app.core import db
from app.core.session_manager import managed_session
from app.models.wallet import WalletPass, WalletPassDevice
from app.wallet_pass.services.pass_service import pass_service

logger = logging.getLogger(__name__)

# Mounted at root — full paths are /v1/devices/..., /v1/passes/..., /v1/log.
# Matches the existing WALLET_WEB_SERVICE_URL=https://portal.ecsfc.com env
# value (Apple PassKit appends /v1/... to that base). Separate blueprint
# from /wallet/pass/by-token/... so the two concerns stay isolated.
passkit_web_service_bp = Blueprint(
    'apple_passkit_web_service',
    __name__,
)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _check_apple_pass_auth(wallet_pass: WalletPass) -> bool:
    """Verify Authorization: ApplePass <token> header matches the pass."""
    auth = request.headers.get('Authorization', '')
    if not auth.lower().startswith('applepass '):
        return False
    token = auth.split(' ', 1)[1].strip()
    return bool(token) and token == wallet_pass.authentication_token


def _resolve_pass(pass_type_identifier: str, serial_number: str, session) -> WalletPass | None:
    """Look up a WalletPass by the (passTypeIdentifier, serialNumber) pair Apple sends.

    The pass_type_identifier is the cert-bound Apple identifier
    (e.g. 'pass.com.ecsfc.membership'). serialNumber is whatever the
    pass.json embedded — for our generator that's the pass's stable
    serial. We accept either WalletPass.serial_number or
    'ecs-v1-{serial_number}' / 'ecs-pub-{serial_number}' templates.
    """
    candidates = [serial_number]
    if serial_number.startswith('ecs-v1-'):
        candidates.append(serial_number[len('ecs-v1-'):])
    if serial_number.startswith('ecs-pub-'):
        candidates.append(serial_number[len('ecs-pub-'):])
    for candidate in candidates:
        wp = session.query(WalletPass).filter(
            WalletPass.serial_number == candidate
        ).first()
        if wp:
            return wp
    return None


# ---------------------------------------------------------------------------
# 1. Register device
# POST /v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}/{serialNumber}
# Body: {"pushToken": "<token>"}
# ---------------------------------------------------------------------------

@passkit_web_service_bp.route(
    '/v1/devices/<device_library_id>/registrations/<pass_type_identifier>/<serial_number>',
    methods=['POST'],
)
def register_device(device_library_id: str, pass_type_identifier: str, serial_number: str):
    try:
        with managed_session() as session:
            wp = _resolve_pass(pass_type_identifier, serial_number, session)
            if not wp:
                return ('', 404)
            if not _check_apple_pass_auth(wp):
                return ('', 401)

            data = request.get_json(silent=True) or {}
            push_token = (data.get('pushToken') or '').strip()
            if not push_token:
                return ('', 400)

            existing = session.query(WalletPassDevice).filter_by(
                wallet_pass_id=wp.id,
                device_library_id=device_library_id,
            ).first()

            if existing:
                # Already registered — refresh push token if changed.
                if existing.push_token != push_token:
                    existing.push_token = push_token
                    existing.last_updated_at = datetime.utcnow()
                    session.commit()
                return ('', 200)

            session.add(WalletPassDevice(
                wallet_pass_id=wp.id,
                device_library_id=device_library_id,
                push_token=push_token,
                platform='apple',
            ))
            session.commit()
            logger.info(
                f"PassKit register: pass={wp.serial_number[:8]}... "
                f"device={device_library_id[:12]}..."
            )
            return ('', 201)
    except Exception as e:
        logger.error(f"PassKit register_device error: {e}", exc_info=True)
        return ('', 500)


# ---------------------------------------------------------------------------
# 2. List updated passes for a device
# GET /v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}?passesUpdatedSince=<tag>
# Returns {"serialNumbers":[...], "lastUpdated":"<tag>"} or 204 No Content
# ---------------------------------------------------------------------------

@passkit_web_service_bp.route(
    '/v1/devices/<device_library_id>/registrations/<pass_type_identifier>',
    methods=['GET'],
)
def get_updated_passes(device_library_id: str, pass_type_identifier: str):
    try:
        since_param = request.args.get('passesUpdatedSince')
        since_ts = None
        if since_param:
            try:
                since_ts = datetime.utcfromtimestamp(float(since_param))
            except (TypeError, ValueError):
                # Unparseable tag — treat as "no since", return everything.
                since_ts = None

        with managed_session() as session:
            q = (
                session.query(WalletPass)
                .join(WalletPassDevice, WalletPassDevice.wallet_pass_id == WalletPass.id)
                .filter(WalletPassDevice.device_library_id == device_library_id)
                .filter(WalletPass.status == 'active')
            )
            if since_ts:
                q = q.filter(WalletPass.updated_at > since_ts)

            rows = q.all()
            if not rows:
                return ('', 204)

            latest = max((wp.updated_at for wp in rows if wp.updated_at), default=datetime.utcnow())
            return jsonify({
                'serialNumbers': [wp.serial_number for wp in rows],
                'lastUpdated': str(latest.replace(tzinfo=timezone.utc).timestamp()),
            }), 200
    except Exception as e:
        logger.error(f"PassKit get_updated_passes error: {e}", exc_info=True)
        return ('', 500)


# ---------------------------------------------------------------------------
# 3. Get latest pass
# GET /v1/passes/{passTypeIdentifier}/{serialNumber}
# Headers: Authorization: ApplePass <token>, If-Modified-Since: <date>
# Returns .pkpass with Last-Modified header, or 304 Not Modified.
# ---------------------------------------------------------------------------

@passkit_web_service_bp.route(
    '/v1/passes/<pass_type_identifier>/<serial_number>',
    methods=['GET'],
)
def get_pass(pass_type_identifier: str, serial_number: str):
    try:
        with managed_session() as session:
            wp = _resolve_pass(pass_type_identifier, serial_number, session)
            if not wp:
                return ('', 404)
            if not _check_apple_pass_auth(wp):
                return ('', 401)

            # ETag/If-Modified-Since negotiation
            if_modified = request.headers.get('If-Modified-Since')
            last_updated = wp.updated_at or wp.created_at or datetime.utcnow()
            if if_modified:
                try:
                    since = parsedate_to_datetime(if_modified)
                    # Apple sends UTC; our column is naive. Compare as naive UTC.
                    last_updated_aware = last_updated.replace(tzinfo=timezone.utc)
                    if last_updated_aware <= since:
                        return ('', 304)
                except (TypeError, ValueError):
                    pass  # malformed — fall through and return the pass

            try:
                pass_file = pass_service.generate_apple_pass(wp)
            except Exception as e:
                logger.error(f"PassKit get_pass: generation failed for {wp.id}: {e}")
                return ('', 500)

            response = make_response(pass_file.getvalue())
            response.headers['Content-Type'] = 'application/vnd.apple.pkpass'
            response.headers['Last-Modified'] = format_datetime(
                last_updated.replace(tzinfo=timezone.utc), usegmt=True
            )
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            return response
    except Exception as e:
        logger.error(f"PassKit get_pass error: {e}", exc_info=True)
        return ('', 500)


# ---------------------------------------------------------------------------
# 4. Unregister device
# DELETE /v1/devices/{deviceLibraryIdentifier}/registrations/{passTypeIdentifier}/{serialNumber}
# ---------------------------------------------------------------------------

@passkit_web_service_bp.route(
    '/v1/devices/<device_library_id>/registrations/<pass_type_identifier>/<serial_number>',
    methods=['DELETE'],
)
def unregister_device(device_library_id: str, pass_type_identifier: str, serial_number: str):
    try:
        with managed_session() as session:
            wp = _resolve_pass(pass_type_identifier, serial_number, session)
            if not wp:
                return ('', 404)
            if not _check_apple_pass_auth(wp):
                return ('', 401)

            existing = session.query(WalletPassDevice).filter_by(
                wallet_pass_id=wp.id,
                device_library_id=device_library_id,
            ).first()
            if existing:
                session.delete(existing)
                session.commit()
                logger.info(
                    f"PassKit unregister: pass={wp.serial_number[:8]}... "
                    f"device={device_library_id[:12]}..."
                )
            return ('', 200)
    except Exception as e:
        logger.error(f"PassKit unregister_device error: {e}", exc_info=True)
        return ('', 500)


# ---------------------------------------------------------------------------
# 5. Log endpoint
# POST /v1/log  Body: {"logs":["...","..."]}
# Apple Wallet posts errors here (e.g. signature failures, network issues).
# ---------------------------------------------------------------------------

@passkit_web_service_bp.route('/v1/log', methods=['POST'])
def receive_logs():
    try:
        data = request.get_json(silent=True) or {}
        for line in (data.get('logs') or []):
            logger.warning(f"[PassKit Wallet log] {line}")
        return ('', 200)
    except Exception:
        return ('', 200)  # never fail this endpoint
