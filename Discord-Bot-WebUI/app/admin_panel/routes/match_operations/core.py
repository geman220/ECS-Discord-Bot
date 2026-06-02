# app/admin_panel/routes/match_operations/core.py

"""
Match Operations Core Routes

Hub page and statistics for match operations.
"""

import logging
from datetime import datetime, timedelta

from flask import render_template, flash, redirect, url_for
from flask_login import login_required

from app.admin_panel import admin_panel_bp
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def match_operations():
    """Match & League Operations hub."""
    try:
        from app.models import Match, Team, Season, League, Schedule
        from app.utils.special_weeks import get_special_week_display_name

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

        # ---- Fixture Board: real per-fixture rows for the current week ----
        # Window is the calendar week (Mon..Sun) containing today, so the board
        # always shows "this week's" fixtures grouped by day. All fields below are
        # read straight off the Match/Team/League models -- no fabricated data.
        from sqlalchemy.orm import joinedload

        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=6)              # Sunday

        week_query = Match.query.options(
            joinedload(Match.home_team).joinedload(Team.league),
            joinedload(Match.away_team),
        )
        if current_season:
            week_query = week_query.join(Schedule).filter(Schedule.season_id == current_season.id)
        week_matches = (
            week_query
            .filter(Match.date >= week_start, Match.date <= week_end)
            .order_by(Match.date.asc(), Match.time.asc())
            .all()
        )

        def _fixture_status(m):
            """Derive a status from real fields only (no live telemetry exists)."""
            if m.reported:
                return 'verified' if m.fully_verified else 'pending_verify'
            # No scores yet: future = upcoming, today/past = awaiting a report.
            return 'upcoming' if m.date > today else 'needs_report'

        status_counts = {
            'all': 0, 'upcoming': 0, 'needs_report': 0,
            'pending_verify': 0, 'verified': 0,
        }
        fixtures_by_day = []
        current_label = None
        for m in week_matches:
            st = _fixture_status(m)
            status_counts['all'] += 1
            status_counts[st] += 1

            league_name = None
            if m.home_team and m.home_team.league:
                league_name = m.home_team.league.name

            row = {
                'id': m.id,
                'time': m.time.strftime('%-I:%M %p') if m.time else None,
                'home_team': m.home_team.name if m.home_team else 'TBD',
                'away_team': m.away_team.name if m.away_team else 'TBD',
                'home_score': m.home_team_score,
                'away_score': m.away_team_score,
                'status': st,
                'league_name': league_name,
                'location': m.location,
                'week_type': m.week_type,
                'special_week_display': get_special_week_display_name(m),
            }

            day_label = m.date.strftime('%a, %b %-d')
            if day_label != current_label:
                current_label = day_label
                is_today = (m.date == today)
                fixtures_by_day.append({
                    'label': day_label,
                    'is_today': is_today,
                    'count': 0,
                    'rows': [],
                })
            fixtures_by_day[-1]['count'] += 1
            fixtures_by_day[-1]['rows'].append(row)

        # Leagues for the (real) filter select.
        if current_season:
            board_leagues = League.query.filter_by(season_id=current_season.id).order_by(League.name).all()
        else:
            board_leagues = League.query.order_by(League.name).all()
        leagues = [{'id': lg.id, 'name': lg.name} for lg in board_leagues]

        week_label = f"{week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d')}"

        return render_template(
            'admin_panel/match_operations_flowbite.html',
            stats=stats,
            fixtures_by_day=fixtures_by_day,
            status_counts=status_counts,
            leagues=leagues,
            week_label=week_label,
        )
    except Exception as e:
        logger.error(f"Error loading match operations: {e}")
        flash('Match operations unavailable. Check database connectivity and model imports.', 'error')
        return redirect(url_for('admin_panel.dashboard'))
