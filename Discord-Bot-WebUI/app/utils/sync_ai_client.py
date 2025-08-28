# app/utils/sync_ai_client.py

"""
Synchronous AI Client for Enhanced Commentary

Provides synchronous wrappers around the AI commentary service to work
with the V2 synchronous live reporting architecture.
"""

import logging
import asyncio
import concurrent.futures
from typing import Dict, Any, Optional
from app.services.ai_commentary import get_enhanced_ai_service

logger = logging.getLogger(__name__)


class SyncAIClient:
    """Synchronous client for AI commentary service."""
    
    def __init__(self):
        self.service = get_enhanced_ai_service()
        self.timeout = 10  # seconds
    
    def generate_pre_match_hype(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate pre-match hype message synchronously.
        
        Args:
            match_context: Match details for hype generation
            
        Returns:
            Generated hype message or None
        """
        try:
            return self._run_sync(
                self.service.generate_pre_match_hype(match_context)
            )
        except Exception as e:
            logger.error(f"Error generating pre-match hype: {e}")
            return None
    
    def generate_half_time_message(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate half-time analysis message synchronously.
        
        Args:
            match_context: Match details for half-time analysis
            
        Returns:
            Generated half-time message or None
        """
        try:
            return self._run_sync(
                self.service.generate_half_time_message(match_context)
            )
        except Exception as e:
            logger.error(f"Error generating half-time message: {e}")
            return None
    
    def generate_full_time_message(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate full-time summary message synchronously.
        
        Args:
            match_context: Complete match details for summary
            
        Returns:
            Generated full-time message or None
        """
        try:
            return self._run_sync(
                self.service.generate_full_time_message(match_context)
            )
        except Exception as e:
            logger.error(f"Error generating full-time message: {e}")
            return None
    
    def generate_match_thread_context(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate match thread contextual description synchronously.
        
        Args:
            match_context: Match details for context generation
            
        Returns:
            Generated thread context or None
        """
        try:
            return self._run_sync(
                self.service.generate_match_thread_context(match_context)
            )
        except Exception as e:
            logger.error(f"Error generating thread context: {e}")
            return None
    
    def generate_commentary(self, event_data: Dict[str, Any], match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate regular event commentary synchronously.
        
        Args:
            event_data: Event details
            match_context: Match context
            
        Returns:
            Generated commentary or None
        """
        try:
            return self._run_sync(
                self.service.generate_commentary(event_data, match_context)
            )
        except Exception as e:
            logger.error(f"Error generating event commentary: {e}")
            return None
    
    def _run_sync(self, coroutine) -> Any:
        """
        Run an async coroutine synchronously with proper event loop handling.
        
        Args:
            coroutine: The async coroutine to run
            
        Returns:
            Result of the coroutine execution
        """
        def run_in_new_loop():
            """Run the coroutine in a new event loop."""
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(coroutine)
            finally:
                new_loop.close()
        
        # Check for eventlet environment
        try:
            import eventlet
            if eventlet.patcher.is_monkey_patched('thread'):
                import eventlet.tpool
                return eventlet.tpool.execute(run_in_new_loop)
        except ImportError:
            pass
        
        try:
            # Check if there's already a running event loop
            asyncio.get_running_loop()
            # If we get here, use a thread pool
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_in_new_loop)
                return future.result(timeout=self.timeout)
        except RuntimeError:
            # No running event loop - run directly
            return run_in_new_loop()


# Global client instance
_sync_ai_client = None

def get_sync_ai_client() -> SyncAIClient:
    """Get the global synchronous AI client instance."""
    global _sync_ai_client
    if _sync_ai_client is None:
        _sync_ai_client = SyncAIClient()
    return _sync_ai_client