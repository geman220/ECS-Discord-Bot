# app/discord_websocket_client.py

"""
Discord Bot WebSocket Client

This module allows the Discord bot to connect to the Flask app's WebSocket
server to receive real-time RSVP updates. This creates a bidirectional
communication channel where:

1. Discord bot → Flask: Via REST API (existing)
2. Flask → Discord bot: Via WebSocket (new)

This ensures all RSVP changes are synchronized across all platforms.
"""

import asyncio
import logging
import socketio
from typing import Dict, List, Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)


class DiscordWebSocketClient:
    """
    WebSocket client for Discord bot to receive real-time RSVP updates.
    
    This client connects to the Flask Socket.IO server and listens for
    RSVP updates to keep Discord messages in sync.
    """
    
    def __init__(self, flask_url: str = 'http://webui:5000', api_key: str = None):
        """
        Initialize the Discord WebSocket client.
        
        Args:
            flask_url: URL of the Flask Socket.IO server
            api_key: API key for authentication
        """
        self.flask_url = flask_url
        self.api_key = api_key or 'discord-bot-internal-key'
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,  # Infinite attempts
            reconnection_delay=1,
            reconnection_delay_max=30,
            logger=logger
        )
        self.connected = False
        self.active_matches: Dict[int, Dict] = {}  # Track active match rooms
        
        # Callbacks
        self.on_rsvp_update: Optional[Callable] = None
        self.on_rsvp_summary: Optional[Callable] = None
        
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Set up Socket.IO event handlers."""
        
        @self.sio.on('connect')
        async def on_connect():
            self.connected = True
            logger.info("✅ Discord bot connected to Flask WebSocket server")
            
            # Rejoin all active match rooms after reconnection
            if self.active_matches:
                logger.info(f"Rejoining {len(self.active_matches)} active match rooms")
                for match_id in list(self.active_matches.keys()):
                    await self.join_match(match_id)
        
        @self.sio.on('disconnect')
        async def on_disconnect():
            self.connected = False
            logger.warning("❌ Discord bot disconnected from Flask WebSocket server")
        
        @self.sio.on('error')
        async def on_error(data):
            logger.error(f"WebSocket error: {data}")
        
        @self.sio.on('authentication_success')
        async def on_auth_success(data):
            logger.info(f"🔐 Authentication successful: {data.get('message')}")
        
        @self.sio.on('authentication_failed')
        async def on_auth_failed(data):
            logger.error(f"🔐 Authentication failed: {data.get('error')}")
        
        @self.sio.on('joined_match_rsvp')
        async def on_joined_match(data):
            match_id = data.get('match_id')
            logger.info(f"📊 Joined match {match_id} RSVP room")
            
            # Store match info
            self.active_matches[match_id] = {
                'joined_at': datetime.utcnow(),
                'match_info': data.get('match_info'),
                'current_rsvps': data.get('current_rsvps')
            }
        
        @self.sio.on('rsvp_update')
        async def on_rsvp_update(data):
            """Handle RSVP update events."""
            match_id = data.get('match_id')
            player_id = data.get('player_id')
            availability = data.get('availability')
            source = data.get('source')
            player_name = data.get('player_name')
            
            logger.info(f"📨 RSVP Update: Match {match_id}, {player_name} -> {availability} (source: {source})")
            
            # Don't process our own updates to avoid loops
            if source == 'discord':
                logger.debug("Ignoring Discord-sourced update to avoid loops")
                return
            
            # Call the callback if registered
            if self.on_rsvp_update:
                try:
                    await self.on_rsvp_update(data)
                except Exception as e:
                    logger.error(f"Error in RSVP update callback: {str(e)}", exc_info=True)
        
        @self.sio.on('rsvp_summary')
        async def on_rsvp_summary(data):
            """Handle RSVP summary updates."""
            match_id = data.get('match_id')
            counts = data.get('rsvp_counts', {})
            
            logger.debug(f"📊 RSVP Summary: Match {match_id}, Counts: {counts}")
            
            # Update our cache
            if match_id in self.active_matches:
                self.active_matches[match_id]['last_summary'] = counts
            
            # Call the callback if registered
            if self.on_rsvp_summary:
                try:
                    await self.on_rsvp_summary(data)
                except Exception as e:
                    logger.error(f"Error in RSVP summary callback: {str(e)}", exc_info=True)
    
    async def connect(self):
        """Connect to the Flask Socket.IO server."""
        try:
            logger.info(f"🔌 Connecting to Flask WebSocket at {self.flask_url}")
            
            await self.sio.connect(
                self.flask_url,
                headers={
                    'X-API-Key': self.api_key,
                    'User-Agent': 'Discord-Bot-WebSocket-Client/1.0'
                },
                transports=['websocket'],  # Prefer WebSocket over polling
                auth={
                    'type': 'discord-bot',
                    'api_key': self.api_key
                }
            )
            
            # Wait a bit to ensure connection is established
            await asyncio.sleep(0.5)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Flask WebSocket: {str(e)}", exc_info=True)
            return False
    
    async def disconnect(self):
        """Disconnect from the Flask Socket.IO server."""
        try:
            if self.connected:
                logger.info("🔌 Disconnecting from Flask WebSocket")
                await self.sio.disconnect()
                self.connected = False
                self.active_matches.clear()
        except Exception as e:
            logger.error(f"Error disconnecting: {str(e)}", exc_info=True)
    
    async def join_match(self, match_id: int, team_id: Optional[int] = None):
        """
        Join a match room to receive RSVP updates.
        
        Args:
            match_id: ID of the match to join
            team_id: Optional team ID for filtering
        """
        if not self.connected:
            logger.warning(f"Cannot join match {match_id} - not connected")
            return False
        
        try:
            logger.info(f"🏠 Joining match {match_id} RSVP room")
            
            await self.sio.emit('join_match_rsvp', {
                'match_id': match_id,
                'team_id': team_id
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Error joining match {match_id}: {str(e)}", exc_info=True)
            return False
    
    async def leave_match(self, match_id: int):
        """
        Leave a match room.
        
        Args:
            match_id: ID of the match to leave
        """
        if not self.connected:
            return
        
        try:
            logger.info(f"👋 Leaving match {match_id} RSVP room")
            
            await self.sio.emit('leave_match_rsvp', {
                'match_id': match_id
            })
            
            # Remove from active matches
            self.active_matches.pop(match_id, None)
            
        except Exception as e:
            logger.error(f"Error leaving match {match_id}: {str(e)}", exc_info=True)
    
    async def join_active_matches(self, match_ids: List[int]):
        """
        Join multiple match rooms at once.
        
        Args:
            match_ids: List of match IDs to join
        """
        logger.info(f"📊 Joining {len(match_ids)} active match rooms")
        
        tasks = [self.join_match(match_id) for match_id in match_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is True)
        logger.info(f"✅ Successfully joined {success_count}/{len(match_ids)} match rooms")
    
    async def get_match_rsvps(self, match_id: int, team_id: Optional[int] = None):
        """
        Get current RSVPs for a match via WebSocket.
        
        Args:
            match_id: ID of the match
            team_id: Optional team ID for filtering
            
        Returns:
            Dict with RSVP data or None if failed
        """
        if not self.connected:
            logger.warning("Cannot get match RSVPs - not connected")
            return None
        
        try:
            # Create a future to wait for response
            response_future = asyncio.Future()
            
            # Handler for the response
            @self.sio.on('match_rsvps_data')
            async def on_rsvps_data(data):
                if data.get('match_id') == match_id:
                    response_future.set_result(data.get('rsvps'))
            
            # Request the data
            await self.sio.emit('get_match_rsvps_live', {
                'match_id': match_id,
                'team_id': team_id,
                'include_details': True
            })
            
            # Wait for response with timeout
            try:
                rsvps = await asyncio.wait_for(response_future, timeout=5.0)
                return rsvps
            except asyncio.TimeoutError:
                logger.error(f"Timeout getting RSVPs for match {match_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting match RSVPs: {str(e)}", exc_info=True)
            return None
    
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self.connected
    
    def get_active_matches(self) -> List[int]:
        """Get list of currently joined match IDs."""
        return list(self.active_matches.keys())


# Example usage in Discord bot
async def setup_websocket_client(bot_instance):
    """
    Set up WebSocket client for a Discord bot instance.
    
    Args:
        bot_instance: The Discord bot instance
    """
    # Create client
    client = DiscordWebSocketClient(
        flask_url='http://webui:5000',
        api_key='discord-bot-key'
    )
    
    # Register callback for RSVP updates
    async def handle_rsvp_update(data):
        match_id = data['match_id']
        player_name = data.get('player_name', 'Unknown')
        availability = data['availability']
        source = data['source']
        
        logger.info(f"Received RSVP update from {source}: {player_name} -> {availability}")
        
        # Update Discord embed for this match
        try:
            await bot_instance.update_match_rsvp_embed(match_id)
        except Exception as e:
            logger.error(f"Failed to update Discord embed: {str(e)}")
    
    client.on_rsvp_update = handle_rsvp_update
    
    # Connect
    if await client.connect():
        # Get active matches from database
        active_match_ids = await bot_instance.get_active_match_ids()
        
        # Join all active match rooms
        await client.join_active_matches(active_match_ids)
        
        logger.info(f"✅ Discord WebSocket client ready, monitoring {len(active_match_ids)} matches")
    
    return client


if __name__ == "__main__":
    # Test the client
    async def test_client():
        client = DiscordWebSocketClient()
        
        # Set up test handlers
        async def test_rsvp_handler(data):
            print(f"RSVP Update: {data}")
        
        client.on_rsvp_update = test_rsvp_handler
        
        # Connect and join a test match
        if await client.connect():
            await client.join_match(123)
            
            # Keep running for 60 seconds
            await asyncio.sleep(60)
            
            await client.disconnect()
    
    # Run test
    asyncio.run(test_client())