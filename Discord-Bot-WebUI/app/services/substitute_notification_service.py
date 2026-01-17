# app/services/substitute_notification_service.py

"""
Substitute Notification Service

Unified service for all substitute-related notifications including:
- Contacting substitute pools (bulk)
- Contacting individual substitutes
- Sending assignment confirmations
- Multi-channel support (email, SMS, Discord)
"""

import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from flask import current_app, url_for

from app.core import db
from app.email import send_email
from app.sms_helpers import send_sms

logger = logging.getLogger(__name__)


class SubstituteNotificationService:
    """
    Unified notification service for substitute management.
    Handles email, SMS, and Discord notifications with channel tracking.
    """

    # Channel constants
    CHANNEL_EMAIL = 'EMAIL'
    CHANNEL_SMS = 'SMS'
    CHANNEL_DISCORD = 'DISCORD'

    def __init__(self):
        self.bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')

    def get_player_channels(
        self,
        player,
        pool_entry=None
    ) -> Dict[str, bool]:
        """
        Get available notification channels for a player based on their preferences.

        Args:
            player: Player model instance
            pool_entry: SubstitutePool entry (optional, for pool-specific preferences)

        Returns:
            Dict with channel availability: {'EMAIL': bool, 'SMS': bool, 'DISCORD': bool}
        """
        channels = {
            self.CHANNEL_EMAIL: False,
            self.CHANNEL_SMS: False,
            self.CHANNEL_DISCORD: False
        }

        # Check email availability
        if player.user and player.user.email:
            # Check pool-specific preference if available
            if pool_entry and hasattr(pool_entry, 'email_for_sub_requests'):
                channels[self.CHANNEL_EMAIL] = pool_entry.email_for_sub_requests
            elif player.user.email_notifications:
                channels[self.CHANNEL_EMAIL] = True

        # Check SMS availability
        if player.phone or (hasattr(player, 'encrypted_phone') and player.encrypted_phone):
            # Check pool-specific preference if available
            if pool_entry and hasattr(pool_entry, 'sms_for_sub_requests'):
                channels[self.CHANNEL_SMS] = pool_entry.sms_for_sub_requests
            elif player.user and player.user.sms_notifications:
                channels[self.CHANNEL_SMS] = True

        # Check Discord availability
        if player.discord_id:
            # Check pool-specific preference if available
            if pool_entry and hasattr(pool_entry, 'discord_for_sub_requests'):
                channels[self.CHANNEL_DISCORD] = pool_entry.discord_for_sub_requests
            elif player.user and player.user.discord_notifications:
                channels[self.CHANNEL_DISCORD] = True

        return channels

    def notify_pool(
        self,
        request_id: int,
        league_type: str,
        custom_message: str,
        channels: Optional[List[str]] = None,
        gender_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Contact all available substitutes in a pool for a specific request.

        Args:
            request_id: SubstituteRequest ID
            league_type: League type ('Premier', 'Classic', 'ECS FC')
            custom_message: Custom message from admin/coach
            channels: List of channels to use (defaults to all enabled)
            gender_filter: Optional gender filter

        Returns:
            Dict with notification results
        """
        from app.models.substitutes import (
            SubstituteRequest, SubstituteResponse, SubstitutePool,
            get_active_substitutes
        )

        results = {
            'success': False,
            'total_subs': 0,
            'notifications_sent': 0,
            'errors': [],
            'responses_created': []
        }

        try:
            # Get the substitute request
            sub_request = db.session.query(SubstituteRequest).get(request_id)
            if not sub_request:
                results['errors'].append(f'SubstituteRequest {request_id} not found')
                return results

            # Get active substitutes for this league type
            active_subs = get_active_substitutes(league_type, db.session, gender_filter)
            results['total_subs'] = len(active_subs)

            if not active_subs:
                results['errors'].append(f'No active substitutes found for {league_type}')
                return results

            # Get match details for message
            match = sub_request.match
            match_details = self._format_match_details(match, sub_request)

            for pool_entry in active_subs:
                try:
                    player = pool_entry.player

                    # Check if response already exists
                    existing_response = db.session.query(SubstituteResponse).filter_by(
                        request_id=request_id,
                        player_id=player.id
                    ).first()

                    if existing_response:
                        continue  # Skip if already contacted

                    # Get player's available channels
                    available_channels = self.get_player_channels(player, pool_entry)

                    # Filter to requested channels if specified
                    if channels:
                        for channel in list(available_channels.keys()):
                            if channel not in channels:
                                available_channels[channel] = False

                    # Skip if no channels available
                    if not any(available_channels.values()):
                        continue

                    # Create SubstituteResponse record
                    response = SubstituteResponse(
                        request_id=request_id,
                        player_id=player.id,
                        is_available=None,  # Not yet responded
                        notification_sent_at=datetime.utcnow(),
                        notification_methods=','.join(
                            ch for ch, enabled in available_channels.items() if enabled
                        )
                    )
                    response.generate_token()
                    db.session.add(response)
                    db.session.flush()  # Get the ID

                    # Build RSVP URL
                    rsvp_url = self._build_rsvp_url(response.rsvp_token)

                    # Send notifications
                    send_results = self._send_notifications(
                        player=player,
                        channels=available_channels,
                        subject=f"Sub Request: {match_details['teams']}",
                        message=self._build_message(custom_message, match_details, rsvp_url),
                        rsvp_url=rsvp_url
                    )

                    if send_results['sent_count'] > 0:
                        results['notifications_sent'] += 1
                        results['responses_created'].append(response.id)

                        # Update pool stats
                        pool_entry.requests_received = (pool_entry.requests_received or 0) + 1
                        pool_entry.last_active_at = datetime.utcnow()

                except Exception as e:
                    logger.error(f"Error notifying player {player.id}: {e}")
                    results['errors'].append(f"Player {player.id}: {str(e)}")

            db.session.commit()
            results['success'] = results['notifications_sent'] > 0

        except Exception as e:
            logger.error(f"Error in notify_pool: {e}")
            db.session.rollback()
            results['errors'].append(str(e))

        return results

    def notify_individual(
        self,
        player_id: int,
        request_id: int,
        custom_message: str,
        channels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Contact a single substitute for a request.

        Args:
            player_id: Player ID to contact
            request_id: SubstituteRequest ID
            custom_message: Custom message from admin/coach
            channels: List of channels to use (defaults to all enabled)

        Returns:
            Dict with notification results
        """
        from app.models import Player
        from app.models.substitutes import SubstituteRequest, SubstituteResponse, SubstitutePool

        results = {
            'success': False,
            'channels_used': [],
            'response_id': None,
            'errors': []
        }

        try:
            # Get player and request
            player = db.session.query(Player).get(player_id)
            if not player:
                results['errors'].append(f'Player {player_id} not found')
                return results

            sub_request = db.session.query(SubstituteRequest).get(request_id)
            if not sub_request:
                results['errors'].append(f'SubstituteRequest {request_id} not found')
                return results

            # Check if response already exists
            existing_response = db.session.query(SubstituteResponse).filter_by(
                request_id=request_id,
                player_id=player_id
            ).first()

            if existing_response:
                results['errors'].append('Player has already been contacted for this request')
                return results

            # Get pool entry if exists
            pool_entry = db.session.query(SubstitutePool).filter_by(
                player_id=player_id,
                is_active=True
            ).first()

            # Get player's available channels
            available_channels = self.get_player_channels(player, pool_entry)

            # Filter to requested channels if specified
            if channels:
                for channel in list(available_channels.keys()):
                    if channel not in channels:
                        available_channels[channel] = False

            # Skip if no channels available
            if not any(available_channels.values()):
                results['errors'].append('No notification channels available for this player')
                return results

            # Get match details
            match = sub_request.match
            match_details = self._format_match_details(match, sub_request)

            # Create SubstituteResponse record
            response = SubstituteResponse(
                request_id=request_id,
                player_id=player_id,
                is_available=None,
                notification_sent_at=datetime.utcnow(),
                notification_methods=','.join(
                    ch for ch, enabled in available_channels.items() if enabled
                )
            )
            response.generate_token()
            db.session.add(response)
            db.session.flush()

            # Build RSVP URL
            rsvp_url = self._build_rsvp_url(response.rsvp_token)

            # Send notifications
            send_results = self._send_notifications(
                player=player,
                channels=available_channels,
                subject=f"Sub Request: {match_details['teams']}",
                message=self._build_message(custom_message, match_details, rsvp_url),
                rsvp_url=rsvp_url
            )

            results['channels_used'] = send_results['channels_sent']
            results['response_id'] = response.id

            if send_results['sent_count'] > 0:
                results['success'] = True

                # Update pool stats if exists
                if pool_entry:
                    pool_entry.requests_received = (pool_entry.requests_received or 0) + 1
                    pool_entry.last_active_at = datetime.utcnow()

            db.session.commit()

        except Exception as e:
            logger.error(f"Error in notify_individual: {e}")
            db.session.rollback()
            results['errors'].append(str(e))

        return results

    def send_confirmation(
        self,
        assignment_id: int,
        league_type: str = 'pub_league'
    ) -> Dict[str, Any]:
        """
        Send confirmation to an assigned substitute via the SAME channels
        used for the initial outreach.

        Args:
            assignment_id: SubstituteAssignment ID
            league_type: Type of league ('pub_league' or 'ecs_fc')

        Returns:
            Dict with confirmation results
        """
        from app.models.substitutes import SubstituteAssignment, SubstituteResponse

        results = {
            'success': False,
            'channels_used': [],
            'errors': []
        }

        try:
            # Get the assignment
            assignment = db.session.query(SubstituteAssignment).get(assignment_id)
            if not assignment:
                results['errors'].append(f'Assignment {assignment_id} not found')
                return results

            player = assignment.player
            sub_request = assignment.request
            match = sub_request.match

            # Get the original response to find channels used for outreach
            response = db.session.query(SubstituteResponse).filter_by(
                request_id=sub_request.id,
                player_id=player.id
            ).first()

            # Determine channels to use for confirmation
            if response and response.notification_methods:
                outreach_channels = response.notification_methods.split(',')
            elif assignment.outreach_methods:
                outreach_channels = assignment.outreach_methods.split(',')
            else:
                # Fallback to all available channels
                available = self.get_player_channels(player)
                outreach_channels = [ch for ch, enabled in available.items() if enabled]

            if not outreach_channels:
                results['errors'].append('No channels available for confirmation')
                return results

            # Build confirmation message
            match_details = self._format_match_details(match, sub_request)
            confirmation_message = self._build_confirmation_message(player, match_details, assignment)

            # Convert channel list to dict format
            channels_dict = {
                self.CHANNEL_EMAIL: self.CHANNEL_EMAIL in outreach_channels,
                self.CHANNEL_SMS: self.CHANNEL_SMS in outreach_channels,
                self.CHANNEL_DISCORD: self.CHANNEL_DISCORD in outreach_channels
            }

            # Send confirmation notifications
            send_results = self._send_notifications(
                player=player,
                channels=channels_dict,
                subject=f"Confirmed: You're subbing for {match_details['team_name']}",
                message=confirmation_message,
                rsvp_url=None  # No RSVP needed for confirmations
            )

            results['channels_used'] = send_results['channels_sent']

            if send_results['sent_count'] > 0:
                results['success'] = True
                assignment.notification_sent = True
                assignment.notification_sent_at = datetime.utcnow()
                assignment.notification_methods = ','.join(send_results['channels_sent'])
                db.session.commit()

        except Exception as e:
            logger.error(f"Error in send_confirmation: {e}")
            db.session.rollback()
            results['errors'].append(str(e))

        return results

    def _format_match_details(self, match, sub_request) -> Dict[str, Any]:
        """Format match details for messages."""
        team = sub_request.team

        return {
            'teams': f"{match.home_team.name} vs {match.away_team.name}",
            'team_name': team.name,
            'date': match.date.strftime('%A, %B %d, %Y') if match.date else 'TBD',
            'time': match.time.strftime('%I:%M %p') if match.time else 'TBD',
            'location': match.location or 'TBD',
            'positions_needed': sub_request.positions_needed or 'Any position',
            'notes': sub_request.notes or ''
        }

    def _build_message(
        self,
        custom_message: str,
        match_details: Dict[str, Any],
        rsvp_url: Optional[str]
    ) -> str:
        """Build the full notification message."""
        message_parts = [
            custom_message,
            "",
            f"Match: {match_details['teams']}",
            f"Team: {match_details['team_name']}",
            f"Date: {match_details['date']}",
            f"Time: {match_details['time']}",
            f"Location: {match_details['location']}",
            f"Position(s): {match_details['positions_needed']}"
        ]

        if match_details['notes']:
            message_parts.append(f"Notes: {match_details['notes']}")

        if rsvp_url:
            message_parts.extend([
                "",
                f"Click here to respond: {rsvp_url}"
            ])

        return "\n".join(message_parts)

    def _build_confirmation_message(
        self,
        player,
        match_details: Dict[str, Any],
        assignment
    ) -> str:
        """Build the confirmation message for an assigned sub."""
        message_parts = [
            f"Hi {player.name},",
            "",
            f"You've been confirmed as a substitute for {match_details['team_name']}!",
            "",
            f"Match: {match_details['teams']}",
            f"Date: {match_details['date']}",
            f"Time: {match_details['time']}",
            f"Location: {match_details['location']}"
        ]

        if assignment.position_assigned:
            message_parts.append(f"Position: {assignment.position_assigned}")

        if assignment.notes:
            message_parts.append(f"Notes: {assignment.notes}")

        message_parts.extend([
            "",
            "Please arrive 15 minutes before the match. Thanks for stepping up!"
        ])

        return "\n".join(message_parts)

    def _build_rsvp_url(self, token: str) -> str:
        """Build the RSVP URL for a token."""
        try:
            base_url = os.getenv('BASE_URL', 'https://ecsdev.cvillehome.space')
            return f"{base_url}/sub-rsvp/{token}"
        except Exception:
            return f"/sub-rsvp/{token}"

    def _send_notifications(
        self,
        player,
        channels: Dict[str, bool],
        subject: str,
        message: str,
        rsvp_url: Optional[str]
    ) -> Dict[str, Any]:
        """
        Send notifications via specified channels.

        Returns:
            Dict with 'sent_count' and 'channels_sent' list
        """
        results = {
            'sent_count': 0,
            'channels_sent': [],
            'errors': []
        }

        # Send email
        if channels.get(self.CHANNEL_EMAIL) and player.user and player.user.email:
            try:
                html_message = self._format_email_html(message, rsvp_url)
                email_result = send_email(player.user.email, subject, html_message)
                if email_result:
                    results['sent_count'] += 1
                    results['channels_sent'].append(self.CHANNEL_EMAIL)
                    logger.info(f"Sent email to {player.user.email}")
            except Exception as e:
                logger.error(f"Failed to send email: {e}")
                results['errors'].append(f"Email: {str(e)}")

        # Send SMS
        if channels.get(self.CHANNEL_SMS):
            try:
                phone = self._get_player_phone(player)
                if phone:
                    # Shorten message for SMS
                    sms_message = self._format_sms_message(message, rsvp_url)
                    success, sms_result = send_sms(phone, sms_message)
                    if success:
                        results['sent_count'] += 1
                        results['channels_sent'].append(self.CHANNEL_SMS)
                        logger.info(f"Sent SMS to player {player.id}")
            except Exception as e:
                logger.error(f"Failed to send SMS: {e}")
                results['errors'].append(f"SMS: {str(e)}")

        # Send Discord DM
        if channels.get(self.CHANNEL_DISCORD) and player.discord_id:
            try:
                discord_result = self._send_discord_dm(player.discord_id, message)
                if discord_result:
                    results['sent_count'] += 1
                    results['channels_sent'].append(self.CHANNEL_DISCORD)
                    logger.info(f"Sent Discord DM to {player.discord_id}")
            except Exception as e:
                logger.error(f"Failed to send Discord DM: {e}")
                results['errors'].append(f"Discord: {str(e)}")

        return results

    def _format_email_html(self, message: str, rsvp_url: Optional[str]) -> str:
        """Format message as HTML for email."""
        # Convert newlines to <br> and create basic HTML structure
        html_message = message.replace('\n', '<br>')

        if rsvp_url:
            # Make the RSVP link a proper button
            html_message = html_message.replace(
                f"Click here to respond: {rsvp_url}",
                f'<br><a href="{rsvp_url}" style="display:inline-block;padding:12px 24px;'
                f'background-color:#007bff;color:white;text-decoration:none;border-radius:5px;'
                f'margin-top:10px;">Respond to Request</a>'
            )

        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background-color: #f8f9fa; padding: 20px; border-radius: 10px;">
                    {html_message}
                </div>
                <p style="color: #666; font-size: 12px; margin-top: 20px;">
                    This message was sent by ECS Soccer League.
                </p>
            </div>
        </body>
        </html>
        """

    def _format_sms_message(self, message: str, rsvp_url: Optional[str]) -> str:
        """Format message for SMS (shorter format)."""
        # Extract key info for SMS
        lines = message.split('\n')
        sms_parts = []

        for line in lines[:5]:  # First 5 lines max (reserve space for opt-out)
            if line.strip():
                sms_parts.append(line.strip())

        if rsvp_url:
            sms_parts.append(f"Respond: {rsvp_url}")

        # Add TCPA-compliant opt-out language
        sms_parts.append("Reply STOP to opt out.")

        return ' | '.join(sms_parts)[:320]  # SMS length limit

    def _get_player_phone(self, player) -> Optional[str]:
        """Get player's phone number (handles encryption)."""
        if hasattr(player, 'phone') and player.phone:
            return player.phone

        if hasattr(player, 'get_phone'):
            return player.get_phone()

        if hasattr(player, 'encrypted_phone') and player.encrypted_phone:
            # Attempt to decrypt
            try:
                from app.utils.encryption import decrypt_phone
                return decrypt_phone(player.encrypted_phone)
            except Exception:
                pass

        return None

    def _send_discord_dm(self, discord_id: str, message: str) -> bool:
        """Send a Discord DM via the bot API."""
        import requests

        try:
            url = f"{self.bot_api_url}/send_discord_dm"
            payload = {
                'discord_id': discord_id,
                'message': message
            }

            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200

        except Exception as e:
            logger.error(f"Discord DM failed: {e}")
            return False


# Singleton instance
_notification_service = None


def get_notification_service() -> SubstituteNotificationService:
    """Get the singleton notification service instance."""
    global _notification_service
    if _notification_service is None:
        _notification_service = SubstituteNotificationService()
    return _notification_service
