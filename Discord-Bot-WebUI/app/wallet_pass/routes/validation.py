# app/wallet_pass/routes/validation.py

"""
Wallet Pass Validation API

Provides endpoints for validating wallet passes via QR/barcode scanning.
Used by staff at events to verify membership status.
"""

import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

from app.models.wallet import WalletPass, WalletPassCheckin, CheckInType
from app.wallet_pass.services.pass_service import pass_service
from app.core import db

logger = logging.getLogger(__name__)

validation_bp = Blueprint('wallet_validation', __name__, url_prefix='/api/v1/wallet')


@validation_bp.route('/validate', methods=['POST'])
def validate_pass():
    """
    Validate a wallet pass by barcode data.

    This endpoint is called when scanning a pass QR code at events.

    Expected payload:
    {
        "barcode": "ECS-2025-ABC123",
        "event_name": "Match vs Seattle" (optional),
        "location": "Memorial Stadium" (optional),
        "check_in": true (optional - record check-in if valid)
    }

    Returns:
    {
        "valid": true,
        "pass": {
            "member_name": "John Doe",
            "pass_type": "ECS Membership",
            "validity": "2025",
            "status": "active"
        },
        "check_in_recorded": true (if check_in was requested)
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        barcode = data.get('barcode')
        if not barcode:
            return jsonify({'error': 'Missing barcode'}), 400

        # Find and validate the pass
        wallet_pass = pass_service.validate_barcode(barcode)

        if not wallet_pass:
            logger.warning(f"Invalid barcode scanned: {barcode[:20]}...")
            return jsonify({
                'valid': False,
                'error': 'Pass not found or invalid barcode'
            }), 404

        # Check pass validity
        is_valid = wallet_pass.is_valid

        response = {
            'valid': is_valid,
            'pass': {
                'id': wallet_pass.id,
                'member_name': wallet_pass.member_name,
                'member_email': wallet_pass.member_email,
                'pass_type': wallet_pass.pass_type.name if wallet_pass.pass_type else None,
                'pass_type_code': wallet_pass.pass_type.code if wallet_pass.pass_type else None,
                'validity': wallet_pass.display_validity,
                'status': wallet_pass.status,
                'is_expired': wallet_pass.is_expired,
                'team_name': wallet_pass.team_name,
                'valid_from': wallet_pass.valid_from.isoformat() if wallet_pass.valid_from else None,
                'valid_until': wallet_pass.valid_until.isoformat() if wallet_pass.valid_until else None
            }
        }

        if not is_valid:
            if wallet_pass.status == 'voided':
                response['reason'] = 'Pass has been voided'
            elif wallet_pass.is_expired:
                response['reason'] = 'Pass has expired'
            else:
                response['reason'] = 'Pass is not active'

        # Record check-in if requested and pass is valid
        if data.get('check_in') and is_valid:
            event_name = data.get('event_name')
            location = data.get('location')

            checkin = WalletPassCheckin(
                pass_id=wallet_pass.id,
                check_in_type=CheckInType.QR_SCAN,
                event_name=event_name,
                location=location
            )
            db.session.add(checkin)
            db.session.commit()

            response['check_in_recorded'] = True
            response['check_in_id'] = checkin.id
            logger.info(
                f"Check-in recorded for {wallet_pass.member_name} "
                f"at {event_name or 'unknown event'}"
            )
        else:
            response['check_in_recorded'] = False

        return jsonify(response)

    except Exception as e:
        logger.error(f"Error validating pass: {e}", exc_info=True)
        return jsonify({'error': 'Validation failed', 'details': str(e)}), 500


@validation_bp.route('/validate/<barcode>', methods=['GET'])
def quick_validate(barcode: str):
    """
    Quick validation endpoint for simple barcode lookups.

    GET /api/v1/wallet/validate/ECS-2025-ABC123

    Returns basic validity info without recording check-in.
    """
    try:
        wallet_pass = pass_service.validate_barcode(barcode)

        if not wallet_pass:
            return jsonify({
                'valid': False,
                'error': 'Pass not found'
            }), 404

        return jsonify({
            'valid': wallet_pass.is_valid,
            'member_name': wallet_pass.member_name,
            'pass_type': wallet_pass.pass_type.name if wallet_pass.pass_type else None,
            'validity': wallet_pass.display_validity,
            'status': wallet_pass.status
        })

    except Exception as e:
        logger.error(f"Error in quick validation: {e}")
        return jsonify({'error': 'Validation failed'}), 500


@validation_bp.route('/checkins', methods=['GET'])
def list_checkins():
    """
    List recent check-ins for reporting.

    Query params:
        pass_id: Filter by specific pass
        event_name: Filter by event
        date: Filter by date (YYYY-MM-DD)
        limit: Max results (default 50)
    """
    try:
        pass_id = request.args.get('pass_id', type=int)
        event_name = request.args.get('event_name')
        date_str = request.args.get('date')
        limit = request.args.get('limit', 50, type=int)

        query = WalletPassCheckin.query

        if pass_id:
            query = query.filter_by(pass_id=pass_id)

        if event_name:
            query = query.filter(
                WalletPassCheckin.event_name.ilike(f'%{event_name}%')
            )

        if date_str:
            try:
                date = datetime.strptime(date_str, '%Y-%m-%d').date()
                query = query.filter(
                    db.func.date(WalletPassCheckin.checked_in_at) == date
                )
            except ValueError:
                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

        checkins = query.order_by(
            WalletPassCheckin.checked_in_at.desc()
        ).limit(limit).all()

        return jsonify({
            'checkins': [
                {
                    'id': c.id,
                    'pass_id': c.pass_id,
                    'member_name': c.wallet_pass.member_name if c.wallet_pass else None,
                    'pass_type': c.wallet_pass.pass_type.name if c.wallet_pass and c.wallet_pass.pass_type else None,
                    'check_in_type': c.check_in_type.value,
                    'event_name': c.event_name,
                    'location': c.location,
                    'checked_in_at': c.checked_in_at.isoformat()
                }
                for c in checkins
            ],
            'count': len(checkins)
        })

    except Exception as e:
        logger.error(f"Error listing check-ins: {e}", exc_info=True)
        return jsonify({'error': 'Failed to retrieve check-ins'}), 500


@validation_bp.route('/checkins/stats', methods=['GET'])
def checkin_stats():
    """
    Get check-in statistics.

    Query params:
        event_name: Filter by event
        date: Filter by date (YYYY-MM-DD)
    """
    try:
        event_name = request.args.get('event_name')
        date_str = request.args.get('date')

        query = db.session.query(WalletPassCheckin)

        if event_name:
            query = query.filter(
                WalletPassCheckin.event_name.ilike(f'%{event_name}%')
            )

        if date_str:
            try:
                date = datetime.strptime(date_str, '%Y-%m-%d').date()
                query = query.filter(
                    db.func.date(WalletPassCheckin.checked_in_at) == date
                )
            except ValueError:
                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

        total_checkins = query.count()

        # Get unique members checked in
        unique_members = query.with_entities(
            WalletPassCheckin.pass_id
        ).distinct().count()

        # Get by pass type
        by_type = db.session.query(
            WalletPass.pass_type_id,
            db.func.count(WalletPassCheckin.id).label('count')
        ).join(
            WalletPassCheckin, WalletPass.id == WalletPassCheckin.pass_id
        )

        if event_name:
            by_type = by_type.filter(
                WalletPassCheckin.event_name.ilike(f'%{event_name}%')
            )

        if date_str:
            by_type = by_type.filter(
                db.func.date(WalletPassCheckin.checked_in_at) == date
            )

        by_type = by_type.group_by(WalletPass.pass_type_id).all()

        return jsonify({
            'total_checkins': total_checkins,
            'unique_members': unique_members,
            'by_pass_type': {
                str(t[0]): t[1] for t in by_type
            },
            'filters': {
                'event_name': event_name,
                'date': date_str
            }
        })

    except Exception as e:
        logger.error(f"Error getting check-in stats: {e}", exc_info=True)
        return jsonify({'error': 'Failed to retrieve statistics'}), 500
