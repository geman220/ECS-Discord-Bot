from flask import Blueprint, render_template, redirect, url_for, flash, request, g
from flask_login import login_required
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
from app.decorators import role_required
from app.models import Season, League, Team, Player, Schedule
from app.discord_utils import (
    create_discord_channel,
    delete_team_channel,
    rename_team_roles, 
    delete_team_roles,
    assign_roles_to_player
)
import asyncio
import logging

logger = logging.getLogger(__name__)

publeague = Blueprint('publeague', __name__, url_prefix='/publeague')

# Register blueprints
from app.season_routes import season_bp
from app.schedule_routes import schedule_bp
publeague.register_blueprint(season_bp, url_prefix='/seasons')
publeague.register_blueprint(schedule_bp, url_prefix='/schedules')

async def assign_roles_to_players(session, players):
    """Assign Discord roles to multiple players with rate limiting."""
    semaphore = asyncio.Semaphore(10)
    
    async def sem_task(player):
        async with semaphore:
            try:
                await assign_roles_to_player(session, player)
            except Exception as e:
                logger.error(f"Error assigning roles to player {player.id}: {str(e)}")
                # Continue processing other players even if one fails

    try:
        await asyncio.gather(*(sem_task(player) for player in players))
    except Exception as e:
        logger.error(f"Error in role assignment batch: {str(e)}")
        raise

@publeague.before_request
def before_request():
    """Setup current seasons before each request."""
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
    """Clear all players from the database."""
    session = g.db_session
    try:
        # First, clear Discord roles for all players
        players = session.query(Player).filter(Player.discord_id.isnot(None)).all()
        for player in players:
            try:
                asyncio.run(delete_team_roles(session, player))
            except Exception as e:
                logger.error(f"Error clearing Discord roles for player {player.id}: {str(e)}")
        
        # Then delete all players
        deleted_count = session.query(Player).delete()
        logger.info(f"Deleted {deleted_count} players")
        flash('All players have been cleared.', 'success')
        return redirect(url_for('publeague.view_players'))
    except Exception as e:
        logger.error(f'Error clearing players: {str(e)}')
        flash(f'Error clearing players: {str(e)}', 'danger')
        raise

@publeague.route('/add_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def add_team():
    """Add a new team with Discord channel and roles."""
    session = g.db_session
    try:
        # Validate input
        team_name = request.form.get('team_name', '').strip()
        league_name = request.form.get('league_name', '').strip()
        season_id = request.form.get('season_id', '').strip()

        if not all([team_name, league_name, season_id]):
            flash('Team name, league name, and season ID are required.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        # Get league
        league = session.query(League).filter_by(name=league_name, season_id=season_id).first()
        if not league:
            flash('League not found.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        # Create and persist team
        new_team = Team(name=team_name, league=league)
        session.add(new_team)
        session.flush()  # Get new_team.id

        # Queue Discord channel creation as a Celery task
        from app.tasks.tasks_discord import create_team_discord_resources_task
        create_team_discord_resources_task.delay(new_team.id)

        flash(f'Team "{team_name}" added successfully. Discord setup in progress...', 'success')
        return redirect(url_for('publeague.manage_teams'))
    except Exception as e:
        logger.error(f"Error creating team: {str(e)}")
        flash(f"Error creating team: {str(e)}", 'danger')
        raise

@publeague.route('/edit_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_team():
    """Edit team details and update Discord."""
    session = g.db_session
    try:
        team_id = request.form.get('team_id')
        new_team_name = request.form.get('team_name', '').strip()
        
        if not all([team_id, new_team_name]):
            flash('Team ID and new team name are required.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        team = session.query(Team).get(team_id)
        if not team:
            flash('Team not found.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        old_team_name = team.name
        team.name = new_team_name

        # Queue Discord update as a Celery task
        from app.tasks.tasks_discord import update_team_discord_resources_task
        update_team_discord_resources_task.delay(team_id, new_team_name)

        flash(f'Team "{old_team_name}" renamed to "{new_team_name}". Discord update in progress...', 'success')
        return redirect(url_for('publeague.manage_teams'))
    except Exception as e:
        logger.error(f"Error updating team: {str(e)}")
        flash(f"Error updating team: {str(e)}", 'danger')
        raise

@publeague.route('/delete_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_team():
    session = g.db_session
    try:
        team_id = request.form.get('team_id')
        if not team_id:
            flash('Team ID is required.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        team = session.query(Team).get(team_id)
        if not team:
            flash('Team not found.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        team_name = team.name
        
        # Queue Discord cleanup
        from app.tasks.tasks_discord import cleanup_team_discord_resources_task
        cleanup_team_discord_resources_task.delay(team_id)

        session.delete(team)
        
        flash(f'Team "{team_name}" deleted. Discord cleanup in progress...', 'success')
        return redirect(url_for('publeague.manage_teams'))

    except Exception as e:
        logger.error(f"Error deleting team: {str(e)}")
        flash('An error occurred while deleting the team.', 'danger')
        return redirect(url_for('publeague.manage_teams'))

@publeague.route('/manage_teams', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_teams():
    session = g.db_session
    try:
        seasons = (
            session.query(Season)
            .filter_by(is_current=True)
            .all()
        )

        # Manually get leagues for each season
        for season in seasons:
            leagues = session.query(League).filter_by(season_id=season.id).all()
            print(f"DEBUG: Season {season.id} => leagues: {leagues}")
            season.leagues = leagues

        # Sort and mark first league
        first_league = True
        for season in seasons:
            season.leagues.sort(key=lambda x: {'Premier': 1, 'Classic': 2, 'ECS FC': 3}.get(x.name, 99))
            first_league = True  # <-- reset here for every season
            for league in season.leagues:
                league.is_first = first_league
                first_league = False

        session.commit()
        return render_template('manage_teams.html', seasons=seasons)
    except Exception as e:
        session.rollback()
        logger.error(f"Error in manage_teams: {str(e)}")
        flash('Error loading teams.', 'danger')
        return redirect(url_for('main.index'))

@publeague.route('/assign_discord_roles', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def assign_discord_roles():
    """Bulk assign Discord roles to all eligible players."""
    session = g.db_session
    try:
        # Get all players with Discord IDs and team assignments
        players = session.query(Player).filter(
            Player.discord_id.isnot(None),
            Player.team_id.isnot(None)
        ).all()

        if not players:
            flash('No eligible players found for role assignment.', 'info')
            return redirect(url_for('publeague.manage_teams'))

        # Process role assignments
        asyncio.run(assign_roles_to_players(session, players))
        
        flash('Discord roles have been assigned to all eligible players.', 'success')
        return redirect(url_for('publeague.manage_teams'))
    except Exception as e:
        logger.error(f"Error assigning Discord roles: {str(e)}")
        flash('Error occurred while assigning Discord roles.', 'danger')
        return redirect(url_for('publeague.manage_teams'))