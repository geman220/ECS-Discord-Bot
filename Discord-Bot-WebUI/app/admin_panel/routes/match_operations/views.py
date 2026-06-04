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

from flask import jsonify
from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.utils.db_utils import transactional

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
            elif status_filter == 'results':
                # Reported matches (both scores entered) — the old "Match Results" completed list.
                query = query.filter(
                    Match.home_team_score != None,
                    Match.away_team_score != None
                )
            elif status_filter == 'awaiting_score':
                # Past matches still missing a score — the old "Match Results" pending list.
                query = query.filter(
                    Match.date <= datetime.utcnow().date(),
                    Match.home_team_score == None,
                    Match.away_team_score == None
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
            'admin_panel/match_operations/view_matches_flowbite.html',
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
    """Consolidated into the unified Matches page — redirect to its Upcoming preset.

    The View Matches page (admin_panel.view_matches) already supports status=upcoming
    plus league/week/date filters and forward-looking KPI cards, so this standalone
    page is retired but kept as a redirect for old links/bookmarks.
    """
    return redirect(url_for('admin_panel.view_matches', status='upcoming'))


def _legacy_upcoming_matches_impl():
    try:
        from app.models import Match, Team, Season, League, Schedule

        today = datetime.utcnow().date()

        # Filter parameters from the toolbar
        league_filter = request.args.get('league_id', type=int)
        window_filter = request.args.get('window', 'all')  # all | today | week

        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()

        # Get upcoming matches with team and league information
        query = Match.query.filter(Match.date >= today)

        # Filter by current season if available
        if current_season:
            query = query.join(Schedule).filter(Schedule.season_id == current_season.id)

        # Apply league filter (filter by team's league)
        if league_filter:
            league_team_ids = [t.id for t in Team.query.filter_by(league_id=league_filter).all()]
            if league_team_ids:
                query = query.filter(
                    or_(
                        Match.home_team_id.in_(league_team_ids),
                        Match.away_team_id.in_(league_team_ids)
                    )
                )

        # Apply time-window filter
        if window_filter == 'today':
            query = query.filter(Match.date == today)
        elif window_filter == 'week':
            query = query.filter(Match.date <= today + timedelta(days=7))

        upcoming = query.order_by(Match.date.asc(), Match.time.asc()).limit(50).all()

        # Leagues for the filter dropdown (current season only, when available)
        if current_season:
            leagues = League.query.filter_by(season_id=current_season.id).order_by(League.name).all()
        else:
            leagues = League.query.order_by(League.name).all()

        # Get statistics (computed against the loaded result set)
        stats = {
            'total_upcoming': len(upcoming),
            'today': len([m for m in upcoming if m.date == today]),
            'this_week': len([m for m in upcoming if m.date <= today + timedelta(days=7)]),
            'next_week': len([m for m in upcoming if today + timedelta(days=7) < m.date <= today + timedelta(days=14)]),
            'this_month': len([m for m in upcoming if m.date <= today + timedelta(days=30)])
        }

        return render_template('admin_panel/match_operations/upcoming_matches_flowbite.html',
                               matches=upcoming, stats=stats, leagues=leagues,
                               today_date=today, current_league_id=league_filter,
                               current_window=window_filter)
    except Exception as e:
        logger.error(f"Error loading upcoming matches: {e}")
        flash('Upcoming matches unavailable. Verify database connection and date filtering.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/results')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def match_results():
    """Consolidated into the unified Matches page — redirect to its Results preset.

    The View Matches page now exposes a 'Results (reported)' and an 'Awaiting Score'
    status preset that reproduce this page's completed + pending lists, and it carries
    the same per-row score-entry action, so this page is retired (kept as a redirect).
    """
    return redirect(url_for('admin_panel.view_matches', status='results'))


def _legacy_match_results_impl():
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
            'admin_panel/match_operations/match_results_flowbite.html',
            completed_matches=completed_matches,
            pending_results=pending_results,
            stats=stats
        )
    except Exception as e:
        logger.error(f"Error loading match results: {e}")
        flash('Match results unavailable. Check database connectivity and score data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


LIVE_MATCHES_PAGE_ROLES = [
    'Global Admin', 'Pub League Admin', 'ECS FC Admin', 'Pub League Ref',
    'ECS FC Coach', 'Pub League Coach',
]


def _live_match_view_context():
    """Shared payload for the Live Matches page + its JSON refresh endpoint.

    `live` = matches actually being reported right now (real LiveMatch /
    EcsFcLiveMatch state, both leagues) via the single shared helper. `today`
    counts are context only. `v2_enabled` tells the client whether to upgrade
    to instant socket push; `observer_eligible` gates that join to admin/ref.
    """
    from app.services.live_reporting.live_match_queries import get_live_match_overviews
    from app.services.live_reporting.live_match_roles import is_admin_or_ref
    from app.models import Match, Season, Schedule
    from web_config import Config

    live = get_live_match_overviews(db.session)

    today = datetime.utcnow().date()
    current_season = Season.query.filter_by(is_current=True).first()
    today_q = Match.query.filter(Match.date == today)
    if current_season:
        today_q = today_q.join(Schedule).filter(Schedule.season_id == current_season.id)
    scheduled_today = today_q.count()

    return {
        'live': live,
        'stats': {
            'in_progress': len(live),
            'scheduled_today': scheduled_today,
        },
        'v2_enabled': bool(getattr(Config, 'LIVE_MATCH_STATE_V2_ENABLED', False)),
        'observer_eligible': is_admin_or_ref(current_user),
    }


@admin_panel_bp.route('/match-operations/live')
@login_required
@role_required(LIVE_MATCHES_PAGE_ROLES)
def live_matches():
    """Monitor matches being live-reported right now (Pub League + ECS FC)."""
    try:
        ctx = _live_match_view_context()
        return render_template('admin_panel/match_operations/live_matches_flowbite.html', **ctx)
    except Exception as e:
        logger.error(f"Error loading live matches: {e}", exc_info=True)
        flash('Live matches unavailable. Verify database connection and live-reporting tables.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/live/data')
@login_required
@role_required(LIVE_MATCHES_PAGE_ROLES)
def live_matches_data():
    """JSON snapshot of currently-live matches.

    Powers the page's periodic refresh (works with V1 or V2) and the socket
    fallback when LIVE_MATCH_STATE_V2_ENABLED is off. Datetimes are ISO strings.
    """
    try:
        ctx = _live_match_view_context()
        # Render the board with the SAME partial the page uses, so refreshed
        # markup never drifts from the initial server render.
        board_html = render_template(
            'admin_panel/match_operations/_live_board.html', live=ctx['live']
        )
        live = []
        for o in ctx['live']:
            live.append({
                'match_id': o['match_id'],
                'league_type': o['league_type'],
                'room': o['room'],
            })
        return jsonify({'success': True, 'live': live, 'stats': ctx['stats'],
                        'html': board_html,
                        'generated_at': datetime.utcnow().isoformat()})
    except Exception as e:
        logger.error(f"Error loading live matches data: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to load live match data'}), 500


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

        # Calculate basic statistics. "Completed" = both scores entered (Match has
        # no status column, so the old Match.status=='completed' check always read 0).
        total_matches = Match.query.count()
        recent_matches_count = len(recent_matches)
        completed_matches = Match.query.filter(
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None)
        ).count()

        reports_data = {
            'total_matches': total_matches,
            'recent_matches_count': recent_matches_count,
            'completed_matches': completed_matches,
            'pending_matches': total_matches - completed_matches,
            'recent_matches': recent_matches,
            'teams': teams
        }

        return render_template('admin_panel/match_operations/match_reports_flowbite.html',
                               reports_data=reports_data)
    except Exception as e:
        logger.error(f"Error loading match reports: {e}")
        flash('Match reports unavailable. Check database connectivity and report generation.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/matches/bulk-actions', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def match_bulk_actions():
    """Perform bulk actions on matches (delete, update status)."""
    try:
        from app.models import Match

        data = request.get_json()
        action = data.get('action')
        match_ids = data.get('match_ids', [])

        if not match_ids:
            return jsonify({'success': False, 'error': 'No matches selected'}), 400

        if action == 'delete':
            matches = Match.query.filter(Match.id.in_(match_ids)).all()
            count = len(matches)
            for match in matches:
                db.session.delete(match)

            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='bulk_delete_matches',
                resource_type='match',
                resource_id=','.join(str(m) for m in match_ids),
                new_value=f"Deleted {count} matches",
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            return jsonify({'success': True, 'message': f'{count} matches deleted successfully'})

        elif action == 'update_status':
            new_status = data.get('status')
            valid_statuses = ['scheduled', 'live', 'completed', 'cancelled', 'postponed']

            if new_status not in valid_statuses:
                return jsonify({'success': False, 'error': f'Invalid status: {new_status}'}), 400

            matches = Match.query.filter(Match.id.in_(match_ids)).all()
            count = len(matches)

            for match in matches:
                if hasattr(match, 'status'):
                    match.status = new_status

            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='bulk_update_match_status',
                resource_type='match',
                resource_id=','.join(str(m) for m in match_ids),
                new_value=f"Updated {count} matches to status: {new_status}",
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            return jsonify({'success': True, 'message': f'{count} matches updated to {new_status}'})

        else:
            return jsonify({'success': False, 'error': f'Unknown action: {action}'}), 400

    except Exception as e:
        logger.error(f"Error performing bulk match action: {e}")
        return jsonify({'success': False, 'error': 'Failed to perform bulk action'}), 500
