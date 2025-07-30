# websocket_rsvp_manager.py

"""
Discord Bot WebSocket RSVP Manager

This module manages the WebSocket connection between the Discord bot and Flask app
for real-time RSVP synchronization. It runs in parallel with the existing REST API
system to provide dual validation and logging.
"""

import asyncio
import logging
import socketio
import aiohttp
from typing import Dict, List, Optional, Callable
from datetime import datetime
import json
import os
from shared_states import get_bot_instance

logger = logging.getLogger(__name__)

class DiscordRSVPWebSocketManager:
    """
    Manages WebSocket connection to Flask for real-time RSVP updates.
    
    This runs alongside the existing REST API system to:
    1. Provide real-time updates when players RSVP via mobile/web
    2. Log all RSVP changes for validation
    3. Eventually replace the complex polling system
    """
    
    def __init__(self, flask_url: str = None, api_key: str = None):
        """Initialize the WebSocket manager."""
        self.flask_url = flask_url or os.getenv('WEBUI_API_URL', 'http://webui:5000')
        self.api_key = api_key or os.getenv('DISCORD_BOT_API_KEY', 'discord-bot-internal-key')
        
        # Socket.IO client
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,  # Infinite attempts
            reconnection_delay=1,
            reconnection_delay_max=30,
            logger=False  # Disable socket.io logging to avoid spam
        )
        
        # Connection state
        self.connected = False
        self.connection_task = None
        self.active_matches: Dict[int, Dict] = {}
        self.rsvp_events_log: List[Dict] = []  # Log all RSVP events for validation
        
        # Stats for logging
        self.events_received = 0
        self.events_processed = 0
        self.connection_attempts = 0
        self.last_event_time = None
        
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Set up Socket.IO event handlers."""
        
        @self.sio.on('connect')
        async def on_connect():
            self.connected = True
            self.connection_attempts += 1
            logger.info(f"🔗 Discord bot connected to Flask WebSocket (attempt #{self.connection_attempts})")
            
            # Join all active match rooms after connection
            await self._rejoin_active_matches()
        
        @self.sio.on('disconnect')
        async def on_disconnect():
            self.connected = False
            logger.warning("❌ Discord bot disconnected from Flask WebSocket")
        
        @self.sio.on('connect_error')
        async def on_connect_error(data):
            logger.error(f"🔗 WebSocket connection error: {data}")
        
        @self.sio.on('authentication_success')
        async def on_auth_success(data):
            logger.info(f"🔐 WebSocket authentication successful: {data.get('message', 'OK')}")
        
        @self.sio.on('authentication_failed')
        async def on_auth_failed(data):
            logger.error(f"🔐 WebSocket authentication failed: {data.get('error', 'Unknown error')}")
        
        @self.sio.on('joined_match_rsvp')
        async def on_joined_match(data):
            match_id = data.get('match_id')
            current_rsvps = data.get('current_rsvps', {})
            summary = current_rsvps.get('summary', {})
            
            logger.info(f"📊 [MATCH {match_id}] Joined WebSocket room - Current RSVPs: "
                       f"Yes={summary.get('yes_count', 0)}, No={summary.get('no_count', 0)}, "
                       f"Maybe={summary.get('maybe_count', 0)}")
            
            # Store match info
            self.active_matches[match_id] = {
                'joined_at': datetime.utcnow(),
                'match_info': data.get('match_info'),
                'current_rsvps': current_rsvps,
                'websocket_events': 0
            }
        
        @self.sio.on('rsvp_update')
        async def on_rsvp_update(data):
            """Handle RSVP update events - the main event handler."""
            await self._handle_rsvp_update(data)
        
        @self.sio.on('rsvp_summary')
        async def on_rsvp_summary(data):
            """Handle RSVP summary updates."""
            match_id = data.get('match_id')
            counts = data.get('rsvp_counts', {})
            
            logger.info(f"📊 [MATCH {match_id}] RSVP Summary Update - "
                       f"Yes={counts.get('yes', 0)}, No={counts.get('no', 0)}, Maybe={counts.get('maybe', 0)}")
            
            # Update stats
            if match_id in self.active_matches:
                self.active_matches[match_id]['last_summary'] = counts
    
    async def _handle_rsvp_update(self, data):
        """
        Handle incoming RSVP updates from WebSocket.
        
        This is where we log events and potentially update Discord embeds.
        """
        self.events_received += 1
        self.last_event_time = datetime.utcnow()
        
        match_id = data.get('match_id')
        player_id = data.get('player_id')
        player_name = data.get('player_name', 'Unknown Player')
        availability = data.get('availability')
        source = data.get('source')
        timestamp = data.get('timestamp')
        team_id = data.get('team_id')
        
        # Log the event for validation
        event_log = {
            'timestamp': timestamp,
            'received_at': datetime.utcnow().isoformat(),
            'match_id': match_id,
            'player_id': player_id,
            'player_name': player_name,
            'availability': availability,
            'source': source,
            'team_id': team_id
        }
        self.rsvp_events_log.append(event_log)
        
        # Keep only last 1000 events to prevent memory bloat
        if len(self.rsvp_events_log) > 1000:
            self.rsvp_events_log = self.rsvp_events_log[-1000:]
        
        # DYNAMIC AUTO-JOINING: If this is a new match, join its room automatically
        if match_id not in self.active_matches:
            logger.info(f"🔄 [MATCH {match_id}] New match detected - auto-joining WebSocket room")
            await self.join_match(match_id, team_id)
            
            self.active_matches[match_id] = {
                'last_updated': datetime.utcnow(),
                'rsvp_count': 0,
                'websocket_events': 0,
                'auto_joined': True,  # Track that this was auto-joined
                'first_joined': datetime.utcnow()  # Track when we first joined
            }
            
            # Trigger cleanup of old rooms to prevent bloat
            await self._cleanup_old_rooms()
        
        # Update match stats
        self.active_matches[match_id]['last_updated'] = datetime.utcnow()
        self.active_matches[match_id]['rsvp_count'] += 1
        self.active_matches[match_id]['websocket_events'] += 1
        
        # Log the event with detailed info
        logger.info(f"📨 [MATCH {match_id}] WebSocket RSVP: {player_name} -> {availability} "
                   f"(source: {source}, player_id: {player_id}, team_id: {team_id})")
        
        # Don't process our own updates to avoid loops
        if source == 'discord':
            logger.debug(f"⏭️  [MATCH {match_id}] Ignoring Discord-sourced update to prevent loops")
            return
        
        # Here's where we would update Discord embeds
        # For now, we'll just log it for validation
        try:
            await self._update_discord_embed_for_match(match_id, event_log)
            self.events_processed += 1
        except Exception as e:
            logger.error(f"❌ Error updating Discord embed for match {match_id}: {str(e)}")
    
    async def _update_discord_embed_for_match(self, match_id: int, event_log: Dict):
        """
        Update Discord embed for a match when RSVP changes.
        
        This integrates with the existing Discord bot embed system.
        """
        try:
            bot = get_bot_instance()
            if not bot:
                logger.debug(f"🤖 Bot instance not available for match {match_id} embed update")
                return
            
            # Use existing embed update logic
            from api.utils.rsvp_utils import update_embed_for_message
            
            # Get message IDs for this match (you'll need to implement this)
            message_ids = await self._get_message_ids_for_match(match_id)
            
            if not message_ids:
                logger.debug(f"📨 No Discord messages found for match {match_id}")
                return
            
            # Update embeds for all messages related to this match
            updated_count = 0
            for message_id in message_ids:
                try:
                    success = await update_embed_for_message(message_id)
                    if success:
                        updated_count += 1
                except Exception as e:
                    logger.error(f"❌ Failed to update embed for message {message_id}: {str(e)}")
            
            if updated_count > 0:
                logger.info(f"✅ [MATCH {match_id}] Updated {updated_count} Discord embeds after "
                           f"{event_log.get('player_name')} -> {event_log.get('availability')}")
            
        except Exception as e:
            logger.error(f"❌ Error in _update_discord_embed_for_match: {str(e)}", exc_info=True)
    
    async def _get_message_ids_for_match(self, match_id: int) -> List[str]:
        """
        Get Discord message IDs for a match.
        
        This would integrate with your existing message tracking system.
        """
        try:
            # This should integrate with your existing system
            # For now, return empty list - you'll need to implement this
            # based on how you currently track Discord messages
            return []
        except Exception as e:
            logger.error(f"Error getting message IDs for match {match_id}: {str(e)}")
            return []
    
    async def connect(self):
        """Connect to the Flask WebSocket server."""
        if self.connected:
            logger.debug("Already connected to WebSocket")
            return True
        
        try:
            logger.info(f"🔌 Connecting Discord bot to Flask WebSocket at {self.flask_url}")
            
            await self.sio.connect(
                self.flask_url,
                headers={
                    'X-API-Key': self.api_key,
                    'User-Agent': 'Discord-Bot-WebSocket-Client/1.0'
                },
                transports=['websocket'],
                auth={
                    'type': 'discord-bot',
                    'api_key': self.api_key
                }
            )
            
            # Wait for connection to establish
            await asyncio.sleep(1)
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Flask WebSocket: {str(e)}")
            return False
    
    async def disconnect(self):
        """Disconnect from WebSocket server."""
        if self.connected:
            logger.info("🔌 Disconnecting from Flask WebSocket")
            await self.sio.disconnect()
            self.connected = False
            self.active_matches.clear()
    
    async def join_match(self, match_id: int, team_id: Optional[int] = None):
        """Join a match room to receive RSVP updates."""
        if not self.connected:
            logger.warning(f"Cannot join match {match_id} - WebSocket not connected")
            return False
        
        try:
            logger.info(f"📊 [MATCH {match_id}] Joining WebSocket RSVP room")
            
            await self.sio.emit('join_match_rsvp', {
                'match_id': match_id,
                'team_id': team_id
            })
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error joining match {match_id}: {str(e)}")
            return False
    
    async def join_active_matches(self, match_ids: List[int]):
        """Join multiple match rooms at once."""
        if not self.connected:
            logger.warning("Cannot join matches - WebSocket not connected")
            return
        
        logger.info(f"📊 Joining {len(match_ids)} active match WebSocket rooms")
        
        success_count = 0
        for match_id in match_ids:
            if await self.join_match(match_id):
                success_count += 1
        
        logger.info(f"✅ Successfully joined {success_count}/{len(match_ids)} match WebSocket rooms")
    
    async def _rejoin_active_matches(self):
        """Rejoin all active matches after reconnection."""
        if self.active_matches:
            match_ids = list(self.active_matches.keys())
            logger.info(f"🔄 Rejoining {len(match_ids)} match rooms after reconnection")
            await self.join_active_matches(match_ids)
    
    async def start_connection_manager(self):
        """Start the connection manager as a background task."""
        if self.connection_task:
            logger.debug("Connection manager already running")
            return
        
        self.connection_task = asyncio.create_task(self._connection_manager_loop())
        logger.info("🚀 Started WebSocket connection manager")
    
    async def _connection_manager_loop(self):
        """Background task to manage WebSocket connection."""
        while True:
            try:
                if not self.connected:
                    logger.info("🔄 Attempting to connect/reconnect to Flask WebSocket")
                    await self.connect()
                
                # Wait before next check
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except asyncio.CancelledError:
                logger.info("🛑 Connection manager cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in connection manager: {str(e)}")
                await asyncio.sleep(10)  # Wait before retrying
    
    def get_stats(self) -> Dict:
        """Get statistics about WebSocket operations."""
        return {
            'connected': self.connected,
            'connection_attempts': self.connection_attempts,
            'events_received': self.events_received,
            'events_processed': self.events_processed,
            'active_matches': len(self.active_matches),
            'last_event_time': self.last_event_time.isoformat() if self.last_event_time else None,
            'total_logged_events': len(self.rsvp_events_log)
        }
    
    def get_recent_events(self, limit: int = 50) -> List[Dict]:
        """Get recent RSVP events for logging/debugging."""
        return self.rsvp_events_log[-limit:] if self.rsvp_events_log else []
    
    async def stop(self):
        """Stop the WebSocket manager."""
        if self.connection_task:
            self.connection_task.cancel()
            try:
                await self.connection_task
            except asyncio.CancelledError:
                pass
        
        await self.disconnect()
        logger.info("🛑 WebSocket RSVP manager stopped")
    
    async def _cleanup_old_rooms(self):
        """
        Clean up WebSocket rooms for old matches to prevent memory bloat.
        
        Rules:
        - Remove matches older than 3 days (likely finished)
        - Keep matches with recent activity (last 24 hours)
        - Limit total rooms to 20 matches max
        """
        try:
            if not self.active_matches:
                return
                
            now = datetime.utcnow()
            rooms_to_remove = []
            
            # Find matches that are old and inactive
            for match_id, match_data in self.active_matches.items():
                last_updated = match_data.get('last_updated', now)
                days_old = (now - last_updated).days
                
                # MASTER KILL: Force remove after 10 days no matter what
                days_since_joined = (now - match_data.get('first_joined', now)).days
                
                # Remove if:
                # 1. No activity in 7+ days (next RSVP cycle)
                # 2. MASTER KILL: 10+ days old regardless of activity
                if days_old >= 7 or days_since_joined >= 10:
                    if days_since_joined >= 10:
                        logger.info(f"🔥 [MATCH {match_id}] MASTER KILL - removing room after 10 days")
                    rooms_to_remove.append(match_id)
            
            # Also enforce max room limit (keep most recent 50)
            # With 24 matches/week × 2 weeks = 48 max expected, 50 gives buffer
            if len(self.active_matches) > 50:
                # Sort by last_updated, keep newest 50
                sorted_matches = sorted(
                    self.active_matches.items(),
                    key=lambda x: x[1].get('last_updated', datetime.min),
                    reverse=True
                )
                
                # Mark oldest matches for removal
                for match_id, _ in sorted_matches[50:]:
                    if match_id not in rooms_to_remove:
                        rooms_to_remove.append(match_id)
            
            # Remove old rooms
            for match_id in rooms_to_remove:
                try:
                    await self.sio.emit('leave_match_rsvp', {'match_id': match_id})
                    del self.active_matches[match_id]
                    logger.info(f"🧹 [MATCH {match_id}] Left WebSocket room (cleanup)")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to leave room for match {match_id}: {str(e)}")
            
            if rooms_to_remove:
                remaining = len(self.active_matches)
                logger.info(f"🧹 Cleaned up {len(rooms_to_remove)} old WebSocket rooms, {remaining} remaining")
                
        except Exception as e:
            logger.error(f"❌ Error during room cleanup: {str(e)}")
    
    async def join_match_on_rsvp_post(self, match_id: int):
        """
        Join WebSocket room when Discord RSVP message is posted.
        
        This is called after successfully posting an RSVP message to Discord,
        whether via scheduled automation or manual "force send".
        
        Args:
            match_id: The match ID that just had an RSVP message posted
        """
        try:
            if not self.connected:
                logger.warning(f"⚠️ [MATCH {match_id}] Cannot join room - WebSocket not connected")
                return False
                
            # Join the room for this match
            success = await self.join_match(match_id)
            
            if success:
                # Track this match with 7-day lifecycle
                self.active_matches[match_id] = {
                    'last_updated': datetime.utcnow(),
                    'rsvp_count': 0,
                    'websocket_events': 0,
                    'rsvp_message_posted': True,  # Mark that RSVP message was posted
                    'first_joined': datetime.utcnow()
                }
                
                logger.info(f"✅ [MATCH {match_id}] Joined WebSocket room after RSVP message posted")
                
                # Trigger cleanup to maintain room limits
                await self._cleanup_old_rooms()
                
                return True
            else:
                logger.error(f"❌ [MATCH {match_id}] Failed to join WebSocket room after RSVP message posted")
                return False
                
        except Exception as e:
            logger.error(f"❌ [MATCH {match_id}] Error joining room after RSVP post: {str(e)}")
            return False


# Global instance
_websocket_manager = None

def get_websocket_manager() -> Optional[DiscordRSVPWebSocketManager]:
    """Get the global WebSocket manager instance."""
    return _websocket_manager

async def initialize_websocket_manager(flask_url: str = None, api_key: str = None) -> DiscordRSVPWebSocketManager:
    """Initialize the global WebSocket manager."""
    global _websocket_manager
    
    if _websocket_manager:
        logger.info("WebSocket manager already initialized")
        return _websocket_manager
    
    logger.info("🚀 Initializing Discord bot WebSocket RSVP manager")
    
    _websocket_manager = DiscordRSVPWebSocketManager(flask_url, api_key)
    
    # Start the connection manager
    await _websocket_manager.start_connection_manager()
    
    logger.info("✅ Discord bot WebSocket RSVP manager initialized")
    return _websocket_manager

async def shutdown_websocket_manager():
    """Shutdown the global WebSocket manager."""
    global _websocket_manager
    
    if _websocket_manager:
        await _websocket_manager.stop()
        _websocket_manager = None
        logger.info("🛑 WebSocket manager shutdown complete")