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

from app.models import Match, Team, Season, Player, player_teams, League
from app.models.calendar import LeagueEvent
from app.models.ecs_fc import EcsFcMatch
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
        home_league = aliased(League)

        matches = (session_db.query(Match)
                   .join(home_team, Match.home_team_id == home_team.id)
                   .join(away_team, Match.away_team_id == away_team.id)
                   .join(home_league, home_team.league_id == home_league.id)
                   .outerjoin(ref_player, Match.ref_id == ref_player.id)
                   .with_entities(
                       Match.id,
                       Match.date,
                       Match.time,
                       Match.location,
                       home_team.name.label('home_team_name'),
                       away_team.name.label('away_team_name'),
                       home_league.name.label('home_league_name'),
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
            # Determine division from league name
            division = match.home_league_name or 'Classic'
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

        # Add league events to the calendar
        try:
            league_events = session_db.query(LeagueEvent).filter(
                LeagueEvent.is_active == True
            ).all()

            # Color mapping for event types
            event_type_colors = {
                'party': '#9c27b0',       # Purple
                'meeting': '#2196f3',     # Blue
                'social': '#e91e63',      # Pink
                'plop': '#4caf50',        # Green
                'tournament': '#ffc107',  # Yellow/Gold
                'fundraiser': '#ff5722',  # Deep Orange
                'other': '#607d8b',       # Blue-grey
            }

            for league_event in league_events:
                event_color = event_type_colors.get(league_event.event_type, '#607d8b')
                events.append({
                    'id': f'event-{league_event.id}',
                    'title': league_event.title,
                    'start': league_event.start_datetime.isoformat() if league_event.start_datetime else None,
                    'end': league_event.end_datetime.isoformat() if league_event.end_datetime else None,
                    'allDay': league_event.is_all_day,
                    'color': event_color,
                    'type': 'league_event',
                    'eventType': league_event.event_type,
                    'description': league_event.description,
                    'location': league_event.location,
                    'notify_discord': league_event.notify_discord,
                    'extendedProps': {
                        'type': 'league_event',
                        'eventType': league_event.event_type,
                        'description': league_event.description,
                        'location': league_event.location,
                        'leagueId': league_event.league_id,
                        'seasonId': league_event.season_id,
                    }
                })
        except Exception as e:
            logger.warning(f"Could not load league events: {e}")

        # Add ECS FC matches to the calendar
        ecs_fc_match_count = 0
        try:
            ecs_fc_matches = session_db.query(EcsFcMatch).options(
                joinedload(EcsFcMatch.team)
            ).all()

            for match in ecs_fc_matches:
                start_datetime = datetime.combine(match.match_date, match.match_time)
                team_name = match.team.name if match.team else 'ECS FC'

                # Format title based on home/away
                if match.is_home_match:
                    title = f"ECS FC: {team_name} vs {match.opponent_name}"
                else:
                    title = f"ECS FC: {team_name} @ {match.opponent_name}"

                events.append({
                    'id': f'ecsfc-{match.id}',
                    'title': title,
                    'start': start_datetime.isoformat(),
                    'description': f"Location: {match.location}",
                    'color': '#7b1fa2',  # Purple for ECS FC
                    'type': 'ecs_fc',
                    'division': 'ECS FC',
                    'teams': f"{team_name} vs {match.opponent_name}",
                    'location': match.location,
                    'ref': 'N/A',  # ECS FC matches don't have refs assigned the same way
                    'extendedProps': {
                        'type': 'ecs_fc',
                        'matchId': match.id,
                        'teamId': match.team_id,
                        'isHomeMatch': match.is_home_match,
                        'status': match.status,
                        'fieldName': match.field_name,
                        'notes': match.notes,
                    }
                })
                ecs_fc_match_count += 1

        except Exception as e:
            logger.warning(f"Could not load ECS FC matches: {e}")

        # For referees, also include which matches they can edit
        referee_assigned_matches = []
        from app.role_impersonation import is_impersonation_active, get_effective_roles
        
        if is_impersonation_active():
            user_roles = get_effective_roles()
            is_referee_role = 'Pub League Ref' in user_roles
        else:
            from app.utils.user_helpers import safe_current_user
            user_roles = [role.name for role in safe_current_user.roles] if hasattr(safe_current_user, 'roles') else []
            is_referee_role = 'Pub League Ref' in user_roles
        
        if is_referee_role and not is_impersonation_active():
            # Get actual referee assignments for real users
            referee_player = session_db.query(Player).filter_by(user_id=current_user.id, is_ref=True).first()
            if referee_player:
                referee_assigned_matches = [match.id for match in matches if hasattr(match, 'id') and match.id in [m.id for m in session_db.query(Match).filter_by(ref_id=referee_player.id).all()]]

        return jsonify({
            'events': events,
            'stats': {
                'totalMatches': total_matches,
                'assignedRefs': assigned_refs,
                'unassignedMatches': unassigned_matches
            },
            'referee_assigned_matches': referee_assigned_matches
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
        from app.role_impersonation import is_impersonation_active, get_effective_roles
        
        # Check if role impersonation is active
        if is_impersonation_active():
            # When impersonating, return empty assignments for testing purposes
            return jsonify({
                'assignments': [],
                'total_assignments': 0,
                'message': 'Role impersonation active - no assignments shown'
            })
        
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
        home_league = aliased(League)

        # Get matches assigned to this referee
        matches = (session_db.query(Match)
                   .join(home_team, Match.home_team_id == home_team.id)
                   .join(away_team, Match.away_team_id == away_team.id)
                   .join(home_league, home_team.league_id == home_league.id)
                   .filter(Match.ref_id == player.id)
                   .filter(home_team.league_id.in_(league_ids))
                   .with_entities(
                       Match.id,
                       Match.date,
                       Match.time,
                       Match.location,
                       home_team.name.label('home_team_name'),
                       away_team.name.label('away_team_name'),
                       home_league.name.label('home_league_name')
                   )
                   .order_by(Match.date, Match.time)
                   .all())

        assignments = []
        for match in matches:
            division = match.home_league_name or 'Classic'
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
        from app.role_impersonation import is_impersonation_active
        
        # Check if role impersonation is active
        if is_impersonation_active():
            # When impersonating, return a mock response
            return jsonify({
                'message': 'Availability toggled (impersonation mode)',
                'is_available': True
            }), 200
        
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
        from app.role_impersonation import is_impersonation_active
        
        # Check if role impersonation is active
        if is_impersonation_active():
            # When impersonating, return a mock response
            return jsonify({
                'is_available': True,
                'referee_name': 'Impersonated Referee'
            }), 200
        
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


@calendar_bp.route('/calendar/public_events', endpoint='public_events', methods=['GET'])
def public_events():
    """
    Retrieve public league events for unauthenticated users.

    This endpoint returns only league events (not matches) that are marked as active.
    Used for the public calendar view.

    Returns:
        JSON response containing the list of public events.
    """
    session_db = g.db_session
    try:
        events = []

        # Only fetch league events for public view
        league_events = session_db.query(LeagueEvent).filter(
            LeagueEvent.is_active == True
        ).all()

        # Color mapping for event types
        event_type_colors = {
            'party': '#9c27b0',       # Purple
            'meeting': '#2196f3',     # Blue
            'social': '#e91e63',      # Pink
            'plop': '#4caf50',        # Green
            'tournament': '#ffc107',  # Yellow/Gold
            'fundraiser': '#ff5722',  # Deep Orange
            'other': '#607d8b',       # Blue-grey
        }

        for league_event in league_events:
            event_color = event_type_colors.get(league_event.event_type, '#607d8b')
            events.append({
                'id': f'event-{league_event.id}',
                'title': league_event.title,
                'start': league_event.start_datetime.isoformat() if league_event.start_datetime else None,
                'end': league_event.end_datetime.isoformat() if league_event.end_datetime else None,
                'allDay': league_event.is_all_day,
                'color': event_color,
                'type': 'league_event',
                'eventType': league_event.event_type,
                'description': league_event.description,
                'location': league_event.location,
                'extendedProps': {
                    'type': 'league_event',
                    'eventType': league_event.event_type,
                    'description': league_event.description,
                    'location': league_event.location,
                }
            })

        return jsonify({
            'events': events,
            'stats': {
                'totalEvents': len(events)
            }
        })

    except Exception as e:
        logger.exception("An error occurred while fetching public events.")
        return jsonify({'error': 'An internal error occurred.'}), 500


@calendar_bp.route('/calendar', endpoint='calendar_view', methods=['GET'])
def calendar_view():
    """
    Render the calendar view page.

    This route is accessible to both authenticated and unauthenticated users:
    - Unauthenticated users see a public read-only calendar with league events only
    - Authenticated users with teams see their team's matches
    - Authenticated users with admin/coach/ref roles see additional features
    """
    session_db = g.db_session

    # Check if user is authenticated
    if not current_user.is_authenticated:
        # Public view - show read-only calendar with league events
        return render_template('calendar_public_flowbite.html',
                             title='ECS Pub League Calendar',
                             is_public=True,
                             is_authenticated=False)

    # Check permissions for template based on roles
    from app.role_impersonation import is_impersonation_active, get_effective_roles

    if is_impersonation_active():
        user_roles = get_effective_roles()
    else:
        from app.utils.user_helpers import safe_current_user
        user_roles = [role.name for role in safe_current_user.roles] if hasattr(safe_current_user, 'roles') else []

    # Check if user has special roles for full calendar access
    special_roles = ['Pub League Admin', 'Global Admin', 'Pub League Ref', 'Pub League Coach']
    has_special_role = any(role in special_roles for role in user_roles)

    # Check if user is a player with team associations (regular players can see their matches)
    player = session_db.query(Player).filter_by(user_id=current_user.id).first()
    has_team = player and player.teams and len(player.teams) > 0

    # Users need either a special role OR be a player with teams to see the full calendar
    if not has_special_role and not has_team:
        # User is authenticated but has no teams and no special roles - show public view
        return render_template('calendar_public_flowbite.html',
                             title='ECS Pub League Calendar',
                             is_public=True,
                             is_authenticated=True)

    # Full calendar view for authorized users
    is_referee = False
    if is_impersonation_active():
        # When impersonating, check if the impersonated role is 'Pub League Ref'
        is_referee = 'Pub League Ref' in user_roles
    else:
        # When not impersonating, check the actual player record
        is_referee = player is not None and player.is_ref

    # Pub League Admin and Global Admin have full calendar access
    # Pub League Coaches and Refs have limited access
    is_admin = any(role in ['Pub League Admin', 'Global Admin'] for role in user_roles)
    is_coach = any(role in ['Pub League Coach', 'ECS FC Coach'] for role in user_roles)
    can_assign_referee = is_admin
    can_view_schedule_stats = is_admin
    can_view_available_referees = is_admin
    can_edit_events = is_admin  # Only admins can create/edit league events

    # Determine if this is a regular player (not admin, coach, or ref)
    is_regular_player = has_team and not is_admin and not is_coach and not is_referee

    return render_template('calendar_flowbite.html',
                         title='Pub League Calendar',
                         is_referee=is_referee,
                         is_regular_player=is_regular_player,
                         can_assign_referee=can_assign_referee,
                         can_view_schedule_stats=can_view_schedule_stats,
                         can_view_available_referees=can_view_available_referees,
                         can_edit_referee_matches=is_referee,
                         can_edit_events=can_edit_events)