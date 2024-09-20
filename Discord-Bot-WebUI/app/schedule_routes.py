from flask import Blueprint, render_template, redirect, url_for, flash, request, g
from flask_login import login_required
from app import db
from app.models import Season, League, Team, Schedule
from app.decorators import role_required
from sqlalchemy.orm import joinedload
from sqlalchemy import cast, Integer

schedule_bp = Blueprint('schedule', __name__)

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
            'team_a': match.team.name,
            'team_b': opponent_team.name,
            'time': formatted_time,
            'location': match.location,
            'match_id': match.id
        })

    return schedule

# Helper function to handle match addition
def handle_add_match(season_id, league_name, week):
    league = League.query.filter_by(name=league_name, season_id=season_id).first()
    if league:
        team_a = Team.query.filter_by(name=request.form.get('teamA'), league_id=league.id).first()
        team_b = Team.query.filter_by(name=request.form.get('teamB'), league_id=league.id).first()

        if team_a and team_b:
            new_match = Schedule(
                week=week,
                date=request.form.get('date'),
                time=request.form.get('time'),
                location=request.form.get('location'),
                team_id=team_a.id,
                opponent=team_b.id
            )
            db.session.add(new_match)
            db.session.commit()
            flash(f'Match {team_a.name} vs {team_b.name} added successfully.', 'success')
        else:
            flash('One or both teams not found.', 'danger')
    else:
        flash('League not found.', 'danger')

# Helper function to handle week deletion
def handle_delete_week(season_id, week):
    Schedule.query.filter_by(week=str(week)).delete()
    db.session.commit()
    flash(f'Week {week} and all its matches have been deleted.', 'success')

# Manage Pub League Schedule
@schedule_bp.route('/publeague/<int:season_id>/schedule', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
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
            matches = Schedule.query.filter_by(team_id=team.id).order_by(Schedule.week.cast(Integer).asc(), Schedule.time.asc()).all()
            league_schedule.extend(matches)
        schedule_data[league.name] = format_match_schedule(league_schedule)

    return render_template('manage_publeague_schedule.html', season=season, leagues=serialized_leagues, schedule=schedule_data)

# Manage ECS FC Schedule
@schedule_bp.route('/ecsfc/<int:season_id>/schedule', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
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
            matches = Schedule.query.filter_by(team_id=team.id).order_by(Schedule.week.cast(Integer).asc(), Schedule.time.asc()).all()
            league_schedule.extend(matches)
        schedule_data[league.name] = format_match_schedule(league_schedule)

    return render_template('manage_ecsfc_schedule.html', season=season, leagues=leagues_data, schedule=schedule_data)

# Bulk Create Matches (Pub League)
@schedule_bp.route('/publeague/bulk_create_matches/<int:season_id>/<string:league_name>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def bulk_create_publeague_matches(season_id, league_name):
    season = Season.query.get_or_404(season_id)
    league = League.query.filter_by(name=league_name, season_id=season_id).first_or_404()

    total_weeks = int(request.form.get('total_weeks', 0))
    matches_per_week = int(request.form.get('matches_per_week', 0))

    if total_weeks == 0 or matches_per_week == 0:
        flash("Total Weeks and Matches Per Week are required fields.", 'danger')
        return redirect(url_for('schedule.manage_publeague_schedule', season_id=season_id))

    fun_week = request.form.get('fun_week')
    tst_week = request.form.get('tst_week')

    for week in range(1, total_weeks + 1):
        if str(week) in [fun_week, tst_week]:
            continue  # Skip fun and TST weeks

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
                db.session.add(Schedule(
                    week=str(week),
                    date=week_date,
                    time=time,
                    opponent=team_b_id,
                    location=location,
                    team_id=team_a_id
                ))
                db.session.add(Schedule(
                    week=str(week),
                    date=week_date,
                    time=time,
                    opponent=team_a_id,
                    location=location,
                    team_id=team_b_id
                ))

    db.session.commit()
    flash(f'Bulk matches created for {league_name} league', 'success')
    return redirect(url_for('schedule.manage_publeague_schedule', season_id=season_id))

# Bulk Create Matches (ECS FC)
@schedule_bp.route('/ecsfc/bulk_create_matches/<int:season_id>/<string:league_name>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def bulk_create_ecsfc_matches(season_id, league_name):
    season = Season.query.get_or_404(season_id)
    league = League.query.filter_by(name=league_name, season_id=season_id).first_or_404()

    total_weeks = int(request.form.get('total_weeks', 0))
    matches_per_week = int(request.form.get('matches_per_week', 0))

    if total_weeks == 0 or matches_per_week == 0:
        flash("Total Weeks and Matches Per Week are required fields.", 'danger')
        return redirect(url_for('schedule.manage_ecsfc_schedule', season_id=season_id))

    fun_week = request.form.get('fun_week')
    tst_week = request.form.get('tst_week')

    for week in range(1, total_weeks + 1):
        if str(week) in [fun_week, tst_week]:
            continue  # Skip fun and TST weeks

        week_date = request.form.get(f'date_week{week}')
        if not week_date:
            flash(f"Date for Week {week} is missing.", 'danger')
            return redirect(url_for('schedule.manage_ecsfc_schedule', season_id=season_id))

        for match_num in range(1, matches_per_week + 1):
            team_a_id = request.form.get(f'teamA_week{week}_match{match_num}')
            team_b_id = request.form.get(f'teamB_week{week}_match{match_num}')
            time = request.form.get(f'time_week{week}_match{match_num}')
            location = request.form.get(f'location_week{week}_match{match_num}')

            if team_a_id and team_b_id and time and location:
                db.session.add(Schedule(
                    week=str(week),
                    date=week_date,
                    time=time,
                    opponent=team_b_id,
                    location=location,
                    team_id=team_a_id
                ))
                db.session.add(Schedule(
                    week=str(week),
                    date=week_date,
                    time=time,
                    opponent=team_a_id,
                    location=location,
                    team_id=team_b_id
                ))

    db.session.commit()
    flash(f'Bulk matches created for {league_name} league', 'success')
    return redirect(url_for('schedule.manage_ecsfc_schedule', season_id=season_id))

# Edit Match
@schedule_bp.route('/edit_match/<int:match_id>', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_match(match_id):
    match = Schedule.query.options(joinedload(Schedule.team).joinedload(Team.league)).get_or_404(match_id)
    league = match.team.league  # Get the league for the match
    teams = Team.query.filter_by(league_id=league.id).all()  # Get all teams in the same league

    if request.method == 'POST':
        match.date = request.form.get('date')
        match.time = request.form.get('time')
        match.location = request.form.get('location')
        match.opponent = int(request.form.get('teamB'))
        db.session.commit()
        flash('Match updated successfully!', 'success')
        return redirect(url_for('schedule.manage_publeague_schedule', season_id=league.season_id))

    print(teams)  # Add this line for debugging
    return render_template('edit_match.html', match=match, teams=teams, league_name=match.team.league.name)

# Delete Match
@schedule_bp.route('/delete_match/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_match(match_id):
    match = Schedule.query.get_or_404(match_id)
    season_id = match.team.league.season_id

    # Find the corresponding match pair
    paired_match = Schedule.query.filter(
        Schedule.team_id == match.opponent, 
        cast(Schedule.opponent, Integer) == match.team_id,
        Schedule.week == match.week,
        Schedule.date == match.date,
        Schedule.time == match.time,
        Schedule.location == match.location
    ).first()

    db.session.delete(match)
    if paired_match:
        db.session.delete(paired_match)
    
    db.session.commit()

    flash('Both matches deleted successfully!', 'success')
    return redirect(url_for('schedule.manage_publeague_schedule', season_id=season_id))

# Delete a specific week
@schedule_bp.route('/<string:league_type>/<int:season_id>/delete_week/<int:week_number>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_week(league_type, season_id, week_number):
    Schedule.query.filter_by(week=str(week_number), season_id=season_id).delete()
    db.session.commit()
    flash(f'Week {week_number} and all its matches have been deleted.', 'success')
    if league_type == "publeague":
        return redirect(url_for('publeague.schedule.manage_publeague_schedule', season_id=season_id))
    elif league_type == "ecsfc":
        return redirect(url_for('publeague.schedule.manage_ecsfc_schedule', season_id=season_id))
