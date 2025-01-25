from flask import current_app, flash, request, jsonify, redirect, url_for, g
from app.models import User, Role
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from app.utils.user_helpers import safe_current_user
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task
from app.db_utils import mark_player_for_discord_update
import logging

logger = logging.getLogger(__name__)

def handle_coach_status_update(player, user):
    try:
        logger.debug("Entering handle_coach_status_update")
        is_coach = 'is_coach' in request.form
        logger.debug(f"Received is_coach: {is_coach}")
        
        player.is_coach = is_coach
        player.discord_needs_update = True
        session = g.db_session

        # Force immediate Discord role update
        if player.discord_id:
            logger.debug(f"Queueing Discord role update for player {player.id}")
            discord_task = assign_roles_to_player_task.delay(player_id=player.id)
            if discord_task:
                logger.info(f"Discord role update task queued for player {player.id}")
            else:
                logger.error(f"Failed to queue Discord role update for player {player.id}")

        session.commit()
        logger.info(f"{player.name}'s coach status updated successfully to {is_coach}")
        flash(f"{player.name}'s coach status updated successfully.", 'success')
        return redirect(url_for('players.player_profile', player_id=player.id))
        
    except Exception as e:
        logger.error(f"Error updating coach status: {str(e)}", exc_info=True)
        flash('Error updating coach status.', 'danger')
        raise

def handle_ref_status_update(player, user):
    try:
        logger.debug("Entering handle_ref_status_update")
        is_ref = 'is_ref' in request.form
        logger.debug(f"Received is_ref: {is_ref}")
        
        player.is_ref = is_ref
        player.discord_needs_update = True
        session = g.db_session

        if player.discord_id:
            discord_task = assign_roles_to_player_task.delay(player_id=player.id)
            if discord_task:
                logger.info(f"Discord role update task queued for player {player.id}")
            else:
                logger.error(f"Failed to queue Discord role update for player {player.id}")

        session.commit()
        
        logger.info(f"{player.name}'s referee status updated successfully.")
        flash(f"{player.name}'s referee status updated successfully.", 'success')
        return redirect(url_for('players.player_profile', player_id=player.id))
        
    except Exception as e:
        logger.error(f"Error updating referee status: {str(e)}", exc_info=True)
        flash('Error updating referee status.', 'danger')
        raise

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

def check_email_uniqueness(email, user_id):
    """Check if email is unique among users, excluding current user"""
    session = g.db_session
    try:
        logger.debug(f"Checking uniqueness for email: {email} and user_id: {user_id}")
        existing_user = session.query(User).filter(User.email == email, User.id != user_id).first()
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

        player.update_season_stats(season_id, stats_changes, user_id=safe_current_user.id)
        logger.info(f"Season stats updated successfully for player {player.id} in season {season_id}")
        flash('Season stats updated successfully.', 'success')
        return redirect(url_for('players.player_profile', player_id=player.id))

    except Exception as e:
        logger.error(f"Error updating season stats: {str(e)}", exc_info=True)
        flash('Error updating season stats.', 'danger')
        raise

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

        player.add_stat_manually(new_stat_data, user_id=safe_current_user.id)
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
