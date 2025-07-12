#!/usr/bin/env python3
"""
Query scheduled_messages table for a specific record
"""

import os
import sys
import logging
from datetime import datetime
from pprint import pprint

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from sqlalchemy import text
from app import create_app
from app.core.session_manager import managed_session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def query_scheduled_message(message_id):
    """Query scheduled_messages table for a specific record"""
    app = create_app()
    
    try:
        with app.app_context():
            with managed_session() as session:
                # Query the specific record
                query = text("""
                    SELECT 
                        id,
                        match_id,
                        scheduled_send_time,
                        status,
                        message_type,
                        message_metadata,
                        created_by,
                        created_at,
                        updated_at,
                        last_send_attempt,
                        sent_at,
                        send_error,
                        task_name,
                        home_channel_id,
                        home_message_id,
                        away_channel_id,
                        away_message_id
                    FROM scheduled_messages 
                    WHERE id = :message_id
                """)
                
                result = session.execute(query, {"message_id": message_id}).fetchone()
                
                if result:
                    # Convert result to dictionary for better display
                    columns = [
                        'id', 'match_id', 'scheduled_send_time', 'status', 'message_type',
                        'message_metadata', 'created_by', 'created_at', 'updated_at',
                        'last_send_attempt', 'sent_at', 'send_error', 'task_name',
                        'home_channel_id', 'home_message_id', 'away_channel_id', 'away_message_id'
                    ]
                    
                    record = dict(zip(columns, result))
                    
                    print(f"Scheduled Message Record (ID: {message_id})")
                    print("=" * 60)
                    
                    for key, value in record.items():
                        if key == 'message_metadata':
                            print(f"{key:20}: {value}")
                            if value:
                                print("    Metadata details:")
                                try:
                                    # If it's already a dict, pretty print it
                                    if isinstance(value, dict):
                                        for k, v in value.items():
                                            print(f"      {k}: {v}")
                                    else:
                                        print(f"      {value}")
                                except Exception as e:
                                    print(f"      Error parsing metadata: {e}")
                        elif key in ['scheduled_send_time', 'created_at', 'updated_at', 'last_send_attempt', 'sent_at']:
                            print(f"{key:20}: {value}")
                        else:
                            print(f"{key:20}: {value}")
                    
                    return record
                else:
                    print(f"No record found with ID: {message_id}")
                    return None
                    
    except Exception as e:
        logger.error(f"Error querying database: {e}")
        return None

if __name__ == "__main__":
    message_id = 188
    if len(sys.argv) > 1:
        try:
            message_id = int(sys.argv[1])
        except ValueError:
            print("Usage: python query_scheduled_message.py [message_id]")
            sys.exit(1)
    
    result = query_scheduled_message(message_id)
    
    if result and result.get('message_metadata'):
        print("\n" + "=" * 60)
        print("ANALYSIS:")
        print("=" * 60)
        
        metadata = result['message_metadata']
        message_type = result['message_type']
        
        print(f"Message Type: {message_type}")
        
        if message_type == 'ecs_fc_rsvp':
            if isinstance(metadata, dict):
                ecs_fc_match_id = metadata.get('ecs_fc_match_id')
                if ecs_fc_match_id:
                    print(f"ECS FC Match ID found: {ecs_fc_match_id}")
                    print("This explains why the ECS FC task is working correctly.")
                else:
                    print("NO ECS FC Match ID found in metadata!")
                    print("This explains the error: 'No ECS FC match ID in scheduled message metadata'")
            else:
                print("Metadata is not a dictionary - may be stored as string")
        else:
            print(f"This is not an ECS FC RSVP message (type: {message_type})")