#!/usr/bin/env python3
"""
Test script for team notification system

This script tests the new team notification functionality by:
1. Testing the team member lookup endpoint
2. Testing the notification sending endpoint (without actually sending)
"""

import requests
import json

# Configuration
BASE_URL = "http://webui:5000"  # Docker service name
TEST_TEAM_ROLE = "ECS-FC-PL-TEAM-H-PLAYER"  # Update this to an actual team role from your Discord

def test_team_members_lookup():
    """Test the team members lookup endpoint"""
    print(f"🔍 Testing team members lookup for: {TEST_TEAM_ROLE}")
    
    url = f"{BASE_URL}/api/team-notifications/teams/{TEST_TEAM_ROLE}/members"
    
    try:
        response = requests.get(url)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("✅ Team members lookup successful!")
            print(f"Team DB Name: {data.get('team_db_name')}")
            print(f"Total Members: {data.get('total_members')}")
            print(f"Members with Push Tokens: {data.get('total_with_tokens')}")
            
            if data.get('members'):
                print("\\n👥 Team Members:")
                for member in data['members'][:5]:  # Show first 5
                    print(f"  - {member['player_name']} ({member['username']})")
                    print(f"    Discord ID: {member['discord_id']}")
                    print(f"    Has Push Token: {member['has_active_token']}")
                    print()
        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"❌ Exception occurred: {e}")

def test_team_notification_send():
    """Test the team notification sending endpoint (dry run)"""
    print(f"\\n📱 Testing team notification send for: {TEST_TEAM_ROLE}")
    
    url = f"{BASE_URL}/api/team-notifications/send"
    
    payload = {
        "team_name": TEST_TEAM_ROLE,
        "message": "🧪 This is a test message from the team notification system!",
        "coach_discord_id": "123456789012345678",  # Mock Discord ID
        "title": "⚽ Test Team Message"
    }
    
    try:
        response = requests.post(url, json=payload)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("✅ Team notification send successful!")
            print(f"Team: {data.get('team_name')}")
            print(f"Tokens sent to: {data.get('tokens_sent_to')}")
            print(f"Result: {data.get('result')}")
        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"❌ Exception occurred: {e}")

def main():
    print("🚀 Starting Team Notification System Tests\\n")
    
    # Test team members lookup
    test_team_members_lookup()
    
    # Test notification sending
    test_team_notification_send()
    
    print("\\n✨ Tests completed!")

if __name__ == "__main__":
    main()