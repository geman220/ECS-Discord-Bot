from app.season_routes import season_bp
from app.schedule_routes import schedule_bp
from flask import Blueprint, render_template, redirect, url_for, flash, request, g
from flask_login import login_required
from app.models import Season, League, Team, Player, Schedule
from app.decorators import role_required, handle_db_operation, query_operation
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from app.discord_utils import (
    create_discord_channel,
    delete_team_channel,
    rename_team_roles, 
    delete_team_roles,
    assign_roles_to_player
)
from app.db_utils import (
    update_discord_channel_id,
    update_discord_role_ids
)
import asyncio
import logging

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
@handle_db_operation()
def clear_players():
    try:
        Player.query.delete()
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
@handle_db_operation()
def update_publeague_team_name(season_id, league_name, team_name):
    try:
        league = League.query.filter_by(name=league_name, season_id=season_id).first_or_404()
        team = Team.query.filter_by(name=team_name, league_id=league.id).first_or_404()

        new_team_name = request.form.get('team_name')
        if new_team_name:
            team.name = new_team_name
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
    loop.run_until_complete(assign_roles_to_player(players))
    loop.close()
    
    flash('Discord roles have been assigned to all players.', 'success')
    return redirect(url_for('publeague.manage_teams'))

@publeague.route('/add_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@handle_db_operation()
def add_team():
    try:
        team_name = request.form.get('team_name', '').strip()
        league_name = request.form.get('league_name', '').strip()
        season_id = request.form.get('season_id', '').strip()

        if not all([team_name, league_name, season_id]):
            flash('Team name, league name, and season ID are required.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        league = League.query.filter_by(name=league_name, season_id=season_id).first()
        if not league:
            flash('League not found.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        # Create team
        new_team = Team(name=team_name, league=league)  # Use relationship
        
        # Create Discord channel and roles
        asyncio.run(create_discord_channel(team_name, league.name, new_team.id))
        
        flash(f'Team "{team_name}" added to league "{league_name}".', 'success')
        return redirect(url_for('publeague.manage_teams'))
    except Exception as e:
        logger.error(f"Error creating team: {str(e)}")
        flash(f"Error creating team: {str(e)}", 'danger')
        raise

@publeague.route('/edit_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@handle_db_operation()
def edit_team():
    try:
        team_id = request.form.get('team_id')
        new_team_name = request.form.get('team_name', '').strip()
        if not all([team_id, new_team_name]):
            flash('Team ID and new team name are required.', 'danger')
            return redirect(url_for('publeague.manage_teams'))
        
        team = Team.query.get(team_id)
        if not team:
            flash('Team not found.', 'danger')
            return redirect(url_for('publeague.manage_teams'))
            
        old_team_name = team.name
        team.name = new_team_name
        
        # Update Discord channel and roles
        asyncio.run(rename_team_roles(team, new_team_name))
        
        flash(f'Team "{old_team_name}" updated to "{new_team_name}" and Discord updated.', 'success')
        return redirect(url_for('publeague.manage_teams'))
    except Exception as e:
        logger.error(f"Error updating team: {str(e)}")
        flash(f"Error updating team: {str(e)}", 'danger')
        raise

@publeague.route('/delete_team', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@handle_db_operation()
def delete_team():
    try:
        team_id = request.form.get('team_id')
        if not team_id:
            flash('Team ID is required.', 'danger')
            return redirect(url_for('publeague.manage_teams'))
            
        team = Team.query.get(team_id)
        if not team:
            flash('Team not found.', 'danger')
            return redirect(url_for('publeague.manage_teams'))
            
        team_name = team.name
        # Delete Discord entities
        asyncio.run(delete_team_channel(team))
        asyncio.run(delete_team_roles(team))
        
        # Mark for deletion (decorator handles the session)
        team.delete()
        
        flash(f'Team "{team_name}" has been deleted.', 'success')
        return redirect(url_for('publeague.manage_teams'))
    except Exception as e:
        logger.error(f"Error deleting team: {str(e)}")
        flash(f"Error deleting team: {str(e)}", 'danger')
        raise

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
