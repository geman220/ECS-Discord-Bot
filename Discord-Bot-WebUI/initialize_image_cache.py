#!/usr/bin/env python3
"""
Initialize Image Cache for All Players

This script initializes the image cache for all current players to ensure
fast loading in the draft system.
"""

import os
import sys

# Add the project root to Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from app.image_cache_service import ImageCacheService
from app.models import Player

def main():
    app = create_app()
    
    with app.app_context():
        print("🚀 Initializing image cache for all players...")
        
        # Get all current players with profile pictures
        players = Player.query.filter(
            Player.is_current_player == True,
            Player.profile_picture_url.isnot(None),
            Player.profile_picture_url != ''
        ).all()
        
        player_ids = [p.id for p in players if p.profile_picture_url and p.profile_picture_url.strip()]
        
        print(f"📊 Found {len(player_ids)} players with profile pictures")
        
        if not player_ids:
            print("❌ No players with profile pictures found")
            return
        
        # Initialize image cache
        try:
            results = ImageCacheService.bulk_optimize_images(player_ids)
            print(f"✅ Image cache initialization completed:")
            print(f"   - Success: {results['success']} players")
            print(f"   - Failed: {results['failed']} players")
            print(f"   - Skipped: {results['skipped']} players")
            
            if results['failed'] > 0:
                print("⚠️  Some players had image optimization failures")
            else:
                print("🎉 All player images successfully optimized!")
                
        except Exception as e:
            print(f"❌ Error during image cache initialization: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()