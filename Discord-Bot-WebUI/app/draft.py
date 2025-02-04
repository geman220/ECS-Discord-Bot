from flask import Blueprint, render_template, redirect, url_for, flash, g
from flask_login import login_required
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import exists, and_, or_
from sqlalchemy import text
from app.sockets.session import socket_session
from contextlib import contextmanager
from app.models import (
   League, Player, Team, Season, PlayerSeasonStats,
   player_teams, player_league
)
from app.decorators import role_required
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
    session = g.db_session

    # A) Find ALL leagues named "Classic" (any season) => For player's membership
    all_classic_leagues = session.query(League).filter(League.name == 'Classic').all()
    if not all_classic_leagues:
        flash('No league(s) found with name "Classic".', 'danger')
        return redirect(url_for('main.index'))

    # B) Find the *current* "Classic" league => For the actual teams
    current_classic = (
        session.query(League)
        .join(League.season)
        .filter(League.name == 'Classic')
        .filter_by(is_current=True)
        .one_or_none()
    )
    if not current_classic:
        flash('No *current* Classic league found.', 'danger')
        return redirect(url_for('main.index'))

    # 1) TEAMS => only from the current classic
    teams = current_classic.teams
    team_ids = [t.id for t in teams]

    # 2) PLAYERS => belongs to "Classic" from any season + is_active
    classic_league_ids = [l.id for l in all_classic_leagues]

    belongs_to_classic = or_(
        Player.primary_league_id.in_(classic_league_ids),
        exists().where(
            and_(
                player_league.c.player_id == Player.id,
                player_league.c.league_id.in_(classic_league_ids)
            )
        )
    )
    is_active = Player.is_current_player.is_(True)

    # 3) Available = belongs_to_classic & is_active & not in these team_ids
    not_in_classic_teams = ~exists().where(
        and_(
            player_teams.c.player_id == Player.id,
            player_teams.c.team_id.in_(team_ids)
        )
    )

    available_players = (
        session.query(Player)
        .filter(belongs_to_classic)
        .filter(is_active)
        .filter(not_in_classic_teams)
        .order_by(Player.name.asc())
        .options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats)
        )
        .all()
    )

    # 4) Drafted = belongs_to_classic & is_active & in these team_ids
    drafted_players = (
        session.query(Player)
        .join(player_teams, player_teams.c.player_id == Player.id)
        .filter(player_teams.c.team_id.in_(team_ids))
        .filter(belongs_to_classic)
        .filter(is_active)
        .options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats),
            joinedload(Player.teams)
        )
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
        drafted_players_by_team=drafted_by_team
    )

@draft.route('/premier', endpoint='draft_premier')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_premier():
    session = g.db_session

    # A) All "Premier" leagues for player membership
    all_premier_leagues = session.query(League).filter(League.name == 'Premier').all()
    if not all_premier_leagues:
        flash('No league(s) found with name "Premier".', 'danger')
        return redirect(url_for('main.index'))

    # B) Current "Premier" for the actual teams
    current_premier = (
        session.query(League)
        .join(League.season)
        .filter(League.name == 'Premier')
        .filter_by(is_current=True)
        .one_or_none()
    )
    if not current_premier:
        flash('No *current* Premier league found.', 'danger')
        return redirect(url_for('main.index'))

    teams = current_premier.teams
    team_ids = [t.id for t in teams]

    premier_league_ids = [l.id for l in all_premier_leagues]
    belongs_to_premier = or_(
        Player.primary_league_id.in_(premier_league_ids),
        exists().where(
            and_(
                player_league.c.player_id == Player.id,
                player_league.c.league_id.in_(premier_league_ids)
            )
        )
    )
    is_active = Player.is_current_player.is_(True)

    not_in_premier_teams = ~exists().where(
        and_(
            player_teams.c.player_id == Player.id,
            player_teams.c.team_id.in_(team_ids)
        )
    )

    available_players = (
        session.query(Player)
        .filter(belongs_to_premier)
        .filter(is_active)
        .filter(not_in_premier_teams)
        .order_by(Player.name.asc())
        .options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats)
        )
        .all()
    )

    drafted_players = (
        session.query(Player)
        .join(player_teams, player_teams.c.player_id == Player.id)
        .filter(player_teams.c.team_id.in_(team_ids))
        .filter(belongs_to_premier)
        .filter(is_active)
        .order_by(Player.name.asc())
        .options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
            joinedload(Player.teams)
        )
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
        drafted_players_by_team=drafted_by_team
    )

@draft.route('/ecs_fc', endpoint='draft_ecs_fc')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_ecs_fc():
    session = g.db_session

    # A) All "ECS FC" leagues for player membership
    all_ecs_leagues = session.query(League).filter(League.name == 'ECS FC').all()
    if not all_ecs_leagues:
        flash('No league(s) named "ECS FC".', 'danger')
        return redirect(url_for('main.index'))

    # B) The "current" ECS FC for the actual teams
    current_ecs_fc = (
        session.query(League)
        .join(League.season)
        .filter(League.name == 'ECS FC')
        .filter_by(is_current=True)
        .one_or_none()
    )
    if not current_ecs_fc:
        flash('No *current* ECS FC league found.', 'danger')
        return redirect(url_for('main.index'))

    teams = current_ecs_fc.teams
    team_ids = [t.id for t in teams]

    ecs_league_ids = [l.id for l in all_ecs_leagues]
    belongs_to_ecs = or_(
        Player.primary_league_id.in_(ecs_league_ids),
        exists().where(
            and_(
                player_league.c.player_id == Player.id,
                player_league.c.league_id.in_(ecs_league_ids)
            )
        )
    )
    is_active = Player.is_current_player.is_(True)
    not_in_ecs_teams = ~exists().where(
        and_(
            player_teams.c.player_id == Player.id,
            player_teams.c.team_id.in_(team_ids)
        )
    )

    available_players = (
        session.query(Player)
        .filter(belongs_to_ecs)
        .filter(is_active)
        .filter(not_in_ecs_teams)
        .order_by(Player.name.asc())
        .options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats)
        )
        .all()
    )

    drafted_players = (
        session.query(Player)
        .join(player_teams, player_teams.c.player_id == Player.id)
        .filter(player_teams.c.team_id.in_(team_ids))
        .filter(belongs_to_ecs)
        .filter(is_active)
        .order_by(Player.name.asc())
        .options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
            joinedload(Player.teams)
        )
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
        drafted_players_by_team=drafted_by_team
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