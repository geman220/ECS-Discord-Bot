# app/services/event_deduplication.py

"""
Event Deduplication Service

Provides idempotent event creation and deduplication logic for offline resilience.
Supports both MatchEvent (WebSocket/live reporting) and PlayerEvent (REST API) models.

Key features:
1. Exact duplicate detection via idempotency_key
2. Near-duplicate detection (same player + event_type + minute ±1)
3. Idempotent create operations that return existing events on duplicates
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple, Union
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.database.db_models import MatchEvent
from app.models.stats import PlayerEvent
from app.models import User

logger = logging.getLogger(__name__)

# Near-duplicate detection window in minutes (±3 handles clock drift between devices)
NEAR_DUPLICATE_MINUTE_WINDOW = 3


@dataclass
class DeduplicationResult:
    """Result of a deduplication check or idempotent create operation."""
    status: str  # 'created', 'duplicate', 'near_duplicate'
    event: Optional[Union[MatchEvent, PlayerEvent]] = None
    event_id: Optional[int] = None
    idempotency_key: Optional[str] = None
    near_duplicates: Optional[List[dict]] = None
    message: Optional[str] = None


def check_duplicate_match_event(
    session: Session,
    match_id: int,
    idempotency_key: str
) -> Optional[MatchEvent]:
    """
    Check if a MatchEvent with the given idempotency_key already exists.

    Args:
        session: Database session
        match_id: Match ID to check within
        idempotency_key: Client-generated unique key

    Returns:
        Existing MatchEvent if found, None otherwise
    """
    if not idempotency_key:
        return None

    return session.query(MatchEvent).filter_by(
        match_id=match_id,
        idempotency_key=idempotency_key
    ).first()


def check_duplicate_player_event(
    session: Session,
    match_id: int,
    idempotency_key: str
) -> Optional[PlayerEvent]:
    """
    Check if a PlayerEvent with the given idempotency_key already exists.

    Args:
        session: Database session
        match_id: Match ID to check within
        idempotency_key: Client-generated unique key

    Returns:
        Existing PlayerEvent if found, None otherwise
    """
    if not idempotency_key:
        return None

    return session.query(PlayerEvent).filter_by(
        match_id=match_id,
        idempotency_key=idempotency_key
    ).first()


def find_near_duplicate_match_events(
    session: Session,
    match_id: int,
    player_id: Optional[int],
    event_type: str,
    minute: Optional[int],
    exclude_idempotency_key: Optional[str] = None
) -> List[MatchEvent]:
    """
    Find near-duplicate MatchEvents (same player, event_type, minute ±NEAR_DUPLICATE_MINUTE_WINDOW).

    This helps detect potential duplicates when idempotency_key is not provided
    or when client clock skew might cause issues.

    Args:
        session: Database session
        match_id: Match ID to check within
        player_id: Player ID (can be None for team-level events)
        event_type: Type of event (GOAL, YELLOW_CARD, etc.)
        minute: Match minute (can be None)
        exclude_idempotency_key: Optionally exclude events with this key

    Returns:
        List of potentially duplicate MatchEvents
    """
    query = session.query(MatchEvent).filter(
        MatchEvent.match_id == match_id,
        MatchEvent.event_type == event_type
    )

    # Filter by player if provided
    if player_id is not None:
        query = query.filter(MatchEvent.player_id == player_id)

    # Filter by minute range (±NEAR_DUPLICATE_MINUTE_WINDOW) if provided
    if minute is not None:
        minute_conditions = [MatchEvent.minute == minute + offset
                           for offset in range(-NEAR_DUPLICATE_MINUTE_WINDOW, NEAR_DUPLICATE_MINUTE_WINDOW + 1)]
        query = query.filter(or_(*minute_conditions))

    # Exclude specific idempotency_key if provided
    if exclude_idempotency_key:
        query = query.filter(
            or_(
                MatchEvent.idempotency_key != exclude_idempotency_key,
                MatchEvent.idempotency_key.is_(None)
            )
        )

    return query.all()


def find_near_duplicate_player_events(
    session: Session,
    match_id: int,
    player_id: Optional[int],
    event_type: str,
    minute: Optional[str],
    exclude_idempotency_key: Optional[str] = None
) -> List[PlayerEvent]:
    """
    Find near-duplicate PlayerEvents (same player, event_type, minute ±NEAR_DUPLICATE_MINUTE_WINDOW).

    Args:
        session: Database session
        match_id: Match ID to check within
        player_id: Player ID (can be None for own goals)
        event_type: Type of event (goal, yellow_card, etc.)
        minute: Match minute as string (can be None)
        exclude_idempotency_key: Optionally exclude events with this key

    Returns:
        List of potentially duplicate PlayerEvents
    """
    from app.models.stats import PlayerEventType

    # Convert string event_type to enum if needed
    try:
        event_type_enum = PlayerEventType(event_type.lower())
    except (ValueError, AttributeError):
        # If it's already an enum or invalid, return empty list
        return []

    query = session.query(PlayerEvent).filter(
        PlayerEvent.match_id == match_id,
        PlayerEvent.event_type == event_type_enum
    )

    # Filter by player if provided
    if player_id is not None:
        query = query.filter(PlayerEvent.player_id == player_id)

    # Filter by minute range (±NEAR_DUPLICATE_MINUTE_WINDOW) if provided
    if minute is not None:
        try:
            minute_int = int(minute)
            minute_conditions = [PlayerEvent.minute == str(minute_int + offset)
                               for offset in range(-NEAR_DUPLICATE_MINUTE_WINDOW, NEAR_DUPLICATE_MINUTE_WINDOW + 1)]
            query = query.filter(or_(*minute_conditions))
        except (ValueError, TypeError):
            # If minute is not a valid integer, just match exact
            query = query.filter(PlayerEvent.minute == minute)

    # Exclude specific idempotency_key if provided
    if exclude_idempotency_key:
        query = query.filter(
            or_(
                PlayerEvent.idempotency_key != exclude_idempotency_key,
                PlayerEvent.idempotency_key.is_(None)
            )
        )

    return query.all()


def serialize_match_event(event: MatchEvent) -> dict:
    """
    Serialize a MatchEvent to a dictionary for API responses.

    Args:
        event: MatchEvent to serialize

    Returns:
        Dictionary representation
    """
    return {
        'id': event.id,
        'event_type': event.event_type,
        'team_id': event.team_id,
        'player_id': event.player_id,
        'minute': event.minute,
        'period': event.period,
        'timestamp': event.timestamp.isoformat() if event.timestamp else None,
        'reported_by': event.reported_by,
        'idempotency_key': event.idempotency_key,
        'client_timestamp': event.client_timestamp.isoformat() if event.client_timestamp else None,
        'sync_status': event.sync_status
    }


def serialize_match_event_with_reporter(session: Session, event: MatchEvent) -> dict:
    """
    Serialize a MatchEvent with reporter name included for iOS/watchOS compatibility.

    Args:
        session: Database session
        event: MatchEvent to serialize

    Returns:
        Dictionary representation with reported_by_name field
    """
    data = serialize_match_event(event)
    if event.reported_by:
        reporter = session.query(User).get(event.reported_by)
        data['reported_by_name'] = reporter.username if reporter else None
    else:
        data['reported_by_name'] = None
    return data


def get_reporter_name(session: Session, user_id: Optional[int]) -> Optional[str]:
    """
    Get the username for a given user ID.

    Args:
        session: Database session
        user_id: User ID to look up

    Returns:
        Username string or None if not found
    """
    if not user_id:
        return None
    reporter = session.query(User).get(user_id)
    return reporter.username if reporter else None


def create_match_event_idempotent(
    session: Session,
    match_id: int,
    event_data: dict,
    idempotency_key: Optional[str],
    client_timestamp: Optional[datetime],
    user_id: int,
    check_near_duplicates: bool = True
) -> DeduplicationResult:
    """
    Create a MatchEvent idempotently, checking for duplicates first.

    Args:
        session: Database session
        match_id: Match ID for the event
        event_data: Dictionary containing event_type, team_id, player_id, minute, period, additional_data
        idempotency_key: Client-generated unique key (optional but recommended)
        client_timestamp: When the event was created on the client
        user_id: ID of the user creating the event
        check_near_duplicates: Whether to check for near-duplicates

    Returns:
        DeduplicationResult with status and event info
    """
    # Check for exact duplicate by idempotency_key
    if idempotency_key:
        existing = check_duplicate_match_event(session, match_id, idempotency_key)
        if existing:
            logger.info(f"Duplicate event detected: idempotency_key={idempotency_key}")
            return DeduplicationResult(
                status='duplicate',
                event=existing,
                event_id=existing.id,
                idempotency_key=idempotency_key,
                message='Event already exists with this idempotency key'
            )

    # Check for near-duplicates
    if check_near_duplicates:
        near_dupes = find_near_duplicate_match_events(
            session=session,
            match_id=match_id,
            player_id=event_data.get('player_id'),
            event_type=event_data.get('event_type'),
            minute=event_data.get('minute'),
            exclude_idempotency_key=idempotency_key
        )

        if near_dupes:
            logger.info(f"Near-duplicate events found: {len(near_dupes)} matches")
            return DeduplicationResult(
                status='near_duplicate',
                idempotency_key=idempotency_key,
                near_duplicates=[serialize_match_event(e) for e in near_dupes],
                message='Similar events found - please confirm this is not a duplicate'
            )

    # Create new event
    event = MatchEvent(
        match_id=match_id,
        event_type=event_data.get('event_type'),
        team_id=event_data.get('team_id'),
        player_id=event_data.get('player_id'),
        minute=event_data.get('minute'),
        period=event_data.get('period'),
        timestamp=datetime.utcnow(),
        reported_by=user_id,
        additional_data=event_data.get('additional_data'),
        idempotency_key=idempotency_key,
        client_timestamp=client_timestamp,
        sync_status='synced'
    )

    session.add(event)
    session.flush()  # Get the ID without committing

    logger.info(f"Created new event: id={event.id}, idempotency_key={idempotency_key}")

    return DeduplicationResult(
        status='created',
        event=event,
        event_id=event.id,
        idempotency_key=idempotency_key,
        message='Event created successfully'
    )


def create_player_event_idempotent(
    session: Session,
    match_id: int,
    event_type: str,
    player_id: Optional[int],
    team_id: Optional[int],
    minute: Optional[str],
    idempotency_key: Optional[str],
    client_timestamp: Optional[datetime],
    check_near_duplicates: bool = True
) -> DeduplicationResult:
    """
    Create a PlayerEvent idempotently, checking for duplicates first.

    Args:
        session: Database session
        match_id: Match ID for the event
        event_type: Type of event (goal, assist, yellow_card, red_card, own_goal)
        player_id: Player ID (None for own goals)
        team_id: Team ID (used for own goals)
        minute: Match minute as string
        idempotency_key: Client-generated unique key (optional but recommended)
        client_timestamp: When the event was created on the client
        check_near_duplicates: Whether to check for near-duplicates

    Returns:
        DeduplicationResult with status and event info
    """
    from app.models.stats import PlayerEventType

    # Check for exact duplicate by idempotency_key
    if idempotency_key:
        existing = check_duplicate_player_event(session, match_id, idempotency_key)
        if existing:
            logger.info(f"Duplicate PlayerEvent detected: idempotency_key={idempotency_key}")
            return DeduplicationResult(
                status='duplicate',
                event=existing,
                event_id=existing.id,
                idempotency_key=idempotency_key,
                message='Event already exists with this idempotency key'
            )

    # Check for near-duplicates
    if check_near_duplicates:
        near_dupes = find_near_duplicate_player_events(
            session=session,
            match_id=match_id,
            player_id=player_id,
            event_type=event_type,
            minute=minute,
            exclude_idempotency_key=idempotency_key
        )

        if near_dupes:
            logger.info(f"Near-duplicate PlayerEvents found: {len(near_dupes)} matches")
            return DeduplicationResult(
                status='near_duplicate',
                idempotency_key=idempotency_key,
                near_duplicates=[e.to_dict() for e in near_dupes],
                message='Similar events found - please confirm this is not a duplicate'
            )

    # Create new event
    event = PlayerEvent(
        match_id=match_id,
        event_type=PlayerEventType(event_type.lower()),
        player_id=player_id,
        team_id=team_id,
        minute=minute,
        idempotency_key=idempotency_key,
        client_timestamp=client_timestamp
    )

    session.add(event)
    session.flush()  # Get the ID without committing

    logger.info(f"Created new PlayerEvent: id={event.id}, idempotency_key={idempotency_key}")

    return DeduplicationResult(
        status='created',
        event=event,
        event_id=event.id,
        idempotency_key=idempotency_key,
        message='Event created successfully'
    )


def parse_client_timestamp(timestamp_str: Optional[str]) -> Optional[datetime]:
    """
    Parse a client timestamp string into a datetime object.

    Supports ISO 8601 format and common variations.

    Args:
        timestamp_str: Timestamp string from client

    Returns:
        Parsed datetime or None if parsing fails
    """
    if not timestamp_str:
        return None

    try:
        # Try ISO 8601 format (most common from mobile clients)
        if 'T' in timestamp_str:
            # Handle timezone suffix
            if timestamp_str.endswith('Z'):
                timestamp_str = timestamp_str[:-1]
            # Remove microseconds if present for simpler parsing
            if '.' in timestamp_str:
                timestamp_str = timestamp_str.split('.')[0]
            return datetime.fromisoformat(timestamp_str)
        else:
            # Try basic datetime format
            return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse client timestamp '{timestamp_str}': {e}")
        return None
