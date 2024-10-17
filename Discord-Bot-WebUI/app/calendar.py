from app import db, login_manager
from datetime import datetime
from flask import Blueprint, jsonify, render_template, request
from app.models import Match, Team, Season, League, Player
from sqlalchemy.orm import aliased
from flask_login import login_required
from app.decorators import role_required
import logging

# Get the logger for this module
logger = logging.getLogger(__name__)

calendar_bp = Blueprint('calendar', __name__)

@calendar_bp.route('/calendar/events', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Ref'])
def get_schedule():
    try:
        # Get all current seasons
        seasons = Season.query.filter_by(is_current=True).all()
        if not seasons:
            logger.warning("No current season found.")
            return jsonify({'error': 'No current season found.'}), 404

        # Collect all league IDs for the current seasons (Pub League and ECS FC)
        league_ids = [league.id for season in seasons for league in season.leagues]

        home_team = aliased(Team)
        away_team = aliased(Team)

        # Query all matches for all current seasons using the league IDs
        matches = (Match.query
                   .join(home_team, Match.home_team_id == home_team.id)
                   .join(away_team, Match.away_team_id == away_team.id)
                   .outerjoin(Player, Match.ref_id == Player.id)
                   .with_entities(
                       Match.id,
                       Match.date,
                       Match.time,
                       Match.location,
                       home_team.name.label('home_team_name'),
                       away_team.name.label('away_team_name'),
                       home_team.league_id.label('home_league_id'),
                       Player.name.label('ref_name')  # Include ref name
                   )
                   .filter(home_team.league_id.in_(league_ids))
                   .all())

        if not matches:
            logger.warning("No matches found for the current seasons.")
            return jsonify({'message': 'No matches found'}), 404

        # Format the matches as events for FullCalendar
        events = []
        total_matches = len(matches)
        assigned_refs = 0

        for match in matches:
            division = 'Premier' if match.home_league_id == 10 else 'Classic'
            # Combine date and time into a single datetime object
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

@calendar_bp.route('/calendar/refs', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Ref'])
def get_refs():
    try:
        match_id = request.args.get('match_id', type=int)
        if not match_id:
            return jsonify({'error': 'match_id parameter is required.'}), 400

        match = Match.query.get(match_id)
        if not match:
            return jsonify({'error': 'Match not found.'}), 404

        # Query refs who are eligible
        refs = Player.query.filter_by(is_ref=True).all()

        ref_list = []
        for ref in refs:
            # Check if ref is on either team in this match
            if ref.team_id not in [match.home_team_id, match.away_team_id]:
                # Count the matches assigned to this referee in the current week
                matches_assigned_in_week = Match.query.filter_by(ref_id=ref.id).filter(
                    Match.date == match.date
                ).count()

                # Count the total matches assigned to this referee
                total_matches_assigned = Match.query.filter_by(ref_id=ref.id).count()

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

@calendar_bp.route('/calendar/assign_ref', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def assign_ref():
    try:
        data = request.get_json()
        match_id = data.get('match_id')
        ref_id = data.get('ref_id')

        if not match_id or not ref_id:
            logger.warning("Match ID and Ref ID are required.")
            return jsonify({'error': 'Match ID and Ref ID are required.'}), 400

        match = Match.query.get(match_id)
        if not match:
            logger.warning(f"Match not found: ID {match_id}")
            return jsonify({'error': 'Match not found.'}), 404

        ref = Player.query.get(ref_id)
        if not ref or not ref.is_ref:
            logger.error(f"Attempted to assign invalid ref: Player ID {ref_id}")
            return jsonify({'error': 'Invalid referee.'}), 400

        # Check if ref is already assigned to another match at the same date and time
        conflicting_match = Match.query.filter(
            Match.ref_id == ref_id,
            Match.date == match.date,
            Match.time == match.time,
            Match.id != match_id
        ).first()

        if conflicting_match:
            logger.error(f"Referee already assigned to match {conflicting_match.id} at the same time.")
            return jsonify({'error': 'Referee is already assigned to another match at this time.'}), 400

        # Check if ref is on either team in this match
        if ref.team_id in [match.home_team_id, match.away_team_id]:
            logger.error(f"Referee {ref.name} is a player on one of the teams.")
            return jsonify({'error': 'Referee is on one of the teams in this match.'}), 400

        # Assign the ref
        logger.info(f"Assigning Referee {ref.name} (ID: {ref_id}) to Match ID {match_id}")
        match.ref = ref

        # Commit changes to the database
        try:
            db.session.commit()
            return jsonify({'message': 'Referee assigned successfully.'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error committing referee assignment: {str(e)}")
            return jsonify({'error': 'An internal error occurred while assigning the referee.'}), 500

    except Exception as e:
        logger.exception("An error occurred while assigning the referee.")
        return jsonify({'error': 'An internal error occurred.'}), 500

@calendar_bp.route('/calendar/available_refs', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Ref'])
def available_refs():
    try:
        # Parse start_date and end_date from the request parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        if not start_date or not end_date:
            return jsonify({'error': 'start_date and end_date parameters are required.'}), 400

        start_date = datetime.fromisoformat(start_date)
        end_date = datetime.fromisoformat(end_date)

        # Fetch all referees
        refs = Player.query.filter_by(is_ref=True).all()
        ref_list = []

        for ref in refs:
            # Count the number of matches assigned to this referee in the current week (start_date to end_date)
            matches_assigned_in_week = Match.query.filter_by(ref_id=ref.id).filter(
                Match.date >= start_date, Match.date <= end_date
            ).count()

            # Count the total number of matches assigned to this referee
            total_matches_assigned = Match.query.filter_by(ref_id=ref.id).count()

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

@calendar_bp.route('/calendar/remove_ref', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def remove_ref():
    try:
        data = request.get_json()
        match_id = data.get('match_id')

        if not match_id:
            logger.warning("Match ID is required to remove referee.")
            return jsonify({'error': 'Match ID is required.'}), 400

        match = Match.query.get(match_id)
        if not match:
            logger.warning(f"Match not found: ID {match_id}")
            return jsonify({'error': 'Match not found.'}), 404

        if not match.ref:
            logger.info(f"No referee assigned to match ID {match_id}.")
            return jsonify({'error': 'No referee assigned to this match.'}), 400

        # Remove the referee
        logger.info(f"Removing referee {match.ref.name} from match ID {match_id}.")
        match.ref = None

        # Commit changes to the database
        try:
            db.session.commit()
            return jsonify({'message': 'Referee removed successfully.'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error committing referee removal: {str(e)}")
            return jsonify({'error': 'An internal error occurred while removing the referee.'}), 500

    except Exception as e:
        logger.exception("An error occurred while removing the referee.")
        return jsonify({'error': 'An internal error occurred.'}), 500

@calendar_bp.route('/calendar', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Ref'])
def calendar_view():
    return render_template('calendar.html')