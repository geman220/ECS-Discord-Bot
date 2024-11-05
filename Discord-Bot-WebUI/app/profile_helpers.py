from flask import current_app, flash, request, jsonify, redirect, url_for
from flask_login import current_user
from app.models import User, Role
from app import db
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from io import BytesIO
import os
import base64
import logging

# Get the logger for this module
logger = logging.getLogger(__name__)

from app.decorators import db_operation, query_operation  # Import your decorators

@db_operation
def handle_coach_status_update(player, user):
    """Update player's coach status and role membership"""
    try:
        logger.debug("Entering handle_coach_status_update")
        is_coach = 'is_coach' in request.form
        logger.debug(f"Received is_coach: {is_coach}")

        player.is_coach = is_coach
        
        coach_role = Role.query.filter_by(name='Pub League Coach').first()
        if not coach_role:
            logger.warning("Pub League Coach role not found in the database.")
            flash('Coach role not found.', 'warning')
            return redirect(url_for('players.player_profile', player_id=player.id))

        if is_coach and coach_role not in user.roles:
            user.roles.append(coach_role)
            logger.debug("Added Pub League Coach role to user.")
        elif not is_coach and coach_role in user.roles:
            user.roles.remove(coach_role)
            logger.debug("Removed Pub League Coach role from user.")

        logger.info(f"{player.name}'s coach status updated successfully.")
        flash(f"{player.name}'s coach status updated successfully.", 'success')
        return redirect(url_for('players.player_profile', player_id=player.id))
        
    except Exception as e:
        logger.error(f"Error updating coach status: {str(e)}", exc_info=True)
        flash('Error updating coach status.', 'danger')
        raise

@db_operation
def handle_ref_status_update(player, user):
    """Update player's referee status and role membership"""
    try:
        logger.debug("Entering handle_ref_status_update")
        is_ref = 'is_ref' in request.form
        logger.debug(f"Received is_ref: {is_ref}")

        player.is_ref = is_ref
        
        ref_role = Role.query.filter_by(name='Pub League Ref').first()
        if not ref_role:
            logger.warning("Pub League Ref role not found in the database.")
            flash('Referee role not found.', 'warning')
            return redirect(url_for('players.player_profile', player_id=player.id))

        if is_ref and ref_role not in user.roles:
            user.roles.append(ref_role)
            logger.debug("Added Pub League Ref role to user.")
        elif not is_ref and ref_role in user.roles:
            user.roles.remove(ref_role)
            logger.debug("Removed Pub League Ref role from user.")

        logger.info(f"{player.name}'s referee status updated successfully.")
        flash(f"{player.name}'s referee status updated successfully.", 'success')
        return redirect(url_for('players.player_profile', player_id=player.id))
        
    except Exception as e:
        logger.error(f"Error updating referee status: {str(e)}", exc_info=True)
        flash('Error updating referee status.', 'danger')
        raise

@db_operation
def handle_profile_update(form, player, user):
    """Update player profile and associated user information"""
    try:
        logger.debug("Entering handle_profile_update")
        
        # Check email uniqueness
        if check_email_uniqueness(form.email.data, user.id):
            logger.debug("Email not unique. Aborting update.")
            return redirect(url_for('players.player_profile', player_id=player.id))

        # Update user and player emails
        new_email = form.email.data.lower()
        logger.debug(f"Updating user.email from {user.email} to {new_email}")
        user.email = new_email
        player.email = new_email

        # Populate player fields from form
        form.populate_obj(player)

        # Handle array fields
        player.other_positions = ','.join(form.other_positions.data) if form.other_positions.data else None
        player.positions_not_to_play = ','.join(form.positions_not_to_play.data) if form.positions_not_to_play.data else None
        
        # Handle team swap if present
        if hasattr(form, 'team_swap'):
            player.team_swap = form.team_swap.data if form.team_swap.data else None
            logger.debug(f"Set player.team_swap to {player.team_swap}")

        flash('Profile updated successfully.', 'success')
        logger.info(f"Profile for player {player.id} updated successfully.")
        return redirect(url_for('players.player_profile', player_id=player.id))
        
    except Exception as e:
        logger.error(f"Error updating profile: {str(e)}", exc_info=True)
        flash('Error updating profile.', 'danger')
        raise

@query_operation
def check_email_uniqueness(email, user_id):
    """Check if email is unique among users, excluding current user"""
    try:
        logger.debug(f"Checking uniqueness for email: {email} and user_id: {user_id}")
        existing_user = User.query.filter(User.email == email, User.id != user_id).first()
        if existing_user:
            logger.warning(f"Email {email} already in use by user {existing_user.id}.")
            flash('Email is already in use by another account.', 'danger')
            return True
        logger.debug(f"Email {email} is unique.")
        return False
    except Exception as e:
        logger.error(f"Error checking email uniqueness: {str(e)}", exc_info=True)
        flash('Error checking email availability.', 'danger')
        return True

@db_operation
def handle_season_stats_update(player, form, season_id):
    """Update player's season statistics"""
    try:
        logger.debug(f"Entering handle_season_stats_update for player {player.id} and season {season_id}")
        stats_changes = {
            'goals': form.season_goals.data - player.get_season_stat(season_id, 'goals'),
            'assists': form.season_assists.data - player.get_season_stat(season_id, 'assists'),
            'yellow_cards': form.season_yellow_cards.data - player.get_season_stat(season_id, 'yellow_cards'),
            'red_cards': form.season_red_cards.data - player.get_season_stat(season_id, 'red_cards'),
        }
        
        player.update_season_stats(season_id, stats_changes, user_id=current_user.id)
        logger.info(f"Season stats updated successfully for player {player.id} in season {season_id}")
        flash('Season stats updated successfully.', 'success')
        return redirect(url_for('players.player_profile', player_id=player.id))
        
    except Exception as e:
        logger.error(f"Error updating season stats: {str(e)}", exc_info=True)
        flash('Error updating season stats.', 'danger')
        raise

@db_operation
def handle_career_stats_update(player, form):
    """Update player's career statistics"""
    try:
        logger.debug(f"Entering handle_career_stats_update for player {player.id}")
        if not player.career_stats:
            flash('No career stats found for this player.', 'danger')
            return redirect(url_for('players.player_profile', player_id=player.id))
            
        form.populate_obj(player.career_stats[0])
        logger.info(f"Career stats updated successfully for player {player.id}")
        flash('Career stats updated successfully.', 'success')
        return redirect(url_for('players.player_profile', player_id=player.id))
        
    except Exception as e:
        logger.error(f"Error updating career stats: {str(e)}", exc_info=True)
        flash('Error updating career stats.', 'danger')
        raise

@db_operation
def handle_add_stat_manually(player):
    """Add manual statistics for a player"""
    try:
        logger.debug(f"Entering handle_add_stat_manually for player {player.id}")
        
        match_id = request.form.get('match_id')
        if not match_id:
            flash('Match ID is required.', 'danger')
            return redirect(url_for('players.player_profile', player_id=player.id))
            
        new_stat_data = {
            'match_id': match_id,
            'goals': int(request.form.get('goals', 0)),
            'assists': int(request.form.get('assists', 0)),
            'yellow_cards': int(request.form.get('yellow_cards', 0)),
            'red_cards': int(request.form.get('red_cards', 0)),
        }
        
        player.add_stat_manually(new_stat_data, user_id=current_user.id)
        logger.info(f"Stat added successfully for player {player.id} in match {match_id}")
        flash('Stat added successfully.', 'success')
        return redirect(url_for('players.player_profile', player_id=player.id))
        
    except ValueError as e:
        logger.error(f"Invalid input for stats: {str(e)}", exc_info=True)
        flash('Invalid input for stats. Please enter valid numbers.', 'danger')
        raise
    except Exception as e:
        logger.error(f"Error adding stats: {str(e)}", exc_info=True)
        flash('Error adding stats.', 'danger')
        raise