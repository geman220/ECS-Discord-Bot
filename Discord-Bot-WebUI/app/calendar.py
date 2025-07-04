# app/calendar.py

"""
Calendar Module

This module defines endpoints for retrieving calendar events and referee
information for the league. Endpoints include:
- Retrieving a schedule of match events.
- Retrieving available referees for a match.
- Assigning or removing referees from matches.
- Rendering the calendar view page.

Access is restricted to authenticated users with appropriate roles.
"""

from datetime import datetime
import logging

from flask import Blueprint, jsonify, render_template, request, g
from flask_login import login_required
from sqlalchemy.orm import aliased, joinedload
from flask_login import current_user

from app.models import Match, Team, Season, Player, player_teams
from app.decorators import role_required

logger = logging.getLogger(__name__)
calendar_bp = Blueprint('calendar', __name__)


@calendar_bp.route('/calendar/events', endpoint='get_schedule', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Ref', 'Pub League Coach'])
def get_schedule():
    """
    Retrieve a schedule of match events for the current season.

    This endpoint:
    - Loads the current season and its associated leagues.
    - Retrieves matches for those leagues.
    - Converts match dates from UTC to Pacific Time for display.
    - Builds an event list with details (title, start time, description, color, URL, etc.).

    Returns:
        JSON response containing the list of events and basic statistics.
    """
    session_db = g.db_session
    try:
        seasons = session_db.query(Season).options(joinedload(Season.leagues)).filter_by(is_current=True).all()
        if not seasons:
            logger.warning("No current season found.")
            return jsonify({'error': 'No current season found.'}), 404

        league_ids = [league.id for season in seasons for league in season.leagues]

        # Aliases for join queries
        home_team = aliased(Team)
        away_team = aliased(Team)
        ref_player = aliased(Player)

        matches = (session_db.query(Match)
                   .join(home_team, Match.home_team_id == home_team.id)
                   .join(away_team, Match.away_team_id == away_team.id)
                   .outerjoin(ref_player, Match.ref_id == ref_player.id)
                   .with_entities(
                       Match.id,
                       Match.date,
                       Match.time,
                       Match.location,
                       home_team.name.label('home_team_name'),
                       away_team.name.label('away_team_name'),
                       home_team.league_id.label('home_league_id'),
                       ref_player.name.label('ref_name')
                   )
                   .filter(home_team.league_id.in_(league_ids))
                   .all())

        if not matches:
            logger.warning("No matches found for the current seasons.")
            return jsonify({'message': 'No matches found'}), 404

        events = []
        total_matches = len(matches)
        assigned_refs = 0

        for match in matches:
            # Determine division based on league ID (example logic)
            division = 'Premier' if match.home_league_id == 10 else 'Classic'
            start_datetime = datetime.combine(match.date, match.time)
            ref_name = match.ref_name if match.ref_name else 'Unassigned'

            if ref_name != 'Unassigned':
                assigned_refs += 1

            events.append({
                'id': match.id,
                'title': f"{division}: {match.home_team_name} vs {match.away_team_name}",
                'start': start_datetime.isoformat(),
                'description': f"Location: {match.location}",
                'color': 'blue' if division == 'Premier' else 'green',
                'url': f"/matches/{match.id}",
                'ref': ref_name,
                'division': division,
                'teams': f"{match.home_team_name} vs {match.away_team_name}"
            })

        unassigned_matches = total_matches - assigned_refs

        return jsonify({
            'events': events,
            'stats': {
                'totalMatches': total_matches,
                'assignedRefs': assigned_refs,
                'unassignedMatches': unassigned_matches
            }
        })

    except Exception as e:
        logger.exception("An error occurred while fetching events.")
        return jsonify({'error': 'An internal error occurred.'}), 500


@calendar_bp.route('/calendar/refs', endpoint='get_refs', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Ref', 'Pub League Coach'])
def get_refs():
    """
    Retrieve a list of referees available for a specific match.

    Expects a 'match_id' query parameter.

    Returns:
        JSON response with referee details excluding those assigned to the match teams.
    """
    session_db = g.db_session
    try:
        match_id = request.args.get('match_id', type=int)
        if not match_id:
            return jsonify({'error': 'match_id parameter is required.'}), 400

        match = session_db.query(Match).get(match_id)
        if not match:
            return jsonify({'error': 'Match not found.'}), 404

        refs = session_db.query(Player).filter_by(is_ref=True, is_available_for_ref=True).all()
        ref_list = []
        for ref in refs:
            # Get the team IDs this referee is associated with
            ref_team_ids = [team.id for team in ref.teams]
            
            # Exclude refs who are players on the match teams or playing at the same time
            if match.home_team_id not in ref_team_ids and match.away_team_id not in ref_team_ids:
                # Check if referee is playing in any match at the same date and time
                conflicting_match = session_db.query(Match).join(
                    player_teams, (Match.home_team_id == player_teams.c.team_id) | (Match.away_team_id == player_teams.c.team_id)
                ).filter(
                    player_teams.c.player_id == ref.id,
                    Match.date == match.date,
                    Match.time == match.time,
                    Match.id != match.id
                ).first()
                
                if not conflicting_match:
                    matches_assigned_in_week = session_db.query(Match).filter_by(ref_id=ref.id).filter(
                        Match.date == match.date
                    ).count()
                    total_matches_assigned = session_db.query(Match).filter_by(ref_id=ref.id).count()

                    ref_list.append({
                        'id': ref.id,
                        'name': ref.name,
                        'matches_assigned_in_week': matches_assigned_in_week,
                        'total_matches_assigned': total_matches_assigned
                    })

        return jsonify(ref_list)

    except Exception as e:
        logger.exception("An error occurred while fetching referees.")
        return jsonify({'error': 'An internal error occurred.'}), 500


@calendar_bp.route('/calendar/assign_ref', endpoint='assign_ref', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Manager', 'Pub League Coach'])
def assign_ref():
    """
    Assign a referee to a match.

    Expects JSON with 'match_id' and 'ref_id'.

    Returns:
        JSON response indicating success or error.
    """
    session_db = g.db_session
    try:
        data = request.get_json()
        match_id = data.get('match_id')
        ref_id = data.get('ref_id')

        if not match_id or not ref_id:
            logger.warning("Match ID and Ref ID are required.")
            return jsonify({'error': 'Match ID and Ref ID are required.'}), 400

        match = session_db.query(Match).get(match_id)
        if not match:
            logger.warning(f"Match not found: ID {match_id}")
            return jsonify({'error': 'Match not found.'}), 404

        ref = session_db.query(Player).get(ref_id)
        if not ref or not ref.is_ref:
            logger.error(f"Attempted to assign invalid ref: Player ID {ref_id}")
            return jsonify({'error': 'Invalid referee.'}), 400

        conflicting_match = session_db.query(Match).filter(
            Match.ref_id == ref_id,
            Match.date == match.date,
            Match.time == match.time,
            Match.id != match_id
        ).first()

        if conflicting_match:
            logger.error(f"Referee already assigned to match {conflicting_match.id} at the same time.")
            return jsonify({'error': 'Referee is already assigned to another match at this time.'}), 400

        # Get the team IDs this referee is associated with
        ref_team_ids = [team.id for team in ref.teams]
        
        if match.home_team_id in ref_team_ids or match.away_team_id in ref_team_ids:
            logger.error(f"Referee {ref.name} is a player on one of the teams.")
            return jsonify({'error': 'Referee is on one of the teams in this match.'}), 400
        
        # Check if referee is playing in any match at the same date and time
        conflicting_player_match = session_db.query(Match).join(
            player_teams, (Match.home_team_id == player_teams.c.team_id) | (Match.away_team_id == player_teams.c.team_id)
        ).filter(
            player_teams.c.player_id == ref.id,
            Match.date == match.date,
            Match.time == match.time,
            Match.id != match.id
        ).first()
        
        if conflicting_player_match:
            logger.error(f"Referee {ref.name} is playing in another match at the same time.")
            return jsonify({'error': 'Referee is playing in another match at this time.'}), 400

        logger.info(f"Assigning Referee {ref.name} (ID: {ref_id}) to Match ID {match_id}")
        match.ref = ref
        session_db.commit()

        return jsonify({'message': 'Referee assigned successfully.'}), 200

    except Exception as e:
        logger.exception("An error occurred while assigning the referee.")
        raise


@calendar_bp.route('/calendar/available_refs', endpoint='available_refs', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Ref', 'Pub League Coach'])
def available_refs():
    """
    Retrieve available referees for a specified date range.

    Expects 'start_date' and 'end_date' as ISO format query parameters.

    Returns:
        JSON response with a list of available referees and match assignment statistics.
    """
    session_db = g.db_session
    try:
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        if not start_date_str or not end_date_str:
            return jsonify({'error': 'start_date and end_date parameters are required.'}), 400

        start_date = datetime.fromisoformat(start_date_str)
        end_date = datetime.fromisoformat(end_date_str)

        refs = session_db.query(Player).filter_by(is_ref=True, is_available_for_ref=True).all()
        ref_list = []
        for ref in refs:
            matches_assigned_in_week = session_db.query(Match).filter_by(ref_id=ref.id).filter(
                Match.date >= start_date, Match.date <= end_date
            ).count()
            total_matches_assigned = session_db.query(Match).filter_by(ref_id=ref.id).count()

            ref_list.append({
                'id': ref.id,
                'name': ref.name,
                'matches_assigned_in_week': matches_assigned_in_week,
                'total_matches_assigned': total_matches_assigned
            })

        return jsonify(ref_list)
    except Exception as e:
        logger.exception(f"Error fetching available referees: {str(e)}")
        return jsonify({'error': 'An error occurred fetching referees'}), 500


@calendar_bp.route('/calendar/remove_ref', endpoint='remove_ref', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def remove_ref():
    """
    Remove the referee assignment from a match.

    Expects JSON with 'match_id'.

    Returns:
        JSON response indicating success or error.
    """
    session_db = g.db_session
    try:
        data = request.get_json()
        match_id = data.get('match_id')
        if not match_id:
            logger.warning("Match ID is required to remove referee.")
            return jsonify({'error': 'Match ID is required.'}), 400

        match = session_db.query(Match).get(match_id)
        if not match:
            logger.warning(f"Match not found: ID {match_id}")
            return jsonify({'error': 'Match not found.'}), 404

        if not match.ref:
            logger.info(f"No referee assigned to match ID {match_id}.")
            return jsonify({'error': 'No referee assigned to this match.'}), 400

        logger.info(f"Removing referee {match.ref.name} from match ID {match_id}.")
        match.ref = None

        return jsonify({'message': 'Referee removed successfully.'}), 200

    except Exception as e:
        logger.exception("An error occurred while removing the referee.")
        raise


@calendar_bp.route('/calendar/my_assignments', endpoint='my_assignments', methods=['GET'])
@login_required
@role_required(['Pub League Ref'])
def my_assignments():
    """
    Get referee assignments for the current user.
    
    Returns:
        JSON response with the referee's assigned matches.
    """
    session_db = g.db_session
    try:
        # Get the current user's player record
        player = session_db.query(Player).filter_by(user_id=current_user.id, is_ref=True).first()
        if not player:
            return jsonify({'error': 'User is not a referee.'}), 404
        
        # Get current season leagues
        seasons = session_db.query(Season).options(joinedload(Season.leagues)).filter_by(is_current=True).all()
        if not seasons:
            return jsonify({'message': 'No current season found.'}), 404
        
        league_ids = [league.id for season in seasons for league in season.leagues]
        
        # Aliases for join queries
        home_team = aliased(Team)
        away_team = aliased(Team)
        
        # Get matches assigned to this referee
        matches = (session_db.query(Match)
                   .join(home_team, Match.home_team_id == home_team.id)
                   .join(away_team, Match.away_team_id == away_team.id)
                   .filter(Match.ref_id == player.id)
                   .filter(home_team.league_id.in_(league_ids))
                   .with_entities(
                       Match.id,
                       Match.date,
                       Match.time,
                       Match.location,
                       home_team.name.label('home_team_name'),
                       away_team.name.label('away_team_name'),
                       home_team.league_id.label('home_league_id')
                   )
                   .order_by(Match.date, Match.time)
                   .all())
        
        assignments = []
        for match in matches:
            division = 'Premier' if match.home_league_id == 10 else 'Classic'
            start_datetime = datetime.combine(match.date, match.time)
            
            assignments.append({
                'id': match.id,
                'title': f"{division}: {match.home_team_name} vs {match.away_team_name}",
                'start': start_datetime.isoformat(),
                'date': match.date.strftime('%Y-%m-%d'),
                'time': match.time.strftime('%H:%M'),
                'location': match.location,
                'home_team': match.home_team_name,
                'away_team': match.away_team_name,
                'division': division
            })
        
        return jsonify({
            'assignments': assignments,
            'total_assignments': len(assignments)
        })
        
    except Exception as e:
        logger.exception("An error occurred while fetching referee assignments.")
        return jsonify({'error': 'An internal error occurred.'}), 500


@calendar_bp.route('/calendar/toggle_availability', endpoint='toggle_availability', methods=['POST'])
@login_required
@role_required(['Pub League Ref'])
def toggle_availability():
    """
    Toggle referee availability for assignments.
    
    Returns:
        JSON response indicating success or error.
    """
    session_db = g.db_session
    try:
        # Get the current user's player record
        player = session_db.query(Player).filter_by(user_id=current_user.id, is_ref=True).first()
        if not player:
            return jsonify({'error': 'User is not a referee.'}), 404
        
        # Toggle availability
        player.is_available_for_ref = not player.is_available_for_ref
        session_db.commit()
        
        status = 'available' if player.is_available_for_ref else 'unavailable'
        logger.info(f"Referee {player.name} (ID: {player.id}) set availability to {status}")
        
        return jsonify({
            'message': f'Availability set to {status}',
            'is_available': player.is_available_for_ref
        }), 200
        
    except Exception as e:
        logger.exception("An error occurred while toggling referee availability.")
        session_db.rollback()
        return jsonify({'error': 'An internal error occurred.'}), 500


@calendar_bp.route('/calendar/availability_status', endpoint='availability_status', methods=['GET'])
@login_required
@role_required(['Pub League Ref'])
def availability_status():
    """
    Get current referee availability status.
    
    Returns:
        JSON response with availability status.
    """
    session_db = g.db_session
    try:
        # Get the current user's player record
        player = session_db.query(Player).filter_by(user_id=current_user.id, is_ref=True).first()
        if not player:
            return jsonify({'error': 'User is not a referee.'}), 404
        
        return jsonify({
            'is_available': player.is_available_for_ref,
            'referee_name': player.name
        }), 200
        
    except Exception as e:
        logger.exception("An error occurred while fetching referee availability.")
        return jsonify({'error': 'An internal error occurred.'}), 500


@calendar_bp.route('/calendar', endpoint='calendar_view', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Ref', 'Pub League Coach'])
def calendar_view():
    """
    Render the calendar view page.
    """
    # Check if user is a referee
    session_db = g.db_session
    is_referee = False
    if current_user.is_authenticated:
        player = session_db.query(Player).filter_by(user_id=current_user.id, is_ref=True).first()
        is_referee = player is not None
    
    # Check permissions for template
    from app.role_impersonation import is_impersonation_active, get_effective_roles, has_effective_permission
    
    if is_impersonation_active():
        user_roles = get_effective_roles()
        can_assign_referee = has_effective_permission('assign_referee')
        can_view_schedule_stats = has_effective_permission('view_schedule_stats')
        can_view_available_referees = has_effective_permission('view_available_referees')
    else:
        from app.utils.user_helpers import safe_current_user
        user_roles = [role.name for role in safe_current_user.roles] if hasattr(safe_current_user, 'roles') else []
        can_assign_referee = safe_current_user.has_permission('assign_referee')
        can_view_schedule_stats = safe_current_user.has_permission('view_schedule_stats')  
        can_view_available_referees = safe_current_user.has_permission('view_available_referees')
    
    return render_template('calendar.html', 
                         title='Pub League Calendar', 
                         is_referee=is_referee,
                         can_assign_referee=can_assign_referee,
                         can_view_schedule_stats=can_view_schedule_stats,
                         can_view_available_referees=can_view_available_referees)