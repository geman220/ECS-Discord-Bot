#!/usr/bin/env python3
"""
Debug script to check player image URLs
"""

from app import create_app
from app.models import Player

def debug_player_images():
    app = create_app()
    with app.app_context():
        # Check all current players
        players = Player.query.filter_by(is_current_player=True).all()
        print(f"Total current players: {len(players)}")
        
        # Check how many have profile pictures
        players_with_images = []
        for player in players:
            if player.profile_picture_url and player.profile_picture_url.strip():
                players_with_images.append(player)
        
        print(f"Players with profile pictures: {len(players_with_images)}")
        
        # Show sample URLs
        print("\nSample profile picture URLs:")
        for i, player in enumerate(players_with_images[:10]):
            print(f"  {player.id}: {player.name} -> {player.profile_picture_url}")
        
        if len(players_with_images) > 10:
            print(f"  ... and {len(players_with_images) - 10} more")
        
        # Check for common patterns
        url_types = {}
        for player in players_with_images:
            url = player.profile_picture_url
            if url.startswith('/static/'):
                url_types['local_static'] = url_types.get('local_static', 0) + 1
            elif url.startswith('http'):
                url_types['external_http'] = url_types.get('external_http', 0) + 1
            else:
                url_types['other'] = url_types.get('other', 0) + 1
        
        print(f"\nURL types found:")
        for url_type, count in url_types.items():
            print(f"  {url_type}: {count}")

if __name__ == '__main__':
    debug_player_images()