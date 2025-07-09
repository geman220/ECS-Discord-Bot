#!/usr/bin/env python3
"""
Query scheduled_messages table using Flask application context
"""

import os
import sys
import logging
from datetime import datetime
from pprint import pprint

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.core import db
from app.models import ScheduledMessage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def query_scheduled_message_flask(message_id):
    """Query scheduled_messages table using Flask ORM"""
    try:
        # Create Flask application
        app = create_app()
        
        with app.app_context():
            # Query the specific record
            record = ScheduledMessage.query.filter_by(id=message_id).first()
            
            if record:
                print(f"Scheduled Message Record (ID: {message_id})")
                print("=" * 60)
                
                # Display all fields
                fields = [
                    'id', 'match_id', 'scheduled_send_time', 'status', 'message_type',
                    'message_metadata', 'created_by', 'created_at', 'updated_at',
                    'last_send_attempt', 'sent_at', 'send_error', 'task_name',
                    'home_channel_id', 'home_message_id', 'away_channel_id', 'away_message_id'
                ]
                
                record_dict = {}
                for field in fields:
                    value = getattr(record, field, None)
                    record_dict[field] = value
                    
                    if field == 'message_metadata':
                        print(f"{field:20}: {value}")
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
                    elif field in ['scheduled_send_time', 'created_at', 'updated_at', 'last_send_attempt', 'sent_at']:
                        print(f"{field:20}: {value}")
                    else:
                        print(f"{field:20}: {value}")
                
                return record_dict
            else:
                print(f"No record found with ID: {message_id}")
                return None
                
    except Exception as e:
        logger.error(f"Error querying database: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    message_id = 188
    if len(sys.argv) > 1:
        try:
            message_id = int(sys.argv[1])
        except ValueError:
            print("Usage: python flask_query_scheduled_message.py [message_id]")
            sys.exit(1)
    
    result = query_scheduled_message_flask(message_id)
    
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
                print("Metadata type:", type(metadata))
                print("Metadata value:", metadata)
        else:
            print(f"This is not an ECS FC RSVP message (type: {message_type})")
            
    elif result:
        print("\n" + "=" * 60)
        print("ANALYSIS:")
        print("=" * 60)
        print("No message_metadata found in this record.")
        print("This explains the error: 'No ECS FC match ID in scheduled message metadata'")
        
    print("\nTo fix this issue, you need to:")
    print("1. Check how ECS FC scheduled messages are created")
    print("2. Ensure the 'message_metadata' field contains {'ecs_fc_match_id': <actual_match_id>}")
    print("3. Verify the message_type is set to 'ecs_fc_rsvp' for ECS FC messages")