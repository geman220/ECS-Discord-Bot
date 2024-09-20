from flask import Blueprint, render_template, redirect, url_for, flash, request, g, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Season, League, Team, Player, Schedule
from app.decorators import role_required
from datetime import datetime, timedelta
from sqlalchemy import cast, Integer
from sqlalchemy.orm import joinedload
from app.discord_utils import create_discord_channel, delete_discord_channel, rename_discord_channel,  rename_discord_roles, delete_discord_roles, rename_discord_role, create_discord_role, create_discord_roles
from .season_routes import season_bp
from .schedule_routes import schedule_bp
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

publeague = Blueprint('publeague', __name__, url_prefix='/publeague')

# Registering blueprints under publeague
publeague.register_blueprint(season_bp, url_prefix='/seasons')
publeague.register_blueprint(schedule_bp, url_prefix='/schedules')

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

# Manage Teams (Add)
@publeague.route('/teams', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_teams():
    # Fetch the current seasons for Pub League and ECS FC
    current_pub_league_season = Season.query.filter_by(league_type='Pub League', is_current=True).first()
    current_ecs_fc_season = Season.query.filter_by(league_type='ECS FC', is_current=True).first()

    if not current_pub_league_season and not current_ecs_fc_season:
        flash('No current seasons found for either Pub League or ECS FC. Please create seasons first.', 'warning')
        return redirect(url_for('publeague.manage_seasons'))

    if request.method == 'POST':
        league_name = request.form.get('league_name').strip()
        team_name = request.form.get('team_name').strip()
        league_type = request.form.get('league_type').strip()

        if league_type == 'Pub League':
            current_season = current_pub_league_season
        elif league_type == 'ECS FC':
            current_season = current_ecs_fc_season
        else:
            flash('Invalid league type.', 'danger')
            return redirect(url_for('publeague.manage_teams'))

        league = League.query.filter_by(name=league_name, season_id=current_season.id).first()

        if league and team_name:
            existing_team = Team.query.filter_by(name=team_name, league_id=league.id).first()
            if not existing_team:
                new_team = Team(name=team_name, league_id=league.id)
                db.session.add(new_team)
                db.session.commit()

                # Handle Discord channel creation differently for Pub League and ECS FC
                if league_type == 'Pub League':
                    division = "classic" if "classic" in league_name.lower() else "premier"
                else:
                    division = "ecsfc"  # Placeholder division name for ECS FC or any custom logic you need

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(create_discord_channel(team_name, division, new_team.id))

                flash(f'Team "{team_name}" added to {league_name} league successfully.', 'success')
            else:
                flash(f'Team "{team_name}" already exists in {league_name} league.', 'warning')
        else:
            flash('League or team name is missing.', 'danger')

        return redirect(url_for('publeague.manage_teams'))

    return render_template(
        'manage_teams.html',
        pub_league_season=current_pub_league_season,
        ecs_fc_season=current_ecs_fc_season
    )

# Edit Team
@publeague.route('/teams/<string:league_name>/<string:team_name>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_team(league_name, team_name):
    if league_name in ['Classic', 'Premier']:
        current_season = Season.query.filter_by(league_type='Pub League', is_current=True).first_or_404()
    else:
        current_season = Season.query.filter_by(league_type='ECS FC', is_current=True).first_or_404()

    league = League.query.filter_by(name=league_name, season_id=current_season.id).first_or_404()
    team = Team.query.filter_by(name=team_name, league_id=league.id).first_or_404()

    if request.method == 'POST':
        new_team_name = request.form.get('team_name').strip()
        if team and new_team_name and team_name != new_team_name:
            old_team_name = team.name
            team.name = new_team_name
            db.session.commit()
            flash(f'Team "{team_name}" updated to "{new_team_name}".', 'success')

            # Use a separate thread to run async functions
            async def update_discord():
                try:
                    await rename_discord_channel(team, new_team_name)
                    await rename_discord_roles(team, new_team_name)
                except Exception as e:
                    logger.error(f"Failed to update Discord: {str(e)}")
                    flash(f"Failed to update Discord: {str(e)}", "danger")
                    return False
                return True

            # Run the async task in the background
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            update_success = loop.run_until_complete(update_discord())

            if update_success:
                flash(f"Discord channel and roles updated successfully.", "success")
                logger.info(f"Discord channel and roles updated successfully for team {new_team_name}")
            else:
                flash(f"Failed to update Discord. Check the logs for details.", "danger")
                logger.warning(f"Failed to update Discord for team {new_team_name}")

        return redirect(url_for('publeague.manage_teams'))

    return render_template('edit_team.html', team=team)

# Delete Team
@publeague.route('/teams/<string:league_name>/<string:team_name>/delete', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_team(league_name, team_name):
    # Determine the current season based on the league type
    if league_name in ['Classic', 'Premier']:
        current_season = Season.query.filter_by(league_type='Pub League', is_current=True).first_or_404()
    else:
        current_season = Season.query.filter_by(league_type='ECS FC', is_current=True).first_or_404()
    
    league = League.query.filter_by(name=league_name, season_id=current_season.id).first_or_404()
    team = Team.query.filter_by(name=team_name, league_id=league.id).first_or_404()

    if team:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(delete_discord_channel(team))
        loop.run_until_complete(delete_discord_roles(team))

        db.session.delete(team)
        db.session.commit()
        flash(f'Team "{team_name}" deleted from {league_name} league.')

    return redirect(url_for('publeague.manage_teams'))

# View Players
@publeague.route('/players')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def view_players():
    players = Player.query.all()  # This should fetch players with their related league
    return render_template('view_players.html', players=players)

# Clear Players
@publeague.route('/clear_players', methods=['POST'])
@login_required
@role_required('Global Admin')
def clear_players():
    try:
        Player.query.delete()
        db.session.commit()
        flash('All players have been cleared.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error clearing players: {str(e)}', 'danger')
    return redirect(url_for('publeague.view_players'))

# Update Team Name
@publeague.route('/seasons/<int:season_id>/teams/<string:league_name>/<string:team_name>/update', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_publeague_team_name(season_id, league_name, team_name):
    league = League.query.filter_by(name=league_name, season_id=season_id).first_or_404()
    team = Team.query.filter_by(name=team_name, league_id=league.id).first_or_404()

    new_team_name = request.form.get('team_name')
    if new_team_name:
        team.name = new_team_name
        db.session.commit()
        flash(f'Team name updated to "{new_team_name}".', 'success')
    else:
        flash('Team name cannot be empty.', 'danger')

    return redirect(url_for('publeague.manage_teams', season_id=season_id))

def choose_team(league, match_num, team_type):
    teams = league.teams
    team = teams[(match_num - 1) % len(teams)]
    return team.name if team_type == 'A' else teams[(match_num) % len(teams)].name

def calculate_date_for_week(start_date, week):
    # This function calculates the date for each week based on the start date of the season
    return start_date + timedelta(weeks=week - 1)