from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app as app
from flask_login import login_required
from app.models import League, Player, Team, Season, PlayerSeasonStats
from app.decorators import role_required
from app.routes import get_current_season_and_year
from app import db, socketio
from flask_socketio import SocketIO, emit
from app.discord_utils import assign_role_to_player, remove_role_from_player
import asyncio

draft = Blueprint('draft', __name__)

# Draft Classic League
@draft.route('/classic')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_classic():
    classic_league = League.query.filter_by(name='Classic').first()
    teams = classic_league.teams

    # Fetch the current season
    current_season_name, current_year = get_current_season_and_year()
    current_season = Season.query.filter_by(name=current_season_name).first()

    # Fetch players who are available (not yet drafted) in the Classic league
    available_players = Player.query.filter_by(league_id=classic_league.id, team_id=None).order_by(Player.name.asc()).all()

    # Fetch players who have been drafted to a team in the Classic league
    drafted_players_by_team = {}
    for team in teams:
        drafted_players_by_team[team.id] = Player.query.filter_by(league_id=classic_league.id, team_id=team.id).order_by(Player.name.asc()).all()

    return render_template('draft_classic.html', teams=teams, available_players=available_players, drafted_players_by_team=drafted_players_by_team, season=current_season)

# Draft Premier League
@draft.route('/premier')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_premier():
    premier_league = League.query.filter_by(name='Premier').first()
    teams = premier_league.teams

    # Fetch the current season
    current_season_name, current_year = get_current_season_and_year()  # Ensure this function returns the current season's name and year
    season = Season.query.filter_by(name=current_season_name).first()

    # Fetch players who are available (not yet drafted) in the Premier league
    available_players = Player.query.filter_by(league_id=premier_league.id, team_id=None).order_by(Player.name.asc()).all()

    # Fetch players who have been drafted to a team in the Premier league
    drafted_players_by_team = {}
    for team in teams:
        drafted_players_by_team[team.id] = Player.query.filter_by(league_id=premier_league.id, team_id=team.id).order_by(Player.name.asc()).all()

    return render_template('draft_premier.html', teams=teams, available_players=available_players, drafted_players_by_team=drafted_players_by_team, season=season)

# Handle Draft via WebSocket
@socketio.on('draft_player')
def handle_draft_player(data):
    print("Draft player function called")
    player_id = data['player_id']
    team_id = data['team_id']

    player = db.session.get(Player, player_id)
    team = db.session.get(Team, team_id)

    if player and team:
        print(f"Assigning player {player.name} (ID: {player_id}) to team {team.name} (ID: {team_id})")
        player.team_id = team_id
        db.session.commit()

        # Assign the role in Discord
        asyncio.run(assign_role_to_player(player))

        # Fetch the current season
        current_season = Season.query.order_by(Season.id.desc()).first()

        # Fetch season-specific stats from PlayerSeasonStats
        season_stats = PlayerSeasonStats.query.filter_by(player_id=player.id, season_id=current_season.id).first()

        emit('player_drafted', {
            'player_id': player.id,
            'player_name': player.name,
            'team_id': team.id,
            'team_name': team.name,
            'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
            'goals': season_stats.goals if season_stats else 0,
            'assists': season_stats.assists if season_stats else 0,
            'yellow_cards': season_stats.yellow_cards if season_stats else 0,
            'red_cards': season_stats.red_cards if season_stats else 0,
            'player_notes': player.player_notes or 'No notes available'
        }, broadcast=True)

# Handle Player Removal via WebSocket
@socketio.on('remove_player')
def handle_remove_player(data):
    player_id = data['player_id']
    team_id = data['team_id']

    player = db.session.get(Player, player_id)
    team = db.session.get(Team, team_id)

    if player and team:
        # Remove the role in Discord
        asyncio.run(remove_role_from_player(player))

        # Remove the player from the team
        player.team_id = None
        db.session.commit()

        # Fetch the current season
        current_season = Season.query.order_by(Season.id.desc()).first()

        # Fetch season-specific stats from PlayerSeasonStats
        season_stats = PlayerSeasonStats.query.filter_by(player_id=player.id, season_id=current_season.id).first()

        # Notify all clients about the removal
        emit('player_removed', {
            'player_id': player.id,
            'player_name': player.name,
            'team_id': team.id,  # Including team_id for consistency
            'team_name': team.name,  # Including team_name for consistency
            'goals': season_stats.goals if season_stats else 0,
            'assists': season_stats.assists if season_stats else 0,
            'yellow_cards': season_stats.yellow_cards if season_stats else 0,
            'red_cards': season_stats.red_cards if season_stats else 0,
            'player_notes': player.player_notes or 'No notes available',
            'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png'
        }, broadcast=True)