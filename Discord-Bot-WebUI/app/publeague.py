# app/publeague.py

"""
Pub League Module

This module defines the blueprint and routes for Pub League functionality,
including team management, season configuration, and Discord role assignments.
"""

# Standard library imports
import asyncio
import logging

# Third-party imports
from flask import Blueprint, render_template, redirect, url_for, request, g
from flask_login import login_required
from sqlalchemy.exc import SQLAlchemyError
from app.tasks.tasks_discord import process_discord_role_updates

# Local application imports
from app.decorators import role_required
from app.models import Season, League, Team, Player
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.discord_utils import delete_team_roles
from app.tasks.tasks_discord import cleanup_team_discord_resources_task, create_team_discord_resources_task, update_team_discord_resources_task

logger = logging.getLogger(__name__)

# Create the blueprint with a URL prefix.
publeague = Blueprint('publeague', __name__, url_prefix='/publeague')

# Register additional blueprints.
from app.season_routes import season_bp
from app.schedule_routes import schedule_bp
publeague.register_blueprint(season_bp, url_prefix='/seasons')
publeague.register_blueprint(schedule_bp, url_prefix='/schedules')


# assign_roles_to_players() REMOVED. It called discord_utils.assign_roles_to_player(),
# whose real signature is assign_roles_to_player(guild_id: int, player) — this passed the
# SQLAlchemy Session as guild_id. The Session got interpolated into the bot-API URL, which
# 404'd, logged an error, and raised NOTHING, so the per-player except swallowed it and the
# route reported success having assigned zero roles. It also ran Discord HTTP for the whole
# roster inside g.db_session's OPEN TRANSACTION (asyncio.run + semaphore(10)), which pins a
# pgbouncer slot for minutes -> "FATAL: idle transaction timeout".
#
# The route now dispatches the canonical batch task instead (process_discord_role_updates),
# which is what every other bulk role-sync surface in the app already uses.


@publeague.before_request
def before_request():
    """
    Set up current Pub League and ECS FC seasons before each request.
    
    Retrieves the current seasons from the database and stores them in the
    Flask global 'g' for use in subsequent routes.
    """
    session = g.db_session
    try:
        g.current_pub_league_season = session.query(Season).filter_by(
            league_type='Pub League', 
            is_current=True
        ).first()
        g.current_ecs_fc_season = session.query(Season).filter_by(
            league_type='ECS FC', 
            is_current=True
        ).first()
    except SQLAlchemyError as e:
        logger.error(f"Database error in before_request: {str(e)}")
        g.current_pub_league_season = None
        g.current_ecs_fc_season = None


@publeague.route('/clear_players', methods=['POST'])
@login_required
@role_required('Global Admin')
def clear_players():
    """
    Clear all players from the database, including their Discord roles.

    First, it clears Discord roles for all players with a Discord ID.
    Then, it deletes all player records.
    """
    session = g.db_session
    try:
        # Clear Discord roles for all players with a Discord ID.
        players = session.query(Player).filter(Player.discord_id.isnot(None)).all()
        for player in players:
            try:
                asyncio.run(delete_team_roles(session, player))
            except Exception as e:
                logger.error(f"Error clearing Discord roles for player {player.id}: {str(e)}")
        
        # Delete all player records.
        deleted_count = session.query(Player).delete()
        logger.info(f"Deleted {deleted_count} players")
        show_success('All players have been cleared.')
        return redirect(url_for('publeague.view_players'))
    except Exception as e:
        logger.error(f"Error clearing players: {str(e)}")
        show_error(f"Error clearing players: {str(e)}")
        raise


@publeague.route('/add_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def add_team():
    """
    Add a new team with associated Discord resources.

    Validates the input, creates a new team record, and enqueues a task to set up
    the corresponding Discord channel and roles.
    """
    session = g.db_session
    try:
        # Validate input.
        team_name = request.form.get('team_name', '').strip()
        league_name = request.form.get('league_name', '').strip()
        season_id = request.form.get('season_id', '').strip()

        if not all([team_name, league_name, season_id]):
            show_error('Team name, league name, and season ID are required.')
            return redirect(url_for('publeague.manage_teams'))

        # Retrieve the league.
        league = session.query(League).filter_by(name=league_name, season_id=season_id).first()
        if not league:
            show_error('League not found.')
            return redirect(url_for('publeague.manage_teams'))

        # Create and persist the team.
        new_team = Team(name=team_name, league=league)
        session.add(new_team)
        session.flush()  # Obtain new_team.id

        # Enqueue Discord channel creation as a Celery task.
        create_team_discord_resources_task.delay(new_team.id)

        show_success(f'Team "{team_name}" added successfully. Discord setup in progress...')
        return redirect(url_for('publeague.manage_teams'))
    except Exception as e:
        logger.error(f"Error creating team: {str(e)}")
        show_error(f"Error creating team: {str(e)}")
        raise


@publeague.route('/edit_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_team():
    """
    Edit a team's details and update its Discord resources.

    Expects the team ID and the new team name from the request form.
    """
    session = g.db_session
    try:
        team_id = request.form.get('team_id')
        new_team_name = request.form.get('team_name', '').strip()
        
        if not all([team_id, new_team_name]):
            show_error('Team ID and new team name are required.')
            return redirect(url_for('publeague.manage_teams'))

        team = session.query(Team).get(team_id)
        if not team:
            show_error('Team not found.')
            return redirect(url_for('publeague.manage_teams'))

        old_team_name = team.name
        team.name = new_team_name

        # Enqueue Discord update as a Celery task.
        update_team_discord_resources_task.delay(team_id, new_team_name)

        show_success(f'Team "{old_team_name}" renamed to "{new_team_name}". Discord update in progress...')
        return redirect(url_for('publeague.manage_teams'))
    except Exception as e:
        logger.error(f"Error updating team: {str(e)}")
        show_error(f"Error updating team: {str(e)}")
        raise


@publeague.route('/delete_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_team():
    """
    Delete a team and trigger cleanup of its Discord resources.
    """
    session = g.db_session
    try:
        team_id = request.form.get('team_id')
        if not team_id:
            show_error('Team ID is required.')
            return redirect(url_for('publeague.manage_teams'))

        team = session.query(Team).get(team_id)
        if not team:
            show_error('Team not found.')
            return redirect(url_for('publeague.manage_teams'))

        team_name = team.name

        # Guard: never delete a team that carries history/results.
        #   - matches & standings FKs are NO ACTION, so the delete would ERROR
        #     mid-request — AFTER Discord cleanup already fired, stranding Discord.
        #   - player_team_season → team is ON DELETE CASCADE, so deleting a team
        #     with history would SILENTLY destroy the roster snapshots that career
        #     & attendance stats depend on.
        # Only truly-empty placeholder teams (never played, no history) may be deleted.
        from app.models.matches import Match
        from app.models.stats import Standings
        from app.models import PlayerTeamSeason
        blocking = []
        match_ct = session.query(Match).filter(
            (Match.home_team_id == team.id) | (Match.away_team_id == team.id)
        ).count()
        if match_ct:
            blocking.append(f'{match_ct} match(es)')
        if session.query(Standings).filter_by(team_id=team.id).count():
            blocking.append('standings')
        history_ct = session.query(PlayerTeamSeason).filter_by(team_id=team.id).count()
        if history_ct:
            blocking.append(f'{history_ct} season-history record(s)')
        if blocking:
            show_error(
                f'Cannot delete "{team_name}" — it has {", ".join(blocking)}. Deleting it '
                f'would destroy historical stats/standings. Keep the team for the record.'
            )
            return redirect(url_for('publeague.manage_teams'))

        # Enqueue Discord cleanup ONLY now that we know the delete will proceed.
        cleanup_team_discord_resources_task.delay(team_id)

        session.delete(team)

        show_success(f'Team "{team_name}" deleted. Discord cleanup in progress...')
        return redirect(url_for('publeague.manage_teams'))
    except Exception as e:
        logger.error(f"Error deleting team: {str(e)}")
        show_error('An error occurred while deleting the team.')
        return redirect(url_for('publeague.manage_teams'))


@publeague.route('/manage_teams', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_teams():
    """
    Display and manage teams for the current seasons.

    Retrieves current seasons and their associated leagues, sorts leagues,
    and marks the first league for each season.
    """
    session = g.db_session
    try:
        seasons = session.query(Season).filter_by(is_current=True).all()

        # Retrieve leagues for each season.
        for season in seasons:
            leagues = session.query(League).filter_by(season_id=season.id).all()
            # Debug print; consider using logger.debug in production.
            print(f"DEBUG: Season {season.id} => leagues: {leagues}")
            season.leagues = leagues

        # Sort leagues and mark the first league for each season.
        for season in seasons:
            season.leagues.sort(key=lambda x: {'Premier': 1, 'Classic': 2, 'ECS FC': 3}.get(x.name, 99))
            first_league = True
            for league in season.leagues:
                league.is_first = first_league
                first_league = False

        session.commit()
        return render_template('manage_teams_flowbite.html', seasons=seasons)
    except Exception as e:
        session.rollback()
        logger.error(f"Error in manage_teams: {str(e)}")
        show_error('Error loading teams.')
        return redirect(url_for('main.index'))


@publeague.route('/assign_discord_roles', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def assign_discord_roles():
    """
    Bulk assign Discord roles to all eligible players.

    Retrieves players who have both a Discord ID and a team assignment,
    then assigns roles asynchronously.
    """
    session = g.db_session
    try:
        # Player.team_id DOES NOT EXIST — team membership is the player_teams many-to-many
        # (Player.teams). The AttributeError was swallowed by the except below, so this route
        # never once worked; it always flashed "Error occurred while assigning Discord roles."
        # teams.any() also beats primary_team_id, which would miss anyone rostered without a
        # primary team set. Select only discord_id — the task takes ids, not ORM objects.
        discord_ids = [
            row[0] for row in session.query(Player.discord_id).filter(
                Player.discord_id.isnot(None),
                Player.teams.any()
            ).distinct()
        ]

        if not discord_ids:
            show_info('No eligible players found for role assignment.')
            return redirect(url_for('publeague.manage_teams'))

        # only_add=True: this route ASSIGNS. The default reconcile also REVOKES, and a single
        # bad expected-role calculation would strip the whole roster's Discord access
        # (see the warning in tasks_discord._extract_batch_role_update_data).
        process_discord_role_updates.delay(discord_ids, only_add=True)

        # Honest wording: the work is queued, not done. The old copy claimed roles "have been
        # assigned" even when every single assignment failed.
        show_success(
            f'Discord role sync queued for {len(discord_ids)} players. '
            f'Changes should take effect within a few minutes.'
        )
        return redirect(url_for('publeague.manage_teams'))
    except Exception as e:
        logger.error(f"Error assigning Discord roles: {str(e)}")
        show_error('Error occurred while assigning Discord roles.')
        return redirect(url_for('publeague.manage_teams'))