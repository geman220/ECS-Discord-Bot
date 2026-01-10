# app/mobile_api/calendar.py

"""
Mobile Calendar API Endpoints

Provides calendar-related endpoints for mobile clients including:
- Unified calendar events (matches + league events)
- League events listing
- Calendar event details
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload
from sqlalchemy import or_

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import Match, Player, Season
from app.models.calendar import LeagueEvent
from app.models_ecs import EcsFcMatch

logger = logging.getLogger(__name__)


# Event type definitions for mobile UI
# Each type has: id, value, label, color, icon
EVENT_TYPES = {
    'party': {'id': 1, 'value': 'party', 'label': 'Party/Social', 'color': '#9c27b0', 'icon': 'celebration'},
    'tournament': {'id': 2, 'value': 'tournament', 'label': 'Tournament', 'color': '#ffc107', 'icon': 'trophy'},
    'meeting': {'id': 3, 'value': 'meeting', 'label': 'Meeting', 'color': '#2196f3', 'icon': 'groups'},
    'plop': {'id': 4, 'value': 'plop', 'label': 'PLOP', 'color': '#4caf50', 'icon': 'sports'},
    'fundraiser': {'id': 5, 'value': 'fundraiser', 'label': 'Fundraiser', 'color': '#ff5722', 'icon': 'volunteer_activism'},
    'social': {'id': 6, 'value': 'social', 'label': 'Social Event', 'color': '#e91e63', 'icon': 'heart'},
    'other': {'id': 7, 'value': 'other', 'label': 'Other', 'color': '#607d8b', 'icon': 'calendar'},
}

# Legacy mappings for backward compatibility
EVENT_TYPE_COLORS = {k: v['color'] for k, v in EVENT_TYPES.items()}
EVENT_TYPE_ICONS = {k: v['icon'] for k, v in EVENT_TYPES.items()}


def _match_to_calendar_event(match, user_team_ids: list = None) -> dict:
    """Convert a Match object to a calendar event dict for mobile."""
    # Determine if this is a user's team match
    is_my_team = False
    if user_team_ids:
        is_my_team = match.home_team_id in user_team_ids or match.away_team_id in user_team_ids

    # Determine division color
    division = 'Premier' if getattr(match.home_team, 'league_id', None) == 10 else 'Classic'
    color = '#1976d2' if division == 'Premier' else '#4caf50'

    return {
        'id': f'match-{match.id}',
        'type': 'match',
        'title': f"{match.home_team.name if match.home_team else 'TBD'} vs {match.away_team.name if match.away_team else 'TBD'}",
        'start': datetime.combine(match.date, match.time).isoformat() if match.time else match.date.isoformat(),
        'end': None,
        'all_day': False,
        'location': getattr(match, 'location', None),
        'color': color,
        'division': division,
        'is_my_team': is_my_team,
        'match_id': match.id,
        'home_team': {
            'id': match.home_team_id,
            'name': match.home_team.name if match.home_team else None
        },
        'away_team': {
            'id': match.away_team_id,
            'name': match.away_team.name if match.away_team else None
        },
        'referee': match.ref.name if match.ref else None
    }


def _league_event_to_calendar_event(event: LeagueEvent, include_league_name: bool = True) -> dict:
    """
    Convert a LeagueEvent object to a calendar event dict for mobile.

    Returns format matching app expectations:
    - id: integer (not prefixed string)
    - event_type_key: the event type value
    - event_type_details: full type info with id, value, label, color, icon
    - is_all_day: boolean (not all_day)
    - league_name: included when available
    """
    from flask import request

    # Get event type details (default to 'other' if not found)
    event_type_key = event.event_type or 'other'
    event_type_details = EVENT_TYPES.get(event_type_key, EVENT_TYPES['other'])

    # Build base URL for any URLs
    base_url = request.host_url.rstrip('/') if request else ''

    result = {
        'id': event.id,  # Integer, not prefixed string
        'type': 'league_event',
        'title': event.title,
        'description': event.description,
        'start': event.start_datetime.isoformat() if event.start_datetime else None,
        'end': event.end_datetime.isoformat() if event.end_datetime else None,
        'location': event.location,
        'event_type_key': event_type_key,
        'event_type_details': event_type_details,
        'league_id': event.league_id,
        'is_all_day': event.is_all_day,
        'url': f"{base_url}/calendar?event={event.id}" if base_url else None,
        'metadata': {
            'notify_discord': event.notify_discord,
            'season_id': event.season_id,
            'created_at': event.created_at.isoformat() if event.created_at else None,
        },
        # Legacy fields for backward compatibility
        'event_type': event_type_key,
        'color': event_type_details['color'],
        'icon': event_type_details['icon'],
        'event_id': event.id,
        'all_day': event.is_all_day,
    }

    # Include league name if available and requested
    if include_league_name and event.league:
        result['league_name'] = event.league.name
    else:
        result['league_name'] = None

    return result


def _ecs_fc_match_to_calendar_event(match: EcsFcMatch, user_team_ids: list = None) -> dict:
    """Convert an EcsFcMatch object to a calendar event dict for mobile."""
    # Determine if this is a user's team match
    is_my_team = match.team_id in user_team_ids if user_team_ids else False

    return {
        'id': f'ecs-fc-match-{match.id}',
        'type': 'ecs_fc_match',
        'title': f"{match.team.name if match.team else 'Unknown'} vs {match.opponent_name}",
        'start': datetime.combine(match.match_date, match.match_time).isoformat() if match.match_time else match.match_date.isoformat(),
        'end': None,
        'all_day': False,
        'location': match.location,
        'field_name': match.field_name,
        'color': '#ff6b35',  # Orange for ECS FC matches
        'division': 'ECS FC',
        'is_my_team': is_my_team,
        'is_home_match': match.is_home_match,
        'match_id': match.id,
        'team': {
            'id': match.team_id,
            'name': match.team.name if match.team else None
        },
        'opponent_name': match.opponent_name,
        'status': match.status,
        'notes': match.notes,
        'rsvp_deadline': match.rsvp_deadline.isoformat() if match.rsvp_deadline else None,
        'home_shirt_color': getattr(match, 'home_shirt_color', None),
        'away_shirt_color': getattr(match, 'away_shirt_color', None)
    }


@mobile_api_v2.route('/calendar/events', methods=['GET'])
@jwt_required()
def get_calendar_events():
    """
    Get all calendar events (matches + league events) for the user.

    Query parameters:
        start: ISO date string for range start (default: today)
        end: ISO date string for range end (default: 30 days from start)
        include_matches: Include matches (default: true)
        include_league_events: Include league events (default: true)
        my_team_only: Only show user's team matches (default: false)

    Returns:
        JSON with calendar events
    """
    current_user_id = int(get_jwt_identity())

    # Parse query parameters
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    include_matches = request.args.get('include_matches', 'true').lower() == 'true'
    include_league_events = request.args.get('include_league_events', 'true').lower() == 'true'
    my_team_only = request.args.get('my_team_only', 'false').lower() == 'true'

    # Default date range
    if start_str:
        try:
            start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00')).date()
        except ValueError:
            start_date = datetime.strptime(start_str[:10], '%Y-%m-%d').date()
    else:
        start_date = datetime.now().date()

    if end_str:
        try:
            end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00')).date()
        except ValueError:
            end_date = datetime.strptime(end_str[:10], '%Y-%m-%d').date()
    else:
        end_date = start_date + timedelta(days=30)

    events = []

    with managed_session() as session_db:
        # Get user's player profile and team IDs
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()
        user_team_ids = [t.id for t in player.teams] if player and player.teams else []

        # Get matches
        if include_matches:
            match_query = session_db.query(Match).options(
                joinedload(Match.home_team),
                joinedload(Match.away_team),
                joinedload(Match.ref)
            ).filter(
                Match.date >= start_date,
                Match.date <= end_date
            )

            # Filter to user's teams if requested
            if my_team_only and user_team_ids:
                match_query = match_query.filter(
                    or_(
                        Match.home_team_id.in_(user_team_ids),
                        Match.away_team_id.in_(user_team_ids)
                    )
                )

            matches = match_query.order_by(Match.date, Match.time).all()

            for match in matches:
                events.append(_match_to_calendar_event(match, user_team_ids))

        # Get league events
        if include_league_events:
            event_query = session_db.query(LeagueEvent).filter(
                LeagueEvent.start_datetime >= datetime.combine(start_date, datetime.min.time()),
                LeagueEvent.start_datetime <= datetime.combine(end_date, datetime.max.time()),
                LeagueEvent.is_active == True
            )

            league_events = event_query.order_by(LeagueEvent.start_datetime).all()

            for event in league_events:
                events.append(_league_event_to_calendar_event(event))

        # Get ECS FC matches (always include if user has team membership)
        ecs_fc_query = session_db.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team)
        ).filter(
            EcsFcMatch.match_date >= start_date,
            EcsFcMatch.match_date <= end_date,
            EcsFcMatch.status != 'CANCELLED'
        )

        # Filter to user's teams if my_team_only
        if my_team_only and user_team_ids:
            ecs_fc_query = ecs_fc_query.filter(EcsFcMatch.team_id.in_(user_team_ids))
        elif user_team_ids:
            # Show all ECS FC matches for user's teams
            ecs_fc_query = ecs_fc_query.filter(EcsFcMatch.team_id.in_(user_team_ids))

        ecs_fc_matches = ecs_fc_query.order_by(EcsFcMatch.match_date, EcsFcMatch.match_time).all()

        for ecs_match in ecs_fc_matches:
            events.append(_ecs_fc_match_to_calendar_event(ecs_match, user_team_ids))

        # Sort all events by start datetime
        events.sort(key=lambda x: x['start'])

    return jsonify({
        'events': events,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'total_count': len(events),
        'match_count': sum(1 for e in events if e['type'] == 'match'),
        'event_count': sum(1 for e in events if e['type'] == 'league_event'),
        'ecs_fc_match_count': sum(1 for e in events if e['type'] == 'ecs_fc_match')
    }), 200


@mobile_api_v2.route('/calendar/league-events', methods=['GET'])
@jwt_required()
def get_league_events():
    """
    Get league events only (no matches).

    Query parameters:
        date_from: ISO date string for range start (alias: start)
        date_to: ISO date string for range end (alias: end)
        league_id: Filter by league ID (optional)
        event_type: Filter by event type (party, meeting, social, plop, tournament, fundraiser, other)
        limit: Maximum events to return (default: 50)

    Returns:
        JSON with league events matching app expected format
    """
    # Parse query parameters (support both naming conventions)
    start_str = request.args.get('date_from') or request.args.get('start')
    end_str = request.args.get('date_to') or request.args.get('end')
    event_type = request.args.get('event_type')
    league_id = request.args.get('league_id', type=int)
    limit = request.args.get('limit', 50, type=int)
    limit = min(limit, 100)  # Cap at 100

    with managed_session() as session_db:
        # Eagerly load league for league_name
        query = session_db.query(LeagueEvent).options(
            joinedload(LeagueEvent.league)
        ).filter(
            LeagueEvent.is_active == True
        )

        # Apply date filters
        if start_str:
            try:
                start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            except ValueError:
                start_date = datetime.strptime(start_str[:10], '%Y-%m-%d')
            query = query.filter(LeagueEvent.start_datetime >= start_date)

        if end_str:
            try:
                end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            except ValueError:
                end_date = datetime.strptime(end_str[:10], '%Y-%m-%d')
            query = query.filter(LeagueEvent.start_datetime <= end_date)

        # Filter by event type
        if event_type:
            query = query.filter(LeagueEvent.event_type == event_type)

        # Filter by league
        if league_id:
            query = query.filter(LeagueEvent.league_id == league_id)

        events = query.order_by(LeagueEvent.start_datetime).limit(limit).all()

        events_data = [_league_event_to_calendar_event(event) for event in events]

    return jsonify({
        'events': events_data,
        'total_count': len(events_data)
    }), 200


@mobile_api_v2.route('/calendar/league-events/<int:event_id>', methods=['GET'])
@jwt_required()
def get_league_event_detail(event_id: int):
    """
    Get details for a specific league event.

    Returns:
        JSON with event details
    """
    with managed_session() as session_db:
        event = session_db.query(LeagueEvent).filter_by(
            id=event_id,
            is_active=True
        ).first()

        if not event:
            return jsonify({'error': 'Event not found'}), 404

        return jsonify(_league_event_to_calendar_event(event)), 200


@mobile_api_v2.route('/calendar/upcoming', methods=['GET'])
@jwt_required()
def get_upcoming_calendar():
    """
    Get upcoming calendar events (matches + league events) for quick preview.

    Query parameters:
        days: Number of days to look ahead (default: 14)
        limit: Maximum events to return (default: 10)

    Returns:
        JSON with upcoming events
    """
    current_user_id = int(get_jwt_identity())

    days = request.args.get('days', 14, type=int)
    days = min(max(days, 1), 90)  # Between 1 and 90 days

    limit = request.args.get('limit', 10, type=int)
    limit = min(limit, 50)  # Cap at 50

    start_date = datetime.now().date()
    end_date = start_date + timedelta(days=days)

    events = []

    with managed_session() as session_db:
        # Get user's team IDs
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()
        user_team_ids = [t.id for t in player.teams] if player and player.teams else []

        # Get matches (user's teams only for upcoming view)
        match_query = session_db.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.ref)
        ).filter(
            Match.date >= start_date,
            Match.date <= end_date
        )

        if user_team_ids:
            match_query = match_query.filter(
                or_(
                    Match.home_team_id.in_(user_team_ids),
                    Match.away_team_id.in_(user_team_ids)
                )
            )

        matches = match_query.order_by(Match.date, Match.time).all()

        for match in matches:
            events.append(_match_to_calendar_event(match, user_team_ids))

        # Get league events
        league_events = session_db.query(LeagueEvent).filter(
            LeagueEvent.start_datetime >= datetime.combine(start_date, datetime.min.time()),
            LeagueEvent.start_datetime <= datetime.combine(end_date, datetime.max.time()),
            LeagueEvent.is_active == True
        ).order_by(LeagueEvent.start_datetime).all()

        for event in league_events:
            events.append(_league_event_to_calendar_event(event))

        # Get ECS FC matches for user's teams
        if user_team_ids:
            ecs_fc_matches = session_db.query(EcsFcMatch).options(
                joinedload(EcsFcMatch.team)
            ).filter(
                EcsFcMatch.match_date >= start_date,
                EcsFcMatch.match_date <= end_date,
                EcsFcMatch.team_id.in_(user_team_ids),
                EcsFcMatch.status != 'CANCELLED'
            ).order_by(EcsFcMatch.match_date, EcsFcMatch.match_time).all()

            for ecs_match in ecs_fc_matches:
                events.append(_ecs_fc_match_to_calendar_event(ecs_match, user_team_ids))

    # Sort and limit
    events.sort(key=lambda x: x['start'])
    events = events[:limit]

    return jsonify({
        'events': events,
        'total_count': len(events)
    }), 200


@mobile_api_v2.route('/calendar/event-types', methods=['GET'])
@jwt_required()
def get_event_types():
    """
    Get available league event types with colors and icons.

    Returns:
        JSON array of event type definitions with id, value, label, color, icon
    """
    # Return as list sorted by id
    event_types = sorted(EVENT_TYPES.values(), key=lambda x: x['id'])
    return jsonify(event_types), 200
