# app/admin_panel/routes/match_operations/substitutes.py

"""
Substitute Management Routes

Routes for substitute management:
- Substitute management dashboard
- Assign substitute
"""

import logging
from datetime import datetime

from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import joinedload, selectinload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.core import Season
from app.models.matches import Schedule
from app.decorators import role_required
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/substitute-management')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def substitute_management():
    """Substitute management dashboard."""
    try:
        from app.models import Match, Team
        from app.models.players import Player
        from app.models.substitutes import SubstituteRequest, SubstituteAssignment, SubstitutePool

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

        from app.utils.substitute_helpers import ACTIVE_SUB_STATUSES, actionable_sub_cutoff_date

        # Get filter parameters
        show_requested = request.args.get('show_requested', 'all')
        week_filter = request.args.get('week', type=int)
        # request_scope controls which requests the LIST shows. The KPI stat cards
        # always reflect the real-current (actionable) numbers regardless of this.
        #   active (default) — still staffable: match not past the grace window
        #   past            — active-status requests whose match already happened (clean-up / retroactive)
        #   all             — every non-terminal request this season
        request_scope = request.args.get('request_scope', 'active')
        if request_scope not in ('active', 'past', 'all'):
            request_scope = 'active'

        # Earliest match date still worth staffing (today minus the grace window).
        actionable_cutoff = actionable_sub_cutoff_date()

        # Get current Pub League season IDs for filtering
        current_seasons = Season.query.filter_by(is_current=True).all()
        current_season_ids = [s.id for s in current_seasons]

        # Get upcoming matches filtered to current season
        upcoming_matches_query = Match.query.join(
            Schedule, Match.schedule_id == Schedule.id
        ).filter(
            Match.date >= datetime.utcnow().date(),
            Schedule.season_id.in_(current_season_ids)
        ).order_by(Match.date.asc(), Match.time.asc())

        if week_filter:
            upcoming_matches_query = upcoming_matches_query.filter(
                Schedule.week == str(week_filter)
            )

        upcoming_matches = upcoming_matches_query.limit(20).all()

        # Base query: non-terminal requests in the current season(s). The grace-window
        # date filter is layered on per scope so the list and the KPI stats stay in lockstep.
        sub_requests_base = SubstituteRequest.query.options(
            joinedload(SubstituteRequest.match).joinedload(Match.home_team),
            joinedload(SubstituteRequest.match).joinedload(Match.away_team),
            joinedload(SubstituteRequest.team),
            selectinload(SubstituteRequest.assignments),
            selectinload(SubstituteRequest.responses)
        ).join(
            Match, SubstituteRequest.match_id == Match.id
        ).join(
            Schedule, Match.schedule_id == Schedule.id
        ).filter(
            SubstituteRequest.status.in_(list(ACTIVE_SUB_STATUSES)),
            Schedule.season_id.in_(current_season_ids)
        )

        # Actionable = still staffable (match not past the grace window). This drives
        # the KPI band's real-current numbers no matter which scope the list shows.
        actionable_requests = sub_requests_base.filter(
            Match.date >= actionable_cutoff
        ).order_by(SubstituteRequest.created_at.desc()).all()

        # Past-unresolved = active-status requests whose match already happened. Surfaced
        # so an admin can retroactively assign or close them out, but excluded from counts.
        past_unresolved_count = sub_requests_base.filter(
            Match.date < actionable_cutoff
        ).count()

        # The list shown follows request_scope; the default reuses the actionable set.
        if request_scope == 'past':
            sub_requests = sub_requests_base.filter(
                Match.date < actionable_cutoff
            ).order_by(SubstituteRequest.created_at.desc()).limit(100).all()
        elif request_scope == 'all':
            sub_requests = sub_requests_base.order_by(
                SubstituteRequest.created_at.desc()
            ).limit(100).all()
        else:
            sub_requests = actionable_requests

        # Batch-query RSVP counts per requesting team for each sub request
        rsvp_counts = {}
        if sub_requests:
            from app.models.matches import Availability
            from app.models.players import player_teams

            mt_pairs = set((req.match_id, req.team_id) for req in sub_requests)
            pair_conditions = [
                and_(
                    Availability.match_id == mid,
                    player_teams.c.team_id == tid
                )
                for mid, tid in mt_pairs
            ]

            counts_rows = (
                db.session.query(
                    Availability.match_id,
                    player_teams.c.team_id,
                    Availability.response,
                    func.count(Availability.id)
                )
                .join(player_teams, player_teams.c.player_id == Availability.player_id)
                .filter(or_(*pair_conditions))
                .group_by(Availability.match_id, player_teams.c.team_id, Availability.response)
                .all()
            )

            rsvp_lookup = {}
            for match_id, team_id, response, count in counts_rows:
                key = (match_id, team_id)
                if key not in rsvp_lookup:
                    rsvp_lookup[key] = {'yes': 0, 'maybe': 0, 'no': 0}
                if response in ('yes', 'maybe', 'no'):
                    rsvp_lookup[key][response] = count

            for req in sub_requests:
                rsvp_counts[req.id] = rsvp_lookup.get(
                    (req.match_id, req.team_id),
                    {'yes': 0, 'maybe': 0, 'no': 0}
                )

        # Get available substitutes from the SubstitutePool with player names
        pool_entries = SubstitutePool.query.options(
            joinedload(SubstitutePool.player)
        ).filter_by(is_active=True).all()

        available_subs = []
        for entry in pool_entries:
            if entry.player:
                available_subs.append({
                    'id': entry.player.id,
                    'name': entry.player.name,
                    'positions': entry.preferred_positions or entry.player.favorite_position or '',
                    'league_type': entry.league_type
                })
        # Sort by name
        available_subs.sort(key=lambda s: s['name'])

        # ── KPI stats: always derived from the actionable set so every card on the
        # page agrees with itself and with the admin dashboard, regardless of which
        # scope the list below is showing. ──
        total_requests = SubstituteRequest.query.join(
            Match, SubstituteRequest.match_id == Match.id
        ).join(
            Schedule, Match.schedule_id == Schedule.id
        ).filter(
            Schedule.season_id.in_(current_season_ids)
        ).count()

        filled_slots = 0
        need_slots = 0
        fully_staffed = 0
        for req in actionable_requests:
            filled = len(req.assignments) if req.assignments else 0
            needed = req.substitutes_needed or 0
            filled_slots += filled
            need_slots += needed
            if filled >= needed:
                fully_staffed += 1
        open_slots = need_slots - filled_slots if need_slots > filled_slots else 0

        stats = {
            'total_requests': total_requests,
            'active_requests': len(actionable_requests),
            'available_subs': len(available_subs),
            'upcoming_matches': len(upcoming_matches),
            'open_slots': open_slots,
            'filled_slots': filled_slots,
            'need_slots': need_slots,
            'fully_staffed': fully_staffed,
            'past_unresolved': past_unresolved_count,
        }

        # Group requests by match for easier template processing
        requested_teams_by_match = {}
        for sub_request in sub_requests:
            match_id = sub_request.match_id
            if match_id not in requested_teams_by_match:
                requested_teams_by_match[match_id] = {}
            requested_teams_by_match[match_id][sub_request.team_id] = sub_request

        # Get available weeks from Schedule model
        weeks = []
        try:
            if current_season_ids:
                schedules = Schedule.query.filter(
                    Schedule.season_id.in_(current_season_ids)
                ).order_by(Schedule.week_number).all()
                weeks = sorted(set(s.week_number for s in schedules if s.week_number))
        except Exception:
            weeks = list(range(1, 21))
        current_week = week_filter or (weeks[0] if weeks else 1)

        return render_template(
            'admin_panel/substitute_management_flowbite.html',
            stats=stats,
            sub_requests=sub_requests,
            rsvp_counts=rsvp_counts,
            upcoming_matches=upcoming_matches,
            available_subs=available_subs,
            requested_teams_by_match=requested_teams_by_match,
            weeks=weeks,
            current_week=current_week,
            show_requested=show_requested,
            request_scope=request_scope
        )
    except Exception as e:
        logger.error(f"Error loading substitute management: {e}", exc_info=True)
        flash('Substitute management unavailable. Verify database connection and substitute models.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/substitute-request/<int:request_id>/available-players')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_available_players_for_request(request_id):
    """Return players who responded 'available' for a specific sub request."""
    from flask import jsonify
    from app.models.substitutes import SubstituteResponse
    from app.models.players import Player

    responses = db.session.query(SubstituteResponse).options(
        joinedload(SubstituteResponse.player)
    ).filter_by(
        request_id=request_id,
        is_available=True
    ).all()

    players = []
    for resp in responses:
        if resp.player:
            players.append({
                'id': resp.player.id,
                'name': resp.player.name,
                'positions': resp.player.favorite_position or '',
                'responded_at': resp.responded_at.strftime('%m/%d %I:%M %p') if resp.responded_at else '',
            })

    return jsonify({'success': True, 'players': players})


@admin_panel_bp.route('/assign-substitute', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def assign_substitute():
    """Assign a substitute to a match."""
    from app.models.substitutes import SubstituteAssignment, SubstituteRequest, SubstituteResponse
    from app.utils.substitute_helpers import create_temp_sub_assignment
    from app.services.substitute_notification_service import get_notification_service

    match_id = request.form.get('match_id', type=int)
    team_id = request.form.get('team_id', type=int)
    player_id = request.form.get('player_id', type=int)
    request_id = request.form.get('request_id', type=int)
    position_assigned = request.form.get('position_assigned')
    notes = request.form.get('notes')
    send_confirmation = request.form.get('send_confirmation', 'true').lower() == 'true'

    if not all([match_id, team_id, player_id]):
        flash('Missing required information for substitute assignment.', 'error')
        return redirect(url_for('admin_panel.substitute_management'))

    # Get the outreach methods from the response if available
    outreach_methods = None
    if request_id:
        response = db.session.query(SubstituteResponse).filter_by(
            request_id=request_id,
            player_id=player_id
        ).first()
        if response and response.notification_methods:
            outreach_methods = response.notification_methods

    # Create substitute assignment
    assignment = SubstituteAssignment(
        request_id=request_id,
        player_id=player_id,
        assigned_by=current_user.id,
        assigned_at=datetime.utcnow(),
        position_assigned=position_assigned,
        notes=notes,
        outreach_methods=outreach_methods
    )

    db.session.add(assignment)
    db.session.flush()  # Get the assignment ID

    # Create TemporarySubAssignment for stat attribution
    temp_assignment = create_temp_sub_assignment(
        match_id=match_id,
        player_id=player_id,
        team_id=team_id,
        assigned_by=current_user.id,
        request_id=request_id,
        assignment_id=assignment.id,
        notes=notes,
        session=db.session
    )

    # Update the substitute request status if all spots filled
    if request_id:
        sub_request = db.session.query(SubstituteRequest).get(request_id)
        if sub_request:
            assignments_count = len(sub_request.assignments)
            if assignments_count >= sub_request.substitutes_needed:
                sub_request.status = 'FILLED'
                sub_request.filled_at = datetime.utcnow()

    # Send confirmation notification if requested
    if send_confirmation:
        notification_service = get_notification_service()
        notification_service.send_confirmation(assignment.id)

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
