from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from sqlalchemy import func
from app.models import Season, League, Team, Schedule
from app.decorators import role_required, db_operation
import logging

# Get the logger for this module
logger = logging.getLogger(__name__)

season_bp = Blueprint('season', __name__)

@season_bp.route('/', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def manage_seasons():
    pub_league_seasons = Season.query.filter_by(league_type='Pub League').all()
    ecs_fc_seasons = Season.query.filter_by(league_type='ECS FC').all()

    if request.method == 'POST':
        season_name = request.form.get('season_name')
        ecs_fc_season_name = request.form.get('ecs_fc_season_name')

        if season_name:
            try:
                create_pub_league_season(season_name)
                flash(f'Pub League Season "{season_name}" created successfully with Premier and Classic leagues.', 'success')
            except Exception as e:
                logger.error(f"Error creating Pub League season: {e}")
                flash('Error occurred while creating Pub League season.', 'danger')
                raise

        elif ecs_fc_season_name:
            try:
                create_ecs_fc_season(ecs_fc_season_name)
                flash(f'ECS FC Season "{ecs_fc_season_name}" created successfully.', 'success')
            except Exception as e:
                logger.error(f"Error creating ECS FC season: {e}")
                flash('Error occurred while creating ECS FC season.', 'danger')
                raise

        else:
            flash('Season name cannot be empty.', 'danger')

        return redirect(url_for('season.manage_seasons'))

    return render_template('manage_seasons.html', pub_league_seasons=pub_league_seasons, ecs_fc_seasons=ecs_fc_seasons)

@db_operation
def create_pub_league_season(season_name):
    """Create a new Pub League season with Premier and Classic leagues."""
    season_name = season_name.strip()
    existing_season = Season.query.filter(
        func.lower(Season.name) == season_name.lower(),
        Season.league_type == 'Pub League'
    ).first()
    
    if not existing_season:
        # Set all existing seasons to not current
        Season.query.filter_by(league_type='Pub League').update({'is_current': False})
        
        # Create new season
        new_season = Season(name=season_name, league_type='Pub League', is_current=True)
        
        # Create Premier and Classic leagues
        premier_league = League(name="Premier", season=new_season)
        classic_league = League(name="Classic", season=new_season)
        
        # Return the season (db_operation decorator will handle the session)
        return new_season
    else:
        flash(f'Season "{season_name}" already exists.', 'warning')
        return None

@db_operation
def create_ecs_fc_season(season_name):
    """Create a new ECS FC season."""
    season_name = season_name.strip()
    existing_season = Season.query.filter(
        func.lower(Season.name) == season_name.lower(),
        Season.league_type=='ECS FC'
    ).first()
    
    if not existing_season:
        Season.query.filter_by(league_type='ECS FC').update({'is_current': False})
        
        new_season = Season(name=season_name, league_type='ECS FC', is_current=True)
        ecs_fc_league = League(name="ECS FC", season=new_season)
        
        return new_season
    else:
        flash(f'Season "{season_name}" already exists.', 'warning')
        return None

@season_bp.route('/<int:season_id>/set_current', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def set_current_season(season_id):
    try:
        season = Season.query.get_or_404(season_id)
        Season.query.filter_by(league_type=season.league_type).update({'is_current': False})
        season.is_current = True
        flash(f'Season "{season.name}" is now the current season for {season.league_type}.', 'success')
    except Exception as e:
        logger.error(f"Error setting current season: {e}")
        flash('Failed to set the current season.', 'danger')
        raise

    return redirect(url_for('season.manage_seasons'))

@season_bp.route('/delete/<int:season_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def delete_season(season_id):
    try:
        season = Season.query.get_or_404(season_id)
        leagues = League.query.filter_by(season_id=season_id).all()
        for league in leagues:
            teams = Team.query.filter_by(league_id=league.id).all()
            for team in teams:
                Schedule.query.filter_by(team_id=team.id).delete()
                # Just mark for deletion, decorator handles session
                team.delete()
            league.delete()
        
        # Mark season for deletion
        season.delete()
        flash(f'Season "{season.name}" has been deleted along with its associated leagues.', 'success')
    except Exception as e:
        logger.error(f"Error deleting season: {e}")
        flash('Failed to delete the season.', 'danger')
        raise
    return redirect(url_for('season.manage_seasons'))
