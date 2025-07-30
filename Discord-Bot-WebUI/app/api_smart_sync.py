# app/api_smart_sync.py

"""
Flask API endpoints to support the smart RSVP sync system.

These endpoints help the Discord bot determine what needs syncing
after container restarts by tracking bot online status and RSVP activity.
"""

from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from sqlalchemy import text
from app.models import db
from app.models.core import DiscordBotStatus
from app.models.communication import ScheduledMessage
from app.models.matches import Match

logger = logging.getLogger(__name__)

smart_sync_bp = Blueprint('smart_sync', __name__)

@smart_sync_bp.route('/api/discord_bot_last_online', methods=['GET'])
def get_discord_bot_last_online():
    """
    Get the last known online timestamp for the Discord bot.
    
    This helps the bot determine if sync is needed after startup.
    Returns None if this is the first startup.
    """
    try:
        # Query the bot status using SQLAlchemy model
        bot_status = DiscordBotStatus.query.filter_by(instance_type='main').first()
        
        if bot_status and bot_status.last_online:
            return jsonify({
                'success': True,
                'last_online': bot_status.last_online.isoformat(),
                'message': 'Last online timestamp retrieved'
            })
        else:
            return jsonify({
                'success': True,
                'last_online': None,
                'message': 'No previous online timestamp found'
            })
            
    except Exception as e:
        logger.error(f"Error getting Discord bot last online time: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@smart_sync_bp.route('/api/discord_bot_last_online', methods=['POST'])
def update_discord_bot_last_online():
    """
    Update the last known online timestamp for the Discord bot.
    
    Called by the bot during startup and periodically as a heartbeat.
    """
    try:
        data = request.get_json()
        instance_id = data.get('instance_id', 'unknown')
        last_online = datetime.fromisoformat(data.get('last_online'))
        
        # Upsert the bot status using SQLAlchemy
        bot_status = DiscordBotStatus.query.filter_by(instance_type='main').first()
        
        if bot_status:
            # Update existing record
            bot_status.instance_id = instance_id
            bot_status.last_online = last_online
            bot_status.last_updated = datetime.utcnow()
        else:
            # Create new record
            bot_status = DiscordBotStatus(
                instance_type='main',
                instance_id=instance_id,
                last_online=last_online,
                last_updated=datetime.utcnow()
            )
            db.session.add(bot_status)
        
        db.session.commit()
        
        logger.debug(f"Updated Discord bot last online time: {last_online}")
        
        return jsonify({
            'success': True,
            'message': 'Last online timestamp updated',
            'timestamp': last_online.isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error updating Discord bot last online time: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@smart_sync_bp.route('/api/matches_with_rsvp_activity_since', methods=['GET'])
def get_matches_with_rsvp_activity_since():
    """
    Get matches that had RSVP message posting activity since a given timestamp.
    
    This helps the bot determine which matches need syncing after downtime.
    Only returns matches that:
    1. Had RSVP messages posted since the given timestamp
    2. Are within a reasonable time window (not ancient)
    3. Actually exist and are valid
    """
    try:
        since_str = request.args.get('since')
        limit_days = int(request.args.get('limit_days', 7))
        
        if not since_str:
            return jsonify({
                'success': False,
                'error': 'Missing required parameter: since'
            }), 400
        
        since = datetime.fromisoformat(since_str)
        
        # Get matches that had RSVP messages posted since the timestamp
        # This is the key query - it finds matches where Discord bot might have missed RSVPs
        query = text("""
            SELECT DISTINCT 
                m.id as match_id,
                m.date as match_date,
                m.home_team_id,
                m.away_team_id,
                sm.sent_at as rsvp_message_posted_at,
                COUNT(sm.id) as message_count
            FROM matches m
            JOIN scheduled_message sm ON m.id = sm.match_id
            WHERE sm.sent_at >= :since
                AND sm.message_type IN ('standard', 'rsvp')  -- RSVP-related messages
                AND sm.status = 'SENT'        -- Only successfully sent messages
                AND m.date >= :min_date       -- Not too old
                AND m.date <= :max_date       -- Not too far future
            GROUP BY m.id, m.date, m.home_team_id, m.away_team_id, sm.sent_at
            ORDER BY sm.sent_at DESC
            LIMIT 50
        """)
        
        min_date = datetime.utcnow() - timedelta(days=limit_days)
        max_date = datetime.utcnow() + timedelta(days=limit_days)
        
        results = db.session.execute(query, {
            'since': since,
            'min_date': min_date,
            'max_date': max_date
        }).fetchall()
        
        matches = []
        for row in results:
            matches.append({
                'match_id': row.match_id,
                'match_date': row.match_date.isoformat() if row.match_date else None,
                'home_team_id': row.home_team_id,
                'away_team_id': row.away_team_id,
                'rsvp_message_posted_at': row.rsvp_message_posted_at.isoformat(),
                'message_count': row.message_count
            })
        
        logger.info(f"Found {len(matches)} matches with RSVP activity since {since}")
        
        return jsonify({
            'success': True,
            'matches': matches,
            'total_count': len(matches),
            'query_params': {
                'since': since.isoformat(),
                'limit_days': limit_days
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting matches with RSVP activity: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@smart_sync_bp.route('/api/sync_stats', methods=['GET'])
def get_sync_stats():
    """
    Get statistics about sync operations for monitoring.
    
    Helpful for understanding how well the smart sync is working.
    """
    try:
        # Get recent Discord bot activity
        bot_status = DiscordBotStatus.query.filter_by(instance_type='main').first()
        
        # Get recent RSVP message posting activity
        since_time = datetime.utcnow() - timedelta(hours=24)
        message_count = ScheduledMessage.query.filter(
            ScheduledMessage.message_type.in_(['standard', 'rsvp']),
            ScheduledMessage.status == 'SENT',
            ScheduledMessage.sent_at >= since_time
        ).count()
        
        latest_message = ScheduledMessage.query.filter(
            ScheduledMessage.message_type.in_(['standard', 'rsvp']),
            ScheduledMessage.status == 'SENT',
            ScheduledMessage.sent_at >= since_time
        ).order_by(ScheduledMessage.sent_at.desc()).first()
        
        stats = {
            'bot_status': {
                'instance_id': bot_status.instance_id if bot_status else None,
                'last_online': bot_status.last_online.isoformat() if bot_status and bot_status.last_online else None,
                'last_updated': bot_status.last_updated.isoformat() if bot_status and bot_status.last_updated else None,
                'is_recent': (bot_status and bot_status.last_updated and 
                            (datetime.utcnow() - bot_status.last_updated).total_seconds() < 600) if bot_status else False
            },
            'recent_activity': {
                'rsvp_messages_24h': message_count,
                'latest_message': latest_message.sent_at.isoformat() if latest_message and latest_message.sent_at else None
            }
        }
        
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        logger.error(f"Error getting sync stats: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500