# main.py
from flask import Blueprint, render_template, redirect, url_for, abort, request, flash, jsonify
from flask_login import login_required
from collections import defaultdict
from datetime import datetime, timedelta
from sqlalchemy.orm import aliased, joinedload
from sqlalchemy import or_, func
from app.models import Schedule, Match, Notification, Team, Player, Announcement
from app.decorators import role_required, handle_db_operation, query_operation
from app.utils.user_helpers import safe_current_user
from app.forms import OnboardingForm, soccer_positions, pronoun_choices, availability_choices, willing_to_referee_choices
import logging
import subprocess
import requests
import os

logger = logging.getLogger(__name__)

main = Blueprint('main', __name__)

PROJECT_DIR = "/app"  # This will be inside the Docker container
VERSION_FILE = os.path.join(PROJECT_DIR, "version.txt")
LATEST_VERSION_URL = "https://raw.githubusercontent.com/geman220/ECS-Discord-Bot/master/Discord-Bot-WebUI/version.txt"

@query_operation
def fetch_announcements():
    """Fetch the latest 5 announcements."""
    return Announcement.query.order_by(Announcement.position.asc()).limit(5).all()

@query_operation
def get_onboarding_form(player=None, formdata=None):

    # Initialize the OnboardingForm with formdata and the player object
    onboarding_form = OnboardingForm(formdata=formdata, obj=player)

    # Fetch distinct jersey sizes from the database
    distinct_jersey_sizes = Player.query.with_entities(Player.jersey_size).distinct().all()
    jersey_size_choices = [(size[0], size[0]) for size in distinct_jersey_sizes if size[0]]

    # Populate choices dynamically if necessary
    onboarding_form.jersey_size.choices = jersey_size_choices or [('', 'Select a size')]
    onboarding_form.pronouns.choices = pronoun_choices or [('', 'Select pronouns')]
    onboarding_form.expected_weeks_available.choices = availability_choices or [('', 'Select availability')]
    onboarding_form.favorite_position.choices = soccer_positions or [('', 'Select position')]
    onboarding_form.other_positions.choices = soccer_positions
    onboarding_form.positions_not_to_play.choices = soccer_positions
    onboarding_form.willing_to_referee.choices = willing_to_referee_choices

    # Pre-populate multi-select fields if player data is available
    if player and not formdata:
        # Only pre-populate if the formdata is not provided
        if player.other_positions:
            onboarding_form.other_positions.data = [pos.strip() for pos in player.other_positions.strip('{}').split(',')]
        else:
            onboarding_form.other_positions.data = []

        if player.positions_not_to_play:
            onboarding_form.positions_not_to_play.data = [pos.strip() for pos in player.positions_not_to_play.strip('{}').split(',')]
        else:
            onboarding_form.positions_not_to_play.data = []

        # Pre-populate the email field from the User model (since it's no longer in the Player model)
        if player.user:
            onboarding_form.email.data = player.user.email  # Populate email from the User model

    elif not player:
        # If no player data, ensure multi-select fields are empty
        onboarding_form.other_positions.data = []
        onboarding_form.positions_not_to_play.data = []

    return onboarding_form

@handle_db_operation()
def create_player_profile(onboarding_form):
    """Create a new player profile for the current user using form data."""
    try:
        # Extract file handling to a separate function
        @query_operation
        def handle_profile_picture():
            if not onboarding_form.profile_picture.data:
                return None
                
            from werkzeug.utils import secure_filename
            import os
            
            filename = secure_filename(onboarding_form.profile_picture.data.filename)
            upload_folder = 'static/uploads'  # Adjust based on your configuration
            
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
                
            upload_path = os.path.join(upload_folder, filename)
            onboarding_form.profile_picture.data.save(upload_path)
            return url_for('static', filename='uploads/' + filename)

        # Process multi-select values
        other_positions = request.form.getlist('other_positions')
        positions_not_to_play = request.form.getlist('positions_not_to_play')
        
        logger.debug(
            f"Processing positions - Other: {other_positions}, "
            f"Not to Play: {positions_not_to_play}"
        )

        # Handle profile picture
        profile_picture_url = handle_profile_picture()

        # Create player instance
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
            team_id=None,
            league_id=None,
            is_current_player=True
        )

        # Add the new player and update user
        db.session.add(player)
        
        # Update the user's onboarding status
        safe_current_user.has_completed_onboarding = True
        safe_current_user.player = player

        logger.info(f"Created player profile for user {safe_current_user.id}")
        flash('Player profile created successfully.', 'success')
        
        return player

    except Exception as e:
        logger.error(f"Error creating profile for user {safe_current_user.id}: {e}")
        raise

@handle_db_operation()
def handle_profile_update(player, onboarding_form):
    """Handle the update of the player profile."""
    try:
        # Assign single-select and string fields directly
        player.name = onboarding_form.name.data
        player.phone = onboarding_form.phone.data
        player.jersey_size = onboarding_form.jersey_size.data
        player.jersey_number = onboarding_form.jersey_number.data
        player.pronouns = onboarding_form.pronouns.data
        player.favorite_position = onboarding_form.favorite_position.data
        player.expected_weeks_available = onboarding_form.expected_weeks_available.data
        player.unavailable_dates = onboarding_form.unavailable_dates.data

        # Serialize multi-select fields
        player.other_positions = "{" + ",".join(onboarding_form.other_positions.data) + "}" if onboarding_form.other_positions.data else None
        player.positions_not_to_play = "{" + ",".join(onboarding_form.positions_not_to_play.data) + "}" if onboarding_form.positions_not_to_play.data else None

        # Assign other fields
        player.willing_to_referee = onboarding_form.willing_to_referee.data
        player.frequency_play_goal = onboarding_form.frequency_play_goal.data
        player.player_notes = onboarding_form.player_notes.data
        player.team_swap = onboarding_form.team_swap.data
        player.additional_info = onboarding_form.additional_info.data

        # Assign settings fields (notifications, visibility)
        safe_current_user.email_notifications = onboarding_form.email_notifications.data
        safe_current_user.sms_notifications = onboarding_form.sms_notifications.data
        safe_current_user.discord_notifications = onboarding_form.discord_notifications.data
        safe_current_user.profile_visibility = onboarding_form.profile_visibility.data

        # Update the email from the onboarding form to the User model
        safe_current_user.email = onboarding_form.email.data

        # Handle profile picture upload if necessary
        if onboarding_form.profile_picture.data:
            from werkzeug.utils import secure_filename
            import os
            filename = secure_filename(onboarding_form.profile_picture.data.filename)
            upload_folder = 'static/uploads'  # Adjust based on your configuration
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            upload_path = os.path.join(upload_folder, filename)
            onboarding_form.profile_picture.data.save(upload_path)
            player.profile_picture_url = url_for('static', filename='uploads/' + filename)

        # Mark onboarding as complete
        safe_current_user.has_completed_onboarding = True

        # Optional: Flash a success message
        flash('Profile updated successfully.', 'success')
        logger.info(f"User {safe_current_user.id} updated their profile successfully.")
    except Exception as e:
        logger.error(f"Error updating profile for user {safe_current_user.id}: {e}")
        flash('An error occurred while updating your profile. Please try again.', 'danger')
        raise  # Reraise the exception for the decorator to handle rollback

def fetch_upcoming_matches(
    team, 
    match_limit=4, 
    include_past_matches=False, 
    start_date=None, 
    end_date=None, 
    order='asc', 
    specific_day=None, 
    per_day_limit=None
):
    grouped_matches = defaultdict(list)
    today = datetime.now().date()

    if team:
        # Define default date range if not provided
        if not start_date:
            if include_past_matches:
                # For past matches: fetch the last 4 weeks
                start_date = today - timedelta(weeks=4)
            else:
                # For upcoming matches: from today onwards
                start_date = today
        if not end_date:
            if include_past_matches:
                # For past matches: up to yesterday
                end_date = today - timedelta(days=1)
            else:
                # For upcoming matches: next 4 weeks
                end_date = today + timedelta(weeks=4)

        # Define ordering
        if order == 'asc':
            order_by = [Match.date.asc(), Match.time.asc()]
        else:
            order_by = [Match.date.desc(), Match.time.desc()]

        # Base query with eager loading
        query = (
            Match.query.options(
                joinedload(Match.home_team).joinedload(Team.players),
                joinedload(Match.away_team).joinedload(Team.players)
            )
            .filter(
                or_(
                    Match.home_team_id == team.id,
                    Match.away_team_id == team.id
                ),
                Match.date >= start_date,
                Match.date <= end_date
            )
            .order_by(*order_by)
        )
        
        # Apply specific day filter if provided
        if specific_day is not None:
            # Note: Adjust 'dow' extraction based on your DB's representation
            # PostgreSQL: 0=Sunday, 6=Saturday
            query = query.filter(func.extract('dow', Match.date) == specific_day)
        
        # Fetch all relevant matches
        matches = query.all()
        
        if specific_day is not None and per_day_limit is not None:
            # Enforce per-day limit
            day_count = defaultdict(int)  # Tracks count per date

            for match in matches:
                match_date = match.date
                if day_count[match_date] < per_day_limit:
                    grouped_matches[match_date].append({
                        'match': match,
                        'home_team_name': match.home_team.name,
                        'opponent_name': match.away_team.name,
                        'home_team_id': match.home_team_id,
                        'opponent_team_id': match.away_team_id,
                        'home_players': [{'id': player.id, 'name': player.name} for player in match.home_team.players],
                        'opponent_players': [{'id': player.id, 'name': player.name} for player in match.away_team.players]
                    })
                    day_count[match_date] += 1
                # Continue until all matches are processed; no global limit
        else:
            # Apply match limit if specified
            if match_limit:
                matches = matches[:match_limit]
            
            # Group matches by date
            for match in matches:
                grouped_matches[match.date].append({
                    'match': match,
                    'home_team_name': match.home_team.name,
                    'opponent_name': match.away_team.name,
                    'home_team_id': match.home_team_id,
                    'opponent_team_id': match.away_team_id,
                    'home_players': [{'id': player.id, 'name': player.name} for player in match.home_team.players],
                    'opponent_players': [{'id': player.id, 'name': player.name} for player in match.away_team.players]
                })
    
    return grouped_matches

# Home
@main.route('/', methods=['GET', 'POST'])
@login_required
def index():
    from app.forms import ReportMatchForm
    current_year = datetime.now().year

    # Attempt to get the player profile associated with the current user
    player = getattr(safe_current_user, 'player', None)

    if player:
        # Eagerly load team and league relationships
        player = Player.query.options(
            joinedload(Player.team).joinedload(Team.league)
        ).filter_by(id=player.id).first()
    else:
        player = None

    # Initialize the combined onboarding form with formdata if POST
    onboarding_form = get_onboarding_form(player, formdata=request.form if request.method == 'POST' else None)

    # Initialize ReportMatchForm
    report_form = ReportMatchForm()
    matches = Match.query.options(
        joinedload(Match.home_team),
        joinedload(Match.away_team)
    ).all()
    # Determine if onboarding should be shown
    show_onboarding = False
    if player:
        show_onboarding = not safe_current_user.has_completed_onboarding
    else:
        show_onboarding = not safe_current_user.has_skipped_profile_creation

    # Determine if the tour should be shown
    show_tour = safe_current_user.has_completed_onboarding and not safe_current_user.has_completed_tour

    if request.method == 'POST':
        form_action = request.form.get('form_action', '')
        logger.debug(f"Form Action: {form_action}")
        logger.debug(f"Form Data: {request.form}")

        if form_action in ['create_profile', 'update_profile']:
            # Handle profile creation or update
            logger.debug(f"Attempting to {'create' if not player else 'update'} a player profile for user {safe_current_user.id}")

            if onboarding_form.validate_on_submit():
                if not player:
                    # Create a new player profile
                    player = create_player_profile(onboarding_form)
                    if player:
                        safe_current_user.has_skipped_profile_creation = False
                else:
                    # Update the existing player profile
                    handle_profile_update(player, onboarding_form)

                if player:
                    # Only proceed if player is successfully created or updated
                    safe_current_user.has_completed_onboarding = True  # Mark onboarding as complete

                    logger.debug(f"Player profile {'created' if not player else 'updated'} and onboarding completed for user {safe_current_user.id}")
                    flash('Player profile created or updated successfully!', 'success')
                    return redirect(url_for('main.index'))
            else:
                flash('Form validation failed. Please check the form inputs.', 'danger')
                logger.debug(onboarding_form.errors)  # Log validation errors for debugging

        elif form_action == 'skip_profile':
            # Handle skipping profile creation
            logger.debug(f"Handling 'skip_profile' action for user {safe_current_user.id}")
            safe_current_user.has_skipped_profile_creation = True
            show_onboarding = False  # Do not show onboarding anymore
            flash('You have chosen to skip profile creation for now.', 'info')
            return redirect(url_for('main.index'))

        elif form_action == 'reset_skip_profile':
            # Handle resetting the skip flag to allow onboarding again
            logger.debug(f"Handling 'reset_skip_profile' action for user {safe_current_user.id}")
            safe_current_user.has_skipped_profile_creation = False
            show_onboarding = True  # Reopen the onboarding modal
            flash('Onboarding has been reset. Please complete the onboarding process.', 'info')
            return redirect(url_for('main.index'))

    # Fetch the user's team and matches, if applicable
    user_team = player.team if player else None

    today = datetime.now().date()
    two_weeks_later = today + timedelta(weeks=2)
    one_week_ago = today - timedelta(weeks=1)
    yesterday = today - timedelta(days=1)

    # **Fetch Next Matches**:
    # Requirements:
    # - Next 2 weeks (4 matches total)
    # - 2 matches per Sunday

    # Determine the day number for Sunday based on PostgreSQL (0=Sunday)
    sunday_dow = 0  # Adjust if using different DB; PostgreSQL uses 0=Sunday

    next_matches = fetch_upcoming_matches(
        team=user_team,
        start_date=today,
        end_date=two_weeks_later,
        specific_day=sunday_dow,
        per_day_limit=2,
        order='asc'
    )

    # **Fetch Previous Matches**:
    # Requirements:
    # - Last week's 2 matches

    previous_matches = fetch_upcoming_matches(
        team=user_team,
        start_date=one_week_ago,
        end_date=yesterday,
        match_limit=2,
        include_past_matches=True,
        order='desc'  # Latest past matches first
    )

    # Fetch announcements to be displayed
    announcements = fetch_announcements()

    # Prepare player choices for each match
    player_choices_per_match = {}

    # Process Next Matches
    for date_key, matches in next_matches.items():
        for match_data in matches:
            match = match_data['match']
            home_team_id = match_data['home_team_id']
            opponent_team_id = match_data['opponent_team_id']

            # Get team names
            home_team_name = match_data['home_team_name']
            opponent_team_name = match_data['opponent_name']

            # Set attributes on the match object
            setattr(match, 'home_team_id', home_team_id)
            setattr(match, 'away_team_id', opponent_team_id)
            setattr(match, 'home_team_name', home_team_name)
            setattr(match, 'away_team_name', opponent_team_name)

            # Fetch players from both teams
            players = Player.query.filter(Player.team_id.in_([home_team_id, opponent_team_id])).all()

            # Structure the players by team using team names
            player_choices_per_match[match.id] = {
                home_team_name: {player.id: player.name for player in players if player.team_id == home_team_id},
                opponent_team_name: {player.id: player.name for player in players if player.team_id == opponent_team_id}
            }

    # Process Previous Matches
    for date_key, matches in previous_matches.items():
        for match_data in matches:
            match = match_data['match']
            home_team_id = match_data['home_team_id']
            opponent_team_id = match_data['opponent_team_id']

            # Get team names
            home_team_name = match_data['home_team_name']
            opponent_team_name = match_data['opponent_name']

            # Set attributes on the match object
            setattr(match, 'home_team_id', home_team_id)
            setattr(match, 'away_team_id', opponent_team_id)
            setattr(match, 'home_team_name', home_team_name)
            setattr(match, 'away_team_name', opponent_team_name)

            # Fetch players from both teams
            players = Player.query.filter(Player.team_id.in_([home_team_id, opponent_team_id])).all()

            # Structure the players by team using team names
            player_choices_per_match[match.id] = {
                home_team_name: {player.id: player.name for player in players if player.team_id == home_team_id},
                opponent_team_name: {player.id: player.name for player in players if player.team_id == opponent_team_id}
            }

    # Render the main page with all context variables
    return render_template(
        'index.html',
        report_form=report_form,  # Pass report_form
        matches=matches,
        onboarding_form=onboarding_form,
        user_team=user_team,
        next_matches=next_matches,  # Use next_matches
        previous_matches=previous_matches,  # Use previous_matches
        current_year=current_year,
        team=user_team,  # Pass the team object for identification
        player=player,
        is_linked_to_discord=player.discord_id is not None if player else False,
        discord_server_link="https://discord.gg/weareecs",
        show_onboarding=show_onboarding,
        show_tour=show_tour,
        announcements=announcements,
        player_choices=player_choices_per_match
    )

# Notification Routes
@main.route('/notifications', methods=['GET'])
@login_required
@query_operation
def notifications():
    notifications = safe_current_user.notifications.order_by(Notification.created_at.desc()).all()
    return render_template('notifications.html', notifications=notifications)

@main.route('/notifications/mark_as_read/<int:notification_id>', methods=['POST'])
@login_required
@handle_db_operation()
def mark_as_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    
    if notification.user_id != safe_current_user.id:
        abort(403)

    try:
        notification.read = True
        flash('Notification marked as read.', 'success')
    except Exception as e:
        logger.error(f"Error marking notification {notification_id} as read: {str(e)}")
        flash('An error occurred. Please try again.', 'danger')
        raise  # Reraise exception for the decorator to handle

    return redirect(url_for('main.notifications'))

@main.route('/set_tour_skipped', methods=['POST'])
@login_required
@handle_db_operation()
def set_tour_skipped():
    try:
        safe_current_user.has_completed_tour = False
        logger.info(f"User {safe_current_user.id} set tour as skipped.")
    except Exception as e:
        logger.error(f"Error setting tour skipped for user {safe_current_user.id}: {str(e)}")
        return jsonify({'error': 'An error occurred while updating tour status'}), 500
        raise  # Reraise exception for the decorator to handle
    
    return '', 204

@main.route('/set_tour_complete', methods=['POST'])
@login_required
@handle_db_operation()
def set_tour_complete():
    try:
        safe_current_user.has_completed_tour = True
        logger.info(f"User {safe_current_user.id} completed the tour.")
    except Exception as e:
        logger.error(f"Error setting tour complete for user {safe_current_user.id}: {str(e)}")
        return jsonify({'error': 'An error occurred while updating tour status'}), 500
        raise  # Reraise exception for the decorator to handle
    
    return '', 204

@main.route('/version', methods=['GET'])
def get_version():
    """Returns the current version of the application."""
    with open(VERSION_FILE, 'r') as f:
        version = f.read().strip()
    return jsonify({"version": version})

# Helper function to get the latest version from GitHub
def get_latest_version():
    response = requests.get(LATEST_VERSION_URL)
    if response.status_code == 200:
        return response.text.strip()
    return None

# Route to check if an update is available
@main.route('/check-update', methods=['GET'])
@login_required
@role_required('Global Admin')
def check_for_update():
    """Check if a new version is available by comparing the current version with the latest version on GitHub."""
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

# Route to update the application
@main.route('/update', methods=['POST'])
@login_required
@role_required('Global Admin')
def update_application():
    """Triggers the update script on the host machine."""
    if not request.is_json or request.json.get('confirm') != 'yes':
        return jsonify({"success": False, "message": "Confirmation required"}), 400
    
    try:
        # Run the script on the host machine
        result = subprocess.run(["/path/to/update_app.sh"], check=True, capture_output=True, text=True)
        return jsonify({"success": True, "message": "Update initiated", "output": result.stdout})

    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "message": str(e)}), 500
