"""
Image Optimization Celery Tasks

Handles asynchronous image optimization for player profile pictures.
"""

import logging
from app.decorators import celery_task
from app.image_cache_service import ImageCacheService

logger = logging.getLogger(__name__)


@celery_task(name='app.tasks.tasks_image_optimization.optimize_player_image', max_retries=3)
def optimize_player_image_task(self, session, player_id: int, force_refresh: bool = False):
    """
    Celery task to optimize a player's profile image asynchronously.
    
    Args:
        session: Database session
        player_id: ID of the player whose image to optimize
        force_refresh: Whether to force re-optimization even if already done
    """
    try:
        logger.info(f"Starting image optimization for player {player_id}")
        
        # Perform the optimization
        success = ImageCacheService.optimize_player_image(player_id, force_refresh, session)
        
        if success:
            logger.info(f"Successfully optimized image for player {player_id}")
            return {'success': True, 'player_id': player_id}
        else:
            logger.warning(f"Failed to optimize image for player {player_id}")
            return {'success': False, 'player_id': player_id}
            
    except Exception as e:
        logger.error(f"Error optimizing image for player {player_id}: {e}")
        # Retry the task
        raise self.retry(exc=e, countdown=60)


@celery_task(name='app.tasks.tasks_image_optimization.bulk_optimize_images', max_retries=1)
def bulk_optimize_images_task(self, session, player_ids: list = None):
    """
    Celery task to optimize multiple player images in bulk.
    
    Args:
        session: Database session
        player_ids: List of player IDs to optimize (None for all)
    """
    try:
        logger.info(f"Starting bulk image optimization")
        
        # Perform bulk optimization
        results = ImageCacheService.bulk_optimize_images(player_ids)
        
        logger.info(f"Bulk optimization completed: {results}")
        return results
        
    except Exception as e:
        logger.error(f"Error in bulk image optimization: {e}")
        return {'success': 0, 'failed': len(player_ids or []), 'skipped': 0}


def queue_image_optimization(player_id: int, force_refresh: bool = False):
    """
    Queue a player's image for optimization via Celery.
    This is the preferred method for production use.
    """
    try:
        optimize_player_image_task.delay(player_id=player_id, force_refresh=force_refresh)
        logger.info(f"Queued image optimization task for player {player_id} (force_refresh={force_refresh})")
        return True
    except Exception as e:
        logger.error(f"Failed to queue image optimization for player {player_id}: {e}")
        return False