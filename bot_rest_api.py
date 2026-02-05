# discord bot_rest_api.py - Refactored main application file

import os
from fastapi import FastAPI
from shared_states import get_bot_instance, set_bot_instance, bot_ready, bot_state
import logging

# Import API utilities
from api.utils.api_client import startup_event, shutdown_event

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

TEAM_ID = os.environ.get('ECS_TEAM_ID', '9726')

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
from api.routes.ispy_routes import router as ispy_router

app.include_router(server_router)
app.include_router(match_router)  # Routes already have /api prefix where needed
app.include_router(league_router)
app.include_router(communication_router)
app.include_router(ecs_fc_sub_router)
app.include_router(onboarding_router, prefix="/onboarding")
app.include_router(websocket_router)
app.include_router(live_reporting_router)  # Live reporting endpoints
app.include_router(testing_router)  # Testing and mock match endpoints
app.include_router(ispy_router)  # I-Spy mobile integration endpoints

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
                "most_used_command": bot_state.get_most_used_command() or "N/A",
                "avg_response_time": f"{bot_state.get_avg_response_time()}ms" if bot_state.get_avg_response_time() is not None else "N/A"
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
        saved_perms = getattr(bot_state, 'command_permissions', {})

        def _permission_label(cmd_name):
            """Derive a human-readable permission level from saved permissions."""
            perms = saved_perms.get(cmd_name)
            if not perms:
                return "Public"
            roles = perms.get("roles", [])
            if not roles or "@everyone" in roles or "User" in roles:
                return "Public"
            if "Global Admin" in roles and len(roles) == 1:
                return "Admin"
            if any(r in roles for r in ("Global Admin", "Moderator")) and "Coach" not in roles:
                return "Moderator"
            return "Restricted"

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
                        "permission_level": _permission_label(cmd.name)
                    })

            # Get text commands (if using commands extension)
            if hasattr(bot, 'commands'):
                for cmd in bot.commands:
                    commands.append({
                        "name": cmd.name,
                        "description": cmd.help or "No description",
                        "category": cmd.cog_name or "General",
                        "permission_level": _permission_label(cmd.name)
                    })

        # If no commands found, provide known commands from the codebase
        if not commands:
            known_commands = [
                {"name": "verify", "description": "Verify ECS membership", "category": "Membership"},
                {"name": "nextmatch", "description": "Get next match information", "category": "Matches"},
                {"name": "record", "description": "Get team record", "category": "Statistics"},
                {"name": "lookup", "description": "Look up player information", "category": "Players"},
                {"name": "rsvp", "description": "RSVP to matches", "category": "Matches"},
                {"name": "schedule", "description": "View match schedule", "category": "Matches"},
                {"name": "standings", "description": "View league standings", "category": "Statistics"},
                {"name": "admin", "description": "Admin commands", "category": "Administration"},
                {"name": "clear", "description": "Clear chat messages", "category": "Moderation"},
                {"name": "poll", "description": "Create polls", "category": "Utilities"}
            ]
            for cmd in known_commands:
                cmd["permission_level"] = _permission_label(cmd["name"])
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
    """Restart the Discord bot by closing the connection.

    Requires the bot process to be managed by a process manager
    (e.g. systemd, supervisord, Docker restart policy) that will
    automatically restart the process after it exits.
    """
    try:
        bot = get_bot_instance()
        if not bot:
            return {"success": False, "message": "Bot not available"}

        _log_bot_activity("Bot restart requested via admin panel")

        async def _do_restart():
            """Close bot after a brief delay so the HTTP response is sent first."""
            import asyncio
            await asyncio.sleep(1)
            await bot.close()

        # Schedule the close so this response returns before the process exits
        import asyncio
        asyncio.get_event_loop().create_task(_do_restart())

        return {"success": True, "message": "Bot restart initiated. The bot will reconnect automatically if managed by a process manager."}
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
        bot_state._save_persisted_state()
        return {"success": True, "message": "Configuration updated successfully"}
        
    except Exception as e:
        logger.error(f"Error updating bot config: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/bot/sync-commands")
async def sync_commands():
    """Sync slash commands with Discord."""
    try:
        bot = get_bot_instance()
        if not bot or not bot.is_ready():
            return {"success": False, "message": "Bot is not ready"}
        synced = await bot.tree.sync()
        _log_bot_activity(f"Synced {len(synced)} slash commands via admin panel")
        return {"success": True, "message": f"Successfully synced {len(synced)} commands", "commands_synced": len(synced)}
    except Exception as e:
        logger.error(f"Error syncing commands: {e}")
        return {"success": False, "message": str(e)}

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


# ============================================================================
# COMMAND PERMISSIONS API
# ============================================================================

@app.get("/api/commands/permissions")
async def get_command_permissions():
    """Get permissions for all commands."""
    try:
        # Get command permissions from bot state or defaults
        permissions = getattr(bot_state, 'command_permissions', {})

        # Default permissions for known commands
        default_permissions = {
            "verify": {"roles": ["@everyone"], "cooldown": 10},
            "nextmatch": {"roles": ["@everyone"], "cooldown": 5},
            "record": {"roles": ["@everyone"], "cooldown": 5},
            "rsvp": {"roles": ["@everyone"], "cooldown": 3},
            "admin": {"roles": ["Global Admin", "Moderator"], "cooldown": 0},
            "clear": {"roles": ["Global Admin", "Moderator"], "cooldown": 0},
        }

        # Merge defaults with saved permissions
        merged = {**default_permissions, **permissions}

        return {"success": True, "permissions": merged}
    except Exception as e:
        logger.error(f"Error getting command permissions: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/commands/permissions")
async def update_command_permissions(data: dict):
    """Update permissions for a command."""
    try:
        command = data.get("command")
        roles = data.get("roles", [])
        cooldown = data.get("cooldown", 5)

        if not command:
            return {"success": False, "error": "Command name required"}

        if not hasattr(bot_state, 'command_permissions'):
            bot_state.command_permissions = {}

        bot_state.command_permissions[command] = {
            "roles": roles,
            "cooldown": cooldown
        }

        _log_bot_activity(f"Command permissions updated: {command} - roles: {roles}")
        bot_state._save_persisted_state()

        return {"success": True, "message": f"Permissions updated for /{command}"}
    except Exception as e:
        logger.error(f"Error updating command permissions: {e}")
        return {"success": False, "error": str(e)}


# ============================================================================
# CUSTOM COMMANDS API
# ============================================================================

@app.get("/api/custom-commands")
async def get_custom_commands():
    """Get list of custom commands."""
    try:
        commands = getattr(bot_state, 'custom_commands', [])
        return {"success": True, "commands": commands}
    except Exception as e:
        logger.error(f"Error getting custom commands: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/custom-commands")
async def create_custom_command(data: dict):
    """Create a new custom command."""
    try:
        name = data.get("name", "").lower().strip()
        description = data.get("description", "")
        response_type = data.get("type", "text")
        response_content = data.get("response", "")
        enabled = data.get("enabled", True)

        if not name:
            return {"success": False, "error": "Command name required"}
        if not response_content:
            return {"success": False, "error": "Response content required"}

        # Validate command name (alphanumeric, underscores, hyphens)
        import re
        if not re.match(r'^[a-z0-9_-]+$', name):
            return {"success": False, "error": "Invalid command name. Use lowercase letters, numbers, underscores, and hyphens only."}

        if not hasattr(bot_state, 'custom_commands'):
            bot_state.custom_commands = []

        # Check for existing command with same name
        for cmd in bot_state.custom_commands:
            if cmd.get("name") == name:
                return {"success": False, "error": f"Command /{name} already exists"}

        new_command = {
            "name": name,
            "description": description,
            "type": response_type,
            "response": response_content,
            "enabled": enabled,
            "created_at": __import__('datetime').datetime.utcnow().isoformat()
        }

        bot_state.custom_commands.append(new_command)

        _log_bot_activity(f"Custom command created: /{name}")
        bot_state._save_persisted_state()

        return {"success": True, "message": f"Custom command /{name} created", "command": new_command}
    except Exception as e:
        logger.error(f"Error creating custom command: {e}")
        return {"success": False, "error": str(e)}


@app.put("/api/custom-commands/{command_name}")
async def update_custom_command(command_name: str, data: dict):
    """Update an existing custom command."""
    try:
        if not hasattr(bot_state, 'custom_commands'):
            return {"success": False, "error": "Command not found"}

        # Find existing command
        cmd_index = None
        for i, cmd in enumerate(bot_state.custom_commands):
            if cmd.get("name") == command_name:
                cmd_index = i
                break

        if cmd_index is None:
            return {"success": False, "error": f"Command /{command_name} not found"}

        # Update fields
        existing = bot_state.custom_commands[cmd_index]
        if "description" in data:
            existing["description"] = data["description"]
        if "type" in data:
            existing["type"] = data["type"]
        if "response" in data:
            existing["response"] = data["response"]
        if "enabled" in data:
            existing["enabled"] = data["enabled"]

        _log_bot_activity(f"Custom command updated: /{command_name}")
        bot_state._save_persisted_state()

        return {"success": True, "message": f"Custom command /{command_name} updated", "command": existing}
    except Exception as e:
        logger.error(f"Error updating custom command: {e}")
        return {"success": False, "error": str(e)}


@app.delete("/api/custom-commands/{command_name}")
async def delete_custom_command(command_name: str):
    """Delete a custom command."""
    try:
        if not hasattr(bot_state, 'custom_commands'):
            return {"success": False, "error": "Command not found"}

        original_length = len(bot_state.custom_commands)
        bot_state.custom_commands = [
            cmd for cmd in bot_state.custom_commands
            if cmd.get("name") != command_name
        ]

        if len(bot_state.custom_commands) == original_length:
            return {"success": False, "error": f"Command /{command_name} not found"}

        _log_bot_activity(f"Custom command deleted: /{command_name}")
        bot_state._save_persisted_state()

        return {"success": True, "message": f"Custom command /{command_name} deleted"}
    except Exception as e:
        logger.error(f"Error deleting custom command: {e}")
        return {"success": False, "error": str(e)}


# ============================================================================
# GUILD MANAGEMENT API
# ============================================================================

@app.get("/api/guilds/{guild_id}/settings")
async def get_guild_settings(guild_id: str):
    """Get settings for a specific guild."""
    try:
        bot = get_bot_instance()

        # Get guild-specific settings from bot state
        guild_settings = getattr(bot_state, 'guild_settings', {})
        settings = guild_settings.get(guild_id, {})

        # Default settings
        default_settings = {
            "prefix": "!",
            "language": "en",
            "welcome_messages": True,
            "mod_logging": True,
            "announce_channel_id": None,
            "log_channel_id": None,
            "admin_role_id": None,
            "mod_role_id": None
        }

        # Merge defaults with saved settings
        merged = {**default_settings, **settings}

        # Add guild info if bot is available
        if bot and bot.is_ready():
            guild = bot.get_guild(int(guild_id))
            if guild:
                merged["guild_name"] = guild.name
                merged["guild_icon"] = str(guild.icon.url) if guild.icon else None
                merged["channels"] = [
                    {"id": str(ch.id), "name": ch.name, "type": str(ch.type)}
                    for ch in guild.channels if hasattr(ch, 'send')
                ][:50]  # Limit to 50 channels
                merged["roles"] = [
                    {"id": str(role.id), "name": role.name, "color": str(role.color)}
                    for role in guild.roles if role.name != "@everyone"
                ][:50]  # Limit to 50 roles

        return {"success": True, "settings": merged}
    except Exception as e:
        logger.error(f"Error getting guild settings: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/guilds/{guild_id}/settings")
async def update_guild_settings(guild_id: str, data: dict):
    """Update settings for a specific guild."""
    try:
        if not hasattr(bot_state, 'guild_settings'):
            bot_state.guild_settings = {}

        if guild_id not in bot_state.guild_settings:
            bot_state.guild_settings[guild_id] = {}

        # Update only provided fields
        allowed_fields = [
            "prefix", "language", "welcome_messages", "mod_logging",
            "announce_channel_id", "log_channel_id", "admin_role_id", "mod_role_id"
        ]

        for field in allowed_fields:
            if field in data:
                bot_state.guild_settings[guild_id][field] = data[field]

        _log_bot_activity(f"Guild settings updated for {guild_id}")
        bot_state._save_persisted_state()

        return {"success": True, "message": "Guild settings updated successfully"}
    except Exception as e:
        logger.error(f"Error updating guild settings: {e}")
        return {"success": False, "error": str(e)}

# ============================================================================
# DISCORD ROLE SYNC API
# ============================================================================

@app.get("/api/discord/roles")
async def get_discord_roles():
    """Get all roles from the Discord server."""
    try:
        import os
        bot = get_bot_instance()
        guild_id = int(os.getenv('SERVER_ID', '0'))

        if not bot or not bot.is_ready():
            return {"success": False, "error": "Bot not ready", "roles": []}

        guild = bot.get_guild(guild_id)
        if not guild:
            return {"success": False, "error": f"Guild {guild_id} not found", "roles": []}

        roles = []
        for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
            if role.name == "@everyone":
                continue
            roles.append({
                "id": str(role.id),
                "name": role.name,
                "color": str(role.color),
                "position": role.position,
                "permissions": role.permissions.value,
                "mentionable": role.mentionable,
                "hoist": role.hoist,
                "managed": role.managed,  # True if managed by integration/bot
                "member_count": len(role.members)
            })

        return {"success": True, "roles": roles, "guild_id": str(guild_id), "guild_name": guild.name}
    except Exception as e:
        logger.error(f"Error getting Discord roles: {e}")
        return {"success": False, "error": str(e), "roles": []}


@app.get("/api/discord/roles/{role_id}/members")
async def get_role_members(role_id: str):
    """Get all members with a specific Discord role."""
    try:
        import os
        bot = get_bot_instance()
        guild_id = int(os.getenv('SERVER_ID', '0'))

        if not bot or not bot.is_ready():
            return {"success": False, "error": "Bot not ready", "members": []}

        guild = bot.get_guild(guild_id)
        if not guild:
            return {"success": False, "error": f"Guild {guild_id} not found", "members": []}

        role = guild.get_role(int(role_id))
        if not role:
            return {"success": False, "error": f"Role {role_id} not found", "members": []}

        members = []
        for member in role.members:
            members.append({
                "id": str(member.id),
                "username": member.name,
                "display_name": member.display_name,
                "discriminator": member.discriminator,
                "avatar_url": str(member.avatar.url) if member.avatar else None,
                "joined_at": member.joined_at.isoformat() if member.joined_at else None
            })

        return {
            "success": True,
            "role": {"id": str(role.id), "name": role.name},
            "members": members,
            "member_count": len(members)
        }
    except Exception as e:
        logger.error(f"Error getting role members: {e}")
        return {"success": False, "error": str(e), "members": []}


@app.post("/api/discord/roles/assign")
async def assign_discord_role(data: dict):
    """Assign a Discord role to a user."""
    try:
        import os
        bot = get_bot_instance()
        guild_id = int(os.getenv('SERVER_ID', '0'))

        user_id = data.get("user_id")
        role_id = data.get("role_id")

        if not user_id or not role_id:
            return {"success": False, "error": "user_id and role_id required"}

        if not bot or not bot.is_ready():
            return {"success": False, "error": "Bot not ready"}

        guild = bot.get_guild(guild_id)
        if not guild:
            return {"success": False, "error": f"Guild {guild_id} not found"}

        member = guild.get_member(int(user_id))
        if not member:
            # Try to fetch member
            try:
                member = await guild.fetch_member(int(user_id))
            except:
                return {"success": False, "error": f"Member {user_id} not found in guild"}

        role = guild.get_role(int(role_id))
        if not role:
            return {"success": False, "error": f"Role {role_id} not found"}

        await member.add_roles(role, reason="Assigned via Flask admin panel")

        _log_bot_activity(f"Role '{role.name}' assigned to user '{member.display_name}'")

        return {
            "success": True,
            "message": f"Role '{role.name}' assigned to '{member.display_name}'"
        }
    except Exception as e:
        logger.error(f"Error assigning Discord role: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/discord/roles/remove")
async def remove_discord_role(data: dict):
    """Remove a Discord role from a user."""
    try:
        import os
        bot = get_bot_instance()
        guild_id = int(os.getenv('SERVER_ID', '0'))

        user_id = data.get("user_id")
        role_id = data.get("role_id")

        if not user_id or not role_id:
            return {"success": False, "error": "user_id and role_id required"}

        if not bot or not bot.is_ready():
            return {"success": False, "error": "Bot not ready"}

        guild = bot.get_guild(guild_id)
        if not guild:
            return {"success": False, "error": f"Guild {guild_id} not found"}

        member = guild.get_member(int(user_id))
        if not member:
            return {"success": False, "error": f"Member {user_id} not found in guild"}

        role = guild.get_role(int(role_id))
        if not role:
            return {"success": False, "error": f"Role {role_id} not found"}

        await member.remove_roles(role, reason="Removed via Flask admin panel")

        _log_bot_activity(f"Role '{role.name}' removed from user '{member.display_name}'")

        return {
            "success": True,
            "message": f"Role '{role.name}' removed from '{member.display_name}'"
        }
    except Exception as e:
        logger.error(f"Error removing Discord role: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/discord/roles/bulk-sync")
async def bulk_sync_roles(data: dict):
    """Bulk sync roles for multiple users based on Flask role mappings."""
    try:
        import os
        bot = get_bot_instance()
        guild_id = int(os.getenv('SERVER_ID', '0'))

        mappings = data.get("mappings", [])  # [{user_id, discord_role_id, action: "add"|"remove"}]

        if not mappings:
            return {"success": False, "error": "No mappings provided"}

        if not bot or not bot.is_ready():
            return {"success": False, "error": "Bot not ready"}

        guild = bot.get_guild(guild_id)
        if not guild:
            return {"success": False, "error": f"Guild {guild_id} not found"}

        results = []
        success_count = 0
        error_count = 0

        for mapping in mappings:
            user_id = mapping.get("user_id")
            role_id = mapping.get("discord_role_id")
            action = mapping.get("action", "add")

            try:
                member = guild.get_member(int(user_id))
                if not member:
                    member = await guild.fetch_member(int(user_id))

                role = guild.get_role(int(role_id))
                if not role:
                    results.append({"user_id": user_id, "status": "error", "message": "Role not found"})
                    error_count += 1
                    continue

                if action == "add":
                    await member.add_roles(role, reason="Bulk sync from Flask")
                else:
                    await member.remove_roles(role, reason="Bulk sync from Flask")

                results.append({"user_id": user_id, "status": "success", "action": action, "role": role.name})
                success_count += 1

            except Exception as e:
                results.append({"user_id": user_id, "status": "error", "message": str(e)})
                error_count += 1

        _log_bot_activity(f"Bulk role sync: {success_count} successful, {error_count} errors")

        return {
            "success": True,
            "results": results,
            "summary": {"success": success_count, "errors": error_count}
        }
    except Exception as e:
        logger.error(f"Error in bulk role sync: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)