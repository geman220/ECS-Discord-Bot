"""
Unified Substitute Pool Management Routes

This module handles all routes for managing substitute pools across
ECS FC, Classic, and Premier divisions.
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, g
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_, func

from app import csrf
from app.core import db
from app.decorators import role_required
from app.alert_helpers import show_success, show_error, show_info
from app.models import User, Player, Role, Team, League, Season
from app.models_substitute_pools import (
    SubstitutePool, SubstitutePoolHistory, SubstituteRequest, 
    SubstituteResponse, SubstituteAssignment,
    get_eligible_players, get_active_substitutes, log_pool_action
)
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

# Create blueprint
substitute_pool_bp = Blueprint('substitute_pool', __name__)

# Exempt from CSRF protection (needed for Discord bot API calls)
csrf.exempt(substitute_pool_bp)

# League type configuration
LEAGUE_TYPES = {
    'ECS FC': {
        'name': 'ECS FC',
        'role': 'ECS FC Sub',
        'color': '#3498db',
        'icon': 'fas fa-futbol'
    },
    'Classic': {
        'name': 'Classic Division',
        'role': 'Classic Sub',
        'color': '#2ecc71',
        'icon': 'fas fa-trophy'
    },
    'Premier': {
        'name': 'Premier Division',
        'role': 'Premier Sub',
        'color': '#e74c3c',
        'icon': 'fas fa-crown'
    }
}


@substitute_pool_bp.route('/admin/substitute-pools')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def manage_substitute_pools():
    """
    Main substitute pool management page.
    Shows all league types and their respective pools.
    """
    try:
        session = g.db_session
        
        # Get data for all league types
        pools_data = {}
        for league_type, config in LEAGUE_TYPES.items():
            # Get active pools by league_type directly
            active_pools = session.query(SubstitutePool).options(
                joinedload(SubstitutePool.player).joinedload(Player.user)
            ).filter(
                SubstitutePool.league_type == league_type,
                SubstitutePool.is_active == True
            ).all()
            
            # Get eligible players not in pool
            eligible_players = get_eligible_players(league_type, session)
            active_pool_player_ids = {pool.player_id for pool in active_pools}
            
            # Filter out players already in pool
            available_players = [
                p for p in eligible_players 
                if p.id not in active_pool_player_ids
            ]
            
            pools_data[league_type] = {
                'config': config,
                'active_pools': active_pools,
                'available_players': available_players,
                'total_eligible': len(eligible_players),
                'total_active': len(active_pools)
            }
        
        return render_template('admin/substitute_pools.html',
                             pools_data=pools_data,
                             league_types=LEAGUE_TYPES)
        
    except Exception as e:
        logger.error(f"Error loading substitute pools: {e}", exc_info=True)
        show_error("An error occurred while loading substitute pools")
        return redirect(url_for('admin.index'))


@substitute_pool_bp.route('/admin/substitute-pools/<league_type>')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def manage_league_pool(league_type: str):
    """
    Manage substitute pool for a specific league type.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            show_error("Invalid league type")
            return redirect(url_for('admin.substitute_pool.manage_substitute_pools'))
        
        session = g.db_session
        
        # Get active pools with full player information
        active_pools = session.query(SubstitutePool).options(
            joinedload(SubstitutePool.player).joinedload(Player.user),
            joinedload(SubstitutePool.league).joinedload(League.season)
        ).join(League, SubstitutePool.league_id == League.id
        ).join(Season, League.season_id == Season.id).filter(
            Season.league_type == league_type,
            SubstitutePool.is_active == True
        ).order_by(SubstitutePool.last_active_at.desc()).all()
        
        # Get eligible players not in pool
        eligible_players = get_eligible_players(league_type, session)
        active_pool_player_ids = {pool.player_id for pool in active_pools}
        
        available_players = [
            p for p in eligible_players 
            if p.id not in active_pool_player_ids
        ]
        
        # Get recent activity
        from app.models import League
        recent_activity = session.query(SubstitutePoolHistory).options(
            joinedload(SubstitutePoolHistory.player),
            joinedload(SubstitutePoolHistory.performer)
        ).join(
            League, SubstitutePoolHistory.league_id == League.id
        ).join(
            Season, League.season_id == Season.id
        ).filter(
            Season.league_type == league_type
        ).order_by(
            SubstitutePoolHistory.performed_at.desc()
        ).limit(10).all()
        
        # Get statistics
        stats = {
            'total_active': len(active_pools),
            'total_eligible': len(eligible_players),
            'pending_approval': len(available_players),
            'total_requests_sent': sum(pool.requests_received for pool in active_pools),
            'total_matches_played': sum(pool.matches_played for pool in active_pools)
        }
        
        return render_template('admin/league_substitute_pool.html',
                             league_type=league_type,
                             league_config=LEAGUE_TYPES[league_type],
                             active_pools=active_pools,
                             available_players=available_players,
                             recent_activity=recent_activity,
                             stats=stats)
        
    except Exception as e:
        logger.error(f"Error loading league pool for {league_type}: {e}", exc_info=True)
        show_error("An error occurred while loading the league pool")
        return redirect(url_for('admin.substitute_pool.manage_substitute_pools'))


@substitute_pool_bp.route('/admin/substitute-pools/<league_type>/add-player', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def add_player_to_pool(league_type: str):
    """
    Add a player to the substitute pool for a specific league.
    """
    try:
        logger.info(f"Adding player to {league_type} pool. Request data: {request.json}")
        
        if league_type not in LEAGUE_TYPES:
            logger.error(f"Invalid league type: {league_type}. Valid types: {list(LEAGUE_TYPES.keys())}")
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        session = g.db_session
        
        # Get form data
        player_id = request.json.get('player_id')
        if not player_id:
            logger.error("No player_id in request")
            return jsonify({'success': False, 'message': 'Player ID is required'}), 400
        
        # Verify player exists and has the appropriate role
        player = session.query(Player).options(
            joinedload(Player.user).joinedload(User.roles)
        ).get(player_id)
        
        if not player:
            logger.error(f"Player not found: {player_id}")
            return jsonify({'success': False, 'message': 'Player not found'}), 404
        
        # Check if player has the required role
        required_role = LEAGUE_TYPES[league_type]['role']
        
        if not player.user:
            logger.error(f"Player {player.name} (ID: {player_id}) has no associated user account")
            return jsonify({'success': False, 'message': 'Player has no associated user account'}), 400
            
        if not player.user.roles:
            logger.error(f"Player {player.name} (ID: {player_id}) has no roles assigned")
            return jsonify({'success': False, 'message': 'Player has no roles assigned'}), 400
            
        player_roles = [role.name for role in player.user.roles]
        logger.info(f"Player {player.name} (ID: {player_id}) has roles: {player_roles}. Required role: {required_role}")
        
        if not any(role.name == required_role for role in player.user.roles):
            logger.error(f"Player {player.name} does not have required role {required_role}")
            return jsonify({'success': False, 'message': f'Player does not have {required_role} role'}), 400
        
        # Check if already in pool for this league type
        logger.info(f"Checking for existing pool entry for player {player_id} in {league_type}")
        existing_pool = session.query(SubstitutePool).filter_by(
            player_id=player_id,
            league_type=league_type
        ).first()
        logger.info(f"Existing pool found: {existing_pool is not None}")
        
        if existing_pool:
            logger.info(f"Existing pool status - is_active: {existing_pool.is_active}, league_type: {existing_pool.league_type}")
            if existing_pool.is_active:
                logger.info(f"Player {player.name} is already in the active {league_type} pool")
                return jsonify({'success': False, 'message': 'Player is already in the active pool'}), 400
            else:
                # Reactivate
                existing_pool.is_active = True
                
                # Assign player to appropriate league if they don't have one
                if not player.league_id and not player.primary_league_id:
                    from app.models import League, Season
                    # Find a league that matches this league type
                    matching_league = session.query(League).join(Season).filter(
                        Season.league_type == league_type,
                        Season.is_current == True
                    ).first()
                    
                    if matching_league:
                        player.league_id = matching_league.id
                        player.primary_league_id = matching_league.id
                        existing_pool.league_id = matching_league.id  # Also update the pool entry
                        logger.info(f"Assigned player {player.name} to {league_type} league (ID: {matching_league.id}) during reactivation")
                        message = f"{player.name} has been reactivated in the {league_type} substitute pool and assigned to {matching_league.name} league"
                    else:
                        logger.warning(f"Could not find current league for type {league_type}")
                        message = f"{player.name} has been reactivated in the {league_type} substitute pool"
                else:
                    message = f"{player.name} has been reactivated in the {league_type} substitute pool"
                
                session.add(existing_pool)
                log_pool_action(
                    player.id, existing_pool.league_id, 'REACTIVATED',
                    f"Player reactivated in {league_type} pool", safe_current_user.id, existing_pool.id, session
                )
        else:
            # Create new pool entry
            logger.info(f"Creating new pool entry for player {player_id} in {league_type}")
            pool_entry = SubstitutePool(
                player_id=player_id,
                league_type=league_type,
                preferred_positions=request.json.get('preferred_positions', ''),
                sms_for_sub_requests=request.json.get('sms_notifications', True),
                discord_for_sub_requests=request.json.get('discord_notifications', True),
                email_for_sub_requests=request.json.get('email_notifications', True)
            )
            logger.info(f"Pool entry created successfully")
            
            pool_entry.is_active = True
            session.add(pool_entry)
            logger.info(f"Added pool entry to session, attempting flush...")
            session.flush()  # Get the ID
            logger.info(f"Pool entry flushed successfully, ID: {pool_entry.id}")
            
            # Assign player to appropriate league if they don't have one
            logger.info(f"Player league_id: {player.league_id}, primary_league_id: {player.primary_league_id}")
            if not player.league_id and not player.primary_league_id:
                logger.info(f"Player has no league assignment, attempting to find matching league for {league_type}")
                from app.models import League, Season
                # Find a league that matches this league type
                matching_league = session.query(League).join(Season).filter(
                    Season.league_type == league_type,
                    Season.is_current == True
                ).first()
                
                if matching_league:
                    logger.info(f"Found matching league: {matching_league.name} (ID: {matching_league.id})")
                    player.league_id = matching_league.id
                    player.primary_league_id = matching_league.id
                    pool_entry.league_id = matching_league.id  # Also set on the pool entry
                    logger.info(f"Assigned player {player.name} to {league_type} league (ID: {matching_league.id})")
                    message += f" and assigned to {matching_league.name} league"
                else:
                    logger.warning(f"Could not find current league for type {league_type}")
            else:
                logger.info(f"Player already has league assignment, skipping auto-assignment")
            
            log_pool_action(
                player.id, pool_entry.league_id, 'ADDED',
                f"Player added to {league_type} pool", safe_current_user.id, pool_entry.id, session
            )
            message = f"{player.name} has been added to the {league_type} substitute pool"
        
        logger.info(f"Attempting to commit transaction...")
        session.commit()
        logger.info(f"Transaction committed successfully")
        
        return jsonify({
            'success': True,
            'message': message,
            'player_data': {
                'id': player.id,
                'name': player.name,
                'discord_id': player.discord_id,
                'phone_number': player.phone,
                'email': player.user.email if player.user else None
            }
        })
        
    except Exception as e:
        logger.error(f"Error adding player to pool: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500


@substitute_pool_bp.route('/admin/substitute-pools/<league_type>/remove-player', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def remove_player_from_pool(league_type: str):
    """
    Remove a player from the substitute pool.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        session = g.db_session
        
        player_id = request.json.get('player_id')
        if not player_id:
            return jsonify({'success': False, 'message': 'Player ID is required'}), 400
        
        # Find the pool entry by league_type
        pool_entry = session.query(SubstitutePool).filter_by(
            player_id=player_id,
            league_type=league_type,
            is_active=True
        ).first()
        
        if not pool_entry:
            return jsonify({'success': False, 'message': 'Player not found in active pool'}), 404
        
        # Deactivate the pool entry
        pool_entry.is_active = False
        session.add(pool_entry)
        
        log_pool_action(
            player_id, pool_entry.league_id, 'REMOVED',
            f"Player removed from {league_type} pool", safe_current_user.id, pool_entry.id, session
        )
        
        session.commit()
        
        return jsonify({
            'success': True,
            'message': f"{pool_entry.player.name} has been removed from the {league_type} substitute pool"
        })
        
    except Exception as e:
        logger.error(f"Error removing player from pool: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@substitute_pool_bp.route('/admin/substitute-pools/<league_type>/update-preferences', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def update_pool_preferences(league_type: str):
    """
    Update a player's substitute pool preferences.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        session = g.db_session
        
        player_id = request.json.get('player_id')
        if not player_id:
            return jsonify({'success': False, 'message': 'Player ID is required'}), 400
        
        # Find the pool entry by league_type
        pool_entry = session.query(SubstitutePool).filter_by(
            player_id=player_id,
            league_type=league_type,
            is_active=True
        ).first()
        
        if not pool_entry:
            return jsonify({'success': False, 'message': 'Player not found in active pool'}), 404
        
        # Store previous status for logging
        
        # Update preferences
        pool_entry.preferred_positions = request.json.get('preferred_positions', pool_entry.preferred_positions)
        pool_entry.sms_for_sub_requests = request.json.get('sms_notifications', pool_entry.sms_for_sub_requests)
        pool_entry.discord_for_sub_requests = request.json.get('discord_notifications', pool_entry.discord_for_sub_requests)
        pool_entry.email_for_sub_requests = request.json.get('email_notifications', pool_entry.email_for_sub_requests)
        pool_entry.max_matches_per_week = request.json.get('max_matches_per_week', pool_entry.max_matches_per_week)
        pool_entry.notes = request.json.get('notes', pool_entry.notes)
        pool_entry.last_active_at = datetime.utcnow()
        
        session.add(pool_entry)
        
        log_pool_action(
            player_id, pool_entry.league_id, 'UPDATED',
            f"Preferences updated for {league_type} pool", safe_current_user.id, pool_entry.id, session
        )
        
        session.commit()
        
        return jsonify({
            'success': True,
            'message': f"Preferences updated for {pool_entry.player.name}"
        })
        
    except Exception as e:
        logger.error(f"Error updating pool preferences: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@substitute_pool_bp.route('/admin/substitute-pools/<league_type>/statistics')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def get_pool_statistics(league_type: str):
    """
    Get detailed statistics for a substitute pool.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        session = g.db_session
        
        # Get active pools with statistics
        active_pools = session.query(SubstitutePool).options(
            joinedload(SubstitutePool.player)
        ).filter(
            SubstitutePool.league_type == league_type,
            SubstitutePool.is_active == True
        ).all()
        
        # Calculate statistics
        stats = {
            'total_active': len(active_pools),
            'total_requests_sent': sum(pool.requests_received for pool in active_pools),
            'total_requests_accepted': sum(pool.requests_accepted for pool in active_pools),
            'total_matches_played': sum(pool.matches_played for pool in active_pools),
            'average_acceptance_rate': 0,
            'top_performers': [],
            'notification_preferences': {
                'sms_enabled': 0,
                'discord_enabled': 0,
                'email_enabled': 0
            }
        }
        
        if active_pools:
            # Calculate average acceptance rate
            total_acceptance = sum(pool.acceptance_rate for pool in active_pools)
            stats['average_acceptance_rate'] = total_acceptance / len(active_pools)
            
            # Get top performers
            top_performers = sorted(
                active_pools,
                key=lambda p: (p.matches_played, p.acceptance_rate),
                reverse=True
            )[:5]
            
            stats['top_performers'] = [
                {
                    'player_name': pool.player.name,
                    'matches_played': pool.matches_played,
                    'acceptance_rate': pool.acceptance_rate,
                    'requests_received': pool.requests_received
                }
                for pool in top_performers
            ]
            
            # Count notification preferences
            stats['notification_preferences'] = {
                'sms_enabled': sum(1 for pool in active_pools if pool.sms_for_sub_requests),
                'discord_enabled': sum(1 for pool in active_pools if pool.discord_for_sub_requests),
                'email_enabled': sum(1 for pool in active_pools if pool.email_for_sub_requests)
            }
        
        return jsonify({
            'success': True,
            'statistics': stats
        })
        
    except Exception as e:
        logger.error(f"Error getting pool statistics: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@substitute_pool_bp.route('/admin/substitute-pools/<league_type>/history')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def get_pool_history(league_type: str):
    """
    Get history for a substitute pool.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        session = g.db_session
        
        # Get history entries through pool relationship
        history = session.query(SubstitutePoolHistory).options(
            joinedload(SubstitutePoolHistory.player),
            joinedload(SubstitutePoolHistory.performer),
            joinedload(SubstitutePoolHistory.pool)
        ).join(
            SubstitutePool, SubstitutePoolHistory.pool_id == SubstitutePool.id
        ).filter(
            SubstitutePool.league_type == league_type
        ).order_by(
            SubstitutePoolHistory.performed_at.desc()
        ).limit(50).all()
        
        history_data = [entry.to_dict() for entry in history]
        
        return jsonify({
            'success': True,
            'history': history_data
        })
        
    except Exception as e:
        logger.error(f"Error getting pool history: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@substitute_pool_bp.route('/api/substitute-pools/player-search')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def search_players():
    """
    Search for players that can be added to substitute pools.
    """
    try:
        session = g.db_session
        
        query = request.args.get('q', '').strip()
        league_type = request.args.get('league_type', '').strip()
        
        if not query or len(query) < 2:
            return jsonify({'success': True, 'players': []})
        
        if league_type and league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        # Build base query
        base_query = session.query(Player).options(
            joinedload(Player.user).joinedload(User.roles)
        ).join(User).filter(
            or_(
                Player.name.ilike(f'%{query}%'),
                User.email.ilike(f'%{query}%'),
                User.username.ilike(f'%{query}%')
            )
        )
        
        # Filter by league type if specified
        if league_type:
            required_role = LEAGUE_TYPES[league_type]['role']
            base_query = base_query.filter(
                User.roles.any(Role.name == required_role)
            )
        
        players = base_query.limit(20).all()
        
        # Format results
        results = []
        for player in players:
            # Check which leagues they're eligible for
            eligible_leagues = []
            for lt, config in LEAGUE_TYPES.items():
                if any(role.name == config['role'] for role in player.user.roles):
                    eligible_leagues.append(lt)
            
            # Check current pool status
            current_pools = session.query(SubstitutePool).options(
                joinedload(SubstitutePool.league)
            ).filter_by(
                player_id=player.id,
                is_active=True
            ).all()
            
            current_pool_types = [pool.league.name for pool in current_pools]
            
            results.append({
                'id': player.id,
                'name': player.name,
                'email': player.user.email if player.user else None,
                'discord_id': player.discord_id,
                'phone_number': player.phone,
                'eligible_leagues': eligible_leagues,
                'current_pools': current_pool_types,
                'can_add_to': [lt for lt in eligible_leagues if lt not in current_pool_types]
            })
        
        return jsonify({
            'success': True,
            'players': results
        })
        
    except Exception as e:
        logger.error(f"Error searching players: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@substitute_pool_bp.route('/admin/substitute-pools/<league_type>/requests')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def get_substitute_requests(league_type: str):
    """
    Get recent substitute requests for a specific league type.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        session = g.db_session
        
        # Get recent substitute requests for this league
        from app.models import Match, Team, League, Season, Season
        requests = session.query(SubstituteRequest).options(
            joinedload(SubstituteRequest.team),
            joinedload(SubstituteRequest.requester),
            joinedload(SubstituteRequest.responses).joinedload(SubstituteResponse.player),
            joinedload(SubstituteRequest.assignments).joinedload(SubstituteAssignment.player)
        ).join(Match, SubstituteRequest.match_id == Match.id
        ).join(Team, SubstituteRequest.team_id == Team.id
        ).join(League, Team.league_id == League.id
        ).join(Season, League.season_id == Season.id
        ).filter(
            Season.league_type == league_type
        ).order_by(
            SubstituteRequest.created_at.desc()
        ).limit(20).all()
        
        requests_data = []
        for req in requests:
            req_dict = req.to_dict(include_responses=True)
            
            # Add response summary
            total_responses = len(req.responses)
            available_responses = len([r for r in req.responses if r.is_available])
            
            req_dict.update({
                'total_responses': total_responses,
                'available_responses': available_responses,
                'response_rate': f"{available_responses}/{total_responses}" if total_responses > 0 else "0/0"
            })
            
            requests_data.append(req_dict)
        
        return jsonify({
            'success': True,
            'requests': requests_data
        })
        
    except Exception as e:
        logger.error(f"Error getting substitute requests: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@substitute_pool_bp.route('/admin/substitute-pools/<league_type>/requests/<int:request_id>/cancel', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def cancel_substitute_request(league_type: str, request_id: int):
    """
    Cancel a substitute request.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        session = g.db_session
        
        # Find the request
        from app.models import Match, Team, League, Season
        request = session.query(SubstituteRequest).join(
            Match, SubstituteRequest.match_id == Match.id
        ).join(
            Team, SubstituteRequest.team_id == Team.id
        ).join(
            League, Team.league_id == League.id
        ).join(
            Season, League.season_id == Season.id
        ).filter(
            SubstituteRequest.id == request_id,
            Season.league_type == league_type
        ).first()
        
        if not request:
            return jsonify({'success': False, 'message': 'Request not found'}), 404
        
        if request.status != 'OPEN':
            return jsonify({'success': False, 'message': 'Can only cancel open requests'}), 400
        
        # Cancel the request
        request.status = 'CANCELLED'
        request.cancelled_at = datetime.utcnow()
        request.updated_at = datetime.utcnow()
        
        session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Substitute request for {request.team.name} has been cancelled'
        })
        
    except Exception as e:
        logger.error(f"Error cancelling substitute request: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@substitute_pool_bp.route('/admin/substitute-pools/<league_type>/requests/<int:request_id>/resend', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def resend_substitute_request(league_type: str, request_id: int):
    """
    Resend notifications for a substitute request.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        session = g.db_session
        
        # Find the request
        from app.models import Match, Team, League, Season
        request = session.query(SubstituteRequest).join(
            Match, SubstituteRequest.match_id == Match.id
        ).join(
            Team, SubstituteRequest.team_id == Team.id
        ).join(
            League, Team.league_id == League.id
        ).join(
            Season, League.season_id == Season.id
        ).filter(
            SubstituteRequest.id == request_id,
            Season.league_type == league_type
        ).first()
        
        if not request:
            return jsonify({'success': False, 'message': 'Request not found'}), 404
        
        if request.status != 'OPEN':
            return jsonify({'success': False, 'message': 'Can only resend for open requests'}), 400
        
        # Check if request was sent recently (within last 30 minutes)
        from datetime import timedelta
        if request.created_at and request.created_at > datetime.utcnow() - timedelta(minutes=30):
            time_since = datetime.utcnow() - request.created_at
            minutes_ago = int(time_since.total_seconds() / 60)
            return jsonify({
                'success': False, 
                'message': f'Request was sent only {minutes_ago} minutes ago. Please wait before resending.',
                'requires_confirmation': True,
                'time_since_last': minutes_ago
            }), 400
        
        # Import and call the notification task
        from app.tasks.tasks_substitute_pools import notify_substitute_pool_of_request
        
        # Update the timestamp to indicate resend
        request.updated_at = datetime.utcnow()
        session.commit()
        
        # Send notifications asynchronously
        try:
            task_result = notify_substitute_pool_of_request.delay(request_id, league_type)
            logger.info(f"Queued substitute notification task {task_result.id} for request {request_id}")
            
            return jsonify({
                'success': True,
                'message': f'Notifications queued for substitute request to {request.team.name}',
                'task_id': task_result.id
            })
        except Exception as task_error:
            logger.error(f"Failed to queue notification task: {task_error}")
            # Fall back to synchronous execution
            result = notify_substitute_pool_of_request(request_id, league_type)
            if result.get('success'):
                return jsonify({
                    'success': True,
                    'message': f'Notifications sent for substitute request to {request.team.name}',
                    'details': result.get('message', '')
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'Failed to send notifications: {result.get("error", "Unknown error")}'
                }), 500
        
    except Exception as e:
        logger.error(f"Error resending substitute request: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@substitute_pool_bp.route('/admin/substitute-pools/match/<match_id>/requests')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def get_match_substitute_requests(match_id: str):
    """
    Get substitute requests for a specific match.
    """
    try:
        session = g.db_session
        
        # Parse match_id to determine if it's ECS FC or regular match
        if match_id.startswith('ecs_'):
            actual_match_id = int(match_id[4:])
            is_ecs_fc = True
        else:
            actual_match_id = int(match_id)
            is_ecs_fc = False
        
        # Get requests for this specific match
        requests = session.query(SubstituteRequest).options(
            joinedload(SubstituteRequest.team),
            joinedload(SubstituteRequest.requester),
            joinedload(SubstituteRequest.responses).joinedload(SubstituteResponse.player),
            joinedload(SubstituteRequest.assignments).joinedload(SubstituteAssignment.player)
        ).filter_by(
            match_id=actual_match_id
        ).order_by(
            SubstituteRequest.created_at.desc()
        ).limit(10).all()
        
        requests_data = []
        for req in requests:
            req_dict = req.to_dict(include_responses=True)
            
            # Add response summary
            total_responses = len(req.responses)
            available_responses = len([r for r in req.responses if r.is_available])
            
            req_dict.update({
                'total_responses': total_responses,
                'available_responses': available_responses,
                'response_rate': f"{available_responses}/{total_responses}" if total_responses > 0 else "0/0"
            })
            
            requests_data.append(req_dict)
        
        return jsonify({
            'success': True,
            'requests': requests_data
        })
        
    except Exception as e:
        logger.error(f"Error getting match substitute requests: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@substitute_pool_bp.route('/api/substitute-pools/process-response', methods=['POST'])
def process_substitute_response():
    """
    Process a substitute's response to a request (called by Discord bot).
    """
    try:
        data = request.get_json()
        discord_id = data.get('discord_id')
        response_text = data.get('response_text', '').strip().upper()
        response_method = data.get('response_method', 'DISCORD')
        
        if not discord_id or not response_text:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        session = g.db_session
        
        # Find the player by Discord ID
        player = session.query(Player).filter_by(discord_id=discord_id).first()
        if not player:
            return jsonify({'success': False, 'error': 'Player not found'}), 404
        
        # Import and call the response processing task
        from app.tasks.tasks_substitute_pools import process_substitute_response
        
        # Process the response
        result = process_substitute_response(player.id, response_text, response_method)
        
        if result.get('success'):
            return jsonify({
                'success': True,
                'is_available': result.get('is_available'),
                'request_id': result.get('request_id'),
                'message': result.get('message')
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
        
    except Exception as e:
        logger.error(f"Error processing substitute response: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'An error occurred'}), 500


@substitute_pool_bp.route('/api/substitute-pools/responses/<match_type>/<match_id>')
@login_required 
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def get_substitute_responses_for_assignment(match_type: str, match_id: str):
    """
    Get substitute responses for assignment dropdown with color coding.
    
    Args:
        match_type: Either 'ecs' for ECS FC matches or 'regular' for pub league
        match_id: The match ID (without 'ecs_' prefix for ECS matches)
    """
    try:
        session = g.db_session
        
        # Determine league type and match ID
        if match_type == 'ecs':
            league_type = 'ECS FC'
            actual_match_id = int(match_id)
        else:
            # For regular matches, determine league type from team
            actual_match_id = int(match_id)
            from app.models import Match, Team
            match = session.query(Match).options(
                joinedload(Match.home_team).joinedload(Team.league),
                joinedload(Match.away_team).joinedload(Team.league)
            ).get(actual_match_id)
            if not match:
                return jsonify({'success': False, 'error': 'Match not found'}), 404
            
            # Determine league type from team (try home team first, then away team)
            league_type = 'Classic'  # Default
            for team in [match.home_team, match.away_team]:
                if team and team.league:
                    league_name = team.league.name.lower()
                    if 'premier' in league_name:
                        league_type = 'Premier'
                        break
                    elif 'classic' in league_name:
                        league_type = 'Classic'
                        break
                    elif 'ecs' in league_name:
                        league_type = 'ECS FC'
                        break
        
        # Find the most recent open request for this match
        request = session.query(SubstituteRequest).filter_by(
            match_id=actual_match_id,
            status='OPEN'
        ).first()
        
        if not request:
            # No open request found - return league-specific available subs
            from app.models_substitute_pools import get_active_substitutes
            pool_subs = get_active_substitutes(league_type, session)
            
            # Format for dropdown with gray color (no response)
            formatted_subs = []
            for pool_sub in pool_subs:
                player = pool_sub.player
                if player:
                    formatted_subs.append({
                        'id': player.id,
                        'name': player.name,
                        'response_status': 'no_response',
                        'color_class': 'text-muted',
                        'sort_order': 2  # No response gets middle priority
                    })
            
            return jsonify({
                'success': True,
                'substitutes': formatted_subs,
                'has_responses': False
            })
        
        # Get all responses for this request
        responses = session.query(SubstituteResponse).options(
            joinedload(SubstituteResponse.player).joinedload(Player.user)
        ).filter_by(request_id=request.id).all()
        
        # Also get pool members who haven't responded
        from app.models_substitute_pools import get_active_substitutes
        all_pool_subs = get_active_substitutes(league_type, session)
        
        # Create a mapping of responses
        response_map = {}
        for response in responses:
            if response.player_id:
                response_map[response.player_id] = response
        
        # Format for dropdown
        formatted_subs = []
        
        for pool_sub in all_pool_subs:
            player = pool_sub.player
            if not player:
                continue
                
            if player.id in response_map:
                response = response_map[player.id]
                if response.is_available:
                    status = 'available'
                    color_class = 'text-success fw-bold'
                    sort_order = 0  # Available gets highest priority
                else:
                    status = 'not_available' 
                    color_class = 'text-danger'
                    sort_order = 2  # Not available gets lowest priority
            else:
                status = 'no_response'
                color_class = 'text-muted'
                sort_order = 1  # No response gets middle priority
            
            formatted_subs.append({
                'id': player.id,
                'name': player.name,
                'response_status': status,
                'color_class': color_class,
                'sort_order': sort_order
            })
        
        # Sort by response status: available first, no response second, not available last
        formatted_subs.sort(key=lambda x: (x['sort_order'], x['name']))
        
        return jsonify({
            'success': True,
            'substitutes': formatted_subs,
            'has_responses': len(responses) > 0,
            'request_id': request.id
        })
        
    except Exception as e:
        logger.error(f"Error getting substitute responses for assignment: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'An error occurred'}), 500


@substitute_pool_bp.route('/api/substitute-pools/assign', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def assign_substitute_from_pool():
    """
    Assign a substitute from the pool to a specific request.
    """
    try:
        data = request.get_json() or request.form
        
        request_id = data.get('request_id')
        player_id = data.get('player_id')
        position_assigned = data.get('position_assigned', '')
        notes = data.get('notes', '')
        
        if not request_id or not player_id:
            return jsonify({'success': False, 'error': 'Missing request_id or player_id'}), 400
        
        session = g.db_session
        
        # Get the substitute request
        sub_request = session.query(SubstituteRequest).get(request_id)
        if not sub_request:
            return jsonify({'success': False, 'error': 'Substitute request not found'}), 404
        
        if sub_request.status != 'OPEN':
            return jsonify({'success': False, 'error': 'Substitute request is not open'}), 400
        
        # Get the player
        player = session.query(Player).get(player_id)
        if not player:
            return jsonify({'success': False, 'error': 'Player not found'}), 404
        
        # Check if there's already an assignment for this request
        existing_assignment = session.query(SubstituteAssignment).filter_by(
            request_id=request_id
        ).first()
        
        if existing_assignment:
            return jsonify({'success': False, 'error': 'A substitute has already been assigned to this request'}), 400
        
        # Create the assignment
        assignment = SubstituteAssignment(
            request_id=request_id,
            player_id=player_id,
            assigned_by=safe_current_user.id,
            position_assigned=position_assigned,
            notes=notes
        )
        
        session.add(assignment)
        
        # Update the request status
        sub_request.status = 'FILLED'
        sub_request.filled_at = datetime.utcnow()
        
        session.commit()
        
        # Send notification to the assigned substitute (async)
        # Use the appropriate notification task based on league type
        if sub_request.team.league.name == 'ECS FC':
            from app.tasks.tasks_ecs_fc_subs import notify_assigned_substitute as notify_ecs_fc_substitute
            notify_ecs_fc_substitute.delay(assignment.id)
        else:
            from app.tasks.tasks_substitute_pools import notify_assigned_substitute
            notify_assigned_substitute.delay(assignment.id)
        
        return jsonify({
            'success': True, 
            'message': f'Successfully assigned {player.name} as substitute',
            'assignment_id': assignment.id
        })
        
    except Exception as e:
        logger.error(f"Error assigning substitute from pool: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'An error occurred'}), 500


@substitute_pool_bp.route('/api/substitute-pools/requests/<int:request_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def delete_substitute_request(request_id: int):
    """
    Delete a cancelled substitute request to keep the list clean.
    """
    try:
        session = g.db_session
        
        # Get the request
        sub_request = session.query(SubstituteRequest).get(request_id)
        if not sub_request:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        
        # Check permissions - only allow deletion if cancelled or by admin
        is_admin = any(role.name in ['Global Admin', 'Pub League Admin'] for role in safe_current_user.roles)
        
        if not is_admin and sub_request.status != 'CANCELLED':
            return jsonify({'success': False, 'error': 'Only cancelled requests can be deleted'}), 403
        
        # Check if user is the requester or admin
        if not is_admin and sub_request.requested_by != safe_current_user.id:
            return jsonify({'success': False, 'error': 'You can only delete your own requests'}), 403
        
        # Delete related responses and assignments first
        session.query(SubstituteResponse).filter_by(request_id=request_id).delete()
        session.query(SubstituteAssignment).filter_by(request_id=request_id).delete()
        
        # Delete the request
        session.delete(sub_request)
        session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Substitute request deleted successfully'
        })
        
    except Exception as e:
        logger.error(f"Error deleting substitute request: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'error': 'An error occurred'}), 500


@substitute_pool_bp.route('/api/substitute-pools/cleanup', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def cleanup_old_substitute_requests():
    """
    Clean up old cancelled requests (admin only).
    Deletes cancelled requests older than 30 days.
    """
    try:
        session = g.db_session
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        
        # Find old cancelled requests
        old_requests = session.query(SubstituteRequest).filter(
            SubstituteRequest.status == 'CANCELLED',
            SubstituteRequest.cancelled_at < cutoff_date
        ).all()
        
        deleted_count = 0
        for request in old_requests:
            # Delete related data
            session.query(SubstituteResponse).filter_by(request_id=request.id).delete()
            session.query(SubstituteAssignment).filter_by(request_id=request.id).delete()
            session.delete(request)
            deleted_count += 1
        
        session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Cleaned up {deleted_count} old cancelled requests',
            'deleted_count': deleted_count
        })
        
    except Exception as e:
        logger.error(f"Error cleaning up old requests: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'error': 'An error occurred'}), 500


@substitute_pool_bp.route('/admin/substitute-pools/<league_type>/requests/<int:request_id>', methods=['GET'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def get_substitute_request_details(league_type: str, request_id: int):
    """
    Get detailed information about a substitute request including responses.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        session = g.db_session
        
        # Get the request with all related data
        from app.models import Match, Team, League, Season
        request = session.query(SubstituteRequest).options(
            joinedload(SubstituteRequest.team),
            joinedload(SubstituteRequest.requester),
            joinedload(SubstituteRequest.responses).joinedload(SubstituteResponse.player).joinedload(Player.user),
            joinedload(SubstituteRequest.assignments).joinedload(SubstituteAssignment.player)
        ).join(
            Match, SubstituteRequest.match_id == Match.id
        ).join(
            Team, SubstituteRequest.team_id == Team.id
        ).join(
            League, Team.league_id == League.id
        ).join(
            Season, League.season_id == Season.id
        ).filter(
            SubstituteRequest.id == request_id,
            Season.league_type == league_type
        ).first()
        
        if not request:
            return jsonify({'success': False, 'message': 'Request not found'}), 404
        
        # Format responses
        responses_data = []
        for response in request.responses:
            player = response.player
            user = player.user if player else None
            
            responses_data.append({
                'id': response.id,
                'player_id': player.id if player else None,
                'player_name': player.name if player else 'Unknown',
                'player_phone': player.phone if player else None,
                'player_email': user.email if user else None,
                'is_available': response.is_available,
                'response_method': response.response_method,
                'response_text': response.response_text,
                'responded_at': response.responded_at.isoformat() if response.responded_at else None,
                'notification_sent_at': response.notification_sent_at.isoformat() if response.notification_sent_at else None,
                'notification_methods': response.notification_methods
            })
        
        # Format assignments
        assignments_data = []
        for assignment in request.assignments:
            player = assignment.player
            
            assignments_data.append({
                'id': assignment.id,
                'player_id': player.id if player else None,
                'player_name': player.name if player else 'Unknown',
                'position_assigned': assignment.position_assigned,
                'notes': assignment.notes,
                'assigned_at': assignment.created_at.isoformat() if assignment.created_at else None,
                'assigned_by': assignment.assigned_by,
                'notification_sent': assignment.notification_sent
            })
        
        request_data = {
            'id': request.id,
            'match_id': request.match_id,
            'team_id': request.team_id,
            'team_name': request.team.name if request.team else 'Unknown Team',
            'league_type': request.team.league.name if request.team and request.team.league else 'Unknown',
            'positions_needed': request.positions_needed,
            'gender_preference': request.gender_preference,
            'notes': request.notes,
            'status': request.status,
            'created_at': request.created_at.isoformat() if request.created_at else None,
            'updated_at': request.updated_at.isoformat() if request.updated_at else None,
            'requester': request.requester.username if request.requester else None,
            'responses': responses_data,
            'assignments': assignments_data,
            'total_responses': len(responses_data),
            'available_responses': len([r for r in responses_data if r['is_available']]),
            'response_rate': f"{len([r for r in responses_data if r['is_available']])}/{len(responses_data)}" if responses_data else "0/0"
        }
        
        return jsonify({
            'success': True,
            'request': request_data
        })
        
    except Exception as e:
        logger.error(f"Error getting request details: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@substitute_pool_bp.route('/admin/substitute-pools/<league_type>/requests/<int:request_id>/assign', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def assign_substitute(league_type: str, request_id: int):
    """
    Assign a substitute to a request.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400
        
        session = g.db_session
        
        # Get form data
        player_id = request.json.get('player_id')
        position_assigned = request.json.get('position_assigned', '')
        notes = request.json.get('notes', '')
        
        if not player_id:
            return jsonify({'success': False, 'message': 'Player ID is required'}), 400
        
        # Verify the request exists and is open
        from app.models import Match, Team, League, Season
        sub_request = session.query(SubstituteRequest).join(
            Match, SubstituteRequest.match_id == Match.id
        ).join(
            Team, SubstituteRequest.team_id == Team.id
        ).join(
            League, Team.league_id == League.id
        ).join(
            Season, League.season_id == Season.id
        ).filter(
            SubstituteRequest.id == request_id,
            Season.league_type == league_type,
            SubstituteRequest.status == 'OPEN'
        ).first()
        
        if not sub_request:
            return jsonify({'success': False, 'message': 'Request not found or not open'}), 404
        
        # Verify the player exists and responded positively
        response = session.query(SubstituteResponse).filter_by(
            request_id=request_id,
            player_id=player_id,
            is_available=True
        ).first()
        
        if not response:
            return jsonify({'success': False, 'message': 'Player has not responded positively to this request'}), 400
        
        # Check if already assigned
        existing_assignment = session.query(SubstituteAssignment).filter_by(
            request_id=request_id
        ).first()
        
        if existing_assignment:
            return jsonify({'success': False, 'message': 'Substitute already assigned to this request'}), 400
        
        # Create the assignment
        assignment = SubstituteAssignment(
            request_id=request_id,
            player_id=player_id,
            assigned_by=safe_current_user.id,
            position_assigned=position_assigned,
            notes=notes
        )
        
        session.add(assignment)
        session.flush()  # Get the ID
        
        # Update request status
        sub_request.status = 'FILLED'
        sub_request.filled_at = datetime.utcnow()
        sub_request.updated_at = datetime.utcnow()
        
        # Send notification to assigned substitute
        from app.tasks.tasks_substitute_pools import notify_assigned_substitute
        try:
            notify_assigned_substitute.delay(assignment.id)
        except Exception as task_error:
            logger.warning(f"Failed to queue assignment notification: {task_error}")
            # Continue with the assignment even if notification fails
        
        session.commit()
        
        player = session.query(Player).get(player_id)
        
        return jsonify({
            'success': True,
            'message': f'{player.name if player else "Player"} has been assigned as substitute',
            'assignment_id': assignment.id
        })
        
    except Exception as e:
        logger.error(f"Error assigning substitute: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred'}), 500