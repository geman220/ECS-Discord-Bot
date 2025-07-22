# app/admin/discord_routes.py

"""
Discord Role Management Routes

This module contains routes for Discord role synchronization and management.
"""

import logging
from datetime import datetime
from flask import jsonify, g, render_template, request, current_app
from flask_login import login_required
from sqlalchemy.orm import joinedload
from app.decorators import role_required
from app.models import Player, Team, User, Season, League
from app.tasks.tasks_discord import (
    update_player_discord_roles,
    fetch_role_status,
    process_discord_role_updates
)
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp


# -----------------------------------------------------------
# Discord Role Management Routes
# -----------------------------------------------------------

@admin_bp.route('/admin/check_role_status/<task_id>', endpoint='check_role_status', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def check_role_status(task_id):
    """
    Check the status of a Discord role update task.
    """
    try:
        task = fetch_role_status.AsyncResult(task_id)
        if task.ready():
            if task.successful():
                task_result = task.get()  # Expected format: {'success':True,'results':[...],'message':...}
                return jsonify({
                    'state': 'COMPLETE',
                    'results': task_result['results']
                })
            else:
                return jsonify({
                    'state': 'FAILED',
                    'error': str(task.result)
                })
        return jsonify({'state': 'PENDING'})
    except Exception as e:
        logger.error(f"Error checking task status: {str(e)}")
        return jsonify({'state': 'ERROR', 'error': str(e)}), 500


@admin_bp.route('/admin/update_player_roles/<int:player_id>', endpoint='update_player_roles_route', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_player_roles_route(player_id):
    """
    Update a player's Discord roles.
    """
    try:
        # This will block until the task completes; consider async polling if needed
        task_result = update_player_discord_roles.delay(player_id).get(timeout=30)
        if task_result.get('success'):
            return jsonify({
                'success': True,
                'player_data': task_result['player_data']
            })
        else:
            return jsonify({
                'success': False,
                'error': task_result.get('message', 'Unknown error occurred')
            }), 400
    except Exception as e:
        logger.error(f"Error updating roles for player {player_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/update_discord_roles', endpoint='mass_update_discord_roles', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def mass_update_discord_roles():
    """
    Initiate a mass update for Discord roles across players.
    """
    session = g.db_session
    try:
        # Mark all players that are out of sync
        session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_roles_synced == False
        ).update({Player.discord_needs_update: True}, synchronize_session=False)

        result = process_discord_role_updates.delay()

        return jsonify({
            'success': True,
            'message': 'Mass role update initiated',
            'task_id': result.id
        })

    except Exception as e:
        logger.error(f"Error initiating mass role update: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/discord_management', endpoint='discord_management', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def discord_management():
    """
    Discord Management Dashboard - Shows players not in Discord server with contact options.
    """
    session = g.db_session
    try:
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)  # Default 20 players per page
        status_filter = request.args.get('status', 'not_in_server')  # Default to showing priority players
        
        # Ensure per_page is within reasonable bounds
        per_page = max(10, min(per_page, 100))

        # Get current seasons to filter teams
        current_seasons = session.query(Season).filter(Season.is_current == True).all()
        current_season_ids = [season.id for season in current_seasons]
        
        # Get base query for all players with Discord IDs, filtering teams to current season only
        base_query = session.query(Player).options(
            joinedload(Player.teams).joinedload(Team.league).joinedload(League.season),
            joinedload(Player.user)
        ).filter(
            Player.discord_id.isnot(None)
        )

        # Get total statistics (for the cards)
        all_players = base_query.all()
        
        # Create a dictionary to store current teams for each player
        player_current_teams = {}
        for player in all_players:
            if player.teams:
                current_season_teams = [
                    team for team in player.teams 
                    if team.league and team.league.season_id in current_season_ids
                ]
                player_current_teams[player.id] = current_season_teams
            else:
                player_current_teams[player.id] = []
        
        players_in_server = []
        players_not_in_server = []
        players_unknown_status = []

        for player in all_players:
            if player.discord_in_server is True:
                players_in_server.append(player)
            elif player.discord_in_server is False:
                players_not_in_server.append(player)
            else:
                players_unknown_status.append(player)

        stats = {
            'total_players': len(all_players),
            'in_server': len(players_in_server),
            'not_in_server': len(players_not_in_server),
            'unknown_status': len(players_unknown_status)
        }

        # Create filtered query based on status filter
        if status_filter == 'not_in_server':
            filtered_query = base_query.filter(Player.discord_in_server == False)
            current_section = 'Players Not In Discord Server'
        elif status_filter == 'unknown':
            filtered_query = base_query.filter(Player.discord_in_server.is_(None))
            current_section = 'Players with Unknown Discord Status'
        elif status_filter == 'in_server':
            filtered_query = base_query.filter(Player.discord_in_server == True)
            current_section = 'Players In Discord Server'
        else:
            # All players
            filtered_query = base_query
            current_section = 'All Players with Discord'

        # Order by last checked (unchecked first, then oldest first)
        filtered_query = filtered_query.order_by(
            Player.discord_last_checked.nulls_first(),
            Player.discord_last_checked.asc()
        )

        # Apply pagination
        from flask import Flask
        if hasattr(Flask, 'extensions') and 'sqlalchemy' in getattr(Flask, 'extensions', {}):
            # Use Flask-SQLAlchemy pagination if available
            try:
                paginated_result = filtered_query.paginate(
                    page=page, per_page=per_page, error_out=False
                )
                players = paginated_result.items
                        
                pagination = {
                    'has_prev': paginated_result.has_prev,
                    'prev_num': paginated_result.prev_num,
                    'page': paginated_result.page,
                    'has_next': paginated_result.has_next,
                    'next_num': paginated_result.next_num,
                    'pages': paginated_result.pages,
                    'total': paginated_result.total,
                    'per_page': per_page
                }
            except:
                # Fallback to manual pagination
                total = filtered_query.count()
                players = filtered_query.offset((page - 1) * per_page).limit(per_page).all()
                        
                pages = (total + per_page - 1) // per_page
                pagination = {
                    'has_prev': page > 1,
                    'prev_num': page - 1 if page > 1 else None,
                    'page': page,
                    'has_next': page < pages,
                    'next_num': page + 1 if page < pages else None,
                    'pages': pages,
                    'total': total,
                    'per_page': per_page
                }
        else:
            # Manual pagination
            total = filtered_query.count()
            players = filtered_query.offset((page - 1) * per_page).limit(per_page).all()
                    
            pages = (total + per_page - 1) // per_page
            pagination = {
                'has_prev': page > 1,
                'prev_num': page - 1 if page > 1 else None,
                'page': page,
                'has_next': page < pages,
                'next_num': page + 1 if page < pages else None,
                'pages': pages,
                'total': total,
                'per_page': per_page
            }

        return render_template('admin/discord_management.html',
                               stats=stats,
                               players=players,
                               pagination=pagination,
                               status_filter=status_filter,
                               current_section=current_section,
                               per_page=per_page,
                               player_current_teams=player_current_teams)

    except Exception as e:
        logger.error(f"Error loading Discord management page: {str(e)}")
        return render_template('admin/discord_management.html',
                               stats={'total_players': 0, 'in_server': 0, 'not_in_server': 0, 'unknown_status': 0},
                               players=[],
                               pagination={'has_prev': False, 'prev_num': None, 'page': 1, 'has_next': False, 'next_num': None, 'pages': 1, 'total': 0, 'per_page': 20},
                               status_filter='not_in_server',
                               current_section='Players Not In Discord Server',
                               per_page=20,
                               player_current_teams={},
                               error=str(e))


@admin_bp.route('/admin/refresh_all_discord_status', endpoint='refresh_all_discord_status', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def refresh_all_discord_status():
    """
    Refresh Discord status for all players with Discord IDs.
    """
    session = g.db_session
    try:
        # Get all players with Discord IDs
        players_with_discord = session.query(Player).filter(
            Player.discord_id.isnot(None)
        ).all()

        success_count = 0
        error_count = 0
        batch_size = 10  # Process in smaller batches to avoid timeout
        
        for i in range(0, len(players_with_discord), batch_size):
            batch = players_with_discord[i:i + batch_size]
            batch_updates = []
            
            # Process batch of players
            for player in batch:
                try:
                    if player.check_discord_status():
                        success_count += 1
                        batch_updates.append(player)
                    else:
                        error_count += 1
                except Exception as e:
                    logger.error(f"Error refreshing Discord status for player {player.id}: {e}")
                    error_count += 1
            
            # Commit this batch
            if batch_updates:
                for player in batch_updates:
                    session.add(player)
                try:
                    session.commit()
                    logger.info(f"Committed batch {i//batch_size + 1}: {len(batch_updates)} players updated")
                except Exception as e:
                    logger.error(f"Error committing batch {i//batch_size + 1}: {e}")
                    session.rollback()
                    # Continue with next batch even if this one fails

        return jsonify({
            'success': True,
            'message': f'Refreshed Discord status for {success_count} players',
            'success_count': success_count,
            'error_count': error_count,
            'total_processed': len(players_with_discord)
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error in refresh_all_discord_status: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/refresh_unknown_discord_status', endpoint='refresh_unknown_discord_status', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def refresh_unknown_discord_status():
    """
    Refresh Discord status for players with unknown status only.
    """
    session = g.db_session
    try:
        # Get players with unknown Discord status (discord_in_server is None)
        players_unknown_status = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.discord_in_server.is_(None)
        ).all()

        success_count = 0
        error_count = 0
        batch_size = 10  # Process in smaller batches to avoid timeout
        
        for i in range(0, len(players_unknown_status), batch_size):
            batch = players_unknown_status[i:i + batch_size]
            batch_updates = []
            
            # Process batch of players
            for player in batch:
                try:
                    if player.check_discord_status():
                        success_count += 1
                        batch_updates.append(player)
                    else:
                        error_count += 1
                except Exception as e:
                    logger.error(f"Error refreshing Discord status for player {player.id}: {e}")
                    error_count += 1
            
            # Commit this batch
            if batch_updates:
                for player in batch_updates:
                    session.add(player)
                try:
                    session.commit()
                    logger.info(f"Committed batch {i//batch_size + 1}: {len(batch_updates)} players updated")
                except Exception as e:
                    logger.error(f"Error committing batch {i//batch_size + 1}: {e}")
                    session.rollback()
                    # Continue with next batch even if this one fails

        return jsonify({
            'success': True,
            'message': f'Checked Discord status for {success_count} players with unknown status',
            'success_count': success_count,
            'error_count': error_count,
            'total_processed': len(players_unknown_status)
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error in refresh_unknown_discord_status: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500