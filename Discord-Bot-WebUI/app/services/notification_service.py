import json
import logging
from typing import List, Dict, Optional
from firebase_admin import messaging, credentials, initialize_app
from firebase_admin.exceptions import FirebaseError
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
        """Send push notification to multiple tokens using 2025 best practices"""
        if not self._initialized:
            raise RuntimeError("NotificationService not initialized")
        
        if not tokens:
            return {"success": 0, "failure": 0}
        
        # Filter out empty/invalid tokens
        valid_tokens = [token.strip() for token in tokens if token and token.strip()]
        if not valid_tokens:
            logger.warning("No valid tokens provided")
            return {"success": 0, "failure": len(tokens)}
        
        # Create message with modern configuration
        message = messaging.MulticastMessage(
            tokens=valid_tokens,
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data or {},
            android=messaging.AndroidConfig(
                notification=messaging.AndroidNotification(
                    sound='default',
                    color='#1976D2',  # ECS Soccer blue
                    priority='high',
                    default_sound=True,
                    default_vibrate_timings=True,
                ),
                priority='high',
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        sound='default',
                        badge=1,
                        alert=messaging.ApsAlert(
                            title=title,
                            body=body
                        ),
                        content_available=True
                    )
                ),
                headers={
                    'apns-priority': '10',
                    'apns-push-type': 'alert'
                }
            ),
        )
        
        try:
            # Use modern send_each_for_multicast API
            response = messaging.send_each_for_multicast(message)
            logger.info(f"Push notification sent: {response.success_count} success, {response.failure_count} failure")
            
            # Update last_used for successful tokens
            if response.success_count > 0:
                self._mark_tokens_as_used(valid_tokens, response.responses)
            
            # Handle failed tokens with proper error categorization
            if response.failure_count > 0:
                invalid_tokens = []
                temporary_failures = []
                
                for idx, resp in enumerate(response.responses):
                    if not resp.success:
                        token = valid_tokens[idx]
                        error = resp.exception
                        
                        # Categorize errors for proper handling
                        if isinstance(error, FirebaseError):
                            error_code = getattr(error, 'code', None)
                            if error_code in ['messaging/registration-token-not-registered', 
                                            'messaging/invalid-registration-token']:
                                invalid_tokens.append(token)
                                logger.warning(f"Invalid token will be cleaned up: {token[:20]}...")
                            else:
                                temporary_failures.append(token)
                                logger.warning(f"Temporary failure for token {token[:20]}...: {error}")
                        else:
                            logger.error(f"Unexpected error for token {token[:20]}...: {error}")
                
                # Clean up invalid tokens
                if invalid_tokens:
                    self._cleanup_invalid_tokens(invalid_tokens)
                
                # Log temporary failures for potential retry
                if temporary_failures:
                    logger.info(f"{len(temporary_failures)} tokens had temporary failures and may be retried")
            
            return {
                "success": response.success_count,
                "failure": response.failure_count,
                "total_attempted": len(valid_tokens)
            }
            
        except FirebaseError as e:
            logger.error(f"Firebase error sending push notification: {e}")
            return {"success": 0, "failure": len(valid_tokens)}
        except Exception as e:
            logger.error(f"Unexpected error sending push notification: {e}")
            return {"success": 0, "failure": len(valid_tokens)}
    
    def send_match_reminder(self, user_tokens: List[str], match_data: Dict) -> Dict[str, int]:
        """Send match reminder notification with enhanced data payload"""
        title = "⚽ Match Reminder"
        opponent = match_data.get('opponent', 'TBD')
        location = match_data.get('location', 'TBD')
        match_time = match_data.get('time', 'TBD')
        
        body = f"Your match against {opponent} starts in 2 hours at {location}"
        
        # Enhanced data payload for modern app handling
        data = {
            'type': 'match_reminder',
            'match_id': str(match_data.get('id', '')),
            'opponent': opponent,
            'location': location,
            'match_time': match_time,
            'click_action': 'FLUTTER_NOTIFICATION_CLICK',
            'deep_link': f"ecsfc://match/{match_data.get('id', '')}",
            'priority': 'high'
        }
        
        return self.send_push_notification(user_tokens, title, body, data)
    
    def send_rsvp_reminder(self, user_tokens: List[str], match_data: Dict) -> Dict[str, int]:
        """Send RSVP reminder notification with enhanced tracking"""
        title = "📝 RSVP Reminder"
        opponent = match_data.get('opponent', 'TBD')
        match_date = match_data.get('date', 'TBD')
        
        body = f"Don't forget to RSVP for your match against {opponent} on {match_date}"
        
        # Enhanced data for better app integration
        data = {
            'type': 'rsvp_reminder',
            'match_id': str(match_data.get('id', '')),
            'opponent': opponent,
            'match_date': match_date,
            'click_action': 'FLUTTER_NOTIFICATION_CLICK',
            'deep_link': f"ecsfc://rsvp/{match_data.get('id', '')}",
            'priority': 'normal',
            'category': 'rsvp'
        }
        
        return self.send_push_notification(user_tokens, title, body, data)
    
    def send_general_notification(self, user_tokens: List[str], title: str, body: str, extra_data: Optional[Dict] = None) -> Dict[str, int]:
        """Send general notification with modern payload structure"""
        # Base data payload with 2025 standards
        data = {
            'type': 'general',
            'click_action': 'FLUTTER_NOTIFICATION_CLICK',
            'timestamp': str(int(__import__('time').time())),
            'priority': 'normal'
        }
        
        # Merge additional data safely
        if extra_data:
            # Ensure all values are strings (FCM requirement)
            for key, value in extra_data.items():
                data[key] = str(value) if value is not None else ''
        
        return self.send_push_notification(user_tokens, title, body, data)
    
    def _cleanup_invalid_tokens(self, invalid_tokens: List[str]):
        """Remove invalid tokens from database using 2025 best practices"""
        if not invalid_tokens:
            return
            
        try:
            # Import here to avoid circular imports
            from app.models import UserFCMToken
            from flask import g
            
            # Mark tokens as inactive instead of deleting (for audit trail)
            if hasattr(g, 'db_session') and g.db_session:
                updated = g.db_session.query(UserFCMToken).filter(
                    UserFCMToken.fcm_token.in_(invalid_tokens)
                ).update({
                    'is_active': False,
                    'deactivated_reason': 'invalid_token'
                }, synchronize_session=False)
                
                g.db_session.commit()
                logger.info(f"Deactivated {updated} invalid FCM tokens from database")
            else:
                logger.warning("No database session available for token cleanup")
                
        except Exception as e:
            logger.error(f"Error cleaning up invalid tokens: {e}")
            # Don't raise - token cleanup shouldn't break notification sending
    
    def _mark_tokens_as_used(self, tokens: List[str], responses):
        """Mark successfully sent tokens as recently used"""
        try:
            from app.models import UserFCMToken
            from flask import g
            
            if not hasattr(g, 'db_session') or not g.db_session:
                return
            
            successful_tokens = []
            for idx, resp in enumerate(responses):
                if resp.success:
                    successful_tokens.append(tokens[idx])
            
            if successful_tokens:
                # Update last_used timestamp for successful tokens
                updated = g.db_session.query(UserFCMToken).filter(
                    UserFCMToken.fcm_token.in_(successful_tokens),
                    UserFCMToken.is_active == True
                ).update({
                    'last_used': __import__('datetime').datetime.utcnow()
                }, synchronize_session=False)
                
                g.db_session.commit()
                logger.debug(f"Updated last_used for {updated} successful FCM tokens")
                
        except Exception as e:
            logger.error(f"Error updating token usage: {e}")
            # Don't raise - this shouldn't break notification sending
    
    def validate_tokens(self, tokens: List[str]) -> Dict[str, List[str]]:
        """Validate FCM tokens without sending notifications"""
        if not self._initialized:
            raise RuntimeError("NotificationService not initialized")
        
        if not tokens:
            return {"valid": [], "invalid": []}
        
        valid_tokens = []
        invalid_tokens = []
        
        # Basic format validation
        for token in tokens:
            if not token or not isinstance(token, str) or len(token.strip()) < 10:
                invalid_tokens.append(token)
            else:
                valid_tokens.append(token.strip())
        
        return {"valid": valid_tokens, "invalid": invalid_tokens}
    
    def send_test_notification(self, token: str) -> Dict[str, any]:
        """Send a test notification to validate a single token"""
        if not self._initialized:
            raise RuntimeError("NotificationService not initialized")
        
        if not token or not token.strip():
            return {"success": False, "error": "Invalid token"}
        
        # Create a simple test message
        message = messaging.Message(
            token=token.strip(),
            notification=messaging.Notification(
                title="🧪 ECS Soccer Test",
                body="Push notifications are working correctly!"
            ),
            data={
                'type': 'test',
                'timestamp': str(int(__import__('time').time()))
            }
        )
        
        try:
            message_id = messaging.send(message)
            logger.info(f"Test notification sent successfully: {message_id}")
            return {"success": True, "message_id": message_id}
        except FirebaseError as e:
            logger.warning(f"Test notification failed: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error in test notification: {e}")
            return {"success": False, "error": "Unexpected error"}
    
    def get_service_status(self) -> Dict[str, any]:
        """Get the current status of the notification service"""
        return {
            "initialized": self._initialized,
            "firebase_available": bool(firebase_admin._apps),
            "service_version": "2025-modernized",
            "supported_platforms": ["android", "ios", "web"]
        }

# Global instance
notification_service = NotificationService()