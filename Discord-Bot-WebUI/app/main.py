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
from collections import defaultdict
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for, abort, request, flash,
    jsonify, g
)
from flask_login import login_required
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, func, text
from werkzeug.utils import secure_filename

from app.models import (
    Match, Notification, Team, Player, Announcement, player_teams
)
from app.decorators import role_required
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

    if not teams:
        return grouped_matches

    team_ids = [t.id for t in teams]
    if not start_date:
        start_date = today - timedelta(weeks=4) if include_past_matches else today
    if not end_date:
        end_date = today - timedelta(days=1) if include_past_matches else today + timedelta(weeks=4)

    order_by = [Match.date.asc(), Match.time.asc()] if order == 'asc' else [Match.date.desc(), Match.time.desc()]

    query = (
        session.query(Match)
        .options(
            joinedload(Match.home_team).joinedload(Team.players),
            joinedload(Match.away_team).joinedload(Team.players)
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

    if specific_day is not None:
        query = query.filter(func.extract('dow', Match.date) == specific_day)

    matches = query.all()

    if specific_day is not None and per_day_limit is not None:
        day_count = defaultdict(int)
        for match in matches:
            match_date = match.date
            if day_count[match_date] < per_day_limit:
                grouped_matches[match_date].append(_build_match_dict(match))
                day_count[match_date] += 1
    else:
        if match_limit:
            matches = matches[:match_limit]
        for match in matches:
            grouped_matches[match.date].append(_build_match_dict(match))

    return grouped_matches


def _build_match_dict(match):
    """
    Build a dictionary of match details.

    Parameters:
        match (Match): The match object.

    Returns:
        dict: A dictionary containing match and team details.
    """
    return {
        'match': match,
        'home_team_name': match.home_team.name,
        'opponent_name': match.away_team.name,
        'home_team_id': match.home_team_id,
        'opponent_team_id': match.away_team_id,
        'home_players': [{'id': p.id, 'name': p.name} for p in match.home_team.players],
        'opponent_players': [{'id': p.id, 'name': p.name} for p in match.away_team.players]
    }


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
        if player:
            player = (
                session.query(Player)
                .options(joinedload(Player.teams).joinedload(Team.league))
                .filter_by(id=player.id)
                .first()
            )
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

        show_onboarding = (
            not safe_current_user.has_completed_onboarding if player
            else not safe_current_user.has_skipped_profile_creation
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

                        if player:
                            safe_current_user.has_completed_onboarding = True
                            session.add(safe_current_user)
                            session.flush()
                            session.execute(
                                text("UPDATE users SET has_completed_onboarding = true WHERE id = :user_id"),
                                {"user_id": safe_current_user.id}
                            )
                            session.commit()
                            session.refresh(safe_current_user)
                            logger.info(f"Verified has_completed_onboarding after update: {safe_current_user.has_completed_onboarding}")
                            result = session.execute(
                                text("SELECT has_completed_onboarding FROM users WHERE id = :user_id"),
                                {"user_id": safe_current_user.id}
                            ).fetchone()
                            logger.info(f"Direct query verification: has_completed_onboarding = {result[0]}")
                        flash('Profile updated successfully!', 'success')
                        return redirect(url_for('main.index'))

                    except Exception as e:
                        session.rollback()
                        logger.error(f"Error in profile creation/update: {str(e)}", exc_info=True)
                        flash('An error occurred while saving your profile. Please try again.', 'danger')
                        return redirect(url_for('main.index'))
                else:
                    logger.warning(f"Form validation failed: {onboarding_form.errors}")
                    flash('Form validation failed. Please check the form inputs.', 'danger')

            elif form_action == 'reset_skip_profile':
                try:
                    with session.begin():
                        safe_current_user.has_skipped_profile_creation = False
                        session.add(safe_current_user)
                    flash('Onboarding has been reset. Please complete the onboarding process.', 'info')
                    return redirect(url_for('main.index'))
                except Exception as e:
                    logger.error(f"Error resetting profile: {str(e)}", exc_info=True)
                    flash('An error occurred. Please try again.', 'danger')
                    return redirect(url_for('main.index'))

        user_teams = player.teams if player else []
        today = datetime.now().date()
        two_weeks_later = today + timedelta(weeks=2)
        one_week_ago = today - timedelta(weeks=1)
        yesterday = today - timedelta(days=1)
        sunday_dow = 0

        next_matches = fetch_upcoming_matches(
            teams=user_teams,
            start_date=today,
            end_date=two_weeks_later,
            specific_day=sunday_dow,
            per_day_limit=2,
            order='asc'
        )

        previous_matches = fetch_upcoming_matches(
            teams=user_teams,
            start_date=one_week_ago,
            end_date=yesterday,
            match_limit=2,
            include_past_matches=True,
            order='desc'
        )

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

        return render_template(
            'index.html',
            report_form=report_form,
            matches=matches,
            onboarding_form=onboarding_form,
            user_team=user_teams,
            next_matches=next_matches,
            previous_matches=previous_matches,
            current_year=current_year,
            team=user_teams,
            player=player,
            is_linked_to_discord=(player.discord_id is not None if player else False),
            discord_server_link="https://discord.gg/weareecs",
            show_onboarding=show_onboarding,
            show_tour=show_tour,
            announcements=announcements,
            player_choices=player_choices_per_match
        )

    except Exception as e:
        logger.error(f"Unexpected error in index route: {str(e)}", exc_info=True)
        flash('An unexpected error occurred. Please try again.', 'danger')
        return redirect(url_for('main.index'))


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
    try:
        notification.read = True
        session.add(notification)
        flash('Notification marked as read.', 'success')
    except Exception as e:
        logger.error(f"Error marking notification {notification_id} as read: {str(e)}")
        flash('An error occurred. Please try again.', 'danger')
        raise
    return redirect(url_for('main.notifications'))


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