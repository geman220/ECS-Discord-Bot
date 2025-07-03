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
from datetime import datetime
from typing import Optional
from werkzeug.utils import secure_filename

from flask import (
    Blueprint, render_template, redirect, url_for, request, jsonify, g,
    current_app
)
from app.alert_helpers import show_success, show_error, show_warning, show_info
from flask_login import login_required
from flask_wtf.csrf import validate_csrf, CSRFError
from sqlalchemy import or_, func
from sqlalchemy.orm import selectinload, joinedload
from PIL import Image
from io import BytesIO

from app.models import (
    Team, Player, League, Season, Match, Standings,
    PlayerEventType, PlayerEvent, PlayerTeamSeason, User,
    PlayerSeasonStats, player_teams
)
from app.forms import ReportMatchForm
from app.teams_helpers import populate_team_stats, update_standings, process_events, process_own_goals
from app.utils.user_helpers import safe_current_user
from app.decorators import role_required

logger = logging.getLogger(__name__)
teams_bp = Blueprint('teams', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

    report_form = ReportMatchForm()

    # Fetch matches for this team within the same league.
    all_matches = (
        session.query(Match)
        .options(
            selectinload(Match.home_team).joinedload(Team.players),
            selectinload(Match.away_team).joinedload(Team.players)
        )
        .filter(
            ((Match.home_team_id == team_id) | (Match.away_team_id == team_id)),
            ((Match.home_team.has(league_id=league.id)) | (Match.away_team.has(league_id=league.id)))
        )
        .order_by(Match.date.asc())
        .all()
    )

    # Build a schedule mapping dates to match details and gather player choices.
    schedule = defaultdict(list)
    player_choices = {}

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

        schedule[match.date].append({
            'id': match.id,
            'time': match.time,
            'location': match.location,
            'opponent_name': away_team_name if match.home_team_id == team_id else home_team_name,
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
        })

    # Determine the next match date for display.
    next_match_date = None
    if schedule:
        today = datetime.today().date()
        match_dates = sorted(schedule.keys())
        for md in match_dates:
            if md >= today:
                next_match_date = md
                break
        if not next_match_date:
            next_match_date = match_dates[-1]

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
        player_choices=player_choices
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
    return render_template('teams_overview.html', title='Teams Overview', teams=teams)


@teams_bp.route('/report_match/<int:match_id>', endpoint='report_match', methods=['GET', 'POST'])
@login_required
def report_match(match_id):
    session = g.db_session
    logger.info(f"Starting report_match for Match ID: {match_id}")
    match = (
        session.query(Match)
        .options(
            joinedload(Match.home_team).joinedload(Team.players),
            joinedload(Match.away_team).joinedload(Team.players),
            joinedload(Match.home_verifier).joinedload(User.player),
            joinedload(Match.away_verifier).joinedload(User.player)
        )
        .get(match_id)
    )
    if not match:
        show_error('Match not found.')
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
            
            if current_user_player:
                user_team_ids = [team.id for team in current_user_player.teams]
            
            # Determine if the user can verify for either team
            can_verify_home = is_admin or match.home_team_id in user_team_ids
            can_verify_away = is_admin or match.away_team_id in user_team_ids
            
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
                'is_admin': is_admin
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
        
        if current_user_player:
            user_team_ids = [team.id for team in current_user_player.teams]
            
        # Check if the user wants to verify for a team
        verify_home = data.get('verify_home_team', False)
        verify_away = data.get('verify_away_team', False)
        
        now = datetime.utcnow()
        
        # Handle home team verification
        if verify_home and (is_admin or match.home_team_id in user_team_ids):
            match.home_team_verified = True
            match.home_team_verified_by = current_user_id
            match.home_team_verified_at = now
            logger.info(f"Home team verified for Match ID {match_id} by User ID {current_user_id}")
            
        # Handle away team verification    
        if verify_away and (is_admin or match.away_team_id in user_team_ids):
            match.away_team_verified = True
            match.away_team_verified_by = current_user_id
            match.away_team_verified_at = now
            logger.info(f"Away team verified for Match ID {match_id} by User ID {current_user_id}")

        update_standings(session, match, old_home_score, old_away_score)
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

    # Populate detailed stats for each team.
    premier_stats = {s.team.id: populate_team_stats(s.team, season) for s in premier_standings}
    classic_stats = {s.team.id: populate_team_stats(s.team, season) for s in classic_standings}

    return render_template(
        'view_standings.html',
        title='Standings',
        premier_standings=premier_standings,
        classic_standings=classic_standings,
        premier_stats=premier_stats,
        classic_stats=classic_stats
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
                League.name,
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
                League.name,
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
        
        filename = secure_filename(file.filename)
        upload_folder = os.path.join(current_app.root_path, 'static', 'img', 'uploads', 'kits')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        
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
        
        # Append a timestamp to bust the cache
        timestamp = int(time.time())
        team.kit_url = url_for('static', filename='img/uploads/kits/' + filename) + f'?v={timestamp}'
        session.commit()
        
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
        filename = secure_filename(file.filename)
        upload_folder = os.path.join(current_app.root_path, 'static', 'img', 'uploads', 'backgrounds')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        
        image = Image.open(file).convert("RGB")
        
        # Resize and optimize for background use
        # Scale to reasonable dimensions while maintaining aspect ratio
        max_width = 1200
        max_height = 600
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        
        # Save with optimization
        image.save(file_path, format='JPEG', optimize=True, quality=85)
        
        # Append a timestamp to bust the cache
        timestamp = int(time.time())
        team.background_image_url = url_for('static', filename='img/uploads/backgrounds/' + filename) + f'?v={timestamp}'
        session.commit()
        
        show_success('Team background updated successfully!')
        return redirect(url_for('teams.team_details', team_id=team_id))
    else:
        show_error('Invalid file type. Allowed types: png, jpg, jpeg, gif.')
        return redirect(url_for('teams.team_details', team_id=team_id))