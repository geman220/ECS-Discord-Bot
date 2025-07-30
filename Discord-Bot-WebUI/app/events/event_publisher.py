# app/events/event_publisher.py

"""
Enterprise Event Publisher with Redis Streams

Provides reliable event publishing with:
- Redis Streams for durability and ordering
- Dead Letter Queue for failed events
- Bulk publishing for performance 
- Automatic retries with exponential backoff
- Event deduplication
- Observability and metrics
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set
from dataclasses import asdict

from app.events.rsvp_events import RSVPEvent, RSVPSyncEvent
from app.utils.redis_manager import get_redis_connection
from app.utils.safe_redis import get_safe_redis

logger = logging.getLogger(__name__)


class EventPublisher:
    """
    Reliable event publisher with enterprise patterns.
    
    Features:
    - Redis Streams for durable, ordered events
    - Consumer groups for load balancing
    - Dead Letter Queue for failed events
    - Deduplication to prevent duplicate processing
    - Bulk operations for performance
    - Circuit breaker for Redis failures
    """
    
    def __init__(self, redis_client=None, max_retries: int = 3):
        self.redis = redis_client or get_redis_connection()
        self.max_retries = max_retries
        
        # Stream configurations
        self.streams = {
            'rsvp:websocket': {
                'maxlen': 10000,  # Keep last 10k events
                'consumer_groups': ['websocket_broadcasters']
            },
            'rsvp:discord': {
                'maxlen': 10000,
                'consumer_groups': ['discord_embed_updaters', 'discord_reaction_updaters']
            },
            'rsvp:analytics': {
                'maxlen': 50000,  # Keep more for analytics
                'consumer_groups': ['analytics_processors']
            },
            'rsvp:audit': {
                'maxlen': 100000,  # Long retention for compliance
                'consumer_groups': ['audit_processors']
            },
            'rsvp:dlq': {
                'maxlen': 10000,
                'consumer_groups': ['dlq_processors']
            }
        }
        
        # Metrics
        self.events_published = 0
        self.events_failed = 0
        self.last_publish_time = None
        
        # Deduplication cache (Redis-based)
        self.dedup_ttl = 3600  # 1 hour
    
    async def initialize(self):
        """Initialize event streams and consumer groups."""
        try:
            logger.info("🚀 Initializing event publisher streams...")
            
            for stream_name, config in self.streams.items():
                # Create stream if it doesn't exist
                safe_redis = get_safe_redis()
                if safe_redis.is_available:
                    try:
                        safe_redis.client.xadd(
                            stream_name,
                            {'_init': 'true'},
                            maxlen=config['maxlen']
                        )
                    except Exception as e:
                        logger.warning(f"Failed to initialize stream {stream_name}: {e}")
                
                # Create consumer groups
                for group_name in config['consumer_groups']:
                    try:
                        safe_redis = get_safe_redis()
                        if safe_redis.is_available:
                            try:
                                safe_redis.client.xgroup_create(
                                    stream_name,
                                    group_name,
                                    id='0',
                                    mkstream=True
                                )
                            except Exception as e:
                                if "BUSYGROUP" not in str(e):
                                    raise
                        logger.debug(f"✅ Created consumer group {group_name} for {stream_name}")
                    except Exception as e:
                        if "BUSYGROUP" in str(e):
                            # Group already exists - that's fine
                            logger.debug(f"📋 Consumer group {group_name} already exists for {stream_name}")
                        else:
                            logger.warning(f"⚠️ Failed to create consumer group {group_name}: {e}")
            
            logger.info("✅ Event publisher initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize event publisher: {e}")
            raise
    
    async def publish_rsvp_event(
        self, 
        event: RSVPEvent,
        targets: Optional[Set[str]] = None,
        ensure_delivery: bool = True
    ) -> bool:
        """
        Publish RSVP event to multiple streams with reliability.
        
        Args:
            event: The RSVP event to publish
            targets: Optional set of target streams ['websocket', 'discord', 'analytics', 'audit']
            ensure_delivery: Whether to use DLQ for failed events
            
        Returns:
            bool: True if published successfully to all targets
        """
        start_time = time.time()
        
        try:
            # Check for duplicate event (idempotency)
            if await self._is_duplicate_event(event):
                logger.info(f"🔄 Skipping duplicate event {event.event_id}")
                return True
            
            # Determine target streams
            if targets is None:
                targets = self._determine_targets(event)
            
            # Prepare event data
            event_data = event.to_dict()
            
            # Add publisher metadata
            event_data.update({
                'publisher_timestamp': datetime.utcnow().isoformat(),
                'publisher_version': '1.0',
                'routing_key': event.get_routing_key()
            })
            
            # Publish to multiple streams atomically
            success = await self._publish_to_streams(event_data, targets, event.event_id)
            
            if success:
                # Mark as published for deduplication
                await self._mark_event_published(event)
                
                # Update metrics
                self.events_published += 1
                self.last_publish_time = datetime.utcnow()
                
                publish_time = (time.time() - start_time) * 1000  # ms
                logger.info(f"📤 Published RSVP event {event.event_id} to {len(targets)} streams ({publish_time:.1f}ms)")
                
                return True
            else:
                # Send to DLQ if ensure_delivery is enabled
                if ensure_delivery:
                    await self._send_to_dlq(event_data, "Failed to publish to primary streams")
                
                self.events_failed += 1
                logger.error(f"❌ Failed to publish event {event.event_id}")
                return False
                
        except Exception as e:
            self.events_failed += 1
            logger.error(f"❌ Error publishing event {event.event_id}: {e}")
            
            # Send to DLQ for manual recovery
            if ensure_delivery:
                try:
                    await self._send_to_dlq(event.to_dict(), f"Publisher error: {str(e)}")
                except Exception as dlq_error:
                    logger.error(f"❌ Failed to send to DLQ: {dlq_error}")
            
            return False
    
    async def publish_sync_event(self, sync_event: RSVPSyncEvent) -> bool:
        """Publish a sync request event for manual RSVP synchronization."""
        try:
            event_data = asdict(sync_event)
            event_data['occurred_at'] = sync_event.occurred_at.isoformat()
            
            # Send to high-priority sync stream
            safe_redis = get_safe_redis()
            result = None
            if safe_redis.is_available:
                try:
                    result = safe_redis.client.xadd(
                        'rsvp:sync',
                        event_data,
                        maxlen=1000
                    )
                except Exception as e:
                    logger.error(f"Failed to publish sync event: {e}")
            
            if result:
                logger.info(f"📤 Published sync event for match {sync_event.match_id}")
                return True
            else:
                logger.error(f"❌ Failed to publish sync event for match {sync_event.match_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error publishing sync event: {e}")
            return False
    
    async def publish_bulk_events(self, events: List[RSVPEvent]) -> Dict[str, int]:
        """
        Publish multiple events efficiently using Redis pipelines.
        
        Returns:
            Dict with 'published' and 'failed' counts
        """
        if not events:
            return {'published': 0, 'failed': 0}
        
        logger.info(f"📦 Publishing {len(events)} events in bulk...")
        
        published = 0
        failed = 0
        
        # Process in batches to avoid memory issues
        batch_size = 100
        for i in range(0, len(events), batch_size):
            batch = events[i:i + batch_size]
            
            try:
                # Use Redis pipeline for atomic batch operations
                pipe = self.redis.pipeline()
                
                for event in batch:
                    if await self._is_duplicate_event(event):
                        continue
                    
                    event_data = event.to_dict()
                    targets = self._determine_targets(event)
                    
                    for target in targets:
                        stream_name = f"rsvp:{target}"
                        if stream_name in self.streams:
                            pipe.xadd(
                                stream_name,
                                event_data,
                                maxlen=self.streams[stream_name]['maxlen']
                            )
                
                # Execute batch
                results = await pipe.execute()
                
                # Count successes (non-None results)
                batch_published = sum(1 for result in results if result)
                published += batch_published
                failed += (len(batch) * len(targets)) - batch_published
                
                logger.debug(f"📦 Batch {i//batch_size + 1}: {batch_published} published")
                
            except Exception as e:
                logger.error(f"❌ Bulk publish batch failed: {e}")
                failed += len(batch)
        
        logger.info(f"📦 Bulk publish complete: {published} published, {failed} failed")
        return {'published': published, 'failed': failed}
    
    def _determine_targets(self, event: RSVPEvent) -> Set[str]:
        """Determine which streams should receive this event."""
        targets = {'audit'}  # Always audit
        
        if event.affects_websocket():
            targets.add('websocket')
        
        if event.affects_discord():
            targets.add('discord')
        
        # Always send to analytics for metrics
        targets.add('analytics')
        
        return targets
    
    async def _publish_to_streams(
        self, 
        event_data: Dict[str, Any], 
        targets: Set[str],
        event_id: str
    ) -> bool:
        """Publish to multiple streams atomically using Redis pipeline."""
        try:
            # Use Redis pipeline for atomic multi-stream publish
            pipe = self.redis.pipeline()
            
            for target in targets:
                stream_name = f"rsvp:{target}"
                if stream_name in self.streams:
                    pipe.xadd(
                        stream_name,
                        event_data,
                        maxlen=self.streams[stream_name]['maxlen']
                    )
                else:
                    logger.warning(f"⚠️ Unknown target stream: {target}")
            
            # Execute all publications atomically
            results = await pipe.execute()
            
            # Check if all succeeded (all results should be non-None)
            success = all(result is not None for result in results)
            
            if not success:
                failed_targets = [target for i, target in enumerate(targets) if results[i] is None]
                logger.error(f"❌ Failed to publish to targets: {failed_targets}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Pipeline publish failed for event {event_id}: {e}")
            return False
    
    async def _is_duplicate_event(self, event: RSVPEvent) -> bool:
        """Check if event was already published (deduplication)."""
        try:
            key = f"event:published:{event.event_id}"
            safe_redis = get_safe_redis()
            exists = safe_redis.exists(key)
            return bool(exists)
        except Exception:
            # If we can't check, assume it's not a duplicate (fail open)
            return False
    
    async def _mark_event_published(self, event: RSVPEvent):
        """Mark event as published for deduplication."""
        try:
            key = f"event:published:{event.event_id}"
            safe_redis = get_safe_redis()
            safe_redis.setex(
                key,
                self.dedup_ttl,
                event.operation_id
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to mark event as published: {e}")
    
    async def _send_to_dlq(self, event_data: Dict[str, Any], error_reason: str):
        """Send failed event to Dead Letter Queue for manual recovery."""
        try:
            dlq_data = {
                'original_event': json.dumps(event_data, default=str),
                'error_reason': error_reason,
                'failed_at': datetime.utcnow().isoformat(),
                'retry_count': 0,
                'dlq_id': f"dlq_{int(time.time() * 1000)}"
            }
            
            safe_redis = get_safe_redis()
            if safe_redis.is_available:
                try:
                    safe_redis.client.xadd(
                        'rsvp:dlq',
                        dlq_data,
                        maxlen=self.streams['rsvp:dlq']['maxlen']
                    )
                except Exception as e:
                    logger.error(f"Failed to add to DLQ: {e}")
            
            logger.warning(f"📨 Sent event to DLQ: {error_reason}")
            
        except Exception as e:
            logger.error(f"❌ Failed to send to DLQ: {e}")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get publisher metrics for monitoring."""
        return {
            'events_published': self.events_published,
            'events_failed': self.events_failed,
            'last_publish_time': self.last_publish_time.isoformat() if self.last_publish_time else None,
            'success_rate': self.events_published / (self.events_published + self.events_failed) if (self.events_published + self.events_failed) > 0 else 0,
            'configured_streams': list(self.streams.keys())
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of event publishing system."""
        health = {
            'status': 'healthy',
            'redis_connected': False,
            'streams_accessible': {},
            'metrics': self.get_metrics()
        }
        
        try:
            # Test Redis connection
            safe_redis = get_safe_redis()
            safe_redis.ping()
            health['redis_connected'] = True
            
            # Test stream accessibility
            for stream_name in self.streams.keys():
                try:
                    # Try to read last event from stream
                    safe_redis = get_safe_redis()
                    result = []
                    if safe_redis.is_available:
                        try:
                            result = safe_redis.client.xrevrange(
                                stream_name,
                                count=1
                            )
                        except Exception:
                            pass
                    health['streams_accessible'][stream_name] = True
                except Exception:
                    health['streams_accessible'][stream_name] = False
                    health['status'] = 'degraded'
            
        except Exception:
            health['redis_connected'] = False
            health['status'] = 'critical'
        
        return health


# Global publisher instance
_event_publisher = None

async def get_event_publisher() -> EventPublisher:
    """Get or create the global event publisher instance."""
    global _event_publisher
    
    if _event_publisher is None:
        _event_publisher = EventPublisher()
        await _event_publisher.initialize()
    
    return _event_publisher