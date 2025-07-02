#!/usr/bin/env python3
"""
Image Cache Management Script

Commands for managing player profile image optimization and caching.
Optimizes images for fast loading in draft system with 200+ players.
"""

import sys
import logging
from pathlib import Path

from app import create_app
from app.core import db
from app.image_cache_service import ImageCacheService
from app.models import Player, PlayerImageCache

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_image_cache():
    """Initialize image cache and optimize all player images."""
    app = create_app()
    with app.app_context():
        try:
            logger.info("🖼️  Initializing image cache...")
            
            # Create cache directories
            ImageCacheService.initialize_cache_directory()
            
            # Get all current players with images
            players_with_images = Player.query.filter(
                Player.is_current_player == True,
                Player.profile_picture_url.isnot(None),
                Player.profile_picture_url != ''
            ).all()
            
            logger.info(f"Found {len(players_with_images)} players with profile pictures")
            
            if len(players_with_images) == 0:
                logger.warning("No players with images found!")
                return
            
            # Bulk optimize images
            player_ids = [p.id for p in players_with_images]
            results = ImageCacheService.bulk_optimize_images(player_ids)
            
            print(f"\n📊 Image Optimization Results:")
            print(f"   ✅ Successfully optimized: {results['success']}")
            print(f"   ❌ Failed to optimize: {results['failed']}")
            print(f"   ⏭️  Skipped (already done): {results['skipped']}")
            
            if results['success'] > 0:
                logger.info("✅ Image cache initialization completed successfully!")
            else:
                logger.warning("⚠️  No images were optimized")
                
        except Exception as e:
            logger.error(f"❌ Error initializing image cache: {e}")
            sys.exit(1)


def optimize_player_image(player_id):
    """Optimize image for a specific player."""
    app = create_app()
    with app.app_context():
        try:
            player = Player.query.get(player_id)
            if not player:
                logger.error(f"Player {player_id} not found")
                sys.exit(1)
            
            if not player.profile_picture_url:
                logger.warning(f"Player {player.name} has no profile picture")
                return
            
            logger.info(f"🖼️  Optimizing image for {player.name}...")
            success = ImageCacheService.optimize_player_image(player_id, force_refresh=True)
            
            if success:
                logger.info("✅ Image optimization completed successfully!")
            else:
                logger.error("❌ Image optimization failed!")
                sys.exit(1)
                
        except Exception as e:
            logger.error(f"❌ Error optimizing image: {e}")
            sys.exit(1)


def show_cache_status():
    """Show image cache status and statistics."""
    app = create_app()
    with app.app_context():
        try:
            # Get cache statistics
            total_players = Player.query.filter_by(is_current_player=True).count()
            players_with_images = Player.query.filter(
                Player.is_current_player == True,
                Player.profile_picture_url.isnot(None),
                Player.profile_picture_url != ''
            ).count()
            
            cache_entries = PlayerImageCache.query.count()
            optimized_count = PlayerImageCache.query.filter_by(is_optimized=True).count()
            pending_count = PlayerImageCache.query.filter_by(cache_status='pending').count()
            failed_count = PlayerImageCache.query.filter_by(cache_status='failed').count()
            
            print(f"\n📊 Image Cache Status:")
            print(f"   • Total current players: {total_players}")
            print(f"   • Players with images: {players_with_images}")
            print(f"   • Cache entries: {cache_entries}")
            print(f"   • Optimized images: {optimized_count}")
            print(f"   • Pending optimization: {pending_count}")
            print(f"   • Failed optimization: {failed_count}")
            
            if players_with_images > 0:
                coverage = (optimized_count / players_with_images) * 100
                print(f"   • Optimization coverage: {coverage:.1f}%")
            
            # Show cache directory size
            cache_dir = Path("app/static/img/cache/players")
            if cache_dir.exists():
                total_size = sum(f.stat().st_size for f in cache_dir.rglob('*') if f.is_file())
                size_mb = total_size / (1024 * 1024)
                print(f"   • Cache directory size: {size_mb:.1f} MB")
            
            # Show sample optimized images
            if optimized_count > 0:
                print(f"\n📝 Sample Optimized Images:")
                sample_cache = PlayerImageCache.query.filter_by(is_optimized=True).limit(5).all()
                for cache in sample_cache:
                    size_kb = cache.file_size / 1024 if cache.file_size else 0
                    print(f"   • Player {cache.player_id}: {cache.width}x{cache.height}, {size_kb:.1f}KB")
            
        except Exception as e:
            logger.error(f"❌ Error showing cache status: {e}")
            sys.exit(1)


def cleanup_cache():
    """Clean up expired cache entries and orphaned files."""
    app = create_app()
    with app.app_context():
        try:
            logger.info("🧹 Cleaning up image cache...")
            
            # Use the service cleanup method
            ImageCacheService.cleanup_expired_cache()
            
            # Also clean up orphaned cache entries (players no longer exist)
            orphaned_entries = db.session.query(PlayerImageCache).outerjoin(
                Player, PlayerImageCache.player_id == Player.id
            ).filter(Player.id.is_(None)).all()
            
            if orphaned_entries:
                logger.info(f"Removing {len(orphaned_entries)} orphaned cache entries...")
                for entry in orphaned_entries:
                    db.session.delete(entry)
                db.session.commit()
            
            logger.info("✅ Cache cleanup completed!")
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up cache: {e}")
            sys.exit(1)


def test_image_loading():
    """Test image loading performance with a sample of players."""
    app = create_app()
    with app.app_context():
        try:
            import time
            
            logger.info("🚀 Testing image loading performance...")
            
            # Get a sample of players (like what draft system would load)
            sample_players = Player.query.filter(
                Player.is_current_player == True,
                Player.profile_picture_url.isnot(None)
            ).limit(50).all()
            
            if not sample_players:
                logger.warning("No players found for testing")
                return
            
            player_ids = [p.id for p in sample_players]
            
            # Test performance
            start_time = time.time()
            image_data = ImageCacheService.get_player_image_data(player_ids)
            end_time = time.time()
            
            elapsed_ms = (end_time - start_time) * 1000
            
            print(f"\n🚀 Performance Test Results:")
            print(f"   • Players tested: {len(sample_players)}")
            print(f"   • Lookup time: {elapsed_ms:.1f}ms")
            print(f"   • Average per player: {elapsed_ms/len(sample_players):.2f}ms")
            
            # Check optimization status
            optimized_count = sum(1 for data in image_data.values() if data.get('is_optimized', False))
            print(f"   • Optimized images: {optimized_count}/{len(sample_players)}")
            
            if elapsed_ms < 100:
                print("   ✅ Performance: Excellent!")
            elif elapsed_ms < 500:
                print("   ✅ Performance: Good")
            else:
                print("   ⚠️  Performance: Could be improved")
            
        except Exception as e:
            logger.error(f"❌ Error testing image loading: {e}")
            sys.exit(1)


def main():
    """Main command dispatcher."""
    if len(sys.argv) < 2:
        print("""
🖼️  Image Cache Management Commands:

   python manage_images.py init
      Initialize image cache and optimize all player images

   python manage_images.py optimize <player_id>
      Optimize image for a specific player

   python manage_images.py status
      Show image cache status and statistics

   python manage_images.py cleanup
      Clean up expired cache entries and orphaned files

   python manage_images.py test
      Test image loading performance

Examples:
   python manage_images.py init
   python manage_images.py optimize 123
   python manage_images.py status
   python manage_images.py cleanup
   python manage_images.py test
        """)
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'init':
        init_image_cache()
    elif command == 'optimize':
        if len(sys.argv) < 3:
            print("❌ Error: Player ID required")
            sys.exit(1)
        player_id = int(sys.argv[2])
        optimize_player_image(player_id)
    elif command == 'status':
        show_cache_status()
    elif command == 'cleanup':
        cleanup_cache()
    elif command == 'test':
        test_image_loading()
    else:
        print(f"❌ Unknown command: {command}")
        sys.exit(1)


if __name__ == '__main__':
    main()