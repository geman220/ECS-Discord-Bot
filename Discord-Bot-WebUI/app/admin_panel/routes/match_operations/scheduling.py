# app/admin_panel/routes/match_operations/scheduling.py

"""
Match Scheduling Routes

Routes for match scheduling:
- Schedule matches page
- Create matches
- Auto-schedule matches
- Update match times
"""

import logging
import itertools
from datetime import datetime, timedelta

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations/schedule')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def schedule_matches():
    """Schedule new matches for Pub League (Premier, Classic, ECS FC)."""
    try:
        from app.models import Team, League, Season, Match, Schedule

        # Log the access to match scheduling
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_match_scheduling',
            resource_type='match_operations',
            resource_id='schedule',
            new_value='Accessed match scheduling interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Get current Pub League season
        current_season = db.session.query(Season).filter_by(is_current=True, league_type="Pub League").first()
        if not current_season:
            current_season = db.session.query(Season).filter_by(is_current=True).first()

        # Get filter parameter
        league_filter = request.args.get('league_id', type=int)

        # Get all leagues for the current season (Premier, Classic, ECS FC)
        # Get leagues for dropdowns
        if current_season:
            leagues = db.session.query(League).filter_by(season_id=current_season.id).order_by(League.name).all()
        else:
            leagues = db.session.query(League).order_by(League.name).all()

        # Get teams filtered by season and optionally by league
        if current_season:
            teams_query = db.session.query(Team).join(League).filter(League.season_id == current_season.id)
            if league_filter:
                teams_query = teams_query.filter(Team.league_id == league_filter)
            teams = teams_query.order_by(Team.name).all()
        else:
            teams = db.session.query(Team).order_by(Team.name).all()

        # Get unscheduled matches (from current season teams)
        if current_season:
            league_ids = [l.id for l in leagues]
            team_ids = [t.id for t in db.session.query(Team).filter(Team.league_id.in_(league_ids)).all()]
            unscheduled_matches = db.session.query(Match).filter(
                or_(
                    Match.home_team_id.in_(team_ids),
                    Match.away_team_id.in_(team_ids)
                ),
                or_(
                    Match.time.is_(None),
                    Match.date.is_(None)
                )
            ).options(
                joinedload(Match.home_team),
                joinedload(Match.away_team)
            ).limit(50).all()

        else:
            from sqlalchemy import or_
            unscheduled_matches = db.session.query(Match).filter(
                or_(
                    Match.time.is_(None),
                    Match.date.is_(None)
                )
            ).limit(50).all()

        # Get weeks for dropdown if needed
        weeks = []
        if current_season:
            week_results = db.session.query(Schedule.week).filter(
                Schedule.season_id == current_season.id,
                Schedule.week != None
            ).distinct().all()
            weeks = sorted([w[0] for w in week_results if w[0]], key=lambda x: int(x) if str(x).isdigit() else 0)

        return render_template(
            'admin_panel/match_operations/schedule_matches_flowbite.html',
            current_season=current_season,
            leagues=leagues,
            teams=teams,
            weeks=weeks,
            unscheduled_matches=unscheduled_matches,
            current_league_id=league_filter
        )
    except Exception as e:
        logger.error(f"Error loading schedule matches: {e}")
        flash('Schedule matches unavailable. Verify database connection and team/league data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/create-match', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def create_match():
    """Create a new match for Pub League."""
    from app.models import Match, Team, Season, League, Schedule

    data = request.get_json()
    home_team_id = data.get('home_team_id')
    away_team_id = data.get('away_team_id')
    match_date = data.get('date')
    match_time = data.get('time')
    location = data.get('location', 'TBD')
    week = data.get('week')

    # Validation
    if not home_team_id or not away_team_id:
        return jsonify({'success': False, 'message': 'Both teams are required'}), 400

    if home_team_id == away_team_id:
        return jsonify({'success': False, 'message': 'Home and Away teams must be different'}), 400

    # Get teams
    home_team = db.session.query(Team).get(home_team_id)
    away_team = db.session.query(Team).get(away_team_id)

    if not home_team or not away_team:
        return jsonify({'success': False, 'message': 'One or both teams not found'}), 404

    # Check if teams are in the same league
    if home_team.league_id != away_team.league_id:
        return jsonify({'success': False, 'message': 'Teams must be in the same league'}), 400

    # Get league
    league = db.session.query(League).get(home_team.league_id)
    if not league:
        return jsonify({'success': False, 'message': 'League not found for teams'}), 404

    # Every match MUST have a schedule in this schema.
    # If no week is provided, use 'Flex' or similar.
    week_name = week or 'Flex'
    default_time = datetime.strptime('19:00', '%H:%M').time()

    # Create schedule first to get its ID
    schedule = Schedule(
        season_id=league.season_id,
        week=week_name,
        date=datetime.strptime(match_date, '%Y-%m-%d').date() if match_date else datetime.utcnow().date(),
        time=datetime.strptime(match_time, '%H:%M').time() if match_time else default_time,
        location=location or 'TBD',
        team_id=home_team_id,
        opponent=away_team_id
    )
    db.session.add(schedule)
    db.session.flush()

    # Create match
    new_match = Match(
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        date=schedule.date,
        time=schedule.time,
        location=schedule.location,
        schedule_id=schedule.id
    )

    db.session.add(new_match)
    db.session.flush()

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='create_match',
        resource_type='match',
        resource_id=str(new_match.id),
        new_value=f'{home_team.name} vs {away_team.name}',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': 'Match created successfully',
        'match_id': new_match.id
    })


@admin_panel_bp.route('/match-operations/auto-schedule', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def auto_schedule_matches():
    """Auto-schedule matches for a league based on round-robin format."""
    from app.models import Match, Team, Season, League, Schedule

    data = request.get_json()
    league_id = data.get('league_id')
    start_date = data.get('start_date')
    weeks_between = data.get('weeks_between', 1)

    if not league_id:
        return jsonify({'success': False, 'message': 'League is required'}), 400

    # Get league and its teams
    league = db.session.query(League).get(league_id)
    if not league:
        return jsonify({'success': False, 'message': 'League not found'}), 404

    teams = db.session.query(Team).filter_by(league_id=league_id).all()
    if len(teams) < 2:
        return jsonify({'success': False, 'message': 'Need at least 2 teams to schedule matches'}), 400

    # Generate round-robin schedule
    team_ids = [t.id for t in teams]
    matches_created = 0

    # Generate all possible matchups
    import itertools
    matchups = list(itertools.combinations(team_ids, 2))

    # Parse start date
    if start_date:
        current_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    else:
        current_date = datetime.utcnow().date() + timedelta(days=7)  # Start next week

    week_num = 1
    default_time = datetime.strptime('19:00', '%H:%M').time()

    # Create matches
    for i, (home_id, away_id) in enumerate(matchups):
        # Check if match already exists
        existing = db.session.query(Match).filter(
            ((Match.home_team_id == home_id) & (Match.away_team_id == away_id)) |
            ((Match.home_team_id == away_id) & (Match.away_team_id == home_id))
        ).first()

        if not existing:
            # Create schedule first
            schedule = Schedule(
                season_id=league.season_id,
                week=str(week_num),
                date=current_date,
                time=default_time,
                location='TBD',
                team_id=home_id,
                opponent=away_id
            )
            db.session.add(schedule)
            db.session.flush()

            # Create match
            match = Match(
                home_team_id=home_id,
                away_team_id=away_id,
                date=current_date,
                time=schedule.time,
                location=schedule.location,
                schedule_id=schedule.id
            )
            db.session.add(match)
            db.session.flush()  # Get the match ID

            # Link schedule to match
            schedule.match_id = match.id

            matches_created += 1

        # Move to next week every few matches
        if (i + 1) % (len(teams) // 2) == 0:
            current_date += timedelta(weeks=weeks_between)
            week_num += 1

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='auto_schedule_matches',
        resource_type='match_operations',
        resource_id=str(league_id),
        new_value=f'Auto-scheduled {matches_created} matches for {league.name}',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': f'Successfully created {matches_created} matches',
        'matches_created': matches_created
    })


@admin_panel_bp.route('/match-operations/update-match-time', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_match_time():
    """Update the date/time for an existing match."""
    from app.models import Match

    data = request.get_json()
    match_id = data.get('match_id')
    match_date = data.get('date')
    match_time = data.get('time')

    if not match_id:
        return jsonify({'success': False, 'message': 'Match ID is required'}), 400

    match = db.session.query(Match).get(match_id)
    if not match:
        return jsonify({'success': False, 'message': 'Match not found'}), 404

    # Update date and time
    old_value = f'{match.date} {match.time}'

    if match_date:
        match.date = datetime.strptime(match_date, '%Y-%m-%d').date()
    if match_time:
        match.time = datetime.strptime(match_time, '%H:%M').time()

    # Update associated schedule if it exists
    if match.schedule_id:
        from app.models import Schedule
        schedule = db.session.query(Schedule).get(match.schedule_id)
        if schedule:
            schedule.date = match.date
            schedule.time = match.time

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='update_match_time',
        resource_type='match',
        resource_id=str(match_id),
        old_value=old_value,
        new_value=f'{match.date} {match.time}',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': 'Match time updated successfully'
    })
