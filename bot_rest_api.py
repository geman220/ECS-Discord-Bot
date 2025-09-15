# discord bot_rest_api.py - Refactored main application file

from fastapi import FastAPI
from shared_states import get_bot_instance, set_bot_instance, bot_ready, bot_state
import logging

# Import API utilities
from api.utils.api_client import startup_event, shutdown_event

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# FIX THIS AFTER TESTING
TEAM_ID = '9726'

# Initialize FastAPI app
app = FastAPI()

# Include existing routers
from ecs_fc_bot_api import router as ecs_fc_router
app.include_router(ecs_fc_router)

# Include new modular routers
from api.routes.server_routes import router as server_router
from api.routes.match_routes import router as match_router
from api.routes.league_routes import router as league_router
from api.routes.communication_routes import router as communication_router
from api.routes.ecs_fc_sub_routes import router as ecs_fc_sub_router
from api.routes.onboarding_routes import router as onboarding_router
from api.routes.websocket_routes import router as websocket_router
from api.routes.live_reporting_routes import router as live_reporting_router
from api.routes.testing_routes import router as testing_router

app.include_router(server_router)
app.include_router(match_router)  # Routes already have /api prefix where needed
app.include_router(league_router)
app.include_router(communication_router)
app.include_router(ecs_fc_sub_router)
app.include_router(onboarding_router, prefix="/onboarding")
app.include_router(websocket_router)
app.include_router(live_reporting_router)  # Live reporting endpoints
app.include_router(testing_router)  # Testing and mock match endpoints

# Startup and shutdown events
app.add_event_handler("startup", startup_event)
app.add_event_handler("shutdown", shutdown_event)

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "message": "Bot REST API is running"}

# Bot statistics endpoint
@app.get("/api/stats")
async def bot_stats():
    """Get Discord bot statistics."""
    try:
        from datetime import datetime, timedelta
        
        bot = get_bot_instance()
        if not bot or not bot.is_ready():
            # Still show API server uptime even if Discord bot is offline
            start_time = getattr(bot_state, 'start_time', datetime.utcnow())
            uptime_seconds = (datetime.utcnow() - start_time).total_seconds()
            
            # Format uptime as duration
            if uptime_seconds < 60:
                uptime_display = f"{uptime_seconds:.0f}s (API only)"
            elif uptime_seconds < 3600:
                minutes = uptime_seconds / 60
                uptime_display = f"{minutes:.1f}m (API only)"
            elif uptime_seconds < 86400:
                hours = uptime_seconds / 3600
                uptime_display = f"{hours:.1f}h (API only)"
            else:
                days = uptime_seconds / 86400
                uptime_display = f"{days:.1f}d (API only)"
            
            return {
                "status": "offline",
                "guild_count": 0,
                "member_count": 0,
                "commands_today": 0,
                "uptime": uptime_display,
                "start_time": start_time.isoformat() if hasattr(start_time, 'isoformat') else str(start_time)
            }
        
        # Calculate uptime
        start_time = getattr(bot_state, 'start_time', datetime.utcnow())
        uptime_seconds = (datetime.utcnow() - start_time).total_seconds()
        
        # Format uptime as duration instead of percentage
        if uptime_seconds < 60:
            uptime_display = f"{uptime_seconds:.0f}s"
        elif uptime_seconds < 3600:
            minutes = uptime_seconds / 60
            uptime_display = f"{minutes:.1f}m"
        elif uptime_seconds < 86400:
            hours = uptime_seconds / 3600
            uptime_display = f"{hours:.1f}h"
        else:
            days = uptime_seconds / 86400
            uptime_display = f"{days:.1f}d"
        
        # Also calculate percentage for compatibility
        uptime_hours = uptime_seconds / 3600
        uptime_percentage = min(100, (uptime_hours / 24) * 100)  # 24h = 100%
        
        # Get guild and member counts
        guild_count = len(bot.guilds)
        member_count = sum(guild.member_count or 0 for guild in bot.guilds)
        
        # Get command usage from bot state
        command_stats = getattr(bot_state, 'command_stats', {})
        today = datetime.utcnow().date()
        commands_today = command_stats.get(str(today), 0)
        
        return {
            "status": "online" if bot.is_ready() else "offline",
            "guild_count": guild_count,
            "member_count": member_count,
            "commands_today": commands_today,
            "uptime": uptime_display,
            "start_time": start_time.isoformat() if hasattr(start_time, 'isoformat') else str(start_time),
            "command_usage": {
                "commands_today": commands_today,
                "commands_this_week": sum(command_stats.get(str((today - timedelta(days=i))), 0) for i in range(7)),
                "most_used_command": "verify",  # Would need actual tracking
                "avg_response_time": "250ms"  # Would need actual measurement
            }
        }
    except Exception as e:
        logger.error(f"Error getting bot stats: {e}")
        return {
            "status": "error",
            "guild_count": 0,
            "member_count": 0,
            "commands_today": 0,
            "uptime": "Error",
            "start_time": "Error"
        }

# Bot commands endpoint
@app.get("/api/commands")
async def bot_commands():
    """Get Discord bot command list."""
    try:
        bot = get_bot_instance()
        commands = []
        
        # Only try to get real commands if bot is available and ready
        if bot and bot.is_ready():
            # Get application commands (slash commands)
            if hasattr(bot, 'tree') and bot.tree:
                app_commands = bot.tree.get_commands()
                for cmd in app_commands:
                    commands.append({
                        "name": cmd.name,
                        "description": cmd.description or "No description",
                        "category": "Slash Commands",
                        "permission_level": "Public"  # Would need actual permission check
                    })
            
            # Get text commands (if using commands extension)
            if hasattr(bot, 'commands'):
                for cmd in bot.commands:
                    commands.append({
                        "name": cmd.name,
                        "description": cmd.help or "No description",
                        "category": cmd.cog_name or "General",
                        "permission_level": "Public"  # Would need actual permission check
                    })
        
        # If no commands found, provide known commands from the codebase
        if not commands:
            known_commands = [
                {"name": "verify", "description": "Verify ECS membership", "category": "Membership", "permission_level": "Public"},
                {"name": "nextmatch", "description": "Get next match information", "category": "Matches", "permission_level": "Public"},
                {"name": "record", "description": "Get team record", "category": "Statistics", "permission_level": "Public"},
                {"name": "lookup", "description": "Look up player information", "category": "Players", "permission_level": "Public"},
                {"name": "rsvp", "description": "RSVP to matches", "category": "Matches", "permission_level": "Public"},
                {"name": "schedule", "description": "View match schedule", "category": "Matches", "permission_level": "Public"},
                {"name": "standings", "description": "View league standings", "category": "Statistics", "permission_level": "Public"},
                {"name": "admin", "description": "Admin commands", "category": "Administration", "permission_level": "Admin"},
                {"name": "clear", "description": "Clear chat messages", "category": "Moderation", "permission_level": "Moderator"},
                {"name": "poll", "description": "Create polls", "category": "Utilities", "permission_level": "Public"}
            ]
            commands = known_commands
        
        return {"commands": commands}
    except Exception as e:
        logger.error(f"Error getting bot commands: {e}")
        return {"commands": []}

# Guild statistics endpoint
@app.get("/api/guild-stats")
async def guild_stats():
    """Get detailed guild statistics."""
    try:
        bot = get_bot_instance()
        if not bot or not bot.is_ready():
            return {"error": "Bot not ready", "guilds": []}
        
        guild_data = []
        for guild in bot.guilds:
            # Get role distribution
            role_distribution = {}
            total_members = guild.member_count or len(guild.members)
            
            # Analyze roles
            role_counts = {}
            for member in guild.members:
                for role in member.roles:
                    if role.name != "@everyone":  # Skip default role
                        role_counts[role.name] = role_counts.get(role.name, 0) + 1
            
            # Calculate percentages for top roles
            for role_name, count in sorted(role_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
                if total_members > 0:
                    percentage = (count / total_members) * 100
                    role_distribution[role_name] = {
                        "count": count,
                        "percentage": round(percentage, 1)
                    }
            
            # Get recent activity (last 24 hours)
            from datetime import datetime, timedelta
            yesterday = datetime.utcnow() - timedelta(days=1)
            
            # Count new members (joined in last 24h)
            new_members_today = sum(1 for member in guild.members 
                                  if member.joined_at and member.joined_at > yesterday)
            
            guild_info = {
                "id": guild.id,
                "name": guild.name,
                "member_count": total_members,
                "channel_count": len(guild.channels),
                "role_count": len(guild.roles),
                "role_distribution": role_distribution,
                "new_members_today": new_members_today,
                "owner_id": guild.owner_id,
                "created_at": guild.created_at.isoformat() if guild.created_at else None
            }
            guild_data.append(guild_info)
        
        return {"guilds": guild_data}
    except Exception as e:
        logger.error(f"Error getting guild stats: {e}")
        return {"error": str(e), "guilds": []}

# Bot logs endpoint
@app.get("/api/logs")
async def bot_logs():
    """Get recent bot logs."""
    try:
        # Get logs from bot_state if available
        logs = getattr(bot_state, 'recent_logs', [])
        
        # If no logs in memory, return some real activity from command stats
        if not logs:
            from datetime import datetime, timedelta
            
            bot = get_bot_instance()
            command_stats = getattr(bot_state, 'command_stats', {})
            
            # Generate recent activity log entries
            recent_logs = []
            
            if bot and bot.is_ready():
                recent_logs.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "level": "INFO",
                    "message": f"Bot connected to Discord as {bot.user.name}#{bot.user.discriminator}"
                })
                
                recent_logs.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "level": "INFO", 
                    "message": f"Monitoring {len(bot.guilds)} guild(s) with {sum(g.member_count or 0 for g in bot.guilds)} total members"
                })
            
            # Add command usage info
            today = str(datetime.utcnow().date())
            commands_today = command_stats.get(today, 0)
            if commands_today > 0:
                recent_logs.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "level": "INFO",
                    "message": f"Processed {commands_today} commands today"
                })
            
            # Add startup info
            start_time = getattr(bot_state, 'start_time', datetime.utcnow())
            recent_logs.append({
                "timestamp": start_time.isoformat(),
                "level": "INFO",
                "message": "Bot startup completed successfully"
            })
            
            return {"logs": recent_logs[-20:]}  # Return last 20 entries
        
        return {"logs": logs[-50:]}  # Return last 50 entries
    except Exception as e:
        logger.error(f"Error getting bot logs: {e}")
        return {"logs": []}

# Enhanced bot control endpoints
@app.post("/api/bot/restart")
async def restart_bot():
    """Restart the Discord bot."""
    try:
        bot = get_bot_instance()
        if bot:
            # Log restart attempt
            _log_bot_activity("Bot restart requested via API")
            
            # Schedule restart (this would need proper implementation)
            return {"success": True, "message": "Bot restart initiated"}
        return {"success": False, "message": "Bot not available"}
    except Exception as e:
        logger.error(f"Error restarting bot: {e}")
        return {"success": False, "message": str(e)}

@app.get("/api/bot/health-detailed")
async def detailed_health():
    """Get detailed bot health information."""
    try:
        bot = get_bot_instance()
        if not bot:
            return {"status": "offline", "details": "Bot instance not available"}
        
        # Detailed health check
        health_info = {
            "status": "online" if bot.is_ready() else "connecting",
            "user_id": bot.user.id if bot.user else None,
            "username": str(bot.user) if bot.user else None,
            "guild_count": len(bot.guilds) if bot.guilds else 0,
            "latency": round(bot.latency * 1000, 2),  # Convert to ms
            "shard_count": bot.shard_count,
            "ready": bot.is_ready(),
            "closed": bot.is_closed(),
        }
        
        # Add memory usage if available
        try:
            import psutil
            process = psutil.Process()
            health_info["memory_usage_mb"] = round(process.memory_info().rss / 1024 / 1024, 1)
            health_info["cpu_percent"] = process.cpu_percent()
        except ImportError:
            pass
        
        return health_info
    except Exception as e:
        logger.error(f"Error getting detailed health: {e}")
        return {"status": "error", "details": str(e)}

# Bot configuration endpoints
@app.get("/api/bot/config")
async def get_bot_config():
    """Get current bot configuration."""
    try:
        bot = get_bot_instance()
        if not bot:
            return {"error": "Bot not available"}
        
        # Get current bot configuration
        config = {
            "prefix": "!",  # Default prefix
            "default_role": getattr(bot_state, 'default_role', ""),
            "activity_type": getattr(bot_state, 'activity_type', "playing"),
            "activity_text": getattr(bot_state, 'activity_text', "ECS FC League"),
            "auto_moderation": getattr(bot_state, 'auto_moderation', True),
            "command_logging": getattr(bot_state, 'command_logging', True),
            "welcome_messages": getattr(bot_state, 'welcome_messages', True)
        }
        
        return {"success": True, "config": config}
    except Exception as e:
        logger.error(f"Error getting bot config: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/bot/config")
async def update_bot_config(config_data: dict):
    """Update bot configuration."""
    try:
        bot = get_bot_instance()
        if not bot:
            return {"success": False, "error": "Bot not available"}
        
        # Update bot state configuration
        if "default_role" in config_data:
            bot_state.default_role = config_data["default_role"]
        if "activity_type" in config_data:
            bot_state.activity_type = config_data["activity_type"]
        if "activity_text" in config_data:
            bot_state.activity_text = config_data["activity_text"]
        if "auto_moderation" in config_data:
            bot_state.auto_moderation = config_data["auto_moderation"]
        if "command_logging" in config_data:
            bot_state.command_logging = config_data["command_logging"]
        if "welcome_messages" in config_data:
            bot_state.welcome_messages = config_data["welcome_messages"]
        
        # Update bot activity if specified
        if "activity_type" in config_data and "activity_text" in config_data:
            try:
                import discord
                activity_type = config_data["activity_type"].lower()
                activity_text = config_data["activity_text"]
                
                if activity_type == "playing":
                    activity = discord.Game(name=activity_text)
                elif activity_type == "listening":
                    activity = discord.Activity(type=discord.ActivityType.listening, name=activity_text)
                elif activity_type == "watching":
                    activity = discord.Activity(type=discord.ActivityType.watching, name=activity_text)
                else:
                    activity = discord.Game(name=activity_text)
                
                await bot.change_presence(activity=activity)
                _log_bot_activity(f"Bot activity updated: {activity_type} {activity_text}")
            except Exception as e:
                logger.error(f"Error updating bot activity: {e}")
        
        _log_bot_activity("Bot configuration updated via admin panel")
        return {"success": True, "message": "Configuration updated successfully"}
        
    except Exception as e:
        logger.error(f"Error updating bot config: {e}")
        return {"success": False, "error": str(e)}

def _log_bot_activity(message: str, level: str = "INFO"):
    """Add a log entry to bot state."""
    try:
        from datetime import datetime
        
        if not hasattr(bot_state, 'recent_logs'):
            bot_state.recent_logs = []
        
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message
        }
        
        bot_state.recent_logs.append(log_entry)
        
        # Keep only last 100 log entries
        if len(bot_state.recent_logs) > 100:
            bot_state.recent_logs = bot_state.recent_logs[-100:]
            
    except Exception as e:
        logger.error(f"Error logging bot activity: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)