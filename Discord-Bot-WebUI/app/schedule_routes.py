from flask import Blueprint, render_template, redirect, url_for, flash, request, g, jsonify
from flask_login import login_required
from app.models import Season, League, Team, Schedule, Match, ScheduledMessage
from app.decorators import role_required, handle_db_operation, query_operation
from datetime import datetime, date, time 
from collections import defaultdict
from sqlalchemy.orm import joinedload
from sqlalchemy import cast, Integer, text
from typing import List
import logging

# Get the logger for this module
logger = logging.getLogger(__name__)

schedule_bp = Blueprint('schedule', __name__)

@query_operation
def get_related_matches(schedule_id: int) -> List[Match]:
    """Get all matches related to a schedule."""
    return Match.query.filter(
        (Match.schedule_id == schedule_id) |
        (Match.schedule.has(Schedule.opponent == Schedule.query.get(schedule_id).team_id))
    ).all()

@handle_db_operation()
def update_match_records(schedule: Schedule, date: date, time: time, 
                        location: str, team_a_id: int, team_b_id: int) -> None:
    """Update or create match records for a schedule."""
    try:
        matches = Match.query.filter_by(schedule_id=schedule.id).all()
        
        if not matches:
            new_match = Match(
                date=date,
                time=time,
                location=location,
                home_team_id=team_a_id,
                away_team_id=team_b_id,
                schedule_id=schedule.id
            )
            Match.query.session.add(new_match)
        else:
            for match in matches:
                match.date = date
                match.time = time
                match.location = location
                match.home_team_id = team_a_id
                match.away_team_id = team_b_id
                
        logger.info(f"Successfully updated match records for schedule {schedule.id}")
        
    except Exception as e:
        logger.error(f"Error updating match records for schedule {schedule.id}: {str(e)}")
        raise

@query_operation
def get_season_and_league(season_id, league_name=None):
    """Helper function to get season and league."""
    season = Season.query.get_or_404(season_id)
    league = League.query.filter_by(name=league_name, season_id=season_id).first_or_404() if league_name else None
    return season, league

def format_match_schedule(matches):
    """Helper function to format match schedules."""
    schedule = {}
    displayed_matches = set()

    for match in matches:
        # Ensure the relationship is loaded correctly
        if not match.team:
            continue

        opponent_team = Team.query.get(int(match.opponent))
        if not opponent_team:
            continue

        match_key = (
            match.week,
            match.team.name,
            opponent_team.name,
            match.time.strftime('%H:%M:%S'),
            match.location
        )
        reverse_match_key = (
            match.week,
            opponent_team.name,
            match.team.name,
            match.time.strftime('%H:%M:%S'),
            match.location
        )

        if match_key in displayed_matches or reverse_match_key in displayed_matches:
            continue

        displayed_matches.add(match_key)
        displayed_matches.add(reverse_match_key)

        if match.week not in schedule:
            schedule[match.week] = {
                'date': match.date.strftime('%Y-%m-%d'),
                'matches': []
            }

        formatted_time = match.time.strftime('%I:%M %p')

        schedule[match.week]['matches'].append({
            'id': match.id,  # Added this line - include the actual match ID
            'team_a': match.team.name,
            'team_a_id': match.team.id,
            'team_b': opponent_team.name,
            'team_b_id': opponent_team.id,
            'time': formatted_time,
            'location': match.location,
        })

    return schedule

@handle_db_operation()
def handle_add_match(season_id, league_name, week):
    """Add a new match with proper session management."""
    try:
        @query_operation
        def get_league_and_teams():
            league = League.query.filter_by(name=league_name, season_id=season_id).first()
            if not league:
                return None, None, None
            team_a = Team.query.filter_by(name=request.form.get('teamA'), league_id=league.id).first()
            team_b = Team.query.filter_by(name=request.form.get('teamB'), league_id=league.id).first()
            return league, team_a, team_b

        league, team_a, team_b = get_league_and_teams()
        
        if not league:
            flash('League not found.', 'danger')
            return
            
        if not (team_a and team_b):
            flash('One or both teams not found.', 'danger')
            return
            
        new_match = Schedule(
            week=week,
            date=request.form.get('date'),
            time=request.form.get('time'),
            location=request.form.get('location'),
            team_id=team_a.id,
            opponent=team_b.id
        )
        db.session.add(new_match)
        flash(f'Match {team_a.name} vs {team_b.name} added successfully.', 'success')
        
    except Exception as e:
        logger.error(f"Error adding match: {e}")
        flash('Error occurred while adding the match.', 'danger')
        raise

# Helper function to handle week deletion
@handle_db_operation()
def handle_delete_week(season_id, week):
    try:
        Schedule.query.filter_by(week=str(week)).delete()
        flash(f'Week {week} and all its matches have been deleted.', 'success')
    except Exception as e:
        logger.error(f"Error deleting week {week}: {e}")
        flash(f'Failed to delete Week {week}.', 'danger')
        raise

@schedule_bp.route('/publeague/<int:season_id>/schedule', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@handle_db_operation()
def manage_publeague_schedule(season_id):
    season = Season.query.get_or_404(season_id)
    leagues = League.query.filter_by(season_id=season_id).all()

    if request.method == 'POST':
        action = request.form.get('action')
        league_name = request.form.get('league_name')
        week = request.form.get('week')

        if action == 'add':
            handle_add_match(season_id, league_name, week)
        elif action == 'delete':
            handle_delete_week(season_id, week)

        flash(f'Action "{action}" performed successfully.', 'success')
        return redirect(url_for('schedule.manage_publeague_schedule', season_id=season_id))

    # Serialize the leagues to a dictionary format
    serialized_leagues = [
        {
            'id': league.id,
            'name': league.name,
            'season_id': league.season_id,
            'teams': [{'id': team.id, 'name': team.name} for team in league.teams]
        } for league in leagues
    ]

    # GET request - Display the schedule
    schedule_data = {}
    for league in leagues:
        league_schedule = []
        for team in league.teams:
            # Fetch matches where the team is team_a (home team)
            matches_a = Schedule.query.filter_by(team_id=team.id).order_by(cast(Schedule.week, Integer).asc(), Schedule.time.asc()).all()
            league_schedule.extend(matches_a)
            # Fetch matches where the team is team_b (away team)
            matches_b = Schedule.query.filter_by(opponent=team.id).order_by(cast(Schedule.week, Integer).asc(), Schedule.time.asc()).all()
            league_schedule.extend(matches_b)
        # Format the schedule for the league
        schedule_data[league.name] = format_match_schedule(league_schedule)

    return render_template('manage_publeague_schedule.html', season=season, leagues=serialized_leagues, schedule=schedule_data)

@schedule_bp.route('/ecsfc/<int:season_id>/schedule', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@handle_db_operation()
def manage_ecsfc_schedule(season_id):
    season = Season.query.get_or_404(season_id)
    leagues = League.query.filter_by(season_id=season_id).all()

    leagues_data = []
    for league in leagues:
        league_info = {
            'id': league.id,
            'name': league.name,
            'teams': [{'id': team.id, 'name': team.name} for team in league.teams]
        }
        leagues_data.append(league_info)

    # Additional logic for schedule data
    schedule_data = {}
    for league in leagues:
        league_schedule = []
        for team in league.teams:
            matches = Schedule.query.filter_by(team_id=team.id).order_by(cast(Schedule.week, Integer).asc(), Schedule.time.asc()).all()
            league_schedule.extend(matches)
        schedule_data[league.name] = format_match_schedule(league_schedule)

    return render_template('manage_ecsfc_schedule.html', season=season, leagues=leagues_data, schedule=schedule_data)

@schedule_bp.route('/publeague/bulk_create_matches/<int:season_id>/<string:league_name>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@handle_db_operation()
def bulk_create_publeague_matches(season_id, league_name):
    try:
        season = Season.query.get_or_404(season_id)
        league = League.query.filter_by(name=league_name, season_id=season_id).first_or_404()
        
        total_weeks = int(request.form.get('total_weeks', 0))
        matches_per_week = int(request.form.get('matches_per_week', 0))
        
        if total_weeks == 0 or matches_per_week == 0:
            flash("Total Weeks and Matches Per Week are required fields.", 'danger')
            return redirect(url_for('schedule.manage_publeague_schedule', season_id=season_id))

        fun_week = request.form.get('fun_week')
        tst_week = request.form.get('tst_week')
        matches = []  # Collect all matches

        for week in range(1, total_weeks + 1):
            if str(week) in [fun_week, tst_week]:
                continue
                
            week_date = request.form.get(f'date_week{week}')
            if not week_date:
                flash(f"Date for Week {week} is missing.", 'danger')
                return redirect(url_for('schedule.manage_publeague_schedule', season_id=season_id))

            for match_num in range(1, matches_per_week + 1):
                team_a_id = request.form.get(f'teamA_week{week}_match{match_num}')
                team_b_id = request.form.get(f'teamB_week{week}_match{match_num}')
                time = request.form.get(f'time_week{week}_match{match_num}')
                location = request.form.get(f'location_week{week}_match{match_num}')

                if team_a_id and team_b_id and time and location:
                    matches.extend([
                        Schedule(
                            week=str(week),
                            date=week_date,
                            time=time,
                            opponent=team_b_id,
                            location=location,
                            team_id=team_a_id
                        ),
                        Schedule(
                            week=str(week),
                            date=week_date,
                            time=time,
                            opponent=team_a_id,
                            location=location,
                            team_id=team_b_id
                        )
                    ])

        # Return matches - decorator will handle session
        return matches

    except Exception as e:
        logger.error(f"Error creating bulk matches: {e}")
        flash('Error occurred while creating bulk matches.', 'danger')
        raise

@schedule_bp.route('/ecsfc/bulk_create_matches/<int:season_id>/<string:league_name>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def bulk_create_ecsfc_matches(season_id, league_name):
    """Bulk create matches with proper session management."""
    @query_operation
    def validate_season_and_league():
        season = Season.query.get_or_404(season_id)
        league = League.query.filter_by(name=league_name, season_id=season_id).first_or_404()
        return season, league

    try:
        season, league = validate_season_and_league()
        total_weeks = int(request.form.get('total_weeks', 0))
        matches_per_week = int(request.form.get('matches_per_week', 0))
        
        if total_weeks == 0 or matches_per_week == 0:
            flash("Total Weeks and Matches Per Week are required fields.", 'danger')
            return redirect(url_for('schedule.manage_ecsfc_schedule', season_id=season_id))

        fun_week = request.form.get('fun_week')
        tst_week = request.form.get('tst_week')

        @handle_db_operation()
        def create_week_matches(week):
            week_date = request.form.get(f'date_week{week}')
            if not week_date:
                raise ValueError(f"Date for Week {week} is missing.")

            for match_num in range(1, matches_per_week + 1):
                team_a_id = request.form.get(f'teamA_week{week}_match{match_num}')
                team_b_id = request.form.get(f'teamB_week{week}_match{match_num}')
                time = request.form.get(f'time_week{week}_match{match_num}')
                location = request.form.get(f'location_week{week}_match{match_num}')
                
                if all([team_a_id, team_b_id, time, location]):
                    # Create match for team A
                    schedule_a = Schedule(
                        week=str(week),
                        date=week_date,
                        time=time,
                        opponent=team_b_id,
                        location=location,
                        team_id=team_a_id
                    )
                    db.session.add(schedule_a)

                    # Create match for team B
                    schedule_b = Schedule(
                        week=str(week),
                        date=week_date,
                        time=time,
                        opponent=team_a_id,
                        location=location,
                        team_id=team_b_id
                    )
                    db.session.add(schedule_b)

        for week in range(1, total_weeks + 1):
            if str(week) in [fun_week, tst_week]:
                continue
            try:
                create_week_matches(week)
            except ValueError as ve:
                flash(str(ve), 'danger')
                return redirect(url_for('schedule.manage_ecsfc_schedule', season_id=season_id))

        flash(f'Bulk matches created for {league_name} league', 'success')
        return redirect(url_for('schedule.manage_ecsfc_schedule', season_id=season_id))

    except Exception as e:
        logger.error(f"Error creating bulk matches: {e}")
        flash('Error occurred while creating bulk matches.', 'danger')
        return redirect(url_for('schedule.manage_ecsfc_schedule', season_id=season_id))

@schedule_bp.route('/edit_match/<int:match_id>', methods=['POST'])
@role_required(['Pub League Admin', 'Global Admin'])
@handle_db_operation()
def edit_match(match_id):
    """Edit match and related records."""
    try:
        # Validate input data
        required_fields = ['date', 'time', 'location', 'team_a', 'team_b', 'week']
        if not all(field in request.form for field in required_fields):
            return jsonify({
                'success': False,
                'message': 'Missing required fields'
            }), 400

        try:
            date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
            time = datetime.strptime(request.form['time'], '%H:%M').time()
        except ValueError as e:
            return jsonify({
                'success': False,
                'message': f'Invalid date or time format: {str(e)}'
            }), 400

        location = request.form['location']
        team_a_id = request.form['team_a']
        team_b_id = request.form['team_b']
        week = request.form['week']

        # Get Schedule record
        schedule = Schedule.query.get(match_id)
        if not schedule:
            return jsonify({
                'success': False,
                'message': 'Schedule not found'
            }), 404

        # Update Schedule record
        schedule.date = date
        schedule.time = time
        schedule.location = location
        schedule.team_id = team_a_id
        schedule.opponent = team_b_id
        schedule.week = week

        objects_to_process = [schedule]

        # Update or create Match record
        match = Match.query.filter_by(schedule_id=match_id).first()
        if not match:
            match = Match(
                schedule_id=match_id,
                date=date,
                time=time,
                location=location,
                home_team_id=team_a_id,
                away_team_id=team_b_id
            )
            objects_to_process.append(match)
        else:
            match.date = date
            match.time = time
            match.location = location
            match.home_team_id = team_a_id
            match.away_team_id = team_b_id
            objects_to_process.append(match)

        # Update paired schedule if it exists
        paired_schedule = Schedule.query.filter_by(
            team_id=team_b_id,
            opponent=team_a_id,
            week=week
        ).first()

        if paired_schedule:
            paired_schedule.date = date
            paired_schedule.time = time
            paired_schedule.location = location
            objects_to_process.append(paired_schedule)

            paired_match = Match.query.filter_by(schedule_id=paired_schedule.id).first()
            if paired_match:
                paired_match.date = date
                paired_match.time = time
                paired_match.location = location
                paired_match.home_team_id = team_b_id
                paired_match.away_team_id = team_a_id
                objects_to_process.append(paired_match)

        return objects_to_process, jsonify({
            'success': True,
            'message': 'Match updated successfully'
        })

    except Exception as e:
        logger.error(f"Error editing match {match_id}: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error updating match: {str(e)}'
        }), 500

@schedule_bp.route('/delete_match/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@handle_db_operation()
def delete_match(match_id):
    """Delete match and related records."""
    try:
        logger.info(f"Attempting to delete match {match_id}")
        
        # Get all records to delete
        schedule = Schedule.query.get_or_404(match_id)
        objects_to_delete = []  # We'll build this in correct order
        
        # First get the matches and their scheduled messages
        match = Match.query.filter_by(schedule_id=match_id).first()
        if match:
            # Get and mark scheduled messages for deletion first
            scheduled_messages = ScheduledMessage.query.filter_by(match_id=match.id).all()
            for msg in scheduled_messages:
                msg.deleted = True
                objects_to_delete.append(msg)
            
            match.deleted = True
            objects_to_delete.append(match)
        
        # Get paired records
        paired_schedule = Schedule.query.filter_by(
            team_id=schedule.opponent,
            opponent=schedule.team_id,
            week=schedule.week
        ).first()
        
        if paired_schedule:
            paired_match = Match.query.filter_by(schedule_id=paired_schedule.id).first()
            if paired_match:
                # Get and mark paired match's scheduled messages
                paired_messages = ScheduledMessage.query.filter_by(match_id=paired_match.id).all()
                for msg in paired_messages:
                    msg.deleted = True
                    objects_to_delete.append(msg)
                
                paired_match.deleted = True
                objects_to_delete.append(paired_match)
                
            # Mark paired schedule for deletion after its match
            paired_schedule.deleted = True
            objects_to_delete.append(paired_schedule)
            
        # Mark original schedule for deletion last
        schedule.deleted = True
        objects_to_delete.append(schedule)
            
        logger.info(f"Successfully marked match {match_id} and related records for deletion")
        
        # Return both the objects to delete and the response
        response = jsonify({
            'success': True,
            'message': 'Match deleted successfully'
        })
        
        return objects_to_delete, response
        
    except Exception as e:
        logger.error(f"Error deleting match {match_id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error deleting match: {str(e)}'
        }), 500

@schedule_bp.route('/<string:league_type>/<int:season_id>/delete_week/<int:week_number>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
@handle_db_operation()
def delete_week(league_type, season_id, week_number):
    try:
        Schedule.query.filter_by(week=str(week_number), season_id=season_id).delete()
        flash(f'Week {week_number} and all its matches have been deleted.', 'success')
    except Exception as e:
        logger.error(f"Error deleting week {week_number}: {e}")
        flash(f'Failed to delete Week {week_number}.', 'danger')
        raise

    if league_type == "publeague":
        return redirect(url_for('schedule.manage_publeague_schedule', season_id=season_id))
    elif league_type == "ecsfc":
        return redirect(url_for('schedule.manage_ecsfc_schedule', season_id=season_id))

@schedule_bp.route('/fetch_schedule', methods=['GET'])
@query_operation
def fetch_schedule():
    """Fetch schedule with team filtering capability."""
    team_id = request.args.get('team_id')
    league_id = request.args.get('league_id')
    
    query = Schedule.query

    if team_id:
        query = query.filter(
            (Schedule.team_id == team_id) | (Schedule.opponent == team_id)
        )
    if league_id:
        query = query.join(Team).filter(Team.league_id == league_id)

    schedules = query.all()
    return jsonify([schedule.to_dict() for schedule in schedules])

@schedule_bp.route('/add_match', methods=['POST'])
@role_required(['Pub League Admin', 'Global Admin'])
@handle_db_operation()
def add_match():
    """Add a new match and its related records."""
    try:
        # Validate required fields
        required_fields = ['week', 'date', 'time', 'location', 'team_a', 'team_b']
        if not all(field in request.form for field in required_fields):
            return jsonify({
                'success': False,
                'message': 'Missing required fields'
            }), 400

        try:
            date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
            time = datetime.strptime(request.form['time'], '%H:%M').time()
        except ValueError as e:
            return jsonify({
                'success': False,
                'message': f'Invalid date or time format: {str(e)}'
            }), 400

        week = request.form['week']
        location = request.form['location']
        team_a_id = request.form['team_a']
        team_b_id = request.form['team_b']

        # Create records - let decorator handle session management
        schedule_a = Schedule(
            week=week,
            date=date,
            time=time,
            location=location,
            team_id=team_a_id,
            opponent=team_b_id
        )

        schedule_b = Schedule(
            week=week,
            date=date,
            time=time,
            location=location,
            team_id=team_b_id,
            opponent=team_a_id
        )

        match = Match(
            date=date,
            time=time,
            location=location,
            home_team_id=team_a_id,
            away_team_id=team_b_id,
            schedule=schedule_a
        )

        return [schedule_a, schedule_b, match], jsonify({
            'success': True,
            'message': 'Match added successfully'
        }), 201

    except Exception as e:
        logger.error(f"Error adding match: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error adding match: {str(e)}'
        }), 500
