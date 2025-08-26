# app/services/live_reporting/models.py

"""
V2 Live Reporting Models

Data models for the V2 live reporting system following enterprise patterns.
These models represent match events and related data structures used throughout
the V2 architecture.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime


@dataclass
class MatchEvent:
    """
    Represents a match event in the V2 live reporting system.
    
    This is a lightweight data class used to structure match events
    before they are processed and stored in the database.
    """
    event_id: str
    event_type: str
    description: str
    clock: str
    team_id: str
    athlete_id: str
    athlete_name: str
    raw_data: Dict[str, Any]
    timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_key(self) -> str:
        """Generate unique key for event deduplication."""
        return f"{self.clock}-{self.event_type}-{self.athlete_name or 'unknown'}-{self.event_id}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type,
            'description': self.description,
            'clock': self.clock,
            'team_id': self.team_id,
            'athlete_id': self.athlete_id,
            'athlete_name': self.athlete_name,
            'raw_data': self.raw_data,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }


@dataclass
class MatchData:
    """
    Represents match data structure for V2 system.
    
    This model contains the core match information used throughout
    the V2 live reporting pipeline.
    """
    match_id: str
    home_team: Dict[str, Any]
    away_team: Dict[str, Any]
    status: str
    score: str
    clock: str
    competition: str
    venue: Dict[str, Any]
    officials: list
    events: list
    raw_espn_data: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'match_id': self.match_id,
            'home_team': self.home_team,
            'away_team': self.away_team,
            'status': self.status,
            'score': self.score,
            'clock': self.clock,
            'competition': self.competition,
            'venue': self.venue,
            'officials': self.officials,
            'events': self.events,
            'raw_espn_data': self.raw_espn_data
        }


@dataclass
class MatchUpdate:
    """
    Represents a match update result from the V2 system.
    
    Contains information about what was processed and any events
    that were generated during the update cycle.
    """
    match_id: str
    success: bool
    events_processed: int
    new_events: list
    status_changed: bool
    score_changed: bool
    error_message: Optional[str] = None
    processing_time_ms: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'match_id': self.match_id,
            'success': self.success,
            'events_processed': self.events_processed,
            'new_events': [event.to_dict() if hasattr(event, 'to_dict') else event for event in self.new_events],
            'status_changed': self.status_changed,
            'score_changed': self.score_changed,
            'error_message': self.error_message,
            'processing_time_ms': self.processing_time_ms
        }