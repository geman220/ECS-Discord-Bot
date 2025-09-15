# smart_rsvp_sync_manager.py

"""
Container-Down-Resilient RSVP Sync Manager

This handles sync scenarios where the entire bot container goes down,
not just WebSocket disconnections. Uses database persistence to track
state across container restarts.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Any
import aiohttp

logger = logging.getLogger(__name__)

class ContainerResilientSyncManager:
    """
    Handles RSVP synchronization that works even when the entire bot container goes down.
    
    Key features:
    - Persists "last online" timestamp in database
    - Uses Flask-side tracking of RSVP message posting times
    - Only syncs matches that were active during potential downtime
    - Dramatically reduces API calls compared to "sync everything" approach
    """
    
    def __init__(self, flask_url: str = None):
        self.flask_url = flask_url or "http://webui:5000"
        self.bot_instance_id = f"discord-bot-{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
    async def on_bot_startup(self):
        """
        Called when bot starts up - determines if sync is needed.
        
        This works by:
        1. Getting our last known online time from database
        2. Getting matches that had RSVP messages posted since then
        3. Only syncing those specific matches
        """
        try:
            logger.info("🚀 Bot startup - checking if RSVP sync needed")
            
            # Get our last known online time from Flask database
            last_online_time = await self._get_last_online_time()
            
            if not last_online_time:
                logger.info("⭐ First startup or no previous online time - performing full sync")
                await self._perform_startup_sync(is_first_startup=True)
            else:
                # Ensure both datetimes are timezone-aware for comparison
                from datetime import timezone
                current_time = datetime.now(timezone.utc)

                # If last_online_time is naive, assume it's UTC
                if last_online_time.tzinfo is None:
                    last_online_time = last_online_time.replace(tzinfo=timezone.utc)

                offline_duration = current_time - last_online_time
                logger.info(f"📅 Last online: {last_online_time}, offline for: {offline_duration}")
                
                if offline_duration.total_seconds() > 300:  # Only if offline > 5 minutes
                    await self._perform_targeted_sync(since=last_online_time)
                else:
                    logger.info("⏩ Short downtime - skipping sync")
            
            # Update our online timestamp
            await self._update_last_online_time()
            
        except Exception as e:
            logger.error(f"❌ Error during startup sync check: {str(e)}")
            # Fallback to basic sync if our smart approach fails
            await self._perform_startup_sync(is_first_startup=False)
    
    async def _perform_targeted_sync_with_conflict_resolution(self, last_online_time: datetime):
        """
        Perform targeted sync with enterprise conflict resolution.
        
        For each active match during downtime:
        1. Get Discord current state (reactions)
        2. Get Database current state  
        3. Get Mobile cached state (if any)
        4. Resolve conflicts using enterprise strategy
        5. Apply resolved state to all systems
        """
        try:
            logger.info(f"🔀 Starting targeted sync with conflict resolution since {last_online_time}")
            
            # Get matches that were active during our downtime
            active_matches = await self._get_matches_with_activity_since(last_online_time)
            
            if not active_matches:
                logger.info("✅ No matches had activity during downtime - no conflicts to resolve")
                return
            
            logger.info(f"🎯 Found {len(active_matches)} matches to check for conflicts")
            
            # Import conflict resolver
            import sys
            sys.path.append('/app')
            from app.services.conflict_resolver import create_conflict_resolver
            
            downtime_duration = datetime.utcnow() - last_online_time
            resolver = await create_conflict_resolver(downtime_duration)
            
            resolved_count = 0
            conflict_count = 0
            
            for match_info in active_matches:
                try:
                    match_id = match_info.get('match_id')
                    logger.info(f"🔍 Checking match {match_id} for RSVP conflicts")
                    
                    # Get all users who might have conflicts for this match
                    conflicted_users = await self._get_users_with_potential_conflicts(
                        match_id, last_online_time
                    )
                    
                    for user_info in conflicted_users:
                        discord_id = user_info.get('discord_id')
                        
                        # Get states from all sources
                        discord_state = await self._get_discord_reaction_state(match_id, discord_id)
                        database_state = await self._get_database_rsvp_state(match_id, discord_id)
                        mobile_state = None  # Would be retrieved from mobile sync cache if available
                        
                        # Resolve conflict
                        resolution = await resolver.resolve_rsvp_conflict(
                            discord_state=discord_state,
                            database_state=database_state,
                            mobile_state=mobile_state,
                            downtime_start=last_online_time,
                            trace_id=f"sync_{match_id}_{discord_id}"
                        )
                        
                        # Apply resolution if there was a conflict
                        if len(resolution.conflicting_states) > 1:
                            conflict_count += 1
                            logger.warning(f"⚠️ Conflict resolved for user {discord_id} on match {match_id}: "
                                         f"{resolution.chosen_source.value} -> {resolution.resolved_response}")
                            
                            # Apply the resolution (this would update database, Discord, WebSocket)
                            success = await self._apply_conflict_resolution(resolution, match_id, discord_id)
                            if success:
                                resolved_count += 1
                        
                except Exception as e:
                    logger.error(f"❌ Error processing match {match_id} for conflicts: {e}")
                    continue
            
            logger.info(f"✅ Conflict resolution complete: {resolved_count}/{conflict_count} conflicts resolved")
            
        except Exception as e:
            logger.error(f"❌ Error in targeted sync with conflict resolution: {e}", exc_info=True)
    
    async def _get_last_online_time(self) -> Optional[datetime]:
        """Get the last time this bot was known to be online from Flask database."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.flask_url}/api/discord_bot_last_online"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('last_online'):
                            return datetime.fromisoformat(data['last_online'])
                    return None
        except Exception as e:
            logger.error(f"❌ Error getting last online time: {str(e)}")
            return None
    
    async def _update_last_online_time(self):
        """Update our last online timestamp in Flask database."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.flask_url}/api/discord_bot_last_online"
                payload = {
                    'instance_id': self.bot_instance_id,
                    'last_online': datetime.utcnow().isoformat()
                }
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logger.debug("✅ Updated last online timestamp")
                    else:
                        logger.warning(f"⚠️ Failed to update last online timestamp: {response.status}")
        except Exception as e:
            logger.error(f"❌ Error updating last online time: {str(e)}")
    
    async def _perform_targeted_sync(self, since: datetime):
        """
        Perform targeted sync only for matches that were active during downtime.
        
        This is the key optimization - instead of syncing ALL matches,
        we only sync matches that:
        1. Had RSVP messages posted since we went offline
        2. Are recent (not ancient matches)
        3. Actually exist in our managed messages
        """
        try:
            logger.info(f"🎯 Performing targeted sync for matches active since {since}")
            
            # Get matches that had RSVP activity during our downtime
            active_matches = await self._get_matches_with_activity_since(since)
            
            if not active_matches:
                logger.info("✅ No matches had activity during downtime - no sync needed")
                return
            
            logger.info(f"🔄 Found {len(active_matches)} matches with activity during downtime")
            
            # Only sync these specific matches
            sync_results = await self._sync_specific_matches(active_matches)
            
            synced_count = sum(1 for result in sync_results if result.get('success'))
            failed_count = len(sync_results) - synced_count
            
            logger.info(f"✅ Targeted sync complete: {synced_count} synced, {failed_count} failed")
            
        except Exception as e:
            logger.error(f"❌ Error during targeted sync: {str(e)}")
            # Fallback to basic sync
            await self._perform_startup_sync(is_first_startup=False)
    
    async def _get_matches_with_activity_since(self, since: datetime) -> List[Dict]:
        """
        Get matches that had RSVP messages posted since the given timestamp.
        
        This queries Flask to find matches where:
        - RSVP messages were posted after 'since' timestamp
        - Match is recent (within last 7 days to 7 days future)
        - Match actually exists in our system
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.flask_url}/api/matches_with_rsvp_activity_since"
                params = {
                    'since': since.isoformat(),
                    'limit_days': 7  # Only check matches within 7 days
                }
                
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        matches = data.get('matches', [])
                        logger.info(f"📊 Found {len(matches)} matches with activity since {since}")
                        return matches
                    else:
                        logger.error(f"❌ Failed to get active matches: {response.status}")
                        return []
                        
        except Exception as e:
            logger.error(f"❌ Error getting matches with activity: {str(e)}")
            return []
    
    async def _sync_specific_matches(self, matches: List[Dict]) -> List[Dict]:
        """
        Sync only the specific matches provided.
        
        This is much more efficient than the current approach which
        syncs ALL managed messages.
        """
        results = []
        semaphore = asyncio.Semaphore(3)  # Limit concurrent operations
        
        async def sync_single_match(match_data):
            async with semaphore:
                try:
                    match_id = match_data['match_id']
                    logger.info(f"🔄 Syncing match {match_id}")
                    
                    # Use existing sync logic but for just this match
                    import ECS_Discord_Bot
                    result = await ECS_Discord_Bot.sync_single_match_rsvps(match_id)
                    
                    results.append({
                        'match_id': match_id,
                        'success': result.get('success', False),
                        'message': result.get('message', 'Unknown result')
                    })
                    
                    # Small delay to avoid overwhelming APIs
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"❌ Error syncing match {match_data.get('match_id')}: {str(e)}")
                    results.append({
                        'match_id': match_data.get('match_id'),
                        'success': False,
                        'error': str(e)
                    })
        
        # Process matches concurrently but with rate limiting
        tasks = [sync_single_match(match) for match in matches]
        await asyncio.gather(*tasks)
        
        return results
    
    async def _perform_startup_sync(self, is_first_startup: bool):
        """
        Fallback sync method - similar to current approach but with better filtering.
        
        Used when:
        - First startup (no previous online time)
        - Smart sync fails for some reason
        """
        try:
            if is_first_startup:
                logger.info("⭐ First startup - syncing recent matches only")
            else:
                logger.info("🔄 Fallback sync - using existing logic")
            
            # Use existing full_rsvp_sync but maybe with tighter time bounds
            from ECS_Discord_Bot import full_rsvp_sync
            await full_rsvp_sync(force_sync=False)
            
        except Exception as e:
            logger.error(f"❌ Error during startup sync: {str(e)}")
    
    async def start_periodic_heartbeat(self):
        """
        Start a background task that periodically updates our online timestamp.
        
        This ensures that if the bot is running, Flask knows about it.
        If the bot crashes/restarts, Flask will know the last time it was alive.
        """
        async def heartbeat_loop():
            while True:
                try:
                    await self._update_last_online_time()
                    await asyncio.sleep(300)  # Update every 5 minutes
                except asyncio.CancelledError:
                    logger.info("📡 Heartbeat loop cancelled")
                    break
                except Exception as e:
                    logger.error(f"❌ Error in heartbeat loop: {str(e)}")
                    await asyncio.sleep(60)  # Wait before retrying
        
        # Start the heartbeat task
        heartbeat_task = asyncio.create_task(heartbeat_loop())
        logger.info("💓 Started periodic heartbeat to track online status")
        return heartbeat_task


# Global instance
_smart_sync_manager = None

def get_smart_sync_manager() -> ContainerResilientSyncManager:
    """Get the global smart sync manager instance."""
    global _smart_sync_manager
    if not _smart_sync_manager:
        _smart_sync_manager = ContainerResilientSyncManager()
    return _smart_sync_manager

async def initialize_smart_sync():
    """Initialize the smart sync manager on bot startup."""
    manager = get_smart_sync_manager()
    await manager.on_bot_startup()
    heartbeat_task = await manager.start_periodic_heartbeat()
    return manager, heartbeat_task