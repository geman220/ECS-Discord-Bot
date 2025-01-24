from flask import Blueprint, render_template, redirect, url_for, flash, request, g
from flask_login import login_required
from sqlalchemy import func
import logging
from typing import Optional
from app.models import Season, League, Player, PlayerTeamSeason, Team, Schedule
from app.decorators import role_required

logger = logging.getLogger(__name__)

season_bp = Blueprint('season', __name__)

@season_bp.route('/', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_seasons():
    session = g.db_session

    pub_league_seasons = session.query(Season).filter_by(league_type='Pub League').all()
    ecs_fc_seasons = session.query(Season).filter_by(league_type='ECS FC').all()

    if request.method == 'POST':
        season_name = request.form.get('season_name')
        ecs_fc_season_name = request.form.get('ecs_fc_season_name')

        if season_name:
            try:
                create_pub_league_season(session, season_name)
                flash(f'Pub League Season "{season_name}" created successfully with Premier and Classic leagues.', 'success')
            except Exception as e:
                logger.error(f"Error creating Pub League season: {e}")
                flash('Error occurred while creating Pub League season.', 'danger')
                raise

        elif ecs_fc_season_name:
            try:
                create_ecs_fc_season(session, ecs_fc_season_name)
                flash(f'ECS FC Season "{ecs_fc_season_name}" created successfully.', 'success')
            except Exception as e:
                logger.error(f"Error creating ECS FC season: {e}")
                flash('Error occurred while creating ECS FC season.', 'danger')
                raise

        else:
            flash('Season name cannot be empty.', 'danger')

        return redirect(url_for('publeague.season.manage_seasons'))

    return render_template('manage_seasons.html', pub_league_seasons=pub_league_seasons, ecs_fc_seasons=ecs_fc_seasons)

def rollover_league(session, old_season: Season, new_season: Season) -> bool:
    try:
        players = session.query(Player).all()
        history_records = []

        # 1. For each Player, see if they have any Team in the old_season
        for player in players:
            # Gather all the teams that belong to old_season’s leagues
            old_season_teams = [
                t for t in player.teams if t.league.season_id == old_season.id
            ]
            # For each matching team, create a history record
            for t in old_season_teams:
                history_records.append(PlayerTeamSeason(
                    player_id=player.id,
                    team_id=t.id,
                    season_id=old_season.id
                ))
        
        # 2. Bulk save the “history” objects
        if history_records:
            session.bulk_save_objects(history_records)
            session.flush()
        
        # 3. Map old leagues -> new leagues, reassign Player league, etc.
        old_leagues = session.query(League).filter_by(season_id=old_season.id).all()
        new_leagues = session.query(League).filter_by(season_id=new_season.id).all()

        league_mapping = {
            old_league.name: next(
                (nl.id for nl in new_leagues if nl.name == old_league.name), None
            )
            for old_league in old_leagues
        }

        for old_league in old_leagues:
            new_league_id = league_mapping.get(old_league.name)
            if new_league_id:
                # For all players in old_league, reset league_id to new_league,
                # and remove any team assignments, etc. 
                session.query(Player).filter_by(league_id=old_league.id).update({
                    'league_id': new_league_id,
                    # There's no single 'team_id' to set to None since it's M2M,
                    # so you might handle that differently if needed.
                }, synchronize_session=False)

        # 4. Finally commit
        session.commit()
        return True

    except Exception as e:
        session.rollback()
        raise

def create_pub_league_season(session, season_name: str) -> Optional[Season]:
    season_name = season_name.strip()

    # 1) Check for existing season
    existing = session.query(Season).filter(
        func.lower(Season.name) == season_name.lower(),
        Season.league_type == 'Pub League'
    ).first()
    if existing:
        logger.warning(f'Season "{season_name}" already exists.')
        return None

    # 2) Find the old current season
    old_season = session.query(Season).filter_by(
        league_type='Pub League',
        is_current=True
    ).first()

    # 3) Create new season
    new_season = Season(
        name=season_name,
        league_type='Pub League',
        is_current=True
    )
    session.add(new_season)
    session.flush()  # Get new_season.id

    # 4) Create leagues
    premier_league = League(name="Premier", season_id=new_season.id)
    classic_league = League(name="Classic", season_id=new_season.id)
    session.add(premier_league)
    session.add(classic_league)

    # 5) If we have an old season, do the rollover (which commits at the end).
    if old_season:
        old_season.is_current = False
        rollover_league(session, old_season, new_season)
    else:
        # 6) If there's no old season, COMMIT here so the leagues actually persist
        session.commit()

    return new_season

def create_ecs_fc_season(session, season_name: str) -> Optional[Season]:
    """
    Enhanced version of create_ecs_fc_season that handles rollover
    """
    season_name = season_name.strip()
    existing = session.query(Season).filter(
        func.lower(Season.name) == season_name.lower(),
        Season.league_type == 'ECS FC'
    ).first()

    if existing:
        logger.warning(f'Season "{season_name}" already exists for ECS FC.')
        return None

    old_season = session.query(Season).filter_by(
        league_type='ECS FC',
        is_current=True
    ).first()

    new_season = Season(
        name=season_name,
        league_type='ECS FC',
        is_current=True
    )
    session.add(new_season)
    session.flush()

    ecs_fc_league = League(name="ECS FC", season_id=new_season.id)
    session.add(ecs_fc_league)

    if old_season:
        old_season.is_current = False
        rollover_league(session, old_season, new_season)

    return new_season

@season_bp.route('/<int:season_id>/set_current', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def set_current_season(season_id):
    session = g.db_session
    season = session.query(Season).get(season_id)
    if not season:
        flash('Season not found.', 'danger')
        return redirect(url_for('publeague.season.manage_seasons'))

    try:
        session.query(Season).filter_by(league_type=season.league_type).update({'is_current': False})
        season.is_current = True
        flash(f'Season "{season.name}" is now the current season for {season.league_type}.', 'success')
    except Exception as e:
        logger.error(f"Error setting current season: {e}")
        flash('Failed to set the current season.', 'danger')
        raise

    return redirect(url_for('publeague.season.manage_seasons'))

@season_bp.route('/delete/<int:season_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_season(season_id):
    session = g.db_session
    season = session.query(Season).get(season_id)
    if not season:
        flash('Season not found.', 'danger')
        return redirect(url_for('publeague.season.manage_seasons'))

    try:
        leagues = session.query(League).filter_by(season_id=season_id).all()
        for league in leagues:
            teams = session.query(Team).filter_by(league_id=league.id).all()
            for team in teams:
                session.query(Schedule).filter_by(team_id=team.id).delete()
                # Mark team for deletion
                session.delete(team)
            session.delete(league)

        session.delete(season)
        flash(f'Season "{season.name}" has been deleted along with its associated leagues.', 'success')
    except Exception as e:
        logger.error(f"Error deleting season: {e}")
        flash('Failed to delete the season.', 'danger')
        raise
    return redirect(url_for('publeague.season.manage_seasons'))
