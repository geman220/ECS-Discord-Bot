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
@role_required(['Pub League Admin', 'Global Admin'])
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
        for match in matches:
            division = 'Premier' if match.home_league_id == 10 else 'Classic'
            # Combine date and time into a single datetime object
            start_datetime = datetime.combine(match.date, match.time)
            events.append({
                'id': match.id,
                'title': f"{division}: {match.home_team_name} vs {match.away_team_name}",
                'start': start_datetime.isoformat(),
                'description': f"Location: {match.location}",
                'color': 'blue' if division == 'Premier' else 'green',
                'url': f"/matches/{match.id}",
                'ref': match.ref_name if match.ref_name else 'Unassigned',
                'division': division,  # Add division to extendedProps
                'teams': f"{match.home_team_name} vs {match.away_team_name}"  # Add teams to extendedProps
            })

        logger.info(f"Events sent to FullCalendar: {events}")

        return jsonify(events)

    except Exception as e:
        logger.exception("An error occurred while fetching events.")
        return jsonify({'error': 'An internal error occurred.'}), 500

@calendar_bp.route('/calendar/refs', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def get_refs():
    try:
        match_id = request.args.get('match_id', type=int)
        if not match_id:
            logger.warning("Missing match_id parameter.")
            return jsonify({'error': 'match_id parameter is required.'}), 400

        match = Match.query.get(match_id)
        if not match:
            logger.warning(f"Match not found: ID {match_id}")
            return jsonify({'error': 'Match not found.'}), 404

        logger.info(f"Fetching referees for Match ID: {match_id}")

        match_date = match.date
        match_time = match.time
        home_team_id = match.home_team_id
        away_team_id = match.away_team_id

        # Query refs who are eligible
        refs = Player.query.filter_by(is_ref=True).filter(
            ~Player.team_id.in_([home_team_id, away_team_id])  # Exclude refs on either team
        )

        # Log the refs being considered
        logger.info(f"Refs available before conflict filtering: {[ref.name for ref in refs]}")

        # Subquery to find refs already assigned to a match at the same date and time
        conflicting_refs_subquery = db.session.query(Match.ref_id).filter(
            Match.date == match_date,
            Match.time == match_time,
            Match.ref_id != None,  # Ensure ref_id is not null
            Match.id != match_id  # Exclude current match if ref is already assigned
        ).subquery()

        # Exclude refs who are already assigned to another match at the same date and time
        refs = refs.filter(~Player.id.in_(conflicting_refs_subquery))

        # Log conflicting refs to help debug assignment issues
        conflicting_refs = db.session.query(Player.name).filter(Player.id.in_(conflicting_refs_subquery)).all()
        logger.info(f"Conflicting refs at the same time: {conflicting_refs}")

        ref_list = [{'id': ref.id, 'name': ref.name} for ref in refs]
        logger.info(f"Returning refs: {ref_list}")
        
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
        db.session.commit()

        return jsonify({'message': 'Referee assigned successfully.'}), 200

    except Exception as e:
        logger.exception("An error occurred while assigning the referee.")
        return jsonify({'error': 'An internal error occurred.'}), 500

@calendar_bp.route('/calendar/available_refs', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def get_available_refs():
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        if not start_date or not end_date:
            return jsonify({'error': 'Missing start_date or end_date parameter.'}), 400

        # Convert dates from ISO string to actual date objects
        start_date = datetime.fromisoformat(start_date)
        end_date = datetime.fromisoformat(end_date)

        # Get all referees
        refs = Player.query.filter_by(is_ref=True).all()

        available_refs = []
        for ref in refs:
            # Check if the referee is assigned to any match during the given date range
            matches_in_week = Match.query.filter(
                Match.ref_id == ref.id,
                Match.date >= start_date,
                Match.date <= end_date
            ).count()

            if matches_in_week == 0:
                available_refs.append({
                    'id': ref.id,
                    'name': ref.name,
                    'matches_assigned_in_week': matches_in_week
                })

        return jsonify(available_refs)

    except Exception as e:
        logger.exception("Error fetching available referees")
        return jsonify({'error': 'An error occurred while fetching referees.'}), 500

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
        db.session.commit()

        return jsonify({'message': 'Referee removed successfully.'}), 200

    except Exception as e:
        logger.exception("An error occurred while removing the referee.")
        return jsonify({'error': 'An internal error occurred.'}), 500

@calendar_bp.route('/calendar', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def calendar_view():
    return render_template('calendar.html')