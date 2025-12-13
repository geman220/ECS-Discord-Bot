# app/admin_panel/routes/match_operations/seasons.py

"""
Season Management Routes

Routes for season management:
- View/manage seasons
"""

import logging
from datetime import datetime

from flask import render_template, flash, redirect, url_for
from flask_login import login_required

from app.admin_panel import admin_panel_bp
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations/seasons')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def seasons():
    """Manage seasons."""
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
