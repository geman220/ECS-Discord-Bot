from flask import current_app, flash, request, jsonify
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
    logger.debug("Entering handle_coach_status_update")
    is_coach = 'is_coach' in request.form
    logger.debug(f"Received is_coach: {is_coach}")

    player.is_coach = is_coach
    logger.debug(f"Set player.is_coach to {player.is_coach}")

    coach_role = Role.query.filter_by(name='Pub League Coach').first()
    if not coach_role:
        logger.warning("Pub League Coach role not found in the database.")
        flash('Coach role not found.', 'warning')
        return

    logger.debug(f"Fetched coach_role: {coach_role}")

    if is_coach and coach_role not in user.roles:
        user.roles.append(coach_role)
        logger.debug("Added Pub League Coach role to user.")
    elif not is_coach and coach_role in user.roles:
        user.roles.remove(coach_role)
        logger.debug("Removed Pub League Coach role from user.")

    # No need to call db.session.commit(); handled by decorator
    logger.info(f"{player.name}'s coach status updated successfully.")
    flash(f"{player.name}'s coach status updated successfully.", 'success')

@db_operation
def handle_ref_status_update(player, user):
    logger.debug("Entering handle_ref_status_update")
    is_ref = 'is_ref' in request.form
    logger.debug(f"Received is_ref: {is_ref}")

    player.is_ref = is_ref
    logger.debug(f"Set player.is_ref to {player.is_ref}")

    ref_role = Role.query.filter_by(name='Pub League Ref').first()
    if not ref_role:
        logger.warning("Pub League Ref role not found in the database.")
        flash('Referee role not found.', 'warning')
        return

    logger.debug(f"Fetched ref_role: {ref_role}")

    if is_ref and ref_role not in user.roles:
        user.roles.append(ref_role)
        logger.debug("Added Pub League Ref role to user.")
    elif not is_ref and ref_role in user.roles:
        user.roles.remove(ref_role)
        logger.debug("Removed Pub League Ref role from user.")

    # No need to call db.session.commit(); handled by decorator
    logger.info(f"{player.name}'s referee status updated successfully.")
    flash(f"{player.name}'s referee status updated successfully.", 'success')

@db_operation
def handle_profile_update(form, player, user):
    logger.debug("Entering handle_profile_update")
    # Checking email uniqueness
    if check_email_uniqueness(form.email.data, user.id):
        logger.debug("Email not unique. Aborting update.")
        return False

    # Update user and player emails
    new_email = form.email.data.lower()
    logger.debug(f"Updating user.email from {user.email} to {new_email}")
    user.email = new_email
    player.email = new_email
    logger.debug(f"Updated player.email to {player.email}")

    # Populate player fields from form
    form.populate_obj(player)
    logger.debug(f"After populate_obj, player data: {player}")

    # Manually handle specific fields
    other_positions = ','.join(form.other_positions.data) if form.other_positions.data else None
    positions_not_to_play = ','.join(form.positions_not_to_play.data) if form.positions_not_to_play.data else None
    logger.debug(f"Setting other_positions to {other_positions} and positions_not_to_play to {positions_not_to_play}")

    player.other_positions = other_positions
    player.positions_not_to_play = positions_not_to_play

    if hasattr(form, 'team_swap'):
        team_swap_value = form.team_swap.data
        logger.debug(f"Form team_swap value: {team_swap_value}")
        player.team_swap = team_swap_value if team_swap_value else None  # Set to None if not selected
        logger.debug(f"Set player.team_swap to {player.team_swap}")

    # No need to call db.session.commit(); handled by decorator
    flash('Profile updated successfully.', 'success')
    logger.info(f"Profile for player {player.id} updated successfully.")
    return True

@query_operation
def check_email_uniqueness(email, user_id):
    logger.debug(f"Checking uniqueness for email: {email} and user_id: {user_id}")
    existing_user = User.query.filter(User.email == email, User.id != user_id).first()
    if existing_user:
        logger.warning(f"Email {email} already in use by user {existing_user.id}.")
        flash('Email is already in use by another account.', 'danger')
        return True
    logger.debug(f"Email {email} is unique.")
    return False

@db_operation
def handle_season_stats_update(player, form, season_id):
    logger.debug(f"Entering handle_season_stats_update for player {player.id} and season {season_id}")
    stats = {
        'goals': form.season_goals.data,
        'assists': form.season_assists.data,
        'yellow_cards': form.season_yellow_cards.data,
        'red_cards': form.season_red_cards.data,
    }
    logger.debug(f"Updating season stats with: {stats} by user {current_user.id}")
    player.update_season_stats(season_id, stats, user_id=current_user.id)
    # No need to call db.session.commit(); handled by decorator
    logger.info(f"Season stats updated successfully for player {player.id} in season {season_id}")
    flash('Season stats updated successfully.', 'success')

@db_operation
def handle_career_stats_update(player, form):
    logger.debug(f"Entering handle_career_stats_update for player {player.id}")
    stats = {
        'goals': form.career_goals.data,
        'assists': form.career_assists.data,
        'yellow_cards': form.career_yellow_cards.data,
        'red_cards': form.career_red_cards.data,
    }
    logger.debug(f"Updating career stats with: {stats} by user {current_user.id}")
    player.update_career_stats(stats, user_id=current_user.id)
    # No need to call db.session.commit(); handled by decorator
    logger.info(f"Career stats updated successfully for player {player.id}")
    flash('Career stats updated successfully.', 'success')

@db_operation
def handle_add_stat_manually(player):
    logger.debug(f"Entering handle_add_stat_manually for player {player.id}")
    try:
        match_id = request.form.get('match_id')
        goals = int(request.form.get('goals', 0))
        assists = int(request.form.get('assists', 0))
        yellow_cards = int(request.form.get('yellow_cards', 0))
        red_cards = int(request.form.get('red_cards', 0))
        
        new_stat_data = {
            'match_id': match_id,
            'goals': goals,
            'assists': assists,
            'yellow_cards': yellow_cards,
            'red_cards': red_cards,
        }
        logger.debug(f"Adding new stat manually with data: {new_stat_data} by user {current_user.id}")
        
        player.add_stat_manually(new_stat_data, user_id=current_user.id)
        # No need to call db.session.commit(); handled by decorator
        logger.info(f"Stat added successfully for player {player.id} in match {match_id}")
        flash('Stat added successfully.', 'success')
    except ValueError as e:
        logger.error(f"ValueError adding stats for player {player.id}: {str(e)}")
        flash('Invalid input for stats. Please enter valid numbers.', 'danger')
        raise  # Reraise exception to trigger rollback
    except Exception as e:
        logger.exception(f"Unexpected error adding stats for player {player.id}: {str(e)}")
        flash('An unexpected error occurred while adding stats. Please try again.', 'danger')
        raise  # Reraise exception to trigger rollback