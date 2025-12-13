# app/admin_panel/routes/match_operations/views.py

"""
Match Views Routes

Routes for viewing matches:
- View all matches
- Upcoming matches
- Match results
- Live matches
- Match reports
"""

import logging
from datetime import datetime, timedelta

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations/matches')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def view_matches():
    """View all Pub League matches (Premier, Classic, ECS FC)."""
    try:
        from app.models import Match, Team, Season, League, Schedule

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
        from app.models.matches import Match

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
        from app.models.matches import Match
        from app.models import Team

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
