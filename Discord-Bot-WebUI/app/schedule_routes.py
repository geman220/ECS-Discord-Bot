# app/schedule_routes.py

"""
Schedule Routes Module

This module provides routes and helper classes for managing schedules,
matches, and related operations in the Pub League and ECS FC. It includes
endpoints for viewing, editing, deleting, and creating matches as well as a
bulk scheduling wizard.
"""

# Standard library imports
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Any
import logging

# Third-party imports
from flask import (
    Blueprint, render_template, redirect, url_for, request, g, jsonify, abort
)
from app.alert_helpers import show_success, show_error, show_warning, show_info
from flask_login import login_required

# Local application imports
from app.decorators import role_required
from app.models import Season, League, Team, Schedule, Match, ScheduledMessage

logger = logging.getLogger(__name__)

# Blueprint definition
schedule_bp = Blueprint('schedule', __name__)


@dataclass
class TimeSlot:
    start_time: datetime
    field: str
    team_a_id: Optional[int] = None
    team_b_id: Optional[int] = None


class ScheduleManager:
    def __init__(self, session):
        self.session = session

    def get_season(self, season_id: int) -> Optional[Season]:
        """Retrieve a Season by its ID."""
        return self.session.query(Season).get(season_id)

    def get_league(self, season_id: int, league_name: str) -> Optional[League]:
        """Retrieve a League by season ID and league name."""
        return self.session.query(League).filter_by(
            name=league_name,
            season_id=season_id
        ).first()

    def get_teams_by_league(self, league_id: int) -> List[Dict]:
        """
        Return all teams for a given league with their id and name.
        
        Returns:
            List[Dict]: A list of dictionaries representing teams.
        """
        teams = self.session.query(Team).filter_by(league_id=league_id).all()
        return [{'id': t.id, 'name': t.name} for t in teams]

    def get_schedule(
        self, league_id: Optional[int] = None, team_id: Optional[int] = None
    ) -> List[Schedule]:
        """
        Return schedule entries. Optionally filter by league_id or team_id.
        """
        query = self.session.query(Schedule)

        if league_id:
            query = query.join(Schedule.team).filter(Team.league_id == league_id)

        if team_id:
            query = query.filter(
                (Schedule.team_id == team_id) | (Schedule.opponent == team_id)
            )

        return query.all()

    def format_week_schedule(self, schedules: List[Schedule]) -> Dict:
        """
        Transform a list of schedules into a dictionary organized by week.

        Returns:
            Dict: A mapping of week numbers to a dictionary containing the date
                  and a list of match details, sorted numerically by week.
        """
        formatted = {}
        displayed = set()

        for schedule in schedules:
            if not schedule.team:
                continue

            opponent = self.session.query(Team).get(schedule.opponent)
            if not opponent:
                continue

            match_key = (schedule.week, schedule.team.name, opponent.name)
            if match_key in displayed:
                continue

            # Add both orderings to avoid duplicates
            displayed.add(match_key)
            displayed.add((schedule.week, opponent.name, schedule.team.name))

            if schedule.week not in formatted:
                formatted[schedule.week] = {
                    'date': schedule.date.strftime('%Y-%m-%d'),
                    'matches': []
                }

            formatted[schedule.week]['matches'].append({
                'id': schedule.id,
                'team_a': schedule.team.name,
                'team_a_id': schedule.team.id,
                'team_b': opponent.name,
                'team_b_id': opponent.id,
                'time': schedule.time.strftime('%I:%M %p'),
                'location': schedule.location
            })

        # Sort weeks numerically before returning
        try:
            sorted_formatted = dict(sorted(formatted.items(), key=lambda x: int(x[0])))
        except (ValueError, TypeError):
            # If conversion to int fails, return unsorted
            sorted_formatted = formatted

        return sorted_formatted

    def update_match(self, match_id: int, data: Dict) -> Tuple[List[Any], Dict]:
        """
        Edit an existing schedule entry and its paired schedule and match record.

        Args:
            match_id (int): The ID of the schedule to update.
            data (Dict): A dictionary with new match data.

        Returns:
            Tuple: A tuple containing a list of updated objects and a response dict.
        """
        schedule = self.session.query(Schedule).get(match_id)
        if not schedule:
            return [], {'success': False, 'message': 'Schedule not found'}

        try:
            match_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            match_time = datetime.strptime(data['time'], '%H:%M').time()
        except ValueError as e:
            return [], {'success': False, 'message': f'Invalid date/time: {str(e)}'}

        objects_to_update = []

        # Store original values before updating for paired lookup
        original_team_id = schedule.team_id
        original_opponent = schedule.opponent
        original_week = schedule.week

        schedule.date = match_date
        schedule.time = match_time
        schedule.location = data['location']
        schedule.team_id = data['team_a']
        schedule.opponent = data['team_b']
        schedule.week = data['week']
        objects_to_update.append(schedule)

        match = self.session.query(Match).filter_by(schedule_id=match_id).first()
        if not match:
            match = Match(
                schedule_id=match_id,
                date=match_date,
                time=match_time,
                location=data['location'],
                home_team_id=data['team_a'],
                away_team_id=data['team_b']
            )
            self.session.add(match)
            objects_to_update.append(match)
        else:
            match.date = match_date
            match.time = match_time
            match.location = data['location']
            match.home_team_id = data['team_a']
            match.away_team_id = data['team_b']
            objects_to_update.append(match)

        # Use ORIGINAL values to find the paired schedule
        paired = self.session.query(Schedule).filter_by(
            team_id=original_opponent,
            opponent=original_team_id,
            week=original_week
        ).first()

        if paired:
            paired.date = match_date
            paired.time = match_time
            paired.location = data['location']
            paired.week = data['week']
            # CRITICAL: Update the paired entry's teams to match (swapped)
            paired.team_id = data['team_b']
            paired.opponent = data['team_a']
            objects_to_update.append(paired)

            paired_match = self.session.query(Match).filter_by(schedule_id=paired.id).first()
            if paired_match:
                paired_match.date = match_date
                paired_match.time = match_time
                paired_match.location = data['location']
                # Also update the match teams (swapped from main match)
                paired_match.home_team_id = data['team_b']
                paired_match.away_team_id = data['team_a']
                objects_to_update.append(paired_match)

        return objects_to_update, {'success': True, 'message': 'Match updated'}

    def delete_match(self, match_id: int) -> Tuple[List[Any], Dict]:
        """
        Delete a match, its schedule row, and the paired schedule and match.

        Args:
            match_id (int): The ID of the main schedule row to delete.

        Returns:
            Tuple: A tuple of objects to delete and a response dict.
        """
        schedule = self.session.query(Schedule).get(match_id)
        if not schedule:
            return [], {'success': False, 'message': 'Schedule not found'}

        objects_to_delete = [schedule]

        match = self.session.query(Match).filter_by(schedule_id=match_id).first()
        if match:
            objects_to_delete.append(match)
            messages = self.session.query(ScheduledMessage).filter_by(match_id=match.id).all()
            objects_to_delete.extend(messages)

        paired = self.session.query(Schedule).filter_by(
            team_id=schedule.opponent,
            opponent=schedule.team_id,
            week=schedule.week
        ).first()
        if paired:
            objects_to_delete.append(paired)
            paired_match = self.session.query(Match).filter_by(schedule_id=paired.id).first()
            if paired_match:
                objects_to_delete.append(paired_match)
                paired_messages = self.session.query(ScheduledMessage).filter_by(match_id=paired_match.id).all()
                objects_to_delete.extend(paired_messages)

        return objects_to_delete, {'success': True, 'message': 'Match deleted'}

    def create_match(self, data: Dict) -> Tuple[List[Any], Dict]:
        """
        Create two schedule rows (for both teams) and one match record.

        Args:
            data (Dict): A dictionary containing match details.

        Returns:
            Tuple: A tuple containing a list of created objects and a response dict.
        """
        try:
            match_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            match_time = datetime.strptime(data['time'], '%H:%M').time()
        except ValueError as e:
            return [], {'success': False, 'message': f'Invalid date/time: {str(e)}'}

        objects_to_create = []

        schedule_a = Schedule(
            week=data['week'],
            date=match_date,
            time=match_time,
            location=data['location'],
            team_id=data['team_a'],
            opponent=data['team_b']
        )
        self.session.add(schedule_a)
        objects_to_create.append(schedule_a)

        schedule_b = Schedule(
            week=data['week'],
            date=match_date,
            time=match_time,
            location=data['location'],
            team_id=data['team_b'],
            opponent=data['team_a']
        )
        self.session.add(schedule_b)
        objects_to_create.append(schedule_b)

        match = Match(
            date=match_date,
            time=match_time,
            location=data['location'],
            home_team_id=data['team_a'],
            away_team_id=data['team_b'],
            schedule=schedule_a,
            # Add special week information if provided
            week_type=data.get('week_type', 'REGULAR'),
            is_special_week=data.get('is_special_week', False),
            is_playoff_game=data.get('is_playoff_game', False),
            playoff_round=data.get('playoff_round', None)
        )
        self.session.add(match)
        objects_to_create.append(match)

        return objects_to_create, {'success': True, 'message': 'Match created'}


######################################################################
# PRIMARY PUB LEAGUE SCHEDULE ROUTE
######################################################################
@schedule_bp.route('/<int:season_id>/schedule', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_publeague_schedule(season_id):
    """
    Render the main schedule management UI for Pub League.

    URL example: /publeague/schedules/16/schedule
    """
    manager = ScheduleManager(g.db_session)
    season = manager.get_season(season_id)
    if not season:
        abort(404)

    leagues = manager.session.query(League).filter_by(season_id=season_id).all()
    schedule_data = {}

    for league in leagues:
        schedules = manager.get_schedule(league_id=league.id)
        schedule_data[league.name] = manager.format_week_schedule(schedules)

    return render_template(
        'manage_publeague_schedule.html',
        season=season,
        leagues=[{'id': league.id, 'name': league.name, 'teams': manager.get_teams_by_league(league.id)}
                 for league in leagues],
        schedule=schedule_data
    )


######################################################################
# EDIT MATCH
######################################################################
@schedule_bp.route('/edit_match/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_match(match_id):
    """
    Edit an existing match and its schedule rows.
    
    Endpoint: POST /publeague/schedules/edit_match/<match_id>
    """
    manager = ScheduleManager(g.db_session)
    try:
        objects, response = manager.update_match(match_id, request.form)
        if objects:
            g.db_session.commit()
        return jsonify(response)
    except Exception as e:
        logger.error(f"Error editing match {match_id}: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


######################################################################
# DELETE MATCH
######################################################################
@schedule_bp.route('/delete_match/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_match(match_id):
    """
    Delete a match, its schedule row, and the paired row.
    
    Endpoint: POST /publeague/schedules/delete_match/<match_id>
    """
    manager = ScheduleManager(g.db_session)
    try:
        objects_to_delete, response = manager.delete_match(match_id)
        if objects_to_delete:
            for obj in objects_to_delete:
                g.db_session.delete(obj)
            g.db_session.commit()
        return jsonify(response)
    except Exception as e:
        logger.error(f"Error deleting match {match_id}: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


######################################################################
# QUICK ADD MATCH
######################################################################
@schedule_bp.route('/add_match', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def add_match():
    """
    Quick-add a single match to the schedule.
    
    Endpoint: POST /publeague/schedules/add_match
    """
    manager = ScheduleManager(g.db_session)
    try:
        objects, response = manager.create_match(request.form)
        if objects:
            g.db_session.commit()
        return jsonify(response)
    except Exception as e:
        logger.error(f"Error adding match: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


######################################################################
# FETCH SCHEDULE (AJAX)
######################################################################
@schedule_bp.route('/fetch_schedule', methods=['GET'])
def fetch_schedule():
    """
    Return a JSON list of schedule objects.
    
    Endpoint: GET /publeague/schedules/fetch_schedule?league_id=xx&team_id=yy
    """
    manager = ScheduleManager(g.db_session)
    schedules = manager.get_schedule(
        league_id=request.args.get('league_id'),
        team_id=request.args.get('team_id')
    )
    return jsonify([s.to_dict() for s in schedules])


######################################################################
# ECS FC MANAGE SCHEDULE
######################################################################
@schedule_bp.route('/ecsfc/<int:season_id>/schedule', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_ecsfc_schedule(season_id):
    """
    Render the ECS FC schedule management UI.
    
    Endpoint: /publeague/schedules/ecsfc/<season_id>/schedule
    """
    manager = ScheduleManager(g.db_session)
    season = manager.get_season(season_id)
    if not season:
        abort(404)

    leagues = manager.session.query(League).filter_by(season_id=season_id).all()
    schedule_data = {}
    for league in leagues:
        schedules = manager.get_schedule(league_id=league.id)
        schedule_data[league.name] = manager.format_week_schedule(schedules)

    return render_template(
        'manage_ecsfc_schedule.html',
        season=season,
        leagues=[{'id': league.id, 'name': league.name, 'teams': manager.get_teams_by_league(league.id)}
                 for league in leagues],
        schedule=schedule_data
    )


######################################################################
# BULK SCHEDULING WIZARD
######################################################################
@schedule_bp.route('/<int:season_id>/schedule_wizard', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def schedule_wizard(season_id):
    """
    Bulk Scheduling Wizard endpoint.
    
    GET: Show the initial form.
    POST: Process wizard steps:
         - Step 1: Create placeholders (or special FUN/BYE day).
         - Step 2: Finalize placeholders into matches.
    """
    manager = ScheduleManager(g.db_session)
    season = manager.get_season(season_id)
    if not season:
        abort(404)

    league_id = request.args.get('league_id', type=int)
    if league_id:
        leagues = manager.session.query(League).filter(
            League.season_id == season_id,
            League.id == league_id
        ).all()
    else:
        leagues = manager.session.query(League).filter_by(season_id=season_id).all()

    placeholders = None

    if request.method == 'POST':
        wizard_step = request.form.get('wizard_step')
        if wizard_step == 'step1':
            start_date_str = request.form['start_date']
            num_weeks = int(request.form['num_weeks'])
            timeslots_str = request.form['timeslots']

            fun_week = request.form.get('fun_week')
            bye_week = request.form.get('bye_week')

            if fun_week or bye_week:
                special_team_name = "FUN WEEK" if fun_week else "BYE"
                special_team = manager.session.query(Team).filter(
                    Team.name == special_team_name
                ).first()
                if not special_team:
                    show_error(f"Error: No special team named {special_team_name} found in DB")
                    return redirect(url_for('schedule.schedule_wizard', season_id=season.id))

                placeholders = []
                off_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()

                for lg in leagues:
                    real_teams = manager.session.query(Team).filter(
                        Team.league_id == lg.id
                    ).all()

                    for t in real_teams:
                        if t.id == special_team.id:
                            continue
                        placeholders.append({
                            'week': 1,
                            'date': off_date.strftime("%Y-%m-%d"),
                            'time': "00:00",
                            'location': "OFF DAY",
                            'team_a': t.id,
                            'team_b': special_team.id
                        })

                for ph in placeholders:
                    data = {
                        'week': str(ph['week']),
                        'date': ph['date'],
                        'time': ph['time'],
                        'team_a': ph['team_a'],
                        'team_b': ph['team_b'],
                        'location': ph['location']
                    }
                    objects, response = manager.create_match(data)
                    if objects:
                        manager.session.commit()

                show_success(f"{special_team_name} placeholders created for {len(placeholders)} matches!")
                return redirect(url_for('schedule.manage_publeague_schedule', season_id=season.id))

            timeslot_list = []
            for slot_str in timeslots_str.split(','):
                slot_str = slot_str.strip()
                if not slot_str:
                    continue
                parts = slot_str.split()
                slot_time = parts[0]
                slot_field = ' '.join(parts[1:]) if len(parts) > 1 else "Unknown"
                timeslot_list.append((slot_time, slot_field))

            placeholders = generate_placeholders(start_date_str, num_weeks, timeslot_list)
            return render_template(
                'schedule_wizard.html',
                season=season,
                leagues=leagues,
                placeholders=placeholders
            )

        elif wizard_step == 'step2':
            create_schedule_from_placeholders(request.form, manager, league_id=league_id)
            show_success("Matches created successfully!")
            return redirect(url_for('schedule.manage_publeague_schedule', season_id=season.id))

    return render_template(
        'schedule_wizard.html',
        season=season,
        leagues=leagues,
        placeholders=placeholders
    )


######################################################################
# ADD SINGLE WEEK
######################################################################
@schedule_bp.route('/add_single_week', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def add_single_week():
    """
    Add match entries for a single week based on provided times, fields, and team selections.
    This updated version uses logic similar to the bulk scheduling wizard.
    """
    manager = ScheduleManager(g.db_session)

    league_id = request.form.get('league_id', type=int)
    if not league_id:
        return jsonify({'success': False, 'message': 'No league specified'}), 400

    week_date_str = request.form.get('week_date')
    if not week_date_str:
        return jsonify({'success': False, 'message': 'No date provided'}), 400

    fun_week = request.form.get('fun_week')
    bye_week = request.form.get('bye_week')

    times = request.form.getlist('times[]')
    fields = request.form.getlist('fields[]')
    team_a_list = request.form.getlist('team_a[]')
    team_b_list = request.form.getlist('team_b[]')

    n = len(times)
    if not n or n != len(fields) or n != len(team_a_list) or n != len(team_b_list):
        return jsonify({'success': False, 'message': 'Timeslots mismatch'}), 400

    try:
        week_date = datetime.strptime(week_date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format'}), 400

    # If FUN/BYE week is checked, handle it using the special team logic.
    if fun_week or bye_week:
        special_team_name = "FUN WEEK" if fun_week else "BYE"
        special_team = manager.session.query(Team).filter_by(name=special_team_name).first()
        if not special_team:
            return jsonify({
                'success': False,
                'message': f"No special team named {special_team_name} found"
            }), 400

        placeholders = []
        real_teams = manager.session.query(Team).filter_by(league_id=league_id).all()
        for t in real_teams:
            if t.id == special_team.id:
                continue
            placeholders.append({
                'date': week_date_str,
                'team_a': t.id,
                'team_b': special_team.id,
                'time': "00:00",
                'location': "OFF DAY"
            })
        create_single_day_placeholders(placeholders, manager, league_id)
        return jsonify({
            'success': True,
            'message': f"{special_team_name} single week created."
        })

    # Compute the new week number using logic similar to bulk scheduling.
    existing = manager.get_schedule(league_id=league_id)
    existing_date_to_week = {}
    for sch in existing:
        d = sch.date
        try:
            w = int(sch.week)
        except ValueError:
            w = 1
        if d not in existing_date_to_week:
            existing_date_to_week[d] = w
        else:
            existing_date_to_week[d] = min(existing_date_to_week[d], w)

    if week_date not in existing_date_to_week:
        existing_date_to_week[week_date] = -1

    all_dates_sorted = sorted(existing_date_to_week.keys())
    date_to_week = {}
    w_num = 1
    for d in all_dates_sorted:
        date_to_week[d] = w_num
        w_num += 1

    the_week = date_to_week[week_date]

    created_count = 0
    # Collect objects to commit at once.
    objects_to_commit = []
    for i in range(n):
        t_str = times[i]
        field_str = fields[i]
        a_id = team_a_list[i]
        b_id = team_b_list[i]

        if not a_id or not b_id:
            continue

        try:
            match_time = datetime.strptime(t_str, '%H:%M').time()
        except ValueError:
            continue

        data = {
            'week': the_week,
            'date': week_date_str,
            'time': t_str,
            'team_a': a_id,
            'team_b': b_id,
            'location': field_str
        }
        objects, resp = manager.create_match(data)
        if objects:
            objects_to_commit.extend(objects)
            created_count += 1

    if objects_to_commit:
        try:
            g.db_session.commit()
        except Exception as e:
            g.db_session.rollback()
            return jsonify({'success': False, 'message': f'Commit failed: {str(e)}'}), 500

    return jsonify({
        'success': True,
        'message': f"Created {created_count} matches for {week_date_str}."
    })


def create_single_day_placeholders(placeholders, manager, league_id):
    """
    Merge a list of placeholder dictionaries for a single date into the schedule.
    
    Assigns the new date to the next available week number.
    """
    date_str = placeholders[0]['date']
    dt = datetime.strptime(date_str, "%Y-%m-%d").date()

    existing = manager.get_schedule(league_id=league_id)
    existing_date_to_week = {}
    for sch in existing:
        d = sch.date
        try:
            w = int(sch.week)
        except ValueError:
            w = 1
        if d not in existing_date_to_week:
            existing_date_to_week[d] = w
        else:
            existing_date_to_week[d] = min(existing_date_to_week[d], w)

    if dt not in existing_date_to_week:
        existing_date_to_week[dt] = -1

    all_dates_sorted = sorted(existing_date_to_week.keys())
    date_to_week = {}
    w_num = 1
    for d in all_dates_sorted:
        date_to_week[d] = w_num
        w_num += 1

    the_week = date_to_week[dt]
    for ph in placeholders:
        team_a_id = ph['team_a'] if ph['team_a'] else your_placeholder_team_id_or_0()
        team_b_id = ph['team_b'] if ph['team_b'] else your_placeholder_team_id_or_0()

        objects, response = manager.create_match({
            'week': the_week,
            'date': ph['date'],
            'time': ph['time'],
            'team_a': team_a_id,
            'team_b': team_b_id,
            'location': ph['location']
        })
        if objects:
            manager.session.commit()


def your_placeholder_team_id_or_0():
    """
    Return a placeholder team ID if real teams are not assigned.
    
    You may modify this to return a special "PLACEHOLDER TEAM" ID or 0.
    """
    return 0


def generate_placeholders(start_date_str: str, num_weeks: int, timeslot_list: list) -> list:
    """
    Generate a list of placeholders for multiple weeks based on a start date and timeslots.
    
    Args:
        start_date_str (str): The start date in "YYYY-MM-DD" format.
        num_weeks (int): The number of weeks for which to generate placeholders.
        timeslot_list (list): A list of tuples (slot_time, slot_field).

    Returns:
        list: A list of placeholder dictionaries.
    """
    placeholders = []
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()

    for week_idx in range(num_weeks):
        for (slot_time, slot_field) in timeslot_list:
            current_date = start_date + timedelta(days=7 * week_idx)
            placeholders.append({
                'week': week_idx + 1,
                'date': current_date.strftime("%Y-%m-%d"),
                'time': slot_time,
                'location': slot_field,
                'team_a': None,
                'team_b': None
            })
    return placeholders


def create_schedule_from_placeholders(form, manager, league_id=None):
    """
    Merge placeholder data from the wizard into the schedule.

    Reads placeholders from the submitted form, merges them with existing schedule data,
    and assigns consistent week numbers across all dates.
    """
    rows = []
    index_list = []
    for key in form.keys():
        if key.startswith("team_a_"):
            idx_str = key.split("_")[-1]
            index_list.append(int(idx_str))
    index_list.sort()

    for idx in index_list:
        date_str = form.get(f"date_{idx}")
        time_str = form.get(f"time_{idx}")
        loc_str  = form.get(f"location_{idx}")
        team_a_id = form.get(f"team_a_{idx}")
        team_b_id = form.get(f"team_b_{idx}")

        if not team_a_id or not team_b_id:
            continue

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        rows.append({
            'parsed_date': dt,
            'date_str': date_str,
            'time_str': time_str,
            'location': loc_str,
            'team_a': team_a_id,
            'team_b': team_b_id
        })

    if not rows:
        return

    existing_schedules = []
    if league_id:
        existing_schedules = manager.get_schedule(league_id=league_id)

    existing_date_to_week = {}
    for sch in existing_schedules:
        d = sch.date
        try:
            w = int(sch.week)
        except ValueError:
            w = 1
        if d not in existing_date_to_week:
            existing_date_to_week[d] = w
        else:
            existing_date_to_week[d] = min(existing_date_to_week[d], w)

    for r in rows:
        if r['parsed_date'] not in existing_date_to_week:
            existing_date_to_week[r['parsed_date']] = -1

    all_dates_sorted = sorted(existing_date_to_week.keys())
    date_to_week = {}
    current_week_num = 1
    for d in all_dates_sorted:
        date_to_week[d] = current_week_num
        current_week_num += 1

    for r in rows:
        the_week = date_to_week[r['parsed_date']]
        data = {
            'week': the_week,
            'date': r['date_str'],
            'time': r['time_str'],
            'team_a': r['team_a'],
            'team_b': r['team_b'],
            'location': r['location']
        }
        objects, response = manager.create_match(data)
        if objects:
            manager.session.commit()