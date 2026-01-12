# app/routes/calendar/league_events.py

"""
League Events Routes

Provides CRUD endpoints for league events (non-match calendar events).
Admin-only operations for creating, updating, and deleting events.
"""

import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, request, jsonify, g
from flask_login import login_required, current_user

# Pacific timezone for Discord announcements
PACIFIC_TZ = ZoneInfo('America/Los_Angeles')

from app.decorators import role_required
from app.services.calendar import create_league_event_service, create_visibility_service
from app.services.discord_service import get_discord_service
from app.dto.calendar_dto import league_event_to_fullcalendar
from app.utils.schedule_image_generator import generate_schedule_image

logger = logging.getLogger(__name__)

league_events_bp = Blueprint('calendar_league_events', __name__)

# Admin roles that can manage league events
ADMIN_ROLES = ['Global Admin', 'Pub League Admin']


def format_datetime_for_discord(dt: datetime) -> str:
    """
    Format a datetime for Discord announcements with Pacific timezone.

    The Discord bot expects timezone-aware ISO format datetimes.
    If the datetime is naive (no timezone), we assume it's already in Pacific time.
    """
    if dt is None:
        return None

    # If naive datetime, assume it's Pacific time and add the timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PACIFIC_TZ)

    return dt.isoformat()


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
                        start_datetime=format_datetime_for_discord(event.start_datetime),
                        description=event.description,
                        event_type=event.event_type,
                        location=event.location,
                        end_datetime=format_datetime_for_discord(event.end_datetime),
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
                        start_datetime=format_datetime_for_discord(event.start_datetime),
                        description=event.description,
                        event_type=event.event_type,
                        location=event.location,
                        end_datetime=format_datetime_for_discord(event.end_datetime),
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


def parse_time_string(time_str: str) -> tuple:
    """
    Parse a time string in various formats.

    Supports: "9:30", "09:30", "9:30 AM", "9:30am", "17:30", etc.

    Returns:
        Tuple of (hour, minute) in 24-hour format
    """
    if not time_str:
        return (0, 0)

    time_str = time_str.strip().upper()

    # Check for AM/PM
    is_pm = 'PM' in time_str
    is_am = 'AM' in time_str

    # Remove AM/PM
    time_str = time_str.replace('AM', '').replace('PM', '').strip()

    # Parse the time
    if ':' in time_str:
        parts = time_str.split(':')
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    else:
        hour = int(time_str)
        minute = 0

    # Convert to 24-hour if needed
    if is_pm and hour < 12:
        hour += 12
    elif is_am and hour == 12:
        hour = 0

    return (hour, minute)


def parse_date_string(date_str: str, default_year: int = None) -> datetime:
    """
    Parse a date string in various formats.

    Supports: "1/4", "01/04", "1/4/2026", "2026-01-04", "Jan 4", etc.

    Returns:
        datetime object
    """
    if not date_str:
        return None

    if default_year is None:
        default_year = datetime.now().year

    date_str = date_str.strip()

    # Try ISO format first (2026-01-04)
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        pass

    # Try M/D/YYYY
    try:
        return datetime.strptime(date_str, '%m/%d/%Y')
    except ValueError:
        pass

    # Try M/D (add default year)
    try:
        dt = datetime.strptime(date_str, '%m/%d')
        return dt.replace(year=default_year)
    except ValueError:
        pass

    # Try Mon D format (Jan 4)
    try:
        dt = datetime.strptime(date_str, '%b %d')
        return dt.replace(year=default_year)
    except ValueError:
        pass

    raise ValueError(f"Could not parse date: {date_str}")


@league_events_bp.route('/league-events/import', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def import_league_events():
    """
    Import league events from a CSV file.

    Expected CSV columns (flexible - uses header names):
    - date: Event date (M/D, M/D/YYYY, or YYYY-MM-DD)
    - title: Event title (optional, uses event_type if not provided)
    - event_type: Type of event (plop, party, meeting, etc.)
    - start_time: Start time (9:30, 9:30 AM, etc.)
    - end_time: End time (optional)
    - location: Event location (optional)
    - description: Event description (optional)

    Query parameters:
    - year: Default year for dates without year (default: current year)
    - notify_discord: Whether to announce events in Discord (default: false)
    - discord_mode: How to announce to Discord when notify_discord=true:
        - 'individual': Post separate embed for each event (spammy for many events)
        - 'summary': Post a single summary embed listing all events (recommended for bulk)
    - preview: If true, only validate and preview without creating (default: false)

    Returns:
        JSON with import results
    """
    try:
        # Check for file upload
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No file selected'}), 400

        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'File must be a CSV'}), 400

        # Get parameters
        default_year = int(request.form.get('year', datetime.now().year))
        notify_discord = request.form.get('notify_discord', 'false').lower() == 'true'
        discord_mode = request.form.get('discord_mode', 'summary').lower()  # 'summary' or 'individual'
        preview_only = request.form.get('preview', 'false').lower() == 'true'
        default_event_type = request.form.get('event_type', 'other').lower()
        default_title = request.form.get('title', '')

        # Read and parse CSV
        content = file.read().decode('utf-8-sig')  # Handle BOM
        reader = csv.DictReader(io.StringIO(content))

        # Normalize header names
        if reader.fieldnames:
            # Map common variations to standard names
            header_map = {
                'date': ['date', 'event_date', 'day'],
                'title': ['title', 'name', 'event_name', 'event'],
                'event_type': ['event_type', 'type', 'category'],
                'start_time': ['start_time', 'start', 'time', 'begins'],
                'end_time': ['end_time', 'end', 'until', 'ends'],
                'location': ['location', 'venue', 'place', 'where'],
                'description': ['description', 'desc', 'details', 'notes']
            }

            # Create reverse mapping
            field_map = {}
            for standard, variations in header_map.items():
                for var in variations:
                    for field in reader.fieldnames:
                        if field.lower().strip() == var:
                            field_map[field] = standard
                            break

        # Process rows
        events_to_create = []
        errors = []
        row_num = 1

        for row in reader:
            row_num += 1

            try:
                # Normalize row keys
                normalized_row = {}
                for key, value in row.items():
                    standard_key = field_map.get(key, key.lower().strip())
                    normalized_row[standard_key] = value.strip() if value else ''

                # Parse date
                date_str = normalized_row.get('date', '')
                if not date_str:
                    errors.append(f"Row {row_num}: Missing date")
                    continue

                try:
                    event_date = parse_date_string(date_str, default_year)
                except ValueError as e:
                    errors.append(f"Row {row_num}: {str(e)}")
                    continue

                # Parse times
                start_time_str = normalized_row.get('start_time', '')
                if start_time_str:
                    start_hour, start_minute = parse_time_string(start_time_str)
                else:
                    start_hour, start_minute = (9, 0)  # Default to 9 AM

                end_time_str = normalized_row.get('end_time', '')
                end_datetime = None
                if end_time_str:
                    end_hour, end_minute = parse_time_string(end_time_str)
                    end_datetime = event_date.replace(hour=end_hour, minute=end_minute)

                start_datetime = event_date.replace(hour=start_hour, minute=start_minute)

                # Get other fields
                event_type = normalized_row.get('event_type', default_event_type).lower()
                if event_type not in create_league_event_service(g.db_session).VALID_EVENT_TYPES:
                    event_type = default_event_type

                title = normalized_row.get('title', '') or default_title or event_type.upper()
                location = normalized_row.get('location', '')
                description = normalized_row.get('description', '')

                events_to_create.append({
                    'title': title,
                    'start_datetime': start_datetime,
                    'end_datetime': end_datetime,
                    'event_type': event_type,
                    'location': location,
                    'description': description,
                    'notify_discord': notify_discord,
                    'row_num': row_num
                })

            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")

        # If preview only, return what would be created
        if preview_only:
            return jsonify({
                'preview': True,
                'events_count': len(events_to_create),
                'events': [
                    {
                        'row': e['row_num'],
                        'title': e['title'],
                        'date': e['start_datetime'].strftime('%Y-%m-%d'),
                        'start_time': e['start_datetime'].strftime('%H:%M'),
                        'end_time': e['end_datetime'].strftime('%H:%M') if e['end_datetime'] else None,
                        'location': e['location'],
                        'event_type': e['event_type']
                    }
                    for e in events_to_create
                ],
                'errors': errors
            })

        # Create events
        league_event_service = create_league_event_service(g.db_session)
        created_events = []

        # Create a single event loop for all Discord announcements
        # Using asyncio.run() multiple times in a loop causes "Event loop is closed" errors
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            for event_data in events_to_create:
                row_num = event_data.pop('row_num')

                result = league_event_service.create_event(
                    title=event_data['title'],
                    start_datetime=event_data['start_datetime'],
                    created_by=current_user.id,
                    end_datetime=event_data['end_datetime'],
                    event_type=event_data['event_type'],
                    location=event_data['location'],
                    description=event_data['description'],
                    notify_discord=event_data['notify_discord']
                )

                if result.success:
                    event = result.data
                    created_events.append({
                        'id': event.id,
                        'title': event.title,
                        'date': event.start_datetime.strftime('%Y-%m-%d'),
                        'time': event.start_datetime.strftime('%I:%M %p'),
                        'location': event.location,
                        'event_type': event.event_type,
                        'event_obj': event  # Keep reference for summary post
                    })

                    # Post to Discord if requested (individual mode only)
                    if event.notify_discord and discord_mode == 'individual':
                        try:
                            discord_service = get_discord_service()
                            discord_result = loop.run_until_complete(
                                discord_service.post_league_event_announcement(
                                    event_id=event.id,
                                    title=event.title,
                                    start_datetime=format_datetime_for_discord(event.start_datetime),
                                    description=event.description,
                                    event_type=event.event_type,
                                    location=event.location,
                                    end_datetime=format_datetime_for_discord(event.end_datetime),
                                    is_all_day=False
                                )
                            )
                            if discord_result:
                                event.discord_message_id = str(discord_result.get('message_id'))
                                event.discord_channel_id = str(discord_result.get('channel_id'))
                                g.db_session.commit()
                        except Exception as discord_error:
                            logger.error(f"Error posting Discord announcement: {discord_error}")
                else:
                    errors.append(f"Row {row_num}: {result.message}")

            # Post summary to Discord if in summary mode
            if notify_discord and discord_mode == 'summary' and created_events:
                try:
                    discord_service = get_discord_service()

                    # Prepare events for image generator
                    image_events = []
                    for evt in created_events:
                        event_obj = evt.get('event_obj')
                        if event_obj:
                            image_events.append({
                                'title': evt['title'],
                                'date': event_obj.start_datetime,
                                'time': evt['time'],
                                'location': evt['location'] or '',
                                'event_type': evt['event_type'],
                            })

                    # Generate the schedule image
                    logger.info(f"Generating schedule image for {len(image_events)} events")
                    image_bytes = generate_schedule_image(
                        events=image_events,
                        title="Event Schedule",
                        footer_url="portal.ecsfc.com/calendar"
                    )

                    # Post schedule image announcement
                    discord_result = loop.run_until_complete(
                        discord_service.post_schedule_image_announcement(
                            image_bytes=image_bytes,
                            title=f"📋 {len(created_events)} New Events Added",
                            description="Check out the upcoming schedule!",
                            footer_text="Pub League Events • View full calendar at portal.ecsfc.com/calendar"
                        )
                    )
                    if discord_result:
                        logger.info(f"Posted schedule image announcement for {len(created_events)} events")
                except Exception as discord_error:
                    logger.error(f"Error posting Discord schedule image: {discord_error}", exc_info=True)

        finally:
            loop.close()

        # Clean up event_obj before returning JSON
        for evt in created_events:
            evt.pop('event_obj', None)

        logger.info(f"Imported {len(created_events)} league events via CSV")

        return jsonify({
            'success': True,
            'created_count': len(created_events),
            'created_events': created_events,
            'errors': errors,
            'discord_mode': discord_mode if notify_discord else 'none'
        })

    except Exception as e:
        logger.error(f"Error importing league events from CSV: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@league_events_bp.route('/league-events/import/template', methods=['GET'])
@login_required
def get_import_template():
    """
    Get a CSV template for importing league events.

    Returns:
        CSV file download
    """
    from flask import Response

    # Create template CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow(['date', 'title', 'event_type', 'start_time', 'end_time', 'location', 'description'])

    # Example rows
    writer.writerow(['1/4', 'PLOP', 'plop', '9:30', '11:30', 'Eckstein Middle School', ''])
    writer.writerow(['1/11', 'PLOP', 'plop', '9:30', '11:30', 'Eckstein Middle School', ''])
    writer.writerow(['1/24', 'Preregistration Party', 'party', '5:00 PM', '8:00 PM', 'Nun Chuck Brewing', 'For returning players'])
    writer.writerow(['2/11', 'Drunken Draft Team Reveals', 'party', '7:00 PM', '', 'Flatstick Pub Pioneer Square', ''])

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=league_events_template.csv'}
    )
