# app/mobile_api/calendar_subscription.py

"""
Mobile Calendar Subscription API Endpoints

JWT-authenticated wrappers around SubscriptionService for mobile clients.
The public iCal feed itself is served by app/routes/calendar/subscriptions.py
at GET /api/calendar/feed/<token>.ics; these endpoints hand the mobile client
the subscribe URLs and let it manage preferences.
"""

import logging

from flask import jsonify, request, url_for
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import User
from app.services.calendar import (
    create_subscription_service,
    create_visibility_service,
)

logger = logging.getLogger(__name__)


def _build_subscription_response(subscription, user, session_db, message=None):
    """Build the {subscription, feed_url, webcal_url, google_calendar_url, is_referee} payload."""
    feed_url = url_for(
        'calendar_api.calendar_subscriptions.serve_ical_feed',
        token=subscription.token,
        _external=True,
    )

    if not feed_url.startswith('https://') and 'localhost' not in feed_url:
        feed_url = feed_url.replace('http://', 'https://')

    webcal_url = feed_url.replace('https://', 'webcal://').replace('http://', 'webcal://')
    google_url = f'https://calendar.google.com/calendar/r?cid={feed_url}'

    visibility = create_visibility_service(session_db)
    is_referee = visibility.is_referee(user) if user else False

    payload = {
        'subscription': subscription.to_dict(),
        'feed_url': feed_url,
        'webcal_url': webcal_url,
        'google_calendar_url': google_url,
        'is_referee': is_referee,
    }
    if message:
        payload['message'] = message
    return payload


@mobile_api_v2.route('/calendar/subscription', methods=['GET'])
@jwt_required()
def get_calendar_subscription():
    """
    Get (or create) the current user's calendar subscription.

    Idempotent — returns the same token across calls until it is rotated or
    the subscription is deactivated.
    """
    current_user_id = int(get_jwt_identity())

    try:
        with managed_session() as session_db:
            subscription_service = create_subscription_service(session_db)
            result = subscription_service.get_or_create_subscription(current_user_id)

            if not result.success:
                return jsonify({'error': result.message}), 500

            user = session_db.query(User).get(current_user_id)
            payload = _build_subscription_response(result.data, user, session_db)
            return jsonify(payload), 200

    except Exception as e:
        logger.error(
            f"Error getting calendar subscription for user {current_user_id}: {e}",
            exc_info=True,
        )
        return jsonify({'error': 'Failed to get subscription'}), 500


@mobile_api_v2.route('/calendar/subscription', methods=['DELETE'])
@jwt_required()
def regenerate_calendar_subscription():
    """
    Rotate the calendar subscription token.

    Invalidates the old feed URL and issues a new one. The mobile client should
    re-subscribe by opening the new webcal:// URL.
    """
    current_user_id = int(get_jwt_identity())

    try:
        with managed_session() as session_db:
            subscription_service = create_subscription_service(session_db)
            regen_result = subscription_service.regenerate_token(current_user_id)

            if not regen_result.success:
                status = 404 if regen_result.error_code == 'NOT_FOUND' else 500
                return jsonify({'error': regen_result.message}), status

            sub_result = subscription_service.get_subscription(current_user_id)
            if not sub_result.success:
                return jsonify({'error': 'Failed to get updated subscription'}), 500

            user = session_db.query(User).get(current_user_id)
            payload = _build_subscription_response(
                sub_result.data,
                user,
                session_db,
                message='Token regenerated. Re-subscribe with the new URL.',
            )
            logger.info(f"Regenerated calendar subscription for user {current_user_id}")
            return jsonify(payload), 200

    except Exception as e:
        logger.error(
            f"Error regenerating calendar subscription for user {current_user_id}: {e}",
            exc_info=True,
        )
        return jsonify({'error': 'Failed to regenerate token'}), 500


@mobile_api_v2.route('/calendar/subscription/preferences', methods=['PATCH'])
@jwt_required()
def update_calendar_subscription_preferences():
    """
    Update calendar subscription preferences.

    Request body (JSON, all optional booleans):
        include_team_matches, include_league_events,
        include_ref_assignments, include_ecs_fc_matches
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    try:
        with managed_session() as session_db:
            subscription_service = create_subscription_service(session_db)
            result = subscription_service.update_preferences(
                user_id=current_user_id,
                include_team_matches=data.get('include_team_matches'),
                include_league_events=data.get('include_league_events'),
                include_ref_assignments=data.get('include_ref_assignments'),
                include_ecs_fc_matches=data.get('include_ecs_fc_matches'),
            )

            if not result.success:
                status = 404 if result.error_code == 'NOT_FOUND' else 500
                return jsonify({'error': result.message}), status

            logger.info(f"Updated calendar preferences for user {current_user_id}")
            return jsonify({
                'message': 'Preferences updated',
                'subscription': result.data.to_dict(),
            }), 200

    except Exception as e:
        logger.error(
            f"Error updating calendar preferences for user {current_user_id}: {e}",
            exc_info=True,
        )
        return jsonify({'error': 'Failed to update preferences'}), 500
