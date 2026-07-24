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
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from flask import current_app, url_for

from app.core import db
from app.email import send_email
from app.sms_helpers import send_sms

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared gender / pronoun matching (Phase 3 convergence)
#
# Historically each sub-notification surface reimplemented gender filtering with
# a naive `'he' in pronouns` substring test — which is ALSO true for 'she/her'
# ('she' contains 'he', 'her' contains 'he'), silently sending male-only
# requests to female players. These helpers are the ONE implementation every
# site now calls. Matching is done on word-boundary tokens, never substrings.
# ---------------------------------------------------------------------------

_PRONOUN_SPLIT_RE = re.compile(r'[^a-z]+')


def _pronoun_tokens(pronouns: Optional[str]) -> set:
    """Split a pronoun string into lowercase word tokens (e.g. 'she/her' -> {'she','her'})."""
    if not pronouns:
        return set()
    return {t for t in _PRONOUN_SPLIT_RE.split(str(pronouns).lower()) if t}


def player_matches_gender_preference(pronouns: Optional[str], gender_preference: Optional[str]) -> bool:
    """
    Inclusive gender-preference match for substitute broadcasts.

    Rules (locked): male -> {he/him, they/them, blank}, female -> {she/her,
    they/them, blank}. A blank preference matches everyone. 'they/them' and
    unset pronouns always match so non-binary / unspecified subs are never
    excluded from a broader broadcast.
    """
    if not gender_preference:
        return True
    pref = str(gender_preference).strip().lower()
    tokens = _pronoun_tokens(pronouns)
    # Inclusive: blank or they/them always match either preference.
    if not tokens or 'they' in tokens or 'them' in tokens:
        return True
    if pref == 'male':
        return 'he' in tokens or 'him' in tokens
    if pref == 'female':
        return 'she' in tokens or 'her' in tokens
    # Unknown preference -> don't exclude.
    return True


def classify_pronoun_gender(pronouns: Optional[str]) -> str:
    """
    Exclusive classification for counts/previews: 'male' | 'female' | 'other'.

    Unlike player_matches_gender_preference (inclusive), this buckets each
    player into exactly one group. 'she/her' classifies as female (NOT male,
    fixing the old substring bug); mixed / they/them / blank -> 'other'.
    """
    tokens = _pronoun_tokens(pronouns)
    has_male = 'he' in tokens or 'him' in tokens
    has_female = 'she' in tokens or 'her' in tokens
    if has_male and not has_female:
        return 'male'
    if has_female and not has_male:
        return 'female'
    return 'other'


class SubstituteNotificationService:
    """
    Unified notification service for substitute management.
    Handles email, SMS, Discord, and push notifications with channel tracking.
    """

    # Channel constants
    CHANNEL_EMAIL = 'EMAIL'
    CHANNEL_SMS = 'SMS'
    CHANNEL_DISCORD = 'DISCORD'
    CHANNEL_PUSH = 'PUSH'

    # Deep link scheme
    DEEP_LINK_SCHEME = 'ecs-fc-scheme'

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
            Dict with channel availability: {'EMAIL': bool, 'SMS': bool, 'DISCORD': bool, 'PUSH': bool}
        """
        channels = {
            self.CHANNEL_EMAIL: False,
            self.CHANNEL_SMS: False,
            self.CHANNEL_DISCORD: False,
            self.CHANNEL_PUSH: False
        }

        # Check email availability
        if player.user and player.user.email:
            # Check pool-specific preference if available
            if pool_entry and hasattr(pool_entry, 'email_for_sub_requests'):
                channels[self.CHANNEL_EMAIL] = pool_entry.email_for_sub_requests
            elif player.user.email_notifications:
                channels[self.CHANNEL_EMAIL] = True

        # Check SMS availability. Consent gate is centralized here (Phase 3):
        # SMS is NEVER a candidate channel unless the player has a phone AND has
        # verified it AND has given SMS consent. Previously only the ECS FC
        # inline paths enforced this; the unified pump did not, so a pool
        # preference alone could text an unconsented number.
        has_phone = bool(
            getattr(player, 'phone', None)
            or (hasattr(player, 'encrypted_phone') and player.encrypted_phone)
        )
        sms_consented = bool(
            getattr(player, 'is_phone_verified', False)
            and getattr(player, 'sms_consent_given', False)
        )
        if has_phone and sms_consented:
            # Check pool-specific preference if available
            if pool_entry and hasattr(pool_entry, 'sms_for_sub_requests'):
                channels[self.CHANNEL_SMS] = bool(pool_entry.sms_for_sub_requests)
            elif player.user and player.user.sms_notifications:
                channels[self.CHANNEL_SMS] = True

        # Check Discord availability
        if player.discord_id:
            # Check pool-specific preference if available
            if pool_entry and hasattr(pool_entry, 'discord_for_sub_requests'):
                channels[self.CHANNEL_DISCORD] = pool_entry.discord_for_sub_requests
            elif player.user and player.user.discord_notifications:
                channels[self.CHANNEL_DISCORD] = True

        # Check push notification availability. Honor the pool's push preference
        # when the pool model carries one (EcsFcSubPool.push_for_sub_requests);
        # SubstitutePool has no such column, so default True when absent.
        if player.user:
            push_pref = True
            if pool_entry is not None and hasattr(pool_entry, 'push_for_sub_requests'):
                push_pref = bool(getattr(pool_entry, 'push_for_sub_requests', True))
            # Check if user has push notifications enabled and has registered devices
            if push_pref and getattr(player.user, 'push_notifications', False):
                # Check for FCM tokens
                if getattr(player.user, 'fcm_tokens', None):
                    channels[self.CHANNEL_PUSH] = True

        return channels

    def notify_pool(
        self,
        request_id: int,
        league_type: str,
        custom_message: str,
        channels: Optional[List[str]] = None,
        gender_filter: Optional[str] = None,
        position_filters: Optional[List[str]] = None,
        player_ids: Optional[List[int]] = None,
        subs_needed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Contact substitutes in a pool for a specific request with filtering.

        Args:
            request_id: SubstituteRequest ID
            league_type: League type ('Premier', 'Classic')
            custom_message: Custom message from admin/coach
            channels: List of channels to use (defaults to all enabled)
            gender_filter: Optional gender filter ('male', 'female')
            position_filters: Optional position filter (['GK', 'DEF', 'MID', 'FWD'])
            player_ids: Optional specific player IDs to contact
            subs_needed: How many subs are needed (for tracking)

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
            'responses_created': [],
            'subs_needed': subs_needed
        }

        try:
            # Get the substitute request
            sub_request = db.session.query(SubstituteRequest).get(request_id)
            if not sub_request:
                results['errors'].append(f'SubstituteRequest {request_id} not found')
                return results

            # Update subs_needed on the request if provided
            if subs_needed and subs_needed > 0:
                sub_request.substitutes_needed = subs_needed

            # Get active substitutes for this league type
            active_subs = get_active_substitutes(league_type, db.session, gender_filter)

            # Apply position filter
            if position_filters:
                position_filters_upper = [p.upper() for p in position_filters]
                filtered_subs = []
                for pool_entry in active_subs:
                    if pool_entry.preferred_positions:
                        player_positions = [p.strip().upper() for p in pool_entry.preferred_positions.split(',')]
                        if any(p in position_filters_upper for p in player_positions):
                            filtered_subs.append(pool_entry)
                active_subs = filtered_subs

            # Apply specific player filter
            if player_ids:
                active_subs = [pe for pe in active_subs if pe.player_id in player_ids]

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

                    # Build RSVP URL (Pub League uses /sub-rsvp path)
                    rsvp_url = self._build_rsvp_url(response.rsvp_token, 'pub_league')

                    # Send notifications
                    send_results = self._send_notifications(
                        player=player,
                        channels=available_channels,
                        subject=f"Sub Request: {match_details['teams']}",
                        message=self._build_message(custom_message, match_details, rsvp_url),
                        rsvp_url=rsvp_url,
                        rsvp_token=response.rsvp_token,
                        league_type='pub_league',
                        request_id=request_id,
                        match_id=match.id if match else None
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

            # Build RSVP URL (Pub League uses /sub-rsvp path)
            rsvp_url = self._build_rsvp_url(response.rsvp_token, 'pub_league')

            # Send notifications
            send_results = self._send_notifications(
                player=player,
                channels=available_channels,
                subject=f"Sub Request: {match_details['teams']}",
                message=self._build_message(custom_message, match_details, rsvp_url),
                rsvp_url=rsvp_url,
                rsvp_token=response.rsvp_token,
                league_type='pub_league',
                request_id=request_id,
                match_id=match.id if match else None
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

    def notify_ecs_fc_pool(
        self,
        request_id: int,
        custom_message: Optional[str] = None,
        channels: Optional[List[str]] = None,
        gender_filter: Optional[str] = None,
        position_filters: Optional[List[str]] = None,
        player_ids: Optional[List[int]] = None,
        subs_needed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Contact ECS FC substitutes in pool for a specific request.

        Args:
            request_id: EcsFcSubRequest ID
            custom_message: Custom message from coach (auto-generated if omitted)
            channels: List of channels to use (defaults to all enabled)
            gender_filter: Optional gender filter ('male' or 'female')
            position_filters: Optional position filter (['GK', 'DEF', 'MID', 'FWD'])
            player_ids: Optional specific player IDs to contact
            subs_needed: How many subs are needed

        Returns:
            Dict with notification results
        """
        from app.models.substitutes import EcsFcSubRequest, EcsFcSubResponse, EcsFcSubPool
        from app.models import Player, User
        from sqlalchemy.orm import joinedload

        results = {
            'success': False,
            'total_subs': 0,
            'notifications_sent': 0,
            'errors': [],
            'responses_created': [],
            'subs_needed': subs_needed
        }

        try:
            sub_request = db.session.query(EcsFcSubRequest).get(request_id)
            if not sub_request:
                results['errors'].append(f'EcsFcSubRequest {request_id} not found')
                return results

            if subs_needed and subs_needed > 0:
                sub_request.substitutes_needed = subs_needed

            # Honor the request's OWN stored gender_preference when the caller did
            # not pass an explicit gender_filter. Coach/admin requests created via the
            # hub (and mobile) persist 'male'/'female' on the request itself, so a
            # pool broadcast that omits gender_filter still respects that M/F ask.
            if not gender_filter:
                gender_filter = getattr(sub_request, 'gender_preference', None) or None

            # Get "Active in Pool" ECS FC members. The EcsFcSubPool model has
            # no approval concept (no approved_at column) — is_active is the
            # only gate. Referencing EcsFcSubPool.approved_at here previously
            # raised AttributeError on every ECS FC broadcast.
            #
            # Does NOT check Player.is_current_player, matching
            # substitutes.get_active_substitutes. That flag means "paid/active THIS
            # season" and season rollover clears it, so requiring it here would mute
            # the ECS FC sub pool at every rollover — subs don't buy season passes.
            # Availability is the pool row's is_active flag (active vs resting).
            query = db.session.query(EcsFcSubPool).options(
                joinedload(EcsFcSubPool.player).joinedload(Player.user)
            ).join(Player).join(User).filter(
                EcsFcSubPool.is_active == True,
                User.is_approved == True
            )

            active_subs = query.all()

            # Apply gender filter via the ONE shared inclusive matcher
            # (they/them + blank always included; no 'he' in 'she/her' bug).
            if gender_filter:
                active_subs = [
                    pe for pe in active_subs
                    if player_matches_gender_preference(
                        getattr(pe.player, 'pronouns', None) if pe.player else None,
                        gender_filter,
                    )
                ]

            # Apply position filter
            if position_filters:
                position_filters_upper = [p.upper() for p in position_filters]
                filtered_subs = []
                for pool_entry in active_subs:
                    if pool_entry.preferred_positions:
                        player_positions = [p.strip().upper() for p in pool_entry.preferred_positions.split(',')]
                        if any(p in position_filters_upper for p in player_positions):
                            filtered_subs.append(pool_entry)
                active_subs = filtered_subs

            # Apply specific player filter
            if player_ids:
                active_subs = [pe for pe in active_subs if pe.player_id in player_ids]

            results['total_subs'] = len(active_subs)

            if not active_subs:
                results['errors'].append('No active ECS FC substitutes found')
                return results

            match_details = self._format_ecs_fc_match_details(sub_request.match, sub_request)

            for pool_entry in active_subs:
                try:
                    player = pool_entry.player

                    existing_response = db.session.query(EcsFcSubResponse).filter_by(
                        request_id=request_id,
                        player_id=player.id
                    ).first()

                    if existing_response:
                        continue

                    available_channels = self.get_player_channels(player, pool_entry)

                    if channels:
                        for channel in list(available_channels.keys()):
                            if channel not in channels:
                                available_channels[channel] = False

                    if not any(available_channels.values()):
                        continue

                    response = EcsFcSubResponse(
                        request_id=request_id,
                        player_id=player.id,
                        is_available=None,
                        notification_sent_at=datetime.utcnow(),
                        notification_methods=','.join(
                            ch for ch, enabled in available_channels.items() if enabled
                        )
                    )
                    response.generate_token()
                    db.session.add(response)
                    db.session.flush()

                    rsvp_url = self._build_rsvp_url(response.rsvp_token, 'ecs_fc')

                    send_results = self._send_notifications(
                        player=player,
                        channels=available_channels,
                        subject=f"Sub Request: ECS FC vs {match_details['opponent']}",
                        message=self._build_message(custom_message or "Sub needed!", match_details, rsvp_url),
                        rsvp_url=rsvp_url,
                        rsvp_token=response.rsvp_token,
                        league_type='ecs_fc',
                        request_id=request_id,
                        match_id=sub_request.match_id
                    )

                    if send_results['sent_count'] > 0:
                        results['notifications_sent'] += 1
                        results['responses_created'].append(response.id)

                        pool_entry.requests_received = (pool_entry.requests_received or 0) + 1
                        pool_entry.last_active_at = datetime.utcnow()

                except Exception as e:
                    logger.error(f"Error notifying ECS FC player {player.id}: {e}")
                    results['errors'].append(f"Player {player.id}: {str(e)}")

            db.session.commit()
            results['success'] = results['notifications_sent'] > 0

        except Exception as e:
            logger.error(f"Error in notify_ecs_fc_pool: {e}")
            db.session.rollback()
            results['errors'].append(str(e))

        return results

    def notify_ecs_fc_individual(
        self,
        player_id: int,
        request_id: int,
        custom_message: str,
        channels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Contact a single ECS FC substitute for a request.

        Args:
            player_id: Player ID to contact
            request_id: EcsFcSubRequest ID
            custom_message: Custom message from coach
            channels: List of channels to use (defaults to all enabled)

        Returns:
            Dict with notification results
        """
        from app.models import Player
        from app.models.substitutes import EcsFcSubRequest, EcsFcSubResponse, EcsFcSubPool

        results = {
            'success': False,
            'channels_used': [],
            'response_id': None,
            'errors': []
        }

        try:
            player = db.session.query(Player).get(player_id)
            if not player:
                results['errors'].append(f'Player {player_id} not found')
                return results

            sub_request = db.session.query(EcsFcSubRequest).get(request_id)
            if not sub_request:
                results['errors'].append(f'EcsFcSubRequest {request_id} not found')
                return results

            existing_response = db.session.query(EcsFcSubResponse).filter_by(
                request_id=request_id,
                player_id=player_id
            ).first()

            if existing_response:
                results['errors'].append('Player has already been contacted for this request')
                return results

            pool_entry = db.session.query(EcsFcSubPool).filter_by(
                player_id=player_id,
                is_active=True
            ).first()

            available_channels = self.get_player_channels(player, pool_entry)

            if channels:
                for channel in list(available_channels.keys()):
                    if channel not in channels:
                        available_channels[channel] = False

            if not any(available_channels.values()):
                results['errors'].append('No notification channels available for this player')
                return results

            match_details = self._format_ecs_fc_match_details(sub_request.match, sub_request)

            response = EcsFcSubResponse(
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

            rsvp_url = self._build_rsvp_url(response.rsvp_token, 'ecs_fc')

            send_results = self._send_notifications(
                player=player,
                channels=available_channels,
                subject=f"Sub Request: ECS FC vs {match_details['opponent']}",
                message=self._build_message(custom_message, match_details, rsvp_url),
                rsvp_url=rsvp_url,
                rsvp_token=response.rsvp_token,
                league_type='ecs_fc',
                request_id=request_id,
                match_id=sub_request.match_id
            )

            results['channels_used'] = send_results['channels_sent']
            results['response_id'] = response.id

            if send_results['sent_count'] > 0:
                results['success'] = True

                if pool_entry:
                    pool_entry.requests_received = (pool_entry.requests_received or 0) + 1
                    pool_entry.last_active_at = datetime.utcnow()

            db.session.commit()

        except Exception as e:
            logger.error(f"Error in notify_ecs_fc_individual: {e}")
            db.session.rollback()
            results['errors'].append(str(e))

        return results

    def _format_ecs_fc_match_details(self, match, sub_request) -> Dict[str, Any]:
        """Format ECS FC match details for messages."""
        team = sub_request.team

        return {
            'teams': f"ECS FC vs {match.opponent_name}" if match else 'ECS FC Match',
            'opponent': match.opponent_name if match else 'TBD',
            'team_name': team.name if team else 'ECS FC',
            'date': match.match_date.strftime('%A, %B %d, %Y') if match and match.match_date else 'TBD',
            'time': match.match_time.strftime('%I:%M %p') if match and match.match_time else 'TBD',
            'location': match.location if match else 'TBD',
            'positions_needed': sub_request.positions_needed or 'Any position',
            'notes': sub_request.notes or ''
        }

    def notify_response_received(
        self,
        request_id: int,
        player_id: int,
        is_available: bool,
        response_method: str,
        league_type: str = 'pub_league',
    ) -> Dict[str, Any]:
        """
        Notify the appropriate audience when a sub has responded with availability.

        One recipient rule for BOTH leagues (Phase 3 convergence): fan out to the
        requesting coach AND every relevant admin (Global Admin + Pub League
        Admin). Previously Pub League notified admins-only and ECS FC notified
        the coach-only, so each league's other audience was silently blind.

        The push payload follows the contract in docs/SUB_SYSTEM_ALIGNMENT.md §5.2:
            data.type = 'sub_response'
            data.request_id, data.league_type, data.player_name,
            data.is_available (string), data.response_method.

        Args:
            request_id: SubstituteRequest / EcsFcSubRequest ID
            player_id: Responding player's ID
            is_available: Their availability answer
            response_method: 'app' | 'web' | 'SMS' | 'DISCORD'
            league_type: 'pub_league' or 'ecs_fc'

        Returns:
            {success: bool, recipients: int, errors: [...]}
        """
        from app.models import Player
        from app.models.core import Role
        from app.models.substitutes import SubstituteRequest, EcsFcSubRequest
        from app.services.notification_orchestrator import (
            orchestrator, NotificationType, NotificationPayload,
        )

        result = {'success': False, 'recipients': 0, 'errors': []}

        try:
            player = db.session.query(Player).get(player_id)
            player_name = player.name if player else f'Player {player_id}'

            if league_type == 'ecs_fc':
                sub_request = db.session.query(EcsFcSubRequest).get(request_id)
                if not sub_request:
                    result['errors'].append(f'EcsFcSubRequest {request_id} not found')
                    return result
                team_name = sub_request.team.name if sub_request.team else 'ECS FC'
                match_blurb = ''
                if sub_request.match and sub_request.match.match_date:
                    match_blurb = f" on {sub_request.match.match_date.strftime('%A, %B %d')}"
            else:
                sub_request = db.session.query(SubstituteRequest).get(request_id)
                if not sub_request:
                    result['errors'].append(f'SubstituteRequest {request_id} not found')
                    return result
                team_name = sub_request.team.name if sub_request.team else 'Unknown Team'
                match_blurb = ''
                if sub_request.match and sub_request.match.date:
                    match_blurb = f" on {sub_request.match.date.strftime('%A, %B %d')}"

            # Recipient rule is admin-configurable (Substitute Command Center →
            # Settings) via sub_notify_on_response:
            #   'coach_and_admins' (default) — requesting coach + admins (the
            #       historical converged behavior for both leagues),
            #   'admins_only' — admins only,
            #   'coach_only' — requesting coach only.
            from app.models.admin_config import AdminConfig
            notify_mode = AdminConfig.get_setting('sub_notify_on_response', 'coach_and_admins')

            # The Settings tab writes a SHORTER vocabulary than this code was
            # reading: it saves 'coach_admins' | 'admins' | 'coach', while the
            # branches below only matched 'coach_and_admins' | 'admins_only' |
            # 'coach_only'. The default made it look fine until an admin pressed
            # Save on that tab -- after which notify_mode matched no branch,
            # recipient_ids stayed empty, and EVERY sub-response notification
            # silently stopped. Accept both spellings.
            notify_mode = {
                'coach_admins': 'coach_and_admins',
                'admins': 'admins_only',
                'coach': 'coach_only',
            }.get(notify_mode, notify_mode)

            recipient_ids = set()
            if notify_mode in ('coach_and_admins', 'coach_only'):
                if getattr(sub_request, 'requested_by', None):
                    recipient_ids.add(sub_request.requested_by)
            if notify_mode in ('coach_and_admins', 'admins_only'):
                admin_roles = db.session.query(Role).filter(
                    Role.name.in_(['Global Admin', 'Pub League Admin'])
                ).all()
                for role in admin_roles:
                    for u in role.users:
                        recipient_ids.add(u.id)
            user_ids = list(recipient_ids)

            if not user_ids:
                result['errors'].append('No recipients to notify')
                return result

            availability_text = 'is available' if is_available else 'is NOT available'
            orchestrator.send(NotificationPayload(
                notification_type=NotificationType.SUB_REQUEST,
                title='Sub Response Received',
                message=f'{player_name} {availability_text} for {team_name}{match_blurb}',
                user_ids=user_ids,
                data={
                    'type': 'sub_response',
                    'request_id': str(request_id),
                    'player_name': player_name,
                    'is_available': str(is_available).lower(),
                    'league_type': league_type,
                    'response_method': response_method,
                    'click_action': 'FLUTTER_NOTIFICATION_CLICK',
                },
            ))

            result['success'] = True
            result['recipients'] = len(user_ids)
            logger.info(
                f"Notified {len(user_ids)} {league_type} recipients of {response_method} "
                f"sub response from {player_name}"
            )

        except Exception as e:
            logger.error(f"Error in notify_response_received: {e}")
            result['errors'].append(str(e))

        return result

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
        # league_type selects the correct model family. Passing an ECS FC
        # assignment id with the Pub League models (the old hard-coded behavior)
        # either found nothing or mis-looked-up a colliding Pub League row.
        if league_type == 'ecs_fc':
            from app.models.substitutes import (
                EcsFcSubAssignment as AssignmentModel,
                EcsFcSubResponse as ResponseModel,
            )
        else:
            from app.models.substitutes import (
                SubstituteAssignment as AssignmentModel,
                SubstituteResponse as ResponseModel,
            )

        results = {
            'success': False,
            'channels_used': [],
            'errors': []
        }

        try:
            # Get the assignment
            assignment = db.session.query(AssignmentModel).get(assignment_id)
            if not assignment:
                results['errors'].append(f'Assignment {assignment_id} not found')
                return results

            player = assignment.player
            sub_request = assignment.request
            match = sub_request.match

            # Get the original response to find channels used for outreach
            response = db.session.query(ResponseModel).filter_by(
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

            # Build confirmation message (ECS FC and Pub League format match
            # details from different relationships/columns).
            if league_type == 'ecs_fc':
                match_details = self._format_ecs_fc_match_details(match, sub_request)
            else:
                match_details = self._format_match_details(match, sub_request)
            confirmation_message = self._build_confirmation_message(player, match_details, assignment)

            # Convert channel list to dict format. For assignment confirmations
            # we also send push if the user has the app installed, even if the
            # initial outreach didn't go through push — the assignment event is
            # critical and the app screen needs the type='substitute_assignment'
            # signal to route to MyAssignmentsScreen.
            available_channels = self.get_player_channels(player)
            channels_dict = {
                self.CHANNEL_EMAIL: self.CHANNEL_EMAIL in outreach_channels,
                self.CHANNEL_SMS: self.CHANNEL_SMS in outreach_channels,
                self.CHANNEL_DISCORD: self.CHANNEL_DISCORD in outreach_channels,
                self.CHANNEL_PUSH: available_channels.get(self.CHANNEL_PUSH, False),
            }

            # Send confirmation notifications
            send_results = self._send_notifications(
                player=player,
                channels=channels_dict,
                subject=f"Confirmed: You're subbing for {match_details['team_name']}",
                message=confirmation_message,
                rsvp_url=None,  # No RSVP needed for confirmations
                league_type=league_type,
                request_id=sub_request.id if sub_request else None,
                match_id=match.id if match else None,
                purpose='assignment',
            )

            results['channels_used'] = send_results['channels_sent']

            if send_results['sent_count'] > 0:
                results['success'] = True
                assignment.notification_sent = True
                assignment.notification_sent_at = datetime.utcnow()
                assignment.notification_methods = ','.join(send_results['channels_sent'])
                db.session.commit()

            # When this assignment completes the request, tell the other pending
            # responders they weren't selected (SUB_FILLED). Isolated so a failure
            # here never rolls back the confirmation we just committed.
            if getattr(sub_request, 'status', None) == 'FILLED':
                try:
                    notified = self._notify_not_selected(sub_request, league_type)
                    if notified:
                        results['not_selected_notified'] = notified
                except Exception as ns_err:
                    logger.error(f"Error notifying not-selected subs: {ns_err}")

        except Exception as e:
            logger.error(f"Error in send_confirmation: {e}")
            db.session.rollback()
            results['errors'].append(str(e))

        return results

    def _notify_not_selected(self, sub_request, league_type: str = 'pub_league') -> int:
        """
        Notify everyone who offered/was pending for a now-FILLED request that
        they weren't selected (NotificationType.SUB_FILLED). Excludes players who
        explicitly declined and anyone actually assigned.

        Returns the number of users notified.
        """
        from app.models.admin_config import AdminConfig
        # Admin toggle (Substitute Command Center → Settings). Default True keeps
        # the current behavior of telling not-selected subs the spot was filled.
        if not AdminConfig.get_setting('sub_notify_not_selected', True):
            return 0

        from app.services.notification_orchestrator import (
            orchestrator, NotificationType, NotificationPayload,
        )

        if league_type == 'ecs_fc':
            from app.models.substitutes import (
                EcsFcSubResponse as ResponseModel,
                EcsFcSubAssignment as AssignmentModel,
            )
        else:
            from app.models.substitutes import (
                SubstituteResponse as ResponseModel,
                SubstituteAssignment as AssignmentModel,
            )

        assigned_ids = {
            a.player_id
            for a in db.session.query(AssignmentModel).filter_by(request_id=sub_request.id).all()
        }

        # is_available is not False -> available (True) or still pending (None).
        responses = db.session.query(ResponseModel).filter(
            ResponseModel.request_id == sub_request.id,
            ResponseModel.is_available.isnot(False),
        ).all()

        user_ids = set()
        for r in responses:
            if r.player_id in assigned_ids:
                continue
            player = r.player
            if player and getattr(player, 'user_id', None):
                user_ids.add(player.user_id)

        if not user_ids:
            return 0

        team_name = sub_request.team.name if getattr(sub_request, 'team', None) else 'the team'
        orchestrator.send(NotificationPayload(
            notification_type=NotificationType.SUB_FILLED,
            title='Substitute Spot Filled',
            message=f"The sub spot for {team_name} has been filled. Thanks for offering to help!",
            user_ids=list(user_ids),
            data={
                'type': 'sub_filled',
                'request_id': str(sub_request.id),
                'league_type': league_type,
                'click_action': 'FLUTTER_NOTIFICATION_CLICK',
            },
        ))
        logger.info(
            f"Notified {len(user_ids)} not-selected {league_type} subs for request {sub_request.id}"
        )
        return len(user_ids)

    def notify_request_cancelled(
        self,
        request_id: int,
        league_type: str = 'pub_league',
    ) -> Dict[str, Any]:
        """
        Notify everyone with a still-pending response for a request that it has
        been cancelled. Sends a Discord DM (where connected) plus a push
        (NotificationType.SUB_REQUEST, data.type='sub_cancelled'). Players who
        already declined are skipped.

        This performs synchronous outbound sends, so callers on the web request
        path should dispatch it via Celery (see
        tasks_substitute_pools.notify_substitute_request_cancelled) rather than
        invoking it inside an open DB transaction.

        Returns {success, recipients, errors}.
        """
        from app.services.notification_orchestrator import (
            orchestrator, NotificationType, NotificationPayload,
        )

        result = {'success': False, 'recipients': 0, 'errors': []}

        try:
            if league_type == 'ecs_fc':
                from app.models.substitutes import (
                    EcsFcSubRequest as RequestModel,
                    EcsFcSubResponse as ResponseModel,
                )
            else:
                from app.models.substitutes import (
                    SubstituteRequest as RequestModel,
                    SubstituteResponse as ResponseModel,
                )

            sub_request = db.session.query(RequestModel).get(request_id)
            if not sub_request:
                result['errors'].append(f'Request {request_id} not found')
                return result

            # is_available is not False -> pending (None) or previously available.
            responses = db.session.query(ResponseModel).filter(
                ResponseModel.request_id == request_id,
                ResponseModel.is_available.isnot(False),
            ).all()

            team_name = sub_request.team.name if getattr(sub_request, 'team', None) else 'your team'
            message = (
                f"The substitute request for {team_name} has been cancelled. "
                f"No action needed — thanks for your help!"
            )

            user_ids = set()
            for r in responses:
                player = r.player
                if not player:
                    continue
                if getattr(player, 'user_id', None):
                    user_ids.add(player.user_id)
                if getattr(player, 'discord_id', None):
                    try:
                        self._send_discord_dm(player.discord_id, message)
                    except Exception as dm_err:
                        result['errors'].append(f"Discord DM: {dm_err}")

            if user_ids:
                orchestrator.send(NotificationPayload(
                    notification_type=NotificationType.SUB_REQUEST,
                    title='Substitute Request Cancelled',
                    message=message,
                    user_ids=list(user_ids),
                    data={
                        'type': 'sub_cancelled',
                        'request_id': str(request_id),
                        'league_type': league_type,
                        'click_action': 'FLUTTER_NOTIFICATION_CLICK',
                    },
                ))

            result['success'] = True
            result['recipients'] = len(user_ids)
            logger.info(
                f"Notified {len(user_ids)} pending {league_type} responders that "
                f"request {request_id} was cancelled"
            )

        except Exception as e:
            logger.error(f"Error in notify_request_cancelled: {e}")
            result['errors'].append(str(e))

        return result

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
        """Build the confirmation message for an assigned sub.

        Admin-configurable (Substitute Command Center → Settings):
          - sub_arrive_early_min: minutes-before lead time (default 15, the
            historical wording).
          - sub_confirmation_msg: optional custom body with {team}{date}{time}
            {location}{early} token substitution; unset => the structured
            default below (current behavior).
        """
        from app.models.admin_config import AdminConfig

        early = AdminConfig.get_setting('sub_arrive_early_min', 15)
        template = AdminConfig.get_setting('sub_confirmation_msg', None)

        if template and str(template).strip():
            body = (
                str(template)
                .replace('{team}', str(match_details.get('team_name', '')))
                .replace('{date}', str(match_details.get('date', '')))
                .replace('{time}', str(match_details.get('time', '')))
                .replace('{location}', str(match_details.get('location', '')))
                .replace('{early}', str(early))
            )
            message_parts = [f"Hi {player.name},", "", body]
            if assignment.position_assigned:
                message_parts.append(f"Position: {assignment.position_assigned}")
            if assignment.notes:
                message_parts.append(f"Notes: {assignment.notes}")
            return "\n".join(message_parts)

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
            f"Please arrive {early} minutes before the match. Thanks for stepping up!"
        ])

        return "\n".join(message_parts)

    def _build_rsvp_url(self, token: str, league_type: str = 'pub_league') -> str:
        """
        Build the RSVP URL for a token.

        Args:
            token: RSVP token
            league_type: 'pub_league' or 'ecs_fc' for different URL patterns

        Returns:
            Full RSVP URL
        """
        try:
            base_url = os.getenv('BASE_URL', 'https://ecsdev.cvillehome.space')
            if league_type == 'ecs_fc':
                return f"{base_url}/ecs-fc/sub-response/{token}"
            return f"{base_url}/sub-rsvp/{token}"
        except Exception:
            if league_type == 'ecs_fc':
                return f"/ecs-fc/sub-response/{token}"
            return f"/sub-rsvp/{token}"

    def _build_deep_link(self, token: str, league_type: str = 'pub_league') -> str:
        """
        Build a deep link URL for mobile app.

        Args:
            token: RSVP token
            league_type: 'pub_league' or 'ecs_fc' for different deep link paths

        Returns:
            Deep link URL (custom scheme)
        """
        if league_type == 'ecs_fc':
            return f"{self.DEEP_LINK_SCHEME}://sub-response/{token}"
        return f"{self.DEEP_LINK_SCHEME}://sub-rsvp/{token}"

    def _send_notifications(
        self,
        player,
        channels: Dict[str, bool],
        subject: str,
        message: str,
        rsvp_url: Optional[str],
        rsvp_token: Optional[str] = None,
        league_type: str = 'pub_league',
        request_id: Optional[int] = None,
        match_id: Optional[int] = None,
        purpose: str = 'request',
        reachout_id: Optional[int] = None,
        time_slots: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Send notifications via specified channels.

        Args:
            player: Player model instance
            channels: Dict of channel availability
            subject: Notification subject/title
            message: Full message text
            rsvp_url: Web URL for RSVP
            rsvp_token: RSVP token for deep linking
            league_type: 'pub_league' or 'ecs_fc'
            request_id: SubstituteRequest ID for mobile API
            match_id: Match ID for mobile API
            purpose: 'request' (initial outreach asking availability) or
                'assignment' (confirmation that the player has been assigned).
                Controls the FCM data.type field that Flutter routes on.
            reachout_id: SubstituteReachout ID. When set, the push is typed
                'sub_reachout' and carries the id so the app can answer at
                POST /substitutes/reachout/<id>/respond (which folds the reply
                into the availability pool) instead of a per-match request screen.
            time_slots: Slots the reach-out asked about, so the app can
                pre-select them on the response screen.

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

        # Send push notification
        if channels.get(self.CHANNEL_PUSH) and player.user:
            try:
                deep_link = self._build_deep_link(rsvp_token, league_type) if rsvp_token else None
                push_data = {
                    'type': (
                        'substitute_assignment' if purpose == 'assignment'
                        else 'sub_reachout' if reachout_id
                        else 'sub_request'
                    ),
                    'token': rsvp_token,
                    'league_type': league_type,
                    'deep_link': deep_link,
                    'web_url': rsvp_url
                }
                # Add reachout_id / request_id / match_id for mobile API access.
                # reachout_id routes the app to the availability-pool response
                # endpoint; request_id would send it to a single-match screen.
                if reachout_id:
                    push_data['reachout_id'] = str(reachout_id)
                if time_slots:
                    push_data['time_slots'] = ','.join(str(s) for s in time_slots)
                if request_id:
                    push_data['request_id'] = str(request_id)
                if match_id:
                    push_data['match_id'] = str(match_id)

                push_result = self._send_push_notification(
                    user=player.user,
                    title=subject,
                    body=message.split('\n')[0][:100],  # First line, truncated
                    data=push_data
                )
                if push_result:
                    results['sent_count'] += 1
                    results['channels_sent'].append(self.CHANNEL_PUSH)
                    logger.info(f"Sent push notification to user {player.user.id}")
            except Exception as e:
                logger.error(f"Failed to send push notification: {e}")
                results['errors'].append(f"Push: {str(e)}")

        return results

    def _send_push_notification(
        self,
        user,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Send a push notification to a user via FCM.

        Args:
            user: User model instance
            title: Notification title
            body: Notification body
            data: Additional data payload (for deep linking)

        Returns:
            True if at least one device received the notification
        """
        try:
            from app.services.notification_orchestrator import (
                orchestrator, NotificationType, NotificationPayload
            )

            payload = NotificationPayload(
                notification_type=NotificationType.SUB_REQUEST,
                title=title,
                message=body,
                user_ids=[user.id],
                data=data,
                force_push=True,
                force_in_app=False,
                force_email=False,
                force_sms=False,
                force_discord=False
            )

            result = orchestrator.send(payload)
            return result.get('push', {}).get('success', False)

        except Exception as e:
            logger.error(f"Push notification error: {e}")
            return False

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

    # ------------------------------------------------------------------
    # Ad-hoc reach-outs (closed-loop sub availability)
    # ------------------------------------------------------------------

    def send_reachout(self, reachout, recipients, session=None) -> Dict[str, Any]:
        """Send a SubstituteReachout to each recipient over their channels.

        The reach-out asks "can you sub this week?" for a date + time slot(s) and
        feeds the SAME availability pool as the Discord poll. For TARGETED reach-outs
        the message NEVER reveals the team (no team name / opponent) — only the date,
        time slot(s) and the ask. General reach-outs are identically team-agnostic.

        Stamps `channels_sent` + `notification_sent_at` on each
        SubstituteReachoutRecipient and includes a secure response link/token.
        Reuses the shared `_send_notifications` channel plumbing (push/discord/sms/
        email) — this is NOT a divergent 4th notifier.

        Args:
            reachout: SubstituteReachout row (kind/league_type/match_date/time_slots/
                channels/message/request_id).
            recipients: iterable of SubstituteReachoutRecipient rows (already persisted
                with a player_id; tokens are generated here if missing).
            session: optional SQLAlchemy session the recipients live in (defaults to
                db.session). The caller is responsible for committing.

        Returns:
            {total, sent, per_channel_counts: {CHANNEL: n}, errors: [...]}
        """
        sess = session or db.session

        results = {
            'total': 0,
            'sent': 0,
            'per_channel_counts': {},
            'errors': [],
        }

        # Channel allow-list from the reach-out (uppercased). Empty/None = all channels.
        requested_channels = None
        if reachout.channels:
            requested_channels = {
                c.strip().upper() for c in reachout.channels.split(',') if c.strip()
            }

        date_str = (
            reachout.match_date.strftime('%A, %B %d, %Y')
            if reachout.match_date else 'this week'
        )
        short_date = reachout.match_date.strftime('%b %d') if reachout.match_date else 'soon'
        slots = reachout.time_slots or []
        slot_str = (
            ', '.join(self._format_reachout_slot(s) for s in slots) if slots else 'any time'
        )

        # When the admin left the reach-out message blank, fall back to the
        # configurable default body (Substitute Command Center → Settings):
        # sub_reachout_msg_general for kind='general', sub_reachout_msg_targeted
        # for kind='targeted'. Both stay team-agnostic — NO {team} token.
        # Tokens: {league}{slots}{date}{slot}. Unset => None => _build_reachout_message
        # uses its hardcoded wording (current behavior).
        default_note = reachout.message
        if not (default_note and str(default_note).strip()):
            from app.models.admin_config import AdminConfig
            if getattr(reachout, 'kind', 'general') == 'targeted':
                tmpl = AdminConfig.get_setting('sub_reachout_msg_targeted', None)
            else:
                tmpl = AdminConfig.get_setting('sub_reachout_msg_general', None)
            if tmpl and str(tmpl).strip():
                default_note = (
                    str(tmpl)
                    .replace('{league}', str(reachout.league_type or ''))
                    .replace('{slots}', str(len(slots)))
                    .replace('{date}', date_str)
                    .replace('{slot}', slot_str)
                )
            else:
                default_note = None

        for recipient in recipients:
            results['total'] += 1
            try:
                player = recipient.player
                if player is None:
                    from app.models import Player
                    player = sess.query(Player).get(recipient.player_id)
                if player is None:
                    results['errors'].append(f"Recipient {recipient.id}: player not found")
                    continue

                available_channels = self.get_player_channels(player)

                # Restrict to the reach-out's requested channels if specified.
                if requested_channels is not None:
                    for ch in list(available_channels.keys()):
                        if ch not in requested_channels:
                            available_channels[ch] = False

                if not any(available_channels.values()):
                    continue

                # Ensure the recipient has a secure response token for the web link.
                if not recipient.response_token:
                    recipient.generate_token()

                web_url = self._build_reachout_url(recipient.response_token)
                message = self._build_reachout_message(
                    default_note, date_str, slot_str, web_url
                )
                subject = f"Can you sub on {short_date}?"

                # Discord reach-outs get native Yes/No buttons that write back to
                # /internal/subs/reachout-response. The generic _send_discord_dm
                # attaches NO view, so send Discord ourselves with view_type +
                # recipient id, then disable it so the generic sender doesn't
                # double-send a button-less DM.
                extra_sent = []
                if available_channels.get(self.CHANNEL_DISCORD) and player.discord_id:
                    if self._send_reachout_discord_dm(player.discord_id, message, recipient.id):
                        extra_sent.append(self.CHANNEL_DISCORD)
                    available_channels[self.CHANNEL_DISCORD] = False

                send_results = self._send_notifications(
                    player=player,
                    channels=available_channels,
                    subject=subject,
                    message=message,
                    rsvp_url=web_url,
                    rsvp_token=recipient.response_token,
                    league_type=reachout.league_type,
                    request_id=reachout.request_id,
                    match_id=None,
                    purpose='request',
                    reachout_id=reachout.id,
                    time_slots=slots,
                )

                combined_sent = list(send_results.get('channels_sent', [])) + extra_sent
                if combined_sent:
                    results['sent'] += 1
                    recipient.channels_sent = ','.join(combined_sent)
                    recipient.notification_sent_at = datetime.utcnow()
                    for ch in combined_sent:
                        results['per_channel_counts'][ch] = (
                            results['per_channel_counts'].get(ch, 0) + 1
                        )

            except Exception as e:
                logger.error(f"Error sending reach-out to recipient {getattr(recipient, 'id', '?')}: {e}")
                results['errors'].append(str(e))

        return results

    def _format_reachout_slot(self, slot) -> str:
        """'08:20' -> '8:20am'. Falls back to the raw value on any parse error."""
        try:
            hh, mm = str(slot).split(':')
            h, m = int(hh), int(mm)
            ampm = 'am' if h < 12 else 'pm'
            h12 = h % 12 or 12
            return f"{h12}:{m:02d}{ampm}"
        except Exception:
            return str(slot)

    def _build_reachout_message(self, admin_note, date_str, slot_str, web_url) -> str:
        """Build the team-agnostic reach-out body (never names a team/opponent)."""
        parts = []
        if admin_note:
            parts.extend([admin_note.strip(), ""])
        parts.extend([
            "Can you sub this week?",
            f"Date: {date_str}",
            f"Time(s): {slot_str}",
            "",
            f"Click here to respond: {web_url}",
        ])
        return "\n".join(parts)

    def _build_reachout_url(self, token: str) -> str:
        """Secure web response link for a reach-out recipient token."""
        base_url = os.getenv('BASE_URL', 'https://ecsdev.cvillehome.space')
        return f"{base_url}/sub-reachout/{token}"

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

    def _send_reachout_discord_dm(self, discord_id: str, message: str,
                                  reachout_recipient_id: int) -> bool:
        """Send a reach-out Discord DM WITH the Yes/No availability buttons.

        Passes view_type='subs_reachout' + reachout_recipient_id so the bot attaches
        SubsReachoutView; the sub's click posts back to /internal/subs/reachout-response.
        """
        import requests

        try:
            url = f"{self.bot_api_url}/send_discord_dm"
            payload = {
                'discord_id': discord_id,
                'message': message,
                'view_type': 'subs_reachout',
                'reachout_recipient_id': int(reachout_recipient_id),
            }
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Reach-out Discord DM failed: {e}")
            return False


# Singleton instance
_notification_service = None


def get_notification_service() -> SubstituteNotificationService:
    """Get the singleton notification service instance."""
    global _notification_service
    if _notification_service is None:
        _notification_service = SubstituteNotificationService()
    return _notification_service
