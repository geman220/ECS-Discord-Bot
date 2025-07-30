# app/services/conflict_resolver.py

"""
Enterprise RSVP Conflict Resolution Service

Handles conflicts when multiple systems (Discord, Mobile, Database) have
different RSVP states for the same user/match during recovery scenarios.

Uses a sophisticated conflict resolution strategy:
1. Timestamp-based Last-Write-Wins
2. Source authority hierarchy  
3. User intent preservation
4. Audit trail for all resolutions
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

from app.models import Availability, Player, Match
from app.events.rsvp_events import RSVPSource

logger = logging.getLogger(__name__)


class ConflictResolutionStrategy(Enum):
    """Strategies for resolving RSVP conflicts."""
    LAST_WRITE_WINS = "last_write_wins"
    SOURCE_HIERARCHY = "source_hierarchy" 
    USER_INTENT_PRESERVATION = "user_intent_preservation"


@dataclass
class RSVPState:
    """Represents RSVP state from a specific source."""
    source: RSVPSource
    response: str
    timestamp: datetime
    confidence: float  # 0.0 to 1.0, how confident we are in this state
    user_id: str
    match_id: int


@dataclass
class ConflictResolution:
    """Result of conflict resolution."""
    resolved_response: str
    chosen_source: RSVPSource
    resolution_strategy: ConflictResolutionStrategy
    confidence: float
    conflicting_states: List[RSVPState]
    resolution_reason: str
    trace_id: str


class EnterpriseConflictResolver:
    """
    Resolves RSVP conflicts using enterprise-grade strategies.
    
    Handles scenarios like:
    - Discord: User has 👎 (NO)
    - Database: User has YES (stale)  
    - Mobile: User has MAYBE (cached)
    
    Determines the "true" state and reconciles all systems.
    """
    
    def __init__(self, downtime_window: timedelta = None):
        """
        Initialize conflict resolver.
        
        Args:
            downtime_window: How long systems were down (for timestamp analysis)
        """
        self.downtime_window = downtime_window or timedelta(hours=1)
        
        # Source authority hierarchy (higher = more authoritative)
        self.source_authority = {
            RSVPSource.SYSTEM: 1,      # Lowest - system-generated
            RSVPSource.DISCORD: 3,     # High - user explicitly reacted
            RSVPSource.MOBILE: 4,      # Highest - user explicitly chose in app
        }
    
    async def resolve_rsvp_conflict(
        self,
        discord_state: Optional[RSVPState],
        database_state: Optional[RSVPState], 
        mobile_state: Optional[RSVPState],
        downtime_start: datetime,
        trace_id: str
    ) -> ConflictResolution:
        """
        Resolve RSVP conflict between multiple sources.
        
        Args:
            discord_state: Current Discord reaction state
            database_state: Current database RSVP state
            mobile_state: Mobile app cached state (if any)
            downtime_start: When systems went offline
            trace_id: For audit tracking
            
        Returns:
            ConflictResolution with the authoritative state
        """
        logger.info(f"🔀 Resolving RSVP conflict for trace_id={trace_id}")
        
        # Collect all non-None states
        states = [s for s in [discord_state, database_state, mobile_state] if s]
        
        if len(states) <= 1:
            # No conflict - single source of truth
            resolved_state = states[0] if states else None
            return self._create_no_conflict_resolution(resolved_state, trace_id)
        
        # Multiple states exist - resolve conflict
        if len(set(s.response for s in states)) == 1:
            # All states agree - no conflict
            return self._create_no_conflict_resolution(states[0], trace_id)
        
        # True conflict exists - apply resolution strategy
        logger.warning(f"⚠️ True RSVP conflict detected: {[(s.source.value, s.response) for s in states]}")
        
        # Use hybrid resolution strategy
        resolution = await self._apply_hybrid_resolution(states, downtime_start, trace_id)
        
        logger.info(f"✅ Conflict resolved: {resolution.chosen_source.value} -> {resolution.resolved_response} "
                   f"(reason: {resolution.resolution_reason})")
        
        return resolution
    
    async def _apply_hybrid_resolution(
        self,
        states: List[RSVPState],
        downtime_start: datetime,
        trace_id: str
    ) -> ConflictResolution:
        """
        Apply hybrid resolution strategy combining multiple approaches.
        
        Strategy:
        1. If any state changed during downtime -> Last-Write-Wins
        2. If multiple changed during downtime -> Source Hierarchy  
        3. If none changed during downtime -> Most Authoritative Source
        """
        downtime_end = downtime_start + self.downtime_window
        
        # Categorize states by when they changed
        changed_during_downtime = [
            s for s in states 
            if downtime_start <= s.timestamp <= downtime_end
        ]
        
        if len(changed_during_downtime) == 1:
            # Clear winner - only one state changed during downtime
            winner = changed_during_downtime[0]
            return ConflictResolution(
                resolved_response=winner.response,
                chosen_source=winner.source,
                resolution_strategy=ConflictResolutionStrategy.LAST_WRITE_WINS,
                confidence=0.95,
                conflicting_states=states,
                resolution_reason=f"Only {winner.source.value} changed during downtime",
                trace_id=trace_id
            )
        
        elif len(changed_during_downtime) > 1:
            # Multiple changes during downtime - use source hierarchy
            winner = max(changed_during_downtime, key=lambda s: self.source_authority[s.source])
            return ConflictResolution(
                resolved_response=winner.response,
                chosen_source=winner.source,
                resolution_strategy=ConflictResolutionStrategy.SOURCE_HIERARCHY,
                confidence=0.85,
                conflicting_states=states,
                resolution_reason=f"{winner.source.value} has highest authority among downtime changes",
                trace_id=trace_id
            )
        
        else:
            # No changes during downtime - use most authoritative source
            winner = max(states, key=lambda s: self.source_authority[s.source])
            return ConflictResolution(
                resolved_response=winner.response,
                chosen_source=winner.source,
                resolution_strategy=ConflictResolutionStrategy.SOURCE_HIERARCHY,
                confidence=0.70,
                conflicting_states=states,
                resolution_reason=f"{winner.source.value} is most authoritative source",
                trace_id=trace_id
            )
    
    def _create_no_conflict_resolution(
        self,
        state: Optional[RSVPState],
        trace_id: str
    ) -> ConflictResolution:
        """Create resolution for non-conflict scenarios."""
        if not state:
            # No state at all - default to no_response
            return ConflictResolution(
                resolved_response="no_response",
                chosen_source=RSVPSource.SYSTEM,
                resolution_strategy=ConflictResolutionStrategy.USER_INTENT_PRESERVATION,
                confidence=1.0,
                conflicting_states=[],
                resolution_reason="No RSVP state found",
                trace_id=trace_id
            )
        
        return ConflictResolution(
            resolved_response=state.response,
            chosen_source=state.source,
            resolution_strategy=ConflictResolutionStrategy.USER_INTENT_PRESERVATION,
            confidence=1.0,
            conflicting_states=[state],
            resolution_reason="Single source of truth",
            trace_id=trace_id
        )
    
    async def get_discord_state(
        self,
        match_id: int,
        discord_id: str,
        message_id: str,
        channel_id: str
    ) -> Optional[RSVPState]:
        """
        Get current Discord reaction state for a user.
        
        Returns the user's current reaction state from Discord's API.
        """
        try:
            # This would call Discord API to get current reactions
            # Implementation depends on your Discord bot integration
            
            # Placeholder - would be implemented with actual Discord API calls
            logger.debug(f"Getting Discord state for user {discord_id} on match {match_id}")
            
            # For now, return None - actual implementation would:
            # 1. Fetch message from Discord
            # 2. Check user's current reactions  
            # 3. Map reaction to RSVP response
            # 4. Return RSVPState with current timestamp
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting Discord state: {e}")
            return None
    
    async def get_database_state(
        self,
        session,
        match_id: int,
        discord_id: str
    ) -> Optional[RSVPState]:
        """Get current database RSVP state for a user."""
        try:
            availability = session.query(Availability).filter_by(
                match_id=match_id,
                discord_id=discord_id
            ).first()
            
            if not availability:
                return None
            
            return RSVPState(
                source=RSVPSource.SYSTEM,  # Database is system source
                response=availability.response,
                timestamp=availability.responded_at,
                confidence=0.8,
                user_id=discord_id,
                match_id=match_id
            )
            
        except Exception as e:
            logger.error(f"Error getting database state: {e}")
            return None
    
    async def apply_resolution(
        self,
        session,
        resolution: ConflictResolution,
        match_id: int,
        discord_id: str
    ) -> bool:
        """
        Apply the conflict resolution to all systems.
        
        Updates:
        1. Database with resolved state
        2. Triggers Discord embed update
        3. Triggers WebSocket broadcast
        """
        try:
            logger.info(f"🔧 Applying conflict resolution: {resolution.chosen_source.value} -> {resolution.resolved_response}")
            
            # Update database
            from app.services.rsvp_service import create_rsvp_service
            rsvp_service = await create_rsvp_service(session)
            
            # Get player ID
            player = session.query(Player).filter_by(discord_id=discord_id).first()
            if not player:
                logger.error(f"Player not found for discord_id: {discord_id}")
                return False
            
            # Apply the resolved state
            success, message, event = await rsvp_service.update_rsvp(
                match_id=match_id,
                player_id=player.id,
                new_response=resolution.resolved_response,
                source=resolution.chosen_source,
                operation_id=f"conflict_resolution_{resolution.trace_id}",
                user_context={
                    'conflict_resolution': True,
                    'resolution_strategy': resolution.resolution_strategy.value,
                    'confidence': resolution.confidence,
                    'resolution_reason': resolution.resolution_reason
                }
            )
            
            if success:
                logger.info(f"✅ Conflict resolution applied successfully")
                return True
            else:
                logger.error(f"❌ Failed to apply conflict resolution: {message}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error applying conflict resolution: {e}", exc_info=True)
            return False


# Factory function for easy usage
async def create_conflict_resolver(downtime_window: timedelta = None) -> EnterpriseConflictResolver:
    """Create a configured conflict resolver."""
    return EnterpriseConflictResolver(downtime_window)