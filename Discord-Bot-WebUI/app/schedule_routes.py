from flask import Blueprint, render_template, redirect, url_for, flash, request, g, jsonify, abort
from flask_login import login_required
from datetime import datetime, date, time
from collections import defaultdict
from sqlalchemy.orm import joinedload
from sqlalchemy import cast, Integer
from typing import List
import logging

from app.decorators import role_required
from app.models import Season, League, Team, Schedule, Match, ScheduledMessage

logger = logging.getLogger(__name__)

schedule_bp = Blueprint('schedule', __name__)

def get_related_matches(schedule_id: int) -> List[Match]:
    """Get all matches related to a schedule."""
    session = g.db_session
    base_schedule = session.query(Schedule).get(schedule_id)
    if not base_schedule:
        return []
    return session.query(Match).filter(
        (Match.schedule_id == schedule_id) |
        (Match.schedule.has(Schedule.opponent == base_schedule.team_id))
    ).all()

def update_match_records(session, schedule: Schedule, match_date: date, match_time: time, 
                         location: str, team_a_id: int, team_b_id: int) -> None:
    """Update or create match records for a schedule."""
    try:
        matches = session.query(Match).filter_by(schedule_id=schedule.id).all()

        if not matches:
            new_match = Match(
                date=match_date,
                time=match_time,
                location=location,
                home_team_id=team_a_id,
                away_team_id=team_b_id,
                schedule_id=schedule.id
            )
            session.add(new_match)
        else:
            for match in matches:
                match.date = match_date
                match.time = match_time
                match.location = location
                match.home_team_id = team_a_id
                match.away_team_id = team_b_id

        logger.info(f"Successfully updated match records for schedule {schedule.id}")

    except Exception as e:
        logger.error(f"Error updating match records for schedule {schedule.id}: {str(e)}")
        raise

def get_season_and_league(session, season_id, league_name=None):
    """Helper function to get season and league."""
    season = session.query(Season).get(season_id)
    if not season:
        abort(404)

    league = None
    if league_name:
        league = session.query(League).filter_by(name=league_name, season_id=season_id).first()
        if not league:
            abort(404)

    return season, league

def format_match_schedule(session, matches):
    """Helper function to format match schedules."""
    schedule = {}
    displayed_matches = set()

    for match in matches:
        if not match.team:
            continue

        opponent_team = session.query(Team).get(int(match.opponent))
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
            'id': match.id,
            'team_a': match.team.name,
            'team_a_id': match.team.id,
            'team_b': opponent_team.name,
            'team_b_id': opponent_team.id,
            'time': formatted_time,
            'location': match.location,
        })

    return schedule

def handle_add_match(session, season_id, league_name, week):
    """Add a new match with proper session management."""
    try:
        league = session.query(League).filter_by(name=league_name, season_id=season_id).first()
        if not league:
            flash('League not found.', 'danger')
            return

        team_a = session.query(Team).filter_by(name=request.form.get('teamA'), league_id=league.id).first()
        team_b = session.query(Team).filter_by(name=request.form.get('teamB'), league_id=league.id).first()

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
        session.add(new_match)
        flash(f'Match {team_a.name} vs {team_b.name} added successfully.', 'success')

    except Exception as e:
        logger.error(f"Error adding match: {e}")
        flash('Error occurred while adding the match.', 'danger')
        raise

def handle_delete_week(session, season_id, week):
    try:
        session.query(Schedule).filter_by(week=str(week), season_id=season_id).delete()
        flash(f'Week {week} and all its matches have been deleted.', 'success')
    except Exception as e:
        logger.error(f"Error deleting week {week}: {e}")
        flash(f'Failed to delete Week {week}.', 'danger')
        raise

@schedule_bp.route('/publeague/<int:season_id>/schedule', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_publeague_schedule(season_id):
    session = g.db_session
    season = session.query(Season).get(season_id)
    if not season:
        abort(404)

    leagues = session.query(League).filter_by(season_id=season_id).all()

    if request.method == 'POST':
        action = request.form.get('action')
        league_name = request.form.get('league_name')
        week = request.form.get('week')

        if action == 'add':
            handle_add_match(session, season_id, league_name, week)
        elif action == 'delete':
            handle_delete_week(session, season_id, week)

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
            matches_a = session.query(Schedule).filter_by(team_id=team.id).order_by(cast(Schedule.week, Integer).asc(), Schedule.time.asc()).all()
            league_schedule.extend(matches_a)
            matches_b = session.query(Schedule).filter_by(opponent=team.id).order_by(cast(Schedule.week, Integer).asc(), Schedule.time.asc()).all()
            league_schedule.extend(matches_b)
        schedule_data[league.name] = format_match_schedule(session, league_schedule)

    return render_template('manage_publeague_schedule.html', season=season, leagues=serialized_leagues, schedule=schedule_data)

@schedule_bp.route('/ecsfc/<int:season_id>/schedule', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_ecsfc_schedule(season_id):
    session = g.db_session
    season = session.query(Season).get(season_id)
    if not season:
        abort(404)

    leagues = session.query(League).filter_by(season_id=season_id).all()

    leagues_data = []
    for league in leagues:
        league_info = {
            'id': league.id,
            'name': league.name,
            'teams': [{'id': team.id, 'name': team.name} for team in league.teams]
        }
        leagues_data.append(league_info)

    schedule_data = {}
    for league in leagues:
        league_schedule = []
        for team in league.teams:
            matches = session.query(Schedule).filter_by(team_id=team.id).order_by(cast(Schedule.week, Integer).asc(), Schedule.time.asc()).all()
            league_schedule.extend(matches)
        schedule_data[league.name] = format_match_schedule(session, league_schedule)

    return render_template('manage_ecsfc_schedule.html', season=season, leagues=leagues_data, schedule=schedule_data)

@schedule_bp.route('/publeague/bulk_create_matches/<int:season_id>/<string:league_name>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def bulk_create_publeague_matches(season_id, league_name):
    session = g.db_session
    season = session.query(Season).get(season_id)
    if not season:
        abort(404)

    league = session.query(League).filter_by(name=league_name, season_id=season_id).first()
    if not league:
        abort(404)

    try:
        total_weeks = int(request.form.get('total_weeks', 0))
        matches_per_week = int(request.form.get('matches_per_week', 0))

        if total_weeks == 0 or matches_per_week == 0:
            flash("Total Weeks and Matches Per Week are required fields.", 'danger')
            return redirect(url_for('schedule.manage_publeague_schedule', season_id=season_id))

        fun_week = request.form.get('fun_week')
        tst_week = request.form.get('tst_week')

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
                t = request.form.get(f'time_week{week}_match{match_num}')
                location = request.form.get(f'location_week{week}_match{match_num}')

                if team_a_id and team_b_id and t and location:
                    schedule_a = Schedule(
                        week=str(week),
                        date=week_date,
                        time=t,
                        opponent=team_b_id,
                        location=location,
                        team_id=team_a_id
                    )
                    session.add(schedule_a)

                    schedule_b = Schedule(
                        week=str(week),
                        date=week_date,
                        time=t,
                        opponent=team_a_id,
                        location=location,
                        team_id=team_b_id
                    )
                    session.add(schedule_b)

        flash(f'Bulk matches created for {league_name} league', 'success')
        return redirect(url_for('schedule.manage_publeague_schedule', season_id=season_id))

    except Exception as e:
        logger.error(f"Error creating bulk matches: {e}")
        flash('Error occurred while creating bulk matches.', 'danger')
        return redirect(url_for('schedule.manage_publeague_schedule', season_id=season_id))

@schedule_bp.route('/ecsfc/bulk_create_matches/<int:season_id>/<string:league_name>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def bulk_create_ecsfc_matches(season_id, league_name):
    session = g.db_session
    season = session.query(Season).get(season_id)
    if not season:
        abort(404)

    league = session.query(League).filter_by(name=league_name, season_id=season_id).first()
    if not league:
        abort(404)

    try:
        total_weeks = int(request.form.get('total_weeks', 0))
        matches_per_week = int(request.form.get('matches_per_week', 0))

        if total_weeks == 0 or matches_per_week == 0:
            flash("Total Weeks and Matches Per Week are required fields.", 'danger')
            return redirect(url_for('schedule.manage_ecsfc_schedule', season_id=season_id))

        fun_week = request.form.get('fun_week')
        tst_week = request.form.get('tst_week')

        def create_week_matches(week):
            week_date = request.form.get(f'date_week{week}')
            if not week_date:
                raise ValueError(f"Date for Week {week} is missing.")

            for match_num in range(1, matches_per_week + 1):
                team_a_id = request.form.get(f'teamA_week{week}_match{match_num}')
                team_b_id = request.form.get(f'teamB_week{week}_match{match_num}')
                t = request.form.get(f'time_week{week}_match{match_num}')
                location = request.form.get(f'location_week{week}_match{match_num}')

                if all([team_a_id, team_b_id, t, location]):
                    schedule_a = Schedule(
                        week=str(week),
                        date=week_date,
                        time=t,
                        opponent=team_b_id,
                        location=location,
                        team_id=team_a_id
                    )
                    session.add(schedule_a)

                    schedule_b = Schedule(
                        week=str(week),
                        date=week_date,
                        time=t,
                        opponent=team_a_id,
                        location=location,
                        team_id=team_b_id
                    )
                    session.add(schedule_b)

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
def edit_match(match_id):
    session = g.db_session
    """Edit match and related records."""
    try:
        required_fields = ['date', 'time', 'location', 'team_a', 'team_b', 'week']
        if not all(field in request.form for field in required_fields):
            return jsonify({
                'success': False,
                'message': 'Missing required fields'
            }), 400

        try:
            match_date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
            match_time = datetime.strptime(request.form['time'], '%H:%M').time()
        except ValueError as e:
            return jsonify({
                'success': False,
                'message': f'Invalid date or time format: {str(e)}'
            }), 400

        location = request.form['location']
        team_a_id = request.form['team_a']
        team_b_id = request.form['team_b']
        week = request.form['week']

        schedule = session.query(Schedule).get(match_id)
        if not schedule:
            return jsonify({
                'success': False,
                'message': 'Schedule not found'
            }), 404

        # Update Schedule record
        schedule.date = match_date
        schedule.time = match_time
        schedule.location = location
        schedule.team_id = team_a_id
        schedule.opponent = team_b_id
        schedule.week = week

        objects_to_process = [schedule]

        # Update or create Match record
        match = session.query(Match).filter_by(schedule_id=match_id).first()
        if not match:
            match = Match(
                schedule_id=match_id,
                date=match_date,
                time=match_time,
                location=location,
                home_team_id=team_a_id,
                away_team_id=team_b_id
            )
            session.add(match)
        else:
            match.date = match_date
            match.time = match_time
            match.location = location
            match.home_team_id = team_a_id
            match.away_team_id = team_b_id

        objects_to_process.append(match)

        # Update paired schedule if it exists
        paired_schedule = session.query(Schedule).filter_by(
            team_id=team_b_id,
            opponent=team_a_id,
            week=week
        ).first()

        if paired_schedule:
            paired_schedule.date = match_date
            paired_schedule.time = match_time
            paired_schedule.location = location
            objects_to_process.append(paired_schedule)

            paired_match = session.query(Match).filter_by(schedule_id=paired_schedule.id).first()
            if paired_match:
                paired_match.date = match_date
                paired_match.time = match_time
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
def delete_match(match_id):
    session = g.db_session
    """Delete match and related records."""
    try:
        logger.info(f"Attempting to delete match {match_id}")

        schedule = session.query(Schedule).get(match_id)
        if not schedule:
            abort(404)

        objects_to_delete = []

        match = session.query(Match).filter_by(schedule_id=match_id).first()
        if match:
            scheduled_messages = session.query(ScheduledMessage).filter_by(match_id=match.id).all()
            for msg in scheduled_messages:
                msg.deleted = True
                objects_to_delete.append(msg)

            match.deleted = True
            objects_to_delete.append(match)

        # Get paired records
        paired_schedule = session.query(Schedule).filter_by(
            team_id=schedule.opponent,
            opponent=schedule.team_id,
            week=schedule.week
        ).first()

        if paired_schedule:
            paired_match = session.query(Match).filter_by(schedule_id=paired_schedule.id).first()
            if paired_match:
                paired_messages = session.query(ScheduledMessage).filter_by(match_id=paired_match.id).all()
                for msg in paired_messages:
                    msg.deleted = True
                    objects_to_delete.append(msg)

                paired_match.deleted = True
                objects_to_delete.append(paired_match)

            paired_schedule.deleted = True
            objects_to_delete.append(paired_schedule)

        schedule.deleted = True
        objects_to_delete.append(schedule)

        logger.info(f"Successfully marked match {match_id} and related records for deletion")

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
def delete_week(league_type, season_id, week_number):
    session = g.db_session
    try:
        session.query(Schedule).filter_by(week=str(week_number), season_id=season_id).delete()
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
def fetch_schedule():
    """Fetch schedule with team filtering capability."""
    session = g.db_session
    team_id = request.args.get('team_id')
    league_id = request.args.get('league_id')

    query = session.query(Schedule)

    if team_id:
        query = query.filter((Schedule.team_id == team_id) | (Schedule.opponent == team_id))
    if league_id:
        query = query.join(Team).filter(Team.league_id == league_id)

    schedules = query.all()
    return jsonify([s.to_dict() for s in schedules])

@schedule_bp.route('/add_match', methods=['POST'])
@role_required(['Pub League Admin', 'Global Admin'])
def add_match():
    """Add a new match and its related records."""
    session = g.db_session
    try:
        required_fields = ['week', 'date', 'time', 'location', 'team_a', 'team_b']
        if not all(field in request.form for field in required_fields):
            return jsonify({
                'success': False,
                'message': 'Missing required fields'
            }), 400

        try:
            match_date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
            match_time = datetime.strptime(request.form['time'], '%H:%M').time()
        except ValueError as e:
            return jsonify({
                'success': False,
                'message': f'Invalid date or time format: {str(e)}'
            }), 400

        week = request.form['week']
        location = request.form['location']
        team_a_id = request.form['team_a']
        team_b_id = request.form['team_b']

        schedule_a = Schedule(
            week=week,
            date=match_date,
            time=match_time,
            location=location,
            team_id=team_a_id,
            opponent=team_b_id
        )

        schedule_b = Schedule(
            week=week,
            date=match_date,
            time=match_time,
            location=location,
            team_id=team_b_id,
            opponent=team_a_id
        )

        match = Match(
            date=match_date,
            time=match_time,
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
