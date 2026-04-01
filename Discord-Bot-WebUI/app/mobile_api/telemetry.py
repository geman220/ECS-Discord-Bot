# app/mobile_api/telemetry.py

"""
Mobile API Telemetry Endpoints

Receives usage telemetry from the Flutter app:
- Session start/end events
- Screen view tracking
- Feature usage events
"""

import logging
from datetime import datetime

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models.mobile_telemetry import MobileSession, MobileScreenView, MobileFeatureUsage

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/telemetry/session', methods=['POST'])
@jwt_required()
def telemetry_session():
    """Report a session start or end event.

    POST body:
    {
        "session_id": "uuid-string",
        "event": "start" | "end",
        "platform": "ios" | "android",
        "app_version": "2.1.0",
        "started_at": "2026-03-31T10:00:00Z",      (for start)
        "ended_at": "2026-03-31T10:15:00Z",         (for end)
        "duration_seconds": 900,                      (for end)
        "screens_viewed": 12                          (for end)
    }
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        session_id = data.get('session_id')
        event = data.get('event')

        if not session_id or event not in ('start', 'end'):
            return jsonify({'error': 'session_id and event (start/end) are required'}), 400

        with managed_session() as db_session:
            if event == 'start':
                existing = db_session.query(MobileSession).filter_by(session_id=session_id).first()
                if existing:
                    return jsonify({'status': 'already_exists'}), 200

                session = MobileSession(
                    user_id=int(user_id) if user_id else None,
                    session_id=session_id,
                    platform=data.get('platform'),
                    app_version=data.get('app_version'),
                    started_at=_parse_dt(data.get('started_at')) or datetime.utcnow(),
                )
                db_session.add(session)
                db_session.flush()
                return jsonify({'status': 'session_started', 'session_id': session_id}), 201

            else:  # end
                session = db_session.query(MobileSession).filter_by(session_id=session_id).first()
                if not session:
                    # Create a retroactive session record
                    session = MobileSession(
                        user_id=int(user_id) if user_id else None,
                        session_id=session_id,
                        platform=data.get('platform'),
                        app_version=data.get('app_version'),
                        started_at=_parse_dt(data.get('started_at')) or datetime.utcnow(),
                    )
                    db_session.add(session)

                session.ended_at = _parse_dt(data.get('ended_at')) or datetime.utcnow()
                session.duration_seconds = data.get('duration_seconds')
                session.screens_viewed = data.get('screens_viewed', 0)
                db_session.flush()
                return jsonify({'status': 'session_ended', 'session_id': session_id}), 200

    except Exception as e:
        logger.error(f"Telemetry session error: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@mobile_api_v2.route('/telemetry/screens', methods=['POST'])
@jwt_required()
def telemetry_screens():
    """Report batch screen view events.

    POST body:
    {
        "session_id": "uuid-string",
        "screens": [
            {
                "screen_name": "HomeScreen",
                "entered_at": "2026-03-31T10:00:00Z",
                "exited_at": "2026-03-31T10:02:30Z",
                "duration_seconds": 150
            }
        ]
    }
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        session_id = data.get('session_id')
        screens = data.get('screens', [])

        if not session_id:
            return jsonify({'error': 'session_id is required'}), 400

        if not screens or not isinstance(screens, list):
            return jsonify({'error': 'screens array is required'}), 400

        received = 0
        with managed_session() as db_session:
            for screen in screens[:100]:  # Max 100 per batch
                screen_name = screen.get('screen_name')
                if not screen_name:
                    continue

                view = MobileScreenView(
                    session_id=session_id,
                    user_id=int(user_id) if user_id else None,
                    screen_name=screen_name,
                    entered_at=_parse_dt(screen.get('entered_at')) or datetime.utcnow(),
                    exited_at=_parse_dt(screen.get('exited_at')),
                    duration_seconds=screen.get('duration_seconds'),
                )
                db_session.add(view)
                received += 1
            db_session.flush()

        return jsonify({'status': 'ok', 'screens_received': received}), 201

    except Exception as e:
        logger.error(f"Telemetry screens error: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@mobile_api_v2.route('/telemetry/feature-usage', methods=['POST'])
@jwt_required()
def telemetry_feature_usage():
    """Report batch feature usage events.

    POST body:
    {
        "events": [
            {
                "feature_name": "push_notifications",
                "used_at": "2026-03-31T10:05:00Z",
                "platform": "ios",
                "app_version": "2.1.0"
            }
        ]
    }
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        events = data.get('events', [])
        if not events or not isinstance(events, list):
            return jsonify({'error': 'events array is required'}), 400

        received = 0
        with managed_session() as db_session:
            for event in events[:100]:  # Max 100 per batch
                feature_name = event.get('feature_name')
                if not feature_name:
                    continue

                usage = MobileFeatureUsage(
                    user_id=int(user_id) if user_id else None,
                    feature_name=feature_name,
                    platform=event.get('platform'),
                    app_version=event.get('app_version'),
                    used_at=_parse_dt(event.get('used_at')) or datetime.utcnow(),
                )
                db_session.add(usage)
                received += 1
            db_session.flush()

        return jsonify({'status': 'ok', 'events_received': received}), 201

    except Exception as e:
        logger.error(f"Telemetry feature usage error: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


def _parse_dt(value):
    """Parse an ISO datetime string, returning None on failure."""
    if not value:
        return None
    try:
        if value.endswith('Z'):
            value = value[:-1] + '+00:00'
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None
