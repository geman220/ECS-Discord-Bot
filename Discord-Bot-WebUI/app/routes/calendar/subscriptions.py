# app/routes/calendar/subscriptions.py

"""
Calendar Subscription Routes

Provides endpoints for iCal subscription management and feed generation.
"""

import logging
from flask import Blueprint, request, jsonify, g, url_for, Response, make_response
from flask_login import login_required, current_user

from app.services.calendar import (
    create_subscription_service,
    create_ical_generator,
    create_visibility_service
)

logger = logging.getLogger(__name__)

subscriptions_bp = Blueprint('calendar_subscriptions', __name__)


@subscriptions_bp.route('/subscription', methods=['GET'])
@login_required
def get_subscription():
    """
    Get the current user's calendar subscription.
    Creates one if it doesn't exist.

    Returns:
        JSON object with subscription details and URLs
    """
    try:
        subscription_service = create_subscription_service(g.db_session)

        result = subscription_service.get_or_create_subscription(current_user.id)

        if not result.success:
            return jsonify({'error': result.message}), 500

        subscription = result.data

        # Build URLs
        feed_url = url_for(
            'calendar_api.calendar_subscriptions.serve_ical_feed',
            token=subscription.token,
            _external=True
        )

        # Ensure HTTPS for production
        if not feed_url.startswith('https://') and 'localhost' not in feed_url:
            feed_url = feed_url.replace('http://', 'https://')

        # webcal:// URL for one-click subscribe on iOS/macOS
        webcal_url = feed_url.replace('https://', 'webcal://').replace('http://', 'webcal://')

        # Google Calendar URL
        google_url = f'https://calendar.google.com/calendar/r?cid={feed_url}'

        # Check if user is a referee (for showing ref assignments toggle)
        visibility_service = create_visibility_service(g.db_session)
        is_referee = visibility_service.is_referee(current_user)

        return jsonify({
            'subscription': subscription.to_dict(),
            'feed_url': feed_url,
            'webcal_url': webcal_url,
            'google_calendar_url': google_url,
            'is_referee': is_referee,
            'instructions': {
                'ios': 'Tap the webcal:// link or go to Settings > Calendar > Accounts > Add Account > Other > Add Subscribed Calendar',
                'macos': 'Click the webcal:// link or use Calendar app > File > New Calendar Subscription',
                'google': 'Open Google Calendar > Settings (gear icon) > Add calendar > From URL > Paste the feed URL',
                'outlook': 'Open Outlook Calendar > Add calendar > Subscribe from web > Paste the feed URL'
            }
        })

    except Exception as e:
        logger.error(f"Error getting subscription: {e}", exc_info=True)
        return jsonify({'error': 'Failed to get subscription'}), 500


@subscriptions_bp.route('/subscription/regenerate', methods=['POST'])
@login_required
def regenerate_subscription():
    """
    Regenerate the subscription token.
    This invalidates the old URL - users must update their calendar subscriptions.

    Returns:
        JSON object with new subscription details
    """
    try:
        subscription_service = create_subscription_service(g.db_session)

        result = subscription_service.regenerate_token(current_user.id)

        if not result.success:
            status = 404 if result.error_code == 'NOT_FOUND' else 500
            return jsonify({'error': result.message}), status

        # Get the updated subscription
        sub_result = subscription_service.get_subscription(current_user.id)
        if not sub_result.success:
            return jsonify({'error': 'Failed to get updated subscription'}), 500

        subscription = sub_result.data

        # Build new URLs
        feed_url = url_for(
            'calendar_api.calendar_subscriptions.serve_ical_feed',
            token=subscription.token,
            _external=True
        )

        if not feed_url.startswith('https://') and 'localhost' not in feed_url:
            feed_url = feed_url.replace('http://', 'https://')

        webcal_url = feed_url.replace('https://', 'webcal://').replace('http://', 'webcal://')

        logger.info(f"Regenerated calendar subscription for user {current_user.id}")

        return jsonify({
            'message': 'Token regenerated successfully. Please update your calendar subscriptions with the new URL.',
            'subscription': subscription.to_dict(),
            'feed_url': feed_url,
            'webcal_url': webcal_url
        })

    except Exception as e:
        logger.error(f"Error regenerating subscription: {e}", exc_info=True)
        return jsonify({'error': 'Failed to regenerate token'}), 500


@subscriptions_bp.route('/subscription/preferences', methods=['PUT', 'PATCH'])
@login_required
def update_preferences():
    """
    Update calendar subscription preferences.

    Request body (JSON):
    - include_team_matches: boolean
    - include_league_events: boolean
    - include_ref_assignments: boolean

    Returns:
        JSON object with updated subscription
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        subscription_service = create_subscription_service(g.db_session)

        result = subscription_service.update_preferences(
            user_id=current_user.id,
            include_team_matches=data.get('include_team_matches'),
            include_league_events=data.get('include_league_events'),
            include_ref_assignments=data.get('include_ref_assignments')
        )

        if not result.success:
            status = 404 if result.error_code == 'NOT_FOUND' else 500
            return jsonify({'error': result.message}), status

        logger.info(f"Updated calendar preferences for user {current_user.id}")

        return jsonify({
            'message': 'Preferences updated',
            'subscription': result.data.to_dict()
        })

    except Exception as e:
        logger.error(f"Error updating preferences: {e}", exc_info=True)
        return jsonify({'error': 'Failed to update preferences'}), 500


@subscriptions_bp.route('/feed/<token>.ics', methods=['GET'])
def serve_ical_feed(token):
    """
    Serve the iCal feed for a subscription token.

    This endpoint is PUBLIC (no authentication required) because:
    - iCal clients don't support HTTP authentication
    - The token itself provides authentication
    - Tokens are cryptographically secure (64 chars, URL-safe)

    Returns:
        iCalendar formatted calendar file
    """
    try:
        # Validate token and get subscription
        subscription_service = create_subscription_service(g.db_session)
        result = subscription_service.get_subscription_by_token(token)

        if not result.success:
            logger.warning(f"Invalid calendar feed token: {token[:8]}...")
            return Response(
                'Calendar not found',
                status=404,
                mimetype='text/plain'
            )

        subscription = result.data

        # Record the access
        subscription_service.record_feed_access(subscription)

        # Generate the iCal feed
        ical_generator = create_ical_generator(g.db_session)
        ical_content = ical_generator.generate_feed(subscription)

        # Create response with proper headers
        response = make_response(ical_content)
        response.headers['Content-Type'] = 'text/calendar; charset=utf-8'
        response.headers['Content-Disposition'] = 'attachment; filename="ecs-fc-calendar.ics"'

        # Allow caching for 5 minutes to reduce server load
        # But not too long so updates are still timely
        response.headers['Cache-Control'] = 'private, max-age=300'

        # Security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'

        return response

    except Exception as e:
        logger.error(f"Error serving iCal feed: {e}", exc_info=True)
        return Response(
            'Error generating calendar',
            status=500,
            mimetype='text/plain'
        )


@subscriptions_bp.route('/subscription/deactivate', methods=['POST'])
@login_required
def deactivate_subscription():
    """
    Deactivate the calendar subscription.
    The feed URL will stop working until reactivated.

    Returns:
        JSON success message
    """
    try:
        subscription_service = create_subscription_service(g.db_session)

        result = subscription_service.deactivate_subscription(current_user.id)

        if not result.success:
            status = 404 if result.error_code == 'NOT_FOUND' else 500
            return jsonify({'error': result.message}), status

        logger.info(f"Deactivated calendar subscription for user {current_user.id}")

        return jsonify({'message': 'Subscription deactivated'})

    except Exception as e:
        logger.error(f"Error deactivating subscription: {e}", exc_info=True)
        return jsonify({'error': 'Failed to deactivate subscription'}), 500


@subscriptions_bp.route('/subscription/activate', methods=['POST'])
@login_required
def activate_subscription():
    """
    Reactivate a deactivated calendar subscription.

    Returns:
        JSON object with subscription details
    """
    try:
        subscription_service = create_subscription_service(g.db_session)

        result = subscription_service.activate_subscription(current_user.id)

        if not result.success:
            status = 404 if result.error_code == 'NOT_FOUND' else 500
            return jsonify({'error': result.message}), status

        subscription = result.data

        feed_url = url_for(
            'calendar_api.calendar_subscriptions.serve_ical_feed',
            token=subscription.token,
            _external=True
        )

        logger.info(f"Activated calendar subscription for user {current_user.id}")

        return jsonify({
            'message': 'Subscription activated',
            'subscription': subscription.to_dict(),
            'feed_url': feed_url
        })

    except Exception as e:
        logger.error(f"Error activating subscription: {e}", exc_info=True)
        return jsonify({'error': 'Failed to activate subscription'}), 500
