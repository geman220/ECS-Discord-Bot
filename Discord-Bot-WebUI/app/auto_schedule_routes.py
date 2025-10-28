# app/auto_schedule_routes.py

"""
Automatic Schedule Routes Module

This module provides endpoints for the automatic schedule generation system.
It allows users to configure and generate randomized round-robin schedules
for soccer leagues with constraints like back-to-back matches, field assignments,
and balanced scheduling.
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, g
from flask_login import login_required, current_user
from datetime import datetime, time, date, timedelta
import logging
from typing import Optional
from sqlalchemy import func

from app.models import (
    League, Team, Season, AutoScheduleConfig, ScheduleTemplate, 
    Schedule, Match, WeekConfiguration, SeasonConfiguration
)
from app.auto_schedule_generator import AutoScheduleGenerator
from app.decorators import role_required
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.tasks.tasks_discord import create_team_discord_resources_task
from app.tasks.discord_cleanup import cleanup_pub_league_discord_resources_celery_task
from app.season_routes import rollover_league

logger = logging.getLogger(__name__)

auto_schedule_bp = Blueprint('auto_schedule', __name__)


@auto_schedule_bp.route('/league/<int:league_id>/season-config', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def season_config(league_id: int):
    """
    Configure season-specific settings for a league (playoffs, practice sessions, etc.).
    """
    session = g.db_session
    league = session.query(League).filter_by(id=league_id).first()
    
    if not league:
        show_error('League not found')
        return redirect(url_for('auto_schedule.schedule_manager'))
    
    # Get existing season configuration
    season_config = session.query(SeasonConfiguration).filter_by(league_id=league_id).first()
    
    if request.method == 'POST':
        try:
            # Parse form data
            regular_season_weeks = int(request.form.get('regular_season_weeks', 7))
            playoff_weeks = int(request.form.get('playoff_weeks', 2))
            has_fun_week = bool(request.form.get('has_fun_week'))
            has_tst_week = bool(request.form.get('has_tst_week'))
            has_bonus_week = bool(request.form.get('has_bonus_week'))
            has_practice_sessions = bool(request.form.get('has_practice_sessions'))
            practice_weeks = request.form.get('practice_weeks', '')
            practice_game_number = int(request.form.get('practice_game_number', 1))
            
            # Create or update season configuration
            if season_config:
                season_config.regular_season_weeks = regular_season_weeks
                season_config.playoff_weeks = playoff_weeks
                season_config.has_fun_week = has_fun_week
                season_config.has_tst_week = has_tst_week
                season_config.has_bonus_week = has_bonus_week
                season_config.has_practice_sessions = has_practice_sessions
                season_config.practice_weeks = practice_weeks if practice_weeks else None
                season_config.practice_game_number = practice_game_number
            else:
                # Determine league type based on league name
                league_type = 'PREMIER' if league.name.upper() == 'PREMIER' else 'CLASSIC' if league.name.upper() == 'CLASSIC' else 'ECS_FC'
                
                season_config = SeasonConfiguration(
                    league_id=league_id,
                    league_type=league_type,
                    regular_season_weeks=regular_season_weeks,
                    playoff_weeks=playoff_weeks,
                    has_fun_week=has_fun_week,
                    has_tst_week=has_tst_week,
                    has_bonus_week=has_bonus_week,
                    has_practice_sessions=has_practice_sessions,
                    practice_weeks=practice_weeks if practice_weeks else None,
                    practice_game_number=practice_game_number
                )
                session.add(season_config)
            
            session.commit()
            show_success(f'Season configuration updated for {league.name}')
            return redirect(url_for('auto_schedule.season_config', league_id=league_id))
            
        except Exception as e:
            logger.error(f"Error updating season configuration: {e}")
            session.rollback()
            show_error('Failed to update season configuration')
    
    # Get default values if no configuration exists
    if not season_config:
        league_type = 'PREMIER' if league.name.upper() == 'PREMIER' else 'CLASSIC' if league.name.upper() == 'CLASSIC' else 'ECS_FC'
        season_config = AutoScheduleGenerator.create_default_season_configuration(league_id, league_type)
    
    return render_template('season_config.html', 
                         league=league, 
                         season_config=season_config)


@auto_schedule_bp.route('/season/<int:season_id>/view')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach', 'pl-classic', 'pl-ecs-fc', 'pl-premier'])
def view_seasonal_schedule(season_id):
    """
    Display complete seasonal schedule view for all leagues in a season.
    """
    session = g.db_session
    
    # Get the season
    season = session.query(Season).get(season_id)
    if not season:
        show_error("Season not found")
        return redirect(url_for('auto_schedule.schedule_manager'))
    
    # Get all leagues in this season with their teams
    leagues = session.query(League).filter_by(season_id=season_id).all()
    for league in leagues:
        league.teams = session.query(Team).filter_by(league_id=league.id).all()
    
    # Get all matches for this season, organized by week
    matches = session.query(Match).join(
        Schedule, Match.schedule_id == Schedule.id
    ).join(
        Team, Schedule.team_id == Team.id
    ).join(
        League, Team.league_id == League.id
    ).filter(
        League.season_id == season_id
    ).order_by(Match.date, Match.time).all()
    
    # Organize matches by week
    schedule_by_week = {}
    
    for match in matches:
        schedule = session.query(Schedule).get(match.schedule_id)
        if not schedule:
            continue
            
        week_num = schedule.week
        if isinstance(week_num, str):
            try:
                week_num = int(week_num)
            except ValueError:
                week_num = 1
        
        if week_num not in schedule_by_week:
            # Get week configuration if it exists
            # Note: WeekConfiguration uses league_id, so we need to check each league
            match_league_id = match.home_team.league_id if hasattr(match, 'home_team') and match.home_team else None
            week_config = None
            if match_league_id:
                week_config = session.query(WeekConfiguration).filter_by(
                    league_id=match_league_id,
                    week_order=week_num
                ).first()
            
            week_type = 'REGULAR'
            if week_config:
                week_type = week_config.week_type
            
            schedule_by_week[week_num] = {
                'date': match.date,
                'week_type': week_type,
                'matches': []
            }
        
        # Add match with team information
        match.home_team = session.query(Team).get(match.home_team_id)
        match.away_team = session.query(Team).get(match.away_team_id)
        match.home_team.league = session.query(League).get(match.home_team.league_id)
        
        # Add special week information to match object for template
        match.week_type = getattr(match, 'week_type', schedule_by_week[week_num]['week_type'])
        match.is_special_week = getattr(match, 'is_special_week', False)
        match.is_playoff_game = getattr(match, 'is_playoff_game', False)
        
        schedule_by_week[week_num]['matches'].append(match)
    
    return render_template(
        'seasonal_schedule_view.html',
        season=season,
        leagues=leagues,
        schedule_by_week=schedule_by_week
    )


@auto_schedule_bp.route('/league/<int:league_id>/manage')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_league_season(league_id):
    """
    Season management page for adding weeks, managing matches, and modifying schedule.
    """
    session = g.db_session
    
    # Get the league and season
    league = session.query(League).get(league_id)
    if not league:
        show_error("League not found")
        return redirect(url_for('auto_schedule.schedule_manager'))
    
    season = session.query(Season).get(league.season_id)
    teams_query = session.query(Team).filter_by(league_id=league_id).all()
    
    # Convert teams to serializable dictionaries
    teams = [{'id': team.id, 'name': team.name} for team in teams_query]
    
    # Get existing schedule organized by week
    matches = session.query(Match).join(
        Schedule, Match.schedule_id == Schedule.id
    ).join(
        Team, Schedule.team_id == Team.id
    ).filter(
        Team.league_id == league_id
    ).order_by(Match.date, Match.time).all()
    
    existing_weeks = {}
    for match in matches:
        schedule = session.query(Schedule).get(match.schedule_id)
        if not schedule:
            continue
            
        week_num = schedule.week
        if isinstance(week_num, str):
            try:
                week_num = int(week_num)
            except ValueError:
                week_num = 1
        
        if week_num not in existing_weeks:
            # Get week configuration if it exists
            week_config = session.query(WeekConfiguration).filter_by(
                league_id=league_id,
                week_order=week_num
            ).first()
            
            week_type = 'REGULAR'
            if week_config:
                week_type = week_config.week_type
            
            existing_weeks[week_num] = {
                'date': match.date,
                'week_type': week_type,
                'matches': []
            }
        
        # Add team information to match
        match.home_team = session.query(Team).get(match.home_team_id)
        match.away_team = session.query(Team).get(match.away_team_id)
        existing_weeks[week_num]['matches'].append(match)
    
    return render_template(
        'season_management.html',
        league=league,
        season=season,
        teams=teams,  # JSON serializable
        teams_full=teams_query,  # Full objects for template dropdowns
        existing_weeks=existing_weeks
    )


@auto_schedule_bp.route('/league/<int:league_id>/add-week', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def add_week(league_id):
    """
    Add a new week with manually assigned matches to an existing season.
    """
    session = g.db_session
    
    try:
        data = request.get_json()
        week_date_str = data.get('week_date')
        week_type = data.get('week_type', 'REGULAR')
        matches_data = data.get('matches', [])
        
        if not week_date_str:
            return jsonify({'success': False, 'error': 'Week date is required'})
        
        # Parse date - use the exact date picked by user
        week_date = datetime.strptime(week_date_str, '%Y-%m-%d').date()
        # Note: No longer automatically adjusting to Sunday - use whatever date the user selected
        
        # Get the league and determine next week number
        league = session.query(League).get(league_id)
        if not league:
            return jsonify({'success': False, 'error': 'League not found'})
        
        # Find the highest existing week number
        existing_schedules = session.query(Schedule).join(
            Team, Schedule.team_id == Team.id
        ).filter(Team.league_id == league_id).all()
        
        max_week = 0
        for schedule in existing_schedules:
            try:
                week_num = int(schedule.week)
                max_week = max(max_week, week_num)
            except (ValueError, TypeError):
                continue
        
        new_week_num = max_week + 1
        
        # Create week configuration
        week_config = WeekConfiguration(
            league_id=league_id,
            week_order=new_week_num,
            week_date=week_date,
            week_type=week_type
        )
        session.add(week_config)
        
        # Create matches
        for match_data in matches_data:
            time_str = match_data.get('time', '08:00')
            field = match_data.get('field', 'North')
            home_team_id = match_data.get('home_team_id')
            away_team_id = match_data.get('away_team_id')
            
            if not home_team_id or not away_team_id:
                continue
            
            # Parse time
            match_time = datetime.strptime(time_str, '%H:%M').time()
            
            # Create schedule entries for both teams
            home_schedule = Schedule(
                week=new_week_num,
                date=week_date,
                time=match_time,
                location=field,
                team_id=home_team_id,
                opponent=away_team_id
            )
            session.add(home_schedule)
            
            away_schedule = Schedule(
                week=new_week_num,
                date=week_date,
                time=match_time,
                location=field,
                team_id=away_team_id,
                opponent=home_team_id
            )
            session.add(away_schedule)
            
            # Create match record
            match = Match(
                date=week_date,
                time=match_time,
                location=field,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                schedule=home_schedule
            )
            session.add(match)
        
        session.commit()
        return jsonify({'success': True, 'message': f'Week {new_week_num} created successfully'})
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error adding week: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@auto_schedule_bp.route('/get-match-data')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def get_match_data():
    """
    Get match data for editing.
    """
    session = g.db_session
    match_id = request.args.get('match_id')
    
    if not match_id:
        return jsonify({'success': False, 'error': 'Match ID required'})
    
    match = session.query(Match).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'})
    
    return jsonify({
        'success': True,
        'match': {
            'time': match.time.strftime('%H:%M'),
            'field': match.location,
            'home_team_id': match.home_team_id,
            'away_team_id': match.away_team_id
        }
    })


@auto_schedule_bp.route('/update-match', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_match():
    """
    Update match details.
    """
    session = g.db_session
    
    try:
        data = request.get_json()
        match_id = data.get('match_id')
        
        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({'success': False, 'error': 'Match not found'})
        
        # Update match
        if 'time' in data:
            match.time = datetime.strptime(data['time'], '%H:%M').time()
        if 'field' in data:
            match.location = data['field']
        if 'home_team_id' in data:
            match.home_team_id = data['home_team_id']
        if 'away_team_id' in data:
            match.away_team_id = data['away_team_id']
        
        # Update corresponding schedule entries
        schedule = session.query(Schedule).get(match.schedule_id)
        if schedule:
            schedule.time = match.time
            schedule.location = match.location
            schedule.team_id = match.home_team_id
            schedule.opponent = match.away_team_id
            
            # Find and update the paired schedule
            paired_schedule = session.query(Schedule).filter_by(
                team_id=match.away_team_id,
                opponent=match.home_team_id,
                week=schedule.week,
                date=schedule.date
            ).first()
            
            if paired_schedule:
                paired_schedule.time = match.time
                paired_schedule.location = match.location
        
        session.commit()
        return jsonify({'success': True, 'message': 'Match updated successfully'})
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating match: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@auto_schedule_bp.route('/update-week', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_week():
    """
    Update week details including date and start time.
    """
    session = g.db_session
    
    try:
        data = request.get_json()
        week_number = data.get('week_number')
        league_id = data.get('league_id')
        new_date = data.get('date')
        new_start_time = data.get('start_time')
        
        if not week_number or not league_id:
            return jsonify({'success': False, 'error': 'Week number and league ID are required'})
        
        # Get all matches for this week and league
        matches = session.query(Match).join(
            Schedule, Match.schedule_id == Schedule.id
        ).join(
            Team, Schedule.team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Schedule.week == week_number
        ).all()
        
        if not matches:
            return jsonify({'success': False, 'error': 'No matches found for this week'})
        
        # Update week configuration if it exists
        week_config = session.query(WeekConfiguration).filter_by(
            league_id=league_id,
            week_order=week_number
        ).first()
        
        if week_config and new_date:
            week_config.week_date = datetime.strptime(new_date, '%Y-%m-%d').date()
        
        # Update matches and schedules
        for match in matches:
            if new_date:
                match.date = datetime.strptime(new_date, '%Y-%m-%d').date()
            if new_start_time:
                match.time = datetime.strptime(new_start_time, '%H:%M').time()
            
            # Update corresponding schedule
            schedule = session.query(Schedule).get(match.schedule_id)
            if schedule:
                if new_date:
                    schedule.date = match.date
                if new_start_time:
                    schedule.time = match.time
                
                # Update paired schedule
                paired_schedule = session.query(Schedule).filter_by(
                    team_id=match.away_team_id,
                    opponent=match.home_team_id,
                    week=schedule.week
                ).first()
                
                if paired_schedule:
                    if new_date:
                        paired_schedule.date = match.date
                    if new_start_time:
                        paired_schedule.time = match.time
        
        session.commit()
        return jsonify({'success': True, 'message': 'Week updated successfully'})
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating week: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@auto_schedule_bp.route('/reorder-weeks', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def reorder_weeks():
    """
    Reorder weeks within a season.
    """
    session = g.db_session
    
    try:
        data = request.get_json()
        league_id = data.get('league_id')
        week_order = data.get('week_order')  # List of week numbers in new order
        
        if not league_id or not week_order:
            return jsonify({'success': False, 'error': 'League ID and week order are required'})
        
        # Update week configurations
        for new_position, old_week_number in enumerate(week_order, 1):
            week_config = session.query(WeekConfiguration).filter_by(
                league_id=league_id,
                week_order=old_week_number
            ).first()
            
            if week_config:
                week_config.week_order = new_position
            
            # Update schedules
            schedules = session.query(Schedule).join(
                Team, Schedule.team_id == Team.id
            ).filter(
                Team.league_id == league_id,
                Schedule.week == old_week_number
            ).all()
            
            for schedule in schedules:
                schedule.week = new_position
        
        session.commit()
        return jsonify({'success': True, 'message': 'Weeks reordered successfully'})
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error reordering weeks: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@auto_schedule_bp.route('/delete-match', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_match():
    """
    Delete a specific match and all its related records.
    """
    session = g.db_session

    try:
        data = request.get_json()
        match_id = data.get('match_id')

        match = session.query(Match).get(match_id)
        if not match:
            return jsonify({'success': False, 'error': 'Match not found'})

        # Import all models that might reference matches
        from app.models import (
            Schedule, Availability, ScheduledMessage, PlayerEvent,
            TemporarySubAssignment, SubstituteRequest
        )
        from app.database.db_models import ActiveMatchReporter, LiveMatch

        # 1. Delete LiveMatch records
        live_matches = session.query(LiveMatch).filter_by(match_id=match_id).all()
        for live_match in live_matches:
            session.delete(live_match)
        logger.info(f"Deleted {len(live_matches)} LiveMatch records")

        # 2. Delete ActiveMatchReporter records
        reporters = session.query(ActiveMatchReporter).filter_by(match_id=match_id).all()
        for reporter in reporters:
            session.delete(reporter)
        logger.info(f"Deleted {len(reporters)} ActiveMatchReporter records")

        # 3. Delete PlayerEvent records (match events)
        events = session.query(PlayerEvent).filter_by(match_id=match_id).all()
        for event in events:
            session.delete(event)
        logger.info(f"Deleted {len(events)} PlayerEvent records")

        # 4. Delete ScheduledMessage records
        messages = session.query(ScheduledMessage).filter_by(match_id=match_id).all()
        for message in messages:
            session.delete(message)
        logger.info(f"Deleted {len(messages)} ScheduledMessage records")

        # 5. Delete Availability records (RSVPs)
        availabilities = session.query(Availability).filter_by(match_id=match_id).all()
        for availability in availabilities:
            session.delete(availability)
        logger.info(f"Deleted {len(availabilities)} Availability records")

        # 6. Delete SubstituteRequest records
        sub_requests = session.query(SubstituteRequest).filter_by(match_id=match_id).all()
        for sub_request in sub_requests:
            session.delete(sub_request)
        logger.info(f"Deleted {len(sub_requests)} SubstituteRequest records")

        # 7. Delete TemporarySubAssignment records (should cascade, but let's be explicit)
        temp_subs = session.query(TemporarySubAssignment).filter_by(match_id=match_id).all()
        for temp_sub in temp_subs:
            session.delete(temp_sub)
        logger.info(f"Deleted {len(temp_subs)} TemporarySubAssignment records")

        # 8. Delete corresponding schedule entries
        schedule = session.query(Schedule).get(match.schedule_id)
        if schedule:
            # Find and delete the paired schedule
            paired_schedule = session.query(Schedule).filter_by(
                team_id=match.away_team_id,
                opponent=match.home_team_id,
                week=schedule.week,
                date=schedule.date
            ).first()

            if paired_schedule:
                session.delete(paired_schedule)

            session.delete(schedule)

        # 9. Finally delete the match itself
        session.delete(match)
        session.commit()

        logger.info(f"Successfully deleted match {match_id} and all related records")
        return jsonify({'success': True, 'message': 'Match deleted successfully'})

    except Exception as e:
        session.rollback()
        logger.error(f"Error deleting match: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@auto_schedule_bp.route('/add-match', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def add_match():
    """
    Add a new match to an existing week.
    """
    session = g.db_session
    
    try:
        data = request.get_json()
        week_number = data.get('week_number')
        league_id = data.get('league_id')
        date_str = data.get('date')
        time_str = data.get('time')
        field = data.get('field')
        home_team_id = data.get('home_team_id')
        away_team_id = data.get('away_team_id')
        
        if not all([week_number, league_id, date_str, time_str, field, home_team_id, away_team_id]):
            return jsonify({'success': False, 'error': 'All fields are required'})
        
        # Parse date and time
        match_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        match_time = datetime.strptime(time_str, '%H:%M').time()
        
        # Create schedule entries for both teams
        home_schedule = Schedule(
            week=week_number,
            date=match_date,
            time=match_time,
            location=field,
            team_id=home_team_id,
            opponent=away_team_id
        )
        session.add(home_schedule)
        
        away_schedule = Schedule(
            week=week_number,
            date=match_date,
            time=match_time,
            location=field,
            team_id=away_team_id,
            opponent=home_team_id
        )
        session.add(away_schedule)
        
        # Create match record
        match = Match(
            date=match_date,
            time=match_time,
            location=field,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            schedule=home_schedule
        )
        session.add(match)
        
        session.commit()
        return jsonify({'success': True, 'message': 'Match added successfully'})
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error adding match: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@auto_schedule_bp.route('/league/<int:league_id>/delete-week', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_week(league_id):
    """
    Delete an entire week and all its matches.
    """
    session = g.db_session
    
    try:
        data = request.get_json()
        week_number = data.get('week_number')
        
        # Get all schedules for this week and league
        schedules = session.query(Schedule).join(
            Team, Schedule.team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Schedule.week == week_number
        ).all()
        
        # Delete matches and schedules
        for schedule in schedules:
            # Delete any matches associated with this schedule
            matches = session.query(Match).filter_by(schedule_id=schedule.id).all()
            for match in matches:
                session.delete(match)
            
            session.delete(schedule)
        
        # Delete week configuration if it exists
        week_config = session.query(WeekConfiguration).filter_by(
            league_id=league_id,
            week_order=week_number
        ).first()
        if week_config:
            session.delete(week_config)
        
        session.commit()
        return jsonify({'success': True, 'message': f'Week {week_number} deleted successfully'})
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error deleting week: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@auto_schedule_bp.route('/')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def schedule_manager():
    """
    Main Auto Schedule Manager - shows all available leagues for schedule generation.
    """
    session = g.db_session
    
    # Get all active seasons
    pub_league_seasons = session.query(Season).filter_by(league_type='Pub League').all()
    ecs_fc_seasons = session.query(Season).filter_by(league_type='ECS FC').all()
    
    # Get current seasons
    current_pub_season = session.query(Season).filter_by(
        league_type='Pub League', is_current=True
    ).first()
    current_ecs_season = session.query(Season).filter_by(
        league_type='ECS FC', is_current=True
    ).first()
    
    return render_template('auto_schedule_manager.html',
                         pub_league_seasons=pub_league_seasons,
                         ecs_fc_seasons=ecs_fc_seasons,
                         current_pub_season=current_pub_season,
                         current_ecs_season=current_ecs_season,
                         title='Auto Schedule Manager (NEW)')


@auto_schedule_bp.route('/league/<int:league_id>')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def league_overview(league_id: int):
    """
    Show overview of a specific league's auto schedule status.
    """
    session = g.db_session
    league = session.query(League).filter_by(id=league_id).first()
    
    if not league:
        show_error('League not found')
        return redirect(url_for('auto_schedule.schedule_manager'))
    
    # Check for existing auto schedule config
    config = session.query(AutoScheduleConfig).filter_by(league_id=league_id).first()
    
    # Check for existing templates
    templates_count = session.query(ScheduleTemplate).filter_by(
        league_id=league_id, is_committed=False
    ).count()
    
    # Check for existing manual schedule
    team_ids = [team.id for team in league.teams]
    existing_schedule = session.query(Schedule).filter(
        Schedule.team_id.in_(team_ids)
    ).first() if team_ids else None
    
    return render_template('auto_schedule_league_overview.html',
                         league=league,
                         config=config,
                         templates_count=templates_count,
                         existing_schedule=existing_schedule,
                         title=f'Auto Schedule - {league.name}')


@auto_schedule_bp.route('/create-season-wizard', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def create_season_wizard():
    """
    Create a new season through the wizard process.
    """
    session = g.db_session
    
    try:
        data = request.get_json()
        
        # Create the season
        season_name = data['season_name']
        league_type = data['league_type']
        set_as_current = data.get('set_as_current', False)
        season_start_date = datetime.strptime(data['season_start_date'], '%Y-%m-%d').date()
        week_configs = data.get('week_configs', [])
        
        # Check if season already exists
        existing = session.query(Season).filter(
            func.lower(Season.name) == season_name.lower(),
            Season.league_type == league_type
        ).first()
        
        if existing:
            return jsonify({'error': f'Season "{season_name}" already exists for {league_type}'}), 400
        
        # Handle rollover if setting as current season
        old_season = None
        if set_as_current:
            # Find existing current season of this type
            old_season = session.query(Season).filter_by(
                league_type=league_type,
                is_current=True
            ).first()
            
            # Mark old season as not current
            if old_season:
                old_season.is_current = False
        
        # Create new season
        new_season = Season(
            name=season_name,
            league_type=league_type,
            is_current=set_as_current
        )
        session.add(new_season)
        session.flush()  # Get the ID
        
        # Create leagues based on type
        if league_type == 'Pub League':
            premier_league = League(name="Premier", season_id=new_season.id)
            classic_league = League(name="Classic", season_id=new_season.id)
            session.add(premier_league)
            session.add(classic_league)
            session.flush()
            
            # Create auto schedule configs for both leagues
            premier_config = AutoScheduleConfig(
                league_id=premier_league.id,
                premier_start_time=datetime.strptime(data['premier_start_time'], '%H:%M').time(),
                classic_start_time=datetime.strptime(data['classic_start_time'], '%H:%M').time(),
                enable_time_rotation=data.get('enable_time_rotation', True),
                break_duration_minutes=int(data.get('break_duration', 10)),
                match_duration_minutes=int(data['match_duration']),
                weeks_count=int(data.get('premier_regular_weeks', 7)),
                fields=data['fields'],
                enable_practice_weeks=data.get('enable_practice_weeks', False),
                practice_weeks=data.get('practice_weeks'),
                created_by=current_user.id
            )
            classic_config = AutoScheduleConfig(
                league_id=classic_league.id,
                premier_start_time=datetime.strptime(data['premier_start_time'], '%H:%M').time(),
                classic_start_time=datetime.strptime(data['classic_start_time'], '%H:%M').time(),
                enable_time_rotation=data.get('enable_time_rotation', True),
                break_duration_minutes=int(data.get('break_duration', 10)),
                match_duration_minutes=int(data['match_duration']),
                weeks_count=int(data.get('classic_regular_weeks', 8)),
                fields=data['fields'],
                enable_practice_weeks=data.get('enable_practice_weeks', False),
                practice_weeks=data.get('practice_weeks'),
                created_by=current_user.id
            )
            session.add(premier_config)
            session.add(classic_config)
            
            # Create season configurations for both leagues
            premier_season_config = AutoScheduleGenerator.create_default_season_configuration(
                premier_league.id, 'PREMIER'
            )
            classic_season_config = AutoScheduleGenerator.create_default_season_configuration(
                classic_league.id, 'CLASSIC'
            )
            
            # Override defaults with user preferences if provided
            if 'premier_playoff_weeks' in data:
                premier_season_config.playoff_weeks = int(data['premier_playoff_weeks'])
            if 'premier_has_fun_week' in data:
                premier_season_config.has_fun_week = bool(data['premier_has_fun_week'])
            if 'premier_has_tst_week' in data:
                premier_season_config.has_tst_week = bool(data['premier_has_tst_week'])
            if 'premier_has_bonus_week' in data:
                premier_season_config.has_bonus_week = bool(data['premier_has_bonus_week'])
            
            if 'classic_playoff_weeks' in data:
                classic_season_config.playoff_weeks = int(data['classic_playoff_weeks'])
            if 'classic_has_practice_sessions' in data:
                classic_season_config.has_practice_sessions = bool(data['classic_has_practice_sessions'])
            if 'classic_practice_weeks' in data:
                classic_season_config.practice_weeks = data['classic_practice_weeks']
            if 'classic_practice_game_number' in data:
                classic_season_config.practice_game_number = int(data['classic_practice_game_number'])
            
            session.add(premier_season_config)
            session.add(classic_season_config)
            
        elif league_type == 'ECS FC':
            ecs_fc_league = League(name="ECS FC", season_id=new_season.id)
            session.add(ecs_fc_league)
            session.flush()
            
            # Create auto schedule config
            ecs_config = AutoScheduleConfig(
                league_id=ecs_fc_league.id,
                start_time=datetime.strptime(data['premier_start_time'], '%H:%M').time(),
                match_duration_minutes=int(data['match_duration']),
                weeks_count=int(data.get('ecs_fc_regular_weeks', 8)),
                fields=data['fields'],
                created_by=current_user.id
            )
            session.add(ecs_config)
            
            # Create season configuration for ECS FC
            ecs_fc_season_config = AutoScheduleGenerator.create_default_season_configuration(
                ecs_fc_league.id, 'ECS_FC'
            )
            
            # Override defaults with user preferences if provided
            if 'ecs_fc_playoff_weeks' in data:
                ecs_fc_season_config.playoff_weeks = int(data['ecs_fc_playoff_weeks'])
                
            session.add(ecs_fc_season_config)
        
        # Perform rollover if setting as current and there was an old season
        rollover_performed = False
        discord_cleanup_queued = False
        
        if set_as_current and old_season:
            try:
                rollover_league(session, old_season, new_season)
                rollover_performed = True
                logger.info(f"Rollover completed from {old_season.name} to {new_season.name}")
                
                # Queue Discord cleanup for Pub League seasons only
                if old_season.league_type == 'Pub League':
                    try:
                        cleanup_pub_league_discord_resources_celery_task.delay(old_season.id)
                        discord_cleanup_queued = True
                        logger.info(f"Queued Discord cleanup for old season: {old_season.name}")
                    except Exception as e:
                        logger.error(f"Failed to queue Discord cleanup: {e}")
                        # Don't fail the entire operation if Discord cleanup fails to queue
                        
            except Exception as e:
                logger.error(f"Rollover failed: {e}")
                session.rollback()
                return jsonify({'error': f'Season rollover failed: {str(e)}. Season creation aborted to prevent data corruption.'}), 500
        
        # Create placeholder teams based on user selection
        created_teams = []
        
        if league_type == 'Pub League':
            # Create Premier Division teams
            premier_team_count = int(data.get('premier_teams', 8))
            team_letter_offset = 0  # Start from A
            
            for i in range(premier_team_count):
                team_letter = chr(65 + team_letter_offset + i)  # A, B, C, etc.
                team_name = f"Team {team_letter}"
                
                team = Team(name=team_name, league_id=premier_league.id)
                session.add(team)
                session.flush()  # Get team ID
                created_teams.append(team.id)
                logger.info(f"Created Premier team: {team_name} (ID: {team.id})")
            
            # Create Classic Division teams - continue from where Premier left off
            classic_team_count = int(data.get('classic_teams', 4))
            team_letter_offset = premier_team_count  # Continue after Premier teams
            
            for i in range(classic_team_count):
                team_letter = chr(65 + team_letter_offset + i)  # Continue from where Premier ended
                team_name = f"Team {team_letter}"
                
                team = Team(name=team_name, league_id=classic_league.id)
                session.add(team)
                session.flush()  # Get team ID
                created_teams.append(team.id)
                
        elif league_type == 'ECS FC':
            # Create ECS FC teams
            ecs_fc_team_count = int(data.get('ecs_fc_teams', 8))
            for i in range(ecs_fc_team_count):
                team_letter = chr(65 + i)  # A, B, C, etc.
                team_name = f"Team {team_letter}"
                
                team = Team(name=team_name, league_id=ecs_fc_league.id)
                session.add(team)
                session.flush()  # Get team ID
                created_teams.append(team.id)
        
        session.commit()
        
        # Process week configurations from wizard data - store raw data for per-league processing
        logger.info(f"Processing {len(week_configs)} week configurations from wizard")
        if week_configs:
            for week_data in week_configs:
                logger.info(f"  Week {week_data['week_number']}: {week_data['date']} - Type: {week_data['type']} - Division: {week_data.get('division', 'None')}")
        else:
            logger.info("No week configurations provided from wizard")
        
        # Auto-generate schedule for each league
        leagues_to_schedule = []
        if league_type == 'Pub League':
            if premier_league:
                leagues_to_schedule.append(premier_league)
            if classic_league:
                leagues_to_schedule.append(classic_league)
        elif league_type == 'ECS FC':
            if ecs_fc_league:
                leagues_to_schedule.append(ecs_fc_league)
        
        schedule_generation_messages = []
        failed_leagues = []
        for league in leagues_to_schedule:
            try:
                logger.info(f"Auto-generating schedule for league: {league.name}")
                
                # Create generator for this league (will be configured later)
                generator = AutoScheduleGenerator(league.id, session)
                
                # Clean up any existing week configurations and schedule templates for this league
                existing_week_configs = session.query(WeekConfiguration).filter_by(league_id=league.id).count()
                existing_templates = session.query(ScheduleTemplate).filter_by(league_id=league.id).count()
                if existing_week_configs > 0 or existing_templates > 0:
                    logger.info(f"Cleaning up existing data for {league.name}: {existing_week_configs} week configs, {existing_templates} templates")
                    session.query(WeekConfiguration).filter_by(league_id=league.id).delete()
                    session.query(ScheduleTemplate).filter_by(league_id=league.id).delete()
                    session.commit()
                
                # Create league-specific week configurations from raw week_configs data
                league_week_configs = []
                if week_configs:
                    # Determine expected division for this league
                    league_division_map = {
                        'Premier': 'premier',
                        'Classic': 'classic', 
                        'ECS FC': 'ecs_fc'
                    }
                    expected_division = league_division_map.get(league.name)
                    
                    logger.info(f"=== CREATING WEEKS for {league.name} (ID: {league.id}) ===")
                    logger.info(f"Expected division: {expected_division}")
                    
                    # Filter week_configs for this specific division
                    division_weeks = [w for w in week_configs if w.get('division') == expected_division]
                    logger.info(f"Found {len(division_weeks)} weeks for division {expected_division}")
                    
                    # Get season configuration for practice session info
                    season_config = session.query(SeasonConfiguration).filter_by(league_id=league.id).first()
                    practice_weeks = []
                    practice_game_number = 1
                    
                    if season_config and season_config.has_practice_sessions:
                        practice_weeks = season_config.get_practice_weeks_list()
                        practice_game_number = season_config.practice_game_number
                        logger.info(f"Practice sessions enabled for {league.name}: weeks {practice_weeks}, game {practice_game_number}")
                    
                    # Create WeekConfiguration objects for this league
                    for week_data in division_weeks:
                        # Check if this week should have practice sessions
                        has_practice = week_data['week_number'] in practice_weeks
                        
                        # Create WeekConfiguration for this specific league
                        league_week_config = WeekConfiguration(
                            league_id=league.id,
                            week_date=datetime.strptime(week_data['date'], '%Y-%m-%d').date(),
                            week_type=week_data['type'],
                            week_order=week_data['week_number'],
                            is_playoff_week=(week_data['type'] == 'PLAYOFF'),
                            playoff_round=1 if week_data['type'] == 'PLAYOFF' else None,
                            has_practice_session=has_practice,
                            practice_game_number=practice_game_number if has_practice else None
                        )
                        session.add(league_week_config)
                        league_week_configs.append(league_week_config)
                        logger.info(f"  ✓ CREATED WeekConfiguration: League {league.name} (ID: {league.id}), Week {league_week_config.week_order}, Type: {league_week_config.week_type}" + 
                                   (f" (Practice: Game {practice_game_number})" if has_practice else ""))
                
                # Generator already created at start of loop - don't recreate it here
                
                # Get season configuration for this league
                season_config = session.query(SeasonConfiguration).filter_by(league_id=league.id).first()
                if season_config:
                    generator.set_season_configuration(season_config)
                    
                    # If no week configs provided from wizard, generate them from season config
                    if not league_week_configs:
                        logger.warning(f"No weeks found for {league.name}, generating from season config")
                        fallback_week_configs = AutoScheduleGenerator.generate_week_configurations_from_season_config(
                            season_config, season_start_date
                        )
                        
                        # Convert fallback configs to proper WeekConfiguration objects
                        for week_config in fallback_week_configs:
                            if isinstance(week_config, dict):
                                # Convert dict to WeekConfiguration object - handle different field names
                                league_week_config = WeekConfiguration(
                                    league_id=league.id,
                                    week_date=week_config.get('week_date') or week_config.get('date'),
                                    week_type=week_config.get('week_type') or week_config.get('type', 'REGULAR'),
                                    week_order=week_config.get('week_order') or week_config.get('week_number', 1),
                                    is_playoff_week=week_config.get('is_playoff_week', False),
                                    playoff_round=week_config.get('playoff_round', None),
                                    has_practice_session=week_config.get('has_practice_session', False),
                                    practice_game_number=week_config.get('practice_game_number', None)
                                )
                                session.add(league_week_config)
                                league_week_configs.append(league_week_config)
                                logger.info(f"  ✓ CREATED fallback WeekConfiguration: League {league.name} (ID: {league.id}), Week {league_week_config.week_order}, Type: {league_week_config.week_type}")
                            else:
                                # Already a WeekConfiguration object
                                league_week_configs.append(week_config)
                
                # Get the AutoScheduleConfig for this league
                logger.info(f"STARTING AutoScheduleConfig lookup for {league.name} (ID: {league.id})")
                auto_config = session.query(AutoScheduleConfig).filter_by(league_id=league.id).first()
                logger.info(f"AutoScheduleConfig lookup for league {league.name} (ID: {league.id}): {'FOUND' if auto_config else 'NOT FOUND'}")
                
                if auto_config:
                    # Use the appropriate start time based on league name
                    if league.name.lower() == 'premier':
                        start_time = auto_config.premier_start_time
                    elif league.name.lower() == 'classic':
                        start_time = auto_config.classic_start_time
                    else:
                        # For ECS FC or other leagues, use start_time field if it exists, otherwise premier_start_time
                        start_time = getattr(auto_config, 'start_time', None) or auto_config.premier_start_time
                    
                    logger.info(f"Configuring generator for {league.name}: start_time={start_time}")
                    
                    generator.set_config(
                        start_time=start_time,
                        match_duration_minutes=auto_config.match_duration_minutes,
                        weeks_count=auto_config.weeks_count,
                        fields=auto_config.fields
                    )
                    
                    logger.info(f"Generator configured successfully for {league.name}")
                
                else:
                    # Fallback to default configuration if no config found
                    logger.error(f"CRITICAL: No AutoScheduleConfig found for league {league.name} (ID: {league.id}), using defaults!")
                    logger.error(f"This should not happen - configs should have been created earlier")
                    generator.set_config(
                        start_time=time(19, 0),  # 7:00 PM default
                        match_duration_minutes=70,
                        weeks_count=7,
                        fields="North,South"
                    )
                
                # Generate schedule templates - pass the WeekConfiguration objects
                logger.info(f"=== FINAL WEEK CONFIGS for {league.name} ===")
                logger.info(f"Total week configs: {len(league_week_configs)}")
                for i, wc in enumerate(league_week_configs[:5]):  # Show first 5
                    logger.info(f"  Week {i+1}: {type(wc).__name__} - Week {wc.week_order}, Type: {wc.week_type}")
                if len(league_week_configs) > 5:
                    logger.info(f"  ... and {len(league_week_configs) - 5} more week configs")
                
                logger.info(f"Generating schedule templates for {league.name} with {len(league_week_configs)} week configurations")
                logger.info(f"ABOUT TO GENERATE TEMPLATES - Generator start_time: {getattr(generator, 'start_time', 'NOT SET')}")
                templates = generator.generate_schedule_templates(league_week_configs)
                logger.info(f"Generated {len(templates)} schedule templates for {league.name}")
                
                if templates and len(templates) > 0:
                    try:
                        # Save templates to database
                        generator.save_templates(templates)
                        
                        # Count templates before committing
                        template_count = len(templates)
                        
                        # Commit templates to create actual matches
                        generator.commit_templates_to_schedule()
                        
                        # Count actual matches created
                        matches_created = session.query(Match).join(
                            Schedule, Match.schedule_id == Schedule.id
                        ).join(
                            Team, Schedule.team_id == Team.id
                        ).filter(Team.league_id == league.id).count()
                        
                        schedule_generation_messages.append(f"{league.name}: {matches_created} matches created from {template_count} templates")
                        logger.info(f"Successfully generated {matches_created} matches for {league.name}")
                        
                    except Exception as commit_error:
                        error_msg = str(commit_error)
                        schedule_generation_messages.append(f"{league.name}: Schedule generation failed - {error_msg}")
                        logger.error(f"Failed to commit templates for {league.name}: {error_msg}", exc_info=True)
                        failed_leagues.append(league.name)
                        # Continue with Discord resource creation even if schedule generation fails
                else:
                    schedule_generation_messages.append(f"{league.name}: No schedule templates generated")
                    logger.warning(f"No schedule templates generated for {league.name} - check team count and configuration")
                    
            except Exception as e:
                error_msg = f"Schedule generation failed for {league.name}: {str(e)}"
                schedule_generation_messages.append(error_msg)
                logger.error(error_msg, exc_info=True)
                failed_leagues.append(league.name)
                # Continue with other leagues even if one fails
        
        # Commit any placeholder teams and schedule changes
        session.commit()
        
        # Ensure the database transaction is fully committed before queuing tasks
        session.close()
        
        # Queue Discord channel creation tasks for all teams
        # Add a small delay to ensure database commits are visible to workers
        import time as time_module
        time_module.sleep(0.5)
        
        logger.info(f"About to queue Discord resources for {len(created_teams)} teams: {created_teams}")
        for team_id in created_teams:
            try:
                task_result = create_team_discord_resources_task.delay(team_id)
                logger.info(f"Queued Discord resource creation for team ID {team_id}, task ID: {task_result.id}")
            except Exception as e:
                logger.error(f"Failed to queue Discord task for team {team_id}: {e}")
                # Don't fail the entire operation if Discord task queueing fails
        
        # Build success message
        message_parts = [f'Season "{season_name}" created successfully with {len(created_teams)} teams']
        
        # Add schedule generation results
        if schedule_generation_messages:
            message_parts.extend(schedule_generation_messages)
        
        if rollover_performed:
            message_parts.append('Season rollover completed - player team history updated')
            if discord_cleanup_queued:
                message_parts.append('Old team Discord channels and roles cleanup queued')
        elif set_as_current and not old_season:
            message_parts.append('Set as current season (no previous season to roll over)')
        
        message_parts.append('Discord setup in progress...')
        
        # Check if any leagues failed
        if failed_leagues:
            return jsonify({
                'success': False,
                'error': f'Season created but schedule generation failed for: {", ".join(failed_leagues)}. Please check the logs and regenerate schedules for these leagues.',
                'message': '. '.join(message_parts),
                'redirect_url': url_for('auto_schedule.schedule_manager')
            }), 400
        
        return jsonify({
            'success': True,
            'message': '. '.join(message_parts),
            'redirect_url': url_for('auto_schedule.schedule_manager')
        })
        
    except Exception as e:
        logger.error(f"Error creating season: {e}")
        session.rollback()
        return jsonify({'error': 'An error occurred while creating the season'}), 500


@auto_schedule_bp.route('/league/<int:league_id>/auto-schedule', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def auto_schedule_config(league_id: int):
    """
    Configure automatic schedule generation for a league.
    
    Args:
        league_id: ID of the league to configure
    """
    session = g.db_session
    league = session.query(League).filter_by(id=league_id).first()
    
    if not league:
        show_error('League not found')
        return redirect(url_for('publeague.season.manage_seasons'))
    
    # Check if league has enough teams
    team_count = len(league.teams)
    if team_count < 2:
        show_warning(f'League "{league.name}" only has {team_count} teams. Need at least 2 teams to generate a schedule.')
    
    # Get existing config if any
    existing_config = session.query(AutoScheduleConfig).filter_by(league_id=league_id).first()
    
    if request.method == 'POST':
        try:
            # Parse enhanced form data
            premier_start_time_str = request.form.get('premier_start_time', '08:20')
            classic_start_time_str = request.form.get('classic_start_time', '13:10')
            enable_time_rotation = bool(request.form.get('enable_time_rotation'))
            break_duration = int(request.form.get('break_duration', 10))
            match_duration = int(request.form.get('match_duration', 70))
            weeks_count = int(request.form.get('weeks_count', 7))
            enable_practice_weeks = bool(request.form.get('enable_practice_weeks'))
            
            # Parse field configuration
            field_config = []
            field_index = 0
            while True:
                field_name = request.form.get(f'field_name_{field_index}')
                if not field_name:
                    break
                field_capacity = int(request.form.get(f'field_capacity_{field_index}', 20))
                field_config.append({
                    'name': field_name.strip(),
                    'capacity': field_capacity
                })
                field_index += 1
            
            # Fallback to legacy fields format if no field config
            if not field_config:
                fields = request.form.get('fields', 'North,South')
                field_config = [{'name': name.strip(), 'capacity': 20} for name in fields.split(',') if name.strip()]
            
            # Generate fields string for backward compatibility
            fields = ','.join([field['name'] for field in field_config])
            
            # Parse practice weeks
            practice_weeks_list = request.form.getlist('practice_weeks')
            practice_weeks = ','.join(practice_weeks_list) if practice_weeks_list else None
            
            # Parse week configurations from form
            week_configs = []
            week_dates = request.form.getlist('week_dates[]')
            week_types = request.form.getlist('week_types[]')
            week_descriptions = request.form.getlist('week_descriptions[]')
            
            for i, (date_str, week_type) in enumerate(zip(week_dates, week_types)):
                if date_str:  # Only add if date is provided
                    week_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    description = week_descriptions[i] if i < len(week_descriptions) else ''
                    week_configs.append({
                        'date': week_date,
                        'week_type': week_type,
                        'description': description
                    })
            
            if not week_configs:
                show_error('At least one week configuration is required')
                return redirect(url_for('auto_schedule.auto_schedule_config', league_id=league_id))
            
            # Validate inputs
            if not premier_start_time_str or not classic_start_time_str:
                show_error('Both Premier and Classic start times are required')
                return redirect(url_for('auto_schedule.auto_schedule_config', league_id=league_id))
            
            # Parse times
            premier_start_time = datetime.strptime(premier_start_time_str, '%H:%M').time()
            classic_start_time = datetime.strptime(classic_start_time_str, '%H:%M').time()
            
            # Create or update config
            if existing_config:
                existing_config.premier_start_time = premier_start_time
                existing_config.classic_start_time = classic_start_time
                existing_config.enable_time_rotation = enable_time_rotation
                existing_config.break_duration_minutes = break_duration
                existing_config.match_duration_minutes = match_duration
                existing_config.weeks_count = weeks_count
                existing_config.fields = fields
                existing_config.field_config = field_config
                existing_config.enable_practice_weeks = enable_practice_weeks
                existing_config.practice_weeks = practice_weeks
                config = existing_config
            else:
                config = AutoScheduleConfig(
                    league_id=league_id,
                    premier_start_time=premier_start_time,
                    classic_start_time=classic_start_time,
                    enable_time_rotation=enable_time_rotation,
                    break_duration_minutes=break_duration,
                    match_duration_minutes=match_duration,
                    weeks_count=weeks_count,
                    fields=fields,
                    field_config=field_config,
                    enable_practice_weeks=enable_practice_weeks,
                    practice_weeks=practice_weeks,
                    created_by=current_user.id
                )
                session.add(config)
            
            session.commit()
            
            # Generate schedule templates
            generator = AutoScheduleGenerator(league_id, session)
            # Use the appropriate start time based on league type
            league_start_time = config.get_start_time_for_division(league.name)
            generator.set_config(
                start_time=league_start_time,
                match_duration_minutes=match_duration,
                weeks_count=weeks_count,
                fields=fields
            )
            
            # Get season configuration for this league
            season_config = session.query(SeasonConfiguration).filter_by(league_id=league_id).first()
            if season_config:
                generator.set_season_configuration(season_config)
                
                # If no week configs provided, generate them from season config
                if not week_configs:
                    # Use the first week date if provided, otherwise use current date
                    start_date = datetime.strptime(week_dates[0], '%Y-%m-%d').date() if week_dates and week_dates[0] else date.today()
                    week_configs = AutoScheduleGenerator.generate_week_configurations_from_season_config(
                        season_config, start_date
                    )
            
            # Delete any existing uncommitted templates and week configurations
            generator.delete_templates()
            
            # Delete existing week configurations for this league
            session.query(WeekConfiguration).filter_by(league_id=league_id).delete()
            
            # Convert week_configs to WeekConfiguration objects if needed
            week_config_objects = []
            if week_configs:
                for i, config in enumerate(week_configs, 1):
                    if isinstance(config, dict):
                        # Convert dict to WeekConfiguration object
                        week_config_obj = WeekConfiguration(
                            league_id=league_id,
                            week_date=config['date'],
                            week_type=config['week_type'],
                            week_order=i,
                            description=config.get('description', ''),
                            is_playoff_week=config.get('is_playoff_week', False),
                            playoff_round=config.get('playoff_round', None),
                            has_practice_session=config.get('has_practice_session', False),
                            practice_game_number=config.get('practice_game_number', None)
                        )
                        week_config_objects.append(week_config_obj)
                        session.add(week_config_obj)
                    else:
                        # Already a WeekConfiguration object
                        week_config_objects.append(config)
            
            # Generate new templates with week configurations
            templates = generator.generate_schedule_templates(week_config_objects)
            generator.save_templates(templates)
            
            show_success(f'Schedule configuration saved and {len(templates)} match templates generated for {league.name}')
            return redirect(url_for('auto_schedule.preview_schedule', league_id=league_id))
            
        except ValueError as e:
            logger.error(f"Value error in auto schedule config: {e}")
            show_error(f'Invalid input: {str(e)}')
        except Exception as e:
            logger.error(f"Error in auto schedule config: {e}")
            show_error('An error occurred while generating the schedule')
            session.rollback()
    
    return render_template('auto_schedule_config.html', 
                         league=league, 
                         config=existing_config,
                         team_count=team_count,
                         title=f'Auto Schedule - {league.name}')


@auto_schedule_bp.route('/league/<int:league_id>/preview-schedule')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def preview_schedule(league_id: int):
    """
    Preview the generated schedule before committing it.
    
    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).filter_by(id=league_id).first()
    
    if not league:
        show_error('League not found')
        return redirect(url_for('publeague.season.manage_seasons'))
    
    # Get schedule preview
    generator = AutoScheduleGenerator(league_id, session)
    schedule_preview = generator.get_templates_preview()
    
    # Get config
    config = session.query(AutoScheduleConfig).filter_by(league_id=league_id).first()
    
    # Check if any templates exist
    if not schedule_preview:
        show_info('No schedule templates found. Please generate a schedule first.')
        return redirect(url_for('auto_schedule.auto_schedule_config', league_id=league_id))
    
    return render_template('preview_schedule.html',
                         league=league,
                         schedule_preview=schedule_preview,
                         config=config,
                         title=f'Preview Schedule - {league.name}')


@auto_schedule_bp.route('/league/<int:league_id>/commit-schedule', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def commit_schedule(league_id: int):
    """
    Commit the schedule templates to actual schedule entries.
    
    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).filter_by(id=league_id).first()
    
    if not league:
        return jsonify({'error': 'League not found'}), 404
    
    try:
        # Check if league already has a schedule
        existing_schedule = session.query(Schedule).filter_by(season_id=league.season_id).first()
        if existing_schedule:
            # Get team IDs for this league
            team_ids = [team.id for team in league.teams]
            league_schedule = session.query(Schedule).filter(
                Schedule.team_id.in_(team_ids)
            ).first()
            
            if league_schedule:
                return jsonify({'error': 'This league already has a schedule. Please delete it first.'}), 400
        
        # Commit templates to schedule
        generator = AutoScheduleGenerator(league_id, session)
        generator.commit_templates_to_schedule()
        
        show_success(f'Schedule committed successfully for {league.name}')
        return jsonify({'success': True, 'message': 'Schedule committed successfully'})
        
    except Exception as e:
        logger.error(f"Error committing schedule: {e}")
        session.rollback()
        return jsonify({'error': 'An error occurred while committing the schedule'}), 500


@auto_schedule_bp.route('/league/<int:league_id>/delete-schedule', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_schedule(league_id: int):
    """
    Delete the generated schedule templates.
    
    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).filter_by(id=league_id).first()
    
    if not league:
        return jsonify({'error': 'League not found'}), 404
    
    try:
        # Clean up Discord resources for teams in this league before deleting
        from app.tasks.discord_cleanup import cleanup_league_discord_resources_task
        try:
            # Get all teams in this league to clean up their Discord resources
            teams = session.query(Team).filter_by(league_id=league_id).all()
            if teams:
                logger.info(f"Cleaning up Discord resources for {len(teams)} teams in {league.name}")
                # Queue Discord cleanup task
                cleanup_league_discord_resources_task.delay(league_id)
                logger.info(f"Queued Discord cleanup for league: {league.name}")
        except Exception as e:
            logger.error(f"Failed to queue Discord cleanup for league {league_id}: {e}")
            # Continue with schedule deletion even if Discord cleanup fails to queue
        
        # Delete templates
        generator = AutoScheduleGenerator(league_id, session)
        generator.delete_templates()
        
        show_success(f'Schedule templates deleted for {league.name}')
        return jsonify({'success': True, 'message': 'Schedule templates deleted successfully'})
        
    except Exception as e:
        logger.error(f"Error deleting schedule templates: {e}")
        session.rollback()
        return jsonify({'error': 'An error occurred while deleting the schedule templates'}), 500


@auto_schedule_bp.route('/league/<int:league_id>/regenerate-schedule', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def regenerate_schedule(league_id: int):
    """
    Regenerate the schedule templates with a new randomization.
    
    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).filter_by(id=league_id).first()
    
    if not league:
        return jsonify({'error': 'League not found'}), 404
    
    try:
        # Get existing config
        config = session.query(AutoScheduleConfig).filter_by(league_id=league_id).first()
        if not config:
            return jsonify({'error': 'No schedule configuration found. Please configure first.'}), 400
        
        # Delete existing templates
        generator = AutoScheduleGenerator(league_id, session)
        generator.delete_templates()
        
        # Get start date from form
        start_date_str = request.form.get('start_date')
        if not start_date_str:
            return jsonify({'error': 'Start date is required'}), 400
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        # Generate new templates
        generator.set_config(
            start_time=config.start_time,
            match_duration_minutes=config.match_duration_minutes,
            weeks_count=config.weeks_count,
            fields=config.fields
        )
        
        # Get season configuration for this league
        season_config = session.query(SeasonConfiguration).filter_by(league_id=league_id).first()
        if season_config:
            generator.set_season_configuration(season_config)
        
        # Get existing week configurations
        week_configs = session.query(WeekConfiguration).filter_by(league_id=league_id).order_by(WeekConfiguration.week_order).all()
        
        templates = generator.generate_schedule_templates(week_configs)
        generator.save_templates(templates)
        
        show_success(f'Schedule regenerated successfully for {league.name}')
        return jsonify({'success': True, 'message': 'Schedule regenerated successfully'})
        
    except Exception as e:
        logger.error(f"Error regenerating schedule: {e}")
        session.rollback()
        return jsonify({'error': 'An error occurred while regenerating the schedule'}), 500


@auto_schedule_bp.route('/league/<int:league_id>/swap-teams', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def swap_teams(league_id: int):
    """
    Swap teams in specific time slots.
    
    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).filter_by(id=league_id).first()
    
    if not league:
        return jsonify({'error': 'League not found'}), 404
    
    try:
        # Get swap parameters
        template_id_1 = request.form.get('template_id_1')
        template_id_2 = request.form.get('template_id_2')
        
        if not template_id_1 or not template_id_2:
            return jsonify({'error': 'Both template IDs are required'}), 400
        
        # Get templates
        template_1 = session.query(ScheduleTemplate).filter_by(id=template_id_1).first()
        template_2 = session.query(ScheduleTemplate).filter_by(id=template_id_2).first()
        
        if not template_1 or not template_2:
            return jsonify({'error': 'One or both templates not found'}), 404
        
        # Swap the teams
        temp_home = template_1.home_team_id
        temp_away = template_1.away_team_id
        
        template_1.home_team_id = template_2.home_team_id
        template_1.away_team_id = template_2.away_team_id
        template_2.home_team_id = temp_home
        template_2.away_team_id = temp_away
        
        session.commit()
        
        return jsonify({'success': True, 'message': 'Teams swapped successfully'})
        
    except Exception as e:
        logger.error(f"Error swapping teams: {e}")
        session.rollback()
        return jsonify({'error': 'An error occurred while swapping teams'}), 500


@auto_schedule_bp.route('/set-active-season', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def set_active_season():
    """
    Set a season as the active/current season for its league type.
    """
    session = g.db_session
    
    try:
        data = request.get_json()
        season_id = data.get('season_id')
        league_type = data.get('league_type')
        
        if not season_id or not league_type:
            return jsonify({'error': 'Season ID and league type are required'}), 400
        
        # Get the season to set as active
        new_active_season = session.query(Season).filter_by(id=season_id).first()
        if not new_active_season:
            return jsonify({'error': 'Season not found'}), 404
        
        if new_active_season.league_type != league_type:
            return jsonify({'error': 'Season league type mismatch'}), 400
        
        # Set all other seasons of this type as not current
        session.query(Season).filter_by(league_type=league_type).update({'is_current': False})
        
        # Set the selected season as current
        new_active_season.is_current = True
        
        session.commit()
        
        return jsonify({
            'success': True,
            'message': f'"{new_active_season.name}" is now the current {league_type} season'
        })
        
    except Exception as e:
        logger.error(f"Error setting active season: {e}")
        session.rollback()
        return jsonify({'error': 'An error occurred while updating the active season'}), 500


@auto_schedule_bp.route('/recreate-discord-resources', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def recreate_discord_resources():
    """
    Recreate Discord resources (roles, channels, permissions) for all teams in a season.
    
    This endpoint manually triggers Discord resource creation for teams that may have
    been created but didn't get their Discord resources due to task processing issues.
    """
    session = g.db_session
    
    try:
        data = request.get_json()
        if not data or 'season_id' not in data:
            return jsonify({'success': False, 'message': 'Season ID is required'}), 400
        
        season_id = data['season_id']
        
        # Get the season and verify it exists
        season = session.query(Season).filter_by(id=season_id).first()
        if not season:
            return jsonify({'success': False, 'message': 'Season not found'}), 404
        
        # Get all leagues in this season, then get teams from those leagues
        leagues = session.query(League).filter_by(season_id=season_id).all()
        
        if not leagues:
            return jsonify({'success': False, 'message': 'No leagues found in this season'}), 404
        
        # Collect all teams from all leagues in this season
        teams = []
        for league in leagues:
            league_teams = session.query(Team).filter_by(league_id=league.id).all()
            teams.extend(league_teams)
        
        if not teams:
            return jsonify({'success': False, 'message': 'No teams found in this season'}), 404
        
        # Import the Discord task here to avoid circular imports
        from app.tasks.tasks_discord import create_team_discord_resources_task
        
        # Queue Discord resource creation for each team
        queued_teams = []
        failed_teams = []
        
        for team in teams:
            try:
                task_result = create_team_discord_resources_task.delay(team.id)
                queued_teams.append(team.name)
                logger.info(f"Queued Discord resource recreation for team {team.name} (ID: {team.id}), task ID: {task_result.id}")
            except Exception as e:
                failed_teams.append(team.name)
                logger.error(f"Failed to queue Discord task for team {team.name} (ID: {team.id}): {e}")
        
        # Prepare response message
        if queued_teams:
            message = f"Successfully queued Discord resource creation for {len(queued_teams)} teams: {', '.join(queued_teams)}"
            if failed_teams:
                message += f". Failed to queue {len(failed_teams)} teams: {', '.join(failed_teams)}"
            
            logger.info(f"Discord resource recreation queued for season {season.name}: {message}")
            
            return jsonify({
                'success': True,
                'message': message,
                'queued_count': len(queued_teams),
                'failed_count': len(failed_teams)
            })
        else:
            return jsonify({
                'success': False, 
                'message': f"Failed to queue Discord resources for any teams in {season.name}"
            }), 500
        
    except Exception as e:
        logger.error(f"Error recreating Discord resources: {e}")
        session.rollback()
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500