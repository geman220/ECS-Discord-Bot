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

        return render_template('admin_panel/match_operations_flowbite.html', stats=stats)
    except Exception as e:
        logger.error(f"Error loading match operations: {e}")
        flash('Match operations unavailable. Check database connectivity and model imports.', 'error')
        return redirect(url_for('admin_panel.dashboard'))
