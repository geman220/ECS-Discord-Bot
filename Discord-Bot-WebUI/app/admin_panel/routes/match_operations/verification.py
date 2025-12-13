# app/admin_panel/routes/match_operations/verification.py

"""
Match Verification Routes

Routes for match verification:
- Match verification dashboard
- Verify match results
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import or_, desc, cast, Integer
from sqlalchemy.orm import joinedload, aliased

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)


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
