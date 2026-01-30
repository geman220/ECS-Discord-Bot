# app/profile_helpers.py

"""
Profile Helpers Module

This module provides helper functions for handling profile updates,
including updating coach and referee statuses, processing profile information,
and updating season and career statistics.
"""

import logging
from flask import request, redirect, url_for, g
from app.alert_helpers import show_success, show_error
from app.models import User
from app.utils.user_helpers import safe_current_user
from app.tasks.tasks_discord import assign_roles_to_player_task

logger = logging.getLogger(__name__)


def handle_coach_status_update(player, user):
    """
    Update a player's coach status and enqueue a Discord role update task.

    This function updates both the global is_coach flag on the player
    and also updates the is_coach status in the player_teams association table
    for all teams the player is associated with.

    Args:
        player: The player object whose coach status is to be updated.
        user: The associated user object (not used directly here).

    Returns:
        A redirect response to the player's profile page.

    Raises:
        Exception: Propagates any encountered exception.
    """
    try:
        logger.debug("Entering handle_coach_status_update")
        is_coach = 'is_coach' in request.form
        logger.debug(f"Received is_coach: {is_coach}")

        # Update the global coach flag
        player.is_coach = is_coach
        player.discord_needs_update = True

        session = g.db_session
        session.add(player)
        
        # Update coach status in the player_teams association table for all teams
        from app.models import player_teams
        from sqlalchemy import text
        
        # Update all team relationships for this player to have the same coach status
        session.execute(
            text("UPDATE player_teams SET is_coach = :is_coach WHERE player_id = :player_id"),
            {"is_coach": is_coach, "player_id": player.id}
        )
        
        # Update Flask roles to match coach status
        if player.user:
            from app.models import Role
            coach_role = session.query(Role).filter_by(name='Pub League Coach').first()
            if coach_role:
                if is_coach:
                    # Add coach role if not already assigned
                    if coach_role not in player.user.roles:
                        player.user.roles.append(coach_role)
                        logger.info(f"Added 'Pub League Coach' Flask role to player {player.id}")
                else:
                    # Remove coach role if assigned
                    if coach_role in player.user.roles:
                        player.user.roles.remove(coach_role)
                        logger.info(f"Removed 'Pub League Coach' Flask role from player {player.id}")
            else:
                logger.warning("'Pub League Coach' role not found in database")
        
        session.commit()  # Commit changes first

        if player.discord_id:
            logger.debug(f"Queueing Discord role update for player {player.id}")
            discord_task = assign_roles_to_player_task.delay(player_id=player.id, only_add=False)
            if discord_task:
                logger.info(f"Discord role update task queued for player {player.id}. This will {'add' if is_coach else 'remove'} coach roles.")
            else:
                logger.error(f"Failed to queue Discord role update for player {player.id}")

        logger.info(f"{player.name}'s coach status updated successfully to {is_coach}")
        show_success(f"{player.name}'s coach status updated successfully.")
        return redirect(url_for('players.player_profile', player_id=player.id))
    except Exception as e:
        session = g.db_session
        session.rollback()
        logger.error(f"Error updating coach status: {str(e)}", exc_info=True)
        show_error('Error updating coach status.')
        raise


def handle_ref_status_update(player, user):
    """
    Update a player's referee status and enqueue a Discord role update task.

    Args:
        player: The player object whose referee status is to be updated.
        user: The associated user object (not used directly here).

    Returns:
        A redirect response to the player's profile page.

    Raises:
        Exception: Propagates any encountered exception.
    """
    try:
        logger.debug("Entering handle_ref_status_update")
        is_ref = 'is_ref' in request.form
        logger.debug(f"Received is_ref: {is_ref}")

        player.is_ref = is_ref
        player.discord_needs_update = True

        session = g.db_session
        session.add(player)
        
        # Update Flask roles to match referee status
        if player.user:
            from app.models import Role
            ref_role = session.query(Role).filter_by(name='Pub League Ref').first()
            if ref_role:
                if is_ref:
                    # Add referee role if not already assigned
                    if ref_role not in player.user.roles:
                        player.user.roles.append(ref_role)
                        logger.info(f"Added 'Pub League Ref' Flask role to player {player.id}")
                else:
                    # Remove referee role if assigned
                    if ref_role in player.user.roles:
                        player.user.roles.remove(ref_role)
                        logger.info(f"Removed 'Pub League Ref' Flask role from player {player.id}")
            else:
                logger.warning("'Pub League Ref' role not found in database")
        
        session.commit()  # Commit changes first

        if player.discord_id:
            discord_task = assign_roles_to_player_task.delay(player_id=player.id, only_add=False)
            if discord_task:
                logger.info(f"Discord role update task queued for player {player.id}. This will {'add' if is_ref else 'remove'} referee roles.")
            else:
                logger.error(f"Failed to queue Discord role update for player {player.id}")

        logger.info(f"{player.name}'s referee status updated successfully to {is_ref}")
        show_success(f"{player.name}'s referee status updated successfully.")
        return redirect(url_for('players.player_profile', player_id=player.id))
    except Exception as e:
        session = g.db_session
        session.rollback()
        logger.error(f"Error updating referee status: {str(e)}", exc_info=True)
        show_error('Error updating referee status.')
        raise


def handle_profile_update(form, player, user):
    """
    Update a player's profile and associated user email.

    Validates email uniqueness and updates fields such as name, phone,
    jersey size, pronouns, and other profile details.

    Args:
        form: The submitted form containing updated profile data.
        player: The player object to update.
        user: The user object associated with the player.

    Returns:
        A redirect response to the player's profile page.

    Raises:
        Exception: Propagates any encountered exception.
    """
    try:
        logger.debug("Entering handle_profile_update")

        # Check if the email is unique (excluding the current user) only if a new email is provided
        if form.email.data and check_email_uniqueness(form.email.data, user.id):
            logger.debug("Email not unique. Aborting update.")
            return redirect(url_for('players.player_profile', player_id=player.id))

        # Only update email if a new value is provided
        if form.email.data:
            new_email = form.email.data.lower()
            logger.debug(f"Updating user.email from {user.email} to {new_email}")
            user.email = new_email
        else:
            # Keep existing email if no new value provided
            logger.debug(f"No email provided in form, keeping existing email: {user.email}")

        # Update player fields
        player.name = form.name.data.strip() if form.name.data else player.name
        player.phone = form.phone.data.strip() if form.phone.data else player.phone
        player.jersey_size = form.jersey_size.data
        player.pronouns = form.pronouns.data
        player.expected_weeks_available = form.expected_weeks_available.data
        player.favorite_position = form.favorite_position.data
        player.frequency_play_goal = form.frequency_play_goal.data

        # Update array fields separately
        player.other_positions = ','.join(form.other_positions.data) if form.other_positions.data else None
        player.positions_not_to_play = ','.join(form.positions_not_to_play.data) if form.positions_not_to_play.data else None

        # Update player notes
        player.player_notes = form.player_notes.data

        # Handle team swap if present
        if hasattr(form, 'team_swap'):
            player.team_swap = form.team_swap.data if form.team_swap.data else None
            logger.debug(f"Set player.team_swap to {player.team_swap}")

        # Update profile last updated timestamp
        from datetime import datetime
        player.profile_last_updated = datetime.utcnow()

        session = g.db_session
        session.add(user)
        session.add(player)
        session.commit()

        show_success('Profile updated successfully.')
        logger.info(f"Profile for player {player.id} updated successfully.")
        return redirect(url_for('players.player_profile', player_id=player.id))
    except Exception as e:
        session = g.db_session
        session.rollback()
        logger.error(f"Error updating profile: {str(e)}", exc_info=True)
        show_error('Error updating profile.')
        raise


def check_email_uniqueness(email, user_id):
    """
    Check if the given email is already in use by another user (excluding the current user).

    Args:
        email (str): The email address to check.
        user_id: The ID of the current user.

    Returns:
        bool: True if the email is already in use, False otherwise.
    """
    session = g.db_session
    try:
        logger.debug(f"Checking uniqueness for email: {email} and user_id: {user_id}")
        existing_user = session.query(User).filter(User.email == email, User.id != user_id).first()
        if existing_user:
            logger.warning(f"Email {email} already in use by user {existing_user.id}.")
            show_error('Email is already in use by another account.')
            return True
        logger.debug(f"Email {email} is unique.")
        return False
    except Exception as e:
        logger.error(f"Error checking email uniqueness: {str(e)}", exc_info=True)
        show_error('Error checking email availability.')
        return True


def handle_season_stats_update(player, form, season_id):
    """
    Update a player's season statistics based on form input.

    Calculates the changes in goals, assists, yellow cards, and red cards,
    and updates the season statistics accordingly.

    Args:
        player: The player object.
        form: The submitted form containing season stats data.
        season_id: The ID of the season to update.

    Returns:
        A redirect response to the player's profile page.

    Raises:
        Exception: Propagates any encountered exception.
    """
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
        show_success('Season stats updated successfully.')
        return redirect(url_for('players.player_profile', player_id=player.id))
    except Exception as e:
        logger.error(f"Error updating season stats: {str(e)}", exc_info=True)
        show_error('Error updating season stats.')
        raise


def handle_career_stats_update(player, form):
    """
    Update a player's career statistics based on form input.

    Args:
        player: The player object.
        form: The submitted form containing career stats data.

    Returns:
        A redirect response to the player's profile page.

    Raises:
        Exception: Propagates any encountered exception.
    """
    try:
        logger.debug(f"Entering handle_career_stats_update for player {player.id}")
        if not player.career_stats:
            flash('No career stats found for this player.', 'danger')
            return redirect(url_for('players.player_profile', player_id=player.id))

        form.populate_obj(player.career_stats[0])
        logger.info(f"Career stats updated successfully for player {player.id}")
        show_success('Career stats updated successfully.')
        return redirect(url_for('players.player_profile', player_id=player.id))
    except Exception as e:
        logger.error(f"Error updating career stats: {str(e)}", exc_info=True)
        show_error('Error updating career stats.')
        raise


def handle_admin_notes_update(player, form):
    """
    Create a new admin note for a player (with author attribution).

    Args:
        player: The player object to add the note to.
        form: The submitted form containing admin notes data.

    Returns:
        A redirect response to the player's profile page.

    Raises:
        Exception: Propagates any encountered exception.
    """
    from app.models.players import PlayerAdminNote
    from app.utils.user_helpers import safe_current_user

    try:
        logger.debug(f"Entering handle_admin_notes_update for player {player.id}")

        note_content = form.notes.data
        if not note_content or not note_content.strip():
            show_error('Note content is required.')
            return redirect(url_for('players.player_profile', player_id=player.id))

        session = g.db_session

        # Create a new admin note with attribution
        admin_note = PlayerAdminNote(
            player_id=player.id,
            author_id=safe_current_user.id if safe_current_user else None,
            content=note_content.strip()
        )
        session.add(admin_note)
        session.commit()

        logger.info(f"Admin note created for player {player.id} by user {safe_current_user.id if safe_current_user else 'Unknown'}.")
        show_success('Admin note added successfully.')
        return redirect(url_for('players.player_profile', player_id=player.id))
    except Exception as e:
        session = g.db_session
        session.rollback()
        logger.error(f"Error creating admin note: {str(e)}", exc_info=True)
        show_error('Error adding admin note.')
        raise


def handle_add_stat_manually(player):
    """
    Add manual match statistics for a player.

    Reads match ID and stat values from the request form and updates the player's stats.

    Args:
        player: The player object.

    Returns:
        A redirect response to the player's profile page.

    Raises:
        ValueError: If stat values are invalid.
        Exception: Propagates any other encountered exception.
    """
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
        show_success('Stat added successfully.')
        return redirect(url_for('players.player_profile', player_id=player.id))
    except ValueError as e:
        logger.error(f"Invalid input for stats: {str(e)}", exc_info=True)
        show_error('Invalid input for stats. Please enter valid numbers.')
        raise
    except Exception as e:
        logger.error(f"Error adding stats: {str(e)}", exc_info=True)
        show_error('Error adding stats.')
        raise


def handle_profile_verification(player):
    """
    Update a player's profile verification timestamp without changing any other data.
    This is used when a player confirms their profile is accurate.

    Args:
        player: The player object to update.

    Returns:
        A redirect response to the player's profile page.

    Raises:
        Exception: Propagates any encountered exception.
    """
    try:
        logger.debug(f"Entering handle_profile_verification for player {player.id}")
        
        # Update profile last updated timestamp
        from datetime import datetime
        player.profile_last_updated = datetime.utcnow()
        
        session = g.db_session
        session.add(player)
        session.commit()
        
        logger.info(f"Profile verification timestamp updated for player {player.id}")
        show_success('Profile verified successfully. Thank you for confirming your information is current.')
        return redirect(url_for('players.player_profile', player_id=player.id))
    except Exception as e:
        session = g.db_session
        session.rollback()
        logger.error(f"Error updating profile verification: {str(e)}", exc_info=True)
        show_error('Error verifying profile.')
        raise


def handle_profile_verification_mobile(player):
    """
    Mobile version of profile verification that redirects to success page.
    """
    try:
        logger.debug(f"Entering handle_profile_verification_mobile for player {player.id}")
        
        # Update profile last updated timestamp
        from datetime import datetime
        player.profile_last_updated = datetime.utcnow()
        
        session = g.db_session
        session.add(player)
        session.commit()
        
        logger.info(f"Profile verification timestamp updated for player {player.id}")
        return redirect(url_for('players.mobile_profile_success', player_id=player.id, action='verified'))
    except Exception as e:
        session = g.db_session
        session.rollback()
        logger.error(f"Error updating profile verification: {str(e)}", exc_info=True)
        show_error('Error verifying profile.')
        raise


def handle_profile_update_mobile(form, player, user):
    """
    Mobile version of profile update that redirects to success page.
    """
    try:
        logger.debug("Entering handle_profile_update_mobile")

        # Check if the email is unique (excluding the current user) only if a new email is provided
        if form.email.data and check_email_uniqueness(form.email.data, user.id):
            logger.debug("Email not unique. Aborting update.")
            return redirect(url_for('players.mobile_profile_update', player_id=player.id))

        # Only update email if a new value is provided
        if form.email.data:
            new_email = form.email.data.lower()
            logger.debug(f"Updating user.email from {user.email} to {new_email}")
            user.email = new_email
        else:
            # Keep existing email if no new value provided
            logger.debug(f"No email provided in form, keeping existing email: {user.email}")

        # Update player fields
        player.name = form.name.data.strip() if form.name.data else player.name
        player.phone = form.phone.data.strip() if form.phone.data else player.phone
        player.jersey_size = form.jersey_size.data
        player.pronouns = form.pronouns.data
        player.expected_weeks_available = form.expected_weeks_available.data
        player.favorite_position = form.favorite_position.data
        player.frequency_play_goal = form.frequency_play_goal.data

        # Update array fields separately
        player.other_positions = ','.join(form.other_positions.data) if form.other_positions.data else None
        player.positions_not_to_play = ','.join(form.positions_not_to_play.data) if form.positions_not_to_play.data else None

        # Update player notes
        player.player_notes = form.player_notes.data.strip() if form.player_notes.data else None

        # Update profile last updated timestamp
        from datetime import datetime
        player.profile_last_updated = datetime.utcnow()

        session = g.db_session
        session.add(player)
        session.add(user)
        session.commit()

        logger.info(f"Profile updated successfully for player {player.id}")
        return redirect(url_for('players.mobile_profile_success', player_id=player.id, action='updated'))
    except Exception as e:
        session = g.db_session
        session.rollback()
        logger.error(f"Error updating player profile: {str(e)}", exc_info=True)
        show_error('Error updating profile.')
        raise


def handle_wizard_completion(form, player, user):
    """
    Handle the completion of the profile verification wizard.
    Updates player profile and redirects to success page.

    Args:
        form: The submitted PlayerProfileForm
        player: The player object to update
        user: The user object associated with the player

    Returns:
        A redirect response to the success page.
    """
    try:
        logger.debug(f"Entering handle_wizard_completion for player {player.id}")

        # Check email uniqueness if changed
        if form.email.data and check_email_uniqueness(form.email.data, user.id):
            logger.debug("Email not unique. Aborting update.")
            show_error('Email is already in use by another account.')
            return redirect(url_for('players.profile_wizard'))

        # Update email if provided
        if form.email.data:
            new_email = form.email.data.lower()
            user.email = new_email

        # Update player fields
        player.name = form.name.data.strip() if form.name.data else player.name
        player.phone = form.phone.data.strip() if form.phone.data else player.phone
        player.jersey_size = form.jersey_size.data
        player.pronouns = form.pronouns.data
        player.expected_weeks_available = form.expected_weeks_available.data
        player.favorite_position = form.favorite_position.data
        player.frequency_play_goal = form.frequency_play_goal.data
        player.willing_to_referee = form.willing_to_referee.data

        # Update array fields
        player.other_positions = ','.join(form.other_positions.data) if form.other_positions.data else None
        player.positions_not_to_play = ','.join(form.positions_not_to_play.data) if form.positions_not_to_play.data else None

        # Update player notes
        player.player_notes = form.player_notes.data.strip() if form.player_notes.data else None

        # Update verification timestamp
        from datetime import datetime
        player.profile_last_updated = datetime.utcnow()

        session = g.db_session
        session.add(player)
        session.add(user)
        session.commit()

        logger.info(f"Profile wizard completed for player {player.id}")
        return redirect(url_for('players.mobile_profile_success', player_id=player.id, action='verified'))

    except Exception as e:
        session = g.db_session
        session.rollback()
        logger.error(f"Error completing profile wizard: {str(e)}", exc_info=True)
        show_error('Error saving profile. Please try again.')
        raise