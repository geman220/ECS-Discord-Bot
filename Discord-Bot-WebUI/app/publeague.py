from flask import Blueprint, render_template, redirect, url_for, flash, request, g, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Season, League, Team, Player, Schedule
from app.decorators import role_required, db_operation, query_operation
from datetime import datetime, timedelta
from sqlalchemy import cast, Integer
from sqlalchemy.orm import joinedload
from app.discord_utils import create_discord_channel, delete_discord_channel, rename_discord_channel, rename_discord_roles, delete_discord_roles, assign_role_to_player, process_role_assignments
from .season_routes import season_bp
from .schedule_routes import schedule_bp
import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

publeague = Blueprint('publeague', __name__, url_prefix='/publeague')

# Registering blueprints under publeague
publeague.register_blueprint(season_bp, url_prefix='/seasons')
publeague.register_blueprint(schedule_bp, url_prefix='/schedules')

async def assign_roles_to_players(players):
    semaphore = asyncio.Semaphore(10)  # Limit to 10 concurrent tasks

    async def sem_task(player):
        async with semaphore:
            await assign_role_to_player(player)

    await asyncio.gather(*(sem_task(player) for player in players))

def get_latest_season(league_type):
    latest_season = Season.query.filter_by(league_type=league_type, is_current=True).first()
    if not latest_season:
        flash(f'No current {league_type} season found. Please create a season first.', 'danger')
        return None
    return latest_season

@publeague.before_app_request
def before_request():
    g.current_pub_league_season = Season.query.filter_by(league_type='Pub League', is_current=True).first()
    g.current_ecs_fc_season = Season.query.filter_by(league_type='ECS FC', is_current=True).first()

def get_matches_by_league(league_id):
    matches = Schedule.query.filter_by(league_id=league_id).all()
    return matches

# Clear Players
@publeague.route('/clear_players', methods=['POST'])
@login_required
@role_required('Global Admin')
@db_operation
def clear_players():
    try:
        Player.query.delete()
        # No need to call db.session.commit(); handled by decorator
        flash('All players have been cleared.', 'success')
    except Exception as e:
        logger.error(f'Error clearing players: {str(e)}')
        flash(f'Error clearing players: {str(e)}', 'danger')
        raise  # Reraise exception for decorator to handle rollback
    return redirect(url_for('publeague.view_players'))

# Update Team Name
@publeague.route('/seasons/<int:season_id>/teams/<string:league_name>/<string:team_name>/update', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def update_publeague_team_name(season_id, league_name, team_name):
    try:
        league = League.query.filter_by(name=league_name, season_id=season_id).first_or_404()
        team = Team.query.filter_by(name=team_name, league_id=league.id).first_or_404()

        new_team_name = request.form.get('team_name')
        if new_team_name:
            team.name = new_team_name
            # No need to call db.session.commit(); handled by decorator
            flash(f'Team name updated to "{new_team_name}".', 'success')
        else:
            flash('Team name cannot be empty.', 'danger')
    except Exception as e:
        logger.error(f"Error updating team name: {e}")
        flash('Error occurred while updating the team name.', 'danger')
        raise  # Reraise exception for decorator to handle rollback

    return redirect(url_for('publeague.manage_teams', season_id=season_id))

def choose_team(league, match_num, team_type):
    teams = league.teams
    team = teams[(match_num - 1) % len(teams)]
    return team.name if team_type == 'A' else teams[(match_num) % len(teams)].name

def calculate_date_for_week(start_date, week):
    # This function calculates the date for each week based on the start date of the season
    return start_date + timedelta(weeks=week - 1)

@publeague.route('/assign_discord_roles', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def assign_discord_roles():
    players = Player.query.filter(Player.discord_id != None, Player.team_id != None).all()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    results = loop.run_until_complete(process_role_assignments(players))
    loop.close()
    
    return render_template('role_assignment_results.html', results=results)

# Add Team
@publeague.route('/add_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def add_team():
    team_name = request.form.get('team_name', '').strip()
    league_name = request.form.get('league_name', '').strip()
    season_id = request.form.get('season_id', '').strip()

    if not team_name or not league_name or not season_id:
        flash('Team name, league name, and season ID are required.', 'danger')
        return redirect(url_for('publeague.manage_teams'))

    try:
        # Fetch the league
        league = League.query.filter_by(name=league_name, season_id=season_id).first()
        if not league:
            flash('League not found.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        # Check if team already exists
        existing_team = Team.query.filter_by(name=team_name, league_id=league.id).first()
        if existing_team:
            flash(f'Team "{team_name}" already exists in league "{league_name}".', 'warning')
            return redirect(url_for('publeague.manage_teams'))

        # Create the team
        new_team = Team(name=team_name, league_id=league.id)
        db.session.add(new_team)
        db.session.flush()  # Flush to get the new_team ID

        # Handle Discord channel creation
        division = "pl classic" if "classic" in league_name.lower() else "pl premier" if "premier" in league_name.lower() else "ecsfc"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(create_discord_channel(team_name, division, new_team.id))
        loop.close()

        flash(f'Team "{team_name}" added to league "{league_name}".', 'success')
    except Exception as e:
        logger.error(f"Error creating team: {str(e)}")
        flash(f"Error creating team: {str(e)}", 'danger')
        raise  # Reraise exception for decorator to handle rollback
    return redirect(url_for('publeague.manage_teams'))

# Edit Team
@publeague.route('/edit_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def edit_team():
    team_id = request.form.get('team_id')
    new_team_name = request.form.get('team_name', '').strip()

    if not team_id or not new_team_name:
        flash('Team ID and new team name are required.', 'danger')
        return redirect(url_for('publeague.manage_teams'))

    try:
        # Fetch the team
        team = Team.query.get(team_id)
        if not team:
            flash('Team not found.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        old_team_name = team.name
        team.name = new_team_name
        db.session.flush()  # Flush to ensure team ID and changes are recognized
        
        # Handle Discord updates
        async def update_discord():
            await rename_discord_channel(team, new_team_name)
            await rename_discord_roles(team, new_team_name)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(update_discord())
        loop.close()

        flash(f'Team "{old_team_name}" updated to "{new_team_name}" and Discord updated.', 'success')

    except Exception as e:
        logger.error(f"Error updating team: {str(e)}")
        flash(f"Error updating team: {str(e)}", 'danger')
        raise  # Reraise exception for decorator to handle rollback

    return redirect(url_for('publeague.manage_teams'))

# Delete Team
@publeague.route('/delete_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def delete_team():
    team_id = request.form.get('team_id')

    if not team_id:
        flash('Team ID is required.', 'danger')
        return redirect(url_for('publeague.manage_teams'))

    try:
        # Fetch the team
        team = Team.query.get(team_id)
        if not team:
            flash('Team not found.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        team_name = team.name

        # Handle Discord deletion
        async def delete_discord_entities():
            await delete_discord_channel(team)
            await delete_discord_roles(team)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(delete_discord_entities())
        loop.close()

        # Delete the team from the database
        db.session.delete(team)
        # No need to call db.session.commit(); handled by decorator

        flash(f'Team "{team_name}" has been deleted.', 'success')

    except Exception as e:
        logger.error(f"Error deleting team: {str(e)}")
        flash(f"Error deleting team: {str(e)}", 'danger')
        raise  # Reraise exception for decorator to handle rollback

    return redirect(url_for('publeague.manage_teams'))

# Manage Teams
@publeague.route('/manage_teams', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_teams():
    # Fetch all current seasons with leagues and teams eagerly loaded
    seasons = Season.query.options(
        joinedload(Season.leagues).joinedload(League.teams)
    ).filter_by(is_current=True).all()

    # Define the desired league order
    league_order = {'Premier': 1, 'Classic': 2, 'ECS FC': 3}

    # For each season, sort its leagues
    for season in seasons:
        # Sort the leagues based on the desired order
        season.leagues.sort(key=lambda x: league_order.get(x.name, 99))

    return render_template('manage_teams.html', seasons=seasons)