# app/admin_panel/routes/match_operations/substitute_pools.py

"""
Substitute Pool Management Routes

Routes for substitute pool management:
- Substitute pools overview
- League-specific pool management
- Add/remove players from pools
- Pool statistics
"""

import logging

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

logger = logging.getLogger(__name__)


# League type configuration for substitute pools
LEAGUE_TYPES = {
    'ECS FC': {
        'name': 'ECS FC',
        'role': 'ECS FC Sub',
        'color': '#3498db',
        'icon': 'ti ti-ball-football'
    },
    'Classic': {
        'name': 'Classic Division',
        'role': 'Classic Sub',
        'color': '#2ecc71',
        'icon': 'ti ti-trophy'
    },
    'Premier': {
        'name': 'Premier Division',
        'role': 'Premier Sub',
        'color': '#e74c3c',
        'icon': 'ti ti-crown'
    }
}


@admin_panel_bp.route('/substitute-pools')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def substitute_pools():
    """
    Main substitute pool management page.
    Shows all league types and their respective pools.
    """
    try:
        from app.models import Player, User, Role, Team, League, Season
        from app.models_substitute_pools import SubstitutePool, get_eligible_players

        # Log access
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_substitute_pools',
            resource_type='match_operations',
            resource_id='substitute_pools',
            new_value='Accessed substitute pools dashboard',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Get data for all league types
        pools_data = {}
        for league_type, config in LEAGUE_TYPES.items():
            try:
                # Get active pools by league_type directly
                active_pools = SubstitutePool.query.options(
                    joinedload(SubstitutePool.player).joinedload(Player.user)
                ).filter(
                    SubstitutePool.league_type == league_type,
                    SubstitutePool.is_active == True
                ).all()

                pools_data[league_type] = {
                    'config': config,
                    'active_pools': active_pools,
                    'total_active': len(active_pools)
                }
            except Exception as pool_error:
                logger.warning(f"Error loading pool data for {league_type}: {pool_error}")
                pools_data[league_type] = {
                    'config': config,
                    'active_pools': [],
                    'total_active': 0
                }

        return render_template(
            'admin_panel/match_operations/substitute_pools.html',
            pools_data=pools_data,
            league_types=LEAGUE_TYPES
        )

    except ImportError as ie:
        logger.error(f"Missing substitute pool models: {ie}")
        flash('Substitute pool models not configured. Contact an administrator.', 'error')
        return redirect(url_for('admin_panel.match_operations'))
    except Exception as e:
        logger.error(f"Error loading substitute pools: {e}")
        flash('Substitute pools unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/substitute-pools/<league_type>')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def substitute_pool_detail(league_type):
    """
    Manage substitute pool for a specific league type.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            flash('Invalid league type.', 'error')
            return redirect(url_for('admin_panel.substitute_pools'))

        from app.models import Player, User, Role, Team, League, Season
        from app.models_substitute_pools import (
            SubstitutePool, SubstitutePoolHistory, SubstituteRequest,
            SubstituteResponse, SubstituteAssignment, get_eligible_players
        )

        # Get active pools with full player information
        active_pools = SubstitutePool.query.options(
            joinedload(SubstitutePool.player).joinedload(Player.user)
        ).filter(
            SubstitutePool.league_type == league_type,
            SubstitutePool.is_active == True
        ).order_by(SubstitutePool.last_active_at.desc()).all()

        # Get eligible players not in pool
        eligible_players = get_eligible_players(league_type)
        active_pool_player_ids = {pool.player_id for pool in active_pools}

        # Also get rejected/inactive players to exclude from available list
        rejected_player_ids = {
            pool.player_id for pool in SubstitutePool.query.filter(
                SubstitutePool.league_type == league_type,
                SubstitutePool.is_active == False
            ).all()
        }

        available_players = [
            p for p in eligible_players
            if p.id not in active_pool_player_ids and p.id not in rejected_player_ids
        ]

        # Get recent activity
        try:
            recent_activity = SubstitutePoolHistory.query.options(
                joinedload(SubstitutePoolHistory.player),
                joinedload(SubstitutePoolHistory.performer)
            ).join(
                SubstitutePool, SubstitutePoolHistory.pool_id == SubstitutePool.id
            ).filter(
                SubstitutePool.league_type == league_type
            ).order_by(
                SubstitutePoolHistory.performed_at.desc()
            ).limit(10).all()
        except Exception as hist_error:
            logger.warning(f"Error loading pool history: {hist_error}")
            recent_activity = []

        # Get statistics
        stats = {
            'total_active': len(active_pools),
            'total_eligible': len(eligible_players),
            'pending_approval': len(available_players),
            'total_requests_sent': sum(pool.requests_received for pool in active_pools),
            'total_matches_played': sum(pool.matches_played for pool in active_pools)
        }

        return render_template(
            'admin_panel/match_operations/substitute_pool_detail.html',
            league_type=league_type,
            league_config=LEAGUE_TYPES[league_type],
            active_pools=active_pools,
            available_players=available_players,
            recent_activity=recent_activity,
            stats=stats
        )

    except ImportError as ie:
        logger.error(f"Missing substitute pool models: {ie}")
        flash('Substitute pool models not configured. Contact an administrator.', 'error')
        return redirect(url_for('admin_panel.substitute_pools'))
    except Exception as e:
        logger.error(f"Error loading league pool for {league_type}: {e}")
        flash('League pool unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.substitute_pools'))


@admin_panel_bp.route('/substitute-pools/<league_type>/add-player', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def add_player_to_pool(league_type):
    """Add a player to the substitute pool for a specific league."""
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        from app.models import Player, User, Role, League, Season
        from app.models_substitute_pools import SubstitutePool

        # Get form data
        player_id = request.json.get('player_id')
        if not player_id:
            return jsonify({'success': False, 'message': 'Player ID is required'}), 400

        # Verify player exists
        player = Player.query.options(
            joinedload(Player.user).joinedload(User.roles)
        ).get(player_id)

        if not player:
            return jsonify({'success': False, 'message': 'Player not found'}), 404

        # Assign the required role if not already assigned
        required_role_name = LEAGUE_TYPES[league_type]['role']
        required_role = Role.query.filter_by(name=required_role_name).first()

        if player.user and required_role and required_role not in player.user.roles:
            player.user.roles.append(required_role)

        # Check if already in pool for this league type
        existing_pool = SubstitutePool.query.filter_by(
            player_id=player_id,
            league_type=league_type
        ).first()

        if existing_pool:
            if existing_pool.is_active:
                return jsonify({'success': False, 'message': 'Player is already in the active pool'}), 400
            else:
                # Reactivate
                existing_pool.is_active = True
                message = f"{player.name} has been reactivated in the {league_type} substitute pool"
        else:
            # Create new pool entry
            pool_entry = SubstitutePool(
                player_id=player_id,
                league_type=league_type,
                preferred_positions=request.json.get('preferred_positions', ''),
                sms_for_sub_requests=request.json.get('sms_notifications', True),
                discord_for_sub_requests=request.json.get('discord_notifications', True),
                email_for_sub_requests=request.json.get('email_notifications', True),
                is_active=True
            )
            db.session.add(pool_entry)
            message = f"{player.name} has been added to the {league_type} substitute pool"

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='add_to_substitute_pool',
            resource_type='substitute_pools',
            resource_id=str(player_id),
            new_value=f'Added player {player.name} to {league_type} pool',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        db.session.commit()

        # Trigger Discord role update
        try:
            from app.tasks.tasks_discord import assign_roles_to_player_task
            assign_roles_to_player_task.delay(player_id=player.id, only_add=False)
        except Exception as task_error:
            logger.warning(f"Failed to queue Discord role update: {task_error}")

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
        logger.error(f"Error adding player to pool: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500


@admin_panel_bp.route('/substitute-pools/<league_type>/remove-player', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def remove_player_from_pool(league_type):
    """Remove a player from the substitute pool."""
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        from app.models import Player, Role
        from app.models_substitute_pools import SubstitutePool

        player_id = request.json.get('player_id')
        if not player_id:
            return jsonify({'success': False, 'message': 'Player ID is required'}), 400

        # Find the pool entry
        pool_entry = SubstitutePool.query.filter_by(
            player_id=player_id,
            league_type=league_type,
            is_active=True
        ).first()

        if not pool_entry:
            return jsonify({'success': False, 'message': 'Player not found in active pool'}), 404

        # Deactivate the pool entry
        pool_entry.is_active = False

        # Remove the Flask role if player is not in any other active pools
        player = pool_entry.player
        if player and player.user:
            other_active_pools = SubstitutePool.query.filter(
                SubstitutePool.player_id == player_id,
                SubstitutePool.is_active == True,
                SubstitutePool.id != pool_entry.id
            ).count()

            if other_active_pools == 0:
                # Remove all substitute roles
                for role_name in ['ECS FC Sub', 'Classic Sub', 'Premier Sub']:
                    role = Role.query.filter_by(name=role_name).first()
                    if role and role in player.user.roles:
                        player.user.roles.remove(role)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='remove_from_substitute_pool',
            resource_type='substitute_pools',
            resource_id=str(player_id),
            new_value=f'Removed player {player.name} from {league_type} pool',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        db.session.commit()

        # Trigger Discord role update
        try:
            from app.tasks.tasks_discord import assign_roles_to_player_task
            assign_roles_to_player_task.delay(player_id=player_id, only_add=False)
        except Exception as task_error:
            logger.warning(f"Failed to queue Discord role update: {task_error}")

        return jsonify({
            'success': True,
            'message': f"{pool_entry.player.name} has been removed from the {league_type} substitute pool"
        })

    except Exception as e:
        logger.error(f"Error removing player from pool: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@admin_panel_bp.route('/substitute-pools/<league_type>/reject-player', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def reject_player_from_pool(league_type):
    """Reject a player from being added to the substitute pool.

    This prevents the player from appearing in the "Available to Add" list
    without actually adding them to the pool. The rejection is recorded in history.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        from app.models import Player
        from app.models_substitute_pools import SubstitutePool, SubstitutePoolHistory

        player_id = request.json.get('player_id')
        reason = request.json.get('reason', 'Admin rejected')

        if not player_id:
            return jsonify({'success': False, 'message': 'Player ID is required'}), 400

        # Get the player
        player = Player.query.get(player_id)
        if not player:
            return jsonify({'success': False, 'message': 'Player not found'}), 404

        # Check if already in pool (shouldn't happen but check anyway)
        existing_pool = SubstitutePool.query.filter_by(
            player_id=player_id,
            league_type=league_type,
            is_active=True
        ).first()

        if existing_pool:
            return jsonify({'success': False, 'message': 'Player is already in this pool'}), 400

        # Create a rejected pool entry (inactive with rejected status)
        rejected_entry = SubstitutePool(
            player_id=player_id,
            league_type=league_type,
            is_active=False  # Marked as rejected/inactive
        )
        db.session.add(rejected_entry)
        db.session.flush()

        # Log to history
        history = SubstitutePoolHistory(
            pool_id=rejected_entry.id,
            action='REJECTED',
            performed_by=current_user.id,
            notes=reason
        )
        db.session.add(history)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='reject_from_substitute_pool',
            resource_type='substitute_pools',
            resource_id=str(player_id),
            new_value=f'Rejected player {player.name} from {league_type} pool: {reason}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f"{player.name} has been rejected from the {league_type} substitute pool"
        })

    except Exception as e:
        logger.error(f"Error rejecting player from pool: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@admin_panel_bp.route('/substitute-pools/<league_type>/statistics')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def substitute_pool_statistics(league_type):
    """Get detailed statistics for a substitute pool."""
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        from app.models_substitute_pools import SubstitutePool

        # Get active pools with statistics
        active_pools = SubstitutePool.query.options(
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
                'sms_enabled': sum(1 for pool in active_pools if pool.sms_for_sub_requests),
                'discord_enabled': sum(1 for pool in active_pools if pool.discord_for_sub_requests),
                'email_enabled': sum(1 for pool in active_pools if pool.email_for_sub_requests)
            }
        }

        if active_pools:
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
                    'player_name': pool.player.name if pool.player else 'Unknown',
                    'matches_played': pool.matches_played,
                    'acceptance_rate': pool.acceptance_rate,
                    'requests_received': pool.requests_received
                }
                for pool in top_performers
            ]

        return jsonify({'success': True, 'statistics': stats})

    except Exception as e:
        logger.error(f"Error getting pool statistics: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@admin_panel_bp.route('/substitute-pools/player-search')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def substitute_pool_player_search():
    """Search for players that can be added to substitute pools."""
    try:
        from app.models import Player, User, Role
        from app.models_substitute_pools import SubstitutePool
        from sqlalchemy import or_

        query_str = request.args.get('q', '').strip()
        league_type = request.args.get('league_type', '').strip()

        if not query_str or len(query_str) < 2:
            return jsonify({'success': True, 'players': []})

        if league_type and league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        # Build base query
        base_query = Player.query.options(
            joinedload(Player.user).joinedload(User.roles)
        ).join(User).filter(
            or_(
                Player.name.ilike(f'%{query_str}%'),
                User.email.ilike(f'%{query_str}%'),
                User.username.ilike(f'%{query_str}%')
            )
        )

        players = base_query.limit(20).all()

        # Format results
        results = []
        for player in players:
            # Check which leagues they're eligible for
            eligible_leagues = []
            for lt, config in LEAGUE_TYPES.items():
                if player.user and any(role.name == config['role'] for role in player.user.roles):
                    eligible_leagues.append(lt)

            # Check current pool status
            current_pools = SubstitutePool.query.filter_by(
                player_id=player.id,
                is_active=True
            ).all()

            current_pool_types = [pool.league_type for pool in current_pools]

            results.append({
                'id': player.id,
                'name': player.name,
                'email': player.user.email if player.user else None,
                'discord_id': player.discord_id,
                'phone_number': player.phone,
                'eligible_leagues': eligible_leagues,
                'current_pools': current_pool_types,
                'can_add_to': [lt for lt in LEAGUE_TYPES.keys() if lt not in current_pool_types]
            })

        return jsonify({'success': True, 'players': results})

    except Exception as e:
        logger.error(f"Error searching players: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500
