import json
import logging
from typing import List, Dict, Optional
from firebase_admin import messaging, credentials, initialize_app
from flask import current_app
import firebase_admin

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self):
        self._initialized = False
    
    def initialize(self, service_account_path: str):
        """Initialize Firebase Admin SDK"""
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(service_account_path)
                initialize_app(cred)
            self._initialized = True
            logger.info("Firebase Admin SDK initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Firebase Admin SDK: {e}")
            raise
    
    def send_push_notification(
        self, 
        tokens: List[str], 
        title: str, 
        body: str, 
        data: Optional[Dict[str, str]] = None
    ) -> Dict[str, int]:
        """Send push notification to multiple tokens"""
        if not self._initialized:
            raise RuntimeError("NotificationService not initialized")
        
        if not tokens:
            return {"success": 0, "failure": 0}
        
        # Create message
        message = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data or {},
            android=messaging.AndroidConfig(
                notification=messaging.AndroidNotification(
                    sound='default',
                    color='#1976D2',  # ECS Soccer blue
                ),
                priority='high',
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        sound='default',
                        badge=1,
                    )
                )
            ),
        )
        
        try:
            response = messaging.send_multicast(message)
            logger.info(f"Push notification sent: {response.success_count} success, {response.failure_count} failure")
            
            # Log failed tokens for cleanup
            if response.failure_count > 0:
                failed_tokens = []
                for idx, resp in enumerate(response.responses):
                    if not resp.success:
                        failed_tokens.append(tokens[idx])
                        logger.warning(f"Failed to send to token {tokens[idx]}: {resp.exception}")
                
                # You might want to remove invalid tokens from your database here
                self._cleanup_invalid_tokens(failed_tokens)
            
            return {
                "success": response.success_count,
                "failure": response.failure_count
            }
        except Exception as e:
            logger.error(f"Error sending push notification: {e}")
            return {"success": 0, "failure": len(tokens)}
    
    def send_match_reminder(self, user_tokens: List[str], match_data: Dict) -> Dict[str, int]:
        """Send match reminder notification"""
        title = "⚽ Match Reminder"
        body = f"Your match against {match_data.get('opponent', 'TBD')} starts in 2 hours at {match_data.get('location', 'TBD')}"
        
        data = {
            'type': 'match_reminder',
            'match_id': str(match_data.get('id', '')),
            'click_action': 'FLUTTER_NOTIFICATION_CLICK',
        }
        
        return self.send_push_notification(user_tokens, title, body, data)
    
    def send_rsvp_reminder(self, user_tokens: List[str], match_data: Dict) -> Dict[str, int]:
        """Send RSVP reminder notification"""
        title = "📝 RSVP Reminder"
        body = f"Don't forget to RSVP for your match against {match_data.get('opponent', 'TBD')} on {match_data.get('date', 'TBD')}"
        
        data = {
            'type': 'rsvp_reminder',
            'match_id': str(match_data.get('id', '')),
            'click_action': 'FLUTTER_NOTIFICATION_CLICK',
        }
        
        return self.send_push_notification(user_tokens, title, body, data)
    
    def send_general_notification(self, user_tokens: List[str], title: str, body: str, extra_data: Optional[Dict] = None) -> Dict[str, int]:
        """Send general notification to users"""
        data = {
            'type': 'general',
            'click_action': 'FLUTTER_NOTIFICATION_CLICK',
        }
        
        if extra_data:
            data.update(extra_data)
        
        return self.send_push_notification(user_tokens, title, body, data)
    
    def _cleanup_invalid_tokens(self, invalid_tokens: List[str]):
        """Remove invalid tokens from database"""
        # Implement your token cleanup logic here
        # For example, remove tokens from user_fcm_tokens table
        logger.info(f"Cleaning up {len(invalid_tokens)} invalid tokens")

# Global instance
notification_service = NotificationService()