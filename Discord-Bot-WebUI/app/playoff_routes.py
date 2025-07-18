# app/playoff_routes.py

"""
Playoff Management Routes Module

This module provides routes for managing playoff assignments and scheduling.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, g
from flask_login import login_required, current_user

from app.decorators import role_required
from app.models import League, Team, Match, Schedule, Season
from app.alert_helpers import show_success, show_error, show_warning

logger = logging.getLogger(__name__)

# Blueprint definition
playoff_bp = Blueprint('playoff', __name__, url_prefix='/admin/playoffs')


@playoff_bp.route('/league/<int:league_id>/manage', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_playoffs(league_id: int):
    """
    Show playoff management interface for a league.
    
    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)
    
    if not league:
        show_error('League not found')
        return redirect(url_for('auto_schedule.schedule_manager'))
    
    # Get playoff matches for this league
    playoff_matches = get_playoff_matches(session, league_id)
    
    # Get teams for this league
    teams = session.query(Team).filter_by(league_id=league_id).all()
    
    # Get current standings
    standings = get_league_standings(session, league_id)
    
    return render_template('admin/playoff_management.html',
                         league=league,
                         playoff_matches=playoff_matches,
                         teams=teams,
                         standings=standings,
                         title=f'Playoff Management - {league.name}')


@playoff_bp.route('/league/<int:league_id>/assign', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def assign_playoff_matches(league_id: int):
    """
    Assign teams to playoff matches.
    
    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)
    
    if not league:
        show_error('League not found')
        return redirect(url_for('auto_schedule.schedule_manager'))
    
    try:
        # Get all playoff matches for this league
        playoff_matches = session.query(Match).join(
            Schedule, Match.schedule_id == Schedule.id
        ).join(
            Team, Schedule.team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True
        ).all()
        
        updates_made = 0
        
        for match in playoff_matches:
            home_team_key = f'home_team_{match.id}'
            away_team_key = f'away_team_{match.id}'
            description_key = f'description_{match.id}'
            
            if home_team_key in request.form and away_team_key in request.form:
                home_team_id = request.form[home_team_key]
                away_team_id = request.form[away_team_key]
                description = request.form.get(description_key, '')
                
                # Validate team assignments
                if home_team_id and away_team_id:
                    if home_team_id != away_team_id:
                        # Update match
                        match.home_team_id = int(home_team_id)
                        match.away_team_id = int(away_team_id)
                        match.notes = description
                        match.week_type = 'PLAYOFF'
                        match.is_playoff_game = True
                        updates_made += 1
                        
                        # Update associated schedule entries
                        home_schedule = session.query(Schedule).filter_by(
                            team_id=home_team_id,
                            week=match.schedule.week,
                            date=match.date
                        ).first()
                        if home_schedule:
                            home_schedule.opponent = int(away_team_id)
                        
                        away_schedule = session.query(Schedule).filter_by(
                            team_id=away_team_id,
                            week=match.schedule.week,
                            date=match.date
                        ).first()
                        if away_schedule:
                            away_schedule.opponent = int(home_team_id)
                    else:
                        show_warning(f'Cannot assign same team to both home and away for match {match.id}')
        
        session.commit()
        
        if updates_made > 0:
            show_success(f'Successfully assigned teams to {updates_made} playoff matches')
        else:
            show_warning('No playoff assignments were made')
            
    except Exception as e:
        logger.error(f"Error assigning playoff matches: {e}")
        session.rollback()
        show_error(f'Error assigning playoff matches: {str(e)}')
    
    return redirect(url_for('playoff.manage_playoffs', league_id=league_id))


@playoff_bp.route('/league/<int:league_id>/auto-assign', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def auto_assign_playoffs(league_id: int):
    """
    Auto-assign playoff teams based on current standings.
    
    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)
    
    if not league:
        return jsonify({'success': False, 'error': 'League not found'}), 404
    
    try:
        # Get current standings
        standings = get_league_standings(session, league_id)
        
        if len(standings) < 4:
            return jsonify({'success': False, 'error': 'Not enough teams for playoffs (minimum 4 required)'}), 400
        
        # Get playoff matches ordered by week and time
        playoff_matches = session.query(Match).join(
            Schedule, Match.schedule_id == Schedule.id
        ).join(
            Team, Schedule.team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True
        ).order_by(Match.date, Match.time).all()
        
        if not playoff_matches:
            return jsonify({'success': False, 'error': 'No playoff matches found'}), 400
        
        # Assign teams based on league type
        if league.name == 'Premier':
            # Premier: 2 weeks, 3 matches total
            # Week 1: #1 vs #4, #2 vs #3
            # Week 2: Winner vs Winner (will be manually set later)
            if len(playoff_matches) >= 2:
                # Semifinal 1: #1 vs #4
                playoff_matches[0].home_team_id = standings[0].id
                playoff_matches[0].away_team_id = standings[3].id
                playoff_matches[0].notes = 'Semifinal #1'
                
                # Semifinal 2: #2 vs #3
                playoff_matches[1].home_team_id = standings[1].id
                playoff_matches[1].away_team_id = standings[2].id
                playoff_matches[1].notes = 'Semifinal #2'
                
                # Final match (if exists) - leave as TBD
                if len(playoff_matches) >= 3:
                    playoff_matches[2].notes = 'Championship Final - TBD'
                    
        else:  # Classic
            # Classic: 1 week, 2 matches
            # Match 1: #1 vs #2, Match 2: #3 vs #4
            if len(playoff_matches) >= 2:
                # Championship match 1: #1 vs #2
                playoff_matches[0].home_team_id = standings[0].id
                playoff_matches[0].away_team_id = standings[1].id
                playoff_matches[0].notes = 'Championship Match #1'
                
                # Championship match 2: #3 vs #4
                playoff_matches[1].home_team_id = standings[2].id
                playoff_matches[1].away_team_id = standings[3].id
                playoff_matches[1].notes = 'Championship Match #2'
        
        # Update all assigned matches
        for match in playoff_matches:
            match.week_type = 'PLAYOFF'
            match.is_playoff_game = True
        
        session.commit()
        
        return jsonify({'success': True, 'message': 'Playoff teams auto-assigned based on standings'})
        
    except Exception as e:
        logger.error(f"Error auto-assigning playoffs: {e}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


def get_playoff_matches(session, league_id: int) -> Dict[str, List[Match]]:
    """
    Get playoff matches organized by week.
    
    Args:
        session: Database session
        league_id: ID of the league
        
    Returns:
        Dictionary with week names as keys and lists of matches as values
    """
    matches = session.query(Match).join(
        Schedule, Match.schedule_id == Schedule.id
    ).join(
        Team, Schedule.team_id == Team.id
    ).filter(
        Team.league_id == league_id,
        Match.is_playoff_game == True
    ).order_by(Match.date, Match.time).all()
    
    # Group matches by week
    weeks = {}
    for match in matches:
        schedule = session.query(Schedule).get(match.schedule_id)
        if schedule:
            week_key = f"Week {schedule.week}"
            if week_key not in weeks:
                weeks[week_key] = []
            weeks[week_key].append(match)
    
    return weeks


def get_league_standings(session, league_id: int) -> List[Team]:
    """
    Get current standings for a league.
    
    Args:
        session: Database session
        league_id: ID of the league
        
    Returns:
        List of teams ordered by standings
    """
    # For now, return teams in order
    # TODO: Implement actual standings calculation based on match results
    teams = session.query(Team).filter_by(league_id=league_id).all()
    
    # Add placeholder stats for display
    for i, team in enumerate(teams):
        team.points = (len(teams) - i) * 3  # Placeholder points
        team.wins = len(teams) - i
        team.losses = i
        team.draws = 0
    
    return teams