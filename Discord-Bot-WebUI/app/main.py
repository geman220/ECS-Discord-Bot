# main.py
from flask import Blueprint, render_template, redirect, url_for, abort, request, flash
from flask_login import login_required, current_user
from datetime import datetime
from sqlalchemy.orm import aliased
from app import db
from app.models import Schedule, Match, Notification, Team, Player, Announcement
from collections import defaultdict
from sqlalchemy.orm import joinedload
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

main = Blueprint('main', __name__)

def fetch_announcements():
    """Fetch the latest 5 announcements."""
    return Announcement.query.order_by(Announcement.position.asc()).limit(5).all()

def get_onboarding_form(player=None, formdata=None):
    from app.forms import OnboardingForm, soccer_positions, pronoun_choices, availability_choices, willing_to_referee_choices

    # Initialize the OnboardingForm with formdata and the player object
    onboarding_form = OnboardingForm(formdata=formdata, obj=player)

    # Fetch distinct jersey sizes from the database
    distinct_jersey_sizes = db.session.query(Player.jersey_size).distinct().all()
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
    elif not player:
        # If no player data, ensure multi-select fields are empty
        onboarding_form.other_positions.data = []
        onboarding_form.positions_not_to_play.data = []

    return onboarding_form

def create_player_profile(onboarding_form):
    """Create a new player profile for the current user using form data."""
    try:
        # Directly capture the multi-select values from the form submission
        other_positions = request.form.getlist('other_positions')
        positions_not_to_play = request.form.getlist('positions_not_to_play')

        # Log the captured values for debugging
        logger.debug(f"Directly captured Other Positions: {other_positions}, Positions Not to Play: {positions_not_to_play}")

        # Ensure other_positions and positions_not_to_play are lists
        if isinstance(other_positions, str):
            other_positions = [other_positions]
        if isinstance(positions_not_to_play, str):
            positions_not_to_play = [positions_not_to_play]

        # Create a new Player instance and populate it with form data
        player = Player(
            user_id=current_user.id,
            name=onboarding_form.name.data,
            email=onboarding_form.email.data,
            phone=onboarding_form.phone.data,
            jersey_size=onboarding_form.jersey_size.data,
            jersey_number=onboarding_form.jersey_number.data,
            profile_picture_url=None,  # Handle file upload separately
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
            is_coach=False,  # Set based on your logic
            discord_id=None,  # Handle Discord linking separately
            needs_manual_review=False,
            linked_primary_player_id=None,
            order_id=None,
            team_id=None,
            league_id=None,
            is_current_player=True
        )

        # Handle file upload if necessary
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

        # Add the new player to the session and commit to save it to the database
        db.session.add(player)
        db.session.commit()

        # Link the player profile to the current user in the session
        current_user.player = player
        current_user.has_completed_onboarding = True  # Mark onboarding as complete
        db.session.commit()

        # Flash a success message
        flash('Player profile created successfully.', 'success')
        logger.info(f"New player profile created for user {current_user.id}")

        return player  # Return the new player object if needed

    except Exception as e:
        db.session.rollback()
        flash('An error occurred while creating your profile. Please try again.', 'danger')
        logger.error(f"Error creating profile for user {current_user.id}: {e}")
        return None

def handle_profile_update(player, onboarding_form):
    """Handle the update of the player profile."""
    try:
        # Assign single-select and string fields directly
        player.name = onboarding_form.name.data
        player.email = onboarding_form.email.data
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

        # Assign settings fields
        current_user.email_notifications = onboarding_form.email_notifications.data
        current_user.sms_notifications = onboarding_form.sms_notifications.data
        current_user.discord_notifications = onboarding_form.discord_notifications.data
        current_user.profile_visibility = onboarding_form.profile_visibility.data

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
        current_user.has_completed_onboarding = True

        # Commit the changes to the database
        db.session.commit()

        # Optional: Flash a success message
        flash('Profile updated successfully.', 'success')
        logger.info(f"User {current_user.id} updated their profile successfully.")
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while updating your profile. Please try again.', 'danger')
        logger.error(f"Error updating profile for user {current_user.id}: {e}")

def fetch_upcoming_matches(team,  match_limit=4):
    """Fetch and return upcoming matches for the specified team."""
    grouped_matches = defaultdict(list)
    
    if team:
        # Use joinedload to load the home_team and away_team relationships
        matches = (
            Match.query.options(
                joinedload(Match.home_team),
                joinedload(Match.away_team)
            )
            .filter((Match.home_team_id == team.id) | (Match.away_team_id == team.id))
            .filter(Match.date >= datetime.now().date())
            .order_by(Match.date.asc(), Match.time.asc())
            .limit(match_limit)
            .all()
        )
        
        for match in matches:
            # No need to manually create dictionaries, pass the `Match` objects
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

# Home Route
@main.route('/', methods=['GET', 'POST'])
@login_required
def index():
    from app.forms import ReportMatchForm
    current_year = datetime.now().year

    # Attempt to get the player profile associated with the current user
    player = getattr(current_user, 'player', None)

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
        show_onboarding = not current_user.has_completed_onboarding
    else:
        show_onboarding = not current_user.has_skipped_profile_creation

    # Determine if the tour should be shown
    show_tour = current_user.has_completed_onboarding and not current_user.has_completed_tour

    if request.method == 'POST':
        form_action = request.form.get('form_action', '')
        logger.debug(f"Form Action: {form_action}")
        logger.debug(f"Form Data: {request.form}")

        if form_action in ['create_profile', 'update_profile']:
            # Handle profile creation or update
            logger.debug(f"Attempting to {'create' if not player else 'update'} a player profile for user {current_user.id}")

            if onboarding_form.validate_on_submit():
                if not player:
                    # Create a new player profile
                    player = create_player_profile(onboarding_form)
                    if player:
                        current_user.has_skipped_profile_creation = False
                else:
                    # Update the existing player profile
                    handle_profile_update(player, onboarding_form)

                if player:
                    # Only proceed if player is successfully created or updated
                    current_user.has_completed_onboarding = True  # Mark onboarding as complete
                    db.session.commit()

                    logger.debug(f"Player profile {'created' if not player else 'updated'} and onboarding completed for user {current_user.id}")
                    flash('Player profile created or updated successfully!', 'success')
                    return redirect(url_for('main.index'))
            else:
                flash('Form validation failed. Please check the form inputs.', 'danger')
                logger.debug(onboarding_form.errors)  # Log validation errors for debugging

        elif form_action == 'skip_profile':
            # Handle skipping profile creation
            logger.debug(f"Handling 'skip_profile' action for user {current_user.id}")
            current_user.has_skipped_profile_creation = True
            db.session.commit()
            show_onboarding = False  # Do not show onboarding anymore
            flash('You have chosen to skip profile creation for now.', 'info')
            return redirect(url_for('main.index'))

        elif form_action == 'reset_skip_profile':
            # Handle resetting the skip flag to allow onboarding again
            logger.debug(f"Handling 'reset_skip_profile' action for user {current_user.id}")
            current_user.has_skipped_profile_creation = False
            db.session.commit()
            show_onboarding = True  # Reopen the onboarding modal
            flash('Onboarding has been reset. Please complete the onboarding process.', 'info')
            return redirect(url_for('main.index'))

    # Fetch the user's team and upcoming matches, if applicable
    user_team = player.team if player else None
    grouped_matches = fetch_upcoming_matches(user_team)

    # Fetch announcements to be displayed
    announcements = fetch_announcements()

    # Prepare player choices for each match
    player_choices_per_match = {}
    for date, matches in grouped_matches.items():
        for match_data in matches:
            match = match_data['match']
            home_team_id = match_data['home_team_id']
            opponent_team_id = match_data['opponent_team_id']
        
            # Fetch players from both teams
            players = Player.query.filter(Player.team_id.in_([home_team_id, opponent_team_id])).all()
        
            # Get team names
            home_team_name = Team.query.get(home_team_id).name
            opponent_team_name = Team.query.get(opponent_team_id).name
        
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
        grouped_matches=grouped_matches,
        current_year=current_year,
        player=player,
        is_linked_to_discord=player.discord_id is not None if player else False,
        discord_server_link="https://discord.gg/weareecs",
        show_onboarding=show_onboarding,
        show_tour=show_tour,  # Corrected to use the variable
        announcements=announcements,
        player_choices=player_choices_per_match
    )

# Notification Routes
@main.route('/notifications', methods=['GET'])
@login_required
def notifications():
    notifications = current_user.notifications.order_by(Notification.created_at.desc()).all()
    return render_template('notifications.html', notifications=notifications)

@main.route('/notifications/mark_as_read/<int:notification_id>', methods=['POST'])
@login_required
def mark_as_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id != current_user.id:
        abort(403)
    notification.read = True
    db.session.commit()
    return redirect(url_for('main.notifications'))

@main.route('/set_tour_skipped', methods=['POST'])
@login_required
def set_tour_skipped():
    current_user.has_completed_tour = False
    db.session.commit()
    return '', 204  # No content response

@main.route('/set_tour_complete', methods=['POST'])
@login_required
def set_tour_complete():
    current_user.has_completed_tour = True
    db.session.commit()
    return '', 204  # No content response