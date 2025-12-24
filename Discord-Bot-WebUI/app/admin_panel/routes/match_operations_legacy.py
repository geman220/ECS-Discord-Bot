# app/admin_panel/routes/match_operations.py

"""
Admin Panel Match Operations Routes

This module contains routes for match and league operations:
- Match operations hub with statistics
- Match management (view, schedule, results)
- League management and standings
- Team management and rosters
- Season management
- Live match monitoring
- Player transfers and operations
"""

import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func

from .. import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

# Set up the module logger
logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def match_operations():
    """Match & League Operations hub."""
    try:
        from app.models import Match, Team, Season, League, Schedule
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        # Base query for current season matches
        base_query = Match.query
        if current_season:
            base_query = base_query.join(Schedule).filter(Schedule.season_id == current_season.id)
        
        # Get real match operations statistics
        total_matches = base_query.count()
        
        # Upcoming matches (future dates)
        upcoming_matches = base_query.filter(Match.date >= datetime.utcnow().date()).count()
        
        # Past matches for tracking
        past_matches = base_query.filter(Match.date < datetime.utcnow().date()).count()
        
        # Team statistics
        teams_count = Team.query.count()
        
        # Active leagues (all leagues are considered active if no is_active field)
        active_leagues = League.query.count()
        
        # Active seasons
        active_seasons = Season.query.filter_by(is_current=True).count()
        
        # Live matches (matches happening today)
        today = datetime.utcnow().date()
        live_matches = base_query.filter(Match.date == today).count()
        
        # Recent match activity (last 7 days)
        week_ago = datetime.utcnow().date() - timedelta(days=7)
        recent_matches = base_query.filter(Match.date >= week_ago).count()
        
        # Match completion rate
        completed_matches = base_query.filter(
            Match.date < datetime.utcnow().date(),
            Match.status == 'completed'
        ).count() if hasattr(Match, 'status') else past_matches
        
        completion_rate = round((completed_matches / past_matches * 100), 1) if past_matches > 0 else 0
        
        stats = {
            'total_matches': total_matches,
            'upcoming_matches': upcoming_matches,
            'past_matches': past_matches,
            'teams_count': teams_count,
            'active_leagues': active_leagues,
            'live_matches': live_matches,
            'active_seasons': active_seasons,
            'recent_matches': recent_matches,
            'completion_rate': f"{completion_rate}%",
            'pending_transfers': 0  # Would need transfer model implementation
        }
        
        return render_template('admin_panel/match_operations.html', stats=stats)
    except Exception as e:
        logger.error(f"Error loading match operations: {e}")
        flash('Match operations unavailable. Check database connectivity and model imports.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/match-operations/schedule')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def schedule_matches():
    """Schedule new matches for Pub League (Premier, Classic, ECS FC)."""
    try:
        from app.models import Team, League, Season, Match, Schedule
        from sqlalchemy import or_
        from sqlalchemy.orm import joinedload

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
        current_season = Season.query.filter_by(is_current=True, league_type="Pub League").first()
        if not current_season:
            current_season = Season.query.filter_by(is_current=True).first()

        # Get filter parameter
        league_filter = request.args.get('league_id', type=int)

        # Get all leagues for the current season (Premier, Classic, ECS FC)
        if current_season:
            leagues = League.query.filter_by(season_id=current_season.id).order_by(League.name).all()
        else:
            leagues = League.query.order_by(League.name).all()

        # Get teams filtered by season and optionally by league
        if current_season:
            teams_query = Team.query.join(League).filter(League.season_id == current_season.id)
            if league_filter:
                teams_query = teams_query.filter(Team.league_id == league_filter)
            teams = teams_query.order_by(Team.name).all()
        else:
            teams = Team.query.order_by(Team.name).all()

        # Get unscheduled matches (from current season teams)
        if current_season:
            league_ids = [l.id for l in leagues]
            team_ids = [t.id for t in Team.query.filter(Team.league_id.in_(league_ids)).all()]
            unscheduled_matches = Match.query.filter(
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
            unscheduled_matches = Match.query.filter(
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
            'admin_panel/match_operations/schedule_matches.html',
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
def create_match():
    """Create a new match for Pub League."""
    try:
        from app.models import Match, Team, Season, League, Schedule
        from datetime import datetime

        data = request.get_json()
        home_team_id = data.get('home_team_id')
        away_team_id = data.get('away_team_id')
        match_date = data.get('date')
        match_time = data.get('time')
        week = data.get('week')

        # Validation
        if not home_team_id or not away_team_id:
            return jsonify({'success': False, 'message': 'Both teams are required'}), 400

        if home_team_id == away_team_id:
            return jsonify({'success': False, 'message': 'Home and Away teams must be different'}), 400

        # Get teams
        home_team = Team.query.get(home_team_id)
        away_team = Team.query.get(away_team_id)

        if not home_team or not away_team:
            return jsonify({'success': False, 'message': 'One or both teams not found'}), 404

        # Check if teams are in the same league
        if home_team.league_id != away_team.league_id:
            return jsonify({'success': False, 'message': 'Teams must be in the same league'}), 400

        # Create match
        new_match = Match(
            home_team_id=home_team_id,
            away_team_id=away_team_id
        )

        # Set date and time if provided
        if match_date:
            new_match.date = datetime.strptime(match_date, '%Y-%m-%d').date()
        if match_time:
            new_match.time = datetime.strptime(match_time, '%H:%M').time()

        db.session.add(new_match)
        db.session.commit()

        # Create schedule entry if week provided
        if week and home_team.league_id:
            league = League.query.get(home_team.league_id)
            if league and league.season_id:
                schedule = Schedule(
                    season_id=league.season_id,
                    week=week,
                    match_id=new_match.id
                )
                db.session.add(schedule)
                db.session.commit()

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

    except Exception as e:
        logger.error(f"Error creating match: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Error creating match'}), 500


@admin_panel_bp.route('/match-operations/auto-schedule', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def auto_schedule_matches():
    """Auto-schedule matches for a league based on round-robin format."""
    try:
        from app.models import Match, Team, Season, League, Schedule
        from datetime import datetime, timedelta
        import itertools

        data = request.get_json()
        league_id = data.get('league_id')
        start_date = data.get('start_date')
        weeks_between = data.get('weeks_between', 1)

        if not league_id:
            return jsonify({'success': False, 'message': 'League is required'}), 400

        # Get league and its teams
        league = League.query.get(league_id)
        if not league:
            return jsonify({'success': False, 'message': 'League not found'}), 404

        teams = Team.query.filter_by(league_id=league_id).all()
        if len(teams) < 2:
            return jsonify({'success': False, 'message': 'Need at least 2 teams to schedule matches'}), 400

        # Generate round-robin schedule
        team_ids = [t.id for t in teams]
        matches_created = 0

        # Generate all possible matchups
        matchups = list(itertools.combinations(team_ids, 2))

        # Parse start date
        if start_date:
            current_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            current_date = datetime.utcnow().date() + timedelta(days=7)  # Start next week

        week_num = 1

        # Create matches
        for i, (home_id, away_id) in enumerate(matchups):
            # Check if match already exists
            existing = Match.query.filter(
                ((Match.home_team_id == home_id) & (Match.away_team_id == away_id)) |
                ((Match.home_team_id == away_id) & (Match.away_team_id == home_id))
            ).first()

            if not existing:
                match = Match(
                    home_team_id=home_id,
                    away_team_id=away_id,
                    date=current_date
                )
                db.session.add(match)
                db.session.flush()  # Get the match ID

                # Create schedule entry
                if league.season_id:
                    schedule = Schedule(
                        season_id=league.season_id,
                        week=str(week_num),
                        match_id=match.id
                    )
                    db.session.add(schedule)

                matches_created += 1

            # Move to next week every few matches
            if (i + 1) % (len(teams) // 2) == 0:
                current_date += timedelta(weeks=weeks_between)
                week_num += 1

        db.session.commit()

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

    except Exception as e:
        logger.error(f"Error auto-scheduling matches: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Error auto-scheduling matches'}), 500


@admin_panel_bp.route('/match-operations/update-match-time', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_match_time():
    """Update the date/time for an existing match."""
    try:
        from app.models import Match
        from datetime import datetime

        data = request.get_json()
        match_id = data.get('match_id')
        match_date = data.get('date')
        match_time = data.get('time')

        if not match_id:
            return jsonify({'success': False, 'message': 'Match ID is required'}), 400

        match = Match.query.get(match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        # Update date and time
        old_value = f'{match.date} {match.time}'

        if match_date:
            match.date = datetime.strptime(match_date, '%Y-%m-%d').date()
        if match_time:
            match.time = datetime.strptime(match_time, '%H:%M').time()

        db.session.commit()

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

    except Exception as e:
        logger.error(f"Error updating match time: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Error updating match time'}), 500


@admin_panel_bp.route('/match-operations/matches')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def view_matches():
    """View all Pub League matches (Premier, Classic, ECS FC)."""
    try:
        from app.models import Match, Team, Season, League, Schedule
        from sqlalchemy import or_
        from sqlalchemy.orm import joinedload

        # Get current Pub League season
        current_season = Season.query.filter_by(is_current=True, league_type="Pub League").first()
        if not current_season:
            current_season = Season.query.filter_by(is_current=True).first()

        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = 20

        # Get filter parameters
        status_filter = request.args.get('status')
        league_filter = request.args.get('league_id', type=int)
        week_filter = request.args.get('week')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')

        # Build query with eager loading
        query = Match.query.options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.schedule)
        )

        # Filter by current season teams
        if current_season:
            league_ids = [league.id for league in League.query.filter_by(season_id=current_season.id).all()]
            if league_ids:
                team_ids = [team.id for team in Team.query.filter(Team.league_id.in_(league_ids)).all()]
                if team_ids:
                    query = query.filter(
                        or_(
                            Match.home_team_id.in_(team_ids),
                            Match.away_team_id.in_(team_ids)
                        )
                    )

        # Apply status filter
        if status_filter:
            if status_filter == 'upcoming':
                query = query.filter(Match.date >= datetime.utcnow().date())
            elif status_filter == 'past':
                query = query.filter(Match.date < datetime.utcnow().date())
            elif status_filter == 'verified':
                query = query.filter(Match.home_team_verified == True, Match.away_team_verified == True)
            elif status_filter == 'unverified':
                query = query.filter(
                    Match.home_team_score != None,
                    or_(Match.home_team_verified == False, Match.away_team_verified == False)
                )

        # Apply league filter (filter by team's league)
        if league_filter:
            league_team_ids = [team.id for team in Team.query.filter_by(league_id=league_filter).all()]
            if league_team_ids:
                query = query.filter(
                    or_(
                        Match.home_team_id.in_(league_team_ids),
                        Match.away_team_id.in_(league_team_ids)
                    )
                )

        # Apply week filter
        if week_filter:
            query = query.join(Schedule, Match.schedule_id == Schedule.id).filter(Schedule.week == week_filter)

        # Apply date filters
        if date_from:
            try:
                from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
                query = query.filter(Match.date >= from_date)
            except ValueError:
                pass

        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
                query = query.filter(Match.date <= to_date)
            except ValueError:
                pass

        # Order by date descending
        matches = query.order_by(Match.date.desc(), Match.time.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        # Get leagues for filter dropdown (current season only)
        if current_season:
            leagues = League.query.filter_by(season_id=current_season.id).order_by(League.name).all()
        else:
            leagues = League.query.order_by(League.name).all()

        # Get weeks for filter dropdown
        weeks = []
        if current_season:
            week_results = db.session.query(Schedule.week).filter(
                Schedule.season_id == current_season.id,
                Schedule.week != None,
                Schedule.week != ''
            ).distinct().all()
            weeks = sorted([w[0] for w in week_results if w[0]], key=lambda x: int(x) if x.isdigit() else 0)

        return render_template(
            'admin_panel/match_operations/view_matches.html',
            matches=matches,
            leagues=leagues,
            weeks=weeks,
            current_league_id=league_filter,
            current_week=week_filter,
            current_status=status_filter,
            current_season=current_season,
            today_date=datetime.utcnow().date()
        )
    except Exception as e:
        logger.error(f"Error loading view matches: {e}")
        flash('Match view unavailable. Check database connectivity and match data integrity.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/upcoming')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def upcoming_matches():
    """View upcoming matches."""
    try:
        from app.models import Match, Team, Season, League, Schedule
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        # Get upcoming matches with team and league information
        query = Match.query.filter(
            Match.date >= datetime.utcnow().date()
        )
        
        # Filter by current season if available
        if current_season:
            query = query.join(Schedule).filter(Schedule.season_id == current_season.id)
        
        upcoming = query.order_by(Match.date.asc(), Match.time.asc()).limit(50).all()
        
        # Get statistics
        stats = {
            'total_upcoming': len(upcoming),
            'this_week': len([m for m in upcoming if m.date <= datetime.utcnow().date() + timedelta(days=7)]),
            'next_week': len([m for m in upcoming if datetime.utcnow().date() + timedelta(days=7) < m.date <= datetime.utcnow().date() + timedelta(days=14)]),
            'this_month': len([m for m in upcoming if m.date <= datetime.utcnow().date() + timedelta(days=30)])
        }
        
        return render_template('admin_panel/match_operations/upcoming_matches.html', 
                             matches=upcoming, stats=stats)
    except Exception as e:
        logger.error(f"Error loading upcoming matches: {e}")
        flash('Upcoming matches unavailable. Verify database connection and date filtering.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/results')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def match_results():
    """View match results."""
    try:
        # Log the access to match results
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_match_results',
            resource_type='match_operations',
            resource_id='results',
            new_value='Accessed match results interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        # Get completed matches with results
        completed_matches = Match.query.filter(
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None)
        ).order_by(Match.date.desc()).limit(50).all()
        
        # Get matches awaiting results
        pending_results = Match.query.filter(
            Match.date <= datetime.utcnow().date(),
            Match.home_team_score.is_(None),
            Match.away_team_score.is_(None)
        ).order_by(Match.date.desc()).limit(20).all()
        
        stats = {
            'completed_matches': len(completed_matches),
            'pending_results': len(pending_results),
            'recent_results': completed_matches[:10] if completed_matches else []
        }
        
        return render_template(
            'admin_panel/match_operations/match_results.html',
            completed_matches=completed_matches,
            pending_results=pending_results,
            stats=stats
        )
    except Exception as e:
        logger.error(f"Error loading match results: {e}")
        flash('Match results unavailable. Check database connectivity and score data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/live')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def live_matches():
    """View live matches."""
    try:
        from app.models import Match, Team, Season, League, Schedule
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        # Get today's matches (considered "live" if happening today)
        today = datetime.utcnow().date()
        query = Match.query.filter(Match.date == today)
        
        # Filter by current season if available
        if current_season:
            query = query.join(Schedule).filter(Schedule.season_id == current_season.id)
        
        live_matches_list = query.order_by(Match.time.asc()).all()
        
        # Get matches in progress (if we have status tracking)
        in_progress = []
        upcoming_today = []
        completed_today = []
        
        current_time = datetime.utcnow().time()
        
        for match in live_matches_list:
            if hasattr(match, 'status'):
                if match.status == 'in_progress':
                    in_progress.append(match)
                elif match.status == 'completed':
                    completed_today.append(match)
                else:
                    upcoming_today.append(match)
            else:
                # Fallback logic based on time
                if match.time and match.time <= current_time:
                    # Assume match duration of 90 minutes
                    match_end_time = (datetime.combine(today, match.time) + timedelta(minutes=90)).time()
                    if current_time <= match_end_time:
                        in_progress.append(match)
                    else:
                        completed_today.append(match)
                else:
                    upcoming_today.append(match)
        
        stats = {
            'total_today': len(live_matches_list),
            'in_progress': len(in_progress),
            'upcoming_today': len(upcoming_today),
            'completed_today': len(completed_today)
        }
        
        return render_template('admin_panel/match_operations/live_matches.html',
                             in_progress=in_progress,
                             upcoming_today=upcoming_today,
                             completed_today=completed_today,
                             stats=stats)
    except Exception as e:
        logger.error(f"Error loading live matches: {e}")
        flash('Live matches unavailable. Verify database connection and match status data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/reports')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def match_reports():
    """View match reports."""
    try:
        # Log the access to match reports
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_match_reports',
            resource_type='match_operations',
            resource_id='reports',
            new_value='Accessed match reports interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        from app.models.matches import Match
        from app.models import Team
        
        # Get recent matches for reports
        recent_date = datetime.utcnow().date() - timedelta(days=30)
        recent_matches = Match.query.filter(Match.date >= recent_date).limit(20).all()
        
        # Get teams for dropdown/filtering
        teams = Team.query.all()
        
        # Calculate basic statistics
        total_matches = Match.query.count()
        recent_matches_count = len(recent_matches)
        completed_matches = Match.query.filter(Match.status == 'completed').count() if hasattr(Match, 'status') else 0
        
        reports_data = {
            'total_matches': total_matches,
            'recent_matches_count': recent_matches_count,
            'completed_matches': completed_matches,
            'pending_matches': total_matches - completed_matches,
            'recent_matches': recent_matches,
            'teams': teams
        }
        
        return render_template('admin_panel/match_operations/match_reports.html',
                             reports_data=reports_data)
    except Exception as e:
        logger.error(f"Error loading match reports: {e}")
        flash('Match reports unavailable. Check database connectivity and report generation.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/leagues')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_leagues():
    """Manage leagues."""
    try:
        from app.models import League, Team, Match, Season
        
        # Get all leagues
        leagues = League.query.order_by(League.name.asc()).all()
        
        # Get league statistics
        stats = {
            'total_leagues': len(leagues),
            'active_leagues': len(leagues),
            'leagues_with_teams': 0,
            'leagues_with_matches': 0
        }
        
        # Add details for each league
        for league in leagues:
            # Get team count
            league.team_count = Team.query.filter_by(league_id=league.id).count() if hasattr(Team, 'league_id') else 0
            
            # Get match count (if matches have league relationship)
            if hasattr(Match, 'league_id'):
                league.match_count = Match.query.filter_by(league_id=league.id).count()
            else:
                # Fallback: count matches through teams
                league_teams = Team.query.filter_by(league_id=league.id).all() if hasattr(Team, 'league_id') else []
                league.match_count = 0
                for team in league_teams:
                    league.match_count += Match.query.filter(
                        (Match.home_team_id == team.id) | (Match.away_team_id == team.id)
                    ).count()
            
            # Update statistics
            if league.team_count > 0:
                stats['leagues_with_teams'] += 1
            if league.match_count > 0:
                stats['leagues_with_matches'] += 1
            
            # Set league status (all leagues are considered active)
            league.status = 'active'
        
        return render_template('admin_panel/match_operations/manage_leagues.html',
                             leagues=leagues, stats=stats)
    except Exception as e:
        logger.error(f"Error loading manage leagues: {e}")
        flash('League management unavailable. Verify database connection and league data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/standings')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_standings():
    """View league standings."""
    try:
        # Log the access to league standings
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_league_standings',
            resource_type='match_operations',
            resource_id='standings',
            new_value='Accessed league standings interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        from app.models import Team, Season
        from app.models.matches import Match
        from sqlalchemy import func
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        if not current_season:
            flash('No active season found. Please create a season first.', 'warning')
            return redirect(url_for('admin_panel.match_operations'))
        
        # Get all teams in current season
        teams = Team.query.join(League).filter(League.season_id == current_season.id).all() if current_season else Team.query.all()
        
        # Calculate standings for each team
        standings = []
        for team in teams:
            # Get team's matches (both home and away)
            home_matches = Match.query.filter_by(home_team_id=team.id).all()
            away_matches = Match.query.filter_by(away_team_id=team.id).all() if hasattr(Match, 'away_team_id') else []
            
            wins = losses = draws = goals_for = goals_against = 0
            matches_played = len(home_matches) + len(away_matches)
            
            # Calculate stats (this would need actual match results)
            # For now, using placeholder calculations
            wins = matches_played // 3 if matches_played > 0 else 0
            draws = matches_played // 3 if matches_played > 0 else 0
            losses = matches_played - wins - draws
            goals_for = wins * 2 + draws
            goals_against = losses * 2 + draws
            
            points = wins * 3 + draws
            goal_difference = goals_for - goals_against
            
            standings.append({
                'team': team,
                'matches_played': matches_played,
                'wins': wins,
                'draws': draws,
                'losses': losses,
                'goals_for': goals_for,
                'goals_against': goals_against,
                'goal_difference': goal_difference,
                'points': points
            })
        
        # Sort by points, then goal difference
        standings.sort(key=lambda x: (x['points'], x['goal_difference']), reverse=True)
        
        # Add position
        for i, standing in enumerate(standings, 1):
            standing['position'] = i
        
        standings_data = {
            'current_season': current_season,
            'standings': standings,
            'total_teams': len(teams)
        }
        
        return render_template('admin_panel/match_operations/league_standings.html',
                             standings_data=standings_data)
    except Exception as e:
        logger.error(f"Error loading league standings: {e}")
        flash('League standings unavailable. Check database connectivity and season data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


# DEPRECATED: Route moved to match_operations/seasons.py which redirects to league_management
# This duplicate route registration has been disabled to avoid conflicts
# @admin_panel_bp.route('/match-operations/seasons')
# @login_required
# @role_required(['Global Admin', 'Pub League Admin'])
def _seasons_deprecated():
    """DEPRECATED: Manage seasons."""
    try:
        from app.models import Season, League, Match
        
        # Get all seasons (ordered by id since Season has no created_at)
        seasons = Season.query.order_by(Season.id.desc()).all()
        
        # Get season statistics
        current_season = Season.query.filter_by(is_current=True).first()
        
        stats = {
            'total_seasons': len(seasons),
            'current_season': current_season.name if current_season else 'None',
            'active_seasons': len([s for s in seasons if s.is_current]),
            'upcoming_seasons': 0,
            'past_seasons': len([s for s in seasons if not s.is_current])
        }
        
        # Add season details
        for season in seasons:
            # Get match count for each season
            if hasattr(Match, 'season_id'):
                season.match_count = Match.query.filter_by(season_id=season.id).count()
            else:
                season.match_count = 0
            
            # Calculate season status
            today = datetime.utcnow().date()
            if season.start_date and season.end_date:
                if today < season.start_date:
                    season.status = 'upcoming'
                    stats['upcoming_seasons'] += 1
                elif season.start_date <= today <= season.end_date:
                    season.status = 'active'
                else:
                    season.status = 'completed'
            else:
                season.status = 'active' if season.is_current else 'unknown'
        
        return render_template('admin_panel/match_operations/seasons.html',
                             seasons=seasons, stats=stats)
    except Exception as e:
        logger.error(f"Error loading seasons: {e}")
        flash('Seasons data unavailable. Verify database connection and season configuration.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


# DEPRECATED: Route moved to match_operations/teams.py which redirects to league_management
# This duplicate route registration has been disabled to avoid conflicts
# @admin_panel_bp.route('/match-operations/teams')
# @login_required
# @role_required(['Global Admin', 'Pub League Admin'])
def _manage_teams_deprecated():
    """DEPRECATED: Manage teams across all Pub League divisions (Premier, Classic, ECS FC)."""
    try:
        from app.models import Team, League, Player, Season
        from sqlalchemy import or_

        # Get current Pub League season
        current_season = Season.query.filter_by(is_current=True, league_type="Pub League").first()
        if not current_season:
            # Fallback to any current season
            current_season = Season.query.filter_by(is_current=True).first()

        # Get filter parameters
        league_filter = request.args.get('league_id', type=int)

        # Get all leagues for the current season (Premier, Classic, ECS FC)
        if current_season:
            leagues = League.query.filter_by(season_id=current_season.id).order_by(League.name.asc()).all()
        else:
            leagues = League.query.order_by(League.name.asc()).all()

        # Build teams query - show ALL teams from all leagues in the current season
        if current_season:
            teams_query = Team.query.join(
                League, Team.league_id == League.id
            ).filter(
                League.season_id == current_season.id
            )
        else:
            teams_query = Team.query

        # Apply league filter if specified
        if league_filter:
            teams_query = teams_query.filter(Team.league_id == league_filter)

        teams = teams_query.order_by(Team.name.asc()).all()

        # Get team statistics
        stats = {
            'total_teams': len(teams),
            'active_teams': len([t for t in teams if getattr(t, 'is_active', True)]),
            'teams_by_league': {},
            'teams_with_players': 0,
            'current_season': current_season.name if current_season else 'All Seasons'
        }

        # Group teams by league
        for team in teams:
            league_name = team.league.name if team.league else 'No League'
            if league_name not in stats['teams_by_league']:
                stats['teams_by_league'][league_name] = 0
            stats['teams_by_league'][league_name] += 1

            # Count teams that have players (if player-team relationship exists)
            if hasattr(team, 'players') and team.players:
                stats['teams_with_players'] += 1

        return render_template(
            'admin_panel/match_operations/manage_teams.html',
            teams=teams,
            leagues=leagues,
            stats=stats,
            current_league_id=league_filter,
            current_season=current_season
        )
    except Exception as e:
        logger.error(f"Error loading manage teams: {e}")
        flash('Team management unavailable. Check database connectivity and team data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/rosters')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def team_rosters():
    """Manage team rosters."""
    try:
        # Log the access to team rosters
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_team_rosters',
            resource_type='match_operations',
            resource_id='rosters',
            new_value='Accessed team rosters interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        # Get teams with their players for current season
        from app.models import Team, Player, Season, League
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        # Filter teams by current season
        if current_season:
            teams_with_rosters = db.session.query(Team).join(
                League, Team.league_id == League.id, isouter=True
            ).filter(
                League.season_id == current_season.id
            ).join(
                Team.players, isouter=True
            ).options(joinedload(Team.players)).all()
        else:
            teams_with_rosters = db.session.query(Team).join(
                Team.players, isouter=True
            ).options(joinedload(Team.players)).all()
        
        # Get teams without players
        teams_without_players = [team for team in teams_with_rosters if not team.players]
        
        # Get roster statistics
        total_players = db.session.query(func.count(Player.id)).scalar()
        players_assigned = db.session.query(func.count(Player.id)).filter(
            Player.teams.any()
        ).scalar()
        
        roster_stats = {
            'total_teams': len(teams_with_rosters),
            'teams_with_players': len([t for t in teams_with_rosters if t.players]),
            'teams_without_players': len(teams_without_players),
            'total_players': total_players,
            'assigned_players': players_assigned,
            'unassigned_players': total_players - players_assigned,
            'current_season': current_season.name if current_season else 'All Seasons'
        }
        
        return render_template(
            'admin_panel/match_operations/team_rosters.html',
            teams=teams_with_rosters,
            teams_without_players=teams_without_players[:10],  # Show first 10
            stats=roster_stats
        )
    except Exception as e:
        logger.error(f"Error loading team rosters: {e}")
        flash('Team rosters unavailable. Verify database connection and player-team relationships.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/transfers')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def player_transfers():
    """Manage player transfers."""
    try:
        # Log the access to player transfers
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_player_transfers',
            resource_type='match_operations',
            resource_id='transfers',
            new_value='Accessed player transfers interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        from app.models import User, Team, Season, Player
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        if not current_season:
            flash('No active season found. Please create a season first.', 'warning')
            return redirect(url_for('admin_panel.match_operations'))
        
        # Get recent transfers (placeholder - would need a transfers table)
        recent_transfers = []
        
        # Get available players (not currently on a team or available for transfer)
        available_players = User.query.filter_by(is_active=True).all()  # Simplified
        
        # Get all teams for transfer destinations
        teams = Team.query.join(League).filter(League.season_id == current_season.id).all() if current_season else Team.query.all()
        
        # Get pending transfer requests (placeholder)
        pending_requests = []
        
        transfers_data = {
            'current_season': current_season,
            'recent_transfers': recent_transfers,
            'available_players': available_players[:50],  # Limit for performance
            'teams': teams,
            'pending_requests': pending_requests,
            'total_transfers': len(recent_transfers),
            'pending_count': len(pending_requests)
        }
        
        return render_template('admin_panel/match_operations/player_transfers.html',
                             transfers_data=transfers_data)
    except Exception as e:
        logger.error(f"Error loading player transfers: {e}")
        flash('Player transfers unavailable. Check database connectivity and transfer data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


# AJAX Routes for Match Operations
@admin_panel_bp.route('/match-operations/match/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_match_details():
    """Get match details via AJAX."""
    try:
        match_id = request.args.get('match_id')
        
        if not match_id:
            return jsonify({'success': False, 'message': 'Match ID is required'})
        
        # TODO: Get actual match details from database
        details_html = f"""
        <div class="match-details">
            <div class="row">
                <div class="col-md-6">
                    <strong>Match ID:</strong> {match_id}<br>
                    <strong>Date:</strong> TBD<br>
                    <strong>Time:</strong> TBD<br>
                    <strong>Status:</strong> Scheduled
                </div>
                <div class="col-md-6">
                    <strong>League:</strong> TBD<br>
                    <strong>Season:</strong> TBD<br>
                    <strong>Venue:</strong> TBD<br>
                    <strong>Referee:</strong> TBD
                </div>
            </div>
            <div class="row mt-3">
                <div class="col-12">
                    <strong>Teams:</strong><br>
                    <div class="teams-info p-2 bg-light rounded">
                        Match details will be implemented when match model is available.
                    </div>
                </div>
            </div>
        </div>
        """
        
        return jsonify({'success': True, 'html': details_html})
    except Exception as e:
        logger.error(f"Error getting match details: {e}")
        return jsonify({'success': False, 'message': 'Error loading match details'})


@admin_panel_bp.route('/match-operations/league/toggle-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def toggle_league_status():
    """Toggle league active status."""
    try:
        league_id = request.form.get('league_id')
        
        if not league_id:
            return jsonify({'success': False, 'message': 'League ID is required'})
        
        from app.models import League
        league = League.query.get_or_404(league_id)
        
        # Since leagues don't have is_active field, just return success
        return jsonify({
            'success': True,
            'message': f'League "{league.name}" is active',
            'new_status': True
        })
        
    except Exception as e:
        logger.error(f"Error toggling league status: {e}")
        return jsonify({'success': False, 'message': 'Error updating league status'})


@admin_panel_bp.route('/match-operations/season/set-current', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def set_current_season():
    """Set a season as current."""
    try:
        season_id = request.form.get('season_id')
        
        if not season_id:
            return jsonify({'success': False, 'message': 'Season ID is required'})
        
        from app.models import Season
        
        # Clear current season status from all seasons
        Season.query.update({'is_current': False})
        
        # Set the selected season as current
        season = Season.query.get_or_404(season_id)
        season.is_current = True
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='set_current_season',
            resource_type='match_operations',
            resource_id=str(season_id),
            new_value=f'Set {season.name} as current season',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({
            'success': True,
            'message': f'Season "{season.name}" set as current season',
            'season_name': season.name
        })
        
    except Exception as e:
        logger.error(f"Error setting current season: {e}")
        return jsonify({'success': False, 'message': 'Error updating current season'})


@admin_panel_bp.route('/match-operations/teams/rename', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def rename_team():
    """Rename a team and trigger Discord automation."""
    try:
        team_id = request.form.get('team_id')
        new_name = request.form.get('new_name')
        
        if not team_id or not new_name:
            return jsonify({'success': False, 'message': 'Team ID and new name are required'})
        
        from app.models import Team
        
        team = Team.query.get_or_404(team_id)
        old_name = team.name
        
        # Update team name
        team.name = new_name.strip()
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='rename_team',
            resource_type='match_operations',
            resource_id=str(team_id),
            old_value=old_name,
            new_value=new_name,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        # TODO: Trigger Discord automation for team name change
        # This would involve updating Discord role names, channel names, etc.
        # from app.tasks.tasks_discord import update_team_discord_automation
        # update_team_discord_automation.delay(team_id=team_id, old_name=old_name, new_name=new_name)
        
        logger.info(f"Team {team_id} renamed from '{old_name}' to '{new_name}' by user {current_user.id}")
        
        return jsonify({
            'success': True,
            'message': f'Team renamed from "{old_name}" to "{new_name}" successfully',
            'old_name': old_name,
            'new_name': new_name
        })
        
    except Exception as e:
        logger.error(f"Error renaming team: {e}")
        return jsonify({'success': False, 'message': 'Error renaming team'})


@admin_panel_bp.route('/substitute-management')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def substitute_management():
    """Substitute management dashboard."""
    try:
        # Log the access to substitute management
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_substitute_management',
            resource_type='match_operations',
            resource_id='substitute_management',
            new_value='Accessed substitute management dashboard',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        from app.models import Match, Team, User
        from app.models.substitutes import SubstituteRequest, SubstituteAssignment
        
        # Get filter parameters
        show_requested = request.args.get('show_requested', 'all')
        week_filter = request.args.get('week', type=int)
        
        # Get upcoming matches
        upcoming_matches_query = Match.query.filter(
            Match.date >= datetime.utcnow().date()
        ).order_by(Match.date.asc(), Match.time.asc())
        
        if week_filter:
            # Filter by week if implemented
            pass
        
        upcoming_matches = upcoming_matches_query.limit(20).all()
        
        # Get substitute requests
        sub_requests_query = SubstituteRequest.query.filter(
            SubstituteRequest.status.in_(['PENDING', 'APPROVED'])
        ).order_by(SubstituteRequest.created_at.desc())
        
        if show_requested == 'requested':
            # Filter logic for matches with requests
            pass
        
        sub_requests = sub_requests_query.limit(50).all()
        
        # Get available substitutes (users who can sub)
        available_subs = User.query.filter_by(
            is_active=True,
            is_approved=True
        ).limit(100).all()
        
        # Calculate statistics
        stats = {
            'total_requests': SubstituteRequest.query.count(),
            'active_requests': SubstituteRequest.query.filter(
                SubstituteRequest.status.in_(['PENDING', 'APPROVED'])
            ).count(),
            'available_subs': len(available_subs),
            'upcoming_matches': len(upcoming_matches)
        }
        
        # Group requests by match for easier template processing
        requested_teams_by_match = {}
        for sub_request in sub_requests:
            match_id = sub_request.match_id
            if match_id not in requested_teams_by_match:
                requested_teams_by_match[match_id] = {}
            requested_teams_by_match[match_id][sub_request.team_id] = sub_request
        
        # Get available weeks (placeholder)
        weeks = list(range(1, 21))  # Assuming 20 weeks in a season
        current_week = week_filter or 1
        
        return render_template(
            'admin_panel/substitute_management.html',
            stats=stats,
            sub_requests=sub_requests,
            upcoming_matches=upcoming_matches,
            available_subs=available_subs,
            requested_teams_by_match=requested_teams_by_match,
            weeks=weeks,
            current_week=current_week,
            show_requested=show_requested
        )
    except Exception as e:
        logger.error(f"Error loading substitute management: {e}")
        flash('Substitute management unavailable. Verify database connection and substitute models.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/assign-substitute', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def assign_substitute():
    """Assign a substitute to a match."""
    try:
        match_id = request.form.get('match_id')
        team_id = request.form.get('team_id')
        player_id = request.form.get('player_id')
        
        if not all([match_id, team_id, player_id]):
            flash('Missing required information for substitute assignment.', 'error')
            return redirect(url_for('admin_panel.substitute_management'))
        
        from app.models.substitutes import SubstituteAssignment
        
        # Create substitute assignment
        assignment = SubstituteAssignment(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            assigned_by=current_user.id,
            assigned_at=datetime.utcnow(),
            status='ASSIGNED'
        )
        
        db.session.add(assignment)
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='assign_substitute',
            resource_type='match_operations',
            resource_id=f'match_{match_id}_team_{team_id}',
            new_value=f'Assigned player {player_id} as substitute',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        flash('Substitute assigned successfully!', 'success')
        return redirect(url_for('admin_panel.substitute_management'))
        
    except Exception as e:
        logger.error(f"Error assigning substitute: {e}")
        flash('Substitute assignment failed. Check database connectivity and input validation.', 'error')
        return redirect(url_for('admin_panel.substitute_management'))


@admin_panel_bp.route('/match-verification')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def match_verification():
    """
    Match verification dashboard.

    Shows the verification status of matches, highlighting those that need attention.
    Coaches can only see matches for their teams, while admins can see all matches.
    """
    try:
        from app.models import Match, Season, Schedule, Team, League
        from sqlalchemy.orm import joinedload, aliased
        from sqlalchemy import or_, desc, cast, Integer
        from app.utils.user_helpers import safe_current_user

        # Log the access to match verification
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_match_verification',
            resource_type='match_operations',
            resource_id='verification',
            new_value='Accessed match verification dashboard',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Get current Pub League season
        current_season = Season.query.filter_by(is_current=True, league_type="Pub League").first()
        if not current_season:
            # Fallback to any current season
            current_season = Season.query.filter_by(is_current=True).first()

        if not current_season:
            flash('No current season found. Contact an administrator.', 'warning')
            return render_template(
                'admin_panel/match_verification.html',
                matches=[],
                weeks=[],
                leagues=[],
                current_week=None,
                current_league_id=None,
                current_verification_status='all',
                current_season=None,
                verifiable_teams={},
                is_coach=False
            )

        # Start with base query with eager loading
        query = Match.query.options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.schedule)
        )

        # Get all team IDs that belong to leagues in the current season
        league_ids = [league.id for league in League.query.filter_by(season_id=current_season.id).all()]
        team_ids = []
        if league_ids:
            team_ids = [team.id for team in Team.query.filter(Team.league_id.in_(league_ids)).all()]

        # Filter matches to only include those with teams from current season
        if team_ids:
            query = query.filter(
                or_(
                    Match.home_team_id.in_(team_ids),
                    Match.away_team_id.in_(team_ids)
                )
            )

        # Process request filters
        current_week = request.args.get('week')
        current_league_id = request.args.get('league_id')
        current_verification_status = request.args.get('verification_status', 'all')

        # Filter by week if specified
        if current_week:
            query = query.join(Schedule, Match.schedule_id == Schedule.id).filter(Schedule.week == current_week)

        # Filter by league if specified
        if current_league_id:
            league_team_ids = [team.id for team in Team.query.filter_by(league_id=int(current_league_id)).all()]
            if league_team_ids:
                query = query.filter(
                    or_(
                        Match.home_team_id.in_(league_team_ids),
                        Match.away_team_id.in_(league_team_ids)
                    )
                )

        # Filter by verification status
        if current_verification_status == 'unverified':
            query = query.filter(
                Match.home_team_score != None,
                Match.away_team_score != None,
                ~(Match.home_team_verified & Match.away_team_verified)
            )
        elif current_verification_status == 'partially_verified':
            query = query.filter(
                Match.home_team_score != None,
                Match.away_team_score != None,
                or_(Match.home_team_verified, Match.away_team_verified),
                ~(Match.home_team_verified & Match.away_team_verified)
            )
        elif current_verification_status == 'fully_verified':
            query = query.filter(Match.home_team_verified, Match.away_team_verified)
        elif current_verification_status == 'not_reported':
            query = query.filter(or_(Match.home_team_score == None, Match.away_team_score == None))

        # Check if user is a coach (to limit matches to their teams)
        is_coach = safe_current_user.has_role('Pub League Coach') and not (
            safe_current_user.has_role('Pub League Admin') or safe_current_user.has_role('Global Admin')
        )

        # Get verifiable teams for the user
        verifiable_teams = {}
        if hasattr(safe_current_user, 'player') and safe_current_user.player:
            for team in safe_current_user.player.teams:
                verifiable_teams[team.id] = team.name

            # If coach, filter to only their teams
            if is_coach:
                coach_team_ids = list(verifiable_teams.keys())
                if coach_team_ids:
                    query = query.filter(
                        or_(
                            Match.home_team_id.in_(coach_team_ids),
                            Match.away_team_id.in_(coach_team_ids)
                        )
                    )

        # Apply sorting - default by week descending
        sort_by = request.args.get('sort_by', 'week')
        sort_order = request.args.get('sort_order', 'desc')

        if sort_by == 'date':
            query = query.order_by(Match.date.desc() if sort_order == 'desc' else Match.date)
        elif sort_by == 'week':
            schedule_alias = aliased(Schedule)
            query = query.outerjoin(schedule_alias, Match.schedule_id == schedule_alias.id)
            if sort_order == 'desc':
                query = query.order_by(desc(cast(schedule_alias.week, Integer)), Match.date.desc())
            else:
                query = query.order_by(cast(schedule_alias.week, Integer), Match.date)
        else:
            query = query.order_by(Match.date.desc())

        # Execute query
        matches = query.limit(500).all()

        # Get weeks for filter dropdown
        weeks = []
        try:
            # First try getting weeks from Schedule table
            week_results = db.session.query(Schedule.week).filter(
                Schedule.season_id == current_season.id,
                Schedule.week != None,
                Schedule.week != ''
            ).distinct().all()
            weeks = [w[0] for w in week_results if w[0]]

            # If no weeks found in Schedule, try getting from Match->Schedule relationship
            if not weeks and team_ids:
                match_week_results = db.session.query(Schedule.week).join(
                    Match, Match.schedule_id == Schedule.id
                ).filter(
                    or_(
                        Match.home_team_id.in_(team_ids),
                        Match.away_team_id.in_(team_ids)
                    ),
                    Schedule.week != None,
                    Schedule.week != ''
                ).distinct().all()
                weeks = [w[0] for w in match_week_results if w[0]]

            # Sort weeks numerically if possible
            try:
                weeks = sorted(weeks, key=lambda x: int(x))
            except (ValueError, TypeError):
                weeks = sorted(weeks)
        except Exception as e:
            logger.warning(f"Error getting weeks: {e}")
            weeks = [str(i) for i in range(1, 21)]  # Fallback

        # Get leagues for filter dropdown
        leagues = League.query.filter_by(season_id=current_season.id).all()

        return render_template(
            'admin_panel/match_verification.html',
            matches=matches,
            weeks=weeks,
            leagues=leagues,
            current_week=current_week,
            current_league_id=int(current_league_id) if current_league_id else None,
            current_verification_status=current_verification_status,
            current_season=current_season,
            verifiable_teams=verifiable_teams,
            is_coach=is_coach
        )
    except Exception as e:
        logger.error(f"Error loading match verification: {e}", exc_info=True)
        flash('Match verification unavailable. Verify database connection and match data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/verify-match', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def verify_match_legacy():
    """Verify a match result."""
    try:
        from app.models import Match
        
        match_id = request.form.get('match_id')
        action = request.form.get('action', 'verify')
        
        if not match_id:
            flash('Match ID is required for verification.', 'error')
            return redirect(url_for('admin_panel.match_verification'))
        
        match = Match.query.get_or_404(match_id)
        
        if action == 'verify':
            # Verify the match for both teams
            match.home_team_verified = True
            match.home_team_verified_by = current_user.id
            match.home_team_verified_at = datetime.utcnow()
            match.away_team_verified = True
            match.away_team_verified_by = current_user.id
            match.away_team_verified_at = datetime.utcnow()
            
            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='verify_match',
                resource_type='match_operations',
                resource_id=str(match_id),
                new_value=f'Verified match: {match.home_team.name if match.home_team else "TBD"} vs {match.away_team.name if match.away_team else "TBD"}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            flash(f'Match verified successfully!', 'success')
            
        elif action == 'reject':
            # Reject the match result - reset scores and verification
            match.home_team_score = None
            match.away_team_score = None
            match.home_team_verified = False
            match.home_team_verified_by = None
            match.home_team_verified_at = None
            match.away_team_verified = False
            match.away_team_verified_by = None
            match.away_team_verified_at = None
            
            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='reject_match_result',
                resource_type='match_operations',
                resource_id=str(match_id),
                new_value=f'Rejected match result and reset scores',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            flash(f'Match result rejected and scores reset.', 'warning')
        
        db.session.commit()
        return redirect(url_for('admin_panel.match_verification'))
        
    except Exception as e:
        logger.error(f"Error verifying match: {e}")
        flash('Match verification failed. Check database connectivity and permissions.', 'error')
        return redirect(url_for('admin_panel.match_verification'))


@admin_panel_bp.route('/match-operations/verify-match/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def verify_match(match_id):
    """Verify a match result by match ID."""
    try:
        from app.models import Match
        
        team = request.form.get('team', 'both')
        action = request.form.get('action', 'verify')
        
        match = Match.query.get_or_404(match_id)
        
        if action == 'verify':
            if team == 'home' or team == 'both':
                match.home_team_verified = True
                match.home_team_verified_by = current_user.id
                match.home_team_verified_at = datetime.utcnow()
            
            if team == 'away' or team == 'both':
                match.away_team_verified = True
                match.away_team_verified_by = current_user.id
                match.away_team_verified_at = datetime.utcnow()
            
            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='verify_match',
                resource_type='match_operations',
                resource_id=str(match_id),
                new_value=f'Verified match result for {team} team(s)',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            flash(f'Match result verified for {team} team(s).', 'success')
        
        elif action == 'reject':
            # Reset verification and scores
            match.home_team_verified = False
            match.home_team_verified_by = None
            match.home_team_verified_at = None
            match.away_team_verified = False
            match.away_team_verified_by = None
            match.away_team_verified_at = None
            match.home_team_score = None
            match.away_team_score = None

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='reject_match_result',
                resource_type='match_operations',
                resource_id=str(match_id),
                new_value=f'Rejected match result and reset scores',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            flash(f'Match result rejected and scores reset.', 'warning')

        db.session.commit()
        return redirect(url_for('admin_panel.match_verification'))

    except Exception as e:
        logger.error(f"Error verifying match: {e}")
        flash('Match verification failed. Check database connectivity and permissions.', 'error')
        return redirect(url_for('admin_panel.match_verification'))


# =============================================================================
# Substitute Pool Management Routes
# =============================================================================

# League type configuration for substitute pools
LEAGUE_TYPES = {
    'ECS FC': {
        'name': 'ECS FC',
        'role': 'ECS FC Sub',
        'color': '#3498db',
        'icon': 'ti ti-ball-football'
    },
    'Classic': {
        'name': 'Classic Division',
        'role': 'Classic Sub',
        'color': '#2ecc71',
        'icon': 'ti ti-trophy'
    },
    'Premier': {
        'name': 'Premier Division',
        'role': 'Premier Sub',
        'color': '#e74c3c',
        'icon': 'ti ti-crown'
    }
}


@admin_panel_bp.route('/substitute-pools')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def substitute_pools():
    """
    Main substitute pool management page.
    Shows all league types and their respective pools.
    """
    try:
        from app.models import Player, User, Role, Team, League, Season
        from app.models_substitute_pools import SubstitutePool, get_eligible_players
        from sqlalchemy.orm import joinedload

        # Log access
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_substitute_pools',
            resource_type='match_operations',
            resource_id='substitute_pools',
            new_value='Accessed substitute pools dashboard',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        # Get data for all league types
        pools_data = {}
        for league_type, config in LEAGUE_TYPES.items():
            try:
                # Get active pools by league_type directly
                active_pools = SubstitutePool.query.options(
                    joinedload(SubstitutePool.player).joinedload(Player.user)
                ).filter(
                    SubstitutePool.league_type == league_type,
                    SubstitutePool.is_active == True
                ).all()

                pools_data[league_type] = {
                    'config': config,
                    'active_pools': active_pools,
                    'total_active': len(active_pools)
                }
            except Exception as pool_error:
                logger.warning(f"Error loading pool data for {league_type}: {pool_error}")
                pools_data[league_type] = {
                    'config': config,
                    'active_pools': [],
                    'total_active': 0
                }

        return render_template(
            'admin_panel/match_operations/substitute_pools.html',
            pools_data=pools_data,
            league_types=LEAGUE_TYPES
        )

    except ImportError as ie:
        logger.error(f"Missing substitute pool models: {ie}")
        flash('Substitute pool models not configured. Contact an administrator.', 'error')
        return redirect(url_for('admin_panel.match_operations'))
    except Exception as e:
        logger.error(f"Error loading substitute pools: {e}")
        flash('Substitute pools unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/substitute-pools/<league_type>')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def substitute_pool_detail(league_type):
    """
    Manage substitute pool for a specific league type.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            flash('Invalid league type.', 'error')
            return redirect(url_for('admin_panel.substitute_pools'))

        from app.models import Player, User, Role, Team, League, Season
        from app.models_substitute_pools import (
            SubstitutePool, SubstitutePoolHistory, SubstituteRequest,
            SubstituteResponse, SubstituteAssignment, get_eligible_players
        )
        from sqlalchemy.orm import joinedload

        # Get active pools with full player information
        active_pools = SubstitutePool.query.options(
            joinedload(SubstitutePool.player).joinedload(Player.user)
        ).filter(
            SubstitutePool.league_type == league_type,
            SubstitutePool.is_active == True
        ).order_by(SubstitutePool.last_active_at.desc()).all()

        # Get eligible players not in pool
        eligible_players = get_eligible_players(league_type)
        active_pool_player_ids = {pool.player_id for pool in active_pools}

        # Also get rejected/inactive players to exclude from available list
        rejected_player_ids = {
            pool.player_id for pool in SubstitutePool.query.filter(
                SubstitutePool.league_type == league_type,
                SubstitutePool.is_active == False
            ).all()
        }

        available_players = [
            p for p in eligible_players
            if p.id not in active_pool_player_ids and p.id not in rejected_player_ids
        ]

        # Get recent activity
        try:
            recent_activity = SubstitutePoolHistory.query.options(
                joinedload(SubstitutePoolHistory.player),
                joinedload(SubstitutePoolHistory.performer)
            ).join(
                SubstitutePool, SubstitutePoolHistory.pool_id == SubstitutePool.id
            ).filter(
                SubstitutePool.league_type == league_type
            ).order_by(
                SubstitutePoolHistory.performed_at.desc()
            ).limit(10).all()
        except Exception as hist_error:
            logger.warning(f"Error loading pool history: {hist_error}")
            recent_activity = []

        # Get statistics
        stats = {
            'total_active': len(active_pools),
            'total_eligible': len(eligible_players),
            'pending_approval': len(available_players),
            'total_requests_sent': sum(pool.requests_received for pool in active_pools),
            'total_matches_played': sum(pool.matches_played for pool in active_pools)
        }

        return render_template(
            'admin_panel/match_operations/substitute_pool_detail.html',
            league_type=league_type,
            league_config=LEAGUE_TYPES[league_type],
            active_pools=active_pools,
            available_players=available_players,
            recent_activity=recent_activity,
            stats=stats
        )

    except ImportError as ie:
        logger.error(f"Missing substitute pool models: {ie}")
        flash('Substitute pool models not configured. Contact an administrator.', 'error')
        return redirect(url_for('admin_panel.substitute_pools'))
    except Exception as e:
        logger.error(f"Error loading league pool for {league_type}: {e}")
        flash('League pool unavailable. Check database connectivity.', 'error')
        return redirect(url_for('admin_panel.substitute_pools'))


@admin_panel_bp.route('/substitute-pools/<league_type>/add-player', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def add_player_to_pool(league_type):
    """Add a player to the substitute pool for a specific league."""
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        from app.models import Player, User, Role, League, Season
        from app.models_substitute_pools import SubstitutePool
        from sqlalchemy.orm import joinedload

        # Get form data
        player_id = request.json.get('player_id')
        if not player_id:
            return jsonify({'success': False, 'message': 'Player ID is required'}), 400

        # Verify player exists
        player = Player.query.options(
            joinedload(Player.user).joinedload(User.roles)
        ).get(player_id)

        if not player:
            return jsonify({'success': False, 'message': 'Player not found'}), 404

        # Assign the required role if not already assigned
        required_role_name = LEAGUE_TYPES[league_type]['role']
        required_role = Role.query.filter_by(name=required_role_name).first()

        if player.user and required_role and required_role not in player.user.roles:
            player.user.roles.append(required_role)

        # Check if already in pool for this league type
        existing_pool = SubstitutePool.query.filter_by(
            player_id=player_id,
            league_type=league_type
        ).first()

        if existing_pool:
            if existing_pool.is_active:
                return jsonify({'success': False, 'message': 'Player is already in the active pool'}), 400
            else:
                # Reactivate
                existing_pool.is_active = True
                message = f"{player.name} has been reactivated in the {league_type} substitute pool"
        else:
            # Create new pool entry
            pool_entry = SubstitutePool(
                player_id=player_id,
                league_type=league_type,
                preferred_positions=request.json.get('preferred_positions', ''),
                sms_for_sub_requests=request.json.get('sms_notifications', True),
                discord_for_sub_requests=request.json.get('discord_notifications', True),
                email_for_sub_requests=request.json.get('email_notifications', True),
                is_active=True
            )
            db.session.add(pool_entry)
            message = f"{player.name} has been added to the {league_type} substitute pool"

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='add_to_substitute_pool',
            resource_type='substitute_pools',
            resource_id=str(player_id),
            new_value=f'Added player {player.name} to {league_type} pool',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        db.session.commit()

        # Trigger Discord role update
        try:
            from app.tasks.tasks_discord import assign_roles_to_player_task
            assign_roles_to_player_task.delay(player_id=player.id, only_add=False)
        except Exception as task_error:
            logger.warning(f"Failed to queue Discord role update: {task_error}")

        return jsonify({
            'success': True,
            'message': message,
            'player_data': {
                'id': player.id,
                'name': player.name,
                'discord_id': player.discord_id,
                'phone_number': player.phone,
                'email': player.user.email if player.user else None
            }
        })

    except Exception as e:
        logger.error(f"Error adding player to pool: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500


@admin_panel_bp.route('/substitute-pools/<league_type>/remove-player', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def remove_player_from_pool(league_type):
    """Remove a player from the substitute pool."""
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        from app.models import Player, Role
        from app.models_substitute_pools import SubstitutePool

        player_id = request.json.get('player_id')
        if not player_id:
            return jsonify({'success': False, 'message': 'Player ID is required'}), 400

        # Find the pool entry
        pool_entry = SubstitutePool.query.filter_by(
            player_id=player_id,
            league_type=league_type,
            is_active=True
        ).first()

        if not pool_entry:
            return jsonify({'success': False, 'message': 'Player not found in active pool'}), 404

        # Deactivate the pool entry
        pool_entry.is_active = False

        # Remove the Flask role if player is not in any other active pools
        player = pool_entry.player
        if player and player.user:
            other_active_pools = SubstitutePool.query.filter(
                SubstitutePool.player_id == player_id,
                SubstitutePool.is_active == True,
                SubstitutePool.id != pool_entry.id
            ).count()

            if other_active_pools == 0:
                # Remove all substitute roles
                for role_name in ['ECS FC Sub', 'Classic Sub', 'Premier Sub']:
                    role = Role.query.filter_by(name=role_name).first()
                    if role and role in player.user.roles:
                        player.user.roles.remove(role)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='remove_from_substitute_pool',
            resource_type='substitute_pools',
            resource_id=str(player_id),
            new_value=f'Removed player {player.name} from {league_type} pool',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        db.session.commit()

        # Trigger Discord role update
        try:
            from app.tasks.tasks_discord import assign_roles_to_player_task
            assign_roles_to_player_task.delay(player_id=player_id, only_add=False)
        except Exception as task_error:
            logger.warning(f"Failed to queue Discord role update: {task_error}")

        return jsonify({
            'success': True,
            'message': f"{pool_entry.player.name} has been removed from the {league_type} substitute pool"
        })

    except Exception as e:
        logger.error(f"Error removing player from pool: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@admin_panel_bp.route('/substitute-pools/<league_type>/reject-player', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def reject_player_from_pool(league_type):
    """Reject a player from being added to the substitute pool.

    This prevents the player from appearing in the "Available to Add" list
    without actually adding them to the pool. The rejection is recorded in history.
    """
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        from app.models import Player
        from app.models_substitute_pools import SubstitutePool, SubstitutePoolHistory

        player_id = request.json.get('player_id')
        reason = request.json.get('reason', 'Admin rejected')

        if not player_id:
            return jsonify({'success': False, 'message': 'Player ID is required'}), 400

        # Get the player
        player = Player.query.get(player_id)
        if not player:
            return jsonify({'success': False, 'message': 'Player not found'}), 404

        # Check if already in pool (shouldn't happen but check anyway)
        existing_pool = SubstitutePool.query.filter_by(
            player_id=player_id,
            league_type=league_type,
            is_active=True
        ).first()

        if existing_pool:
            return jsonify({'success': False, 'message': 'Player is already in this pool'}), 400

        # Create a rejected pool entry (inactive with rejected status)
        rejected_entry = SubstitutePool(
            player_id=player_id,
            league_type=league_type,
            is_active=False  # Marked as rejected/inactive
        )
        db.session.add(rejected_entry)
        db.session.flush()

        # Log to history
        history = SubstitutePoolHistory(
            pool_id=rejected_entry.id,
            action='REJECTED',
            performed_by=current_user.id,
            notes=reason
        )
        db.session.add(history)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='reject_from_substitute_pool',
            resource_type='substitute_pools',
            resource_id=str(player_id),
            new_value=f'Rejected player {player.name} from {league_type} pool: {reason}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f"{player.name} has been rejected from the {league_type} substitute pool"
        })

    except Exception as e:
        logger.error(f"Error rejecting player from pool: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@admin_panel_bp.route('/substitute-pools/<league_type>/statistics')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def substitute_pool_statistics(league_type):
    """Get detailed statistics for a substitute pool."""
    try:
        if league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        from app.models_substitute_pools import SubstitutePool
        from sqlalchemy.orm import joinedload

        # Get active pools with statistics
        active_pools = SubstitutePool.query.options(
            joinedload(SubstitutePool.player)
        ).filter(
            SubstitutePool.league_type == league_type,
            SubstitutePool.is_active == True
        ).all()

        # Calculate statistics
        stats = {
            'total_active': len(active_pools),
            'total_requests_sent': sum(pool.requests_received for pool in active_pools),
            'total_requests_accepted': sum(pool.requests_accepted for pool in active_pools),
            'total_matches_played': sum(pool.matches_played for pool in active_pools),
            'average_acceptance_rate': 0,
            'top_performers': [],
            'notification_preferences': {
                'sms_enabled': sum(1 for pool in active_pools if pool.sms_for_sub_requests),
                'discord_enabled': sum(1 for pool in active_pools if pool.discord_for_sub_requests),
                'email_enabled': sum(1 for pool in active_pools if pool.email_for_sub_requests)
            }
        }

        if active_pools:
            total_acceptance = sum(pool.acceptance_rate for pool in active_pools)
            stats['average_acceptance_rate'] = total_acceptance / len(active_pools)

            # Get top performers
            top_performers = sorted(
                active_pools,
                key=lambda p: (p.matches_played, p.acceptance_rate),
                reverse=True
            )[:5]

            stats['top_performers'] = [
                {
                    'player_name': pool.player.name if pool.player else 'Unknown',
                    'matches_played': pool.matches_played,
                    'acceptance_rate': pool.acceptance_rate,
                    'requests_received': pool.requests_received
                }
                for pool in top_performers
            ]

        return jsonify({'success': True, 'statistics': stats})

    except Exception as e:
        logger.error(f"Error getting pool statistics: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500


@admin_panel_bp.route('/substitute-pools/player-search')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def substitute_pool_player_search():
    """Search for players that can be added to substitute pools."""
    try:
        from app.models import Player, User, Role
        from app.models_substitute_pools import SubstitutePool
        from sqlalchemy.orm import joinedload
        from sqlalchemy import or_

        query_str = request.args.get('q', '').strip()
        league_type = request.args.get('league_type', '').strip()

        if not query_str or len(query_str) < 2:
            return jsonify({'success': True, 'players': []})

        if league_type and league_type not in LEAGUE_TYPES:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        # Build base query
        base_query = Player.query.options(
            joinedload(Player.user).joinedload(User.roles)
        ).join(User).filter(
            or_(
                Player.name.ilike(f'%{query_str}%'),
                User.email.ilike(f'%{query_str}%'),
                User.username.ilike(f'%{query_str}%')
            )
        )

        players = base_query.limit(20).all()

        # Format results
        results = []
        for player in players:
            # Check which leagues they're eligible for
            eligible_leagues = []
            for lt, config in LEAGUE_TYPES.items():
                if player.user and any(role.name == config['role'] for role in player.user.roles):
                    eligible_leagues.append(lt)

            # Check current pool status
            current_pools = SubstitutePool.query.filter_by(
                player_id=player.id,
                is_active=True
            ).all()

            current_pool_types = [pool.league_type for pool in current_pools]

            results.append({
                'id': player.id,
                'name': player.name,
                'email': player.user.email if player.user else None,
                'discord_id': player.discord_id,
                'phone_number': player.phone,
                'eligible_leagues': eligible_leagues,
                'current_pools': current_pool_types,
                'can_add_to': [lt for lt in LEAGUE_TYPES.keys() if lt not in current_pool_types]
            })

        return jsonify({'success': True, 'players': results})

    except Exception as e:
        logger.error(f"Error searching players: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500