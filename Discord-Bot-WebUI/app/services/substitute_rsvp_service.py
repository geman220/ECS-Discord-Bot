# app/services/substitute_rsvp_service.py

"""
Substitute RSVP Service

Service for handling RSVP token validation and response processing
for substitute requests.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, Union

from app.core import db

logger = logging.getLogger(__name__)


class SubstituteRSVPService:
    """
    Service for RSVP token management and response processing.
    """

    def validate_token(
        self,
        token: str,
        league_type: str = 'pub_league'
    ) -> Tuple[bool, Optional[Any], str]:
        """
        Validate an RSVP token and return the associated response.

        Args:
            token: The RSVP token to validate
            league_type: Type of league ('pub_league' or 'ecs_fc')

        Returns:
            Tuple of (is_valid, response_object, error_message)
        """
        from app.models.substitutes import SubstituteResponse, EcsFcSubResponse

        if not token:
            return False, None, 'No token provided'

        try:
            # Try pub league first
            response = db.session.query(SubstituteResponse).filter_by(
                rsvp_token=token
            ).first()

            if not response:
                # Try ECS FC
                response = db.session.query(EcsFcSubResponse).filter_by(
                    rsvp_token=token
                ).first()

            if not response:
                return False, None, 'Invalid or expired token'

            if not response.is_token_valid():
                if response.token_used_at:
                    return False, response, 'This request has already been responded to'
                else:
                    return False, None, 'This token has expired'

            return True, response, ''

        except Exception as e:
            logger.error(f"Error validating token: {e}")
            return False, None, 'Error validating token'

    def get_request_details(
        self,
        response
    ) -> Dict[str, Any]:
        """
        Get detailed information about a substitute request from a response.

        Args:
            response: SubstituteResponse or EcsFcSubResponse object

        Returns:
            Dict with request details for display
        """
        try:
            request = response.request
            match = request.match
            team = request.team
            player = response.player

            return {
                'request_id': request.id,
                'player_id': player.id,
                'player_name': player.name,
                'team_name': team.name,
                'match': {
                    'id': match.id,
                    'home_team': match.home_team.name,
                    'away_team': match.away_team.name,
                    'date': match.date.strftime('%A, %B %d, %Y') if match.date else 'TBD',
                    'time': match.time.strftime('%I:%M %p') if match.time else 'TBD',
                    'location': match.location or 'TBD'
                },
                'positions_needed': request.positions_needed or 'Any position',
                'notes': request.notes or '',
                'already_responded': response.responded_at is not None,
                'current_response': response.is_available
            }

        except Exception as e:
            logger.error(f"Error getting request details: {e}")
            return {}

    def process_response(
        self,
        token: str,
        user_id: int,
        is_available: bool,
        response_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process an RSVP response from a user.

        Args:
            token: The RSVP token
            user_id: The logged-in user's ID (for verification)
            is_available: Whether the sub is available
            response_text: Optional comment from the sub

        Returns:
            Dict with processing results
        """
        from app.models import User
        from app.models.substitutes import SubstitutePool

        results = {
            'success': False,
            'message': '',
            'response_id': None
        }

        try:
            # Validate the token
            is_valid, response, error = self.validate_token(token)

            if not is_valid:
                results['message'] = error
                return results

            # Verify the user matches the player
            user = db.session.query(User).get(user_id)
            if not user or not user.player:
                results['message'] = 'User account not linked to a player profile'
                return results

            if user.player.id != response.player_id:
                results['message'] = 'You are not authorized to respond to this request'
                return results

            # Check if already responded
            if response.responded_at is not None:
                results['message'] = 'You have already responded to this request'
                results['response_id'] = response.id
                return results

            # Update the response
            response.is_available = is_available
            response.response_text = response_text
            response.responded_at = datetime.utcnow()
            response.response_method = 'WEB'
            response.mark_token_used()

            # Update pool statistics if they accepted
            if is_available:
                pool_entry = db.session.query(SubstitutePool).filter_by(
                    player_id=response.player_id,
                    is_active=True
                ).first()

                if pool_entry:
                    pool_entry.requests_accepted = (pool_entry.requests_accepted or 0) + 1
                    pool_entry.last_active_at = datetime.utcnow()

            db.session.commit()

            results['success'] = True
            results['response_id'] = response.id
            results['message'] = 'Thank you! Your response has been recorded.'

            if is_available:
                results['message'] += ' We will contact you if you are selected.'

        except Exception as e:
            logger.error(f"Error processing RSVP response: {e}")
            db.session.rollback()
            results['message'] = 'An error occurred while processing your response'

        return results

    def get_request_availability_status(
        self,
        request_id: int,
        league_type: str = 'pub_league'
    ) -> Dict[str, Any]:
        """
        Get availability status for all contacted subs for a request.

        Args:
            request_id: SubstituteRequest ID
            league_type: Type of league

        Returns:
            Dict with availability summary and individual responses
        """
        from app.models.substitutes import SubstituteRequest, SubstituteResponse

        results = {
            'request_id': request_id,
            'total_contacted': 0,
            'responded': 0,
            'available': 0,
            'not_available': 0,
            'pending': 0,
            'responses': []
        }

        try:
            responses = db.session.query(SubstituteResponse).filter_by(
                request_id=request_id
            ).all()

            results['total_contacted'] = len(responses)

            for response in responses:
                player = response.player

                response_data = {
                    'player_id': player.id,
                    'player_name': player.name,
                    'notification_methods': response.notification_methods,
                    'notified_at': response.notification_sent_at.isoformat() if response.notification_sent_at else None,
                    'status': 'pending',
                    'response_text': response.response_text,
                    'responded_at': response.responded_at.isoformat() if response.responded_at else None
                }

                if response.responded_at is not None:
                    results['responded'] += 1
                    if response.is_available:
                        response_data['status'] = 'available'
                        results['available'] += 1
                    else:
                        response_data['status'] = 'not_available'
                        results['not_available'] += 1
                else:
                    results['pending'] += 1

                results['responses'].append(response_data)

            # Sort: available first, then pending, then not available
            status_order = {'available': 0, 'pending': 1, 'not_available': 2}
            results['responses'].sort(key=lambda x: status_order.get(x['status'], 3))

        except Exception as e:
            logger.error(f"Error getting availability status: {e}")

        return results


# Singleton instance
_rsvp_service = None


def get_rsvp_service() -> SubstituteRSVPService:
    """Get the singleton RSVP service instance."""
    global _rsvp_service
    if _rsvp_service is None:
        _rsvp_service = SubstituteRSVPService()
    return _rsvp_service
