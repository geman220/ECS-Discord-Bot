# app/main.py

"""
Main Module

This module defines the primary routes for the application. It handles the
index page, user onboarding/profile creation and updates, fetching match
data, notifications, version management, and update operations. The module
leverages Flask blueprints, SQLAlchemy session management, and various forms
to deliver dynamic content and interactivity.
"""

import os
import subprocess
import requests
import logging
import asyncio
import aiohttp
from collections import defaultdict
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for, abort, request,
    jsonify, g, session
)
from app.alert_helpers import show_success, show_error, show_warning, show_info
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, func, text
from werkzeug.utils import secure_filename

from app.models import (
    Match, Notification, Team, Player, Announcement, player_teams, Season
)
from app.models.players import PlayerTeamSeason
from app.decorators import role_required
from app import csrf
from app.forms import (
    OnboardingForm, soccer_positions, pronoun_choices, availability_choices,
    willing_to_referee_choices, ReportMatchForm
)
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)
main = Blueprint('main', __name__)

PROJECT_DIR = "/app"
VERSION_FILE = os.path.join(PROJECT_DIR, "version.txt")
LATEST_VERSION_URL = "https://raw.githubusercontent.com/geman220/ECS-Discord-Bot/master/Discord-Bot-WebUI/version.txt"


@main.route('/api/health', methods=['GET'])
def api_health():
    """Simple health check endpoint for mobile API monitoring."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'webui',
        'version': '3.0.0',
        'message': 'WebUI API is running'
    })


def fetch_announcements():
    """
    Fetch the latest 5 announcements.
    
    Returns:
        list: A list of Announcement objects.
    """
    session = g.db_session
    return session.query(Announcement).order_by(Announcement.position.asc()).limit(5).all()


def get_onboarding_form(player=None, formdata=None):
    """
    Create and configure the onboarding form with dynamic choices.

    Parameters:
        player (Player, optional): The player object to pre-populate form fields.
        formdata (ImmutableMultiDict, optional): Form data from a POST request.

    Returns:
        OnboardingForm: The configured onboarding form instance.
    """
    session = g.db_session
    onboarding_form = OnboardingForm(formdata=formdata, obj=player)
    
    # Clear the name field to force user to enter their real name (not Discord username)
    if player and not formdata:
        onboarding_form.name.data = ""

    distinct_jersey_sizes = session.query(Player.jersey_size).distinct().all()
    jersey_size_choices = [(size[0], size[0]) for size in distinct_jersey_sizes if size[0]]
    onboarding_form.jersey_size.choices = jersey_size_choices or [('', 'Select a size')]
    onboarding_form.pronouns.choices = pronoun_choices or [('', 'Select pronouns')]
    onboarding_form.expected_weeks_available.choices = availability_choices or [('', 'Select availability')]
    onboarding_form.favorite_position.choices = soccer_positions or [('', 'Select position')]
    onboarding_form.other_positions.choices = soccer_positions
    onboarding_form.positions_not_to_play.choices = soccer_positions
    onboarding_form.willing_to_referee.choices = willing_to_referee_choices

    if player and not formdata:
        if player.other_positions:
            onboarding_form.other_positions.data = [
                pos.strip() for pos in player.other_positions.strip('{}').split(',')
            ]
        else:
            onboarding_form.other_positions.data = []
        if player.positions_not_to_play:
            onboarding_form.positions_not_to_play.data = [
                pos.strip() for pos in player.positions_not_to_play.strip('{}').split(',')
            ]
        else:
            onboarding_form.positions_not_to_play.data = []
        if player.user:
            onboarding_form.email.data = player.user.email
    elif not player:
        onboarding_form.other_positions.data = []
        onboarding_form.positions_not_to_play.data = []

    return onboarding_form


def create_player_profile(onboarding_form):
    """
    Create a new player profile from the onboarding form data.

    Parameters:
        onboarding_form (OnboardingForm): The submitted form with player data.

    Returns:
        Player: The newly created player object.
    """
    session = g.db_session
    try:
        def handle_profile_picture():
            if not onboarding_form.profile_picture.data:
                return None
            filename = secure_filename(onboarding_form.profile_picture.data.filename)
            upload_folder = 'static/uploads'
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            upload_path = os.path.join(upload_folder, filename)
            onboarding_form.profile_picture.data.save(upload_path)
            return url_for('static', filename='uploads/' + filename)

        other_positions = request.form.getlist('other_positions')
        positions_not_to_play = request.form.getlist('positions_not_to_play')
        profile_picture_url = handle_profile_picture()

        player = Player(
            user_id=safe_current_user.id,
            name=onboarding_form.name.data,
            email=onboarding_form.email.data,
            phone=onboarding_form.phone.data,
            jersey_size=onboarding_form.jersey_size.data,
            jersey_number=onboarding_form.jersey_number.data,
            profile_picture_url=profile_picture_url,
            pronouns=onboarding_form.pronouns.data,
            expected_weeks_available=onboarding_form.expected_weeks_available.data,
            unavailable_dates=onboarding_form.unavailable_dates.data,
            willing_to_referee=onboarding_form.willing_to_referee.data,
            favorite_position=onboarding_form.favorite_position.data,
            other_positions="{" + ",".join(other_positions) + "}" if other_positions else None,
            positions_not_to_play="{" + ",".join(positions_not_to_play) + "}" if positions_not_to_play else None,
            frequency_play_goal=onboarding_form.frequency_play_goal.data,
            additional_info=onboarding_form.additional_info.data,
            player_notes=onboarding_form.player_notes.data,
            team_swap=onboarding_form.team_swap.data,
            is_coach=False,
            discord_id=None,
            needs_manual_review=False,
            linked_primary_player_id=None,
            order_id=None,
            is_current_player=True
        )

        session.add(player)
        session.add(safe_current_user)
        logger.info(f"Created player profile for user {safe_current_user.id}")
        return player

    except Exception as e:
        logger.error(f"Error creating profile for user {safe_current_user.id}: {e}")
        raise


def trigger_immediate_new_player_notification(discord_id: str):
    """
    Trigger immediate new player notification when onboarding is completed.
    """
    try:
        response = requests.post(
            "http://discord-bot:5001/onboarding/notify-new-player",
            json={"discord_id": discord_id},
            timeout=5
        )
        if response.status_code == 200:
            logger.info(f"Triggered new player notification for {discord_id}")
        else:
            logger.error(f"Failed to trigger new player notification for {discord_id}: {response.status_code}")
    except Exception as e:
        logger.error(f"Error triggering new player notification for {discord_id}: {e}")


def handle_profile_update(player, onboarding_form):
    """
    Update an existing player profile with the data from the onboarding form.

    Parameters:
        player (Player): The player object to update.
        onboarding_form (OnboardingForm): The submitted form with updated data.
    """
    session = g.db_session
    try:
        player.name = onboarding_form.name.data
        player.phone = onboarding_form.phone.data
        player.jersey_size = onboarding_form.jersey_size.data
        player.jersey_number = onboarding_form.jersey_number.data
        player.pronouns = onboarding_form.pronouns.data
        player.favorite_position = onboarding_form.favorite_position.data
        player.expected_weeks_available = onboarding_form.expected_weeks_available.data
        player.unavailable_dates = onboarding_form.unavailable_dates.data
        player.other_positions = (
            "{" + ",".join(onboarding_form.other_positions.data) + "}"
            if onboarding_form.other_positions.data else None
        )
        player.positions_not_to_play = (
            "{" + ",".join(onboarding_form.positions_not_to_play.data) + "}"
            if onboarding_form.positions_not_to_play.data else None
        )
        player.willing_to_referee = onboarding_form.willing_to_referee.data
        player.frequency_play_goal = onboarding_form.frequency_play_goal.data
        player.player_notes = onboarding_form.player_notes.data
        player.team_swap = onboarding_form.team_swap.data
        player.additional_info = onboarding_form.additional_info.data

        safe_current_user.email_notifications = onboarding_form.email_notifications.data
        safe_current_user.sms_notifications = onboarding_form.sms_notifications.data
        safe_current_user.discord_notifications = onboarding_form.discord_notifications.data
        safe_current_user.profile_visibility = onboarding_form.profile_visibility.data
        safe_current_user.email = onboarding_form.email.data

        if onboarding_form.profile_picture.data:
            filename = secure_filename(onboarding_form.profile_picture.data.filename)
            upload_folder = 'static/uploads'
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            upload_path = os.path.join(upload_folder, filename)
            onboarding_form.profile_picture.data.save(upload_path)
            player.profile_picture_url = url_for('static', filename='uploads/' + filename)
            
            # Trigger image optimization for new upload
            try:
                from app.image_cache_service import handle_player_image_update
                handle_player_image_update(player.id)
                logger.info(f"Queued image optimization for player {player.id} during onboarding")
            except Exception as e:
                logger.warning(f"Failed to queue image optimization during onboarding: {e}")

        session.add(player)
        session.add(safe_current_user)
        logger.info(f"Updated profile for user {safe_current_user.id}")

    except Exception as e:
        logger.error(f"Error updating profile for user {safe_current_user.id}: {e}")
        raise


def fetch_upcoming_matches(
    teams,
    match_limit=4,
    include_past_matches=False,
    start_date=None,
    end_date=None,
    order='asc',
    specific_day=None,
    per_day_limit=None
):
    """
    Fetch upcoming (or past) matches for a list of teams and group them by match date.

    Parameters:
        teams (list): List of Team objects.
        match_limit (int, optional): Maximum number of matches to return if no specific day limit is set.
        include_past_matches (bool, optional): Whether to include past matches.
        start_date (date, optional): Start date filter.
        end_date (date, optional): End date filter.
        order (str, optional): 'asc' for ascending or 'desc' for descending order.
        specific_day (int, optional): Specific day of week to filter matches (0=Sunday).
        per_day_limit (int, optional): Maximum number of matches per day if specific_day is set.

    Returns:
        dict: A dictionary of matches grouped by match date.
    """
    session = g.db_session
    grouped_matches = defaultdict(list)
    today = datetime.now().date()

    # Log detailed debugging information
    team_names = [t.name for t in teams]
    logger.info(f"fetch_upcoming_matches called for teams: {team_names}")

    if not teams:
        logger.info("No teams provided, returning empty matches")
        return grouped_matches

    team_ids = [t.id for t in teams]
    logger.info(f"Team IDs: {team_ids}")
    
    if not start_date:
        start_date = today - timedelta(weeks=4) if include_past_matches else today
    if not end_date:
        end_date = today - timedelta(days=1) if include_past_matches else today + timedelta(weeks=4)

    logger.info(f"Date range: {start_date} to {end_date}, include_past_matches: {include_past_matches}")
    
    order_by = [Match.date.asc(), Match.time.asc()] if order == 'asc' else [Match.date.desc(), Match.time.desc()]

    # First, try to count all matches for these teams
    check_query = (
        session.query(func.count(Match.id))
        .filter(
            or_(
                Match.home_team_id.in_(team_ids),
                Match.away_team_id.in_(team_ids)
            )
        )
    )
    total_match_count = check_query.scalar()
    logger.info(f"Total matches for teams (regardless of date): {total_match_count}")
    
    # Now build the actual query with date filters
    # Using subqueries to check if teams and schedules exist
    query = (
        session.query(Match)
        .options(
            joinedload(Match.home_team).joinedload(Team.players),
            joinedload(Match.away_team).joinedload(Team.players),
            joinedload(Match.schedule)
        )
        .filter(
            or_(
                Match.home_team_id.in_(team_ids),
                Match.away_team_id.in_(team_ids)
            ),
            Match.date >= start_date,
            Match.date <= end_date
        )
        .order_by(*order_by)
    )

    # Debug the SQL query
    compiled_query = query.statement.compile(compile_kwargs={"literal_binds": True})
    logger.info(f"SQL query: {compiled_query}")

    # Get the matches
    matches = query.all()
    logger.info(f"Found {len(matches)} matches after filtering")

    # Log each match for debugging
    for match in matches:
        logger.info(f"Match: {match.id}, Date: {match.date}, Home: {match.home_team.name}, Away: {match.away_team.name}")

    if specific_day is not None and per_day_limit is not None:
        day_count = defaultdict(int)
        for match in matches:
            match_date = match.date
            weekday = match_date.weekday()
            logger.info(f"Match {match.id} on {match_date} (weekday {weekday})")
            
            if day_count[match_date] < per_day_limit:
                grouped_matches[match_date].append(_build_match_dict(match))
                day_count[match_date] += 1
                logger.info(f"Added match {match.id} to group {match_date}")
            else:
                logger.info(f"Skipped match {match.id} due to per_day_limit")
    else:
        if match_limit:
            matches = matches[:match_limit]
            logger.info(f"Limited to {len(matches)} matches due to match_limit")
        
        for match in matches:
            grouped_matches[match.date].append(_build_match_dict(match))
            logger.info(f"Added match {match.id} to group {match.date}")

    logger.info(f"Returning {sum(len(v) for v in grouped_matches.values())} matches grouped by {len(grouped_matches)} dates")
    return grouped_matches


def _build_match_dict(match):
    """
    Build a dictionary of match details.

    Parameters:
        match (Match): The match object.

    Returns:
        dict: A dictionary containing match and team details.
    """
    match_dict = {
        'match': match,
        'home_team_name': match.home_team.name,
        'opponent_name': match.away_team.name,
        'home_team_id': match.home_team_id,
        'away_team_id': match.away_team_id,  # Fixed: renamed to away_team_id for template consistency
        'home_players': [{'id': p.id, 'name': p.name} for p in match.home_team.players],
        'opponent_players': [{'id': p.id, 'name': p.name} for p in match.away_team.players]
    }
    
    # Add opponent_team_id as well for backwards compatibility
    match_dict['opponent_team_id'] = match.away_team_id
    
    logger.debug(f"Built match dict for match {match.id}: home_team_id={match_dict['home_team_id']}, away_team_id={match_dict['away_team_id']}")
    
    return match_dict


@main.route('/', endpoint='index', methods=['GET', 'POST'])
@login_required
def index():
    """
    Main index route that handles profile onboarding, match reporting,
    and displays upcoming and previous matches along with announcements.
    """
    session = g.db_session
    current_year = datetime.now().year

    try:
        # Retrieve or refresh the player profile for the current user.
        player = getattr(safe_current_user, 'player', None)
        is_coach = False  # Initialize coach flag
        
        if player:
            # Get player with teams, and with coach status for teams
            player = (
                session.query(Player)
                .options(joinedload(Player.teams).joinedload(Team.league))
                .filter_by(id=player.id)
                .first()
            )
            
            # Check if player is a coach for any team
            if player:
                coach_teams = session.query(player_teams).filter(
                    player_teams.c.player_id == player.id,
                    player_teams.c.is_coach == True
                ).all()
                is_coach = len(coach_teams) > 0
                # Don't modify the database column, use a temporary attribute instead
                player._temp_is_coach = is_coach
        else:
            player = None

        onboarding_form = get_onboarding_form(
            player, formdata=request.form if request.method == 'POST' else None
        )
        report_form = ReportMatchForm()

        matches = (
            session.query(Match)
            .options(joinedload(Match.home_team), joinedload(Match.away_team))
            .all()
        )

        # Check if onboarding should be shown based on user flags and Flask session
        # Use flask.session instead of SQLAlchemy session
        from flask import session as flask_session
        
        # Remove force_onboarding flag if it exists but don't redirect - use modal instead
        if 'force_onboarding' in flask_session and flask_session['force_onboarding']:
            # Delete the flag from session to prevent redirect loops
            flask_session.pop('force_onboarding', None)
            # Don't redirect, just set the show_onboarding flag to True
            logger.info(f"Setting show_onboarding flag for user {safe_current_user.id} (force_onboarding flag found)")
            # We'll use client-side JS to show the onboarding modal instead
            
        show_onboarding = (
            (not safe_current_user.has_completed_onboarding if player else 
             not safe_current_user.has_skipped_profile_creation)
        )
        show_tour = safe_current_user.has_completed_onboarding and not safe_current_user.has_completed_tour

        if request.method == 'POST':
            form_action = request.form.get('form_action', '')
            logger.info(f"Processing form action: {form_action}")

            if form_action in ['create_profile', 'update_profile']:
                if onboarding_form.validate_on_submit():
                    try:
                        logger.info(f"Current has_completed_onboarding: {safe_current_user.has_completed_onboarding}")
                        session.refresh(safe_current_user)
                        if not player:
                            player = create_player_profile(onboarding_form)
                            if player:
                                safe_current_user.has_skipped_profile_creation = False
                        else:
                            handle_profile_update(player, onboarding_form)

                        # Check SMS verification status for users who opted in
                        if player:
                            # If user wants SMS but didn't verify their phone, don't complete onboarding
                            sms_verified = request.form.get('sms_verified') == 'true'
                            # Check if the user is already verified in the database
                            player_already_verified = player.is_phone_verified
                            
                            # Get SMS notification and consent settings from form
                            sms_notifications_enabled = request.form.get('sms_notifications') == 'y'
                            sms_consent_given = request.form.get('sms_consent') == 'on'
                            
                            # Check if phone number is provided when SMS is enabled
                            if sms_notifications_enabled and not player.phone and not request.form.get('phone'):
                                show_warning('Please provide a phone number to enable SMS notifications.')
                                return redirect(url_for('main.onboarding'))
                                
                            # Check for consent when SMS notifications are enabled
                            if sms_notifications_enabled and not sms_consent_given:
                                show_warning('Please check the consent box to enable SMS notifications.')
                                return redirect(url_for('main.onboarding'))
                            
                            # Check if the phone number is verified when SMS is enabled
                            if sms_notifications_enabled and not (sms_verified or player_already_verified):
                                logger.warning(f"SMS notifications enabled but phone not verified for player {player.id}")
                                show_warning('Please verify your phone number to complete registration with SMS notifications.')
                                return redirect(url_for('main.onboarding'))
                            
                            # Update onboarding status
                            safe_current_user.has_completed_onboarding = True
                            session.add(safe_current_user)
                            session.flush()
                            session.execute(
                                text("UPDATE users SET has_completed_onboarding = true WHERE id = :user_id"),
                                {"user_id": safe_current_user.id}
                            )
                            try:
                                session.commit()
                                session.refresh(safe_current_user)
                                logger.info(f"Verified has_completed_onboarding after update: {safe_current_user.has_completed_onboarding}")
                                result = session.execute(
                                    text("SELECT has_completed_onboarding FROM users WHERE id = :user_id"),
                                    {"user_id": safe_current_user.id}
                                ).fetchone()
                                logger.info(f"Direct query verification: has_completed_onboarding = {result[0]}")
                                show_success('Profile updated successfully!')
                                return redirect(url_for('main.index'))
                            except Exception as e:
                                session.rollback()
                                logger.exception(f"Error completing onboarding for user {safe_current_user.id}: {str(e)}")
                                show_error('Error updating profile. Please try again.')
                                return redirect(url_for('main.index'))

                    except Exception as e:
                        session.rollback()
                        logger.error(f"Error in profile creation/update: {str(e)}", exc_info=True)
                        show_error('An error occurred while saving your profile. Please try again.')
                        return redirect(url_for('main.index'))
                else:
                    logger.warning(f"Form validation failed: {onboarding_form.errors}")
                    show_error('Form validation failed. Please check the form inputs.')

            elif form_action == 'reset_skip_profile':
                try:
                    with session.begin():
                        safe_current_user.has_skipped_profile_creation = False
                        session.add(safe_current_user)
                    show_info('Onboarding has been reset. Please complete the onboarding process.')
                    return redirect(url_for('main.index'))
                except Exception as e:
                    logger.error(f"Error resetting profile: {str(e)}", exc_info=True)
                    show_error('An error occurred. Please try again.')
                    return redirect(url_for('main.index'))

        # Get only current season teams for the player
        user_teams = []
        if player:
            # Get current season (filter by Pub League)
            current_season = Season.query.filter_by(is_current=True, league_type='Pub League').first()
            if current_season:
                # Query teams through PlayerTeamSeason for current season only
                current_season_teams = g.db_session.query(Team).join(
                    PlayerTeamSeason, Team.id == PlayerTeamSeason.team_id
                ).filter(
                    PlayerTeamSeason.player_id == player.id,
                    PlayerTeamSeason.season_id == current_season.id
                ).all()
                
                # If no PlayerTeamSeason records found for current season, fall back to direct team relationships
                if not current_season_teams:
                    # Filter teams by current season's leagues
                    current_season_leagues = [league.id for league in current_season.leagues]
                    current_season_teams = [team for team in player.teams if team.league_id in current_season_leagues]
                
                user_teams = current_season_teams
        today = datetime.now().date()
        two_weeks_later = today + timedelta(weeks=2)
        one_week_ago = today - timedelta(weeks=1)
        yesterday = today - timedelta(days=1)
        
        # Debug teams and match relationship directly using SQL
        if user_teams:
            team_ids_str = ", ".join(str(t.id) for t in user_teams)
            try:
                # Find all matches for these teams
                match_query = text(f"""
                    SELECT 
                        m.id, 
                        m.date, 
                        m.time, 
                        m.location,
                        h.id as home_team_id, 
                        h.name as home_team_name,
                        a.id as away_team_id, 
                        a.name as away_team_name
                    FROM 
                        matches m
                    JOIN 
                        team h ON m.home_team_id = h.id
                    JOIN 
                        team a ON m.away_team_id = a.id
                    WHERE 
                        m.home_team_id IN ({team_ids_str}) OR m.away_team_id IN ({team_ids_str})
                    ORDER BY 
                        m.date, m.time
                """)
                
                match_results = session.execute(match_query).fetchall()
                
                # Only log basic info about SQL query results at debug level
                logger.debug(f"Found {len(match_results)} matches for user teams")
                
            except Exception as e:
                logger.error(f"Error in direct SQL query: {e}")
        
        # For upcoming matches - show matches from today forward
        next_matches = fetch_upcoming_matches(
            teams=user_teams,
            start_date=today,
            end_date=today + timedelta(days=30),  # Look ahead a month
            match_limit=4,  # Show up to 4 upcoming matches
            order='asc'
        )
        
        # For previous matches - show matches before today
        previous_matches = fetch_upcoming_matches(
            teams=user_teams,
            start_date=today - timedelta(days=14),  # Look back 2 weeks
            end_date=today - timedelta(days=1),     # Yesterday
            match_limit=4,
            include_past_matches=True,
            order='desc'
        )
        
        # Basic debug info at debug level only
        logger.debug(f"Found {sum(len(matches) for matches in next_matches.values())} upcoming matches for index page")
        logger.info(f"Found {sum(len(matches) for matches in previous_matches.values())} previous matches")

        announcements = fetch_announcements()
        player_choices_per_match = {}

        for matches_dict in [next_matches, previous_matches]:
            for date_key, matches_list in matches_dict.items():
                for match_data in matches_list:
                    match = match_data['match']
                    home_team_id = match_data['home_team_id']
                    opp_team_id = match_data['opponent_team_id']

                    players = (
                        session.query(Player)
                        .join(player_teams, player_teams.c.player_id == Player.id)
                        .filter(player_teams.c.team_id.in_([home_team_id, opp_team_id]))
                        .all()
                    )
                    home_players = [p for p in players if any(t.id == home_team_id for t in p.teams)]
                    away_players = [p for p in players if any(t.id == opp_team_id for t in p.teams)]
                    player_choices_per_match[match.id] = {
                        match_data['home_team_name']: {p.id: p.name for p in home_players},
                        match_data['opponent_name']: {p.id: p.name for p in away_players}
                    }

        # Pre-process match data for the template
        processed_next_matches = {}
        processed_prev_matches = {}
        
        # Process team matches into team-specific collections
        team_matches = {t.id: {'next': {}, 'prev': {}} for t in user_teams}
        
        # Process next matches
        for date, matches_list in next_matches.items():
            processed_next_matches[date] = matches_list  # Keep original structure for debug
            
            # Organize by team
            for match_data in matches_list:
                home_id = match_data['home_team_id']
                away_id = match_data['away_team_id']
                
                # Add to home team if relevant
                if home_id in team_matches:
                    if date not in team_matches[home_id]['next']:
                        team_matches[home_id]['next'][date] = []
                    team_matches[home_id]['next'][date].append(match_data)
                
                # Add to away team if relevant
                if away_id in team_matches:
                    if date not in team_matches[away_id]['next']:
                        team_matches[away_id]['next'][date] = []
                    team_matches[away_id]['next'][date].append(match_data)
        
        # Process previous matches
        for date, matches_list in previous_matches.items():
            processed_prev_matches[date] = matches_list  # Keep original structure for debug
            
            # Organize by team
            for match_data in matches_list:
                home_id = match_data['home_team_id']
                away_id = match_data['away_team_id']
                
                # Add to home team if relevant
                if home_id in team_matches:
                    if date not in team_matches[home_id]['prev']:
                        team_matches[home_id]['prev'][date] = []
                    team_matches[home_id]['prev'][date].append(match_data)
                
                # Add to away team if relevant
                if away_id in team_matches:
                    if date not in team_matches[away_id]['prev']:
                        team_matches[away_id]['prev'][date] = []
                    team_matches[away_id]['prev'][date].append(match_data)
        
        # Log what we found
        for team_id, match_data in team_matches.items():
            team_name = next((t.name for t in user_teams if t.id == team_id), "Unknown")
            next_count = sum(len(matches) for matches in match_data['next'].values())
            prev_count = sum(len(matches) for matches in match_data['prev'].values())
            logger.info(f"Preprocessed matches for {team_name} (ID: {team_id}): {next_count} upcoming, {prev_count} previous")
            
            # Log dates with matches
            logger.info(f"  Next match dates: {list(match_data['next'].keys())}")
            logger.info(f"  Prev match dates: {list(match_data['prev'].keys())}")
            
        # Pass the temporary coach status to the template
        is_coach = getattr(player, '_temp_is_coach', player.is_coach if player else False)
        
        return render_template(
            'index.html',
            title='Home',
            report_form=report_form,
            matches=matches,
            onboarding_form=onboarding_form,
            user_team=user_teams,
            next_matches=next_matches,
            previous_matches=previous_matches,
            team_matches=team_matches,  # Add the pre-processed matches
            current_year=current_year,
            team=user_teams,
            player=player,
            is_coach=is_coach,  # Pass the calculated is_coach value separately
            is_linked_to_discord=(player.discord_id is not None if player else False),
            discord_server_link="https://discord.gg/weareecs",
            show_onboarding=show_onboarding,
            show_tour=show_tour,
            announcements=announcements,
            player_choices=player_choices_per_match
        )

    except Exception as e:
        logger.error(f"Unexpected error in index route: {str(e)}", exc_info=True)
        show_error('An unexpected error occurred. Please try again.')
        return redirect(url_for('main.index'))


@main.route('/privacy-policy', methods=['GET'])
def privacy_policy():
    """
    Display the privacy policy for the ECS Soccer League ChatGPT Assistant.
    
    This route serves the privacy policy required for the ChatGPT Custom GPT integration,
    explaining how user data is accessed and used through the external API.
    
    This page is publicly accessible (no login required) as it needs to be
    accessible to anyone using the ChatGPT integration.
    
    Returns:
        Rendered privacy policy template using unauthenticated base.
    """
    return render_template('privacy_policy.html', title='Privacy Policy')


@main.route('/notifications', endpoint='notifications', methods=['GET'])
@login_required
def notifications():
    """
    Retrieve and display all notifications for the current user.

    Returns:
        Rendered template of notifications.
    """
    session = g.db_session
    notifications = (
        session.query(Notification)
        .filter_by(user_id=safe_current_user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    return render_template('notifications.html', notifications=notifications)


@main.route('/notifications/mark_as_read/<int:notification_id>', endpoint='mark_as_read', methods=['POST'])
@login_required
def mark_as_read(notification_id):
    """
    Mark a specific notification as read.

    Parameters:
        notification_id (int): The ID of the notification.

    Returns:
        Redirect to the notifications page.
    """
    session = g.db_session
    notification = session.query(Notification).get(notification_id)
    if not notification:
        abort(404)
    if notification.user_id != safe_current_user.id:
        abort(403)
    notification.is_read = True
    try:
        session.add(notification)
        session.commit()
        return redirect(url_for('main.notifications'))
    except Exception as e:
        session.rollback()
        logger.exception(f"Error marking notification {notification_id} as read: {str(e)}")
        show_error('Error updating notification.')
        return redirect(url_for('main.notifications'))


@main.route('/profile/me', methods=['GET', 'POST'])
def my_profile():
    """
    Direct users to their own profile or login if not authenticated.
    Perfect for QR codes at registration events.
    """
    # Detect mobile from User-Agent or explicit mobile parameter
    is_mobile_request = request.args.get('mobile') == '1'
    if not is_mobile_request:
        user_agent = request.headers.get('User-Agent', '').lower()
        is_mobile_request = any(mobile_string in user_agent for mobile_string in [
            'mobile', 'iphone', 'android', 'blackberry', 'ipad', 'tablet', 
            'samsung', 'nokia', 'windows phone'
        ])
    
    if not safe_current_user.is_authenticated:
        # Store the intended destination WITH mobile parameter if needed
        if is_mobile_request:
            session['next'] = url_for('main.my_profile', mobile=1)
        else:
            session['next'] = url_for('main.my_profile')
        show_info('Please log in to access your profile.')
        return redirect(url_for('auth.login'))
    
    # Get the player associated with current user
    db_session = g.db_session
    player = db_session.query(Player).filter_by(user_id=safe_current_user.id).first()
    
    if not player:
        show_error('No player profile found. Please contact an administrator.')
        return redirect(url_for('main.index'))
    
    # Route to mobile or desktop version
    if is_mobile_request:
        return redirect(url_for('players.mobile_profile_update', player_id=player.id))
    else:
        return redirect(url_for('players.desktop_profile_update', player_id=player.id))


@main.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    """
    Handle the onboarding process for newly registered users.
    
    This route is used specifically for users who have registered with Discord
    and need to complete their profile information.
    """
    # Get database session and player
    session = g.db_session
    
    # IMPORTANT: Clear any force_onboarding flag immediately to prevent redirect loops
    from flask import session as flask_session
    if 'force_onboarding' in flask_session:
        logger.info(f"Clearing force_onboarding flag for user {safe_current_user.id}")
        flask_session.pop('force_onboarding', None)
    
    # Get player info
    player = getattr(safe_current_user, 'player', None)
    
    # If user already completed onboarding, redirect to index
    if player and safe_current_user.has_completed_onboarding:
        show_info('Your profile is already set up!')
        return redirect(url_for('main.index'))
    
    # Get the onboarding form
    onboarding_form = get_onboarding_form(
        player, 
        formdata=request.form if request.method == 'POST' else None
    )
    
    # Handle form submission
    if request.method == 'POST' and onboarding_form.validate_on_submit():
        try:
            logger.info(f"Processing onboarding form submission for user {safe_current_user.id}")
            
            # Create or update player profile
            if not player:
                player = create_player_profile(onboarding_form)
            else:
                handle_profile_update(player, onboarding_form)
            
            # Process league selection
            preferred_league = request.form.get('preferred_league')
            if preferred_league:
                safe_current_user.preferred_league = preferred_league
                safe_current_user.league_selection_method = 'onboarding'
                logger.info(f"User {safe_current_user.id} selected league: {preferred_league}")
            else:
                logger.warning(f"User {safe_current_user.id} completed onboarding without selecting a league")
            
            # Check SMS verification if needed
            sms_notifications = request.form.get('sms_notifications') == 'y'
            sms_verified = request.form.get('sms_verified') == 'true'
            already_verified = player and player.is_phone_verified
            
            # If SMS is enabled but not verified, show warning
            if sms_notifications and not (sms_verified or already_verified):
                show_warning('Please verify your phone number to enable SMS notifications.')
            else:
                # Mark onboarding as complete
                safe_current_user.has_completed_onboarding = True
                session.add(safe_current_user)
                try:
                    session.commit()
                    show_success('Profile created successfully!')
                    
                    # Trigger new player notification if user already has Discord linked
                    if player and player.discord_id:
                        trigger_immediate_new_player_notification(player.discord_id)
                    
                    return redirect(url_for('main.index'))
                except Exception as e:
                    session.rollback()
                    logger.exception(f"Error completing onboarding for user {safe_current_user.id}: {str(e)}")
                    show_error('Error saving profile. Please try again.')
                    return redirect(url_for('main.onboarding'))
                
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving profile: {e}", exc_info=True)
            show_error('An error occurred. Please try again.')
    
    # Get Discord invite link from session
    discord_invite_link = flask_session.get('discord_invite_link', "https://discord.gg/weareecs")
    needs_discord_join = flask_session.get('needs_discord_join', False)
    
    # Render the template
    return render_template(
        'onboarding.html',
        title='Complete Your Profile',
        onboarding_form=onboarding_form,
        player=player,
        discord_invite_link=discord_invite_link,
        needs_discord_join=needs_discord_join
    )


@main.route('/set_tour_skipped', endpoint='set_tour_skipped', methods=['POST'])
@login_required
def set_tour_skipped():
    """
    Set the tour status as skipped for the current user.

    Returns:
        An empty response with HTTP 204 status code.
    """
    session = g.db_session
    try:
        safe_current_user.has_completed_tour = False
        session.add(safe_current_user)
        session.commit()
        logger.info(f"User {safe_current_user.id} set tour as skipped.")
    except Exception as e:
        logger.error(f"Error setting tour skipped for user {safe_current_user.id}: {str(e)}")
        return jsonify({'error': 'An error occurred while updating tour status'}), 500
    return '', 204


@main.route('/set_tour_complete', endpoint='set_tour_complete', methods=['POST'])
@login_required
def set_tour_complete():
    """
    Mark the tour as completed for the current user.

    Returns:
        An empty response with HTTP 204 status code.
    """
    session = g.db_session
    try:
        safe_current_user.has_completed_tour = True
        session.add(safe_current_user)
        session.commit()
        logger.info(f"User {safe_current_user.id} completed the tour.")
    except Exception as e:
        logger.error(f"Error setting tour complete for user {safe_current_user.id}: {str(e)}")
        return jsonify({'error': 'An error occurred while updating tour status'}), 500
    return '', 204


@main.route('/version', endpoint='get_version', methods=['GET'])
def get_version():
    """
    Retrieve the current version of the application from the version file.

    Returns:
        JSON response containing the current version.
    """
    with open(VERSION_FILE, 'r') as f:
        version = f.read().strip()
    return jsonify({"version": version})


def get_latest_version():
    """
    Fetch the latest version of the application from the remote repository.

    Returns:
        str or None: The latest version string, or None if the request fails.
    """
    response = requests.get(LATEST_VERSION_URL)
    if response.status_code == 200:
        return response.text.strip()
    return None


@main.route('/check-update', endpoint='check_for_update', methods=['GET'])
@login_required
@role_required('Global Admin')
def check_for_update():
    """
    Check if an update is available by comparing the current version with the latest version.

    Returns:
        JSON response indicating whether an update is available.
    """
    current_version = open(VERSION_FILE, 'r').read().strip()
    latest_version = get_latest_version()
    if latest_version and latest_version != current_version:
        return jsonify({
            "update_available": True,
            "current_version": current_version,
            "latest_version": latest_version
        })
    return jsonify({
        "update_available": False,
        "current_version": current_version
    })


@main.route('/update', endpoint='update_application', methods=['POST'])
@login_required
@role_required('Global Admin')
def update_application():
    """
    Initiate an application update if confirmed via JSON payload.

    Expects:
        JSON with {"confirm": "yes"}.

    Returns:
        JSON response indicating success or failure of the update initiation.
    """
    if not request.is_json or request.json.get('confirm') != 'yes':
        return jsonify({"success": False, "message": "Confirmation required"}), 400
    try:
        result = subprocess.run(
            ["/path/to/update_app.sh"],
            check=True,
            capture_output=True,
            text=True
        )
        return jsonify({"success": True, "message": "Update initiated", "output": result.stdout})
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "message": str(e)}), 500


@main.route('/set-theme', methods=['POST'])
def set_theme():
    """
    Set the user's theme preference.

    This endpoint allows users to toggle between light and dark themes.
    The preference is stored in the session and persists between page loads.

    Returns:
        JSON: A JSON response indicating success or failure of the operation.
    """
    data = request.get_json()
    if not data or 'theme' not in data:
        return jsonify({"success": False, "message": "Theme not provided"}), 400
    
    theme = data['theme']
    if theme not in ['light', 'dark', 'system']:
        return jsonify({"success": False, "message": "Invalid theme"}), 400
    
    # Store theme in session
    session['theme'] = theme
    
    # If user is logged in, store preference in their profile
    if current_user.is_authenticated:
        try:
            user = Player.query.get(current_user.id)
            if user and hasattr(user, 'preferences'):
                # Use preferences JSON field if it exists
                preferences = user.preferences or {}
                preferences['theme'] = theme
                user.preferences = preferences
                g.db_session.add(user)
                try:
                    g.db_session.commit()
                except Exception as e:
                    g.db_session.rollback()
                    logger.exception(f"Error saving theme preference for user {current_user.id}: {e}")
        except Exception as e:
            logger.error(f"Error saving theme preference for user {current_user.id}: {e}")
    
    return jsonify({"success": True, "message": f"Theme set to {theme}"})


@csrf.exempt
@main.route('/clear_sweet_alert', methods=['POST'])
def clear_sweet_alert():
    """
    Clear the sweet alert from the session.
    
    This endpoint is called after a SweetAlert has been displayed to prevent
    it from appearing again on page refresh.
    
    Returns:
        JSON response indicating success or failure.
    """
    from flask import session as flask_session
    try:
        if 'sweet_alert' in flask_session:
            alert_data = flask_session.pop('sweet_alert', None)
            logger.info(f"Sweet alert cleared from session: {alert_data}")
            
            # Force session save to ensure the change is persisted
            flask_session.permanent = True
            flask_session.modified = True
            
            return jsonify({'success': True, 'message': 'Alert cleared successfully'})
        else:
            logger.debug("No sweet alert found in session to clear")
            return jsonify({'success': True, 'message': 'No alert to clear'})
    except Exception as e:
        logger.error(f"Error clearing sweet alert: {str(e)}")
        # Try to force clear even if there's an error
        try:
            flask_session.pop('sweet_alert', None)
            flask_session.permanent = True
            flask_session.modified = True
        except:
            pass
        return jsonify({'success': False, 'message': 'Error clearing alert'}), 500


@main.route('/save_phone_for_verification', methods=['POST'])
@login_required
def save_phone_for_verification():
    """
    Save the phone number temporarily for verification purposes.
    
    Returns:
        JSON response with success status.
    """
    try:
        phone_number = request.json.get('phone')
        if not phone_number:
            return jsonify({'success': False, 'message': 'Phone number is required'}), 400
        
        # Format phone number properly if needed
        if not phone_number.startswith('+'):
            if phone_number.startswith('1') and len(phone_number) == 11:
                phone_number = '+' + phone_number
            elif len(phone_number) == 10:
                phone_number = '+1' + phone_number
            else:
                phone_number = '+' + phone_number
        
        # Store in session for temporary use
        from flask import session as flask_session
        flask_session['temp_phone_for_verification'] = phone_number
        logger.info(f"Saved temporary phone number for verification: {phone_number} for user {safe_current_user.id}")
        
        # Also update user's profile phone number if player exists
        session = g.db_session
        player = safe_current_user.player
        
        if player:
            player.phone = phone_number
            session.add(player)
            try:
                session.commit()
                logger.info(f"Updated player {player.id} phone number: {phone_number}")
            except Exception as e:
                session.rollback()
                logger.error(f"Error updating phone number for player {player.id}: {e}")
                # Still continue since we saved to session
        
        return jsonify({'success': True, 'message': 'Phone number saved for verification'})
    except Exception as e:
        logger.error(f"Error saving phone for verification for user {safe_current_user.id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': f'Error saving phone number: {str(e)}'}), 500


@main.route('/send_verification_code', methods=['POST'])
@login_required
def send_verification_code():
    """
    Send an SMS verification code to the user's phone number.
    
    Returns:
        JSON response with success status and message.
    """
    from app.sms_helpers import send_confirmation_sms
    
    try:
        # Get phone from request or from session
        from flask import session as flask_session
        phone_number = request.json.get('phone') or flask_session.get('temp_phone_for_verification')
        
        if not phone_number:
            return jsonify({'success': False, 'message': 'Phone number is required'}), 400
        
        # Format phone number properly if needed
        if not phone_number.startswith('+'):
            if phone_number.startswith('1') and len(phone_number) == 11:
                phone_number = '+' + phone_number
            elif len(phone_number) == 10:
                phone_number = '+1' + phone_number
            else:
                phone_number = '+' + phone_number
        
        logger.info(f"Sending verification code to phone: {phone_number} for user {safe_current_user.id}")
        
        # Ensure the phone number is saved in player record
        session = g.db_session
        player = safe_current_user.player
        
        if not player:
            logger.error(f"Player profile not found for user {safe_current_user.id}")
            return jsonify({'success': False, 'message': 'Player profile not found'}), 404
        
        # Update phone number
        player.phone = phone_number
        session.add(player)
        try:
            session.commit()
            logger.info(f"Updated player {player.id} phone number to {phone_number} for verification")
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating player phone number: {e}")
            # Continue anyway to try sending the verification
        
        # Send verification code
        success, message = send_confirmation_sms(safe_current_user)
        
        if success:
            logger.info(f"Verification code sent successfully to user {safe_current_user.id}")
            return jsonify({'success': True, 'message': 'Verification code sent'})
        else:
            logger.warning(f"Failed to send verification code to user {safe_current_user.id}: {message}")
            return jsonify({'success': False, 'message': f'Failed to send verification code: {message}'}), 200  # Return 200 to let our error handler work
    except Exception as e:
        logger.error(f"Error in send_verification_code for user {safe_current_user.id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': f'Error sending verification code: {str(e)}'}), 500


@main.route('/verify_sms_code', methods=['POST'])
@login_required
def verify_sms_code():
    """
    Verify the SMS code entered by the user.
    
    Returns:
        JSON response with success status and message.
    """
    from app.sms_helpers import verify_sms_confirmation
    
    try:
        code = request.json.get('code')
        if not code:
            return jsonify({'success': False, 'message': 'Verification code is required'})
        
        # Get the session code as backup
        from flask import session as flask_session
        session_code = flask_session.get('sms_confirmation_code')
        logger.info(f"Found code in Flask session: {session_code}")
        
        # If user has no code but we have one in the session, set it
        if not safe_current_user.sms_confirmation_code and session_code:
            logger.info(f"Setting confirmation code from session for user {safe_current_user.id}")
            safe_current_user.sms_confirmation_code = session_code
            db_session = g.db_session
            db_session.add(safe_current_user)
            try:
                db_session.commit()
            except Exception as e:
                db_session.rollback()
                logger.exception(f"Error saving SMS confirmation code for user {safe_current_user.id}: {str(e)}")
                return jsonify({"success": False, "message": "Error saving verification code"})
        
        # Verify the code
        logger.info(f"Verifying SMS code for user {safe_current_user.id}: {code}")
        success = verify_sms_confirmation(safe_current_user, code)
        
        # If verification failed but the code matches the one in session, force success
        if not success and session_code and session_code == code:
            logger.warning(f"Forcing success because code matches session for user {safe_current_user.id}")
            success = True
        
        if success:
            # Also update player record to show verified phone
            session = g.db_session
            player = safe_current_user.player
            if player:
                player.is_phone_verified = True
                player.sms_consent_given = True
                player.sms_consent_timestamp = datetime.utcnow()
                
                # If the player had a different phone number before, it's now verified again
                if player.phone:
                    logger.info(f"Phone verified for player {player.id}: {player.phone}")
                    
                session.add(player)
                try:
                    session.commit()
                    logger.info(f"Phone verification successful for user {safe_current_user.id}")
                except Exception as e:
                    session.rollback()
                    logger.exception(f"Error saving phone verification for user {safe_current_user.id}: {str(e)}")
                    return jsonify({"success": False, "message": "Error saving phone verification"})
                
                # Clear the code from session
                if 'sms_confirmation_code' in flask_session:
                    flask_session.pop('sms_confirmation_code')
                
            return jsonify({'success': True, 'message': 'Phone number verified successfully'})
        else:
            logger.warning(f"Phone verification failed for user {safe_current_user.id}: Invalid code")
            return jsonify({'success': False, 'message': 'Invalid verification code'})
    except Exception as e:
        logger.error(f"Error verifying SMS code for user {safe_current_user.id}: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': f'Error verifying code: {str(e)}'})


@main.route('/test_sms_verification', methods=['GET'])
@login_required
@role_required('Global Admin')
def test_sms_verification():
    """
    Test endpoint for SMS verification - only accessible by admins.
    
    Returns:
        JSON response with current SMS verification status for debugging.
    """
    try:
        player = safe_current_user.player
        verification_status = {
            'user_id': safe_current_user.id,
            'has_player': player is not None,
            'verification_code': safe_current_user.sms_confirmation_code,
            'sms_notifications_enabled': safe_current_user.sms_notifications,
            'sms_consent_timestamp': safe_current_user.sms_opt_in_timestamp,
        }
        
        if player:
            verification_status.update({
                'player_id': player.id,
                'player_phone': player.phone,
                'player_phone_verified': player.is_phone_verified,
                'sms_consent_given': player.sms_consent_given,
                'sms_consent_timestamp': player.sms_consent_timestamp
            })
        
        # Generate a test code for easy verification
        from app.sms_helpers import generate_confirmation_code
        test_code = safe_current_user.sms_confirmation_code or generate_confirmation_code()
        verification_status['test_code'] = test_code
        
        if not safe_current_user.sms_confirmation_code:
            safe_current_user.sms_confirmation_code = test_code
            g.db_session.add(safe_current_user)
            try:
                g.db_session.commit()
                verification_status['debug_note'] = 'Created new test verification code'
            except Exception as e:
                g.db_session.rollback()
                logger.exception(f"Error saving test verification code for user {safe_current_user.id}: {str(e)}")
                verification_status['debug_note'] = 'Error creating test verification code'
            
        return jsonify(verification_status)
    except Exception as e:
        logger.error(f"Error in test_sms_verification: {e}", exc_info=True)
        return jsonify({'error': str(e)})


@main.route('/set_verification_code', methods=['POST'])
@login_required
@role_required('Global Admin')  # Restrict to admins only
def set_verification_code():
    """
    ADMIN ONLY: Manually set a verification code for testing purposes.
    
    This endpoint allows setting the SMS verification code directly,
    bypassing the normal SMS sending process. Useful for testing or
    when SMS services are unavailable.
    
    Returns:
        JSON response with success status.
    """
    try:
        # Get the verification code from the request
        code = request.json.get('code')
        
        if not code:
            # If no code provided, generate a 6-digit code
            from app.sms_helpers import generate_confirmation_code
            code = generate_confirmation_code()
            
        # Set the confirmation code on the user
        safe_current_user.sms_confirmation_code = code
        safe_current_user.sms_opt_in_timestamp = datetime.utcnow()
        
        # Save to database
        session = g.db_session
        session.add(safe_current_user)
        try:
            session.commit()
            logger.info(f"[ADMIN] Manually set verification code {code} for user {safe_current_user.id}")
        except Exception as e:
            session.rollback()
            logger.exception(f"Error saving manual verification code for user {safe_current_user.id}: {str(e)}")
            return jsonify({"success": False, "message": "Error saving verification code"})
        
        # Return the code for the user to enter
        return jsonify({
            'success': True, 
            'code': code, 
            'message': 'Verification code set successfully'
        })
    except Exception as e:
        logger.error(f"Error setting verification code: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})


@main.context_processor
def inject_theme():
    """
    Inject the current theme into all templates.

    This function makes the current theme available to all templates,
    allowing them to adjust their styling accordingly.

    Returns:
        dict: A dictionary containing the current theme.
    """
    # Get theme from session, default to light
    theme = session.get('theme', 'light')
    return {'current_theme': theme}


@main.context_processor
def inject_static_file_versions():
    """
    Inject static file versioning function into templates.
    
    This function makes a file_version function available in templates
    that can be used to add cache-busting version parameters to static file URLs.
    
    Returns:
        dict: A dictionary containing the file_version function.
    """
    from app.extensions import file_versioning
    
    def file_version(filepath, method='mtime'):
        """Generate a versioned URL for a static file to bust browser caches."""
        try:
            version = file_versioning.get_version(filepath, method)
            return f"{url_for('static', filename=filepath)}?v={version}"
        except Exception as e:
            logger.error(f"Error generating version for {filepath}: {str(e)}")
            # Fallback to a random version to ensure cache busting
            import random
            return f"{url_for('static', filename=filepath)}?v={random.randint(1, 1000000)}"
    
    return {'file_version': file_version}


@main.context_processor
def inject_static_file_versions():
    """
    Inject static file versioning function into templates.
    
    This function makes a file_version function available in templates
    that can be used to add cache-busting version parameters to static file URLs.
    
    Returns:
        dict: A dictionary containing the file_version function.
    """
    from app.extensions import file_versioning
    
    def file_version(filepath, method='mtime'):
        """Generate a versioned URL for a static file to bust browser caches."""
        try:
            version = file_versioning.get_version(filepath, method)
            return f"{url_for('static', filename=filepath)}?v={version}"
        except Exception as e:
            logger.error(f"Error generating version for {filepath}: {str(e)}")
            # Fallback to a random version to ensure cache busting
            import random
            return f"{url_for('static', filename=filepath)}?v={random.randint(1, 1000000)}"
    
    return {'file_version': file_version}