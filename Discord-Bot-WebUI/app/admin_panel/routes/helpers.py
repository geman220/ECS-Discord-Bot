# app/admin_panel/routes/helpers.py

"""
Admin Panel Helper Functions

This module contains shared utility functions used across admin panel routes:
- Service status checking functions
- External API health checks
- Statistics calculation helpers
- Quick action implementations
"""

import logging
import time
import os
import requests
from datetime import datetime, timedelta
from flask import current_app

from app.core import db
from app.models.core import User
from app.models.communication import Notification, ScheduledMessage
from app.models.notifications import UserFCMToken

# Set up the module logger
logger = logging.getLogger(__name__)


def _check_discord_api_status():
    """Check Discord API status using parent directory configuration."""
    try:
        import os
        import requests
        from flask import current_app
        
        # Load environment from parent directory if needed
        parent_env_file = os.path.join(os.path.dirname(os.path.dirname(current_app.root_path)), '.env')
        if os.path.exists(parent_env_file):
            try:
                from dotenv import load_dotenv
                load_dotenv(parent_env_file, override=False)  # Don't override existing values
            except ImportError:
                pass  # dotenv not available, continue with existing env vars
        
        # Check for Discord bot token (BOT_TOKEN is the actual key from parent .env)
        bot_token = (
            os.getenv('BOT_TOKEN') or  # Primary token from parent directory
            os.getenv('DISCORD_BOT_TOKEN') or 
            os.getenv('DISCORD_TOKEN') or
            current_app.config.get('BOT_TOKEN') or
            current_app.config.get('DISCORD_BOT_TOKEN') or
            current_app.config.get('DISCORD_TOKEN')
        )
        
        # Check for Discord configuration
        discord_client_id = (
            os.getenv('DISCORD_CLIENT_ID') or 
            current_app.config.get('DISCORD_CLIENT_ID')
        )
        server_id = (
            os.getenv('SERVER_ID') or
            current_app.config.get('SERVER_ID')
        )
        bot_api_url = (
            os.getenv('BOT_API_URL') or
            current_app.config.get('BOT_API_URL')
        )
        
        # First check if our bot API is reachable
        if bot_api_url:
            try:
                start_time = datetime.utcnow()
                bot_health_response = requests.get(
                    f"{bot_api_url}/health",
                    timeout=3
                )
                end_time = datetime.utcnow()
                response_time = f"{(end_time - start_time).total_seconds() * 1000:.0f}ms"
                
                if bot_health_response.status_code == 200:
                    try:
                        bot_health_data = bot_health_response.json()
                        bot_status = bot_health_data.get('status', 'unknown')
                        if bot_status == 'healthy':
                            return {
                                'name': 'Discord API',
                                'status': 'healthy',
                                'message': f'Bot API healthy ({bot_api_url})',
                                'last_check': datetime.utcnow(),
                                'response_time': response_time
                            }
                    except:
                        pass
                        
                    return {
                        'name': 'Discord API',
                        'status': 'healthy',
                        'message': f'Bot API responding ({bot_api_url})',
                        'last_check': datetime.utcnow(),
                        'response_time': response_time
                    }
                else:
                    return {
                        'name': 'Discord API',
                        'status': 'warning',
                        'message': f'Bot API error: HTTP {bot_health_response.status_code}',
                        'last_check': datetime.utcnow(),
                        'response_time': response_time
                    }
            except requests.exceptions.RequestException:
                # Bot API not reachable, fall back to direct Discord API check
                pass
        
        if not bot_token:
            # Check if there's any indication Discord is configured
            has_discord_config = any([
                discord_client_id,
                server_id,
                bot_api_url
            ])
            
            if has_discord_config:
                return {
                    'name': 'Discord API',
                    'status': 'warning',
                    'message': f'Bot token missing (Client ID: {discord_client_id[:10] + "..." if discord_client_id else "None"})',
                    'last_check': datetime.utcnow(),
                    'response_time': 'N/A'
                }
            else:
                return {
                    'name': 'Discord API',
                    'status': 'disabled',
                    'message': 'Discord not configured',
                    'last_check': datetime.utcnow(),
                    'response_time': 'N/A'
                }
        
        # Direct Discord API validation with bot token
        start_time = datetime.utcnow()
        try:
            bot_response = requests.get(
                'https://discord.com/api/v10/users/@me',
                headers={'Authorization': f'Bot {bot_token}'},
                timeout=5
            )
            end_time = datetime.utcnow()
            response_time = f"{(end_time - start_time).total_seconds() * 1000:.0f}ms"
            
            if bot_response.status_code == 200:
                bot_data = bot_response.json()
                bot_name = bot_data.get('username', 'Unknown')
                return {
                    'name': 'Discord API',
                    'status': 'healthy',
                    'message': f'Bot connected: {bot_name}',
                    'last_check': datetime.utcnow(),
                    'response_time': response_time
                }
            elif bot_response.status_code == 401:
                return {
                    'name': 'Discord API',
                    'status': 'error',
                    'message': 'Bot token invalid or expired',
                    'last_check': datetime.utcnow(),
                    'response_time': response_time
                }
            else:
                return {
                    'name': 'Discord API',
                    'status': 'warning',
                    'message': f'API error: HTTP {bot_response.status_code}',
                    'last_check': datetime.utcnow(),
                    'response_time': response_time
                }
        except requests.exceptions.Timeout:
            return {
                'name': 'Discord API',
                'status': 'warning',
                'message': 'Discord API timeout',
                'last_check': datetime.utcnow(),
                'response_time': 'Timeout'
            }
        except requests.exceptions.RequestException as e:
            return {
                'name': 'Discord API',
                'status': 'error',
                'message': f'Connection failed: {str(e)[:30]}',
                'last_check': datetime.utcnow(),
                'response_time': 'Error'
            }
    except Exception as e:
        logger.error(f"Discord API check failed: {e}")
        return {
            'name': 'Discord API',
            'status': 'error',
            'message': f'Check failed: {str(e)[:30]}',
            'last_check': datetime.utcnow(),
            'response_time': 'Error'
        }


def get_discord_bot_stats():
    """Get Discord bot statistics from bot API."""
    try:
        import os
        from flask import current_app
        
        # Load environment from parent directory if needed
        parent_env_file = os.path.join(os.path.dirname(os.path.dirname(current_app.root_path)), '.env')
        if os.path.exists(parent_env_file):
            try:
                from dotenv import load_dotenv
                load_dotenv(parent_env_file, override=False)
            except ImportError:
                pass
        
        bot_api_url = (
            os.getenv('BOT_API_URL') or
            current_app.config.get('BOT_API_URL') or
            'http://localhost:5001'  # Default bot API URL
        )
        
        # Try to get stats from bot API
        try:
            # Get multiple endpoints
            stats_response = requests.get(f"{bot_api_url}/api/stats", timeout=5)
            commands_response = requests.get(f"{bot_api_url}/api/commands", timeout=5)
            guild_stats_response = requests.get(f"{bot_api_url}/api/guild-stats", timeout=5)
            logs_response = requests.get(f"{bot_api_url}/api/logs", timeout=5)
            health_response = requests.get(f"{bot_api_url}/api/bot/health-detailed", timeout=5)
            
            stats_data = stats_response.json() if stats_response.status_code == 200 else {}
            commands_data = commands_response.json() if commands_response.status_code == 200 else {}
            guild_data = guild_stats_response.json() if guild_stats_response.status_code == 200 else {}
            logs_data = logs_response.json() if logs_response.status_code == 200 else {}
            health_data = health_response.json() if health_response.status_code == 200 else {}
            
            # Extract guild statistics
            guilds = guild_data.get('guilds', [])
            main_guild = guilds[0] if guilds else {}
            
            # Extract bot statistics
            bot_stats = {
                'bot_status': health_data.get('status', stats_data.get('status', 'offline')),
                'guilds_connected': stats_data.get('guild_count', 0),
                'member_count': stats_data.get('member_count', main_guild.get('member_count', 0)),
                'commands_today': stats_data.get('commands_today', 0),
                'uptime': stats_data.get('uptime', '0%'),
                'total_commands': len(commands_data.get('commands', [])),
                'last_restart': stats_data.get('start_time', 'Unknown'),
                'latency': health_data.get('latency', 0),
                'ready': health_data.get('ready', False)
            }
            
            # Extract command data
            commands = commands_data.get('commands', [])
            command_usage = stats_data.get('command_usage', {
                'commands_today': stats_data.get('commands_today', 0),
                'commands_this_week': 0,
                'most_used_command': 'verify',
                'avg_response_time': f"{health_data.get('latency', 250):.0f}ms"
            })
            
            # Extract guild info for display
            guild_info = {}
            if main_guild:
                guild_info = {
                    'name': main_guild.get('name', 'ECS FC Discord'),
                    'member_count': main_guild.get('member_count', 0),
                    'channel_count': main_guild.get('channel_count', 0),
                    'role_count': main_guild.get('role_count', 0),
                    'role_distribution': main_guild.get('role_distribution', {}),
                    'new_members_today': main_guild.get('new_members_today', 0)
                }
            
            # Extract recent logs
            recent_logs = logs_data.get('logs', [])
            
            return {
                'success': True,
                'stats': bot_stats,
                'commands': commands,
                'command_usage': command_usage,
                'guild_info': guild_info,
                'recent_logs': recent_logs
            }
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Bot API not available: {e}")
            # Bot API not available, return fallback data
            return {
                'success': False,
                'stats': {
                    'bot_status': 'offline',
                    'guilds_connected': 0,
                    'member_count': 0,
                    'commands_today': 0,
                    'uptime': 'Unknown',
                    'total_commands': 0,
                    'last_restart': 'Unknown',
                    'latency': 0,
                    'ready': False
                },
                'commands': [],
                'command_usage': {
                    'commands_today': 0,
                    'commands_this_week': 0,
                    'most_used_command': 'N/A',
                    'avg_response_time': 'N/A'
                },
                'guild_info': {},
                'recent_logs': []
            }
    except Exception as e:
        logger.error(f"Error getting Discord bot stats: {e}")
        return {
            'success': False,
            'stats': {
                'bot_status': 'error',
                'guilds_connected': 0,
                'member_count': 0,
                'commands_today': 0,
                'uptime': 'Error',
                'total_commands': 0,
                'last_restart': 'Error',
                'latency': 0,
                'ready': False
            },
            'commands': [],
            'command_usage': {
                'commands_today': 0,
                'commands_this_week': 0,
                'most_used_command': 'Error',
                'avg_response_time': 'Error'
            },
            'guild_info': {},
            'recent_logs': []
        }


def _check_push_service_status():
    """Check push notification service status using parent directory configuration."""
    try:
        import os
        from flask import current_app
        
        # Load environment from parent directory if needed
        parent_env_file = os.path.join(os.path.dirname(os.path.dirname(current_app.root_path)), '.env')
        if os.path.exists(parent_env_file):
            try:
                from dotenv import load_dotenv
                load_dotenv(parent_env_file, override=False)  # Don't override existing values
            except ImportError:
                pass
        
        # Check for mobile app configuration
        mobile_config = {
            'api_key': os.getenv('MOBILE_API_KEY'),
            'allowed_networks': os.getenv('MOBILE_APP_ALLOWED_NETWORKS'),
            'webui_base_url': os.getenv('WEBUI_BASE_URL'),
            'webui_api_url': os.getenv('WEBUI_API_URL')
        }
        
        # Check for Apple Wallet configuration (indicates mobile features are active)
        wallet_config = {
            'pass_type_id': os.getenv('WALLET_PASS_TYPE_ID'),
            'team_id': os.getenv('WALLET_TEAM_ID'),
            'key_password': os.getenv('WALLET_KEY_PASSWORD')
        }
        
        # Check AdminConfig for push notification settings
        try:
            from app.models.admin_config import AdminConfig
            # AdminConfig.get_value() DOES NOT EXIST — only get_setting() does. The
            # AttributeError was caught by the except below, so this panel reported push
            # as disabled 100% of the time regardless of the real setting. get_setting()
            # returns the *parsed* value (a real bool when data_type='boolean'), but fall
            # back to string coercion in case the row was stored as a plain string.
            raw = AdminConfig.get_setting('push_notifications_enabled', False)
            push_enabled = raw if isinstance(raw, bool) else str(raw).strip().lower() in ('true', '1', 'yes', 'on')
        except Exception:
            push_enabled = False
        
        # Check if UserFCMToken table exists and is accessible
        total_tokens = 0
        active_tokens = 0
        service_available = False
        try:
            from app.models.notifications import UserFCMToken
            total_tokens = UserFCMToken.query.count()
            active_tokens = UserFCMToken.query.filter_by(is_active=True).count()
            service_available = True
        except ImportError:
            logger.debug("UserFCMToken model not available")
        except Exception as e:
            logger.debug(f"UserFCMToken access failed (table may need migration): {e}")

        # Count configured mobile services
        mobile_configured = bool(mobile_config['api_key'] and mobile_config['webui_base_url'])
        wallet_configured = all(wallet_config.values())

        active_services = []
        if mobile_configured:
            active_services.append(f"Mobile API ({mobile_config['webui_base_url']})")
        if wallet_configured:
            active_services.append(f"Apple Wallet ({wallet_config['pass_type_id']})")

        # Determine status based on configuration and device registrations
        if not mobile_configured and not wallet_configured and not push_enabled:
            return {
                'name': 'Push Notifications',
                'status': 'disabled',
                'message': 'Mobile services not configured',
                'last_check': datetime.utcnow(),
                'response_time': 'N/A'
            }

        # If services are configured but device table isn't available,
        # still attempt the API health check rather than stopping here
        if not service_available and not mobile_config.get('webui_api_url'):
            return {
                'name': 'Push Notifications',
                'status': 'healthy',
                'message': f'Services configured: {", ".join(active_services)}. Device tracking pending setup.',
                'details': 'FCM token table needs migration',
                'last_check': datetime.utcnow(),
                'response_time': 'N/A'
            }
        
        # If mobile services are configured, test API availability
        if mobile_config['webui_api_url']:
            # Try multiple health endpoints
            health_endpoints = [
                f"{mobile_config['webui_api_url']}/health",
                f"{mobile_config['webui_api_url']}/api/external/v1/health"
            ]
            
            for health_url in health_endpoints:
                try:
                    import requests
                    start_time = datetime.utcnow()
                    response = requests.get(health_url, timeout=3)
                    end_time = datetime.utcnow()
                    response_time = f"{(end_time - start_time).total_seconds() * 1000:.0f}ms"
                    
                    if response.status_code == 200:
                        try:
                            health_data = response.json()
                            api_status = health_data.get('status', 'unknown')
                        except:
                            api_status = 'responding'
                            
                        message_parts = [f'Mobile API {api_status} ({response_time})']
                        if active_tokens > 0:
                            message_parts.append(f'{active_tokens}/{total_tokens} devices')
                        elif total_tokens > 0:
                            message_parts.append(f'{total_tokens} inactive devices')
                        
                        return {
                            'name': 'Push Notifications',
                            'status': 'healthy',
                            'message': ', '.join(message_parts),
                            'last_check': datetime.utcnow(),
                            'response_time': response_time
                        }
                    # If this endpoint fails, try the next one
                    continue
                except Exception:
                    # Try the next endpoint
                    continue
            
            # All health endpoints failed
            return {
                'name': 'Push Notifications',
                'status': 'warning',
                'message': f'Mobile API health check failed ({mobile_config["webui_api_url"]})',
                'last_check': datetime.utcnow(),
                'response_time': 'Error'
            }
        
        # Status based on configuration and device tokens
        if active_tokens > 0:
            return {
                'name': 'Push Notifications',
                'status': 'healthy',
                'message': f'{active_tokens}/{total_tokens} active devices, services: {", ".join(active_services) if active_services else "Basic"}',
                'last_check': datetime.utcnow(),
                'response_time': 'N/A'
            }
        elif total_tokens > 0:
            return {
                'name': 'Push Notifications',
                'status': 'warning',
                'message': f'{total_tokens} inactive devices, services: {", ".join(active_services) if active_services else "Basic"}',
                'last_check': datetime.utcnow(),
                'response_time': 'N/A'
            }
        elif active_services:
            return {
                'name': 'Push Notifications',
                'status': 'healthy',
                'message': f'Services configured: {", ".join(active_services)}, awaiting device registrations',
                'last_check': datetime.utcnow(),
                'response_time': 'N/A'
            }
        else:
            return {
                'name': 'Push Notifications',
                'status': 'warning',
                'message': 'Enabled but no services configured or devices registered',
                'last_check': datetime.utcnow(),
                'response_time': 'N/A'
            }
            
    except Exception as e:
        logger.error(f"Push notification check failed: {e}")
        return {
            'name': 'Push Notifications',
            'status': 'error',
            'message': f'Check failed: {str(e)[:30]}',
            'last_check': datetime.utcnow(),
            'response_time': 'Error'
        }


def _check_email_service_status():
    """Check email service status using parent directory configuration."""
    try:
        import os
        from flask import current_app
        
        # Load environment from parent directory if needed
        parent_env_file = os.path.join(os.path.dirname(os.path.dirname(current_app.root_path)), '.env')
        if os.path.exists(parent_env_file):
            try:
                from dotenv import load_dotenv
                load_dotenv(parent_env_file, override=False)  # Don't override existing values
            except ImportError:
                pass
        
        # Check for Twilio SMS configuration (primary communication method from parent .env)
        twilio_config = {
            'account_sid': os.getenv('TWILIO_ACCOUNT_SID') or os.getenv('TWILIO_SID'),
            'auth_token': os.getenv('TWILIO_AUTH_TOKEN'),
            'phone_number': os.getenv('TWILIO_PHONE_NUMBER')
        }
        
        # Check for TextMagic SMS configuration (alternative SMS service)
        textmagic_config = {
            'username': os.getenv('TEXTMAGIC_USERNAME'),
            'api_key': os.getenv('TEXTMAGIC_API_KEY')
        }
        
        # Check for traditional email SMTP configuration
        mail_configs = {
            'server': (
                os.getenv('MAIL_SERVER') or 
                os.getenv('SMTP_SERVER') or 
                current_app.config.get('MAIL_SERVER') or
                current_app.config.get('SMTP_SERVER')
            ),
            'username': (
                os.getenv('MAIL_USERNAME') or 
                os.getenv('SMTP_USERNAME') or
                os.getenv('EMAIL_USER') or
                current_app.config.get('MAIL_USERNAME') or
                current_app.config.get('SMTP_USERNAME')
            ),
            'password': (
                os.getenv('MAIL_PASSWORD') or 
                os.getenv('SMTP_PASSWORD') or
                os.getenv('EMAIL_PASSWORD') or
                current_app.config.get('MAIL_PASSWORD') or
                current_app.config.get('SMTP_PASSWORD')
            ),
            'port': (
                os.getenv('MAIL_PORT') or 
                os.getenv('SMTP_PORT') or
                current_app.config.get('MAIL_PORT') or
                current_app.config.get('SMTP_PORT', 587)
            )
        }
        
        # Count configured services
        twilio_configured = all(twilio_config.values())
        textmagic_configured = all(textmagic_config.values())
        email_configured = sum(1 for v in mail_configs.values() if v) >= 3
        
        active_services = []
        if twilio_configured:
            active_services.append(f"Twilio SMS ({twilio_config['phone_number']})")
        if textmagic_configured:
            active_services.append(f"TextMagic SMS ({textmagic_config['username']})")
        if email_configured:
            active_services.append(f"SMTP ({mail_configs['server']})")
        
        if not active_services:
            # Check if Flask-Mail is configured
            try:
                from flask_mail import Mail
                mail = current_app.extensions.get('mail')
                if mail:
                    return {
                        'name': 'Email Service',
                        'status': 'healthy',
                        'message': 'Flask-Mail configured',
                        'last_check': datetime.utcnow(),
                        'response_time': 'N/A'
                    }
            except Exception:
                pass
            
            return {
                'name': 'Email Service',
                'status': 'warning',
                'message': 'No communication services configured',
                'last_check': datetime.utcnow(),
                'response_time': 'N/A'
            }
        
        # Test Twilio connection if configured
        if twilio_configured:
            try:
                import requests
                start_time = datetime.utcnow()
                
                # Test Twilio API authentication
                auth = (twilio_config['account_sid'], twilio_config['auth_token'])
                response = requests.get(
                    f"https://api.twilio.com/2010-04-01/Accounts/{twilio_config['account_sid']}.json",
                    auth=auth,
                    timeout=5
                )
                
                end_time = datetime.utcnow()
                response_time = f"{(end_time - start_time).total_seconds() * 1000:.0f}ms"
                
                if response.status_code == 200:
                    account_data = response.json()
                    account_status = account_data.get('status', 'unknown')
                    return {
                        'name': 'Email Service',
                        'status': 'healthy',
                        'message': f'Twilio SMS active (status: {account_status})',
                        'last_check': datetime.utcnow(),
                        'response_time': response_time
                    }
                else:
                    return {
                        'name': 'Email Service',
                        'status': 'warning',
                        'message': f'Twilio auth failed: HTTP {response.status_code}',
                        'last_check': datetime.utcnow(),
                        'response_time': response_time
                    }
            except Exception as e:
                # Twilio test failed, check other services
                pass
        
        # Test SMTP connection if email is configured
        if email_configured:
            try:
                import socket
                start_time = datetime.utcnow()
                with socket.create_connection((mail_configs['server'], int(mail_configs['port'] or 587)), timeout=5):
                    pass
                end_time = datetime.utcnow()
                response_time = f"{(end_time - start_time).total_seconds() * 1000:.0f}ms"
                
                return {
                    'name': 'Email Service',
                    'status': 'healthy',
                    'message': f'SMTP server reachable ({mail_configs["server"]})',
                    'last_check': datetime.utcnow(),
                    'response_time': response_time
                }
            except Exception as e:
                return {
                    'name': 'Email Service',
                    'status': 'warning',
                    'message': f'SMTP connection failed: {str(e)[:30]}',
                    'last_check': datetime.utcnow(),
                    'response_time': 'Error'
                }
        
        # If we get here, services are configured but not tested
        return {
            'name': 'Email Service',
            'status': 'healthy',
            'message': f'Services configured: {", ".join(active_services)}',
            'last_check': datetime.utcnow(),
            'response_time': 'N/A'
        }
            
    except Exception as e:
        logger.error(f"Email service check failed: {e}")
        return {
            'name': 'Email Service',
            'status': 'error',
            'message': f'Check failed: {str(e)[:30]}',
            'last_check': datetime.utcnow(),
            'response_time': 'Error'
        }


def _check_redis_service_status():
    """Check Redis service status."""
    try:
        from app.utils.safe_redis import get_safe_redis
        
        start_time = datetime.utcnow()
        redis_client = get_safe_redis()
        
        # Test Redis connection
        redis_client.ping()
        end_time = datetime.utcnow()
        response_time = f"{(end_time - start_time).total_seconds() * 1000:.0f}ms"
        
        # Get Redis info
        try:
            redis_info = redis_client.info()
            memory_usage = redis_info.get('used_memory_human', 'Unknown')
            
            return {
                'name': 'Redis Cache',
                'status': 'healthy',
                'message': f'Connected, using {memory_usage}',
                'last_check': datetime.utcnow(),
                'response_time': response_time
            }
        except:
            return {
                'name': 'Redis Cache',
                'status': 'healthy',
                'message': 'Connected (limited info)',
                'last_check': datetime.utcnow(),
                'response_time': response_time
            }
    except Exception as e:
        return {
            'name': 'Redis Cache',
            'status': 'error',
            'message': f'Connection failed: {str(e)[:50]}',
            'last_check': datetime.utcnow(),
            'response_time': 'Error'
        }


def _check_database_service_status():
    """Check database service status."""
    try:
        from app.core import db
        from sqlalchemy import text
        
        start_time = datetime.utcnow()
        
        # Test database connection with simple query using text()
        result = db.session.execute(text('SELECT 1')).fetchone()
        
        end_time = datetime.utcnow()
        response_time = f"{(end_time - start_time).total_seconds() * 1000:.0f}ms"
        
        if result:
            return {
                'name': 'Database',
                'status': 'healthy',
                'message': 'Connection successful',
                'last_check': datetime.utcnow(),
                'response_time': response_time
            }
        else:
            return {
                'name': 'Database',
                'status': 'warning',
                'message': 'Query returned no result',
                'last_check': datetime.utcnow(),
                'response_time': response_time
            }
    except Exception as e:
        return {
            'name': 'Database',
            'status': 'error',
            'message': f'Connection failed: {str(e)[:50]}',
            'last_check': datetime.utcnow(),
            'response_time': 'Error'
        }


def _estimate_api_calls_today():
    """Estimate API calls made today based on system activity."""
    try:
        from app.models import User
        from app.models.communication import Notification, ScheduledMessage
        
        # Estimate based on various activities
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Count notifications sent today (approximate API calls)
        notifications_today = Notification.query.filter(
            Notification.created_at >= today_start
        ).count()
        
        # Count messages processed today
        messages_today = ScheduledMessage.query.filter(
            ScheduledMessage.created_at >= today_start
        ).count()
        
        # User activity (login/logout events)
        active_users_today = User.query.filter(
            User.last_login >= today_start
        ).count() if hasattr(User, 'last_login') else 0
        
        # Rough estimate: notifications * 2 + messages * 3 + user activity * 5
        estimated_calls = (notifications_today * 2) + (messages_today * 3) + (active_users_today * 5)
        
        return max(estimated_calls, 50)  # Minimum baseline
    except Exception as e:
        logger.error(f"Error estimating API calls: {e}")
        return 0


def _calculate_avg_response_time():
    """Average request response time over the last 24h, from real request logs.

    Computed from APIRequestLog.response_time_ms (the same table that backs the
    System Performance page). Returns a formatted 'NNms' string, or 'N/A' when no
    requests have been logged yet — never a fabricated estimate."""
    try:
        from datetime import datetime, timedelta
        from app.models.api_logs import APIRequestLog
        from sqlalchemy import func
        cutoff = datetime.utcnow() - timedelta(hours=24)
        avg_ms = db.session.query(func.avg(APIRequestLog.response_time_ms)).filter(
            APIRequestLog.timestamp >= cutoff
        ).scalar()
        if avg_ms is None:
            return "N/A"
        return f"{int(round(avg_ms))}ms"
    except Exception as e:
        logger.error(f"Error calculating response time: {e}")
        return "N/A"


def _get_system_performance_metrics():
    """Get real system performance metrics."""
    try:
        import psutil
        import os
        from datetime import timedelta
        
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        
        # Disk usage
        disk = psutil.disk_usage('/')
        disk_percent = (disk.used / disk.total) * 100
        
        # System uptime
        boot_time = psutil.boot_time()
        uptime_seconds = datetime.utcnow().timestamp() - boot_time
        uptime = str(timedelta(seconds=int(uptime_seconds)))
        
        # Load average (Unix-like systems only)
        try:
            load_avg = os.getloadavg()
            load_average = f"{load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}"
        except (OSError, AttributeError):
            load_average = "N/A (Windows)"
        
        # Network connections
        try:
            connections = len(psutil.net_connections())
        except psutil.AccessDenied:
            connections = 0
        
        return {
            'cpu_usage': round(cpu_percent, 1),
            'memory_usage': round(memory_percent, 1),
            'disk_usage': round(disk_percent, 1),
            'uptime': uptime,
            'load_average': load_average,
            'active_connections': connections
        }
    except ImportError:
        logger.warning("psutil not available, returning zero metrics")
        return {
            'cpu_usage': 0,
            'memory_usage': 0,
            'disk_usage': 0,
            'uptime': 'Unknown',
            'load_average': 'Unknown',
            'active_connections': 0
        }
    except Exception as e:
        logger.error(f"Error getting system metrics: {e}")
        return {
            'cpu_usage': 0,
            'memory_usage': 0,
            'disk_usage': 0,
            'uptime': 'Error',
            'load_average': 'Error',
            'active_connections': 0
        }


# Utility function to check if admin panel features are enabled
def is_admin_panel_feature_enabled(feature_key):
    """Check if an admin panel feature is enabled."""
    from app.models.admin_config import AdminConfig
    return AdminConfig.get_setting(feature_key, default=True)


def _playoff_round_label(round_number):
    """
    Map a numeric playoff_round to a human-friendly stage label.

    The Match.playoff_round column is just an integer (1, 2, ...). There is no
    Tournament model that defines named rounds, so we infer a sensible label
    from the round number. Higher round numbers are later stages.
    """
    labels = {
        1: 'Round 1',
        2: 'Quarterfinals',
        3: 'Semifinals',
        4: 'Final',
    }
    if round_number is None:
        return 'Playoffs'
    return labels.get(round_number, f'Round {round_number}')


def get_playoff_stats():
    """
    Get real playoff statistics from the database.

    Aggregates flagged playoff matches (Match.is_playoff_game) and also groups
    them per league/season so the UI can render a "Current Playoffs" view with
    real per-group counts, current stage (from the max playoff_round that still
    has unreported matches), and a progress bar. No Tournament model exists, so
    the league+season is treated as the grouping key. Only real Match fields
    are used; nothing is fabricated.

    Returns:
        dict: Aggregate ints (active_playoffs, completed_playoffs,
            upcoming_matches, playoff_teams) plus a `tournaments` list of
            per-group dicts.
    """
    empty = {
        'active_playoffs': 0,
        'completed_playoffs': 0,
        'upcoming_matches': 0,
        'playoff_teams': 0,
        'tournaments': [],
    }
    try:
        from app.models.matches import Match
        from app.models.core import Season
        from datetime import datetime, timedelta

        # Get current season for context (presence gates the rest, matching
        # prior behavior). If there is no current season, there is nothing to show.
        current_season = Season.query.filter_by(
            is_current=True
        ).first()

        if not current_season:
            return dict(empty)

        # Query all playoff matches, eager-loading the team->league->season chain
        # so per-group naming does not trigger N+1 queries.
        from sqlalchemy.orm import joinedload
        playoff_matches = (
            Match.query
            .options(
                joinedload(Match.home_team),
                joinedload(Match.away_team),
            )
            .filter(Match.is_playoff_game == True)  # noqa: E712
            .all()
        )

        if not playoff_matches:
            return dict(empty)

        today = datetime.utcnow().date()
        next_week = today + timedelta(days=7)

        def _reported(m):
            return m.home_team_score is not None and m.away_team_score is not None

        # Aggregate counts (unchanged semantics).
        active_playoffs = len([m for m in playoff_matches if not _reported(m)])
        completed_playoffs = len([m for m in playoff_matches if _reported(m)])
        upcoming_matches = len([
            m for m in playoff_matches
            if m.date and today <= m.date <= next_week and m.home_team_score is None
        ])

        playoff_team_ids = set()
        for match in playoff_matches:
            if match.home_team_id:
                playoff_team_ids.add(match.home_team_id)
            if match.away_team_id:
                playoff_team_ids.add(match.away_team_id)

        # Group playoff matches by league so each group can be presented as a
        # "tournament" card. We key on the home team's league_id; matches whose
        # team/league can't be resolved fall into an "Unassigned" bucket.
        groups = {}
        for m in playoff_matches:
            league = None
            team = m.home_team or m.away_team
            if team is not None:
                league = getattr(team, 'league', None)
            league_id = getattr(league, 'id', None)
            key = league_id if league_id is not None else 'unassigned'

            grp = groups.get(key)
            if grp is None:
                if league is not None:
                    season = getattr(league, 'season', None)
                    season_name = getattr(season, 'name', None)
                    name = league.name
                    if season_name:
                        name = f"{league.name} · {season_name}"
                else:
                    name = 'Unassigned Playoffs'
                grp = {
                    'league_id': league_id,
                    'name': name,
                    'team_ids': set(),
                    'completed': 0,
                    'remaining': 0,
                    'total': 0,
                    'max_open_round': None,
                    'max_round': None,
                }
                groups[key] = grp

            grp['total'] += 1
            if m.home_team_id:
                grp['team_ids'].add(m.home_team_id)
            if m.away_team_id:
                grp['team_ids'].add(m.away_team_id)

            rnd = m.playoff_round
            if rnd is not None:
                grp['max_round'] = rnd if grp['max_round'] is None else max(grp['max_round'], rnd)

            if _reported(m):
                grp['completed'] += 1
            else:
                grp['remaining'] += 1
                # Current stage = the highest round that still has unreported matches.
                if rnd is not None:
                    grp['max_open_round'] = (
                        rnd if grp['max_open_round'] is None else max(grp['max_open_round'], rnd)
                    )

        # Resolve a real per-league "format" label from stored season config.
        # SeasonConfiguration.playoff_weeks is the only stored structural fact
        # about the playoff format (there is no Tournament / bracket-type model),
        # so we surface that rather than inventing single/double-elimination.
        # Looked up once per league_id present in the groups.
        from app.models.matches import SeasonConfiguration
        league_ids = [
            grp['league_id'] for grp in groups.values()
            if grp.get('league_id') is not None
        ]
        playoff_weeks_by_league = {}
        if league_ids:
            try:
                configs = (
                    SeasonConfiguration.query
                    .filter(SeasonConfiguration.league_id.in_(league_ids))
                    .all()
                )
                for cfg in configs:
                    if cfg.playoff_weeks is not None:
                        playoff_weeks_by_league[cfg.league_id] = cfg.playoff_weeks
            except Exception as cfg_err:
                # Missing table / column should never 500 this page.
                logger.warning(f"Could not load SeasonConfiguration for playoff format: {cfg_err}")

        tournaments = []
        for grp in groups.values():
            total = grp['total']
            completed = grp['completed']
            pct = (completed * 100 // total) if total > 0 else 0
            # Prefer the highest round with open matches for the "current stage";
            # if everything is reported fall back to the highest round overall.
            stage_round = grp['max_open_round'] if grp['max_open_round'] is not None else grp['max_round']

            # Real format label, only if the season config actually stores it.
            # Falls back to the number of distinct playoff rounds actually
            # scheduled (max_round) when no SeasonConfiguration row exists.
            weeks = playoff_weeks_by_league.get(grp['league_id'])
            if weeks is None and grp['max_round'] is not None:
                weeks = grp['max_round']
            format_label = None
            if weeks:
                format_label = f"{weeks} playoff {'week' if weeks == 1 else 'weeks'}"

            tournaments.append({
                'league_id': grp['league_id'],
                'name': grp['name'],
                'team_count': len(grp['team_ids']),
                'completed': completed,
                'remaining': grp['remaining'],
                'total': total,
                'progress_pct': pct,
                'stage': _playoff_round_label(stage_round),
                'format_label': format_label,
            })

        # Stable, readable ordering: most matches first, then name.
        tournaments.sort(key=lambda t: (-t['total'], t['name']))

        return {
            'active_playoffs': active_playoffs,
            'completed_playoffs': completed_playoffs,
            'upcoming_matches': upcoming_matches,
            'playoff_teams': len(playoff_team_ids),
            'tournaments': tournaments,
        }
    except Exception as e:
        logger.error(f"Error getting playoff stats: {e}")
        return dict(empty)