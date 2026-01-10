# app/routes/calendar/league_events.py

"""
League Events Routes

Provides CRUD endpoints for league events (non-match calendar events).
Admin-only operations for creating, updating, and deleting events.
"""

import asyncio
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from flask_login import login_required, current_user

from app.decorators import role_required
from app.services.calendar import create_league_event_service, create_visibility_service
from app.services.discord_service import get_discord_service
from app.dto.calendar_dto import league_event_to_fullcalendar

logger = logging.getLogger(__name__)

league_events_bp = Blueprint('calendar_league_events', __name__)

# Admin roles that can manage league events
ADMIN_ROLES = ['Global Admin', 'Pub League Admin']


@league_events_bp.route('/league-events', methods=['GET'])
@login_required
def list_league_events():
    """
    List league events visible to the current user.

    Query parameters:
    - start: ISO date string for start of range (optional)
    - end: ISO date string for end of range (optional)
    - event_type: Filter by event type (optional)
    - include_inactive: Include soft-deleted events (admin only)

    Returns:
        JSON array of league events
    """
    try:
        start_str = request.args.get('start')
        end_str = request.args.get('end')
        event_type = request.args.get('event_type')
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'

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

        visibility_service = create_visibility_service(g.db_session)

        # Only admins can see inactive events
        if include_inactive and not visibility_service.is_admin(current_user):
            include_inactive = False

        league_event_service = create_league_event_service(g.db_session)

        result = league_event_service.list_events(
            start_date=start_date,
            end_date=end_date,
            event_type=event_type,
            include_inactive=include_inactive
        )

        if not result.success:
            return jsonify({'error': result.message}), 500

        # Filter by visibility
        visible_events = []
        can_edit = visibility_service.can_edit_events(current_user)

        for event in result.data:
            if visibility_service.can_view_league_event(current_user, event):
                visible_events.append(league_event_to_fullcalendar(event, editable=can_edit))

        return jsonify(visible_events)

    except Exception as e:
        logger.error(f"Error listing league events: {e}", exc_info=True)
        return jsonify({'error': 'Failed to list events'}), 500


@league_events_bp.route('/league-events/<int:event_id>', methods=['GET'])
@login_required
def get_league_event(event_id):
    """
    Get a single league event by ID.

    Returns:
        JSON object with event details
    """
    try:
        league_event_service = create_league_event_service(g.db_session)
        visibility_service = create_visibility_service(g.db_session)

        result = league_event_service.get_event(event_id)

        if not result.success:
            return jsonify({'error': result.message}), 404

        event = result.data

        # Check visibility
        if not visibility_service.can_view_league_event(current_user, event):
            return jsonify({'error': 'Event not found'}), 404

        can_edit = visibility_service.can_edit_events(current_user)
        return jsonify(league_event_to_fullcalendar(event, editable=can_edit))

    except Exception as e:
        logger.error(f"Error getting league event {event_id}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to get event'}), 500


@league_events_bp.route('/league-events', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def create_league_event():
    """
    Create a new league event.

    Request body (JSON):
    - title: Event title (required)
    - start_datetime: ISO datetime string (required)
    - end_datetime: ISO datetime string (optional)
    - description: Event description (optional)
    - event_type: Type of event (optional, default: 'other')
    - location: Event location (optional)
    - is_all_day: Boolean (optional, default: false)
    - season_id: Season ID (optional)
    - league_id: League ID (optional, null = all leagues)
    - notify_discord: Whether to announce in Discord (optional, default: false)

    Returns:
        JSON object with created event
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        # Parse required fields
        title = data.get('title')
        start_datetime_str = data.get('start_datetime') or data.get('start')

        if not title:
            return jsonify({'error': 'title is required'}), 400
        if not start_datetime_str:
            return jsonify({'error': 'start_datetime is required'}), 400

        # Parse datetimes
        try:
            start_datetime = datetime.fromisoformat(start_datetime_str.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'error': 'Invalid start_datetime format'}), 400

        end_datetime = None
        end_datetime_str = data.get('end_datetime') or data.get('end')
        if end_datetime_str:
            try:
                end_datetime = datetime.fromisoformat(end_datetime_str.replace('Z', '+00:00'))
            except ValueError:
                return jsonify({'error': 'Invalid end_datetime format'}), 400

        # Create the event
        league_event_service = create_league_event_service(g.db_session)

        result = league_event_service.create_event(
            title=title,
            start_datetime=start_datetime,
            created_by=current_user.id,
            description=data.get('description'),
            event_type=data.get('event_type', 'other'),
            location=data.get('location'),
            end_datetime=end_datetime,
            is_all_day=data.get('is_all_day', False),
            season_id=data.get('season_id'),
            league_id=data.get('league_id'),
            notify_discord=data.get('notify_discord', False)
        )

        if not result.success:
            return jsonify({'error': result.message}), 400

        event = result.data
        logger.info(f"Created league event {event.id}: {event.title}")

        # Post to Discord if requested
        discord_result = None
        if event.notify_discord:
            try:
                discord_service = get_discord_service()
                discord_result = asyncio.run(
                    discord_service.post_league_event_announcement(
                        event_id=event.id,
                        title=event.title,
                        start_datetime=event.start_datetime.isoformat(),
                        description=event.description,
                        event_type=event.event_type,
                        location=event.location,
                        end_datetime=event.end_datetime.isoformat() if event.end_datetime else None,
                        is_all_day=event.is_all_day
                    )
                )

                if discord_result:
                    # Store the Discord message ID and channel ID on the event
                    event.discord_message_id = str(discord_result.get('message_id'))
                    event.discord_channel_id = str(discord_result.get('channel_id'))
                    g.db_session.commit()
                    logger.info(f"Discord announcement posted for event {event.id}")
                else:
                    logger.warning(f"Failed to post Discord announcement for event {event.id}")

            except Exception as discord_error:
                logger.error(f"Error posting Discord announcement: {discord_error}")
                # Don't fail the request if Discord posting fails

        response_data = league_event_to_fullcalendar(event, editable=True)
        if discord_result:
            response_data['discord_posted'] = True
            response_data['discord_channel'] = discord_result.get('channel_name')

        return jsonify(response_data), 201

    except Exception as e:
        logger.error(f"Error creating league event: {e}", exc_info=True)
        return jsonify({'error': 'Failed to create event'}), 500


@league_events_bp.route('/league-events/<int:event_id>', methods=['PUT', 'PATCH'])
@login_required
@role_required(ADMIN_ROLES)
def update_league_event(event_id):
    """
    Update a league event.

    Request body (JSON): Same as create, all fields optional.

    Returns:
        JSON object with updated event
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        # Prepare updates
        updates = {}

        # Handle simple fields
        simple_fields = ['title', 'description', 'event_type', 'location',
                         'is_all_day', 'season_id', 'league_id', 'notify_discord', 'is_active']

        for field in simple_fields:
            if field in data:
                updates[field] = data[field]

        # Handle datetime fields
        start_datetime_str = data.get('start_datetime') or data.get('start')
        if start_datetime_str:
            try:
                updates['start_datetime'] = datetime.fromisoformat(
                    start_datetime_str.replace('Z', '+00:00')
                )
            except ValueError:
                return jsonify({'error': 'Invalid start_datetime format'}), 400

        end_datetime_str = data.get('end_datetime') or data.get('end')
        if end_datetime_str:
            try:
                updates['end_datetime'] = datetime.fromisoformat(
                    end_datetime_str.replace('Z', '+00:00')
                )
            except ValueError:
                return jsonify({'error': 'Invalid end_datetime format'}), 400
        elif 'end_datetime' in data and data['end_datetime'] is None:
            updates['end_datetime'] = None

        # Update the event
        league_event_service = create_league_event_service(g.db_session)

        result = league_event_service.update_event(event_id, **updates)

        if not result.success:
            status = 404 if result.error_code == 'EVENT_NOT_FOUND' else 400
            return jsonify({'error': result.message}), status

        event = result.data
        logger.info(f"Updated league event {event.id}: {event.title}")

        # Update Discord message if one exists
        if event.discord_message_id and event.discord_channel_id:
            try:
                discord_service = get_discord_service()
                asyncio.run(
                    discord_service.update_league_event_announcement(
                        event_id=event.id,
                        message_id=int(event.discord_message_id),
                        channel_id=int(event.discord_channel_id),
                        title=event.title,
                        start_datetime=event.start_datetime.isoformat(),
                        description=event.description,
                        event_type=event.event_type,
                        location=event.location,
                        end_datetime=event.end_datetime.isoformat() if event.end_datetime else None,
                        is_all_day=event.is_all_day
                    )
                )
                logger.info(f"Updated Discord announcement for event {event.id}")
            except Exception as discord_error:
                logger.error(f"Error updating Discord announcement: {discord_error}")

        return jsonify(league_event_to_fullcalendar(event, editable=True))

    except Exception as e:
        logger.error(f"Error updating league event {event_id}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to update event'}), 500


@league_events_bp.route('/league-events/<int:event_id>', methods=['DELETE'])
@login_required
@role_required(ADMIN_ROLES)
def delete_league_event(event_id):
    """
    Delete a league event (soft delete by default).

    Query parameters:
    - hard_delete: If 'true', permanently delete the event

    Returns:
        JSON success message
    """
    try:
        hard_delete = request.args.get('hard_delete', 'false').lower() == 'true'

        league_event_service = create_league_event_service(g.db_session)

        # Get the event first to check for Discord message
        event_result = league_event_service.get_event(event_id)
        discord_message_id = None
        discord_channel_id = None

        if event_result.success:
            event = event_result.data
            discord_message_id = event.discord_message_id
            discord_channel_id = event.discord_channel_id

        result = league_event_service.delete_event(event_id, soft_delete=not hard_delete)

        if not result.success:
            status = 404 if result.error_code == 'EVENT_NOT_FOUND' else 400
            return jsonify({'error': result.message}), status

        logger.info(f"Deleted league event {event_id}")

        # Delete Discord message if one exists
        if discord_message_id and discord_channel_id:
            try:
                discord_service = get_discord_service()
                asyncio.run(
                    discord_service.delete_league_event_announcement(
                        message_id=int(discord_message_id),
                        channel_id=int(discord_channel_id)
                    )
                )
                logger.info(f"Deleted Discord announcement for event {event_id}")
            except Exception as discord_error:
                logger.error(f"Error deleting Discord announcement: {discord_error}")

        return jsonify({'message': 'Event deleted successfully'})

    except Exception as e:
        logger.error(f"Error deleting league event {event_id}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to delete event'}), 500


@league_events_bp.route('/league-events/types', methods=['GET'])
@login_required
def get_event_types():
    """
    Get available event types.

    Returns:
        JSON array of event type options
    """
    event_types = [
        {'id': 1, 'value': 'party', 'label': 'Party/Social', 'color': '#9c27b0', 'icon': 'celebration'},
        {'id': 2, 'value': 'tournament', 'label': 'Tournament', 'color': '#ffc107', 'icon': 'trophy'},
        {'id': 3, 'value': 'meeting', 'label': 'Meeting', 'color': '#2196f3', 'icon': 'groups'},
        {'id': 4, 'value': 'plop', 'label': 'PLOP', 'color': '#4caf50', 'icon': 'sports'},
        {'id': 5, 'value': 'fundraiser', 'label': 'Fundraiser', 'color': '#ff5722', 'icon': 'volunteer_activism'},
        {'id': 6, 'value': 'social', 'label': 'Social Event', 'color': '#e91e63', 'icon': 'heart'},
        {'id': 7, 'value': 'other', 'label': 'Other', 'color': '#607d8b', 'icon': 'calendar'},
    ]
    return jsonify(event_types)
