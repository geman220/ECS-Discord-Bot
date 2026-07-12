"""
Unified Substitute Pool System Tasks

This module contains Celery tasks for the unified substitute pool system
that supports ECS FC, Classic, and Premier divisions.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import joinedload

from app.decorators import celery_task
from app.models import User, Player, Team
from app.models_substitute_pools import (
    SubstitutePool, SubstituteRequest, SubstituteResponse, SubstituteAssignment,
    get_active_substitutes, log_pool_action
)

logger = logging.getLogger(__name__)


@celery_task(name='notify_substitute_pool_of_request')
def notify_substitute_pool_of_request(self, session, request_id: int, league_type: str) -> Dict[str, Any]:
    """
    Send notifications to all active substitutes in the pool about a new request.

    Delegates to SubstituteNotificationService for unified channel delivery
    (SMS, Discord, Email, Push). Pre-resolves the eligible player_ids using
    pronoun-inclusion semantics: when a gender filter is set, also include
    players whose pronouns are 'they/them' or unset so they aren't left out.

    Args:
        request_id: ID of the SubstituteRequest
        league_type: Type of league ('ECS FC', 'Classic', 'Premier')

    Returns:
        Dictionary with notification results
    """
    try:
        sub_request = session.query(SubstituteRequest).options(
            joinedload(SubstituteRequest.team)
        ).get(request_id)
        if not sub_request:
            logger.error(f"Substitute request {request_id} not found")
            return {'success': False, 'error': 'Request not found'}

        gender_filter = getattr(sub_request, 'gender_preference', None)
        eligible_player_ids = _resolve_eligible_player_ids(session, league_type, gender_filter)

        if not eligible_player_ids:
            note = f" (filtered for {gender_filter} players)" if gender_filter else ""
            logger.warning(f"No active substitutes in the {league_type} pool{note}")
            return {
                'success': True,
                'notified': 0,
                'message': f'No active substitutes in {league_type} pool{note}',
            }

        custom_message = _build_default_pool_message(sub_request, league_type, gender_filter)

        from app.services.substitute_notification_service import SubstituteNotificationService
        service = SubstituteNotificationService()
        result = service.notify_pool(
            request_id=request_id,
            league_type=league_type,
            custom_message=custom_message,
            player_ids=eligible_player_ids,
            subs_needed=sub_request.substitutes_needed or 1,
        )

        notified = result.get('notifications_sent', 0)
        result['message'] = (
            f"Notified {notified} substitutes out of "
            f"{result.get('total_subs', 0)} in the {league_type} pool"
        )
        logger.info(f"Substitute request {request_id} notification results: {result}")
        return result

    except Exception as e:
        logger.error(f"Error in notify_substitute_pool_of_request: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def _resolve_eligible_player_ids(session, league_type: str, gender_filter: Optional[str]) -> List[int]:
    """Pick eligible substitute player_ids. When a gender filter is set,
    also include players whose pronouns are 'they/them' or unset so broader
    sub broadcasts don't exclude them."""
    if not gender_filter:
        return [s.player_id for s in get_active_substitutes(league_type, session, None) if s.player_id]

    gender_specific = get_active_substitutes(league_type, session, gender_filter)
    all_subs = get_active_substitutes(league_type, session, None)

    inclusive = []
    for sub in all_subs:
        if not sub.player:
            continue
        prons = (sub.player.pronouns or '').lower().strip()
        if 'they/them' in prons or not prons:
            inclusive.append(sub)

    seen = set()
    out = []
    for sub in list(gender_specific) + inclusive:
        pid = sub.player_id
        if pid and pid not in seen:
            out.append(pid)
            seen.add(pid)
    return out


def _build_default_pool_message(sub_request: SubstituteRequest, league_type: str, gender_filter: Optional[str]) -> str:
    """Headline for the default pool broadcast. SubstituteNotificationService
    appends match details (date / time / location / positions / notes) under it."""
    team_name = sub_request.team.name if sub_request.team else 'a team'
    parts = [f"{league_type} Sub Request: {team_name} needs a sub"]
    if gender_filter:
        parts.append(f"(seeking {gender_filter} player)")
    return ' '.join(parts) + '.'


# NAME MUST BE FULLY QUALIFIED.
# This task and app/tasks/tasks_ecs_fc_subs.py BOTH declared name='notify_assigned_substitute'.
# Celery's task registry is a dict keyed by NAME, so whichever module conf.imports loaded
# SECOND silently overwrote the first — and tasks_ecs_fc_subs is listed after
# tasks_substitute_pools (celery_config.py:61 vs :63), so the ECS FC implementation won.
# .delay() dispatches BY NAME, so even the routes that explicitly imported the Pub League
# symbol were enqueuing the ECS FC task — which then looked up an EcsFcSubAssignment using a
# PUB LEAGUE assignment id. Those are independent id sequences: either no row was found (the
# substitute was never notified at all) or a colliding row WAS found and the WRONG PLAYER was
# notified about the WRONG MATCH.
@celery_task(name='app.tasks.tasks_substitute_pools.notify_assigned_substitute')
def notify_assigned_substitute(self, session, assignment_id: int) -> Dict[str, Any]:
    """
    Send notification to the assigned substitute with match details.
    
    Args:
        assignment_id: ID of the SubstituteAssignment
        
    Returns:
        Dictionary with notification results
    """
    try:
        assignment = session.query(SubstituteAssignment).options(
            joinedload(SubstituteAssignment.player)
        ).get(assignment_id)
        if not assignment:
            logger.error(f"Assignment {assignment_id} not found")
            return {'success': False, 'error': 'Assignment not found'}

        # Bump the pool member's matches_played counter; the unified service
        # owns sending the notification itself.
        pool_entry = session.query(SubstitutePool).filter_by(
            player_id=assignment.player_id,
            league_type=assignment.request.league_type,
            is_active=True,
        ).first()
        if pool_entry:
            pool_entry.matches_played = (pool_entry.matches_played or 0) + 1

        from app.services.substitute_notification_service import SubstituteNotificationService
        service = SubstituteNotificationService()
        result = service.send_confirmation(assignment_id=assignment_id, league_type='pub_league')

        player_name = assignment.player.name if assignment.player else 'unknown'
        channels = result.get('channels_used', [])
        result['player_name'] = player_name
        result['message'] = (
            f"Notified {player_name} via {', '.join(channels)}"
            if channels else f"Failed to notify {player_name}"
        )
        logger.info(f"Assignment {assignment_id} notification results: {result}")
        return result

    except Exception as e:
        logger.error(f"Error in notify_assigned_substitute: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


@celery_task(name='process_substitute_response')
def process_substitute_response(self, session, player_id: int, response_text: str, response_method: str) -> Dict[str, Any]:
    """
    Process a substitute's response to a request that arrived via SMS or Discord.

    Records the availability on the SubstituteResponse row, bumps the pool's
    accepted-counter when applicable, and delegates the admin-facing FCM push
    to SubstituteNotificationService.notify_response_received so the same
    payload contract holds across all entry points (SMS, Discord, web, app).

    Args:
        player_id: ID of the player responding
        response_text: The response text (e.g., "YES", "NO")
        response_method: How they responded (SMS, DISCORD)

    Returns:
        Dictionary with processing results
    """
    try:
        response_text = response_text.strip().upper()
        is_available = response_text in ['YES', 'Y', 'AVAILABLE', '1']

        response = session.query(SubstituteResponse).join(
            SubstituteRequest
        ).filter(
            SubstituteResponse.player_id == player_id,
            SubstituteRequest.status == 'OPEN'
        ).order_by(
            SubstituteResponse.notification_sent_at.desc()
        ).first()

        if not response:
            logger.warning(f"No open sub request found for player {player_id}")
            return {'success': False, 'error': 'No active substitute request found'}

        response.is_available = is_available
        response.response_method = response_method
        response.response_text = response_text
        response.responded_at = datetime.utcnow()

        pool_entry = session.query(SubstitutePool).filter_by(
            player_id=player_id,
            league_type=response.request.league_type,
            is_active=True
        ).first()
        if pool_entry and is_available:
            pool_entry.requests_accepted = (pool_entry.requests_accepted or 0) + 1

        try:
            from app.services.substitute_notification_service import SubstituteNotificationService
            SubstituteNotificationService().notify_response_received(
                request_id=response.request_id,
                player_id=player_id,
                is_available=is_available,
                response_method=response_method,
                league_type='pub_league',
            )
        except Exception as e:
            logger.error(f"Failed to notify admins of sub response: {e}")

        return {
            'success': True,
            'is_available': is_available,
            'request_id': response.request_id,
            'message': f"Response recorded: {'Available' if is_available else 'Not available'}"
        }

    except Exception as e:
        logger.error(f"Error processing substitute response: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_match_info_for_league(sub_request: SubstituteRequest, league_type: str) -> Optional[Dict[str, Any]]:
    """
    Get match information for a substitute request based on league type.
    
    Args:
        sub_request: The substitute request
        league_type: The league type ('ECS FC', 'Classic', 'Premier')
        
    Returns:
        Dictionary with match information or None if not found
    """
    try:
        if league_type == 'ECS FC':
            # For ECS FC, get match from ECS FC tables
            from app.models_ecs import EcsFcMatch
            match = session.query(EcsFcMatch).get(sub_request.match_id)
            if match:
                return {
                    'date': match.match_date,
                    'time': match.match_time,
                    'location': match.location,
                    'notes': match.notes
                }
        else:
            # For Pub League (Classic/Premier), get match from regular Match table
            from app.models import Match
            match = session.query(Match).get(sub_request.match_id)
            if match:
                return {
                    'date': match.date,
                    'time': match.time,
                    'location': match.location,
                    'notes': match.notes
                }
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting match info for league {league_type}: {e}")
        return None