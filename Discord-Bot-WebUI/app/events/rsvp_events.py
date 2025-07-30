# app/events/rsvp_events.py

"""
RSVP Domain Events

Defines the event structure for RSVP changes with full traceability
and idempotency support for distributed systems.
"""

import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class RSVPEventType(Enum):
    """RSVP event types for different lifecycle stages."""
    RSVP_CREATED = "rsvp.created"
    RSVP_UPDATED = "rsvp.updated" 
    RSVP_DELETED = "rsvp.deleted"
    RSVP_SYNC_REQUESTED = "rsvp.sync_requested"  # For manual sync triggers


class RSVPSource(Enum):
    """Source systems that can trigger RSVP changes."""
    MOBILE = "mobile"
    WEB = "web" 
    DISCORD = "discord"
    ADMIN = "admin"
    SYSTEM = "system"  # Automated processes
    MIGRATION = "migration"  # Data migrations


@dataclass
class RSVPEvent:
    """
    Domain event for RSVP changes with full observability.
    
    This event structure supports:
    - Idempotent processing via operation_id
    - Distributed tracing via trace_id
    - Event replay via event_id
    - Conflict resolution via version/timestamp
    """
    
    # Event metadata
    event_id: str
    event_type: RSVPEventType
    occurred_at: datetime
    
    # RSVP data
    match_id: int
    player_id: int
    old_response: Optional[str]  # Previous RSVP state
    new_response: str  # New RSVP state ('yes', 'no', 'maybe', 'no_response')
    
    # Player context
    discord_id: Optional[str]
    player_name: Optional[str]
    team_id: Optional[int]
    
    # System context
    source: RSVPSource
    trace_id: str  # For distributed tracing
    operation_id: str  # For idempotency
    
    # Versioning for conflict resolution
    version: int = 1
    
    # Optional metadata
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    session_id: Optional[str] = None
    
    @classmethod
    def create_rsvp_updated(
        cls,
        match_id: int,
        player_id: int,
        old_response: Optional[str],
        new_response: str,
        discord_id: Optional[str] = None,
        player_name: Optional[str] = None,
        team_id: Optional[int] = None,
        source: RSVPSource = RSVPSource.SYSTEM,
        trace_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        **metadata
    ) -> 'RSVPEvent':
        """Factory method for RSVP update events."""
        
        # Determine event type based on state change
        if old_response is None and new_response != 'no_response':
            event_type = RSVPEventType.RSVP_CREATED
        elif new_response == 'no_response':
            event_type = RSVPEventType.RSVP_DELETED
        else:
            event_type = RSVPEventType.RSVP_UPDATED
            
        return cls(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            occurred_at=datetime.utcnow(),
            match_id=match_id,
            player_id=player_id,
            old_response=old_response,
            new_response=new_response,
            discord_id=discord_id,
            player_name=player_name,
            team_id=team_id,
            source=source,
            trace_id=trace_id or str(uuid.uuid4()),
            operation_id=operation_id or str(uuid.uuid4()),
            **metadata
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        data = asdict(self)
        
        # Convert enums to strings
        data['event_type'] = self.event_type.value
        data['source'] = self.source.value
        
        # Convert datetime to ISO string
        data['occurred_at'] = self.occurred_at.isoformat()
        
        # Remove None values to reduce payload size
        return {k: v for k, v in data.items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RSVPEvent':
        """Create event from dictionary (for deserialization)."""
        # Convert strings back to enums
        data['event_type'] = RSVPEventType(data['event_type'])
        data['source'] = RSVPSource(data['source'])
        
        # Convert ISO string back to datetime
        data['occurred_at'] = datetime.fromisoformat(data['occurred_at'])
        
        return cls(**data)
    
    def get_routing_key(self) -> str:
        """Get routing key for event distribution."""
        return f"rsvp.{self.event_type.value}.match.{self.match_id}"
    
    def is_no_op(self) -> bool:
        """Check if this event represents a no-operation (no actual change)."""
        return self.old_response == self.new_response
    
    def affects_discord(self) -> bool:
        """Check if this event should trigger Discord updates."""
        # Skip Discord updates for Discord-sourced events to prevent loops
        if self.source == RSVPSource.DISCORD:
            return False
            
        # Only update Discord for actual state changes
        return not self.is_no_op()
    
    def affects_websocket(self) -> bool:
        """Check if this event should trigger WebSocket broadcasts."""
        # All real changes should be broadcast for real-time UI updates
        return not self.is_no_op()
    
    def __str__(self) -> str:
        """Human-readable event description."""
        return (f"RSVPEvent({self.event_type.value}, "
                f"match={self.match_id}, player={self.player_id}, "
                f"{self.old_response}->{self.new_response}, "
                f"source={self.source.value})")


@dataclass 
class RSVPSyncEvent:
    """
    Event for requesting full RSVP synchronization.
    
    Used when systems need to resync after failures or inconsistencies.
    """
    event_id: str
    match_id: int
    requested_by: str  # User/system requesting sync
    sync_targets: list  # ['discord', 'websocket', 'analytics']
    force_update: bool = False  # Force update even if no changes
    trace_id: str = None
    occurred_at: datetime = None
    
    def __post_init__(self):
        if self.occurred_at is None:
            self.occurred_at = datetime.utcnow()
        if self.trace_id is None:
            self.trace_id = str(uuid.uuid4())