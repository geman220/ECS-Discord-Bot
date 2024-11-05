from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app as app
from flask_login import login_required
from sqlalchemy.orm import joinedload
from app.models import League, Player, Team, Season, PlayerSeasonStats
from app.decorators import role_required, db_operation, query_operation
from app.routes import get_current_season_and_year
from app.extensions import socketio
from flask_socketio import emit
from app.discord_utils import assign_role_to_player, remove_role_from_player
import asyncio
import logging

# Get the logger for this module
logger = logging.getLogger(__name__)

draft = Blueprint('draft', __name__)

@draft.route('/classic')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
@query_operation
def draft_classic():
    try:
        # Fetch the Classic league with eager loading
        classic_league = League.query.options(
            joinedload(League.teams)
        ).filter_by(name='Classic').first()
        
        if not classic_league:
            flash('Classic league not found.', 'danger')
            return redirect(url_for('main.index'))

        teams = classic_league.teams

        # Get current season
        current_season_name, current_year = get_current_season_and_year()
        current_season = Season.query.filter_by(name=current_season_name).first()

        if not current_season:
            flash('Current season not found.', 'danger')
            return redirect(url_for('main.index'))

        # Use eager loading for available players
        available_players = Player.query.options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
            joinedload(Player.team)
        ).filter_by(
            league_id=classic_league.id,
            team_id=None
        ).order_by(Player.name.asc()).all()

        # Force load relationships
        for player in available_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

        # Get drafted players with eager loading
        drafted_players = Player.query.options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
            joinedload(Player.team)
        ).filter(
            Player.league_id == classic_league.id,
            Player.team_id.isnot(None)
        ).order_by(Player.name.asc()).all()

        # Force load relationships
        for player in drafted_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

        # Organize drafted players
        drafted_players_by_team = {team.id: [] for team in teams}
        for player in drafted_players:
            if player.team_id in drafted_players_by_team:
                drafted_players_by_team[player.team_id].append(player)

        return render_template(
            'draft_classic.html',
            teams=teams,
            available_players=available_players,
            drafted_players_by_team=drafted_players_by_team,
            season=current_season
        )

    except Exception as e:
        logger.error(f"Error in draft_classic: {str(e)}", exc_info=True)
        flash('An error occurred while loading the draft page.', 'danger')
        return redirect(url_for('main.index'))

@draft.route('/premier')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_premier():
    try:
        # Fetch the Premier league with eager loading of teams
        premier_league = League.query.options(
            joinedload(League.teams)
        ).filter_by(name='Premier').first()
        
        if not premier_league:
            flash('Premier league not found.', 'danger')
            return redirect(url_for('main.index'))

        teams = premier_league.teams

        # Fetch the current season
        current_season_name, current_year = get_current_season_and_year()
        season = Season.query.filter_by(name=current_season_name).first()
        
        if not season:
            flash('Current season not found.', 'danger')
            return redirect(url_for('main.index'))

        # Fetch available players with eager loading
        available_players = Player.query.options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
            joinedload(Player.team)
        ).filter_by(
            league_id=premier_league.id, 
            team_id=None
        ).order_by(Player.name.asc()).all()

        # Force load relationships
        for player in available_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

        # Fetch drafted players with eager loading
        drafted_players = Player.query.options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
            joinedload(Player.team)
        ).filter(
            Player.league_id == premier_league.id,
            Player.team_id.isnot(None)
        ).order_by(Player.name.asc()).all()

        # Force load relationships
        for player in drafted_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

        # Organize drafted players by team
        drafted_players_by_team = {team.id: [] for team in teams}
        for player in drafted_players:
            if player.team_id in drafted_players_by_team:
                drafted_players_by_team[player.team_id].append(player)

        return render_template(
            'draft_premier.html',
            teams=teams,
            available_players=available_players,
            drafted_players_by_team=drafted_players_by_team,
            season=season
        )

    except Exception as e:
        logger.error(f"Error in draft_premier: {str(e)}", exc_info=True)
        flash('An error occurred while loading the draft page.', 'danger')
        return redirect(url_for('main.index'))

@draft.route('/ecs_fc')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
@query_operation
def draft_ecs_fc():
    try:
        # Fetch ECS FC league with eager loading
        ecs_fc_league = League.query.options(
            joinedload(League.teams)
        ).filter_by(name='ECS FC').first()

        if not ecs_fc_league:
            flash('ECS FC league not found.', 'danger')
            return redirect(url_for('main.index'))

        teams = ecs_fc_league.teams

        # Get current season
        current_season_name, current_year = get_current_season_and_year()
        current_season = Season.query.filter_by(name=current_season_name).first()

        if not current_season:
            flash('Current season not found.', 'danger')
            return redirect(url_for('main.index'))

        # Use eager loading for available players
        available_players = Player.query.options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
            joinedload(Player.team)
        ).filter_by(
            league_id=ecs_fc_league.id,
            team_id=None
        ).order_by(Player.name.asc()).all()

        # Force load relationships
        for player in available_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

        # Get drafted players with eager loading
        drafted_players = Player.query.options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
            joinedload(Player.team)
        ).filter(
            Player.league_id == ecs_fc_league.id,
            Player.team_id.isnot(None)
        ).order_by(Player.name.asc()).all()

        # Force load relationships
        for player in drafted_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

        # Organize drafted players
        drafted_players_by_team = {team.id: [] for team in teams}
        for player in drafted_players:
            if player.team_id in drafted_players_by_team:
                drafted_players_by_team[player.team_id].append(player)

        return render_template(
            'draft_ecs_fc.html',
            teams=teams,
            available_players=available_players,
            drafted_players_by_team=drafted_players_by_team,
            season=current_season
        )

    except Exception as e:
        logger.error(f"Error in draft_ecs_fc: {str(e)}", exc_info=True)
        flash('An error occurred while loading the draft page.', 'danger')
        return redirect(url_for('main.index'))

@socketio.on('draft_player')
@db_operation
def handle_draft_player(data):
    try:
        player_id = data['player_id']
        team_id = data['team_id']

        # Use eager loading for the player query
        player = Player.query.options(
            joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season)
        ).get_or_404(player_id)
        
        team = Team.query.get_or_404(team_id)

        # Update player's team
        player.team_id = team_id

        # Assign Discord role
        asyncio.run(assign_role_to_player(player))

        # Get current season and stats
        current_season = Season.query.filter_by(is_current=True).first()
        season_stats = next(
            (stats for stats in player.season_stats if stats.season_id == current_season.id),
            None
        ) if player.season_stats else None

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

    except Exception as e:
        logger.error(f"Error handling player draft: {str(e)}", exc_info=True)
        emit('error', {'message': 'An error occurred while drafting the player'}, broadcast=False)
        raise

@socketio.on('remove_player')
@db_operation
def handle_remove_player(data):
    try:
        player_id = data['player_id']
        team_id = data['team_id']

        # Fetch the player and team from the database
        player = Player.query.get(player_id)
        team = Team.query.get(team_id)

        if player and team:
            # Remove the role in Discord asynchronously
            asyncio.run(remove_role_from_player(player))

            # Remove the player from the team
            player.team_id = None

            # Fetch the current season
            current_season = Season.query.order_by(Season.id.desc()).first()

            # Fetch season-specific stats from PlayerSeasonStats
            season_stats = PlayerSeasonStats.query.filter_by(player_id=player.id, season_id=current_season.id).first()

            # Emit the player_removed event with player and team data
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
        else:
            print(f"Player or team not found: Player ID {player_id}, Team ID {team_id}")
            emit('error', {'message': 'Player or team not found'}, broadcast=False)

    except Exception as e:
        logger.error(f"Error handling player removal: {str(e)}")
        emit('error', {'message': 'An error occurred while removing the player'}, broadcast=False)
        raise  # Reraise the exception for the decorator to handle rollback
