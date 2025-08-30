# app/players.py

"""
Players Module

This module handles all routes and functionality related to player management.
It includes endpoints for viewing, creating, updating, and deleting players,
as well as profile management, stat updates, and Discord notifications.
"""

import logging

from flask import (
    current_app, Blueprint, render_template, redirect, url_for,
    request, abort, jsonify, g
)
from app.alert_helpers import show_success, show_error, show_warning, show_info
from flask_login import login_required
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import SQLAlchemyError
import requests
from werkzeug.exceptions import Forbidden
from celery.result import AsyncResult
from datetime import datetime, timedelta

# Local application imports
from app.models import (
    Player, Team, League, Season, PlayerSeasonStats, PlayerCareerStats,
    User, Notification, Role, PlayerStatAudit, Match,
    PlayerEvent, user_roles, PlayerTeamSeason
)
from app.core import db, celery
from app.decorators import role_required, admin_or_owner_required
from app.routes import get_current_season_and_year
from app.forms import (
    PlayerProfileForm, SeasonStatsForm, CareerStatsForm, CreatePlayerForm,
    EditPlayerForm, soccer_positions, goal_frequency_choices, availability_choices
)
from app.utils.user_helpers import safe_current_user
from app.players_helpers import save_cropped_profile_picture, create_user_for_player
from app.player_management_helpers import create_player_profile, record_order_history
from app.stat_helpers import decrement_player_stats
from app.profile_helpers import (
    handle_coach_status_update, handle_ref_status_update, handle_profile_update,
    handle_season_stats_update, handle_career_stats_update, handle_add_stat_manually,
    handle_admin_notes_update
)
from app.tasks.player_sync import sync_players_with_woocommerce
from app.utils.sync_data_manager import get_sync_data, delete_sync_data


logger = logging.getLogger(__name__)
players_bp = Blueprint('players', __name__)


@players_bp.errorhandler(Forbidden)
def handle_forbidden_error(error):
    """
    Handle Forbidden errors by flashing a warning and redirecting the user.
    """
    show_warning("You don't have the necessary permissions to perform that action.")
    return redirect(request.referrer or url_for('players.view_players')), 403


@players_bp.route('/', endpoint='view_players', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def view_players():
    """
    Redirect to the consolidated user management page.
    """
    return redirect(url_for('user_management.manage_users'))


@players_bp.route('/update', endpoint='update_players', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_players():
    """
    Redirect to the consolidated user management WooCommerce sync.
    """
    return redirect(url_for('user_management.update_players'), code=307)


@players_bp.route('/confirm_update', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def confirm_update():
    """
    Redirect to the consolidated user management confirm update.
    """
    return redirect(url_for('user_management.confirm_update'), code=307)


@players_bp.route('/update_status/<task_id>', methods=['GET'])
@login_required
def update_status(task_id):
    """
    Redirect to the consolidated user management update status.
    """
    return redirect(url_for('user_management.update_status', task_id=task_id))


@players_bp.route('/create_player', endpoint='create_player', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def create_player():
    """
    Create a new player (and associated user if needed) using submitted form data.
    """
    session = g.db_session
    form = CreatePlayerForm()

    logger.debug("Entered create_player route")
    logger.debug(
        f"Form data: name={request.form.get('name')} "
        f"email={request.form.get('email')} "
        f"phone={request.form.get('phone')} "
        f"jersey_size={request.form.get('jersey_size')} "
        f"league_id={request.form.get('league_id')}"
    )

    # Populate the form manually from request data
    form.name.data = request.form.get('name')
    form.email.data = request.form.get('email')
    form.phone.data = request.form.get('phone')
    form.jersey_size.data = request.form.get('jersey_size')
    form.league_id.data = request.form.get('league_id')

    # Set choices for leagues and jersey sizes
    leagues = session.query(League).all()
    distinct_jersey_sizes = session.query(Player.jersey_size).distinct().all()
    jersey_sizes = sorted(set(size[0] for size in distinct_jersey_sizes if size[0]))
    form.jersey_size.choices = [(size, size) for size in jersey_sizes]
    form.league_id.choices = [(str(league.id), league.name) for league in leagues]

    if not form.validate():
        show_error('Form validation failed. Please check your inputs.')
        logger.debug("Form validation failed.")
        return redirect(url_for('players.view_players'))

    try:
        # Gather and clean player data from the form
        player_data = {
            'name': form.name.data.strip(),
            'email': form.email.data.lower().strip(),
            'phone': form.phone.data.strip(),
            'jersey_size': form.jersey_size.data,
        }
        league_id = form.league_id.data
        league = session.query(League).get(league_id)

        logger.debug(f"Attempting to create user from player_data={player_data}")
        user = create_user_for_player(player_data, session=session)
        logger.debug(f"User created: {user!r} (id: {getattr(user, 'id', None)})")

        logger.debug("Attempting to create player profile.")
        player = create_player_profile(player_data, league, user, session=session)
        logger.debug(f"Player profile created: {player!r} (id: {getattr(player, 'id', None)})")

        session.commit()
        logger.debug("session.commit() succeeded.")

        show_success('Player created or updated successfully.')
        return redirect(url_for('players.view_players'))
    except SQLAlchemyError as e:
        logger.error("SQLAlchemyError creating/updating player", exc_info=True)
        session.rollback()
        show_error('An error occurred while creating or updating the player. Please try again.')
        return redirect(url_for('players.view_players'))
    except Exception as e:
        logger.exception("Unexpected error creating/updating player")
        session.rollback()
        show_error('An unexpected error occurred. Please contact support.')
        return redirect(url_for('players.view_players'))


@players_bp.route('/player/<int:player_id>/team_history')
@login_required
def get_player_team_history(player_id):
    """
    Retrieve and display the team history for a given player.
    """
    session = g.db_session
    try:
        history = session.query(
            PlayerTeamSeason, Team, Season
        ).join(
            Team, PlayerTeamSeason.team_id == Team.id
        ).join(
            Season, PlayerTeamSeason.season_id == Season.id
        ).filter(
            PlayerTeamSeason.player_id == player_id
        ).order_by(
            Season.name.desc()
        ).all()
        
        return render_template('_team_history.html', title='Team History', team_history=history)
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching team history: {str(e)}")
        return "Error loading team history", 500


@players_bp.route('/profile/<int:player_id>', endpoint='player_profile', methods=['GET', 'POST'])
@login_required
def player_profile(player_id):
    """
    Display and update a player's profile.
    Handles both GET (display) and POST (update) requests.
    
    Access Control:
    - Own profile: Always accessible for editing
    - Other profiles: Requires 'view_all_player_profiles' permission
    - Global Admin: Always has full access
    """
    session = g.db_session
    logger.info(f"Accessing profile for player_id: {player_id} by user_id: {safe_current_user.id}")

    # Load player with all needed relationships using the main session
    from sqlalchemy.orm import selectinload
    from app.models import PlayerEvent, PlayerTeamSeason
    player = session.query(Player).options(
        selectinload(Player.teams),
        selectinload(Player.user),
        selectinload(Player.career_stats),
        selectinload(Player.season_stats),
        selectinload(Player.events).selectinload(PlayerEvent.match)
    ).get(player_id)

    if not player:
        abort(404)
    
    # Get current season teams for the player (filter by Pub League)
    current_season = session.query(Season).filter_by(is_current=True, league_type='Pub League').first()
    current_season_teams = []
    if current_season:
        # Query teams through PlayerTeamSeason for current season only
        current_season_teams = session.query(Team).join(
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
        
    # Check access permissions
    from app.role_impersonation import is_impersonation_active, get_effective_roles, has_effective_permission
    
    if is_impersonation_active():
        user_roles = get_effective_roles()
        can_view_all_profiles = has_effective_permission('view_all_player_profiles')
    else:
        user = session.merge(safe_current_user)
        user_roles = [role.name for role in user.roles]
        can_view_all_profiles = safe_current_user.has_permission('view_all_player_profiles')
    
    # Check if user can access this profile
    is_own_profile = (safe_current_user.id == player.user_id)
    is_global_admin = 'Global Admin' in user_roles
    
    # Players can view basic profile info of others, but coaches/admins can view full profiles
    can_view_basic_profile = True  # Everyone can see basic profile info
    
    # Only deny access if no authentication
    if not safe_current_user.is_authenticated:
        show_error('Please log in to view player profiles.')
        session.commit()
        return redirect(url_for('auth.login'))

    try:
        events = list(player.events)
        matches = list({event.match for event in events})
        user = player.user

        # Use the current season from the database instead of calculating from date
        season = current_season
        if not season:
            show_error('Current Pub League season not found.')
            session.commit()
            return redirect(url_for('main.index'))

        matches = session.query(Match).join(PlayerEvent).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.events)
        ).filter(PlayerEvent.player_id == player_id).all()

        jersey_sizes = session.query(Player.jersey_size).distinct().all()
        jersey_size_choices = [(size[0], size[0]) for size in jersey_sizes if size[0]]

        classic_league = session.query(League).filter_by(name='Classic').first()
        if not classic_league:
            show_error('Classic division not found')
            session.commit()
            return redirect(url_for('players.player_profile', player_id=player.id))

        season_stats = session.query(PlayerSeasonStats).filter_by(
            player_id=player_id,
            season_id=season.id
        ).first()
        if not season_stats:
            season_stats = PlayerSeasonStats(player_id=player_id, season_id=season.id)
            session.add(season_stats)

        if not player.career_stats:
            new_career_stats = PlayerCareerStats(player_id=player.id)
            player.career_stats = [new_career_stats]
            session.add(new_career_stats)

        is_classic_league_player = player.league_id == classic_league.id
        is_player = is_own_profile  # Use the permission check we already did
        
        # Determine what the user can see/edit based on permissions
        impersonation_active = is_impersonation_active()
        logger.info(f"Player profile {player_id}: Impersonation active: {impersonation_active}")
        
        if impersonation_active:
            logger.info(f"  Using has_effective_permission() for permissions")
            can_edit_stats = has_effective_permission('edit_player_stats')
            can_view_contact_info = has_effective_permission('view_player_contact_info')
            can_view_admin_notes = has_effective_permission('view_player_admin_notes')
            can_edit_admin_notes = has_effective_permission('edit_player_admin_notes')
            can_edit_any_profile = has_effective_permission('edit_any_player_profile')
            can_edit_own_profile = has_effective_permission('edit_own_profile')
        else:
            logger.info(f"  Using safe_current_user.has_permission() for permissions")
            can_edit_stats = safe_current_user.has_permission('edit_player_stats')
            can_view_contact_info = safe_current_user.has_permission('view_player_contact_info')
            can_view_admin_notes = safe_current_user.has_permission('view_player_admin_notes')
            can_edit_admin_notes = safe_current_user.has_permission('edit_player_admin_notes')
            can_edit_any_profile = safe_current_user.has_permission('edit_any_player_profile')
            can_edit_own_profile = safe_current_user.has_permission('edit_own_profile')
        
        # Debug logging for admin notes permissions
        logger.info(f"Player profile {player_id}: User {safe_current_user.id if safe_current_user else 'None'}")
        logger.info(f"  can_view_admin_notes: {can_view_admin_notes}")
        logger.info(f"  can_edit_admin_notes: {can_edit_admin_notes}")
        logger.info(f"  User roles: {[role.name for role in safe_current_user.roles] if safe_current_user else []}")
        
        # Check the specific permission lookups
        if impersonation_active:
            logger.info(f"  has_effective_permission('view_player_admin_notes'): {has_effective_permission('view_player_admin_notes')}")
            logger.info(f"  has_effective_permission('edit_player_admin_notes'): {has_effective_permission('edit_player_admin_notes')}")
        else:
            logger.info(f"  safe_current_user.has_permission('view_player_admin_notes'): {safe_current_user.has_permission('view_player_admin_notes')}")
            logger.info(f"  safe_current_user.has_permission('edit_player_admin_notes'): {safe_current_user.has_permission('edit_player_admin_notes')}")
        
        # Special case: Allow viewing own contact info even without permission
        can_view_contact_info = can_view_contact_info or is_own_profile
        
        # Determine if user can edit this profile
        can_edit_profile = is_global_admin or (is_own_profile and can_edit_own_profile) or can_edit_any_profile
        
        is_admin = any(role in ['Pub League Admin', 'Global Admin'] for role in user_roles)

        form = PlayerProfileForm(obj=player)
        form.jersey_size.choices = jersey_size_choices
        
        # Only initialize form data with current values on GET requests
        # On POST requests, we want to preserve the submitted form data
        if request.method == 'GET':
            form.email.data = user.email
            form.other_positions.data = (
                player.other_positions.strip('{}').split(',')
                if player.other_positions else []
            )
            form.positions_not_to_play.data = (
                player.positions_not_to_play.strip('{}').split(',')
                if player.positions_not_to_play else []
            )

            if is_classic_league_player and hasattr(form, 'team_swap'):
                form.team_swap.data = player.team_swap

        season_stats_form = SeasonStatsForm(obj=season_stats) if can_edit_stats else None
        career_stats_form = (CareerStatsForm(obj=player.career_stats[0])
                             if can_edit_stats and player.career_stats else None)

        if request.method == 'POST':
            if can_edit_stats and 'update_coach_status' in request.form:
                return handle_coach_status_update(player, user)
            elif can_edit_stats and 'update_ref_status' in request.form:
                return handle_ref_status_update(player, user)
            elif form.validate_on_submit() and 'update_profile' in request.form:
                if can_edit_profile:
                    return handle_profile_update(form, player, user)
                else:
                    show_error('You do not have permission to update this profile.')
                    return redirect(url_for('players.player_profile', player_id=player.id))
            elif form.validate_on_submit() and 'update_admin_notes' in request.form:
                if can_edit_admin_notes:
                    return handle_admin_notes_update(player, form)
                else:
                    show_error('You do not have permission to update admin notes.')
                    return redirect(url_for('players.player_profile', player_id=player.id))
            elif can_edit_stats and season_stats_form and season_stats_form.validate_on_submit() and 'update_season_stats' in request.form:
                return handle_season_stats_update(player, season_stats_form, season.id)
            elif can_edit_stats and career_stats_form and career_stats_form.validate_on_submit() and 'update_career_stats' in request.form:
                return handle_career_stats_update(player, career_stats_form)
            elif can_edit_stats and 'add_stat_manually' in request.form:
                return handle_add_stat_manually(player)

        audit_logs = session.query(PlayerStatAudit).filter_by(
            player_id=player_id
        ).order_by(PlayerStatAudit.timestamp.desc()).all()

        # Check if profile verification has expired (older than 5 months)
        profile_expired = False
        if player.profile_last_updated:
            five_months_ago = datetime.utcnow() - timedelta(days=150)  # Approximately 5 months
            profile_expired = player.profile_last_updated < five_months_ago

        # Determine if user can view draft history (admins only)
        can_view_draft_history = is_admin
        
        # Get draft history for admins
        draft_history = {}
        if can_view_draft_history:
            from app.models import DraftOrderHistory
            draft_picks = session.query(DraftOrderHistory).filter_by(
                player_id=player_id
            ).join(Season).join(League).order_by(
                Season.name.desc(), DraftOrderHistory.draft_position
            ).all()
            
            # Group draft picks by season for easier lookup
            for pick in draft_picks:
                season_key = f"{pick.season.name}_league_{pick.league.id}"
                draft_history[season_key] = pick.draft_position

        # Commit the session before rendering the template to avoid holding
        # the transaction open during template rendering, which can be slow
        # and cause idle-in-transaction timeouts
        session.commit()
        
        return render_template(
            'player_profile.html',
            title='Player Profile',
            player=player,
            user=user,
            matches=matches,
            events=events,
            season=season,
            is_admin=is_admin,
            is_player=is_player,
            is_own_profile=is_own_profile,
            is_classic_league_player=is_classic_league_player,
            form=form,
            season_stats_form=season_stats_form,
            career_stats_form=career_stats_form,
            audit_logs=audit_logs,
            team_history=player.season_assignments,
            current_season_teams=current_season_teams,
            draft_history=draft_history,
            # Permission-based access variables
            can_edit_stats=can_edit_stats,
            can_view_contact_info=can_view_contact_info,
            can_view_admin_notes=can_view_admin_notes,
            can_edit_admin_notes=can_edit_admin_notes,
            can_edit_profile=can_edit_profile,
            can_view_draft_history=can_view_draft_history,
            profile_expired=profile_expired
        )
    except Exception as e:
        logger.error(f"Error in player_profile: {str(e)}", exc_info=True)
        show_error('An error occurred while loading the profile.')
        return redirect(url_for('main.index'))


@players_bp.route('/add_stat_manually/<int:player_id>', endpoint='add_stat_manually', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def add_stat_manually_route(player_id):
    """
    Allow an admin to add a player's stat manually.
    """
    session = g.db_session
    player = session.query(Player).get_or_404(player_id)

    try:
        new_stat_data = {
            'match_id': request.form.get('match_id'),
            'goals': int(request.form.get('goals', 0)),
            'assists': int(request.form.get('assists', 0)),
            'yellow_cards': int(request.form.get('yellow_cards', 0)),
            'red_cards': int(request.form.get('red_cards', 0)),
        }
        player.add_stat_manually(new_stat_data, user_id=safe_current_user.id)
        show_success('Stat added successfully.')
    except ValueError as e:
        show_error('Invalid input values provided.')
        raise

    return redirect(url_for('players.player_profile', player_id=player_id))



@players_bp.route('/profile/<int:player_id>/mobile', endpoint='mobile_profile_update', methods=['GET', 'POST'])
@login_required
def mobile_profile_update(player_id):
    """
    Mobile-optimized profile update page for registration events.
    """
    session = g.db_session
    player = session.query(Player).get(player_id)
    if not player:
        abort(404)
    
    # Check if user can edit this profile
    is_own_profile = (safe_current_user.id == player.user_id)
    if not is_own_profile:
        show_error('You can only update your own profile.')
        return redirect(url_for('players.player_profile', player_id=player_id))
    
    user = player.user
    
    # Build jersey size choices from existing data
    jersey_sizes = session.query(Player.jersey_size).distinct().all()
    jersey_size_choices = [(size[0], size[0]) for size in jersey_sizes if size[0]]
    
    form = PlayerProfileForm(obj=player)
    form.jersey_size.choices = jersey_size_choices
    
    # Handle profile verification
    if request.method == 'POST' and 'verify_profile' in request.form:
        try:
            from app.profile_helpers import handle_profile_verification_mobile
            return handle_profile_verification_mobile(player)
        except Exception as e:
            logger.exception(f"Error verifying profile for player {player_id}: {str(e)}")
            show_error('Error verifying profile.')
            return redirect(url_for('players.mobile_profile_update', player_id=player_id))
    
    # Handle profile update
    if form.validate_on_submit() and 'update_profile' in request.form:
        try:
            from app.profile_helpers import handle_profile_update_mobile
            return handle_profile_update_mobile(form, player, user)
        except Exception as e:
            logger.exception(f"Error updating profile for player {player_id}: {str(e)}")
            show_error('Error updating profile.')
            return redirect(url_for('players.mobile_profile_update', player_id=player_id))
    
    # Initialize form data on GET
    if request.method == 'GET':
        form.email.data = user.email
        form.other_positions.data = (
            player.other_positions.strip('{}').split(',')
            if player.other_positions else []
        )
        form.positions_not_to_play.data = (
            player.positions_not_to_play.strip('{}').split(',')
            if player.positions_not_to_play else []
        )
    
    # Check if profile is expired
    profile_expired = False
    if player.profile_last_updated:
        five_months_ago = datetime.utcnow() - timedelta(days=150)
        profile_expired = player.profile_last_updated < five_months_ago
    
    session.commit()
    
    return render_template(
        'player_profile_mobile.html',
        title='Update Your Profile',
        player=player,
        user=user,
        form=form,
        profile_expired=profile_expired
    )


@players_bp.route('/profile/<int:player_id>/desktop', endpoint='desktop_profile_update', methods=['GET', 'POST'])
@login_required
def desktop_profile_update(player_id):
    """
    Desktop-optimized profile update page.
    """
    session = g.db_session
    player = session.query(Player).get(player_id)
    if not player:
        abort(404)
    
    # Check if user can edit this profile
    is_own_profile = (safe_current_user.id == player.user_id)
    if not is_own_profile:
        show_error('You can only update your own profile.')
        return redirect(url_for('players.player_profile', player_id=player_id))
    
    user = player.user
    
    # Build jersey size choices from existing data
    jersey_sizes = session.query(Player.jersey_size).distinct().all()
    jersey_size_choices = [(size[0], size[0]) for size in jersey_sizes if size[0]]
    
    form = PlayerProfileForm(obj=player)
    form.jersey_size.choices = jersey_size_choices
    
    # Handle profile verification
    if request.method == 'POST' and 'verify_profile' in request.form:
        try:
            from app.profile_helpers import handle_profile_verification_mobile
            return handle_profile_verification_mobile(player)
        except Exception as e:
            logger.exception(f"Error verifying profile for player {player_id}: {str(e)}")
            show_error('Error verifying profile.')
            return redirect(url_for('players.desktop_profile_update', player_id=player_id))
    
    # Handle profile update
    if form.validate_on_submit() and 'update_profile' in request.form:
        try:
            from app.profile_helpers import handle_profile_update_mobile
            return handle_profile_update_mobile(form, player, user)
        except Exception as e:
            logger.exception(f"Error updating profile for player {player_id}: {str(e)}")
            show_error('Error updating profile.')
            return redirect(url_for('players.desktop_profile_update', player_id=player_id))
    
    # Initialize form data on GET
    if request.method == 'GET':
        form.email.data = user.email
        form.other_positions.data = (
            player.other_positions.strip('{}').split(',')
            if player.other_positions else []
        )
        form.positions_not_to_play.data = (
            player.positions_not_to_play.strip('{}').split(',')
            if player.positions_not_to_play else []
        )
    
    # Check if profile is expired
    profile_expired = False
    if player.profile_last_updated:
        five_months_ago = datetime.utcnow() - timedelta(days=150)
        profile_expired = player.profile_last_updated < five_months_ago
    
    session.commit()
    
    return render_template(
        'player_profile_desktop.html',
        title='Update Your Profile',
        player=player,
        user=user,
        form=form,
        profile_expired=profile_expired
    )


@players_bp.route('/profile/<int:player_id>/mobile/success', endpoint='mobile_profile_success', methods=['GET'])
@login_required
def mobile_profile_success(player_id):
    """
    Success confirmation page for mobile profile updates.
    Shows a clear confirmation that players can show to registration staff.
    """
    session = g.db_session
    player = session.query(Player).get(player_id)
    if not player:
        abort(404)
    
    # Check if user can view this success page
    is_own_profile = (safe_current_user.id == player.user_id)
    if not is_own_profile:
        show_error('You can only view your own profile confirmation.')
        return redirect(url_for('players.player_profile', player_id=player_id))
    
    action_type = request.args.get('action', 'updated')  # 'updated' or 'verified'
    
    session.commit()
    
    return render_template(
        'player_profile_mobile_success.html',
        title='Profile Complete!',
        player=player,
        action_type=action_type
    )


@players_bp.route('/profile/<int:player_id>/verify', endpoint='verify_profile', methods=['POST'])
@login_required
def verify_profile(player_id):
    """
    Verify a player's profile without making changes.
    Updates the profile_last_updated timestamp to mark the profile as current.
    Only the profile owner can verify their own profile.
    """
    session = g.db_session
    player = session.query(Player).get(player_id)
    if not player:
        abort(404)
    
    # Check if user can verify this profile (only their own)
    is_own_profile = (safe_current_user.id == player.user_id)
    if not is_own_profile:
        show_error('You can only verify your own profile.')
        return redirect(url_for('players.player_profile', player_id=player_id))
    
    try:
        from app.profile_helpers import handle_profile_verification
        return handle_profile_verification(player)
    except Exception as e:
        logger.exception(f"Error verifying profile for player {player_id}: {str(e)}")
        show_error('Error verifying profile.')
        return redirect(url_for('players.player_profile', player_id=player_id))


@players_bp.route('/api/player_profile/<int:player_id>', endpoint='api_player_profile', methods=['GET'])
@login_required
def api_player_profile(player_id):
    """
    Return a JSON representation of a player's profile data.
    """
    session = g.db_session
    player = session.query(Player).get(player_id)
    if not player:
        abort(404)
        
    def get_friendly_value(value, choices):
        return dict(choices).get(value, value)

    profile_data = {
        'profile_picture_url': player.profile_picture_url,
        'name': player.name,
        'goals': player.get_career_goals(),
        'assists': player.get_career_assists(),
        'yellow_cards': player.get_career_yellow_cards(),
        'red_cards': player.get_career_red_cards(),
        'player_notes': player.player_notes,
        'admin_notes': getattr(player, 'notes', None),
        'favorite_position': get_friendly_value(player.favorite_position, soccer_positions),
        'other_positions': player.other_positions.strip('{}').replace(',', ', ') if player.other_positions else None,
        'goal_frequency': get_friendly_value(player.frequency_play_goal, goal_frequency_choices),
        'positions_to_avoid': player.positions_not_to_play.strip('{}').replace(',', ', ') if player.positions_not_to_play else None,
        'expected_availability': get_friendly_value(player.expected_weeks_available, availability_choices)
    }
    return jsonify(profile_data)


@players_bp.route('/admin/review', endpoint='admin_review', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def admin_review():
    """
    Display a review page for players needing manual review and notify admins.
    """
    session = g.db_session
    players_needing_review = session.query(Player).filter_by(needs_manual_review=True).all()
    admins = session.query(User).join(user_roles).join(Role).filter(
        Role.name.in_(['Pub League Admin', 'Global Admin'])
    ).all()

    for admin in admins:
        notification = Notification(
            user_id=admin.id,
            content=f"{len(players_needing_review)} player(s) need manual review.",
            notification_type='warning',
            icon='ti-alert-triangle'
        )
        session.add(notification)

    return render_template('admin_review.html', title='Admin Review', players=players_needing_review)


@players_bp.route('/create-profile', endpoint='create_profile', methods=['POST'])
@login_required
def create_profile():
    """
    Handle the creation of a player profile via form submission.
    """
    session = g.db_session
    form = PlayerProfileForm()
    if form.validate_on_submit():
        player = Player(
            user_id=safe_current_user.id,
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            jersey_size=form.jersey_size.data,
            jersey_number=form.jersey_number.data,
            pronouns=form.pronouns.data,
            expected_weeks_available=form.expected_weeks_available.data,
            unavailable_dates=form.unavailable_dates.data,
            willing_to_referee=form.willing_to_referee.data,
            favorite_position=form.favorite_position.data,
            other_positions="{" + ",".join(form.other_positions.data) + "}" if form.other_positions.data else None,
            positions_not_to_play="{" + ",".join(form.positions_not_to_play.data) + "}" if form.positions_not_to_play.data else None,
            frequency_play_goal=form.frequency_play_goal.data,
            additional_info=form.additional_info.data,
            player_notes=form.player_notes.data,
            team_swap=form.team_swap.data,
            team_id=form.team_id.data,
            league_id=form.league_id.data
        )
        session.add(player)
        show_success('Player profile created successfully!')
        return redirect(url_for('main.index'))

    show_error('Error creating player profile. Please check your inputs.')
    return redirect(url_for('main.index'))


@players_bp.route('/edit_match_stat/<int:stat_id>', endpoint='edit_match_stat', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_match_stat(stat_id):
    """
    Edit match stat details.
    GET returns the current stat values.
    POST updates the stat with provided data.
    """
    session = g.db_session
    if request.method == 'GET':
        match_stat = session.query(PlayerEvent).get(stat_id)
        if not match_stat:
            abort(404)
        return jsonify({
            'goals': match_stat.goals,
            'assists': match_stat.assists,
            'yellow_cards': match_stat.yellow_cards,
            'red_cards': match_stat.red_cards,
        })

    if request.method == 'POST':
        try:
            match_stat = session.query(PlayerEvent).get_or_404(stat_id)
            match_stat.goals = request.form.get('goals', 0)
            match_stat.assists = request.form.get('assists', 0)
            match_stat.yellow_cards = request.form.get('yellow_cards', 0)
            match_stat.red_cards = request.form.get('red_cards', 0)
            return jsonify({'success': True})
        except (SQLAlchemyError, ValueError) as e:
            current_app.logger.error(f"Error editing match stat {stat_id}: {str(e)}")
            return jsonify({'success': False}), 500


@players_bp.route('/remove_match_stat/<int:stat_id>', endpoint='remove_match_stat', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def remove_match_stat(stat_id):
    """
    Remove a match stat and adjust the player's overall stats accordingly.
    """
    session = g.db_session
    try:
        match_stat = session.query(PlayerEvent).get(stat_id)
        if not match_stat:
            abort(404)
        player_id = match_stat.player_id
        event_type = match_stat.event_type

        current_app.logger.info(f"Removing stat for Player ID: {player_id}, Event Type: {event_type}, Stat ID: {stat_id}")
        decrement_player_stats(player_id, event_type)
        session.delete(match_stat)
        current_app.logger.info(f"Successfully removed stat for Player ID: {player_id}, Stat ID: {stat_id}")
        return jsonify({'success': True})
    except SQLAlchemyError as e:
        current_app.logger.error(f"Error deleting match stat {stat_id}: {str(e)}")
        raise
    except Exception as e:
        current_app.logger.error(f"Unexpected error deleting match stat {stat_id}: {str(e)}")
        return jsonify({'success': False}), 500


@players_bp.route('/player/<int:player_id>/upload_profile_picture', methods=['POST'])
@login_required
@admin_or_owner_required
def upload_profile_picture(player_id):
    """
    Upload and update a player's profile picture.
    """
    session = g.db_session
    player = session.query(Player).get(player_id)
    if not player:
        abort(404)

    cropped_image_data = request.form.get('cropped_image_data')
    if not cropped_image_data:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message='No image data provided'), 400
        show_error('No image data provided.')
        return redirect(url_for('players.player_profile', player_id=player_id))

    try:
        image_url = save_cropped_profile_picture(cropped_image_data, player_id)
        player.profile_picture_url = image_url
        player.updated_at = datetime.utcnow()  # Update the timestamp to force a cache refresh
        session.add(player)
        session.commit()
        
        # Trigger image optimization asynchronously
        try:
            from app.image_cache_service import handle_player_image_update
            handle_player_image_update(player_id)
            logger.info(f"Queued image optimization for player {player_id}")
        except Exception as e:
            logger.warning(f"Failed to queue image optimization: {e}")
            # Don't fail the upload if optimization queue fails
        
        show_success('Profile picture updated successfully!')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=True, message='Profile picture updated!', image_url=image_url)
        return redirect(url_for('players.player_profile', player_id=player_id))
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message=str(e)), 500
        show_error(f'An error occurred while uploading the image: {str(e)}')
        raise


@players_bp.route('/delete_player/<int:player_id>', endpoint='delete_player', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_player(player_id):
    """
    Delete a player and the associated user account.
    """
    session = g.db_session
    try:
        player = session.query(Player).get(player_id)
        if not player:
            abort(404)
            
        # First, delete any temporary sub assignments connected to this player
        from app.models import TemporarySubAssignment
        temp_subs = session.query(TemporarySubAssignment).filter_by(player_id=player_id).all()
        for sub in temp_subs:
            session.delete(sub)
        session.flush()  # Ensure sub assignments are deleted first
            
        user = player.user
        session.delete(player)
        session.delete(user)
        session.commit()
        show_success('Player and user account deleted successfully.')
        return redirect(url_for('players.view_players'))
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.error(f"Error deleting player {player_id}: {str(e)}")
        show_error('An error occurred while deleting the player. Please try again.')
        return redirect(url_for('players.view_players'))


@players_bp.route('/edit_player/<int:player_id>', endpoint='edit_player', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_player(player_id):
    """
    Edit a player's information.
    """
    session = g.db_session
    player = session.query(Player).get(player_id)
    if not player:
        abort(404)
    form = EditPlayerForm(obj=player)

    if request.method == 'GET':
        return render_template('edit_player.html', title='Edit Player', form=form, player=player)

    if form.validate_on_submit():
        try:
            form.populate_obj(player)
            show_success('Player updated successfully.')
            return redirect(url_for('players.view_players'))
        except SQLAlchemyError as e:
            current_app.logger.error(f"Error updating player {player_id}: {str(e)}")
            show_error('An error occurred while updating the player. Please try again.')
            raise

    return render_template('edit_player.html', title='Edit Player', form=form, player=player)


@players_bp.route('/contact_player_discord/<int:player_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def contact_player_discord(player_id):
    """
    Send a Discord message to a player using the configured Discord bot.
    """
    message_text = request.form.get('discord_message')
    if not message_text:
         show_error("Message cannot be empty.")
         return redirect(url_for('players.player_profile', player_id=player_id))
    
    player = Player.query.get_or_404(player_id)
    
    if not player.discord_id:
         show_error("This player does not have a linked Discord account.")
         return redirect(url_for('players.player_profile', player_id=player_id))
    
    user = User.query.get(player.user_id)
    if not user.discord_notifications:
         show_error("The player has opted out of Discord notifications.")
         return redirect(url_for('players.player_profile', player_id=player_id))
    
    # Extract the data we need before making the external API call
    discord_id = player.discord_id
    
    # Commit the session before making the external API call to avoid
    # holding the database transaction open during the 10-second timeout
    g.db_session.commit()
    
    payload = {
        "message": message_text,
        "discord_id": discord_id
    }
    
    bot_api_url = current_app.config.get('BOT_API_URL', 'http://localhost:5001') + '/send_discord_dm'
    
    try:
        response = requests.post(bot_api_url, json=payload, timeout=10)
        if response.status_code == 200:
            show_success("Message sent successfully on Discord.")
        else:
            # Try to get detailed error information from the bot service
            try:
                error_data = response.json()
                error_detail = error_data.get('detail', 'Unknown error')
                
                # Provide user-friendly error messages based on status code
                if response.status_code == 403:
                    show_error(f"Cannot send Discord message: {error_detail}. The user likely has DMs disabled or has blocked the bot.")
                elif response.status_code == 404:
                    show_error(f"Discord user not found: {error_detail}. The player's Discord account may be invalid or deleted.")
                else:
                    show_error(f"Failed to send Discord message (Status {response.status_code}): {error_detail}")
            except ValueError:
                # Response is not JSON, use raw text
                show_error(f"Failed to send Discord message (Status {response.status_code}): {response.text[:200]}")
    except requests.exceptions.Timeout:
        show_error("Discord bot service timed out. Please try again later.")
    except requests.exceptions.ConnectionError:
        show_error("Cannot connect to Discord bot service. Please contact an administrator.")
    except Exception as e:
        show_error(f"Error contacting Discord bot: {str(e)}")
    
    return redirect(url_for('players.player_profile', player_id=player_id))


@players_bp.route('/profile/<int:player_id>/update_modal', endpoint='update_profile_modal', methods=['POST'])
@login_required
def update_profile_modal(player_id):
    """
    Update a player's profile data via the modal form and verify it.
    Only the profile owner can update their own profile.
    """
    session = g.db_session
    player = session.query(Player).get(player_id)
    if not player:
        return jsonify({'success': False, 'message': 'Player not found'}), 404
    
    # Check if user can update this profile (only their own)
    is_own_profile = (safe_current_user.id == player.user_id)
    if not is_own_profile:
        return jsonify({'success': False, 'message': 'You can only update your own profile'}), 403
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        # Update player fields
        if 'phone' in data:
            player.phone = data['phone']
        if 'pronouns' in data:
            player.pronouns = data['pronouns']
        if 'jersey_size' in data:
            player.jersey_size = data['jersey_size']
        if 'expected_weeks_available' in data:
            player.expected_weeks_available = data['expected_weeks_available']
        if 'unavailable_dates' in data:
            player.unavailable_dates = data['unavailable_dates']
        if 'willing_to_referee' in data:
            player.willing_to_referee = data['willing_to_referee']
        if 'team_swap' in data:
            player.team_swap = data['team_swap']
        if 'favorite_position' in data:
            player.favorite_position = data['favorite_position']
        if 'other_positions' in data:
            player.other_positions = data['other_positions']
        if 'positions_not_to_play' in data:
            player.positions_not_to_play = data['positions_not_to_play']
        if 'frequency_play_goal' in data:
            player.frequency_play_goal = data['frequency_play_goal']
        if 'additional_info' in data:
            player.additional_info = data['additional_info']
        if 'player_notes' in data:
            player.player_notes = data['player_notes']
        
        # Update profile verification timestamp
        player.profile_last_updated = datetime.utcnow()
        
        session.commit()
        
        logger.info(f"Profile updated and verified for player {player_id} by user {safe_current_user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Profile updated and verified successfully'
        })
        
    except Exception as e:
        session.rollback()
        logger.exception(f"Error updating profile for player {player_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'Error updating profile'}), 500