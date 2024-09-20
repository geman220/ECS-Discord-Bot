from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from app import db
from app.models import Season, League, Team, Schedule
from app.decorators import role_required

season_bp = Blueprint('season', __name__)

# Manage Seasons
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
            season_name = season_name.strip()
            existing_season = Season.query.filter(db.func.lower(Season.name) == season_name.lower(), Season.league_type == 'Pub League').first()
            if not existing_season:
                Season.query.filter_by(league_type='Pub League').update({'is_current': False})
                
                new_season = Season(name=season_name, league_type='Pub League', is_current=True)
                db.session.add(new_season)
                db.session.commit()

                db.session.add(League(name="Premier", season_id=new_season.id))
                db.session.add(League(name="Classic", season_id=new_season.id))
                db.session.commit()

                flash(f'Pub League Season "{season_name}" created successfully with Premier and Classic leagues.', 'success')
            else:
                flash(f'Season "{season_name}" already exists.', 'warning')

        elif ecs_fc_season_name:
            ecs_fc_season_name = ecs_fc_season_name.strip()
            existing_season = Season.query.filter(db.func.lower(Season.name) == ecs_fc_season_name.lower(), Season.league_type == 'ECS FC').first()
            if not existing_season:
                Season.query.filter_by(league_type='ECS FC').update({'is_current': False})
                
                new_season = Season(name=ecs_fc_season_name, league_type='ECS FC', is_current=True)
                db.session.add(new_season)
                db.session.commit()

                db.session.add(League(name="ECS FC", season_id=new_season.id))
                db.session.commit()

                flash(f'ECS FC Season "{ecs_fc_season_name}" created successfully.', 'success')
            else:
                flash(f'Season "{ecs_fc_season_name}" already exists.', 'warning')

        else:
            flash('Season name cannot be empty.', 'danger')

        return redirect(url_for('season.manage_seasons'))

    return render_template('manage_seasons.html', pub_league_seasons=pub_league_seasons, ecs_fc_seasons=ecs_fc_seasons)

# Set Current Season
@season_bp.route('/<int:season_id>/set_current', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def set_current_season(season_id):
    season = Season.query.get_or_404(season_id)
    Season.query.filter_by(league_type=season.league_type).update({'is_current': False})
    season.is_current = True
    db.session.commit()
    flash(f'Season "{season.name}" is now the current season for {season.league_type}.', 'success')
    return redirect(url_for('season.manage_seasons'))

# Delete Season
@season_bp.route('/delete/<int:season_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_season(season_id):
    season = Season.query.get_or_404(season_id)
    leagues = League.query.filter_by(season_id=season_id).all()
    for league in leagues:
        teams = Team.query.filter_by(league_id=league.id).all()
        for team in teams:
            Schedule.query.filter_by(team_id=team.id).delete()
            db.session.delete(team)
        db.session.delete(league)
    
    db.session.delete(season)
    db.session.commit()
    flash(f'Season "{season.name}" has been deleted along with its associated leagues.', 'success')
    return redirect(url_for('season.manage_seasons'))
