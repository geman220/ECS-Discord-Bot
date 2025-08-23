# app/utils/session_monitor.py

"""
Session Monitoring Utilities

This module provides utilities for monitoring database session lifecycle
and detecting potential connection leaks.
"""

import logging
import time
import threading
from typing import Dict, List, Optional
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class SessionInfo:
    """Information about a database session."""
    session_id: str
    created_at: float
    route: Optional[str]
    user_id: Optional[int]
    status: str  # 'active', 'committed', 'rolled_back', 'closed'
    

class SessionMonitor:
    """Monitor database session lifecycle and detect leaks."""
    
    def __init__(self):
        self._sessions: Dict[str, SessionInfo] = {}
        self._lock = threading.Lock()
        self._stats = defaultdict(int)
        
    def register_session_start(self, session_id: str, route: str = None, user_id: int = None):
        """Register the start of a new session."""
        with self._lock:
            self._sessions[session_id] = SessionInfo(
                session_id=session_id,
                created_at=time.time(),
                route=route,
                user_id=user_id,
                status='active'
            )
            self._stats['total_created'] += 1
            # Session registration logged only at trace level
            pass
    
    def register_session_commit(self, session_id: str):
        """Register that a session was committed."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].status = 'committed'
                self._stats['total_committed'] += 1
                # Session commit logged only at trace level
                pass
    
    def register_session_rollback(self, session_id: str):
        """Register that a session was rolled back."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].status = 'rolled_back'
                self._stats['total_rolled_back'] += 1
                logger.info(f"Session rolled back: {session_id}")
    
    def register_session_close(self, session_id: str):
        """Register that a session was closed."""
        with self._lock:
            if session_id in self._sessions:
                session_info = self._sessions[session_id]
                duration = time.time() - session_info.created_at
                
                if session_info.status == 'active':
                    logger.warning(f"Session closed without commit/rollback: {session_id} (duration: {duration:.2f}s)")
                    
                del self._sessions[session_id]
                self._stats['total_closed'] += 1
                # Session closure logged only at trace level
                pass
    
    def get_active_sessions(self) -> List[SessionInfo]:
        """Get list of currently active sessions."""
        with self._lock:
            return list(self._sessions.values())
    
    def get_long_running_sessions(self, threshold_seconds: float = 30.0) -> List[SessionInfo]:
        """Get sessions that have been active longer than the threshold."""
        current_time = time.time()
        with self._lock:
            return [
                session for session in self._sessions.values()
                if current_time - session.created_at > threshold_seconds
            ]
    
    def get_stats(self) -> dict:
        """Get session statistics."""
        with self._lock:
            active_count = len(self._sessions)
            long_running_count = len(self.get_long_running_sessions())
            
            return {
                'active_sessions': active_count,
                'long_running_sessions': long_running_count,
                'total_created': self._stats['total_created'],
                'total_committed': self._stats['total_committed'],
                'total_rolled_back': self._stats['total_rolled_back'],
                'total_closed': self._stats['total_closed'],
                'potential_leaks': active_count,
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def log_session_report(self):
        """Log a summary report of session status."""
        stats = self.get_stats()
        long_running = self.get_long_running_sessions()
        
        logger.info(f"Session Monitor Report: {stats}")
        
        if long_running:
            logger.warning(f"Long-running sessions detected: {len(long_running)}")
            for session in long_running:
                duration = time.time() - session.created_at
                logger.warning(
                    f"Long-running session: {session.session_id} "
                    f"(route: {session.route}, duration: {duration:.1f}s, status: {session.status})"
                )
    
    def cleanup_stale_sessions(self, max_age_seconds: float = 300.0):
        """Remove session records that are too old (likely closed but not properly tracked)."""
        current_time = time.time()
        stale_sessions = []
        
        with self._lock:
            for session_id, session_info in list(self._sessions.items()):
                if current_time - session_info.created_at > max_age_seconds:
                    stale_sessions.append(session_id)
                    del self._sessions[session_id]
        
        if stale_sessions:
            logger.info(f"Cleaned up {len(stale_sessions)} stale session records")

# Global session monitor instance
session_monitor = SessionMonitor()

def get_session_monitor() -> SessionMonitor:
    """Get the global session monitor instance."""
    return session_monitor