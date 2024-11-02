from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from app import db
from app.models import Season, League, Team, Schedule
from app.decorators import role_required, db_operation
import logging

# Get the logger for this module
logger = logging.getLogger(__name__)

season_bp = Blueprint('season', __name__)

@season_bp.route('/', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
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

        elif ecs_fc_season_name:
            try:
                create_ecs_fc_season(ecs_fc_season_name)
                flash(f'ECS FC Season "{ecs_fc_season_name}" created successfully.', 'success')
            except Exception as e:
                logger.error(f"Error creating ECS FC season: {e}")
                flash('Error occurred while creating ECS FC season.', 'danger')

        else:
            flash('Season name cannot be empty.', 'danger')

        return redirect(url_for('season.manage_seasons'))

    return render_template('manage_seasons.html', pub_league_seasons=pub_league_seasons, ecs_fc_seasons=ecs_fc_seasons)

@db_operation
def create_pub_league_season(season_name):
    """Create a new Pub League season with Premier and Classic leagues."""
    season_name = season_name.strip()
    existing_season = Season.query.filter(
        db.func.lower(Season.name) == season_name.lower(),
        Season.league_type == 'Pub League'
    ).first()
    if not existing_season:
        Season.query.filter_by(league_type='Pub League').update({'is_current': False})
        
        new_season = Season(name=season_name, league_type='Pub League', is_current=True)
        db.session.add(new_season)
        
        db.session.add(League(name="Premier", season_id=new_season.id))
        db.session.add(League(name="Classic", season_id=new_season.id))
        # No need to call db.session.commit(); handled by decorator
    else:
        flash(f'Season "{season_name}" already exists.', 'warning')

@db_operation
def create_ecs_fc_season(season_name):
    """Create a new ECS FC season."""
    season_name = season_name.strip()
    existing_season = Season.query.filter(
        db.func.lower(Season.name) == season_name.lower(),
        Season.league_type=='ECS FC'
    ).first()
    if not existing_season:
        Season.query.filter_by(league_type='ECS FC').update({'is_current': False})
        
        new_season = Season(name=season_name, league_type='ECS FC', is_current=True)
        db.session.add(new_season)
        
        db.session.add(League(name="ECS FC", season_id=new_season.id))
        # No need to call db.session.commit(); handled by decorator
    else:
        flash(f'Season "{season_name}" already exists.', 'warning')

@season_bp.route('/<int:season_id>/set_current', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@db_operation
def set_current_season(season_id):
    try:
        season = Season.query.get_or_404(season_id)
        Season.query.filter_by(league_type=season.league_type).update({'is_current': False})
        season.is_current = True
        # No need to call db.session.commit(); handled by decorator
        flash(f'Season "{season.name}" is now the current season for {season.league_type}.', 'success')
    except Exception as e:
        logger.error(f"Error setting current season: {e}")
        flash('Failed to set the current season.', 'danger')
        raise  # Reraise exception for decorator to handle rollback

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
                db.session.delete(team)
            db.session.delete(league)
        
        db.session.delete(season)
        # No need to call db.session.commit(); handled by decorator
        flash(f'Season "{season.name}" has been deleted along with its associated leagues.', 'success')
    except Exception as e:
        logger.error(f"Error deleting season: {e}")
        flash('Failed to delete the season.', 'danger')
        raise  # Reraise exception for decorator to handle rollback

    return redirect(url_for('season.manage_seasons'))