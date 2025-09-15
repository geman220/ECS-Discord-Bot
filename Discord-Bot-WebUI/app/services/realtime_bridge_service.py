# app/services/realtime_bridge_service.py

"""
Real-Time Bridge Service

This service acts as a bridge between the Celery-based MatchSchedulerService
and the RealtimeReportingService. It handles coordination and communication
between the scheduling and real-time components.

Key Functions:
- Notify real-time service when new sessions start
- Handle real-time service availability checks
- Provide fallback coordination if services are misaligned
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from app.services.redis_connection_service import get_redis_service
from app.utils.task_session_manager import task_session

logger = logging.getLogger(__name__)


class RealtimeBridgeService:
    """
    Bridge service for coordinating Celery scheduling and real-time processing.

    This service ensures smooth integration between:
    1. MatchSchedulerService (Celery tasks for scheduling)
    2. RealtimeReportingService (dedicated real-time updates)
    """

    def __init__(self):
        self.redis_service = get_redis_service()

    def notify_session_started(self, session_id: int, match_id: int, thread_id: str) -> Dict[str, Any]:
        """
        Notify the real-time service that a new live reporting session has started.

        This is called by the start_live_reporting_task in MatchSchedulerService.
        """
        try:
            # Create notification payload
            notification = {
                'session_id': session_id,
                'match_id': match_id,
                'thread_id': thread_id,
                'timestamp': datetime.utcnow().isoformat(),
                'action': 'session_started'
            }

            # Publish to Redis channel for real-time service
            channel = 'realtime_service:notifications'
            self.redis_service.publish(channel, str(notification))

            # Also set a direct notification key
            notification_key = f'realtime_service:new_session:{session_id}'
            self.redis_service.setex(notification_key, 300, str(notification))

            logger.info(f"Notified real-time service of new session {session_id} for match {match_id}")

            return {
                'success': True,
                'message': 'Real-time service notified',
                'session_id': session_id
            }

        except Exception as e:
            logger.error(f"Error notifying real-time service: {e}")
            return {
                'success': False,
                'error': str(e),
                'session_id': session_id
            }

    def notify_session_stopped(self, session_id: int, match_id: int, reason: str) -> Dict[str, Any]:
        """
        Notify the real-time service that a live reporting session has stopped.

        This is called by the stop_live_reporting_task in MatchSchedulerService.
        """
        try:
            notification = {
                'session_id': session_id,
                'match_id': match_id,
                'timestamp': datetime.utcnow().isoformat(),
                'action': 'session_stopped',
                'reason': reason
            }

            # Publish notification
            channel = 'realtime_service:notifications'
            self.redis_service.publish(channel, str(notification))

            # Set direct notification
            notification_key = f'realtime_service:stop_session:{session_id}'
            self.redis_service.setex(notification_key, 60, str(notification))

            logger.info(f"Notified real-time service to stop session {session_id}: {reason}")

            return {
                'success': True,
                'message': 'Real-time service notified of stop',
                'session_id': session_id
            }

        except Exception as e:
            logger.error(f"Error notifying real-time service of stop: {e}")
            return {
                'success': False,
                'error': str(e),
                'session_id': session_id
            }

    def check_realtime_service_health(self) -> Dict[str, Any]:
        """
        Check if the real-time service is running and healthy.
        """
        try:
            # Check status key
            status = self.redis_service.get('realtime_service:status')
            heartbeat = self.redis_service.get('realtime_service:heartbeat')

            # Decode bytes to string if needed
            if isinstance(status, bytes):
                status = status.decode('utf-8')
            if isinstance(heartbeat, bytes):
                heartbeat = heartbeat.decode('utf-8')

            is_running = status == 'running'

            # Parse heartbeat timestamp
            last_heartbeat = None
            heartbeat_age = None
            if heartbeat:
                try:
                    last_heartbeat = datetime.fromisoformat(heartbeat)
                    heartbeat_age = (datetime.utcnow() - last_heartbeat).seconds
                except:
                    pass

            # Determine health status
            if is_running and heartbeat_age and heartbeat_age < 120:
                health = 'healthy'
            elif is_running and heartbeat_age and heartbeat_age < 300:
                health = 'degraded'
            elif is_running:
                health = 'unknown'
            else:
                health = 'offline'

            return {
                'is_running': is_running,
                'health': health,
                'last_heartbeat': last_heartbeat.isoformat() if last_heartbeat else None,
                'heartbeat_age_seconds': heartbeat_age,
                'timestamp': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Error checking real-time service health: {e}")
            return {
                'is_running': False,
                'health': 'error',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }

    def get_active_sessions_status(self) -> Dict[str, Any]:
        """
        Get status of active live reporting sessions from both database and real-time service.
        """
        try:
            with task_session() as session:
                from app.models import LiveReportingSession

                # Get database sessions
                db_sessions = session.query(LiveReportingSession).filter_by(is_active=True).all()

                db_session_data = []
                for live_session in db_sessions:
                    db_session_data.append({
                        'session_id': live_session.id,
                        'match_id': live_session.match_id,
                        'thread_id': live_session.thread_id,
                        'competition': live_session.competition,
                        'last_status': live_session.last_status,
                        'last_update_at': live_session.last_update_at.isoformat() if live_session.last_update_at else None,
                        'update_count': live_session.update_count or 0,
                        'error_count': live_session.error_count or 0
                    })

                # Get real-time service status
                realtime_status = self.check_realtime_service_health()

                return {
                    'timestamp': datetime.utcnow().isoformat(),
                    'database_sessions': len(db_session_data),
                    'sessions': db_session_data,
                    'realtime_service': realtime_status,
                    'coordination_status': 'healthy' if realtime_status['health'] == 'healthy' else 'degraded'
                }

        except Exception as e:
            logger.error(f"Error getting active sessions status: {e}")
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'error': str(e),
                'coordination_status': 'error'
            }

    def force_session_sync(self) -> Dict[str, Any]:
        """
        Force synchronization between database sessions and real-time service.

        This can be used to recover from misaligned states.
        """
        try:
            # Get current active sessions from database
            with task_session() as session:
                from app.models import LiveReportingSession

                active_sessions = session.query(LiveReportingSession).filter_by(is_active=True).all()

                sync_notifications = []
                for live_session in active_sessions:
                    # Send sync notification for each session
                    notification = {
                        'session_id': live_session.id,
                        'match_id': live_session.match_id,
                        'thread_id': live_session.thread_id,
                        'competition': live_session.competition,
                        'timestamp': datetime.utcnow().isoformat(),
                        'action': 'force_sync'
                    }

                    # Publish sync notification
                    channel = 'realtime_service:notifications'
                    self.redis_service.publish(channel, str(notification))

                    sync_notifications.append(notification)

                logger.info(f"Forced sync for {len(sync_notifications)} active sessions")

                return {
                    'success': True,
                    'message': f'Synced {len(sync_notifications)} sessions',
                    'synced_sessions': len(sync_notifications),
                    'notifications': sync_notifications
                }

        except Exception as e:
            logger.error(f"Error forcing session sync: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def send_realtime_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Send a command to the real-time service.

        Commands can be: 'refresh_sessions', 'health_check', 'status_report', etc.
        """
        try:
            command_payload = {
                'command': command,
                'params': params or {},
                'timestamp': datetime.utcnow().isoformat(),
                'source': 'bridge_service'
            }

            # Send command via Redis channel
            channel = 'realtime_service:commands'
            self.redis_service.publish(channel, str(command_payload))

            # Also set command key for direct access
            command_key = f'realtime_service:command:{command}'
            self.redis_service.setex(command_key, 30, str(command_payload))

            logger.info(f"Sent command '{command}' to real-time service")

            return {
                'success': True,
                'command': command,
                'message': 'Command sent to real-time service'
            }

        except Exception as e:
            logger.error(f"Error sending realtime command: {e}")
            return {
                'success': False,
                'command': command,
                'error': str(e)
            }


# Singleton instance
realtime_bridge = RealtimeBridgeService()


# Helper functions for easy integration
def notify_session_started(session_id: int, match_id: int, thread_id: str) -> Dict[str, Any]:
    """Helper function to notify real-time service of new session."""
    return realtime_bridge.notify_session_started(session_id, match_id, thread_id)


def notify_session_stopped(session_id: int, match_id: int, reason: str) -> Dict[str, Any]:
    """Helper function to notify real-time service of stopped session."""
    return realtime_bridge.notify_session_stopped(session_id, match_id, reason)


def check_realtime_health() -> Dict[str, Any]:
    """Helper function to check real-time service health."""
    return realtime_bridge.check_realtime_service_health()


def get_coordination_status() -> Dict[str, Any]:
    """Helper function to get overall coordination status."""
    return realtime_bridge.get_active_sessions_status()