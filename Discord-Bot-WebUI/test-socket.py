#!/usr/bin/env python3

"""
This is a test script to verify Socket.IO connection and functionality.
Run this from the command line to test if your Socket.IO server is working properly.

Example usage:
    python test-socket.py --url=http://localhost:5000 --token=your_jwt_token
"""

import argparse
import socketio
import sys
import time
import json
from urllib.parse import urlparse, parse_qs

def main():
    parser = argparse.ArgumentParser(description='Test Socket.IO connection for live reporting')
    parser.add_argument('--url', default='http://localhost:5000', help='Server URL')
    parser.add_argument('--token', help='JWT token for authentication')
    parser.add_argument('--match-id', type=int, help='Match ID for testing')
    parser.add_argument('--team-id', type=int, help='Team ID for testing')
    parser.add_argument('--namespace', default='/live', help='Socket.IO namespace')
    
    args = parser.parse_args()
    
    if not args.token:
        print("Error: JWT token is required")
        return 1
    
    # Clean token (remove Bearer prefix if present)
    clean_token = args.token
    if clean_token.startswith('Bearer '):
        clean_token = clean_token[7:]
    
    # Create Socket.IO client
    sio = socketio.Client(logger=True, engineio_logger=True)
    
    # Set up event handlers
    @sio.event(namespace=args.namespace)
    def connect():
        print(f"Connected to {args.url}{args.namespace}")
        
        # Test connection with test_connection event
        print("Testing connection...")
        sio.emit('test_connection', {'clientTime': time.time()}, namespace=args.namespace, callback=handle_test_connection)
        
        # Test ping
        print("Sending ping...")
        sio.emit('ping_server', {}, namespace=args.namespace, callback=handle_ping)
        
        # If match_id and team_id are provided, join the match
        if args.match_id and args.team_id:
            print(f"Joining match {args.match_id} for team {args.team_id}...")
            sio.emit('join_match', {
                'match_id': args.match_id,
                'team_id': args.team_id
            }, namespace=args.namespace)
    
    @sio.event(namespace=args.namespace)
    def connect_error(error):
        print(f"Connection error: {error}")
    
    @sio.event(namespace=args.namespace)
    def disconnect():
        print("Disconnected from server")
    
    # Define callback handlers
    def handle_test_connection(data):
        print("Test connection response:")
        print(json.dumps(data, indent=2))
    
    def handle_ping(data):
        print("Ping response:")
        print(json.dumps(data, indent=2))
    
    # Set up handlers for live reporting events
    @sio.on('match_state', namespace=args.namespace)
    def on_match_state(data):
        print("\nReceived match state:")
        print(json.dumps(data, indent=2))
    
    @sio.on('active_reporters', namespace=args.namespace)
    def on_active_reporters(data):
        print("\nReceived active reporters:")
        print(json.dumps(data, indent=2))
    
    @sio.on('player_shifts', namespace=args.namespace)
    def on_player_shifts(data):
        print("\nReceived player shifts:")
        print(json.dumps(data, indent=2))
    
    @sio.on('error', namespace=args.namespace)
    def on_error(data):
        print("\nReceived error:")
        print(json.dumps(data, indent=2))
    
    # Connect to server
    try:
        print(f"Connecting to {args.url}{args.namespace} with token...")
        
        # Construct query parameter with token
        url_parts = urlparse(args.url)
        query = parse_qs(url_parts.query)
        
        # Add token to query
        query['token'] = [clean_token]
        
        # Reconstruct URL with token in query
        auth_url = args.url
        
        # Connect with both methods for compatibility
        sio.connect(
            auth_url,
            headers={'Authorization': f'Bearer {clean_token}'},
            namespaces=[args.namespace],
            transports=['websocket']
        )
        
        print("Connected successfully.")
        
        # Keep the connection open for a while
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nExiting...")
        finally:
            sio.disconnect()
        
    except Exception as e:
        print(f"Error connecting to server: {e}")
        return 1
        
    return 0

if __name__ == "__main__":
    sys.exit(main())