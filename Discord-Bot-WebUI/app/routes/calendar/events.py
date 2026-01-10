# app/routes/calendar/events.py

"""
Calendar Events Routes

Provides unified event fetching for the calendar view.
Returns both matches and league events in FullCalendar-compatible format.
"""

import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g
from flask_login import login_required, current_user

from app.services.calendar import create_visibility_service
from app.dto.calendar_dto import match_to_fullcalendar, league_event_to_fullcalendar, ecs_fc_match_to_fullcalendar

logger = logging.getLogger(__name__)

events_bp = Blueprint('calendar_events', __name__)


@events_bp.route('/events', methods=['GET'])
@login_required
def get_events():
    """
    Get all visible calendar events for the current user.

    Query parameters:
    - start: ISO date string for start of range (optional)
    - end: ISO date string for end of range (optional)
    - include_matches: boolean to include matches (default: true)
    - include_league_events: boolean to include league events (default: true)

    Returns:
        JSON array of FullCalendar-compatible events
    """
    try:
        # Parse date range from query params
        start_str = request.args.get('start')
        end_str = request.args.get('end')
        include_matches = request.args.get('include_matches', 'true').lower() == 'true'
        include_league_events = request.args.get('include_league_events', 'true').lower() == 'true'

        start_date = None
        end_date = None

        if start_str:
            try:
                start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            except ValueError:
                start_date = datetime.strptime(start_str[:10], '%Y-%m-%d')

        if end_str:
            try:
                end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            except ValueError:
                end_date = datetime.strptime(end_str[:10], '%Y-%m-%d')

        # Get visibility service
        visibility_service = create_visibility_service(g.db_session)

        events = []

        # Get matches
        if include_matches:
            matches = visibility_service.get_visible_matches(
                current_user,
                start_date=start_date,
                end_date=end_date
            )

            # Determine if user can edit (admin only)
            can_edit = visibility_service.can_edit_events(current_user)

            for match in matches:
                fc_event = match_to_fullcalendar(match, editable=False)
                events.append(fc_event)

        # Get league events
        if include_league_events:
            league_events = visibility_service.get_visible_league_events(
                current_user,
                start_date=start_date,
                end_date=end_date
            )

            can_edit = visibility_service.can_edit_events(current_user)

            for league_event in league_events:
                fc_event = league_event_to_fullcalendar(league_event, editable=can_edit)
                events.append(fc_event)

        # Get ECS FC matches
        ecs_fc_matches = visibility_service.get_visible_ecs_fc_matches(
            current_user,
            start_date=start_date,
            end_date=end_date
        )

        user_team_ids = visibility_service.get_user_team_ids(current_user)
        for ecs_match in ecs_fc_matches:
            fc_event = ecs_fc_match_to_fullcalendar(ecs_match, user_team_ids=user_team_ids)
            events.append(fc_event)

        return jsonify(events)

    except Exception as e:
        logger.error(f"Error fetching calendar events: {e}", exc_info=True)
        return jsonify({'error': 'Failed to fetch events'}), 500


@events_bp.route('/events/permissions', methods=['GET'])
@login_required
def get_permissions():
    """
    Get the current user's calendar permissions.

    Returns:
        JSON object with permission flags
    """
    try:
        visibility_service = create_visibility_service(g.db_session)

        permissions = {
            'can_view_all_matches': visibility_service.can_view_all_matches(current_user),
            'can_edit_events': visibility_service.can_edit_events(current_user),
            'can_assign_refs': visibility_service.can_assign_refs(current_user),
            'is_admin': visibility_service.is_admin(current_user),
            'is_coach': visibility_service.is_coach(current_user),
            'is_referee': visibility_service.is_referee(current_user),
            'team_ids': visibility_service.get_user_team_ids(current_user),
        }

        return jsonify(permissions)

    except Exception as e:
        logger.error(f"Error fetching calendar permissions: {e}", exc_info=True)
        return jsonify({'error': 'Failed to fetch permissions'}), 500


@events_bp.route('/events/upcoming', methods=['GET'])
@login_required
def get_upcoming_events():
    """
    Get upcoming events for the next 30 days.

    Query parameters:
    - days: Number of days to look ahead (default: 30)
    - limit: Maximum number of events to return (default: 20)

    Returns:
        JSON array of upcoming events
    """
    try:
        days = int(request.args.get('days', 30))
        limit = int(request.args.get('limit', 20))

        # Clamp values
        days = min(max(days, 1), 365)
        limit = min(max(limit, 1), 100)

        start_date = datetime.utcnow()
        end_date = start_date + timedelta(days=days)

        visibility_service = create_visibility_service(g.db_session)

        # Get all visible events
        matches, league_events, ecs_fc_matches = visibility_service.get_all_visible_events(
            current_user,
            start_date=start_date,
            end_date=end_date
        )

        # Convert to FullCalendar format
        events = []
        for match in matches:
            events.append(match_to_fullcalendar(match, editable=False))
        for event in league_events:
            events.append(league_event_to_fullcalendar(event, editable=False))

        # Include ECS FC matches
        user_team_ids = visibility_service.get_user_team_ids(current_user)
        for ecs_match in ecs_fc_matches:
            events.append(ecs_fc_match_to_fullcalendar(ecs_match, user_team_ids=user_team_ids))

        # Sort by start date and limit
        events.sort(key=lambda x: x.get('start', ''))
        events = events[:limit]

        return jsonify(events)

    except Exception as e:
        logger.error(f"Error fetching upcoming events: {e}", exc_info=True)
        return jsonify({'error': 'Failed to fetch upcoming events'}), 500
