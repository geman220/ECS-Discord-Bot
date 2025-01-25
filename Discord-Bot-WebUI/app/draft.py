from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import exists, and_
from sqlalchemy import text
from app.sockets.session import socket_session
from contextlib import contextmanager
from app.models import (
   League, Player, Team, Season, PlayerSeasonStats,
   player_teams
)
from app.decorators import role_required, cleanup_db_connection
from app.core import socketio, db
from app.core.session_manager import managed_session
from flask_socketio import emit
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task
from app.db_utils import mark_player_for_discord_update
import logging

logger = logging.getLogger(__name__)
draft = Blueprint('draft', __name__)

@draft.route('/classic', endpoint='draft_classic')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_classic():
    with managed_session() as session:
        current_season = (
            session.query(Season)
            .filter_by(league_type='Pub League', is_current=True)
            .first()
        )
        if not current_season:
            flash('No current Pub League season found.', 'danger')
            return redirect(url_for('main.index'))

        classic_league = (
            session.query(League)
            .options(joinedload(League.teams))
            .filter_by(name='Classic', season_id=current_season.id)
            .first()
        )
        if not classic_league:
            flash('No Classic league found.', 'danger')
            return redirect(url_for('main.index'))

        teams = classic_league.teams
        team_ids = [t.id for t in teams]

        not_in_classic_teams = ~exists().where(
            and_(
                player_teams.c.player_id == Player.id,
                player_teams.c.team_id.in_(team_ids)
            )
        )

        available_players = (
            session.query(Player)
            .options(joinedload(Player.career_stats), joinedload(Player.season_stats))
            .filter(not_in_classic_teams)
            .order_by(Player.name.asc())
            .all()
        )

        drafted_players = (
            session.query(Player)
            .options(
                joinedload(Player.career_stats),
                joinedload(Player.season_stats),
                joinedload(Player.teams)
            )
            .join(player_teams, player_teams.c.player_id == Player.id)
            .filter(player_teams.c.team_id.in_(team_ids))
            .order_by(Player.name.asc())
            .all()
        )

        drafted_by_team = {t.id: [] for t in teams}
        for p in drafted_players:
            for tm in p.teams:
                if tm.id in drafted_by_team:
                    drafted_by_team[tm.id].append(p)
                    break

        return render_template(
            'draft_classic.html',
            teams=teams,
            available_players=available_players,
            drafted_players_by_team=drafted_by_team,
            season=current_season
        )

@draft.route('/premier', endpoint='draft_premier')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
@cleanup_db_connection
def draft_premier():
    with managed_session() as session:
        current_season = (
            session.query(Season)
            .filter_by(league_type='Pub League', is_current=True)
            .first()
        )
        if not current_season:
            flash('No current Pub League season found.', 'danger')
            return redirect(url_for('main.index'))

        premier_league = (
            session.query(League)
            .options(joinedload(League.teams))
            .filter_by(name='Premier', season_id=current_season.id)
            .first()
        )
        if not premier_league:
            flash('No Premier league found.', 'danger')
            return redirect(url_for('main.index'))

        teams = premier_league.teams
        team_ids = [t.id for t in teams]

        not_in_premier_teams = ~exists().where(
            and_(
                player_teams.c.player_id == Player.id,
                player_teams.c.team_id.in_(team_ids)
            )
        )

        available_players = (
            session.query(Player)
            .options(joinedload(Player.career_stats), joinedload(Player.season_stats))
            .filter(not_in_premier_teams)
            .order_by(Player.name.asc())
            .all()
        )

        drafted_players = (
            session.query(Player)
            .options(
                joinedload(Player.career_stats),
                joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
                joinedload(Player.teams)
            )
            .join(player_teams, player_teams.c.player_id == Player.id)
            .filter(player_teams.c.team_id.in_(team_ids))
            .order_by(Player.name.asc())
            .all()
        )

        drafted_by_team = {t.id: [] for t in teams}
        for p in drafted_players:
            for tm in p.teams:
                if tm.id in drafted_by_team:
                    drafted_by_team[tm.id].append(p)
                    break

        return render_template(
            'draft_premier.html',
            teams=teams,
            available_players=available_players,
            drafted_players_by_team=drafted_by_team,
            season=current_season
        )

@draft.route('/ecs_fc', endpoint='draft_ecs_fc')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
@cleanup_db_connection
def draft_ecs_fc():
    with managed_session() as session:
        current_season = (
            session.query(Season)
            .filter_by(league_type='ECS FC', is_current=True)
            .first()
        )
        if not current_season:
            flash('No current ECS FC season found.', 'danger')
            return redirect(url_for('main.index'))

        ecs_fc_league = (
            session.query(League)
            .options(joinedload(League.teams))
            .filter_by(name='ECS FC', season_id=current_season.id)
            .first()
        )
        if not ecs_fc_league:
            flash('No ECS FC league found.', 'danger')
            return redirect(url_for('main.index'))

        teams = ecs_fc_league.teams
        team_ids = [t.id for t in teams]

        not_in_ecs_teams = ~exists().where(
            and_(
                player_teams.c.player_id == Player.id,
                player_teams.c.team_id.in_(team_ids)
            )
        )

        available_players = (
            session.query(Player)
            .options(joinedload(Player.career_stats), joinedload(Player.season_stats))
            .filter(not_in_ecs_teams)
            .order_by(Player.name.asc())
            .all()
        )

        drafted_players = (
            session.query(Player)
            .options(
                joinedload(Player.career_stats),
                joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
                joinedload(Player.teams)
            )
            .join(player_teams, player_teams.c.player_id == Player.id)
            .filter(player_teams.c.team_id.in_(team_ids))
            .order_by(Player.name.asc())
            .all()
        )

        drafted_by_team = {t.id: [] for t in teams}
        for p in drafted_players:
            for tm in p.teams:
                if tm.id in drafted_by_team:
                    drafted_by_team[tm.id].append(p)
                    break

        return render_template(
            'draft_ecs_fc.html',
            teams=teams,
            available_players=available_players,
            drafted_players_by_team=drafted_by_team,
            season=current_season
        )


#
# Socket.IO Event Handlers
#
@socketio.on('draft_player', namespace='/draft')
def handle_draft_player(data):
    """
    Drafts a player to a team, sets them as primary if none is set,
    dispatches tasks for Discord role updates, and emits 'player_drafted'.
    """

    with socket_session(db.engine) as session:
        try:
            session.execute(text("SET LOCAL statement_timeout = '10s'"))

            player = session.query(Player).get(data['player_id'])
            team = session.query(Team).get(data['team_id'])

            if not player or not team:
                emit('error', {'message': 'Player or team not found'}, broadcast=False)
                return

            # Add team if not already in player's teams
            if team not in player.teams:
                player.teams.append(team)

            # If player has no primary team, set this one
            if not player.primary_team_id:
                player.primary_team_id = team.id

            # Mark for Discord sync / Trigger role assignment for exactly this team
            mark_player_for_discord_update(session, player.id)
            # Pass both player_id AND team_id
            assign_roles_to_player_task.delay(player_id=player.id, team_id=team.id)

            # Prepare stats for the response
            current_season = session.query(Season).get(team.league.season_id)
            stats = {
                'goals': player.season_goals(current_season.id) if current_season else 0,
                'assists': player.season_assists(current_season.id) if current_season else 0,
                'yellow_cards': player.season_yellow_cards(current_season.id) if current_season else 0,
                'red_cards': player.season_red_cards(current_season.id) if current_season else 0
            }

            emit('player_drafted', {
                'player_id': player.id,
                'player_name': player.name,
                'team_id': team.id,
                'team_name': team.name,
                'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
                **stats,
                'player_notes': player.player_notes or 'No notes available'
            }, broadcast=True)

        except Exception as e:
            logger.error(f"Error handling player draft: {e}", exc_info=True)
            emit('error', {'message': 'Draft failed - please try again'}, broadcast=False)
            raise

@socketio.on('remove_player', namespace='/draft')
def handle_remove_player(data):
    """
    Removes a player from a team, unsets primary if applicable,
    dispatches a task for Discord role updates, and emits 'player_removed'.
    """

    with socket_session(db.engine) as session:
        try:
            session.execute(text("SET LOCAL statement_timeout = '10s'"))

            player = session.query(Player).get(data['player_id'])
            team = session.query(Team).get(data['team_id'])

            if not player or not team:
                emit('error', {'message': 'Player or team not found'}, broadcast=False)
                return

            # Remove the team if currently assigned
            if team in player.teams:
                player.teams.remove(team)

            # Reset primary if this was the player's current primary team
            if player.primary_team_id == team.id:
                player.primary_team_id = None

            # Trigger removal for this exact team
            remove_player_roles_task.delay(player.id, team.id)

            current_season = session.query(Season).get(team.league.season_id)
            stats = {
                'goals': player.season_goals(current_season.id) if current_season else 0,
                'assists': player.season_assists(current_season.id) if current_season else 0,
                'yellow_cards': player.season_yellow_cards(current_season.id) if current_season else 0,
                'red_cards': player.season_red_cards(current_season.id) if current_season else 0
            }

            emit('player_removed', {
                'player_id': player.id,
                'player_name': player.name,
                'team_id': team.id,
                'team_name': team.name,
                'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
                **stats,
                'player_notes': player.player_notes or 'No notes available'
            }, broadcast=True)

        except Exception as e:
            logger.error(f"Error handling player removal: {e}", exc_info=True)
            emit('error', {'message': 'Remove failed - please try again'}, broadcast=False)
            raise