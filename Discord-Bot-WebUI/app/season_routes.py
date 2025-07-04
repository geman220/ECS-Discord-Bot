# app/season_routes.py

"""
Season Routes Module

This module provides endpoints and helper functions for managing seasons,
including creating new seasons (for both Pub League and ECS FC), performing
league rollovers, setting the current season, and deleting seasons along with
their associated leagues and teams.
"""

from flask import Blueprint, render_template, redirect, url_for, request, g
from app.alert_helpers import show_success, show_error, show_warning, show_info
from flask_login import login_required
from sqlalchemy import func
from typing import Optional
import logging

from app.models import Season, League, Player, PlayerTeamSeason, Team, Schedule
from app.decorators import role_required

logger = logging.getLogger(__name__)

season_bp = Blueprint('season', __name__)


@season_bp.route('/', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_seasons():
    """
    Manage seasons: Display existing Pub League and ECS FC seasons and
    allow creation of new seasons via form submission.
    """
    session = g.db_session

    pub_league_seasons = session.query(Season).filter_by(league_type='Pub League').all()
    ecs_fc_seasons = session.query(Season).filter_by(league_type='ECS FC').all()

    if request.method == 'POST':
        season_name = request.form.get('season_name')
        ecs_fc_season_name = request.form.get('ecs_fc_season_name')

        if season_name:
            try:
                create_pub_league_season(session, season_name)
                show_success(f'Pub League Season "{season_name}" created successfully with Premier and Classic leagues.')
            except Exception as e:
                logger.error(f"Error creating Pub League season: {e}")
                show_error('Error occurred while creating Pub League season.')
                raise
        elif ecs_fc_season_name:
            try:
                create_ecs_fc_season(session, ecs_fc_season_name)
                show_success(f'ECS FC Season "{ecs_fc_season_name}" created successfully.')
            except Exception as e:
                logger.error(f"Error creating ECS FC season: {e}")
                show_error('Error occurred while creating ECS FC season.')
                raise
        else:
            show_error('Season name cannot be empty.')

        return redirect(url_for('publeague.season.manage_seasons'))

    return render_template('manage_seasons.html', pub_league_seasons=pub_league_seasons, ecs_fc_seasons=ecs_fc_seasons, title='Manage Seasons')


def rollover_league(session, old_season: Season, new_season: Season) -> bool:
    """
    Perform league rollover from an old season to a new season.

    For each player, records their team history for the old season.
    Then updates players to belong to the corresponding league in the new season.

    Args:
        session: Database session.
        old_season (Season): The previous season.
        new_season (Season): The newly created season.

    Returns:
        bool: True if the rollover is successful.

    Raises:
        Exception: Propagates any exception after rolling back.
    """
    try:
        players = session.query(Player).all()
        history_records = []

        for player in players:
            # Get teams for the player that are in the old season.
            old_season_teams = [t for t in player.teams if t.league.season_id == old_season.id]
            for t in old_season_teams:
                history_records.append(PlayerTeamSeason(
                    player_id=player.id,
                    team_id=t.id,
                    season_id=old_season.id
                ))

        if history_records:
            session.bulk_save_objects(history_records)
            session.flush()
        
        # Retrieve leagues from both seasons.
        old_leagues = session.query(League).filter_by(season_id=old_season.id).all()
        new_leagues = session.query(League).filter_by(season_id=new_season.id).all()

        # Create a mapping from old league names to new league IDs.
        league_mapping = {
            old_league.name: next((nl.id for nl in new_leagues if nl.name == old_league.name), None)
            for old_league in old_leagues
        }

        # Update players' league associations.
        for old_league in old_leagues:
            new_league_id = league_mapping.get(old_league.name)
            if new_league_id:
                session.query(Player).filter_by(league_id=old_league.id).update({
                    'league_id': new_league_id,
                }, synchronize_session=False)

        session.commit()
        return True

    except Exception as e:
        session.rollback()
        raise


def create_pub_league_season(session, season_name: str) -> Optional[Season]:
    """
    Create a new Pub League season with default Premier and Classic leagues.

    If an old season exists, mark it as not current and perform a rollover.

    Args:
        session: Database session.
        season_name (str): Name of the new season.

    Returns:
        Optional[Season]: The newly created season or None if it already exists.
    """
    season_name = season_name.strip()

    existing = session.query(Season).filter(
        func.lower(Season.name) == season_name.lower(),
        Season.league_type == 'Pub League'
    ).first()
    if existing:
        logger.warning(f'Season "{season_name}" already exists.')
        return None

    old_season = session.query(Season).filter_by(
        league_type='Pub League',
        is_current=True
    ).first()

    new_season = Season(
        name=season_name,
        league_type='Pub League',
        is_current=True
    )
    session.add(new_season)
    session.flush()

    # Create default leagues for the new season.
    premier_league = League(name="Premier", season_id=new_season.id)
    classic_league = League(name="Classic", season_id=new_season.id)
    session.add(premier_league)
    session.add(classic_league)

    if old_season:
        old_season.is_current = False
        rollover_league(session, old_season, new_season)
    else:
        session.commit()

    return new_season


def create_ecs_fc_season(session, season_name: str) -> Optional[Season]:
    """
    Create a new ECS FC season with its default league.

    If an old ECS FC season exists, mark it as not current and perform a rollover.

    Args:
        session: Database session.
        season_name (str): Name of the new ECS FC season.

    Returns:
        Optional[Season]: The newly created season or None if it already exists.
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
    """
    Set the specified season as the current season for its league type.

    Args:
        season_id (int): The ID of the season to be set as current.

    Returns:
        A redirect response to the season management page.
    """
    session = g.db_session
    season = session.query(Season).get(season_id)
    if not season:
        show_error('Season not found.')
        return redirect(url_for('publeague.season.manage_seasons'))

    try:
        # Mark all seasons of this league type as not current.
        session.query(Season).filter_by(league_type=season.league_type).update({'is_current': False})
        season.is_current = True
        show_success(f'Season "{season.name}" is now the current season for {season.league_type}.')
    except Exception as e:
        logger.error(f"Error setting current season: {e}")
        show_error('Failed to set the current season.')
        raise

    return redirect(url_for('publeague.season.manage_seasons'))


@season_bp.route('/delete/<int:season_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_season(season_id):
    """
    Delete the specified season along with its associated leagues, teams, and schedules.

    Args:
        season_id (int): The ID of the season to delete.

    Returns:
        A redirect response to the season management page.
    """
    session = g.db_session
    season = session.query(Season).get(season_id)
    if not season:
        show_error('Season not found.')
        return redirect(url_for('publeague.season.manage_seasons'))

    try:
        # Delete associated leagues and teams.
        leagues = session.query(League).filter_by(season_id=season_id).all()
        for league in leagues:
            teams = session.query(Team).filter_by(league_id=league.id).all()
            for team in teams:
                session.query(Schedule).filter_by(team_id=team.id).delete()
                session.delete(team)
            session.delete(league)

        session.delete(season)
        show_success(f'Season "{season.name}" has been deleted along with its associated leagues.')
    except Exception as e:
        logger.error(f"Error deleting season: {e}")
        show_error('Failed to delete the season.')
        raise
    return redirect(url_for('publeague.season.manage_seasons'))