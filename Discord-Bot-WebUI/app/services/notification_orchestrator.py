# app/services/notification_orchestrator.py

"""
Unified Notification Orchestrator
=================================

Central service for coordinating all notification delivery channels:
- In-app notifications (navbar/bell icon)
- Push notifications (FCM - iOS/Android/Web)
- Email notifications (Gmail API)
- SMS notifications (Twilio)
- Discord DM notifications (Bot API)

Key Features:
- Single interface for all notification needs
- User preference enforcement
- Automatic multi-channel coordination
- Analytics tracking
- Event-based notification triggers
"""

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    """Notification types with their default settings"""
    # Match-related
    MATCH_REMINDER = 'match_reminder'
    MATCH_RESULT = 'match_result'
    MATCH_CANCELLED = 'match_cancelled'
    MATCH_RESCHEDULED = 'match_rescheduled'

    # RSVP-related
    RSVP_REMINDER = 'rsvp_reminder'
    RSVP_CONFIRMED = 'rsvp_confirmed'

    # Team-related
    TEAM_UPDATE = 'team_update'
    TEAM_ROSTER_CHANGE = 'team_roster_change'

    # League-related
    LEAGUE_ANNOUNCEMENT = 'league_announcement'
    STANDINGS_UPDATE = 'standings_update'

    # Admin/System
    ADMIN_ANNOUNCEMENT = 'admin_announcement'
    SYSTEM = 'system'
    WELCOME = 'welcome'

    # Substitute-related
    SUB_REQUEST = 'sub_request'
    SUB_FILLED = 'sub_filled'

    # Direct Messaging
    DIRECT_MESSAGE = 'direct_message'


@dataclass
class NotificationPayload:
    """Structured notification payload"""
    notification_type: NotificationType
    title: str
    message: str
    user_ids: List[int]  # Target users
    data: Optional[Dict[str, Any]] = None  # Extra data for deep links, etc.
    icon: Optional[str] = None  # Custom icon class
    priority: str = 'normal'  # 'high' for urgent notifications

    # Channel overrides (None = respect user preferences)
    force_push: Optional[bool] = None
    force_in_app: Optional[bool] = None
    force_email: Optional[bool] = None
    force_sms: Optional[bool] = None
    force_discord: Optional[bool] = None
    skip_preferences: bool = False  # For critical system notifications

    # Email-specific fields
    email_subject: Optional[str] = None  # Custom email subject (defaults to title)
    email_html_body: Optional[str] = None  # Custom HTML email body

    # Action URL for emails/SMS
    action_url: Optional[str] = None  # URL to include as call-to-action


# Default icons for notification types
NOTIFICATION_ICONS = {
    NotificationType.MATCH_REMINDER: 'ti ti-calendar-event',
    NotificationType.MATCH_RESULT: 'ti ti-trophy',
    NotificationType.MATCH_CANCELLED: 'ti ti-calendar-off',
    NotificationType.MATCH_RESCHEDULED: 'ti ti-calendar-stats',
    NotificationType.RSVP_REMINDER: 'ti ti-clipboard-check',
    NotificationType.RSVP_CONFIRMED: 'ti ti-check',
    NotificationType.TEAM_UPDATE: 'ti ti-users',
    NotificationType.TEAM_ROSTER_CHANGE: 'ti ti-user-plus',
    NotificationType.LEAGUE_ANNOUNCEMENT: 'ti ti-speakerphone',
    NotificationType.STANDINGS_UPDATE: 'ti ti-chart-bar',
    NotificationType.ADMIN_ANNOUNCEMENT: 'ti ti-bell-ringing',
    NotificationType.SYSTEM: 'ti ti-info-circle',
    NotificationType.WELCOME: 'ti ti-confetti',
    NotificationType.SUB_REQUEST: 'ti ti-hand-stop',
    NotificationType.SUB_FILLED: 'ti ti-user-check',
    NotificationType.DIRECT_MESSAGE: 'ti ti-message-circle',
}


class NotificationOrchestrator:
    """
    Central orchestrator for all notification delivery.

    Usage:
        from app.services.notification_orchestrator import orchestrator, NotificationPayload, NotificationType

        # Send a match reminder
        orchestrator.send(NotificationPayload(
            notification_type=NotificationType.MATCH_REMINDER,
            title="Match Tomorrow!",
            message="Your match against Team X is tomorrow at 7pm",
            user_ids=[123, 456, 789],
            data={'match_id': 42}
        ))

        # Or use convenience methods
        orchestrator.send_match_reminder(match_id=42, user_ids=[123, 456])
        orchestrator.send_rsvp_reminder(match_id=42, user_ids=[123])
    """

    def __init__(self):
        self._push_service = None
        self._db = None
        self.bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')

    def _get_push_service(self):
        """Lazy load push notification service"""
        if self._push_service is None:
            from app.services.notification_service import notification_service
            self._push_service = notification_service
        return self._push_service

    def _get_db(self):
        """Get database session"""
        from app.core import db
        return db

    def send(self, payload: NotificationPayload) -> Dict[str, Any]:
        """
        Send notification through all appropriate channels.

        Returns:
            Dict with results for each channel
        """
        results = {
            'in_app': {'created': 0, 'skipped': 0},
            'push': {'success': 0, 'failure': 0, 'skipped': 0},
            'email': {'success': 0, 'failure': 0, 'skipped': 0},
            'sms': {'success': 0, 'failure': 0, 'skipped': 0},
            'discord': {'success': 0, 'failure': 0, 'skipped': 0},
            'total_users': len(payload.user_ids)
        }

        if not payload.user_ids:
            logger.warning("No user IDs provided for notification")
            return results

        try:
            # Get user preferences and contact info
            users_with_prefs = self._get_users_with_preferences(payload.user_ids)

            # Process each user
            for user_id, preferences in users_with_prefs.items():
                # In-App Notification
                if self._should_send_in_app(payload, preferences):
                    if self._create_in_app_notification(user_id, payload):
                        results['in_app']['created'] += 1
                    else:
                        results['in_app']['skipped'] += 1
                else:
                    results['in_app']['skipped'] += 1

            # Push Notifications (batch for efficiency)
            push_user_ids = [
                uid for uid, prefs in users_with_prefs.items()
                if self._should_send_push(payload, prefs)
            ]

            if push_user_ids:
                push_results = self._send_push_notifications(push_user_ids, payload)
                results['push']['success'] = push_results.get('success', 0)
                results['push']['failure'] = push_results.get('failure', 0)

            results['push']['skipped'] = len(payload.user_ids) - len(push_user_ids)

            # Email Notifications
            for user_id, prefs in users_with_prefs.items():
                if self._should_send_email(payload, prefs):
                    email = prefs.get('email')
                    if email:
                        if self._send_email_notification(email, payload):
                            results['email']['success'] += 1
                        else:
                            results['email']['failure'] += 1
                    else:
                        results['email']['skipped'] += 1
                else:
                    results['email']['skipped'] += 1

            # SMS Notifications
            for user_id, prefs in users_with_prefs.items():
                if self._should_send_sms(payload, prefs):
                    phone = prefs.get('phone')
                    if phone:
                        if self._send_sms_notification(phone, user_id, payload):
                            results['sms']['success'] += 1
                        else:
                            results['sms']['failure'] += 1
                    else:
                        results['sms']['skipped'] += 1
                else:
                    results['sms']['skipped'] += 1

            # Discord DM Notifications
            for user_id, prefs in users_with_prefs.items():
                if self._should_send_discord(payload, prefs):
                    discord_id = prefs.get('discord_id')
                    if discord_id:
                        if self._send_discord_notification(discord_id, payload):
                            results['discord']['success'] += 1
                        else:
                            results['discord']['failure'] += 1
                    else:
                        results['discord']['skipped'] += 1
                else:
                    results['discord']['skipped'] += 1

            # Track analytics
            self._track_notification_sent(payload, results)

            logger.info(
                f"Notification sent: type={payload.notification_type.value}, "
                f"in_app={results['in_app']['created']}, "
                f"push={results['push']['success']}, "
                f"email={results['email']['success']}, "
                f"sms={results['sms']['success']}, "
                f"discord={results['discord']['success']}"
            )

            return results

        except Exception as e:
            logger.error(f"Error in notification orchestrator: {e}", exc_info=True)
            return results

    def _get_users_with_preferences(self, user_ids: List[int]) -> Dict[int, Dict]:
        """Get users and their notification preferences along with contact info"""
        from app.models import User, Player

        db = self._get_db()
        users = db.session.query(User).filter(User.id.in_(user_ids)).all()

        result = {}
        for user in users:
            # Get player profile for phone number and discord_id
            player = db.session.query(Player).filter_by(user_id=user.id).first()

            # Get phone number from player profile
            phone = None
            is_phone_verified = False
            sms_consent_given = False
            if player:
                phone = player.phone
                is_phone_verified = getattr(player, 'is_phone_verified', False)
                sms_consent_given = getattr(player, 'sms_consent_given', False)
                # Handle encrypted phone if needed
                if not phone and hasattr(player, 'encrypted_phone') and player.encrypted_phone:
                    try:
                        from app.utils.encryption import decrypt_phone
                        phone = decrypt_phone(player.encrypted_phone)
                    except Exception:
                        pass

            # Get Discord ID from player profile
            discord_id = player.discord_id if player else None

            result[user.id] = {
                # Channel preferences
                'push_enabled': getattr(user, 'push_notifications', True),
                'email_enabled': user.email_notifications,
                'sms_enabled': user.sms_notifications,
                'discord_enabled': user.discord_notifications,

                # Contact information
                'email': user.email,
                'phone': phone,
                'discord_id': discord_id,

                # SMS verification status (CRITICAL for legal compliance)
                'is_phone_verified': is_phone_verified,
                'sms_consent_given': sms_consent_given,

                # Type-specific preferences
                'match_reminders': getattr(user, 'match_reminder_notifications', True),
                'rsvp_reminders': getattr(user, 'rsvp_reminder_notifications', True),
                'team_updates': getattr(user, 'team_update_notifications', True),
                'announcements': getattr(user, 'announcement_notifications', True),
                'dm_notifications': getattr(user, 'dm_notifications', True),
            }

        return result

    def _should_send_in_app(self, payload: NotificationPayload, preferences: Dict) -> bool:
        """Determine if in-app notification should be sent"""
        # In-app notifications are always created unless explicitly skipped
        if payload.force_in_app is False:
            return False
        return True

    def _should_send_push(self, payload: NotificationPayload, preferences: Dict) -> bool:
        """Determine if push notification should be sent based on preferences"""
        # Force override
        if payload.force_push is True:
            return True
        if payload.force_push is False:
            return False

        # Skip preferences for critical notifications
        if payload.skip_preferences:
            return True

        # Check global push preference
        if not preferences.get('push_enabled', True):
            return False

        # Check type-specific preferences
        notification_type = payload.notification_type

        if notification_type in (NotificationType.MATCH_REMINDER, NotificationType.MATCH_RESULT,
                                  NotificationType.MATCH_CANCELLED, NotificationType.MATCH_RESCHEDULED):
            return preferences.get('match_reminders', True)

        if notification_type in (NotificationType.RSVP_REMINDER, NotificationType.RSVP_CONFIRMED):
            return preferences.get('rsvp_reminders', True)

        if notification_type in (NotificationType.TEAM_UPDATE, NotificationType.TEAM_ROSTER_CHANGE):
            return preferences.get('team_updates', True)

        if notification_type in (NotificationType.LEAGUE_ANNOUNCEMENT, NotificationType.ADMIN_ANNOUNCEMENT):
            return preferences.get('announcements', True)

        # Default: send
        return True

    def _should_send_email(self, payload: NotificationPayload, preferences: Dict) -> bool:
        """Determine if email notification should be sent based on preferences"""
        # Force override
        if payload.force_email is True:
            return True
        if payload.force_email is False:
            return False

        # Skip preferences for critical notifications
        if payload.skip_preferences:
            return True

        # Check global email preference
        if not preferences.get('email_enabled', False):
            return False

        # Check if user has email
        if not preferences.get('email'):
            return False

        # Check type-specific preferences
        notification_type = payload.notification_type

        if notification_type in (NotificationType.MATCH_REMINDER, NotificationType.MATCH_RESULT,
                                  NotificationType.MATCH_CANCELLED, NotificationType.MATCH_RESCHEDULED):
            return preferences.get('match_reminders', True)

        if notification_type in (NotificationType.RSVP_REMINDER, NotificationType.RSVP_CONFIRMED):
            return preferences.get('rsvp_reminders', True)

        if notification_type in (NotificationType.TEAM_UPDATE, NotificationType.TEAM_ROSTER_CHANGE):
            return preferences.get('team_updates', True)

        if notification_type in (NotificationType.LEAGUE_ANNOUNCEMENT, NotificationType.ADMIN_ANNOUNCEMENT):
            return preferences.get('announcements', True)

        if notification_type == NotificationType.DIRECT_MESSAGE:
            return preferences.get('dm_notifications', True)

        # Default: send
        return True

    def _should_send_sms(self, payload: NotificationPayload, preferences: Dict) -> bool:
        """Determine if SMS notification should be sent based on preferences"""
        # Force override
        if payload.force_sms is True:
            # Even with force, we MUST verify phone is verified for legal compliance
            if not preferences.get('is_phone_verified', False):
                logger.warning(
                    "SMS force_sms=True but phone not verified - skipping for legal compliance"
                )
                return False
            return True
        if payload.force_sms is False:
            return False

        # Skip preferences for critical notifications
        # NOTE: Even for critical notifications, we still require phone verification
        # for TCPA legal compliance

        # Check global SMS preference
        if not preferences.get('sms_enabled', False):
            return False

        # Check if user has phone
        if not preferences.get('phone'):
            return False

        # CRITICAL: Check if phone is verified (double opt-in legal requirement)
        if not preferences.get('is_phone_verified', False):
            logger.debug(
                "SMS skipped: phone not verified (is_phone_verified=False)"
            )
            return False

        # CRITICAL: Check if SMS consent was given
        if not preferences.get('sms_consent_given', False):
            logger.debug(
                "SMS skipped: consent not given (sms_consent_given=False)"
            )
            return False

        # Check type-specific preferences
        notification_type = payload.notification_type

        if notification_type in (NotificationType.MATCH_REMINDER, NotificationType.MATCH_RESULT,
                                  NotificationType.MATCH_CANCELLED, NotificationType.MATCH_RESCHEDULED):
            return preferences.get('match_reminders', True)

        if notification_type in (NotificationType.RSVP_REMINDER, NotificationType.RSVP_CONFIRMED):
            return preferences.get('rsvp_reminders', True)

        if notification_type in (NotificationType.TEAM_UPDATE, NotificationType.TEAM_ROSTER_CHANGE):
            return preferences.get('team_updates', True)

        if notification_type in (NotificationType.LEAGUE_ANNOUNCEMENT, NotificationType.ADMIN_ANNOUNCEMENT):
            return preferences.get('announcements', True)

        if notification_type == NotificationType.DIRECT_MESSAGE:
            return preferences.get('dm_notifications', True)

        # Default: send
        return True

    def _should_send_discord(self, payload: NotificationPayload, preferences: Dict) -> bool:
        """Determine if Discord DM notification should be sent based on preferences"""
        # Force override
        if payload.force_discord is True:
            return True
        if payload.force_discord is False:
            return False

        # Skip preferences for critical notifications
        if payload.skip_preferences:
            return True

        # Check global Discord preference
        if not preferences.get('discord_enabled', False):
            return False

        # Check if user has Discord ID
        if not preferences.get('discord_id'):
            return False

        # Check type-specific preferences
        notification_type = payload.notification_type

        if notification_type in (NotificationType.MATCH_REMINDER, NotificationType.MATCH_RESULT,
                                  NotificationType.MATCH_CANCELLED, NotificationType.MATCH_RESCHEDULED):
            return preferences.get('match_reminders', True)

        if notification_type in (NotificationType.RSVP_REMINDER, NotificationType.RSVP_CONFIRMED):
            return preferences.get('rsvp_reminders', True)

        if notification_type in (NotificationType.TEAM_UPDATE, NotificationType.TEAM_ROSTER_CHANGE):
            return preferences.get('team_updates', True)

        if notification_type in (NotificationType.LEAGUE_ANNOUNCEMENT, NotificationType.ADMIN_ANNOUNCEMENT):
            return preferences.get('announcements', True)

        if notification_type == NotificationType.DIRECT_MESSAGE:
            return preferences.get('dm_notifications', True)

        # Default: send
        return True

    def _create_in_app_notification(self, user_id: int, payload: NotificationPayload) -> bool:
        """Create in-app notification in database"""
        try:
            from app.models import Notification

            db = self._get_db()

            icon = payload.icon or NOTIFICATION_ICONS.get(payload.notification_type, 'ti ti-bell')

            notification = Notification(
                user_id=user_id,
                content=payload.message,
                notification_type=payload.notification_type.value,
                icon=icon,
                read=False
            )

            db.session.add(notification)
            db.session.commit()

            return True

        except Exception as e:
            logger.error(f"Error creating in-app notification for user {user_id}: {e}")
            return False

    def _send_push_notifications(self, user_ids: List[int], payload: NotificationPayload) -> Dict[str, int]:
        """Send push notifications to users with FCM tokens"""
        try:
            from app.models import UserFCMToken

            db = self._get_db()

            # Get active FCM tokens for users
            tokens = db.session.query(UserFCMToken.fcm_token).filter(
                UserFCMToken.user_id.in_(user_ids),
                UserFCMToken.is_active == True
            ).all()

            token_list = [t[0] for t in tokens if t[0]]

            if not token_list:
                return {'success': 0, 'failure': 0}

            # Build data payload
            data = {
                'type': payload.notification_type.value,
                'timestamp': str(int(datetime.utcnow().timestamp())),
                'priority': payload.priority,
            }

            if payload.data:
                for key, value in payload.data.items():
                    data[key] = str(value) if value is not None else ''

            # Add deep link if match_id present
            if 'match_id' in data:
                if payload.notification_type == NotificationType.RSVP_REMINDER:
                    data['deep_link'] = f"ecs-fc-scheme://rsvp/{data['match_id']}"
                else:
                    data['deep_link'] = f"ecs-fc-scheme://match/{data['match_id']}"

            # Send via push service
            push_service = self._get_push_service()
            result = push_service.send_push_notification(
                tokens=token_list,
                title=payload.title,
                body=payload.message,
                data=data
            )

            return result

        except Exception as e:
            logger.error(f"Error sending push notifications: {e}")
            return {'success': 0, 'failure': len(user_ids)}

    def _send_email_notification(self, email: str, payload: NotificationPayload) -> bool:
        """Send email notification to a single user"""
        try:
            from app.email import send_email

            subject = payload.email_subject or payload.title

            # Use custom HTML body if provided, otherwise build from message
            if payload.email_html_body:
                html_body = payload.email_html_body
            else:
                html_body = self._build_email_html(payload)

            result = send_email(email, subject, html_body)
            if result:
                logger.debug(f"Email sent to {email}")
                return True
            else:
                logger.warning(f"Failed to send email to {email}")
                return False

        except Exception as e:
            logger.error(f"Error sending email to {email}: {e}")
            return False

    def _build_email_html(self, payload: NotificationPayload) -> str:
        """Build HTML email body from notification payload"""
        icon = NOTIFICATION_ICONS.get(payload.notification_type, 'ti ti-bell')

        # Escape HTML in message
        message_html = payload.message.replace('\n', '<br>')

        # Build action button if URL provided
        action_button = ''
        if payload.action_url:
            action_button = f'''
            <div style="text-align: center; margin-top: 20px;">
                <a href="{payload.action_url}"
                   style="display: inline-block; padding: 12px 24px;
                          background-color: #007bff; color: white;
                          text-decoration: none; border-radius: 5px;
                          font-weight: bold;">
                    View Details
                </a>
            </div>
            '''

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                     line-height: 1.6; color: #333; margin: 0; padding: 0;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background-color: #f8f9fa; padding: 25px; border-radius: 10px;
                            border: 1px solid #e9ecef;">
                    <h2 style="margin: 0 0 15px 0; color: #2c3e50; font-size: 20px;">
                        {payload.title}
                    </h2>
                    <div style="color: #495057; font-size: 16px;">
                        {message_html}
                    </div>
                    {action_button}
                </div>
                <div style="margin-top: 20px; padding: 15px; text-align: center;
                            color: #6c757d; font-size: 12px;">
                    <p style="margin: 5px 0;">
                        This email was sent by ECS Soccer League.
                    </p>
                    <p style="margin: 5px 0;">
                        You can manage your notification preferences in your
                        <a href="https://weareecs.com/settings" style="color: #007bff;">account settings</a>.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

    def _send_sms_notification(self, phone: str, user_id: int, payload: NotificationPayload) -> bool:
        """Send SMS notification to a single user"""
        try:
            from app.sms_helpers import send_sms

            # TCPA-compliant opt-out suffix
            opt_out_text = "\nReply STOP to opt out."

            # Build concise SMS message
            sms_message = f"{payload.title}\n{payload.message}"

            # Add action URL if provided (shortened format)
            if payload.action_url:
                sms_message += f"\nDetails: {payload.action_url}"

            # Truncate if too long for SMS (account for opt-out text)
            max_content_length = 320 - len(opt_out_text)
            if len(sms_message) > max_content_length:
                sms_message = sms_message[:max_content_length - 3] + "..."

            # Add opt-out language
            sms_message += opt_out_text

            # Map notification type to SMS message type for audit logging
            message_type = payload.notification_type or 'notification'

            success, result = send_sms(
                phone, sms_message, user_id=user_id,
                message_type=message_type,
                source='orchestrator'
            )
            if success:
                logger.debug(f"SMS sent to phone ending in ...{phone[-4:] if len(phone) >= 4 else phone}")
                return True
            else:
                logger.warning(f"Failed to send SMS: {result}")
                return False

        except Exception as e:
            logger.error(f"Error sending SMS: {e}")
            return False

    def _send_discord_notification(self, discord_id: str, payload: NotificationPayload) -> bool:
        """Send Discord DM notification to a single user"""
        try:
            import requests

            url = f"{self.bot_api_url}/api/send_dm"

            # Build Discord message (supports markdown)
            discord_message = f"**{payload.title}**\n\n{payload.message}"

            if payload.action_url:
                discord_message += f"\n\n🔗 [View Details]({payload.action_url})"

            send_payload = {
                'user_id': discord_id,
                'message': discord_message
            }

            response = requests.post(url, json=send_payload, timeout=10)

            if response.status_code == 200:
                logger.debug(f"Discord DM sent to {discord_id}")
                return True
            else:
                logger.warning(f"Failed to send Discord DM: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error sending Discord DM to {discord_id}: {e}")
            return False

    def _track_notification_sent(self, payload: NotificationPayload, results: Dict):
        """Track notification analytics (future: store in analytics table)"""
        # For now, just log - can be expanded to store in analytics table
        logger.debug(
            f"Notification analytics: type={payload.notification_type.value}, "
            f"users={results['total_users']}, "
            f"in_app={results['in_app']['created']}, "
            f"push={results['push']['success']}, "
            f"email={results['email']['success']}, "
            f"sms={results['sms']['success']}, "
            f"discord={results['discord']['success']}"
        )

    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================

    def send_match_reminder(
        self,
        match_id: int,
        user_ids: List[int],
        opponent: str,
        match_time: str,
        location: str,
        hours_until: int = 24
    ) -> Dict[str, Any]:
        """Send match reminder notification"""
        title = "⚽ Match Reminder"
        if hours_until <= 2:
            message = f"Your match against {opponent} starts in {hours_until} hour{'s' if hours_until != 1 else ''}!"
        else:
            message = f"Your match against {opponent} is tomorrow at {match_time}"

        return self.send(NotificationPayload(
            notification_type=NotificationType.MATCH_REMINDER,
            title=title,
            message=message,
            user_ids=user_ids,
            data={
                'match_id': match_id,
                'opponent': opponent,
                'location': location,
                'match_time': match_time,
            },
            priority='high' if hours_until <= 2 else 'normal'
        ))

    def send_rsvp_reminder(
        self,
        match_id: int,
        user_ids: List[int],
        opponent: str,
        match_date: str,
        days_until: int = 3
    ) -> Dict[str, Any]:
        """Send RSVP reminder notification"""
        urgency = "URGENT: " if days_until <= 1 else ""
        message = f"{urgency}Please RSVP for your match against {opponent} on {match_date}"

        return self.send(NotificationPayload(
            notification_type=NotificationType.RSVP_REMINDER,
            title="📝 RSVP Needed",
            message=message,
            user_ids=user_ids,
            data={
                'match_id': match_id,
                'opponent': opponent,
                'match_date': match_date,
            },
            priority='high' if days_until <= 1 else 'normal'
        ))

    def send_match_result(
        self,
        match_id: int,
        user_ids: List[int],
        home_team: str,
        away_team: str,
        home_score: int,
        away_score: int,
        user_team_won: bool = None
    ) -> Dict[str, Any]:
        """Send match result notification"""
        score = f"{home_score}-{away_score}"

        if user_team_won is True:
            title = "🎉 Victory!"
            message = f"Congratulations! Final score: {home_team} {score} {away_team}"
        elif user_team_won is False:
            title = "Match Result"
            message = f"Match ended: {home_team} {score} {away_team}"
        else:
            title = "Match Result"
            message = f"Final score: {home_team} {score} {away_team}"

        return self.send(NotificationPayload(
            notification_type=NotificationType.MATCH_RESULT,
            title=title,
            message=message,
            user_ids=user_ids,
            data={
                'match_id': match_id,
                'home_team': home_team,
                'away_team': away_team,
                'score': score,
            }
        ))

    def send_admin_announcement(
        self,
        user_ids: List[int],
        title: str,
        message: str,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Send admin announcement to users"""
        return self.send(NotificationPayload(
            notification_type=NotificationType.ADMIN_ANNOUNCEMENT,
            title=title,
            message=message,
            user_ids=user_ids,
            data=data,
            priority='normal'
        ))

    def send_welcome(self, user_id: int, username: str) -> Dict[str, Any]:
        """Send welcome notification to new user"""
        return self.send(NotificationPayload(
            notification_type=NotificationType.WELCOME,
            title="Welcome to ECS Soccer! 🎉",
            message=f"Hey {username}! Your account is all set up. Explore the app to find your team and matches.",
            user_ids=[user_id],
            force_in_app=True,
            force_push=True,
            skip_preferences=True  # Always send welcome
        ))

    def send_sub_request(
        self,
        match_id: int,
        user_ids: List[int],
        team_name: str,
        match_date: str,
        position: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send substitute request notification"""
        pos_text = f" ({position})" if position else ""
        message = f"{team_name} needs a sub{pos_text} for their match on {match_date}"

        return self.send(NotificationPayload(
            notification_type=NotificationType.SUB_REQUEST,
            title="🙋 Sub Needed",
            message=message,
            user_ids=user_ids,
            data={
                'match_id': match_id,
                'team_name': team_name,
                'match_date': match_date,
                'position': position or '',
            },
            priority='high'
        ))

    def send_direct_message(
        self,
        recipient_id: int,
        sender_id: int,
        sender_name: str,
        message_preview: str,
        message_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Send notification for a new direct message.

        Args:
            recipient_id: User ID of message recipient
            sender_id: User ID of message sender
            sender_name: Display name of sender
            message_preview: First ~50 chars of message
            message_id: Optional message ID for deep linking

        Returns:
            Dict with notification results
        """
        # Truncate message preview
        if len(message_preview) > 50:
            message_preview = message_preview[:47] + '...'

        return self.send(NotificationPayload(
            notification_type=NotificationType.DIRECT_MESSAGE,
            title=f"💬 {sender_name}",
            message=message_preview,
            user_ids=[recipient_id],
            data={
                'sender_id': str(sender_id),
                'sender_name': sender_name,
                'message_id': str(message_id) if message_id else '',
                'deep_link': f'ecs-fc-scheme://messages/{sender_id}',
            },
            priority='high'
        ))


# Global singleton instance
orchestrator = NotificationOrchestrator()
