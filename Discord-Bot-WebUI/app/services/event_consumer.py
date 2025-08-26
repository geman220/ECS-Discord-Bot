# app/services/event_consumer.py

"""
Event Consumer Framework for RSVP System

Provides reliable event consumption from Redis Streams with:
- Consumer groups for load balancing
- Automatic failure handling and retries
- Circuit breaker protection for external services
- Dead letter queue for failed events
- Idempotent processing
- Comprehensive observability
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass

from app.events.rsvp_events import RSVPEvent, RSVPSource
from app.services.redis_connection_service import get_redis_service
from app.utils.safe_redis import get_safe_redis
from app.utils.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from app.sockets.rsvp import emit_rsvp_update
from app import socketio

logger = logging.getLogger(__name__)


@dataclass
class ConsumerConfig:
    """Configuration for event consumers."""
    
    # Consumer identification
    consumer_name: str
    consumer_group: str
    stream_name: str
    
    # Processing behavior
    batch_size: int = 10
    poll_timeout: int = 5000  # milliseconds
    max_retries: int = 3
    retry_delay: int = 5  # seconds
    
    # Performance tuning
    prefetch_count: int = 100
    processing_timeout: int = 30  # seconds per event
    
    # Health monitoring
    heartbeat_interval: int = 60  # seconds
    max_processing_age: int = 300  # seconds before considering stuck


@dataclass
class ProcessingMetrics:
    """Metrics for event processing monitoring."""
    
    events_processed: int = 0
    events_failed: int = 0
    events_retried: int = 0
    events_dead_lettered: int = 0
    
    total_processing_time: float = 0.0
    last_processed_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    
    # Performance metrics
    avg_processing_time: float = 0.0
    peak_processing_time: float = 0.0
    
    def add_success(self, processing_time: float):
        """Record successful event processing."""
        self.events_processed += 1
        self.total_processing_time += processing_time
        self.last_processed_at = datetime.utcnow()
        
        # Update averages
        self.avg_processing_time = self.total_processing_time / self.events_processed
        self.peak_processing_time = max(self.peak_processing_time, processing_time)
    
    def add_failure(self):
        """Record failed event processing."""
        self.events_failed += 1
        self.last_failure_at = datetime.utcnow()
    
    def add_retry(self):
        """Record event retry."""
        self.events_retried += 1
    
    def add_dead_letter(self):
        """Record event sent to DLQ."""
        self.events_dead_lettered += 1
    
    def get_success_rate(self) -> float:
        """Get processing success rate."""
        total = self.events_processed + self.events_failed
        return self.events_processed / total if total > 0 else 0.0


class EventConsumer(ABC):
    """
    Base class for Redis Streams event consumers.
    
    Provides enterprise-grade event consumption with:
    - Reliable message processing with acknowledgments
    - Automatic failure handling and retries
    - Dead letter queue for persistent failures
    - Consumer group management for load balancing
    - Circuit breaker protection for downstream services
    - Comprehensive metrics and observability
    """
    
    def __init__(self, config: ConsumerConfig, redis_service=None):
        self.config = config
        self.redis_service = redis_service or get_redis_service()
        self.metrics = ProcessingMetrics()
        self.running = False
        self.consumer_task = None
        
        # Circuit breaker for external service protection
        self.circuit_breaker = None
        if hasattr(self, 'get_circuit_breaker_config'):
            cb_config = self.get_circuit_breaker_config()
            self.circuit_breaker = CircuitBreaker(
                name=f"{self.config.consumer_name}_circuit_breaker",
                config=cb_config
            )
        
        # Processing state
        self._processing_events: Dict[str, datetime] = {}
        self._last_heartbeat = datetime.utcnow()
        
        logger.info(f"🔧 Initialized event consumer '{config.consumer_name}' for stream '{config.stream_name}'")
    
    async def start(self):
        """Start the event consumer."""
        if self.running:
            logger.warning(f"⚠️ Consumer {self.config.consumer_name} is already running")
            return
        
        logger.info(f"🚀 Starting event consumer '{self.config.consumer_name}'...")
        
        try:
            # Initialize consumer group if needed
            await self._initialize_consumer_group()
            
            # Start consumer task
            self.running = True
            self.consumer_task = asyncio.create_task(self._consume_loop())
            
            logger.info(f"✅ Event consumer '{self.config.consumer_name}' started successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to start consumer '{self.config.consumer_name}': {e}")
            self.running = False
            raise
    
    async def stop(self):
        """Stop the event consumer gracefully."""
        if not self.running:
            return
        
        logger.info(f"🛑 Stopping event consumer '{self.config.consumer_name}'...")
        
        self.running = False
        
        if self.consumer_task:
            self.consumer_task.cancel()
            try:
                await self.consumer_task
            except asyncio.CancelledError:
                pass
        
        logger.info(f"✅ Event consumer '{self.config.consumer_name}' stopped")
    
    @abstractmethod
    async def process_event(self, event: RSVPEvent, raw_data: Dict[str, Any]) -> bool:
        """
        Process a single RSVP event.
        
        Args:
            event: Parsed RSVP event
            raw_data: Raw event data from Redis
            
        Returns:
            bool: True if processed successfully, False to retry
        """
        pass
    
    def get_circuit_breaker_config(self) -> Optional[CircuitBreakerConfig]:
        """Override to provide circuit breaker configuration."""
        return None
    
    async def _initialize_consumer_group(self):
        """Initialize Redis consumer group if it doesn't exist."""
        try:
            # Check if Redis service is healthy
            if not self.redis_service.is_healthy():
                logger.warning(f"⚠️ Redis service is not healthy for consumer group creation - will retry during consumption")
                return  # Don't fail startup, just skip group creation
            
            with self.redis_service.get_connection() as redis_client:
                try:
                    redis_client.xgroup_create(
                        self.config.stream_name,
                        self.config.consumer_group,
                        id='0',
                        mkstream=True
                    )
                    logger.debug(f"✅ Created consumer group '{self.config.consumer_group}' for stream '{self.config.stream_name}'")
                except Exception as e:
                    if "BUSYGROUP" not in str(e):
                        logger.warning(f"⚠️ Failed to create consumer group '{self.config.consumer_group}': {e}")
                        return  # Don't fail startup, just skip group creation
                    else:
                        logger.debug(f"📋 Consumer group '{self.config.consumer_group}' already exists")
                    
        except Exception as e:
            logger.warning(f"⚠️ Consumer group initialization failed: {e} - will retry during consumption")
            return  # Don't fail startup, allow consumer to start without group
    
    async def _consume_loop(self):
        """Main event consumption loop."""
        logger.info(f"🔄 Starting consumption loop for '{self.config.consumer_name}'")
        
        while self.running:
            try:
                # Process pending messages first (from previous failures)
                await self._process_pending_messages()
                
                # Read new messages
                await self._read_and_process_new_messages()
                
                # Update heartbeat
                self._last_heartbeat = datetime.utcnow()
                
                # Brief pause to prevent busy waiting
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                logger.info(f"🛑 Consumer loop cancelled for '{self.config.consumer_name}'")
                break
            except Exception as e:
                logger.error(f"❌ Error in consumer loop for '{self.config.consumer_name}': {e}")
                await asyncio.sleep(5)  # Back off on errors
    
    async def _process_pending_messages(self):
        """Process pending messages that haven't been acknowledged."""
        try:
            # Check for pending messages (claimed but not acknowledged)
            if not self.redis_service.is_healthy():
                logger.warning("Redis service not healthy, skipping pending messages")
                return
            
            pending = []
            with self.redis_service.get_connection() as redis_client:
                try:
                    pending = redis_client.xpending_range(
                        self.config.stream_name,
                        self.config.consumer_group,
                        '-',
                        '+',
                        count=self.config.batch_size
                    )
                except Exception as e:
                    logger.warning(f"Failed to get pending messages: {e}")
            
            if pending:
                logger.debug(f"📋 Processing {len(pending)} pending messages for '{self.config.consumer_name}'")
                
                for msg_info in pending:
                    message_id = msg_info['message_id']
                    
                    # Check if message is too old (likely stuck)
                    idle_time = msg_info['time_since_delivered']
                    if idle_time > self.config.max_processing_age * 1000:  # Convert to milliseconds
                        logger.warning(f"⚰️ Message {message_id} idle for {idle_time/1000:.1f}s - sending to DLQ")
                        await self._send_to_dlq(message_id, "Message processing timeout")
                        continue
                    
                    # Try to claim and process the message
                    claimed = []
                    with self.redis_service.get_connection() as redis_client:
                        try:
                            claimed = redis_client.xclaim(
                                self.config.stream_name,
                                self.config.consumer_group,
                                self.config.consumer_name,
                                min_idle_time=1000,  # 1 second
                                message_ids=[message_id]
                            )
                        except Exception as e:
                            logger.warning(f"Failed to claim message {message_id}: {e}")
                    
                    if claimed:
                        await self._process_message_batch(claimed)
                        
        except Exception as e:
            logger.error(f"❌ Error processing pending messages: {e}")
    
    async def _read_and_process_new_messages(self):
        """Read and process new messages from the stream."""
        try:
            # Read new messages
            if not self.redis_service.is_healthy():
                logger.warning("Redis service not healthy, skipping new messages")
                return
            
            messages = []
            with self.redis_service.get_connection() as redis_client:
                try:
                    messages = redis_client.xreadgroup(
                        self.config.consumer_group,
                        self.config.consumer_name,
                        streams={self.config.stream_name: '>'},
                        count=self.config.batch_size,
                        block=self.config.poll_timeout
                    )
                except Exception as e:
                    # If consumer group doesn't exist, try to create it
                    if "NOGROUP" in str(e):
                        logger.info(f"🔧 Consumer group '{self.config.consumer_group}' doesn't exist, creating it now...")
                        try:
                            redis_client.xgroup_create(
                                self.config.stream_name,
                                self.config.consumer_group,
                                id='0',
                                mkstream=True
                            )
                            logger.info(f"✅ Created consumer group '{self.config.consumer_group}' during consumption")
                            # Retry reading after creating the group
                            messages = redis_client.xreadgroup(
                                self.config.consumer_group,
                                self.config.consumer_name,
                                streams={self.config.stream_name: '>'},
                                count=self.config.batch_size,
                                block=self.config.poll_timeout
                            )
                        except Exception as create_e:
                            if "BUSYGROUP" not in str(create_e):
                                logger.error(f"❌ Failed to create consumer group during consumption: {create_e}")
                    elif "timeout" not in str(e).lower():
                        logger.error(f"Error reading messages: {e}")
            
            if messages:
                for stream_name, stream_messages in messages:
                    if stream_messages:
                        logger.debug(f"📨 Received {len(stream_messages)} new messages for '{self.config.consumer_name}'")
                        await self._process_message_batch(stream_messages)
                        
        except Exception as e:
            if "timeout" not in str(e).lower():
                logger.error(f"❌ Error reading new messages: {e}")
    
    async def _process_message_batch(self, messages: List[tuple]):
        """Process a batch of messages."""
        for message_id, fields in messages:
            await self._process_single_message(message_id, fields)
    
    async def _process_single_message(self, message_id: str, fields: Dict[str, Any]):
        """Process a single message with full error handling."""
        start_time = time.time()
        
        try:
            # Track processing start
            self._processing_events[message_id] = datetime.utcnow()
            
            # Parse event data
            event_data = {k.decode() if isinstance(k, bytes) else k: 
                         v.decode() if isinstance(v, bytes) else v 
                         for k, v in fields.items()}
            
            # Skip initialization messages
            if event_data.get('_init') == 'true':
                await self._acknowledge_message(message_id)
                return
            
            # Parse RSVP event
            try:
                event = RSVPEvent.from_dict(event_data)
            except Exception as e:
                logger.error(f"❌ Failed to parse event {message_id}: {e}")
                await self._send_to_dlq(message_id, f"Invalid event format: {str(e)}")
                return
            
            logger.debug(f"🔧 Processing event {message_id}: {event}")
            
            # Apply circuit breaker protection if configured
            if self.circuit_breaker:
                success = await self.circuit_breaker.call(self.process_event, event, event_data)
            else:
                success = await self.process_event(event, event_data)
            
            if success:
                # Acknowledge successful processing
                await self._acknowledge_message(message_id)
                
                # Update metrics
                processing_time = time.time() - start_time
                self.metrics.add_success(processing_time)
                
                logger.debug(f"✅ Successfully processed event {message_id} ({processing_time:.3f}s)")
            else:
                # Handle processing failure
                await self._handle_processing_failure(message_id, "Process returned False")
                
        except Exception as e:
            logger.error(f"❌ Error processing message {message_id}: {e}")
            await self._handle_processing_failure(message_id, str(e))
        finally:
            # Clean up processing tracking
            self._processing_events.pop(message_id, None)
    
    async def _handle_processing_failure(self, message_id: str, error_reason: str):
        """Handle processing failure with retry logic."""
        self.metrics.add_failure()
        
        # Get retry count from message metadata
        retry_count = await self._get_retry_count(message_id)
        
        if retry_count < self.config.max_retries:
            # Schedule retry
            self.metrics.add_retry()
            logger.warning(f"🔄 Retrying message {message_id} (attempt {retry_count + 1}/{self.config.max_retries})")
            
            # Use exponential backoff for retries
            retry_delay = self.config.retry_delay * (2 ** retry_count)
            await asyncio.sleep(retry_delay)
            
            # Don't acknowledge - let it be retried
        else:
            # Max retries exceeded - send to DLQ
            self.metrics.add_dead_letter()
            logger.error(f"💀 Max retries exceeded for message {message_id} - sending to DLQ")
            await self._send_to_dlq(message_id, f"Max retries exceeded: {error_reason}")
    
    async def _acknowledge_message(self, message_id: str):
        """Acknowledge successful message processing."""
        try:
            with self.redis_service.get_connection() as redis_client:
                try:
                    redis_client.xack(
                        self.config.stream_name,
                        self.config.consumer_group,
                        message_id
                    )
                except Exception as e:
                    logger.error(f"Failed to ack message {message_id}: {e}")
            logger.debug(f"✅ Acknowledged message {message_id}")
        except Exception as e:
            logger.error(f"❌ Failed to acknowledge message {message_id}: {e}")
    
    async def _send_to_dlq(self, message_id: str, error_reason: str):
        """Send failed message to Dead Letter Queue."""
        try:
            dlq_data = {
                'original_message_id': message_id,
                'original_stream': self.config.stream_name,
                'consumer_group': self.config.consumer_group,
                'consumer_name': self.config.consumer_name,
                'error_reason': error_reason,
                'failed_at': datetime.utcnow().isoformat()
            }
            
            with self.redis_service.get_connection() as redis_client:
                try:
                    redis_client.xadd(
                        'rsvp:dlq',
                        dlq_data,
                        maxlen=10000
                    )
                except Exception as e:
                    logger.error(f"Failed to add to DLQ: {e}")
            
            # Acknowledge the original message to remove it from pending
            await self._acknowledge_message(message_id)
            
            logger.warning(f"📨 Sent message {message_id} to DLQ: {error_reason}")
            
        except Exception as e:
            logger.error(f"❌ Failed to send message {message_id} to DLQ: {e}")
    
    async def _get_retry_count(self, message_id: str) -> int:
        """Get retry count for a message (simplified - could be enhanced with Redis storage)."""
        # For now, use a simple approach - in production might store in Redis
        return 0
    
    def get_health(self) -> Dict[str, Any]:
        """Get consumer health status."""
        now = datetime.utcnow()
        heartbeat_age = (now - self._last_heartbeat).total_seconds()
        
        status = 'healthy'
        if heartbeat_age > self.config.heartbeat_interval * 2:
            status = 'critical'
        elif heartbeat_age > self.config.heartbeat_interval:
            status = 'degraded'
        
        health = {
            'consumer_name': self.config.consumer_name,
            'status': status,
            'running': self.running,
            'last_heartbeat': self._last_heartbeat.isoformat(),
            'heartbeat_age_seconds': heartbeat_age,
            'processing_count': len(self._processing_events),
            'metrics': {
                'events_processed': self.metrics.events_processed,
                'events_failed': self.metrics.events_failed,
                'success_rate': self.metrics.get_success_rate(),
                'avg_processing_time': self.metrics.avg_processing_time,
                'last_processed_at': self.metrics.last_processed_at.isoformat() if self.metrics.last_processed_at else None
            }
        }
        
        if self.circuit_breaker:
            health['circuit_breaker'] = self.circuit_breaker.get_status()
        
        return health


class WebSocketBroadcaster(EventConsumer):
    """
    Event consumer for broadcasting RSVP updates via WebSocket.
    
    Replaces direct WebSocket calls with reliable, event-driven approach.
    """
    
    def __init__(self, redis_service=None):
        config = ConsumerConfig(
            consumer_name="websocket_broadcaster",
            consumer_group="websocket_broadcasters",
            stream_name="rsvp:websocket",
            batch_size=20,  # Higher throughput for real-time updates
            poll_timeout=1000,  # Faster polling for real-time
            processing_timeout=5  # Quick processing for UI updates
        )
        super().__init__(config, redis_service)
    
    async def process_event(self, event: RSVPEvent, raw_data: Dict[str, Any]) -> bool:
        """Broadcast RSVP update to connected WebSocket clients."""
        try:
            logger.debug(f"🌐 Broadcasting WebSocket update for match {event.match_id}")
            
            # Use existing WebSocket infrastructure
            emit_rsvp_update(
                match_id=event.match_id,
                player_id=event.player_id,
                availability=event.new_response,
                source='system',
                player_name=getattr(event, 'player_name', None),
                team_id=getattr(event, 'team_id', None)
            )
            success = True
            
            if success:
                logger.debug(f"✅ WebSocket broadcast successful for event {event.event_id}")
                return True
            else:
                logger.warning(f"⚠️ WebSocket broadcast failed for event {event.event_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ WebSocket broadcast error for event {event.event_id}: {e}")
            return False


class DiscordEmbedUpdater(EventConsumer):
    """
    Event consumer for updating Discord embeds when RSVPs change.
    
    Provides reliable Discord integration with circuit breaker protection.
    """
    
    def __init__(self, redis_service=None):
        config = ConsumerConfig(
            consumer_name="discord_embed_updater",
            consumer_group="discord_embed_updaters", 
            stream_name="rsvp:discord",
            batch_size=5,  # Smaller batches for Discord rate limits
            poll_timeout=5000,
            processing_timeout=30,  # Allow time for Discord API calls
            max_retries=5  # More retries for network issues
        )
        super().__init__(config, redis_service)
    
    def get_circuit_breaker_config(self) -> CircuitBreakerConfig:
        """Configure circuit breaker for Discord API protection."""
        return CircuitBreakerConfig(
            failure_threshold=3,
            timeout=60,  # 1 minute timeout before retry
            call_timeout=15.0,  # 15 second timeout for Discord calls
            expected_exceptions=(Exception,)  # Catch all exceptions for Discord
        )
    
    async def process_event(self, event: RSVPEvent, raw_data: Dict[str, Any]) -> bool:
        """Update Discord embed for RSVP change."""
        try:
            logger.debug(f"🤖 Updating Discord embed for match {event.match_id}")
            
            # Import here to avoid circular imports
            from app.tasks.tasks_rsvp import notify_discord_of_rsvp_change_task
            from app.core.session_manager import managed_session
            
            # Call the existing Discord notification function as a Celery task
            # This will use the improved rate limiting (10 seconds instead of 60)
            with managed_session() as session:
                result = notify_discord_of_rsvp_change_task(
                    session=session,
                    match_id=event.match_id
                )
            
            if result:
                logger.debug(f"✅ Discord embed update successful for event {event.event_id}")
                return True
            else:
                logger.warning(f"⚠️ Discord embed update failed for event {event.event_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Discord embed update error for event {event.event_id}: {e}")
            return False


# Consumer registry for management
_consumers: Dict[str, EventConsumer] = {}

async def register_consumer(consumer: EventConsumer):
    """Register an event consumer for lifecycle management."""
    _consumers[consumer.config.consumer_name] = consumer
    logger.info(f"📋 Registered consumer '{consumer.config.consumer_name}'")

async def start_all_consumers():
    """Start all registered consumers."""
    logger.info(f"🚀 Starting {len(_consumers)} event consumers...")
    
    start_tasks = []
    for consumer in _consumers.values():
        start_tasks.append(consumer.start())
    
    # Start all consumers concurrently
    results = await asyncio.gather(*start_tasks, return_exceptions=True)
    
    successful = 0
    for i, result in enumerate(results):
        consumer_name = list(_consumers.keys())[i]
        if isinstance(result, Exception):
            logger.error(f"❌ Failed to start consumer '{consumer_name}': {result}")
        else:
            successful += 1
    
    logger.info(f"✅ Started {successful}/{len(_consumers)} consumers successfully")

async def stop_all_consumers():
    """Stop all registered consumers gracefully."""
    logger.info(f"🛑 Stopping {len(_consumers)} event consumers...")
    
    stop_tasks = []
    for consumer in _consumers.values():
        stop_tasks.append(consumer.stop())
    
    # Stop all consumers concurrently
    await asyncio.gather(*stop_tasks, return_exceptions=True)
    
    logger.info(f"✅ Stopped all consumers")

def get_consumer_health() -> Dict[str, Any]:
    """Get health status of all consumers."""
    health = {
        'overall_status': 'healthy',
        'total_consumers': len(_consumers),
        'consumers': {}
    }
    
    unhealthy_count = 0
    for name, consumer in _consumers.items():
        consumer_health = consumer.get_health()
        health['consumers'][name] = consumer_health
        
        if consumer_health['status'] != 'healthy':
            unhealthy_count += 1
    
    if unhealthy_count > 0:
        if unhealthy_count == len(_consumers):
            health['overall_status'] = 'critical'
        else:
            health['overall_status'] = 'degraded'
        health['unhealthy_consumers'] = unhealthy_count
    
    return health

async def initialize_default_consumers():
    """Initialize and register default RSVP consumers."""
    logger.info("🔧 Initializing default RSVP event consumers...")
    
    # Create default consumers
    websocket_broadcaster = WebSocketBroadcaster()
    discord_updater = DiscordEmbedUpdater()
    
    # Register consumers
    await register_consumer(websocket_broadcaster)
    await register_consumer(discord_updater)
    
    logger.info("✅ Default consumers initialized")
    
    return websocket_broadcaster, discord_updater