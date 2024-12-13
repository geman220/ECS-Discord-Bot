from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app as app, g, abort
from flask_login import login_required
from sqlalchemy.orm import joinedload, Session
from app.models import League, Player, Team, Season, PlayerSeasonStats
from app.decorators import role_required
from app.routes import get_current_season_and_year
from app.core import socketio
from flask_socketio import emit
from app.discord_utils import assign_roles_to_player
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task
from app.db_utils import mark_player_for_discord_update
import asyncio
import logging

logger = logging.getLogger(__name__)

draft = Blueprint('draft', __name__)

@draft.route('/classic', endpoint='draft_classic')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_classic():
    session: Session = g.db_session
    try:
        classic_league = (session.query(League)
                          .options(joinedload(League.teams))
                          .filter_by(name='Classic')
                          .first())
        
        if not classic_league:
            flash('Classic league not found.', 'danger')
            return redirect(url_for('main.index'))

        teams = classic_league.teams

        current_season_name, current_year = get_current_season_and_year()
        current_season = session.query(Season).filter_by(name=current_season_name).first()

        if not current_season:
            flash('Current season not found.', 'danger')
            return redirect(url_for('main.index'))

        available_players = (session.query(Player)
                             .options(
                                 joinedload(Player.career_stats),
                                 joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
                                 joinedload(Player.team)
                             )
                             .filter_by(league_id=classic_league.id, team_id=None)
                             .order_by(Player.name.asc())
                             .all())

        for player in available_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

        drafted_players = (session.query(Player)
                           .options(
                               joinedload(Player.career_stats),
                               joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
                               joinedload(Player.team)
                           )
                           .filter(
                               Player.league_id == classic_league.id,
                               Player.team_id.isnot(None)
                           )
                           .order_by(Player.name.asc())
                           .all())

        for player in drafted_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

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

@draft.route('/premier', endpoint='draft_premier')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_premier():
    session: Session = g.db_session
    try:
        premier_league = (session.query(League)
                          .options(joinedload(League.teams))
                          .filter_by(name='Premier')
                          .first())
        
        if not premier_league:
            flash('Premier league not found.', 'danger')
            return redirect(url_for('main.index'))

        teams = premier_league.teams
        current_season_name, current_year = get_current_season_and_year()
        season = session.query(Season).filter_by(name=current_season_name).first()
        
        if not season:
            flash('Current season not found.', 'danger')
            return redirect(url_for('main.index'))

        available_players = (session.query(Player)
                             .options(
                                 joinedload(Player.career_stats),
                                 joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
                                 joinedload(Player.team)
                             )
                             .filter_by(league_id=premier_league.id, team_id=None)
                             .order_by(Player.name.asc())
                             .all())

        for player in available_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

        drafted_players = (session.query(Player)
                           .options(
                               joinedload(Player.career_stats),
                               joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
                               joinedload(Player.team)
                           )
                           .filter(
                               Player.league_id == premier_league.id,
                               Player.team_id.isnot(None)
                           )
                           .order_by(Player.name.asc())
                           .all())

        for player in drafted_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

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

@draft.route('/ecs_fc', endpoint='draft_ecs_fc')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_ecs_fc():
    session: Session = g.db_session
    try:
        ecs_fc_league = (session.query(League)
                         .options(joinedload(League.teams))
                         .filter_by(name='ECS FC')
                         .first())

        if not ecs_fc_league:
            flash('ECS FC league not found.', 'danger')
            return redirect(url_for('main.index'))

        teams = ecs_fc_league.teams
        current_season_name, current_year = get_current_season_and_year()
        current_season = session.query(Season).filter_by(name=current_season_name).first()

        if not current_season:
            flash('Current season not found.', 'danger')
            return redirect(url_for('main.index'))

        available_players = (session.query(Player)
                             .options(
                                 joinedload(Player.career_stats),
                                 joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
                                 joinedload(Player.team)
                             )
                             .filter_by(
                                 league_id=ecs_fc_league.id,
                                 team_id=None
                             )
                             .order_by(Player.name.asc())
                             .all())

        for player in available_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

        drafted_players = (session.query(Player)
                           .options(
                               joinedload(Player.career_stats),
                               joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
                               joinedload(Player.team)
                           )
                           .filter(
                               Player.league_id == ecs_fc_league.id,
                               Player.team_id.isnot(None)
                           )
                           .order_by(Player.name.asc())
                           .all())

        for player in drafted_players:
            _ = list(player.career_stats) if player.career_stats else []
            _ = list(player.season_stats) if player.season_stats else []

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

@socketio.on('draft_player', namespace='/draft')
def handle_draft_player(data):
    session = app.SessionLocal()  # Create a new session explicitly
    try:
        player_id = data['player_id']
        team_id = data['team_id']

        player = (session.query(Player)
                  .options(joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season))
                  .filter(Player.id == player_id)
                  .first())
        if not player:
            emit('error', {'message': 'Player not found'}, broadcast=False)
            session.rollback()
            return

        team = session.query(Team).filter_by(id=team_id).first()
        if not team:
            emit('error', {'message': 'Team not found'}, broadcast=False)
            session.rollback()
            return

        player.team_id = team_id

        mark_player_for_discord_update(session, player_id)
        assign_roles_to_player_task.delay(player_id)

        current_season = session.query(Season).order_by(Season.id.desc()).first()
        season_stats = (session.query(PlayerSeasonStats)
                        .filter_by(player_id=player.id, season_id=current_season.id)
                        .first() if current_season else None)

        # Commit changes
        session.commit()

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
        session.rollback()
        emit('error', {'message': 'An error occurred while drafting the player'}, broadcast=False)
    finally:
        session.close()  # Close the session in a finally block

@socketio.on('remove_player', namespace='/draft')
def handle_remove_player(data):
    # Create a new session from the application's SessionLocal
    session = app.SessionLocal()  
    try:
        player_id = data['player_id']
        team_id = data['team_id']

        player = session.query(Player).filter_by(id=player_id).first()
        team = session.query(Team).filter_by(id=team_id).first()

        if player and team:
            # Update player's team assignment
            player.team_id = None
            # Commit these changes before triggering role removal tasks
            session.commit()

            # Schedule role removal task after commit
            remove_player_roles_task.delay(player.id)

            current_season = session.query(Season).order_by(Season.id.desc()).first()
            season_stats = (session.query(PlayerSeasonStats)
                            .filter_by(player_id=player.id, season_id=current_season.id)
                            .first() if current_season else None)

            emit('player_removed', {
                'player_id': player.id,
                'player_name': player.name,
                'team_id': team.id,
                'team_name': team.name,
                'goals': season_stats.goals if season_stats else 0,
                'assists': season_stats.assists if season_stats else 0,
                'yellow_cards': season_stats.yellow_cards if season_stats else 0,
                'red_cards': season_stats.red_cards if season_stats else 0,
                'player_notes': player.player_notes or 'No notes available',
                'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png'
            }, broadcast=True)
        else:
            emit('error', {'message': 'Player or team not found'}, broadcast=False)

    except Exception as e:
        # If there's an error, rollback the session
        session.rollback()
        logger.error(f"Error handling player removal: {str(e)}", exc_info=True)
        emit('error', {'message': 'An error occurred while removing the player'}, broadcast=False)
        raise
    finally:
        # Always close the session
        session.close()