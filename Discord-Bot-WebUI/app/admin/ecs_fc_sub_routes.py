"""
ECS FC Substitute System Routes

This module handles all routes related to ECS FC substitute requests,
responses, and assignments. Separate from pub league substitute system.
"""

import logging
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, g
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_

from app.core import db
from app.decorators import role_required
from app.alert_helpers import show_success, show_error, show_info
from app.utils.db_utils import transactional
from app.models import User, Player, Role
from app.models_ecs import EcsFcMatch
from app.models_ecs_subs import (
    EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment, EcsFcSubPool
)
from app.tasks.tasks_ecs_fc_subs import (
    notify_sub_pool_of_request, notify_assigned_substitute
)

logger = logging.getLogger(__name__)

# Blueprint will be registered by admin blueprint
ecs_fc_subs_bp = Blueprint('ecs_fc_subs', __name__)


@ecs_fc_subs_bp.route('/ecs-fc/sub-request/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
@transactional
def create_sub_request(match_id):
    """Create a substitute request for an ECS FC match."""
    try:
        # Get the match
        match = g.db_session.query(EcsFcMatch).get(match_id)
        if not match:
            show_error("Match not found")
            return redirect(url_for('admin.rsvp_status', match_id=f'ecs_{match_id}'))
        
        # Check if user is coach or admin for this team
        user_player = current_user.player
        if not user_player:
            show_error("You must be linked to a player to request substitutes")
            return redirect(url_for('admin.rsvp_status', match_id=f'ecs_{match_id}'))
        
        # Check permissions - must be coach of the team or admin
        is_coach = any(assignment.role == 'Coach' 
                      for assignment in user_player.team_assignments 
                      if assignment.team_id == match.team_id)
        is_admin = any(role.name in ['Global Admin', 'Pub League Admin', 'ECS FC Admin'] 
                      for role in current_user.roles)
        
        if not is_coach and not is_admin:
            show_error("You don't have permission to request substitutes for this team")
            return redirect(url_for('admin.rsvp_status', match_id=f'ecs_{match_id}'))
        
        # Check if there's already an open request
        existing_request = g.db_session.query(EcsFcSubRequest).filter_by(
            match_id=match.id,
            status='OPEN'
        ).first()
        
        if existing_request:
            show_info("There is already an open substitute request for this match")
            return redirect(url_for('admin.rsvp_status', match_id=f'ecs_{match_id}'))
        
        # Create the request
        notes = request.form.get('notes', '').strip()
        
        # Get the number of substitutes needed (default to 1 if not provided)
        try:
            substitutes_needed = int(request.form.get('substitutes_needed', 1))
            if substitutes_needed < 1:
                substitutes_needed = 1
            elif substitutes_needed > 10:  # Reasonable upper limit
                substitutes_needed = 10
        except (ValueError, TypeError):
            substitutes_needed = 1
        
        sub_request = EcsFcSubRequest(
            match_id=match.id,
            team_id=match.team_id,
            requested_by=current_user.id,
            substitutes_needed=substitutes_needed,
            notes=notes,
            status='OPEN'
        )
        
        g.db_session.add(sub_request)
        g.db_session.flush()  # Get the ID without committing (@transactional handles commit)

        # Create slots from form data
        from app.database.pool import get_db_session
        slots_created = False
        
        try:
            with get_db_session() as session:
                for i in range(1, substitutes_needed + 1):
                    position = request.form.get(f'slot_{i}_position', '')
                    gender = request.form.get(f'slot_{i}_gender', '')
                    
                    # Only create slot if it has specific requirements
                    if position or gender:
                        session.execute(
                            """INSERT INTO ecs_fc_sub_slots 
                               (request_id, slot_number, position_needed, gender_needed) 
                               VALUES (:request_id, :slot_number, :position, :gender)""",
                            {
                                'request_id': sub_request.id,
                                'slot_number': i,
                                'position': position or None,
                                'gender': gender or None
                            }
                        )
                        slots_created = True
                session.commit()
        except Exception as e:
            logger.error(f"Error creating slots: {e}")
        
        # Send notifications using the appropriate task
        if slots_created:
            # Use the new consolidated notification task
            from app.tasks.tasks_ecs_fc_subs import notify_sub_pool_with_slots
            notify_sub_pool_with_slots.delay(sub_request.id)
        else:
            # Fall back to original notification method
            notify_sub_pool_of_request.delay(sub_request.id)
        
        subs_text = "substitute" if substitutes_needed == 1 else "substitutes"
        show_success(f"Substitute request created for {substitutes_needed} {subs_text}. Notifications are being sent to available substitutes.")
        return redirect(url_for('admin.rsvp_status', match_id=f'ecs_{match_id}'))
        
    except Exception as e:
        logger.error(f"Error creating sub request: {e}", exc_info=True)
        raise  # Let @transactional handle rollback


@ecs_fc_subs_bp.route('/ecs-fc/sub-request/<int:request_id>/cancel', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
@transactional
def cancel_sub_request(request_id):
    """Cancel an open substitute request."""
    sub_request = g.db_session.query(EcsFcSubRequest).get(request_id)
    if not sub_request:
        return jsonify({'success': False, 'message': 'Request not found'}), 404

    # Check permissions
    is_requester = sub_request.requested_by == current_user.id
    is_admin = any(role.name in ['Global Admin', 'Pub League Admin', 'ECS FC Admin']
                  for role in current_user.roles)

    if not is_requester and not is_admin:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    if sub_request.status != 'OPEN':
        return jsonify({'success': False, 'message': 'Only open requests can be cancelled'}), 400

    sub_request.status = 'CANCELLED'
    sub_request.updated_at = datetime.utcnow()

    g.db_session.add(sub_request)

    return jsonify({'success': True, 'message': 'Request cancelled successfully'})


@ecs_fc_subs_bp.route('/ecs-fc/sub-request/<int:request_id>/available-subs')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def get_available_subs(request_id):
    """Get list of available substitutes for a request."""
    try:
        sub_request = g.db_session.query(EcsFcSubRequest).options(
            joinedload(EcsFcSubRequest.responses).joinedload(EcsFcSubResponse.player)
        ).get(request_id)
        
        if not sub_request:
            return jsonify({'success': False, 'message': 'Request not found'}), 404
        
        # Get available subs (those who responded positively)
        available_subs = []
        for response in sub_request.responses:
            if response.is_available and response.player:
                available_subs.append({
                    'player_id': response.player_id,
                    'name': response.player.name,
                    'response_method': response.response_method,
                    'responded_at': response.responded_at.isoformat(),
                    'response_text': response.response_text
                })
        
        return jsonify({
            'success': True,
            'available_subs': available_subs,
            'total_responses': len(sub_request.responses),
            'total_available': len(available_subs)
        })
        
    except Exception as e:
        logger.error(f"Error getting available subs: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@ecs_fc_subs_bp.route('/ecs-fc/sub-request/<int:request_id>/assign', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
@transactional
def assign_substitute(request_id):
    """Assign a substitute from the available pool."""
    sub_request = g.db_session.query(EcsFcSubRequest).options(
        joinedload(EcsFcSubRequest.match)
    ).get(request_id)

    if not sub_request:
        show_error("Request not found")
        return redirect(request.referrer or url_for('admin.index'))

    if sub_request.status != 'OPEN':
        show_error("This request has already been handled")
        return redirect(url_for('admin.rsvp_status', match_id=f'ecs_{sub_request.match_id}'))

    # Get the selected player
    player_id = request.form.get('player_id', type=int)
    if not player_id:
        show_error("No player selected")
        return redirect(url_for('admin.rsvp_status', match_id=f'ecs_{sub_request.match_id}'))

    # Verify the player is available
    response = g.db_session.query(EcsFcSubResponse).filter_by(
        request_id=request_id,
        player_id=player_id,
        is_available=True
    ).first()

    if not response:
        show_error("Selected player is not available")
        return redirect(url_for('admin.rsvp_status', match_id=f'ecs_{sub_request.match_id}'))

    # Check if we've already reached the limit
    current_assignments = len(sub_request.assignments or [])
    if current_assignments >= sub_request.substitutes_needed:
        show_error(f"Cannot assign more substitutes. Already have {current_assignments} of {sub_request.substitutes_needed} needed.")
        return redirect(url_for('admin.rsvp_status', match_id=f'ecs_{sub_request.match_id}'))

    # Check if this player is already assigned to this request
    existing_assignment = g.db_session.query(EcsFcSubAssignment).filter_by(
        request_id=request_id,
        player_id=player_id
    ).first()

    if existing_assignment:
        show_error(f"{response.player.name} is already assigned to this request")
        return redirect(url_for('admin.rsvp_status', match_id=f'ecs_{sub_request.match_id}'))

    # Create assignment
    assignment = EcsFcSubAssignment(
        request_id=request_id,
        player_id=player_id,
        assigned_by=current_user.id,
        position_assigned=request.form.get('position', ''),
        notes=request.form.get('notes', '')
    )

    g.db_session.add(assignment)

    # Update request status - only mark as FILLED if we've reached the limit
    new_assignment_count = current_assignments + 1
    if new_assignment_count >= sub_request.substitutes_needed:
        sub_request.status = 'FILLED'
        sub_request.filled_at = datetime.utcnow()
        g.db_session.add(sub_request)

    # Send notification to assigned player (after transaction commits via @transactional)
    notify_assigned_substitute.delay(assignment.id)

    # Show success message with assignment progress
    if new_assignment_count >= sub_request.substitutes_needed:
        show_success(f"Substitute assigned successfully. All {sub_request.substitutes_needed} substitutes have been assigned. Notification sent to {response.player.name}.")
    else:
        remaining = sub_request.substitutes_needed - new_assignment_count
        show_success(f"Substitute assigned successfully ({new_assignment_count} of {sub_request.substitutes_needed}). {remaining} more needed. Notification sent to {response.player.name}.")

    return redirect(url_for('admin.rsvp_status', match_id=f'ecs_{sub_request.match_id}'))


@ecs_fc_subs_bp.route('/ecs-fc/sub-pool')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def manage_sub_pool():
    """View and manage the ECS FC substitute pool."""
    try:
        # Get all players in the sub pool
        sub_pool_entries = g.db_session.query(EcsFcSubPool).options(
            joinedload(EcsFcSubPool.player)
        ).filter_by(is_active=True).all()
        
        # Get players with ECS FC Sub role but not in pool
        ecs_fc_sub_role = g.db_session.query(Role).filter_by(name='ECS FC Sub').first()
        
        eligible_players = []
        if ecs_fc_sub_role:
            # Get all players with the role
            players_with_role = g.db_session.query(Player).join(
                User, Player.user_id == User.id
            ).filter(
                User.roles.contains(ecs_fc_sub_role)
            ).all()
            
            # Find those not in the pool
            pool_player_ids = {entry.player_id for entry in sub_pool_entries}
            eligible_players = [p for p in players_with_role if p.id not in pool_player_ids]
        
        return render_template('admin/ecs_fc_sub_pool_flowbite.html',
                             sub_pool_entries=sub_pool_entries,
                             eligible_players=eligible_players)
        
    except Exception as e:
        logger.error(f"Error loading sub pool: {e}", exc_info=True)
        show_error("An error occurred while loading the substitute pool")
        return redirect(url_for('admin.index'))


@ecs_fc_subs_bp.route('/ecs-fc/sub-pool/add', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
@transactional
def add_to_sub_pool():
    """Add a player to the ECS FC substitute pool."""
    player_id = request.form.get('player_id', type=int)
    if not player_id:
        return jsonify({'success': False, 'message': 'No player specified'}), 400

    # Get the player for Discord sync
    player = g.db_session.query(Player).options(
        joinedload(Player.user).joinedload(User.roles)
    ).get(player_id)
    if not player:
        return jsonify({'success': False, 'message': 'Player not found'}), 404

    # Check if already in pool
    existing = g.db_session.query(EcsFcSubPool).filter_by(player_id=player_id).first()
    if existing:
        if existing.is_active:
            return jsonify({'success': False, 'message': 'Player already in pool'}), 400
        else:
            # Reactivate
            existing.is_active = True
            existing.last_active_at = datetime.utcnow()
            g.db_session.add(existing)
    else:
        # Build preferred positions from player profile
        positions = []
        if player.favorite_position:
            positions.append(player.favorite_position)
        if player.other_positions:
            positions.append(player.other_positions)
        preferred_positions = ', '.join(positions) if positions else ''

        # Create new entry - notification preferences default to True
        # User can manage their own notification preferences via profile settings
        pool_entry = EcsFcSubPool(
            player_id=player_id,
            preferred_positions=preferred_positions,
            sms_for_sub_requests=True,
            discord_for_sub_requests=True,
            email_for_sub_requests=True
        )
        g.db_session.add(pool_entry)

    # Add ECS FC Sub role if not already assigned
    if player.user:
        ecs_fc_sub_role = g.db_session.query(Role).filter_by(name='ECS FC Sub').first()
        if ecs_fc_sub_role and ecs_fc_sub_role not in player.user.roles:
            player.user.roles.append(ecs_fc_sub_role)
            logger.info(f"Assigned 'ECS FC Sub' Flask role to player {player.name}")

    # Trigger Discord role sync
    from app.tasks.tasks_discord import assign_roles_to_player_task
    try:
        assign_roles_to_player_task.delay(player_id=player_id, only_add=False)
        logger.info(f"Queued Discord role sync for player {player_id} after adding to ECS FC sub pool")
    except Exception as e:
        logger.error(f"Failed to queue Discord role sync: {e}")

    return jsonify({'success': True, 'message': 'Player added to substitute pool'})


@ecs_fc_subs_bp.route('/ecs-fc/sub-pool/<int:pool_id>/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
@transactional
def update_sub_pool_entry(pool_id):
    """Update a substitute pool entry."""
    pool_entry = g.db_session.query(EcsFcSubPool).get(pool_id)
    if not pool_entry:
        return jsonify({'success': False, 'message': 'Entry not found'}), 404

    # Update preferences
    pool_entry.preferred_positions = request.form.get('preferred_positions', '')
    pool_entry.sms_for_sub_requests = request.form.get('sms_notifications', 'true') == 'true'
    pool_entry.discord_for_sub_requests = request.form.get('discord_notifications', 'true') == 'true'
    pool_entry.email_for_sub_requests = request.form.get('email_notifications', 'true') == 'true'
    pool_entry.max_matches_per_week = request.form.get('max_matches_per_week', type=int)

    g.db_session.add(pool_entry)
    return jsonify({'success': True, 'message': 'Preferences updated'})


@ecs_fc_subs_bp.route('/ecs-fc/sub-pool/<int:pool_id>/remove', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
@transactional
def remove_from_sub_pool(pool_id):
    """Remove a player from the substitute pool."""
    pool_entry = g.db_session.query(EcsFcSubPool).options(
        joinedload(EcsFcSubPool.player).joinedload(Player.user).joinedload(User.roles)
    ).get(pool_id)
    if not pool_entry:
        return jsonify({'success': False, 'message': 'Entry not found'}), 404

    player_id = pool_entry.player_id
    player = pool_entry.player

    pool_entry.is_active = False
    pool_entry.last_active_at = datetime.utcnow()

    g.db_session.add(pool_entry)

    # Remove ECS FC Sub role if player has no other active ECS FC sub pool entries
    if player and player.user:
        other_active_pools = g.db_session.query(EcsFcSubPool).filter(
            EcsFcSubPool.player_id == player_id,
            EcsFcSubPool.is_active == True,
            EcsFcSubPool.id != pool_id
        ).count()

        if other_active_pools == 0:
            ecs_fc_sub_role = g.db_session.query(Role).filter_by(name='ECS FC Sub').first()
            if ecs_fc_sub_role and ecs_fc_sub_role in player.user.roles:
                player.user.roles.remove(ecs_fc_sub_role)
                logger.info(f"Removed 'ECS FC Sub' Flask role from player {player.name}")

    # Trigger Discord role sync
    from app.tasks.tasks_discord import assign_roles_to_player_task
    try:
        assign_roles_to_player_task.delay(player_id=player_id, only_add=False)
        logger.info(f"Queued Discord role sync for player {player_id} after removing from ECS FC sub pool")
    except Exception as e:
        logger.error(f"Failed to queue Discord role sync: {e}")

    return jsonify({'success': True, 'message': 'Player removed from pool'})