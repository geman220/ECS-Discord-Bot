# app/teams.py

"""
Teams Module

This module defines routes related to teams, including viewing team details,
an overview of teams, reporting match results, and displaying league standings.
It handles both current and historical player data and match reports.
"""

import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional
from werkzeug.utils import secure_filename

from flask import (
    Blueprint, render_template, redirect, url_for, request, jsonify, g,
    current_app
)
from app.alert_helpers import show_success, show_error, show_warning, show_info
from flask_login import login_required
from flask_wtf.csrf import validate_csrf, CSRFError
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import selectinload, joinedload
from PIL import Image
from io import BytesIO

from app.models import (
    Team, Player, League, Season, Match, Standings,
    PlayerEventType, PlayerEvent, PlayerTeamSeason, User,
    PlayerSeasonStats, player_teams
)
from app.models_ecs import is_ecs_fc_team
from app.ecs_fc_schedule import EcsFcScheduleManager, is_user_ecs_fc_coach
from app.forms import ReportMatchForm
from app.teams_helpers import populate_team_stats, update_standings, process_events, process_own_goals
from app.utils.user_helpers import safe_current_user
from app.decorators import role_required

logger = logging.getLogger(__name__)
teams_bp = Blueprint('teams', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _get_special_week_display_name(match):
    """
    Get the display name for special weeks where home_team_id == away_team_id.
    
    Args:
        match: Match object where home_team_id == away_team_id
        
    Returns:
        String display name for the special week
    """
    # Check if the match has a week_type attribute
    if hasattr(match, 'week_type'):
        week_type = match.week_type.upper()
        if week_type == 'FUN':
            return 'Fun Week!'
        elif week_type == 'TST':
            return 'The Soccer Tournament!'
        elif week_type == 'BYE':
            return 'BYE Week!'
        elif week_type == 'BONUS':
            return 'Bonus Week!'
    
    # Fallback: try to determine from team names (backward compatibility)
    if match.home_team and match.home_team.name:
        team_name = match.home_team.name.upper()
        if 'FUN' in team_name:
            return 'Fun Week!'
        elif 'TST' in team_name:
            return 'The Soccer Tournament!'
        elif 'BYE' in team_name:
            return 'BYE Week!'
        elif 'BONUS' in team_name:
            return 'Bonus Week!'
    
    # Final fallback
    return 'Special Week!'


def _is_playoff_placeholder_match(match, viewing_team_id):
    """
    Determine if a playoff match is still using placeholder teams.
    
    A match is considered a placeholder if the viewing team is playing against
    the same opponent multiple times in the same week (indicating placeholder usage).
    
    Args:
        match: Match object
        viewing_team_id: ID of the team viewing the match
        
    Returns:
        Boolean indicating if this is a placeholder match
    """
    try:
        # Import here to avoid circular imports
        from app.models import Match
        from flask import g
        
        # Get all matches for this team in the same week
        week_matches = g.db_session.query(Match).filter(
            Match.league_id == match.league_id,
            Match.week == match.week,
            Match.is_playoff_game == True,
            ((Match.home_team_id == viewing_team_id) | (Match.away_team_id == viewing_team_id))
        ).all()
        
        # If this team plays the same opponent multiple times in this playoff week,
        # it's likely using placeholder teams
        opponents = set()
        for week_match in week_matches:
            if week_match.home_team_id == viewing_team_id:
                opponents.add(week_match.away_team_id)
            else:
                opponents.add(week_match.home_team_id)
        
        # If there's only one unique opponent and multiple matches, it's a placeholder
        return len(opponents) == 1 and len(week_matches) > 1
        
    except Exception as e:
        # If we can't determine, assume it's a placeholder for safety
        return True


def get_opponent_display_name(match, team_id):
    """
    Get the opponent display name for a match from a specific team's perspective.
    Handles regular matches, special weeks, and playoff games.

    Args:
        match: Match object
        team_id: ID of the team viewing the match

    Returns:
        String display name for the opponent or special week
    """
    # Check if this is a placeholder match (home and away teams are the same)
    if match.home_team_id == match.away_team_id:
        # For playoff placeholders, show the round
        if hasattr(match, 'is_playoff_game') and match.is_playoff_game:
            playoff_round = getattr(match, 'playoff_round', 1)
            return f'Playoffs Round {playoff_round} - TBD'
        # For special weeks, get the special week display name
        return _get_special_week_display_name(match)

    # Regular match - return the opponent team name
    if match.home_team_id == team_id:
        return match.away_team.name if match.away_team else 'Unknown'
    else:
        return match.home_team.name if match.home_team else 'Unknown'

@teams_bp.route('/<int:team_id>', endpoint='team_details')
@login_required
def team_details(team_id):
    """
    Display details about a specific team, including current/historical players and matches.

    The view fetches the team along with its players, determines whether to show
    current players or historical players (based on season status), gathers matches,
    and prepares data for rendering the team details page.

    Args:
        team_id (int): The ID of the team to display.

    Returns:
        A rendered template for team details.
    """
    session = g.db_session

    # Load team along with its associated players using eager loading.
    team = (
        session.query(Team)
        .options(joinedload(Team.players))
        .get(team_id)
    )
    if not team:
        show_error('Team not found.')
        return redirect(url_for('teams.teams_overview'))

    league = session.query(League).get(team.league_id)
    season = league.season if league else None

    # Retrieve current players from the many-to-many relationship.
    current_players = team.players

    # Retrieve historical players from PlayerTeamSeason if a season exists.
    historical_players = []
    if season:
        historical_players = (
            session.query(Player)
            .join(PlayerTeamSeason, Player.id == PlayerTeamSeason.player_id)
            .filter(
                PlayerTeamSeason.team_id == team_id,
                PlayerTeamSeason.season_id == season.id
            )
            .all()
        )

    # Choose to display current players if available or if the season is current.
    players = current_players if current_players or (season and season.is_current) else historical_players
    
    # Check Discord status for players who have Discord IDs
    # Smart checking: longer intervals for players in server, shorter for those not in server
    now = datetime.utcnow()
    
    for player in players:
        if not player.discord_id:
            continue
            
        # Determine when to recheck based on current status
        should_check = False
        
        if not player.discord_last_checked:
            # Never checked before - always check
            should_check = True
            reason = "never checked"
        elif player.discord_in_server is True:
            # Player is in server - check every 30 days
            check_threshold = now - timedelta(days=30)
            should_check = player.discord_last_checked < check_threshold
            reason = "in server, 30 day recheck"
        elif player.discord_in_server is False:
            # Player is NOT in server - check every 24 hours
            check_threshold = now - timedelta(hours=24)
            should_check = player.discord_last_checked < check_threshold
            reason = "not in server, 24 hour recheck"
        else:
            # Status is unknown (null) - check every 7 days
            check_threshold = now - timedelta(days=7)
            should_check = player.discord_last_checked < check_threshold
            reason = "unknown status, 7 day recheck"
        
        if should_check:
            try:
                player.check_discord_status()
                session.add(player)  # Mark for update
                logger.info(f"Updated Discord status for player {player.name} (ID: {player.id}) - {reason}")
            except Exception as e:
                logger.error(f"Failed to check Discord status for player {player.name} (ID: {player.id}): {e}")
    
    # Commit any Discord status updates
    try:
        session.commit()
    except Exception as e:
        logger.error(f"Failed to commit Discord status updates: {e}")
        session.rollback()

    report_form = ReportMatchForm()

    # Extract league_id to avoid lazy loading issues
    league_id = league.id if league else None

    # Fetch matches for this team within the same league.
    # Include practice matches for all teams in the same league
    all_matches = []
    if league_id:
        all_matches = (
            session.query(Match)
            .options(
                selectinload(Match.home_team).joinedload(Team.players),
                selectinload(Match.away_team).joinedload(Team.players)
            )
            .filter(
                or_(
                    # Regular matches where this team is playing
                    and_(
                        ((Match.home_team_id == team_id) | (Match.away_team_id == team_id)),
                        ((Match.home_team.has(league_id=league_id)) | (Match.away_team.has(league_id=league_id)))
                    ),
                    # Practice sessions for all teams in the same league
                    and_(
                        Match.week_type == 'PRACTICE',
                        ((Match.home_team.has(league_id=league_id)) | (Match.away_team.has(league_id=league_id)))
                    )
                )
            )
            .order_by(Match.date.asc())
            .all()
        )

    # Build a schedule mapping dates to match details and gather player choices.
    schedule = defaultdict(list)
    player_choices = {}
    practice_dates_added = set()  # Track practice sessions already added

    for match in all_matches:
        home_team_name = match.home_team.name if match.home_team else 'Unknown'
        away_team_name = match.away_team.name if match.away_team else 'Unknown'

        # Load players differently for historical vs. current seasons.
        if season and not season.is_current:
            home_players = (
                session.query(Player)
                .join(PlayerTeamSeason)
                .filter(
                    PlayerTeamSeason.team_id == match.home_team_id,
                    PlayerTeamSeason.season_id == season.id
                )
                .all()
            )
            away_players = (
                session.query(Player)
                .join(PlayerTeamSeason)
                .filter(
                    PlayerTeamSeason.team_id == match.away_team_id,
                    PlayerTeamSeason.season_id == season.id
                )
                .all()
            )
            home_team_players = {p.id: p.name for p in home_players}
            away_team_players = {p.id: p.name for p in away_players}
        else:
            home_team_players = {p.id: p.name for p in match.home_team.players} if match.home_team else {}
            away_team_players = {p.id: p.name for p in match.away_team.players} if match.away_team else {}

        player_choices[match.id] = {
            home_team_name: home_team_players,
            away_team_name: away_team_players
        }

        # Determine scores for display.
        if match.home_team_id == team_id:
            your_team_score = match.home_team_score if match.home_team_score is not None else 'N/A'
            opponent_score = match.away_team_score if match.away_team_score is not None else 'N/A'
        else:
            your_team_score = match.away_team_score if match.away_team_score is not None else 'N/A'
            opponent_score = match.home_team_score if match.home_team_score is not None else 'N/A'

        # Determine match result (Win/Loss/Tie) if scores are available.
        if your_team_score != 'N/A' and opponent_score != 'N/A':
            if your_team_score > opponent_score:
                result_text = 'W'
                result_class = 'success'
            elif your_team_score < opponent_score:
                result_text = 'L'
                result_class = 'danger'
            else:
                result_text = 'T'
                result_class = 'warning'
        else:
            result_text = '-'
            result_class = 'secondary'

        display_score = f"{your_team_score} - {opponent_score}" if your_team_score != 'N/A' else '-'

        # Get opponent display name (handles both regular matches and special weeks)
        opponent_name = get_opponent_display_name(match, team_id)

        # Check if this is a practice session and if we've already added one for this date
        is_practice = getattr(match, 'week_type', 'REGULAR') == 'PRACTICE' or getattr(match, 'is_practice_game', False)
        practice_key = (match.date, 'PRACTICE') if is_practice else None
        
        # Skip duplicate practice sessions
        if is_practice and practice_key in practice_dates_added:
            continue
        
        # Mark this practice session as added
        if is_practice:
            practice_dates_added.add(practice_key)

        schedule[match.date].append({
            'id': match.id,
            'time': match.time,
            'location': match.location,
            'opponent_name': opponent_name,
            'home_team_name': home_team_name,
            'away_team_name': away_team_name,
            'home_team_id': match.home_team_id,
            'away_team_id': match.away_team_id,
            'your_team_score': your_team_score,
            'opponent_score': opponent_score,
            'result_class': result_class,
            'result_text': result_text,
            'display_score': display_score,
            'reported': match.reported,
            'week_type': getattr(match, 'week_type', 'REGULAR'),
            'is_special_week': getattr(match, 'is_special_week', False),
            'is_playoff_game': getattr(match, 'is_playoff_game', False),
        })

    # Determine the next match date for display.
    next_match_date = None
    next_match = None
    if schedule:
        today = datetime.today().date()
        match_dates = sorted(schedule.keys())
        for md in match_dates:
            if md >= today:
                next_match_date = md
                # Get the first match on this date
                if schedule[md]:
                    next_match = schedule[md][0]
                    next_match['date'] = md  # Add date to the match object
                break
        if not next_match_date:
            next_match_date = match_dates[-1]
            # Get the first match on the last date
            if schedule[next_match_date]:
                next_match = schedule[next_match_date][0]
                next_match['date'] = next_match_date  # Add date to the match object

    # Check permissions for template
    from app.role_impersonation import is_impersonation_active, has_effective_permission
    
    if is_impersonation_active():
        user_roles = [role.name for role in safe_current_user.roles] if hasattr(safe_current_user, 'roles') else []
        can_report_match = has_effective_permission('report_match')
        can_upload_kit = has_effective_permission('upload_team_kit')
        can_add_player = has_effective_permission('add_player')
        can_add_match = has_effective_permission('add_match')
        can_view_player_stats = has_effective_permission('view_player_goals_assists')
        can_view_player_cards = has_effective_permission('view_player_cards')
        can_view_game_results = has_effective_permission('view_game_results')
    else:
        user_roles = [role.name for role in safe_current_user.roles] if hasattr(safe_current_user, 'roles') else []
        can_report_match = safe_current_user.has_permission('report_match')
        can_upload_kit = safe_current_user.has_permission('upload_team_kit')
        can_add_player = safe_current_user.has_permission('add_player')
        can_add_match = safe_current_user.has_permission('add_match')
        can_view_player_stats = safe_current_user.has_permission('view_player_goals_assists')
        can_view_player_cards = safe_current_user.has_permission('view_player_cards')
        can_view_game_results = safe_current_user.has_permission('view_game_results')
    
    # Global Admin always has access
    is_global_admin = 'Global Admin' in user_roles
    
    # Check if this is an ECS FC team and if user can manage it
    is_ecs_fc = is_ecs_fc_team(team_id)
    can_manage_ecs_fc = False
    ecs_fc_matches = []
    
    if is_ecs_fc:
        # Check for role impersonation first, then fall back to real roles
        from app.role_impersonation import is_impersonation_active, get_effective_roles
        
        if is_impersonation_active():
            effective_roles = get_effective_roles()
        else:
            effective_roles = user_roles
        
        # Check if user has proper ECS FC permissions through roles
        can_manage_ecs_fc = (
            'Global Admin' in effective_roles or
            'Pub League Admin' in effective_roles or
            'ECS FC Coach' in effective_roles
        )
        
        # Don't allow if user is ONLY a player role (even if they have other roles)
        if effective_roles == ['pl-classic'] or effective_roles == ['pl-ecs-fc'] or effective_roles == ['pl-premier']:
            can_manage_ecs_fc = False
        
        # Get ECS FC matches for this team
        if can_manage_ecs_fc:
            ecs_fc_matches = EcsFcScheduleManager.get_team_matches(team_id, upcoming_only=False)
            
            # Add ECS FC matches to the main schedule
            for ecs_match in ecs_fc_matches:
                schedule[ecs_match.match_date].append({
                    'id': f'ecs_{ecs_match.id}',  # Prefix to distinguish from regular matches
                    'ecs_fc_match_id': ecs_match.id,  # Store the actual ECS FC match ID
                    'time': ecs_match.match_time,
                    'location': ecs_match.location,
                    'opponent_name': ecs_match.opponent_name,
                    'home_team_name': team.name if ecs_match.is_home_match else ecs_match.opponent_name,
                    'away_team_name': ecs_match.opponent_name if ecs_match.is_home_match else team.name,
                    'home_team_id': team_id if ecs_match.is_home_match else None,
                    'away_team_id': None if ecs_match.is_home_match else team_id,
                    'your_team_score': 'N/A',  # ECS FC matches don't have scores yet
                    'opponent_score': 'N/A',
                    'result_class': 'info',  # Use info class for ECS FC matches
                    'result_text': 'ECS FC',  # Show ECS FC badge instead of W/L/T
                    'display_score': 'ECS FC Match',
                    'reported': False,  # ECS FC matches use different reporting system
                    'is_ecs_fc': True,  # Flag to identify ECS FC matches in template
                    'field_name': ecs_match.field_name,
                    'notes': ecs_match.notes,
                    'status': ecs_match.status
                })

    return render_template(
        'team_details.html',
        report_form=report_form,
        team=team,
        league=league,
        season=season,
        players=players,
        schedule=schedule,
        safe_current_user=safe_current_user,
        next_match_date=next_match_date,
        next_match=next_match,
        player_choices=player_choices,
        can_report_match=can_report_match,
        can_upload_kit=can_upload_kit,
        can_add_player=can_add_player,
        # ECS FC specific context
        is_ecs_fc=is_ecs_fc,
        can_manage_ecs_fc=can_manage_ecs_fc,
        ecs_fc_matches=ecs_fc_matches,
        can_add_match=can_add_match,
        can_view_player_stats=can_view_player_stats,
        can_view_player_cards=can_view_player_cards,
        can_view_game_results=can_view_game_results,
        is_global_admin=is_global_admin
    )


@teams_bp.route('/', endpoint='teams_overview')
@login_required
def teams_overview():
    """
    Show an overview of teams for the current Pub League and/or ECS FC seasons.

    Retrieves the current seasons and then queries for teams associated with those seasons.
    """
    session = g.db_session

    # Retrieve current Pub League and ECS FC seasons.
    current_pub_season = (
        session.query(Season)
        .filter_by(is_current=True, league_type='Pub League')
        .first()
    )
    current_ecs_season = (
        session.query(Season)
        .filter_by(is_current=True, league_type='ECS FC')
        .first()
    )

    if not current_pub_season and not current_ecs_season:
        show_warning('No current season found for either Pub League or ECS FC.')
        return redirect(url_for('home.index'))

    # Build conditions based on which current seasons exist.
    conditions = []
    if current_pub_season:
        conditions.append(League.season_id == current_pub_season.id)
    if current_ecs_season:
        conditions.append(League.season_id == current_ecs_season.id)

    teams_query = (
        session.query(Team)
        .join(League, Team.league_id == League.id)
    )

    if len(conditions) == 1:
        teams_query = teams_query.filter(conditions[0])
    elif len(conditions) == 2:
        teams_query = teams_query.filter(or_(*conditions))

    teams = teams_query.order_by(Team.name).all()
    
    # Preload team stats to avoid N+1 queries
    from app.team_performance_helpers import preload_team_stats_for_request
    team_ids = [team.id for team in teams]
    preload_team_stats_for_request(team_ids)
    
    return render_template('teams_overview.html', title='Teams Overview', teams=teams)


@teams_bp.route('/report_match/<int:match_id>', endpoint='report_match', methods=['GET', 'POST'])
@login_required
def report_match(match_id):
    session = g.db_session
    logger.info(f"Starting report_match for Match ID: {match_id}")
    # Use efficient session manager for heavy match loading
    from app.utils.efficient_session_manager import EfficientQuery
    match = EfficientQuery.get_match_details(match_id)
    if not match:
        show_error('Match not found.')
        return redirect(url_for('teams.teams_overview'))
    
    # Check if user has permission to access this match
    from app.role_impersonation import is_impersonation_active, get_effective_roles
    
    current_user_obj = session.query(User).get(safe_current_user.id)
    current_user_player = None
    if current_user_obj.player:
        current_user_player = current_user_obj.player
    
    user_team_ids = []
    is_admin = current_user_obj.has_role('admin')
    is_assigned_referee = False
    is_global_admin = current_user_obj.has_role('Global Admin')
    is_pub_league_admin = current_user_obj.has_role('Pub League Admin')
    is_pub_league_ref = current_user_obj.has_role('Pub League Ref')
    
    if current_user_player:
        user_team_ids = [team.id for team in current_user_player.teams]
        if current_user_player.is_ref and match.ref_id == current_user_player.id:
            is_assigned_referee = True
    
    # Handle role impersonation
    if is_impersonation_active():
        user_roles = get_effective_roles()
        is_admin = any(role in ['Pub League Admin', 'Global Admin'] for role in user_roles)
        is_global_admin = 'Global Admin' in user_roles
        is_pub_league_admin = 'Pub League Admin' in user_roles
        is_pub_league_ref = 'Pub League Ref' in user_roles
        # For impersonation, we don't check is_assigned_referee since impersonated users 
        # don't have actual player records with referee assignments
    
    # Check if user has access to this match
    # Global Admin, Pub League Admin, and Pub League Ref can edit any match
    has_access = (is_admin or 
                  is_global_admin or 
                  is_pub_league_admin or 
                  is_pub_league_ref or
                  match.home_team_id in user_team_ids or 
                  match.away_team_id in user_team_ids or 
                  is_assigned_referee)
    
    if not has_access:
        show_error('You do not have permission to access this match.')
        return redirect(url_for('teams.teams_overview'))

    if request.method == 'GET':
        try:
            event_mapping = {
                PlayerEventType.GOAL: 'goal_scorers',
                PlayerEventType.ASSIST: 'assist_providers',
                PlayerEventType.YELLOW_CARD: 'yellow_cards',
                PlayerEventType.RED_CARD: 'red_cards'
            }

            # Ensure we have team names
            home_team_name = match.home_team.name if match.home_team else "Home Team"
            away_team_name = match.away_team.name if match.away_team else "Away Team"
            
            # Update match properties (for UI display purposes only)
            match.home_team_name = home_team_name
            match.away_team_name = away_team_name
            
            # Prepare team data with players
            home_team_data = {
                'name': home_team_name,
                'id': match.home_team_id,
                'players': []
            }
            
            away_team_data = {
                'name': away_team_name,
                'id': match.away_team_id,
                'players': []
            }
            
            # Add player data if available
            if match.home_team and match.home_team.players:
                home_team_data['players'] = [
                    {'id': player.id, 'name': player.name}
                    for player in match.home_team.players
                ]
            
            if match.away_team and match.away_team.players:
                away_team_data['players'] = [
                    {'id': player.id, 'name': player.name}
                    for player in match.away_team.players
                ]
            
            # Determine the user's team affiliations
            current_user_id = safe_current_user.id
            current_user = session.query(User).get(current_user_id)
            current_user_player = None
            if current_user.player:
                current_user_player = current_user.player
                
            # Determine which team the current user is affiliated with
            user_team_ids = []
            is_admin = current_user.has_role('admin')
            is_global_admin = current_user.has_role('Global Admin')
            is_pub_league_admin = current_user.has_role('Pub League Admin')
            is_pub_league_ref = current_user.has_role('Pub League Ref')
            
            if current_user_player:
                user_team_ids = [team.id for team in current_user_player.teams]
            
            # Check if user is the assigned referee for this match
            is_assigned_referee = False
            if current_user_player and current_user_player.is_ref and match.ref_id == current_user_player.id:
                is_assigned_referee = True
            
            # Handle role impersonation for verification permissions
            if is_impersonation_active():
                user_roles = get_effective_roles()
                is_admin = any(role in ['Pub League Admin', 'Global Admin'] for role in user_roles)
                is_global_admin = 'Global Admin' in user_roles
                is_pub_league_admin = 'Pub League Admin' in user_roles
                is_pub_league_ref = 'Pub League Ref' in user_roles
            
            # Determine if the user can verify for either team
            # Admins and refs can verify for any team
            admin_or_ref = is_admin or is_global_admin or is_pub_league_admin or is_pub_league_ref or is_assigned_referee
            
            # Regular users (coaches/players) can only verify for their own team
            can_verify_home = admin_or_ref or (match.home_team_id in user_team_ids)
            can_verify_away = admin_or_ref or (match.away_team_id in user_team_ids)
            
            data = {
                'goal_scorers': [],
                'assist_providers': [],
                'yellow_cards': [],
                'red_cards': [],
                'home_team_score': match.home_team_score or 0,
                'away_team_score': match.away_team_score or 0,
                'notes': match.notes or '',
                'home_team_name': home_team_name,
                'away_team_name': away_team_name,
                'home_team': home_team_data,
                'away_team': away_team_data,
                'reported': match.reported,
                'home_team_verified': match.home_team_verified,
                'away_team_verified': match.away_team_verified,
                'fully_verified': match.fully_verified,
                'home_verifier': (match.home_verifier.player.name if match.home_verifier and match.home_verifier.player 
                                 else match.home_verifier.username if match.home_verifier else None),
                'away_verifier': (match.away_verifier.player.name if match.away_verifier and match.away_verifier.player 
                                 else match.away_verifier.username if match.away_verifier else None),
                'home_team_verified_at': match.home_team_verified_at.isoformat() if match.home_team_verified_at else None,
                'away_team_verified_at': match.away_team_verified_at.isoformat() if match.away_team_verified_at else None,
                'can_verify_home': can_verify_home,
                'can_verify_away': can_verify_away,
                'user_team_ids': user_team_ids,
                'is_admin': is_admin,
                'version': match.version,
                'updated_at': match.updated_at.isoformat() if match.updated_at else None
            }

            for event_type, field_name in event_mapping.items():
                events = (
                    session.query(PlayerEvent)
                    .filter_by(match_id=match.id, event_type=event_type)
                    .all()
                )
                data[field_name] = [
                    {
                        'id': ev.id,
                        'player_id': ev.player_id,
                        'minute': ev.minute or ''
                    }
                    for ev in events
                ]
            
            # Get own goals separately since they don't have a player_id
            own_goals = (
                session.query(PlayerEvent)
                .filter_by(match_id=match.id, event_type=PlayerEventType.OWN_GOAL)
                .all()
            )
            data['own_goals'] = [
                {
                    'id': ev.id,
                    'team_id': ev.team_id,
                    'minute': ev.minute or ''
                }
                for ev in own_goals
            ]

            logger.debug(f"Returning match data: {data}")
            return jsonify(data), 200

        except Exception as e:
            logger.exception(f"Error fetching match data: {e}")
            return jsonify({'success': False, 'message': 'An error occurred.'}), 500

    elif request.method == 'POST':
        # COMPLETELY BYPASS CSRF for testing
        if not request.is_json:
            return jsonify({'success': False, 'message': 'Invalid content type.'}), 415

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received.'}), 400

        # Optimistic locking check to prevent concurrent modifications
        client_version = data.get('version')
        if client_version is not None and client_version != match.version:
            return jsonify({
                'success': False, 
                'message': 'This match was modified by another user. Please refresh and try again.',
                'error_type': 'version_conflict',
                'current_version': match.version,
                'client_version': client_version
            }), 409  # HTTP 409 Conflict

        old_home_score = match.home_team_score
        old_away_score = match.away_team_score

        try:
            match.home_team_score = int(data.get('home_team_score', old_home_score or 0))
            match.away_team_score = int(data.get('away_team_score', old_away_score or 0))
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid score values.'}), 400

        match.notes = data.get('notes', match.notes)

        # Process player events for the match
        process_events(session, match, data, PlayerEventType.GOAL, 'goals_to_add', 'goals_to_remove')
        process_events(session, match, data, PlayerEventType.ASSIST, 'assists_to_add', 'assists_to_remove')
        process_events(session, match, data, PlayerEventType.YELLOW_CARD, 'yellow_cards_to_add', 'yellow_cards_to_remove')
        process_events(session, match, data, PlayerEventType.RED_CARD, 'red_cards_to_add', 'red_cards_to_remove')
        
        # Process own goals for the match
        process_own_goals(session, match, data, 'own_goals_to_add', 'own_goals_to_remove')

        # Handle team verification
        current_user_id = safe_current_user.id
        current_user = session.query(User).get(current_user_id)
        
        # Get user's player and their team associations
        current_user_player = None
        if current_user.player:
            current_user_player = current_user.player
            
        user_team_ids = []
        is_admin = current_user.has_role('admin')
        is_global_admin = current_user.has_role('Global Admin')
        is_pub_league_admin = current_user.has_role('Pub League Admin')
        is_pub_league_ref = current_user.has_role('Pub League Ref')
        
        if current_user_player:
            user_team_ids = [team.id for team in current_user_player.teams]
            
        # Check if the user wants to verify for a team
        verify_home = data.get('verify_home_team', False)
        verify_away = data.get('verify_away_team', False)
        
        now = datetime.utcnow()
        
        # Handle team verification with proper permission checks
        # Admins and refs can verify for any team, regular users only for their own team
        admin_or_ref = is_admin or is_global_admin or is_pub_league_admin or is_pub_league_ref
        is_assigned_referee = current_user_player and current_user_player.is_ref and match.ref_id == current_user_player.id
        admin_or_ref = admin_or_ref or is_assigned_referee
        
        # Handle home team verification
        can_verify_home = admin_or_ref or (match.home_team_id in user_team_ids)
        if verify_home and can_verify_home:
            match.home_team_verified = True
            match.home_team_verified_by = current_user_id
            match.home_team_verified_at = now
            logger.info(f"Home team verified for Match ID {match_id} by User ID {current_user_id}")
        elif verify_home and not can_verify_home:
            logger.warning(f"User ID {current_user_id} attempted to verify home team for Match ID {match_id} without permission")
            
        # Handle away team verification    
        can_verify_away = admin_or_ref or (match.away_team_id in user_team_ids)
        if verify_away and can_verify_away:
            match.away_team_verified = True
            match.away_team_verified_by = current_user_id
            match.away_team_verified_at = now
            logger.info(f"Away team verified for Match ID {match_id} by User ID {current_user_id}")
        elif verify_away and not can_verify_away:
            logger.warning(f"User ID {current_user_id} attempted to verify away team for Match ID {match_id} without permission")

        # Increment version for optimistic locking (updated_at is handled by onupdate)
        match.version += 1

        update_standings(session, match, old_home_score, old_away_score)

        # Check if we should auto-generate playoff placement games
        from app.playoff_routes import check_and_generate_placement_games
        try:
            placement_games_generated = check_and_generate_placement_games(session, match)
            if placement_games_generated:
                logger.info(f"Playoff placement games auto-generated after match {match_id} was reported")
        except Exception as e:
            logger.error(f"Error checking for placement game generation: {e}", exc_info=True)
            # Don't fail the match reporting if placement game generation fails

        session.commit()

        logger.info(f"Match ID {match_id} reported successfully.")
        return jsonify({
            'success': True,
            'home_team_verified': match.home_team_verified,
            'away_team_verified': match.away_team_verified,
            'fully_verified': match.fully_verified,
            'home_verifier': (match.home_verifier.player.name if match.home_verifier and match.home_verifier.player 
                             else match.home_verifier.username if match.home_verifier else None),
            'away_verifier': (match.away_verifier.player.name if match.away_verifier and match.away_verifier.player 
                             else match.away_verifier.username if match.away_verifier else None),
            'home_team_verified_at': match.home_team_verified_at.isoformat() if match.home_team_verified_at else None,
            'away_team_verified_at': match.away_team_verified_at.isoformat() if match.away_team_verified_at else None
        }), 200

    else:
        return jsonify({'success': False, 'message': 'Method not allowed.'}), 405


@teams_bp.route('/standings', endpoint='view_standings')
@login_required
def view_standings():
    """
    Display the standings for the current Pub League, separated into Premier and Classic divisions.

    Retrieves the current Pub League season, queries standings for each division,
    and populates team statistics for display.
    """
    session = g.db_session
    season = session.query(Season).filter_by(is_current=True, league_type='Pub League').first()
    if not season:
        show_warning('No current season found.')
        return redirect(url_for('home.index'))

    def get_standings(league_name):
        return (
            session.query(Standings)
            .join(Team)
            .join(League)
            .filter(
                Standings.season_id == season.id,
                Team.id == Standings.team_id,
                League.id == Team.league_id,
                League.name == league_name
            )
            .order_by(
                Standings.points.desc(),
                Standings.goal_difference.desc(),
                Standings.goals_for.desc()
            )
            .all()
        )

    premier_standings = get_standings('Premier')
    classic_standings = get_standings('Classic')
    ecsfc_standings = get_standings('ECS FC')

    # Check Redis cache for standings first
    from app.performance_cache import cache_standings_data, set_standings_cache
    
    cached_standings = cache_standings_data(league_id=None)  # Cache all standings together
    
    if cached_standings:
        logger.debug("Using cached standings data")
        premier_stats = cached_standings.get('premier_stats', {})
        classic_stats = cached_standings.get('classic_stats', {})
        ecsfc_stats = cached_standings.get('ecsfc_stats', {})
    else:
        logger.debug("Generating fresh standings data")
        # Preload team stats to avoid N+1 queries
        from app.team_performance_helpers import preload_team_stats_for_request
        all_team_ids = [s.team.id for s in premier_standings] + [s.team.id for s in classic_standings] + [s.team.id for s in ecsfc_standings]
        preload_team_stats_for_request(all_team_ids)

        # Populate detailed stats for each team.
        premier_stats = {s.team.id: populate_team_stats(s.team, season) for s in premier_standings}
        classic_stats = {s.team.id: populate_team_stats(s.team, season) for s in classic_standings}
        ecsfc_stats = {s.team.id: populate_team_stats(s.team, season) for s in ecsfc_standings}
        
        # Cache the results
        standings_data = {
            'premier_stats': premier_stats,
            'classic_stats': classic_stats,
            'ecsfc_stats': ecsfc_stats
        }
        set_standings_cache(standings_data, league_id=None, ttl=300)  # Cache for 5 minutes

    return render_template(
        'view_standings.html',
        title='Standings',
        premier_standings=premier_standings,
        classic_standings=classic_standings,
        ecsfc_standings=ecsfc_standings,
        premier_stats=premier_stats,
        classic_stats=classic_stats,
        ecsfc_stats=ecsfc_stats
    )


@teams_bp.route('/season-overview', endpoint='season_overview')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def season_overview():
    """
    Display a comprehensive overview of the current season for Pub League and Global Admins.
    
    Shows detailed stats for each division:
    - Team standings
    - Top scorers (Golden Boot)
    - Top assisters (Silver Boot)
    - Yellow/Red cards
    - All goal scorers across the league
    """
    session = g.db_session
    
    # Get the current Pub League season
    season = session.query(Season).filter_by(is_current=True, league_type='Pub League').first()
    if not season:
        show_warning('No current season found.')
        return redirect(url_for('home.index'))
    
    # Define a function to get all leagues for a season
    def get_leagues(season_id):
        return (
            session.query(League)
            .filter(League.season_id == season_id)
            .all()
        )
    
    # Get all leagues for the current season
    leagues = get_leagues(season.id)
    league_map = {league.name: league for league in leagues}
    
    # Get standings for each division
    def get_standings(league_name):
        return (
            session.query(Standings)
            .join(Team)
            .join(League)
            .filter(
                Standings.season_id == season.id,
                Team.id == Standings.team_id,
                League.id == Team.league_id,
                League.name == league_name
            )
            .order_by(
                Standings.points.desc(),
                Standings.goal_difference.desc(),
                Standings.goals_for.desc()
            )
            .all()
        )
    
    premier_standings = get_standings('Premier')
    classic_standings = get_standings('Classic')
    
    # Get top scorers for each division (Golden Boot)
    def get_top_scorers(league_name, limit=10):
        league = league_map.get(league_name)
        if not league:
            return []
        
        return (
            session.query(
                Player, 
                func.sum(PlayerSeasonStats.goals).label('total_goals')
            )
            .join(PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id)
            .join(player_teams, Player.id == player_teams.c.player_id)
            .join(Team, player_teams.c.team_id == Team.id)
            .filter(
                PlayerSeasonStats.season_id == season.id,
                Team.league_id == league.id,
                PlayerSeasonStats.goals > 0
            )
            .group_by(Player.id)
            .order_by(func.sum(PlayerSeasonStats.goals).desc())
            .limit(limit)
            .all()
        )
    
    # Get top assisters for each division (Silver Boot)
    def get_top_assisters(league_name, limit=10):
        league = league_map.get(league_name)
        if not league:
            return []
        
        return (
            session.query(
                Player, 
                func.sum(PlayerSeasonStats.assists).label('total_assists')
            )
            .join(PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id)
            .join(player_teams, Player.id == player_teams.c.player_id)
            .join(Team, player_teams.c.team_id == Team.id)
            .filter(
                PlayerSeasonStats.season_id == season.id,
                Team.league_id == league.id,
                PlayerSeasonStats.assists > 0
            )
            .group_by(Player.id)
            .order_by(func.sum(PlayerSeasonStats.assists).desc())
            .limit(limit)
            .all()
        )
    
    # Get yellow cards for each division
    def get_yellow_cards(league_name, limit=10):
        league = league_map.get(league_name)
        if not league:
            return []
        
        return (
            session.query(
                Player, 
                func.sum(PlayerSeasonStats.yellow_cards).label('total_yellow_cards')
            )
            .join(PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id)
            .join(player_teams, Player.id == player_teams.c.player_id)
            .join(Team, player_teams.c.team_id == Team.id)
            .filter(
                PlayerSeasonStats.season_id == season.id,
                Team.league_id == league.id,
                PlayerSeasonStats.yellow_cards > 0
            )
            .group_by(Player.id)
            .order_by(func.sum(PlayerSeasonStats.yellow_cards).desc())
            .limit(limit)
            .all()
        )
    
    # Get red cards for each division
    def get_red_cards(league_name, limit=10):
        league = league_map.get(league_name)
        if not league:
            return []
        
        return (
            session.query(
                Player, 
                func.sum(PlayerSeasonStats.red_cards).label('total_red_cards')
            )
            .join(PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id)
            .join(player_teams, Player.id == player_teams.c.player_id)
            .join(Team, player_teams.c.team_id == Team.id)
            .filter(
                PlayerSeasonStats.season_id == season.id,
                Team.league_id == league.id,
                PlayerSeasonStats.red_cards > 0
            )
            .group_by(Player.id)
            .order_by(func.sum(PlayerSeasonStats.red_cards).desc())
            .limit(limit)
            .all()
        )
    
    # Get all goal scorers across the league
    def get_all_goal_scorers(season_id, league_name=None):
        query = (
            session.query(
                Player,
                Team,
                League.name.label('league_name'),
                func.sum(PlayerSeasonStats.goals).label('total_goals')
            )
            .join(PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id)
            .join(player_teams, Player.id == player_teams.c.player_id)
            .join(Team, player_teams.c.team_id == Team.id)
            .join(League, Team.league_id == League.id)
            .filter(
                PlayerSeasonStats.season_id == season_id,
                League.season_id == season_id,
                PlayerSeasonStats.goals > 0
            )
        )
        
        if league_name:
            query = query.filter(League.name == league_name)
            
        return (
            query.group_by(Player.id, Team.id, League.name)
            .order_by(
                func.sum(PlayerSeasonStats.goals).desc()
            )
            .all()
        )
        
    # Get all assist providers across the league
    def get_all_assist_providers(season_id, league_name=None):
        query = (
            session.query(
                Player,
                Team,
                League.name.label('league_name'),
                func.sum(PlayerSeasonStats.assists).label('total_assists')
            )
            .join(PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id)
            .join(player_teams, Player.id == player_teams.c.player_id)
            .join(Team, player_teams.c.team_id == Team.id)
            .join(League, Team.league_id == League.id)
            .filter(
                PlayerSeasonStats.season_id == season_id,
                League.season_id == season_id,
                PlayerSeasonStats.assists > 0
            )
        )
        
        if league_name:
            query = query.filter(League.name == league_name)
            
        return (
            query.group_by(Player.id, Team.id, League.name)
            .order_by(
                func.sum(PlayerSeasonStats.assists).desc()
            )
            .all()
        )
    
    # Get all player events (goals, assists, cards)
    def get_player_events(season_id):
        return (
            session.query(
                PlayerEvent,
                Player,
                Match,
                Team
            )
            .join(Player, PlayerEvent.player_id == Player.id)
            .join(Match, PlayerEvent.match_id == Match.id)
            .join(Team, or_(Match.home_team_id == Team.id, Match.away_team_id == Team.id))
            .join(League, Team.league_id == League.id)
            .filter(
                League.season_id == season_id
            )
            .order_by(
                Match.date.desc(),
                PlayerEvent.event_type
            )
            .all()
        )
    
    # Get all team stats
    premier_top_scorers = get_top_scorers('Premier')
    premier_top_assisters = get_top_assisters('Premier')
    premier_yellow_cards = get_yellow_cards('Premier')
    premier_red_cards = get_red_cards('Premier')
    
    classic_top_scorers = get_top_scorers('Classic')
    classic_top_assisters = get_top_assisters('Classic')
    classic_yellow_cards = get_yellow_cards('Classic')
    classic_red_cards = get_red_cards('Classic')
    
    # Get all league stats
    all_goal_scorers = get_all_goal_scorers(season.id)
    all_assist_providers = get_all_assist_providers(season.id)
    
    # Get division-specific all league stats
    premier_all_goal_scorers = get_all_goal_scorers(season.id, 'Premier')
    premier_all_assist_providers = get_all_assist_providers(season.id, 'Premier')
    classic_all_goal_scorers = get_all_goal_scorers(season.id, 'Classic')
    classic_all_assist_providers = get_all_assist_providers(season.id, 'Classic')
    
    # Get own goal statistics for the season
    def get_own_goal_stats(season_id, league_name=None):
        query = (
            session.query(func.count(PlayerEvent.id).label('total_own_goals'))
            .join(Team, PlayerEvent.team_id == Team.id)
            .join(League, Team.league_id == League.id)
            .filter(
                PlayerEvent.event_type == PlayerEventType.OWN_GOAL,
                League.season_id == season_id
            )
        )
        
        if league_name:
            query = query.filter(League.name == league_name)
            
        result = query.first()
        return result.total_own_goals if result else 0
    
    # Get own goal counts
    total_own_goals = get_own_goal_stats(season.id)
    premier_own_goals = get_own_goal_stats(season.id, 'Premier')
    classic_own_goals = get_own_goal_stats(season.id, 'Classic')
    
    # Populate team stats for the template
    premier_team_stats = {s.team.id: populate_team_stats(s.team, season) for s in premier_standings}
    classic_team_stats = {s.team.id: populate_team_stats(s.team, season) for s in classic_standings}
    
    return render_template(
        'season_overview.html',
        title='Season Overview',
        season=season,
        premier_standings=premier_standings,
        classic_standings=classic_standings,
        premier_team_stats=premier_team_stats,
        classic_team_stats=classic_team_stats,
        premier_top_scorers=premier_top_scorers,
        premier_top_assisters=premier_top_assisters,
        premier_yellow_cards=premier_yellow_cards,
        premier_red_cards=premier_red_cards,
        classic_top_scorers=classic_top_scorers,
        classic_top_assisters=classic_top_assisters,
        classic_yellow_cards=classic_yellow_cards,
        classic_red_cards=classic_red_cards,
        all_goal_scorers=all_goal_scorers,
        all_assist_providers=all_assist_providers,
        premier_all_goal_scorers=premier_all_goal_scorers,
        premier_all_assist_providers=premier_all_assist_providers,
        classic_all_goal_scorers=classic_all_goal_scorers,
        classic_all_assist_providers=classic_all_assist_providers,
        total_own_goals=total_own_goals,
        premier_own_goals=premier_own_goals,
        classic_own_goals=classic_own_goals
    )

@teams_bp.route('/upload_team_kit/<int:team_id>', methods=['POST'])
@login_required
def upload_team_kit(team_id):
    session = g.db_session
    team = session.query(Team).get(team_id)
    if not team:
        show_error('Team not found.')
        return redirect(url_for('teams.teams_overview'))
    
    if 'team_kit' not in request.files:
        show_error('No file part in the request.')
        return redirect(url_for('teams.team_details', team_id=team_id))
    
    file = request.files['team_kit']
    if file.filename == '':
        show_error('No file selected.')
        return redirect(url_for('teams.team_details', team_id=team_id))
    
    if file and allowed_file(file.filename):
        # Process image first without holding database session
        filename = f'team_{team_id}_kit.png'
        upload_folder = os.path.join(current_app.root_path, 'static', 'img', 'uploads', 'kits')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        
        # Clean up old kit file if it exists
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass  # If we can't remove it, we'll just overwrite it
        
        try:
            # Image processing without database session
            image = Image.open(file).convert("RGBA")
            
            def make_background_transparent(img, bg_color=(255, 255, 255), tolerance=30):
                datas = img.getdata()
                newData = []
                for item in datas:
                    if (abs(item[0] - bg_color[0]) < tolerance and
                        abs(item[1] - bg_color[1]) < tolerance and
                        abs(item[2] - bg_color[2]) < tolerance):
                        newData.append((255, 255, 255, 0))
                    else:
                        newData.append(item)
                img.putdata(newData)
                return img
            
            image = make_background_transparent(image)
            image.save(file_path, format='PNG')
            
            # After successful image processing, update database
            timestamp = int(time.time())
            team.kit_url = url_for('static', filename='img/uploads/kits/' + filename) + f'?v={timestamp}'
            session.add(team)
            session.commit()
            
        except Exception as e:
            logger.error(f"Error processing team kit image: {e}")
            show_error('Error processing image. Please try again.')
            return redirect(url_for('teams.team_details', team_id=team_id))
        
        logger.info(f"Team {team_id} kit updated successfully. Saved as: {filename}, URL: {team.kit_url}")
        show_success('Team kit updated successfully!')
        return redirect(url_for('teams.team_details', team_id=team_id))
    else:
        show_error('Invalid file type. Allowed types: png, jpg, jpeg, gif.')
        return redirect(url_for('teams.team_details', team_id=team_id))


@teams_bp.route('/upload_team_background/<int:team_id>', methods=['POST'])
@login_required
def upload_team_background(team_id):
    session = g.db_session
    team = session.query(Team).get(team_id)
    if not team:
        show_error('Team not found.')
        return redirect(url_for('teams.teams_overview'))
    
    if 'team_background' not in request.files:
        show_error('No file part in the request.')
        return redirect(url_for('teams.team_details', team_id=team_id))
    
    file = request.files['team_background']
    if file.filename == '':
        show_error('No file selected.')
        return redirect(url_for('teams.team_details', team_id=team_id))
    
    if file and allowed_file(file.filename):
        # Process image first without holding database session
        filename = f'team_{team_id}_background.jpg'
        upload_folder = os.path.join(current_app.root_path, 'static', 'img', 'uploads', 'backgrounds')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        
        # Clean up old background file if it exists
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass  # If we can't remove it, we'll just overwrite it
        
        try:
            # Image processing without database session
            image = Image.open(file).convert("RGB")
            
            # Resize and optimize for background use
            # Scale to reasonable dimensions while maintaining aspect ratio
            max_width = 1200
            max_height = 600
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            
            # Save with optimization
            image.save(file_path, format='JPEG', optimize=True, quality=85)
            
            # After successful image processing, update database
            import datetime
            timestamp = int(datetime.datetime.now().timestamp() * 1000)
            team.background_image_url = url_for('static', filename='img/uploads/backgrounds/' + filename) + f'?v={timestamp}'
            
            # Handle position data if provided
            position_data = request.form.get('position_data')
            if position_data:
                try:
                    import json
                    position_info = json.loads(position_data)
                    # Store position data in team metadata or a new field
                    # For now, we'll store it in the session to apply to the template
                    team.background_position = position_info.get('backgroundPosition', 'center')
                    team.background_size = position_info.get('backgroundSize', 'cover')
                    logger.info(f"Parsed position data for team {team_id}: position={team.background_position}, size={team.background_size}")
                except json.JSONDecodeError:
                    logger.warning(f"Invalid position data for team {team_id}: {position_data}")
        
            else:
                logger.info(f"No position data provided for team {team_id}, using defaults")
                team.background_position = 'center'
                team.background_size = 'cover'
            
            session.add(team)
            session.commit()
        
        except Exception as e:
            logger.error(f"Error processing team background image: {e}")
            show_error('Error processing image. Please try again.')
            return redirect(url_for('teams.team_details', team_id=team_id))
        
        # Verify the values were saved
        session.refresh(team)
        logger.info(f"Team {team_id} background updated successfully. Saved as: {filename}, URL: {team.background_image_url}, position: {team.background_position}, size: {team.background_size}")
        show_success('Team background updated successfully!')
        return redirect(url_for('teams.team_details', team_id=team_id))
    else:
        show_error('Invalid file type. Allowed types: png, jpg, jpeg, gif.')
        return redirect(url_for('teams.team_details', team_id=team_id))


@teams_bp.route('/<int:team_id>/refresh-discord-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def refresh_discord_status(team_id):
    """
    Admin endpoint to manually refresh Discord status for all players on a team.
    Useful when you need to force-check players regardless of when they were last checked.
    """
    session = g.db_session
    
    try:
        # Validate CSRF token
        validate_csrf(request.headers.get('X-CSRFToken'))
    except CSRFError:
        return jsonify({'success': False, 'message': 'CSRF token missing or invalid.'}), 403
    
    # Get the team and verify it exists
    team = session.query(Team).options(joinedload(Team.players)).get(team_id)
    if not team:
        return jsonify({'success': False, 'message': 'Team not found.'}), 404
    
    # Get all players on this team who have Discord IDs
    players_with_discord = [p for p in team.players if p.discord_id]
    
    if not players_with_discord:
        return jsonify({
            'success': False, 
            'message': 'No players with Discord IDs found on this team.'
        }), 400
    
    logger.info(f"Manually refreshing Discord status for team {team.name} (ID: {team_id})")
    logger.info(f"Found {len(players_with_discord)} players with Discord IDs: {[p.name for p in players_with_discord]}")
    
    # Track results
    refresh_results = []
    success_count = 0
    error_count = 0
    
    # Check each player's Discord status
    for player in players_with_discord:
        try:
            logger.info(f"Refreshing Discord status for player {player.name} (ID: {player.id}, Discord: {player.discord_id})")
            
            old_status = player.discord_in_server
            success = player.check_discord_status()
            
            if success:
                success_count += 1
                session.add(player)  # Mark for update
                
                # Determine status change
                if old_status is None and player.discord_in_server is not None:
                    status_change = f"Unknown -> {'In Server' if player.discord_in_server else 'Not in Server'}"
                elif old_status != player.discord_in_server:
                    old_text = 'In Server' if old_status else 'Not in Server'
                    new_text = 'In Server' if player.discord_in_server else 'Not in Server'
                    status_change = f"{old_text} -> {new_text}"
                else:
                    status_change = 'In Server' if player.discord_in_server else 'Not in Server' if player.discord_in_server is not None else 'Unknown'
                
                refresh_results.append({
                    'player_name': player.name,
                    'discord_username': player.discord_username,
                    'status': 'success',
                    'in_server': player.discord_in_server,
                    'status_change': status_change
                })
                logger.info(f"Successfully refreshed Discord status for {player.name}: {status_change}")
            else:
                error_count += 1
                refresh_results.append({
                    'player_name': player.name,
                    'status': 'error',
                    'error': 'Discord API error or player not found'
                })
                logger.error(f"Failed to refresh Discord status for {player.name}: API error")
                
        except Exception as e:
            error_count += 1
            refresh_results.append({
                'player_name': player.name,
                'status': 'error',
                'error': str(e)
            })
            logger.error(f"Exception while refreshing Discord status for {player.name}: {e}", exc_info=True)
    
    # Commit the updates
    try:
        session.commit()
        logger.info(f"Committed Discord status updates for team {team.name}")
    except Exception as e:
        logger.error(f"Failed to commit Discord status updates: {e}")
        session.rollback()
        return jsonify({'success': False, 'message': 'Failed to save Discord status updates.'}), 500
    
    # Log final results
    logger.info(f"Manual Discord status refresh completed for team {team.name}")
    logger.info(f"Results: {success_count} successful, {error_count} errors")
    
    # Return results
    return jsonify({
        'success': True,
        'message': f'Discord status refresh completed for {team.name}',
        'team_name': team.name,
        'processed_count': success_count,
        'error_count': error_count,
        'total_players': len(players_with_discord),
        'results': refresh_results
    })


@teams_bp.route('/player/<int:player_id>/refresh-discord-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def refresh_player_discord_status(player_id):
    """
    Admin endpoint to manually refresh Discord status for a single player.
    Useful when you need to check if a specific player has joined the server.
    """
    session = g.db_session
    
    try:
        # Validate CSRF token
        validate_csrf(request.headers.get('X-CSRFToken'))
    except CSRFError:
        return jsonify({'success': False, 'message': 'CSRF token missing or invalid.'}), 403
    
    # Get the player and verify they exist
    player = session.query(Player).get(player_id)
    if not player:
        return jsonify({'success': False, 'message': 'Player not found.'}), 404
    
    if not player.discord_id:
        return jsonify({
            'success': False, 
            'message': f'Player {player.name} does not have a Discord ID linked.'
        }), 400
    
    logger.info(f"Manually refreshing Discord status for player {player.name} (ID: {player_id}, Discord: {player.discord_id})")
    
    try:
        old_status = player.discord_in_server
        old_username = player.discord_username
        
        success = player.check_discord_status()
        
        if success:
            session.add(player)  # Mark for update
            session.commit()
            
            # Determine status change
            if old_status is None and player.discord_in_server is not None:
                status_change = f"Unknown → {'In Server' if player.discord_in_server else 'Not in Server'}"
            elif old_status != player.discord_in_server:
                old_text = 'In Server' if old_status else 'Not in Server'
                new_text = 'In Server' if player.discord_in_server else 'Not in Server'
                status_change = f"{old_text} → {new_text}"
            else:
                status_change = 'In Server' if player.discord_in_server else 'Not in Server' if player.discord_in_server is not None else 'Unknown'
            
            # Check if username changed
            username_change = None
            if old_username != player.discord_username:
                username_change = f"{old_username or 'Unknown'} → {player.discord_username or 'Unknown'}"
            
            logger.info(f"Successfully refreshed Discord status for {player.name}: {status_change}")
            
            return jsonify({
                'success': True,
                'message': f'Discord status updated for {player.name}',
                'player_name': player.name,
                'discord_username': player.discord_username,
                'in_server': player.discord_in_server,
                'status_change': status_change,
                'username_change': username_change,
                'last_checked': player.discord_last_checked.isoformat() if player.discord_last_checked else None
            })
        else:
            logger.error(f"Failed to refresh Discord status for {player.name}: API error")
            return jsonify({
                'success': False,
                'message': f'Failed to check Discord status for {player.name}. They may not exist on Discord or there was an API error.'
            }), 500
            
    except Exception as e:
        logger.error(f"Exception while refreshing Discord status for {player.name}: {e}", exc_info=True)
        session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error checking Discord status: {str(e)}'
        }), 500


@teams_bp.route('/<int:team_id>/assign-discord-roles', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def assign_discord_roles_to_team(team_id):
    """
    Admin endpoint to manually assign Discord roles to all players on a team.
    This is a fix for when the automatic role assignment during draft didn't work.
    """
    session = g.db_session
    
    try:
        # Validate CSRF token
        validate_csrf(request.headers.get('X-CSRFToken'))
    except CSRFError:
        return jsonify({'success': False, 'message': 'CSRF token missing or invalid.'}), 403
    
    # Get the team and verify it exists
    team = session.query(Team).options(joinedload(Team.players)).get(team_id)
    if not team:
        return jsonify({'success': False, 'message': 'Team not found.'}), 404
    
    # Get all players on this team who have Discord IDs
    players_with_discord = [p for p in team.players if p.discord_id]
    
    if not players_with_discord:
        return jsonify({
            'success': False, 
            'message': 'No players with Discord IDs found on this team.'
        }), 400
    
    logger.info(f"Starting manual Discord role assignment for team {team.name} (ID: {team_id})")
    logger.info(f"Found {len(players_with_discord)} players with Discord IDs: {[p.name for p in players_with_discord]}")
    
    # Import the existing Celery task for role assignment
    from app.tasks.tasks_discord import assign_roles_to_player_task
    
    # Track results
    assignment_results = []
    success_count = 0
    error_count = 0
    
    # Process each player with Discord ID
    for player in players_with_discord:
        try:
            logger.info(f"Assigning roles to player {player.name} (ID: {player.id}, Discord: {player.discord_id})")
            
            # Use the existing Celery task to assign roles
            # team_id=None means process all teams for this player (not just one specific team)
            # only_add=False means it will also remove roles that shouldn't be there
            task_result = assign_roles_to_player_task.delay(
                player.id, 
                team_id=None,  # Process all teams, not just this specific team
                only_add=False  # Allow role removal for proper sync
            )
            
            # For manual assignment, we want to know the result immediately
            # In production, you might want to make this async and poll for results
            result = task_result.get(timeout=30)  # Wait up to 30 seconds for result
            
            if result.get('success'):
                success_count += 1
                assignment_results.append({
                    'player_name': player.name,
                    'status': 'success',
                    'roles_added': result.get('roles_added', []),
                    'roles_removed': result.get('roles_removed', [])
                })
                logger.info(f"Successfully assigned roles to {player.name}: added {result.get('roles_added', [])}, removed {result.get('roles_removed', [])}")
            else:
                error_count += 1
                assignment_results.append({
                    'player_name': player.name,
                    'status': 'error',
                    'error': result.get('message', 'Unknown error')
                })
                logger.error(f"Failed to assign roles to {player.name}: {result.get('message', 'Unknown error')}")
                
        except Exception as e:
            error_count += 1
            assignment_results.append({
                'player_name': player.name,
                'status': 'error',
                'error': str(e)
            })
            logger.error(f"Exception while assigning roles to {player.name}: {e}", exc_info=True)
    
    # Log final results
    logger.info(f"Manual Discord role assignment completed for team {team.name}")
    logger.info(f"Results: {success_count} successful, {error_count} errors")
    
    # Return results
    return jsonify({
        'success': True,
        'message': f'Discord role assignment completed for {team.name}',
        'team_name': team.name,
        'processed_count': success_count,
        'error_count': error_count,
        'total_players': len(players_with_discord),
        'results': assignment_results
    })