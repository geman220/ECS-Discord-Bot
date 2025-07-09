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
    Schedule, Match, WeekConfiguration
)
from app.auto_schedule_generator import AutoScheduleGenerator
from app.decorators import role_required
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.tasks.tasks_discord import create_team_discord_resources_task
from app.season_routes import rollover_league

logger = logging.getLogger(__name__)

auto_schedule_bp = Blueprint('auto_schedule', __name__)


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
        
        # Parse and adjust date to Sunday
        week_date = datetime.strptime(week_date_str, '%Y-%m-%d').date()
        if week_date.weekday() != 6:  # Not Sunday (6 = Sunday in weekday())
            days_until_sunday = (6 - week_date.weekday()) % 7
            if days_until_sunday == 0:
                days_until_sunday = 7
            week_date += timedelta(days=days_until_sunday)
        
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
                start_time=datetime.strptime(data['premier_start_time'], '%H:%M').time(),
                match_duration_minutes=int(data['match_duration']),
                weeks_count=int(data['regular_weeks']),
                fields=data['fields'],
                created_by=current_user.id
            )
            classic_config = AutoScheduleConfig(
                league_id=classic_league.id,
                start_time=datetime.strptime(data['classic_start_time'], '%H:%M').time(),
                match_duration_minutes=int(data['match_duration']),
                weeks_count=int(data['regular_weeks']),
                fields=data['fields'],
                created_by=current_user.id
            )
            session.add(premier_config)
            session.add(classic_config)
            
        elif league_type == 'ECS FC':
            ecs_fc_league = League(name="ECS FC", season_id=new_season.id)
            session.add(ecs_fc_league)
            session.flush()
            
            # Create auto schedule config
            ecs_config = AutoScheduleConfig(
                league_id=ecs_fc_league.id,
                start_time=datetime.strptime(data['premier_start_time'], '%H:%M').time(),
                match_duration_minutes=int(data['match_duration']),
                weeks_count=int(data['regular_weeks']),
                fields=data['fields'],
                created_by=current_user.id
            )
            session.add(ecs_config)
        
        # Perform rollover if setting as current and there was an old season
        rollover_performed = False
        if set_as_current and old_season:
            try:
                rollover_league(session, old_season, new_season)
                rollover_performed = True
                logger.info(f"Rollover completed from {old_season.name} to {new_season.name}")
            except Exception as e:
                logger.error(f"Rollover failed: {e}")
                # Continue with season creation even if rollover fails
        
        # Create placeholder teams based on user selection
        created_teams = []
        
        if league_type == 'Pub League':
            # Create Premier League teams
            premier_team_count = int(data.get('premier_teams', 8))
            for i in range(premier_team_count):
                team_letter = chr(65 + i)  # A, B, C, etc.
                team_name = f"Team {team_letter}"
                
                team = Team(name=team_name, league_id=premier_league.id)
                session.add(team)
                session.flush()  # Get team ID
                created_teams.append(team.id)
            
            # Create Classic League teams  
            classic_team_count = int(data.get('classic_teams', 4))
            for i in range(classic_team_count):
                team_letter = chr(65 + i)  # A, B, C, etc.
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
        
        # Queue Discord channel creation tasks for all teams
        for team_id in created_teams:
            try:
                create_team_discord_resources_task.delay(team_id)
                logger.info(f"Queued Discord resource creation for team ID {team_id}")
            except Exception as e:
                logger.error(f"Failed to queue Discord task for team {team_id}: {e}")
                # Don't fail the entire operation if Discord task queueing fails
        
        # Build success message
        message_parts = [f'Season "{season_name}" created successfully with {len(created_teams)} teams']
        
        if rollover_performed:
            message_parts.append('Season rollover completed - player team history updated')
        elif set_as_current and not old_season:
            message_parts.append('Set as current season (no previous season to roll over)')
        
        message_parts.append('Discord setup in progress...')
        
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
            # Parse form data
            start_time_str = request.form.get('start_time')
            match_duration = int(request.form.get('match_duration', 70))
            weeks_count = int(request.form.get('weeks_count', 7))
            fields = request.form.get('fields', 'North,South')
            
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
            if not start_time_str:
                show_error('Start time is required')
                return redirect(url_for('auto_schedule.auto_schedule_config', league_id=league_id))
            
            # Parse time
            start_time = datetime.strptime(start_time_str, '%H:%M').time()
            
            # Create or update config
            if existing_config:
                existing_config.start_time = start_time
                existing_config.match_duration_minutes = match_duration
                existing_config.weeks_count = weeks_count
                existing_config.fields = fields
                config = existing_config
            else:
                config = AutoScheduleConfig(
                    league_id=league_id,
                    start_time=start_time,
                    match_duration_minutes=match_duration,
                    weeks_count=weeks_count,
                    fields=fields,
                    created_by=current_user.id
                )
                session.add(config)
            
            session.commit()
            
            # Generate schedule templates
            generator = AutoScheduleGenerator(league_id, session)
            generator.set_config(
                start_time=start_time,
                match_duration_minutes=match_duration,
                weeks_count=weeks_count,
                fields=fields
            )
            
            # Delete any existing uncommitted templates and week configurations
            generator.delete_templates()
            
            # Delete existing week configurations for this league
            session.query(WeekConfiguration).filter_by(league_id=league_id).delete()
            
            # Generate new templates with week configurations
            templates = generator.generate_schedule_templates(week_configs)
            generator.save_templates(templates)
            
            # Save week configurations
            for config in generator.week_configurations:
                session.add(config)
            
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
        
        templates = generator.generate_schedule_templates(start_date)
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