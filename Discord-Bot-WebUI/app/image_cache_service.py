"""
High-Performance Image Caching Service

Optimizes player profile images for fast loading in draft system.
Handles 200+ player images with automatic optimization, WebP conversion,
thumbnail generation, and lazy loading strategies.
"""

import os
import logging
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from PIL import Image
import io
from pathlib import Path

from app.core import db
from app.utils.path_validator import validate_path_within_directory, PathTraversalError
from app.models import Player, PlayerImageCache

logger = logging.getLogger(__name__)


class ImageCacheService:
    """Service for high-performance player image caching and optimization."""
    
    # Configuration
    CACHE_DIR = Path("app/static/img/cache/players")
    THUMBNAIL_SIZE = (80, 80)  # For draft list view
    MEDIUM_SIZE = (200, 200)   # For detailed view
    WEBP_QUALITY = 85
    JPEG_QUALITY = 90
    CACHE_EXPIRY_DAYS = 30
    
    @classmethod
    def initialize_cache_directory(cls):
        """Create cache directories if they don't exist."""
        cls.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (cls.CACHE_DIR / "thumbnails").mkdir(exist_ok=True)
        (cls.CACHE_DIR / "medium").mkdir(exist_ok=True)
        (cls.CACHE_DIR / "webp").mkdir(exist_ok=True)
    
    @staticmethod
    def get_player_image_data(player_ids: List[int], session=None) -> Dict[int, Dict]:
        """
        OPTIMIZED: Fast bulk lookup of optimized image URLs for multiple players.
        Returns cached URLs for immediate loading with minimal database hits.
        """
        try:
            # Single query to get both cache data and player data
            from sqlalchemy.orm import joinedload
            from app.core import db
            
            # Use provided session or fall back to managed session
            if session is None:
                from app.core.session_manager import managed_session
                with managed_session() as session:
                    return ImageCacheService.get_player_image_data(player_ids, session)
            
            
            # Get cached image data with a single query
            cached_images_query = session.query(PlayerImageCache).filter(
                PlayerImageCache.player_id.in_(player_ids),
                PlayerImageCache.cache_status == 'ready'
            )
            
            # Get players data in the same transaction for missing cache entries
            players_query = session.query(Player).filter(
                Player.id.in_(player_ids)
            )
            
            # Execute queries and build lookup maps
            cached_images = {img.player_id: img for img in cached_images_query.all()}
            all_players = {p.id: p for p in players_query.all()}
            
            result = {}
            
            # Process cached images first (fastest path)
            for player_id, cache_entry in cached_images.items():
                result[player_id] = {
                    'thumbnail_url': cache_entry.thumbnail_url or cache_entry.original_url,
                    'medium_url': cache_entry.cached_url or cache_entry.original_url,
                    'webp_url': cache_entry.webp_url or cache_entry.original_url,
                    'original_url': cache_entry.original_url,
                    'is_optimized': cache_entry.is_optimized,
                    'file_size': cache_entry.file_size or 0
                }
            
            # Handle players without cached images
            players_without_cache = set(player_ids) - set(cached_images.keys())
            optimization_queue = []  # Batch queue for optimization
            
            for player_id in players_without_cache:
                player = all_players.get(player_id)
                if player and player.profile_picture_url:
                    result[player_id] = {
                        'thumbnail_url': player.profile_picture_url,
                        'medium_url': player.profile_picture_url,
                        'webp_url': player.profile_picture_url,
                        'original_url': player.profile_picture_url,
                        'is_optimized': False,
                        'file_size': 0
                    }
                    # Add to batch optimization queue
                    optimization_queue.append((player.id, player.profile_picture_url))
                else:
                    # Use default image for players without profile pictures
                    default_image = "/static/img/default_player.png"
                    result[player_id] = {
                        'thumbnail_url': default_image,
                        'medium_url': default_image,
                        'webp_url': default_image,
                        'original_url': default_image,
                        'is_optimized': True,
                        'file_size': 0
                    }
            
            # Batch queue optimization requests
            if optimization_queue:
                ImageCacheService._batch_queue_for_optimization(optimization_queue)
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting player image data: {e}")
            # Fallback to original URLs
            players = Player.query.filter(Player.id.in_(player_ids)).all()
            return {
                player.id: {
                    'thumbnail_url': player.profile_picture_url or "/static/img/default_player.png",
                    'medium_url': player.profile_picture_url or "/static/img/default_player.png",
                    'webp_url': player.profile_picture_url or "/static/img/default_player.png",
                    'original_url': player.profile_picture_url or "/static/img/default_player.png",
                    'is_optimized': False,
                    'file_size': 0
                } for player in players
            }
    
    @staticmethod
    def _queue_for_optimization(player_id: int, image_url: str, session=None):
        """Queue a player image for optimization."""
        try:
            # Use provided session or fall back to managed session
            if session is None:
                from app.core.session_manager import managed_session
                with managed_session() as session:
                    return ImageCacheService._queue_for_optimization(player_id, image_url, session)
            
            cache_entry = PlayerImageCache.query.filter_by(player_id=player_id).first()
            if not cache_entry:
                cache_entry = PlayerImageCache(
                    player_id=player_id,
                    original_url=image_url,
                    cache_status='pending'
                )
                session.add(cache_entry)
            else:
                cache_entry.original_url = image_url
                cache_entry.cache_status = 'pending'
            
            session.commit()
            
        except Exception as e:
            logger.warning(f"Failed to queue image optimization for player {player_id}: {e}")
    
    @staticmethod
    def _batch_queue_for_optimization(optimization_queue: List[Tuple[int, str]], session=None):
        """OPTIMIZED: Batch queue multiple players for image optimization."""
        if not optimization_queue:
            return
            
        try:
            # Use provided session or fall back to managed session
            if session is None:
                from app.core.session_manager import managed_session
                with managed_session() as session:
                    return ImageCacheService._batch_queue_for_optimization(optimization_queue, session)
            
            # Get existing cache entries for these players
            player_ids = [item[0] for item in optimization_queue]
            existing_entries = {
                entry.player_id: entry 
                for entry in PlayerImageCache.query.filter(
                    PlayerImageCache.player_id.in_(player_ids)
                ).all()
            }
            
            # Batch create/update cache entries
            new_entries = []
            updated_count = 0
            
            for player_id, image_url in optimization_queue:
                if player_id in existing_entries:
                    # Update existing entry
                    existing_entries[player_id].original_url = image_url
                    existing_entries[player_id].cache_status = 'pending'
                    updated_count += 1
                else:
                    # Create new entry
                    new_entries.append(PlayerImageCache(
                        player_id=player_id,
                        original_url=image_url,
                        cache_status='pending'
                    ))
            
            # Bulk insert new entries
            if new_entries:
                session.bulk_save_objects(new_entries)
            
            session.commit()
            
            logger.debug(f"Batch queued {len(new_entries)} new + {updated_count} updated images for optimization")
            
            # Trigger background optimization if enabled
            # This could trigger a Celery task for background processing
            # ImageOptimizationTask.delay(player_ids)
            
        except Exception as e:
            logger.warning(f"Failed to batch queue image optimization: {e}")
            session.rollback()
            # Fallback to individual queuing
            for player_id, image_url in optimization_queue:
                ImageCacheService._queue_for_optimization(player_id, image_url, session)
    
    @staticmethod
    def optimize_player_image(player_id: int, force_refresh: bool = False, session=None) -> bool:
        """
        Optimize a single player's image with multiple formats and sizes.
        Returns True if successful.
        """
        try:
            # Use provided session or fall back to managed session
            if session is None:
                from app.core.session_manager import managed_session
                with managed_session() as session:
                    return ImageCacheService.optimize_player_image(player_id, force_refresh, session)
            
            ImageCacheService.initialize_cache_directory()
            
            # Phase 1: Get image URL and prepare for download
            original_url = None
            cache_entry_id = None
            
            # Get or create cache entry
            cache_entry = PlayerImageCache.query.filter_by(player_id=player_id).first()
            if not cache_entry:
                # Create cache entry from player data
                player = Player.query.get(player_id)
                if not player or not player.profile_picture_url:
                    logger.debug(f"Player {player_id} has no profile picture")
                    return False
                
                cache_entry = PlayerImageCache(
                    player_id=player_id,
                    original_url=player.profile_picture_url,
                    cache_status='pending'
                )
                session.add(cache_entry)
                session.commit()
                logger.debug(f"Created cache entry for player {player_id}")
            
            # Skip if already optimized and not forced
            if cache_entry.is_optimized and not force_refresh:
                return True
            
            cache_entry.cache_status = 'processing'
            original_url = cache_entry.original_url
            cache_entry_id = cache_entry.id
            session.commit()
            
            # Phase 2: Download/load image data without holding session
            image_data = None
            
            if original_url and original_url.startswith('/static/'):
                # Handle local files with path traversal protection
                try:
                    # Construct path and validate it's within app/static
                    original_path = Path("app") / original_url.lstrip('/')
                    validated_path = validate_path_within_directory(str(original_path), "app/static")
                    original_path = Path(validated_path)

                    if original_path.exists():
                        with open(original_path, 'rb') as f:
                            image_data = f.read()
                        logger.debug(f"Loaded local image: {original_path}")
                    else:
                        logger.warning(f"Local image not found: {original_path}")
                except PathTraversalError:
                    logger.warning(f"Path traversal attempt detected in image URL: {original_url}")
                    # Update cache status in new session
                    with managed_session() as fail_session:
                        fail_entry = fail_session.query(PlayerImageCache).get(cache_entry_id)
                        if fail_entry:
                            fail_entry.cache_status = 'failed'
                            fail_session.commit()
                    return False
            elif original_url and original_url.startswith('http'):
                # Download from URL without holding database session
                try:
                    response = requests.get(original_url, timeout=10, stream=True)
                    response.raise_for_status()
                    image_data = response.content
                    logger.debug(f"Downloaded image from: {original_url}")
                except Exception as e:
                    logger.warning(f"Failed to download image from {original_url}: {e}")
                    # Update cache status in new session
                    with managed_session() as fail_session:
                        fail_entry = fail_session.query(PlayerImageCache).get(cache_entry_id)
                        if fail_entry:
                            fail_entry.cache_status = 'failed'
                            fail_session.commit()
                    return False
            else:
                logger.warning(f"Invalid image URL for player {player_id}: {original_url}")
                # Update cache status in new session
                with managed_session() as fail_session:
                    fail_entry = fail_session.query(PlayerImageCache).get(cache_entry_id)
                    if fail_entry:
                        fail_entry.cache_status = 'failed'
                        fail_session.commit()
                return False
            
            if not image_data:
                logger.warning(f"No image data loaded for player {player_id}")
                # Update cache status in new session
                with managed_session() as fail_session:
                    fail_entry = fail_session.query(PlayerImageCache).get(cache_entry_id)
                    if fail_entry:
                        fail_entry.cache_status = 'failed'
                        fail_session.commit()
                return False
            
            # Open and validate image
            image = Image.open(io.BytesIO(image_data))
            if image.mode in ('RGBA', 'LA', 'P'):
                # Convert to RGB for JPEG
                rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                rgb_image.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                image = rgb_image
            
            # Generate filenames
            base_name = f"player_{player_id}"
            timestamp = int(datetime.now().timestamp())
            
            # Create thumbnail
            thumbnail = image.copy()
            thumbnail.thumbnail(ImageCacheService.THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            thumbnail_path = ImageCacheService.CACHE_DIR / "thumbnails" / f"{base_name}_thumb_{timestamp}.jpg"
            thumbnail.save(thumbnail_path, 'JPEG', quality=ImageCacheService.JPEG_QUALITY, optimize=True)
            
            # Create medium size
            medium = image.copy()
            medium.thumbnail(ImageCacheService.MEDIUM_SIZE, Image.Resampling.LANCZOS)
            medium_path = ImageCacheService.CACHE_DIR / "medium" / f"{base_name}_med_{timestamp}.jpg"
            medium.save(medium_path, 'JPEG', quality=ImageCacheService.JPEG_QUALITY, optimize=True)
            
            # Create WebP version (best compression)
            webp_path = ImageCacheService.CACHE_DIR / "webp" / f"{base_name}_{timestamp}.webp"
            medium.save(webp_path, 'WEBP', quality=ImageCacheService.WEBP_QUALITY, optimize=True)
            
            # Phase 3: Update cache entry with new session
            with managed_session() as update_session:
                cache_entry = update_session.query(PlayerImageCache).get(cache_entry_id)
                if cache_entry:
                    cache_entry.thumbnail_url = f"/static/img/cache/players/thumbnails/{thumbnail_path.name}"
                    cache_entry.cached_url = f"/static/img/cache/players/medium/{medium_path.name}"
                    cache_entry.webp_url = f"/static/img/cache/players/webp/{webp_path.name}"
                    cache_entry.width = medium.width
                    cache_entry.height = medium.height
                    cache_entry.file_size = medium_path.stat().st_size
                    cache_entry.is_optimized = True
                    cache_entry.cache_status = 'ready'
                    cache_entry.last_cached = datetime.utcnow()
                    cache_entry.cache_expiry = datetime.utcnow() + timedelta(days=ImageCacheService.CACHE_EXPIRY_DAYS)
                    update_session.commit()
            
            logger.info(f"Successfully optimized image for player {player_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error optimizing image for player {player_id}: {e}")
            try:
                # Update cache status in new session
                with managed_session() as error_session:
                    cache_entry = error_session.query(PlayerImageCache).filter_by(player_id=player_id).first()
                    if cache_entry:
                        cache_entry.cache_status = 'failed'
                        error_session.commit()
            except:
                pass
            return False
    
    @staticmethod
    def bulk_optimize_images(player_ids: List[int] = None, max_workers: int = 1) -> Dict[str, int]:
        """
        Optimize images for multiple players.
        If player_ids is None, optimizes all current players.
        Using sequential processing to avoid Flask context issues.
        """
        try:
            if player_ids is None:
                # Get all current players with images (filter out empty/null URLs)
                players = Player.query.filter(
                    Player.is_current_player == True,
                    Player.profile_picture_url.isnot(None),
                    Player.profile_picture_url != ''
                ).all()
                
                # Further filter to only players with actual image URLs (not just empty strings)
                player_ids = []
                for player in players:
                    if player.profile_picture_url and player.profile_picture_url.strip():
                        player_ids.append(player.id)
                
                logger.info(f"Found {len(player_ids)} players with profile pictures")
            
            if not player_ids:
                logger.info("No players with profile pictures found")
                return {'success': 0, 'failed': 0, 'skipped': 0}
                
            logger.info(f"Starting bulk image optimization for {len(player_ids)} players")
            
            results = {'success': 0, 'failed': 0, 'skipped': 0}
            
            # Process sequentially to avoid Flask context issues
            for i, player_id in enumerate(player_ids):
                try:
                    success = ImageCacheService.optimize_player_image(player_id)
                    if success:
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                    
                    # Log progress every 20 players
                    if (i + 1) % 20 == 0:
                        logger.info(f"Processed {i + 1}/{len(player_ids)} players...")
                        
                except Exception as e:
                    logger.error(f"Error processing player {player_id}: {e}")
                    results['failed'] += 1
            
            logger.info(f"Bulk optimization completed: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Error in bulk image optimization: {e}")
            return {'success': 0, 'failed': len(player_ids or []), 'skipped': 0}
    
    @staticmethod
    def cleanup_expired_cache(session=None):
        """Remove expired cache entries and files."""
        try:
            # Use provided session or fall back to managed session
            if session is None:
                from app.core.session_manager import managed_session
                with managed_session() as session:
                    return ImageCacheService.cleanup_expired_cache(session)
            
            expired_entries = session.query(PlayerImageCache).filter(
                PlayerImageCache.cache_expiry < datetime.utcnow()
            ).all()
            
            for entry in expired_entries:
                # Remove files with path traversal protection
                for url in [entry.thumbnail_url, entry.cached_url, entry.webp_url]:
                    if url and url.startswith('/static/'):
                        try:
                            file_path = Path("app") / url.lstrip('/')
                            # Validate path is within static directory
                            validate_path_within_directory(str(file_path), "app/static")
                            if file_path.exists():
                                file_path.unlink()
                        except PathTraversalError:
                            logger.warning(f"Path traversal attempt in cache cleanup: {url}")
                
                # Remove database entry
                session.delete(entry)
            
            session.commit()
            logger.info(f"Cleaned up {len(expired_entries)} expired cache entries")
            
        except Exception as e:
            logger.error(f"Error cleaning up expired cache: {e}")


def handle_player_image_update(player_id: int, force_refresh: bool = True) -> bool:
    """
    Event handler to be called when a player's profile picture changes.
    Queues the image for async optimization - NEVER blocks the request.

    Returns:
        True if async optimization was queued successfully
        False if async optimization failed (image will be queued for later)
    """
    try:
        player = Player.query.get(player_id)
        if player and player.profile_picture_url:
            # Try to use Celery for async processing if available
            try:
                from app.tasks.tasks_image_optimization import queue_image_optimization
                if queue_image_optimization(player_id, force_refresh=force_refresh):
                    logger.info(f"Queued async image optimization for player {player_id} (force_refresh={force_refresh})")
                    return True
            except ImportError:
                logger.debug("Celery not available for image optimization")
            except Exception as e:
                logger.warning(f"Could not queue image optimization for player {player_id}: {e}")

            # Queue for later optimization instead of blocking synchronously
            # The image will be optimized on next cache access or background task
            ImageCacheService._queue_for_optimization(player_id, player.profile_picture_url)
            logger.info(f"Queued player {player_id} image for later optimization (async unavailable)")
            return False
        return False
    except Exception as e:
        logger.error(f"Failed to handle image update for player {player_id}: {e}")
        return False