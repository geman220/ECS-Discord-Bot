# app/batch_api.py

from flask import Blueprint, request, jsonify, g
from app.models import ScheduledMessage
import logging

logger = logging.getLogger(__name__)
batch_bp = Blueprint('batch', __name__)

@batch_bp.route('/api/batch/get_message_info', methods=['POST'])
def batch_get_message_info():
    """
    Batch endpoint to get message info for multiple message IDs in a single query.
    Reduces database connections from N requests to 1 request.
    
    POST body: {"message_ids": ["123", "456", "789"]}
    Returns: {"123": {...}, "456": {...}, "789": null}
    """
    try:
        data = request.get_json()
        if not data or 'message_ids' not in data:
            return jsonify({'error': 'Missing message_ids in request body'}), 400
        
        message_ids = [str(msg_id) for msg_id in data['message_ids']]
        if not message_ids:
            return jsonify({'error': 'Empty message_ids list'}), 400
        
        logger.info(f"Batch lookup for {len(message_ids)} message IDs")
        
        # Single query for all message IDs
        session_db = g.db_session
        scheduled_msgs = session_db.query(ScheduledMessage).filter(
            (ScheduledMessage.home_message_id.in_(message_ids)) | 
            (ScheduledMessage.away_message_id.in_(message_ids))
        ).all()
        
        # Build response mapping
        results = {}
        
        # Initialize all as None
        for msg_id in message_ids:
            results[msg_id] = None
        
        # Fill in found messages
        for msg in scheduled_msgs:
            msg_info = {
                'channel_id': msg.channel_id,
                'match_id': msg.match_id,
                'team_id': msg.team_id,
                'is_home': None,
                'message_type': None,
                'match_date': str(msg.match.date) if msg.match else None,
                'match_time': str(msg.match.time) if msg.match else None,
                'is_recent_match': False  # Calculate based on your logic
            }
            
            # Check if this is home or away message
            if msg.home_message_id in message_ids:
                results[msg.home_message_id] = {**msg_info, 'is_home': True, 'message_type': 'home'}
            if msg.away_message_id in message_ids:
                results[msg.away_message_id] = {**msg_info, 'is_home': False, 'message_type': 'away'}
        
        logger.info(f"Found {len([r for r in results.values() if r])} messages out of {len(message_ids)}")
        return jsonify(results)
        
    except Exception as e:
        logger.error(f"Error in batch_get_message_info: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500