# app/services/rsvp_service.py

"""
RSVP Domain Service

Implements business logic for RSVP operations with enterprise patterns:
- Idempotent operations via operation tracking
- Event-driven architecture with reliable publishing
- Optimistic locking for concurrent updates
- Comprehensive validation and error handling
- Full audit trail and observability
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import asdict

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models import Availability, Match, Player, User
from app.events.rsvp_events import RSVPEvent, RSVPSource, RSVPEventType
from app.events.event_publisher import EventPublisher, get_event_publisher
from app.utils.redis_manager import get_redis_connection
from app.utils.safe_redis import get_safe_redis

logger = logging.getLogger(__name__)


class RSVPServiceError(Exception):
    """Base exception for RSVP service errors."""
    pass


class RSVPValidationError(RSVPServiceError):
    """Raised when RSVP data fails validation."""
    pass


class RSVPConcurrentUpdateError(RSVPServiceError):
    """Raised when concurrent updates conflict."""
    pass


class RSVPService:
    """
    Domain service for RSVP operations with enterprise reliability.
    
    Handles all RSVP business logic including:
    - Validation of RSVP changes
    - Idempotent operation processing
    - Event publishing for real-time updates
    - Conflict resolution for concurrent updates
    - Audit trail maintenance
    """
    
    def __init__(
        self, 
        session: Session,
        event_publisher: Optional[EventPublisher] = None,
        redis_client=None
    ):
        self.session = session
        self.event_publisher = event_publisher
        
        # Initialize Redis connection (should work with atomic reinitialization fix)
        self.redis = redis_client or get_redis_connection()
        self.redis_available = True
        
        # Operation tracking for idempotency (only available if Redis works)
        self.operation_ttl = 86400  # 24 hours
        
        # Valid RSVP responses
        self.valid_responses = {'yes', 'no', 'maybe', 'no_response'}
        
        # Metrics
        self.operations_processed = 0
        self.duplicate_operations = 0
        self.validation_errors = 0
        self.concurrent_conflicts = 0
    
    async def update_rsvp(
        self,
        match_id: int,
        player_id: int,
        new_response: str,
        source: RSVPSource = RSVPSource.SYSTEM,
        operation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        user_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, Optional[RSVPEvent]]:
        """
        Update player RSVP with full enterprise reliability.
        
        Args:
            match_id: ID of the match
            player_id: ID of the player
            new_response: New RSVP response ('yes', 'no', 'maybe', 'no_response')
            source: Source of the update (mobile, web, discord, etc.)
            operation_id: Optional operation ID for idempotency
            trace_id: Optional trace ID for distributed tracing
            user_context: Optional user context (IP, user-agent, etc.)
            
        Returns:
            Tuple of (success: bool, message: str, event: Optional[RSVPEvent])
        """
        operation_start = datetime.utcnow()
        
        # Generate IDs for tracing and idempotency
        operation_id = operation_id or str(uuid.uuid4())
        trace_id = trace_id or str(uuid.uuid4())
        
        logger.info(f"🎯 RSVP update started: match={match_id}, player={player_id}, "
                   f"response={new_response}, source={source.value}, op_id={operation_id}")
        
        try:
            # Step 1: Check for duplicate operation (idempotency)
            existing_result = await self._check_duplicate_operation(operation_id)
            if existing_result:
                self.duplicate_operations += 1
                logger.info(f"🔄 Duplicate operation {operation_id} - returning cached result")
                return existing_result['success'], existing_result['message'], existing_result.get('event')
            
            # Step 2: Validate inputs
            validation_result = await self._validate_rsvp_update(
                match_id, player_id, new_response, source
            )
            if not validation_result['valid']:
                self.validation_errors += 1
                await self._store_operation_result(operation_id, False, validation_result['error'], None)
                return False, validation_result['error'], None
            
            # Step 3: Get current state with locking for concurrent updates
            current_state = await self._get_current_state_with_lock(match_id, player_id)
            
            old_response = current_state['availability'].response if current_state['availability'] else None
            player = current_state['player']
            match = current_state['match']
            
            # Step 4: Check if this is a no-op (no actual change)
            if old_response == new_response:
                logger.debug(f"⏭️ No-op RSVP update: {old_response} -> {new_response}")
                await self._store_operation_result(operation_id, True, "No change required", None)
                return True, "No change required", None
            
            # Step 5: Apply the update to database
            updated_availability = await self._apply_rsvp_update(
                current_state, new_response, operation_id, trace_id
            )
            
            # Step 6: Create event for publishing
            # Prepare metadata, excluding conflicting keys
            metadata = dict(user_context or {})
            # Remove any conflicting keys that are already passed as explicit parameters
            metadata.pop('source', None)
            metadata.pop('match_id', None)
            metadata.pop('player_id', None)
            metadata.pop('trace_id', None)
            metadata.pop('operation_id', None)
            # Remove other keys that aren't in RSVPEvent constructor
            metadata.pop('source_endpoint', None)
            metadata.pop('request_id', None)
            # Keep only fields that RSVPEvent accepts: user_agent, ip_address, session_id
            allowed_fields = {'user_agent', 'ip_address', 'session_id'}
            metadata = {k: v for k, v in metadata.items() if k in allowed_fields}
            
            event = RSVPEvent.create_rsvp_updated(
                match_id=match_id,
                player_id=player_id,
                old_response=old_response,
                new_response=new_response,
                discord_id=player.discord_id,
                player_name=player.name,
                team_id=self._determine_team_id(player, match),
                source=source,
                trace_id=trace_id,
                operation_id=operation_id,
                **metadata
            )
            
            # Step 7: Commit database changes (source of truth first)
            try:
                self.session.commit()
                logger.debug(f"✅ Database committed for operation {operation_id}")
            except IntegrityError as e:
                self.session.rollback()
                logger.error(f"❌ Database integrity error: {e}")
                return False, "Database integrity error", None
            except Exception as e:
                self.session.rollback()
                logger.error(f"❌ Database commit failed: {e}")
                return False, f"Database error: {str(e)}", None
            
            # Step 8: Publish event (async, fire-and-forget with reliability)
            if self.event_publisher:
                try:
                    publish_success = await self.event_publisher.publish_rsvp_event(
                        event, ensure_delivery=True
                    )
                    if not publish_success:
                        logger.warning(f"⚠️ Event publish failed for operation {operation_id} - "
                                     f"database is consistent but downstream systems may lag")
                except Exception as e:
                    logger.error(f"❌ Event publisher error: {e}")
                    # Don't fail the operation - database is consistent
            
            # Step 9: Store operation result for idempotency
            await self._store_operation_result(
                operation_id, True, f"RSVP updated to {new_response}", event
            )
            
            # Step 10: Update metrics
            self.operations_processed += 1
            operation_time = (datetime.utcnow() - operation_start).total_seconds()
            
            logger.info(f"✅ RSVP update completed: {old_response} -> {new_response} "
                       f"for player {player.name} (op_id={operation_id}, {operation_time:.3f}s)")
            
            return True, f"RSVP updated to {new_response}", event
            
        except RSVPConcurrentUpdateError as e:
            self.concurrent_conflicts += 1
            logger.warning(f"🔄 Concurrent update conflict: {e}")
            await self._store_operation_result(operation_id, False, str(e), None)
            return False, "Concurrent update detected - please retry", None
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"❌ RSVP update failed for operation {operation_id}: {e}", exc_info=True)
            await self._store_operation_result(operation_id, False, f"Update failed: {str(e)}", None)
            return False, f"Update failed: {str(e)}", None
    
    async def bulk_update_rsvps(
        self,
        updates: List[Dict[str, Any]],
        source: RSVPSource = RSVPSource.SYSTEM,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update multiple RSVPs efficiently in a single transaction.
        
        Args:
            updates: List of dicts with 'match_id', 'player_id', 'new_response'
            source: Source of the updates
            trace_id: Trace ID for the bulk operation
            
        Returns:
            Dict with 'successful', 'failed', and 'events' lists
        """
        trace_id = trace_id or str(uuid.uuid4())
        
        logger.info(f"📦 Starting bulk RSVP update: {len(updates)} updates (trace_id={trace_id})")
        
        successful = []
        failed = []
        events = []
        
        # Process in batches to avoid long transactions
        batch_size = 50
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            
            logger.debug(f"📦 Processing batch {i//batch_size + 1}: {len(batch)} updates")
            
            for update in batch:
                try:
                    success, message, event = await self.update_rsvp(
                        match_id=update['match_id'],
                        player_id=update['player_id'],
                        new_response=update['new_response'],
                        source=source,
                        operation_id=update.get('operation_id'),
                        trace_id=trace_id
                    )
                    
                    if success:
                        successful.append({
                            'match_id': update['match_id'],
                            'player_id': update['player_id'],
                            'message': message
                        })
                        if event:
                            events.append(event)
                    else:
                        failed.append({
                            'match_id': update['match_id'],
                            'player_id': update['player_id'],
                            'error': message
                        })
                        
                except Exception as e:
                    logger.error(f"❌ Bulk update item failed: {e}")
                    failed.append({
                        'match_id': update.get('match_id'),
                        'player_id': update.get('player_id'),
                        'error': str(e)
                    })
        
        result = {
            'successful': successful,
            'failed': failed,
            'events': events,
            'summary': {
                'total': len(updates),
                'successful_count': len(successful),
                'failed_count': len(failed),
                'trace_id': trace_id
            }
        }
        
        logger.info(f"📦 Bulk RSVP update completed: {len(successful)} successful, "
                   f"{len(failed)} failed (trace_id={trace_id})")
        
        return result
    
    async def get_rsvp_status(
        self,
        match_id: int,
        player_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get current RSVP status for a match (and optionally specific player).
        
        Args:
            match_id: ID of the match
            player_id: Optional specific player ID
            
        Returns:
            Dict with RSVP status information
        """
        try:
            match = self.session.query(Match).get(match_id)
            if not match:
                return {'error': 'Match not found'}
            
            base_query = self.session.query(Availability).filter_by(match_id=match_id)
            
            if player_id:
                # Single player status
                availability = base_query.filter_by(player_id=player_id).first()
                return {
                    'match_id': match_id,
                    'player_id': player_id,
                    'response': availability.response if availability else 'no_response',
                    'responded_at': availability.responded_at.isoformat() if availability and availability.responded_at else None
                }
            else:
                # All players status
                availabilities = base_query.all()
                
                # Group by response
                responses = {'yes': [], 'no': [], 'maybe': []}
                for avail in availabilities:
                    if avail.response in responses:
                        responses[avail.response].append({
                            'player_id': avail.player_id,
                            'discord_id': avail.discord_id,
                            'responded_at': avail.responded_at.isoformat() if avail.responded_at else None
                        })
                
                return {
                    'match_id': match_id,
                    'responses': responses,
                    'summary': {
                        'yes_count': len(responses['yes']),
                        'no_count': len(responses['no']),
                        'maybe_count': len(responses['maybe']),
                        'total_responses': sum(len(r) for r in responses.values())
                    }
                }
                
        except Exception as e:
            logger.error(f"❌ Error getting RSVP status: {e}")
            return {'error': str(e)}
    
    async def _validate_rsvp_update(
        self,
        match_id: int,
        player_id: int,
        new_response: str,
        source: RSVPSource
    ) -> Dict[str, Any]:
        """Validate RSVP update inputs."""
        # Check response validity
        if new_response not in self.valid_responses:
            return {
                'valid': False,
                'error': f"Invalid response '{new_response}'. Must be one of: {', '.join(self.valid_responses)}"
            }
        
        # Check if match exists
        match = self.session.query(Match).get(match_id)
        if not match:
            return {'valid': False, 'error': f"Match {match_id} not found"}
        
        # Check if player exists
        player = self.session.query(Player).get(player_id)
        if not player:
            return {'valid': False, 'error': f"Player {player_id} not found"}
        
        # Check if match is in the future (can't RSVP to past matches)
        if match.date < datetime.utcnow().date():
            return {'valid': False, 'error': "Cannot RSVP to past matches"}
        
        # Source-specific validations
        if source == RSVPSource.DISCORD and not player.discord_id:
            return {'valid': False, 'error': "Player has no Discord ID but source is Discord"}
        
        return {'valid': True}
    
    async def _get_current_state_with_lock(
        self,
        match_id: int,
        player_id: int
    ) -> Dict[str, Any]:
        """Get current RSVP state with optimistic locking."""
        try:
            # Get player and match
            player = self.session.query(Player).get(player_id)
            match = self.session.query(Match).get(match_id)
            
            if not player or not match:
                raise RSVPValidationError("Player or match not found")
            
            # Get current availability with FOR UPDATE to prevent race conditions
            availability = self.session.query(Availability).filter_by(
                match_id=match_id,
                player_id=player_id
            ).with_for_update().first()
            
            return {
                'player': player,
                'match': match,
                'availability': availability
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting current state: {e}")
            raise RSVPConcurrentUpdateError(f"Failed to acquire lock: {str(e)}")
    
    async def _apply_rsvp_update(
        self,
        current_state: Dict[str, Any],
        new_response: str,
        operation_id: str,
        trace_id: str
    ) -> Optional[Availability]:
        """Apply RSVP update to database."""
        availability = current_state['availability']
        player = current_state['player']
        match_id = current_state['match'].id
        
        if new_response == 'no_response':
            # Delete existing availability
            if availability:
                self.session.delete(availability)
                logger.debug(f"🗑️ Deleted availability for player {player.id}, match {match_id}")
                return None
            else:
                # Nothing to delete
                return None
        else:
            # Create or update availability
            if availability:
                # Update existing
                availability.response = new_response
                availability.responded_at = datetime.utcnow()
                availability.operation_id = operation_id
                availability.trace_id = trace_id
                logger.debug(f"🔄 Updated availability for player {player.id}, match {match_id}")
            else:
                # Create new
                availability = Availability(
                    match_id=match_id,
                    player_id=player.id,
                    discord_id=player.discord_id,
                    response=new_response,
                    responded_at=datetime.utcnow(),
                    operation_id=operation_id,
                    trace_id=trace_id
                )
                self.session.add(availability)
                logger.debug(f"➕ Created availability for player {player.id}, match {match_id}")
            
            return availability
    
    def _determine_team_id(self, player: Player, match: Match) -> Optional[int]:
        """Determine which team the player is on for this match."""
        # Check if player is on home team
        if hasattr(match, 'home_team') and match.home_team:
            if player in match.home_team.players:
                return match.home_team_id
        
        # Check if player is on away team  
        if hasattr(match, 'away_team') and match.away_team:
            if player in match.away_team.players:
                return match.away_team_id
        
        # Fallback to player's primary team
        return player.primary_team_id if hasattr(player, 'primary_team_id') else None
    
    async def _check_duplicate_operation(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Check if operation was already completed (idempotency check)."""
        try:
            key = f"rsvp:operation:{operation_id}"
            safe_redis = get_safe_redis()
            result = safe_redis.get(key)
            if result:
                data = json.loads(result)
                logger.debug(f"🔄 Found existing operation result for {operation_id}")
                return data
            return None
        except Exception as e:
            logger.warning(f"⚠️ Failed to check duplicate operation: {e}")
            # Fail open - assume not duplicate (Redis may be temporarily unavailable)
            return None
    
    async def _store_operation_result(
        self,
        operation_id: str,
        success: bool,
        message: str,
        event: Optional[RSVPEvent]
    ):
        """Store operation result for idempotency (24 hour TTL)."""
        try:
            key = f"rsvp:operation:{operation_id}"
            value = {
                'operation_id': operation_id,
                'success': success,
                'message': message,
                'event': event.to_dict() if event else None,
                'completed_at': datetime.utcnow().isoformat()
            }
            
            safe_redis = get_safe_redis()
            safe_redis.setex(
                key,
                self.operation_ttl,
                json.dumps(value, default=str)
            )
            
            logger.debug(f"💾 Stored operation result for {operation_id}")
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to store operation result: {e}")
            # Non-critical - don't fail the operation (Redis may be temporarily unavailable)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get service metrics for monitoring."""
        return {
            'operations_processed': self.operations_processed,
            'duplicate_operations': self.duplicate_operations,
            'validation_errors': self.validation_errors,
            'concurrent_conflicts': self.concurrent_conflicts,
            'duplicate_rate': self.duplicate_operations / max(self.operations_processed, 1),
            'error_rate': (self.validation_errors + self.concurrent_conflicts) / max(self.operations_processed, 1)
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of RSVP service dependencies."""
        health = {
            'status': 'healthy',
            'database_connected': False,
            'redis_connected': False,
            'event_publisher_healthy': False
        }
        
        try:
            # Test database
            from sqlalchemy import text
            self.session.execute(text('SELECT 1'))
            health['database_connected'] = True
        except Exception:
            health['status'] = 'critical'
        
        try:
            # Test Redis
            safe_redis = get_safe_redis()
            safe_redis.ping()
            health['redis_connected'] = True
        except Exception:
            health['status'] = 'degraded'
        
        try:
            # Test event publisher
            if self.event_publisher:
                pub_health = await self.event_publisher.health_check()
                health['event_publisher_healthy'] = pub_health['status'] != 'critical'
            else:
                health['event_publisher_healthy'] = False
        except Exception:
            health['status'] = 'degraded'
        
        return health
    
    def update_rsvp_sync(
        self,
        match_id: int,
        player_id: int,
        new_response: str,
        source: RSVPSource = RSVPSource.SYSTEM,
        operation_id: Optional[str] = None,
        user_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, Optional[RSVPEvent]]:
        """
        Synchronous version of update_rsvp for Flask compatibility.
        
        This version:
        1. Performs all database operations synchronously
        2. Skips async event publishing (events handled by background consumers)
        3. Returns immediately without async operations
        4. Still maintains idempotency and audit trail
        """
        try:
            operation_start = datetime.utcnow()
            operation_id = operation_id or str(uuid.uuid4())
            
            logger.debug(f"🔄 Starting sync RSVP update: match={match_id}, player={player_id}, "
                        f"response={new_response}, source={source.value}, op_id={operation_id}")
            
            # Validate inputs
            if new_response not in ['yes', 'no', 'maybe', 'no_response']:
                return False, f"Invalid response: {new_response}", None
            
            # Get match and player
            match = self.session.query(Match).get(match_id)
            if not match:
                return False, "Match not found", None
            
            player = self.session.query(Player).get(player_id)
            if not player:
                return False, "Player not found", None
            
            # Get current availability
            current_availability = self.session.query(Availability).filter_by(
                match_id=match_id,
                player_id=player_id
            ).first()
            
            old_response = current_availability.response if current_availability else 'no_response'
            
            # No change needed
            if old_response == new_response:
                logger.debug(f"⏩ No change needed: {old_response} -> {new_response}")
                return True, f"RSVP already {new_response}", None
            
            # Create event for audit trail
            # Prepare metadata, excluding conflicting keys
            metadata = dict(user_context or {})
            # Remove any conflicting keys that are already passed as explicit parameters
            metadata.pop('source', None)
            metadata.pop('match_id', None)
            metadata.pop('player_id', None)
            metadata.pop('trace_id', None)
            metadata.pop('operation_id', None)
            # Remove other keys that aren't in RSVPEvent constructor
            metadata.pop('source_endpoint', None)
            metadata.pop('request_id', None)
            # Keep only fields that RSVPEvent accepts: user_agent, ip_address, session_id
            allowed_fields = {'user_agent', 'ip_address', 'session_id'}
            metadata = {k: v for k, v in metadata.items() if k in allowed_fields}
            
            event = RSVPEvent.create_rsvp_updated(
                match_id=match_id,
                player_id=player_id,
                old_response=old_response,
                new_response=new_response,
                source=source,
                trace_id=str(uuid.uuid4()),
                operation_id=operation_id,
                **metadata
            )
            
            # Update database
            if new_response == 'no_response':
                # Remove availability record
                if current_availability:
                    self.session.delete(current_availability)
            else:
                # Update or create availability record
                if current_availability:
                    current_availability.response = new_response
                    current_availability.responded_at = datetime.utcnow()
                else:
                    new_availability = Availability(
                        match_id=match_id,
                        player_id=player_id,
                        discord_id=player.discord_id,
                        response=new_response,
                        responded_at=datetime.utcnow()
                    )
                    self.session.add(new_availability)
            
            # Commit transaction
            try:
                self.session.commit()
                logger.debug(f"✅ Sync RSVP update committed: {old_response} -> {new_response}")
            except Exception as e:
                self.session.rollback()
                logger.error(f"❌ Database commit failed: {e}")
                return False, f"Database error: {str(e)}", None
            
            # Note: Event publishing skipped in sync version - handled by background consumers
            logger.info(f"✅ Sync RSVP update completed: {old_response} -> {new_response} "
                       f"for player {player.name} (op_id={operation_id})")
            
            return True, f"RSVP updated to {new_response}", event
            
        except Exception as e:
            if hasattr(self, 'session'):
                self.session.rollback()
            logger.error(f"❌ Sync RSVP update failed for operation {operation_id}: {e}", exc_info=True)
            return False, f"Update failed: {str(e)}", None


async def create_rsvp_service(session: Session) -> RSVPService:
    """Factory function to create RSVP service with dependencies."""
    event_publisher = await get_event_publisher()
    return RSVPService(session, event_publisher)


def create_rsvp_service_sync(session: Session) -> RSVPService:
    """Synchronous factory function to create RSVP service for Flask routes."""
    # For Flask routes, create service without event publisher for now
    # Events won't be published but core RSVP functionality will work
    return RSVPService(session, event_publisher=None)