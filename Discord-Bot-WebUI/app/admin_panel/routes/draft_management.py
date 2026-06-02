# app/admin_panel/routes/draft_management.py

"""
Admin Panel Draft Management Routes

This module contains routes for:
- Draft history viewing and editing
- Draft position management
- Draft statistics and normalization
"""

import logging
from datetime import datetime
from flask import render_template, request, jsonify, redirect, url_for, g
from flask_login import login_required, current_user
from sqlalchemy import desc
from sqlalchemy.orm import joinedload, selectinload

from .. import admin_panel_bp
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.models import DraftOrderHistory, Season, League, Player, Team, DraftSession, DraftPickSlot
from app.models.admin_config import AdminAuditLog
from app.core import db
from app.draft_enhanced import DraftService
from app import draft_clock

logger = logging.getLogger(__name__)


# -----------------------------------------------------------
# Draft History Dashboard
# -----------------------------------------------------------

@admin_panel_bp.route('/draft')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_overview():
    """Redirect to unified draft history page."""
    # Redirect to draft history which has all the filtering and data
    return redirect(url_for('admin_panel.draft_history'))


@admin_panel_bp.route('/draft/history')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_history():
    """Display draft history with filtering - unified draft management page."""
    try:
        seasons = db.session.query(Season).order_by(desc(Season.id)).all()
        leagues = db.session.query(League).distinct(League.name).order_by(League.name).all()
        current_season = db.session.query(Season).filter_by(is_current=True).first()

        season_filter = request.args.get('season', type=int)
        league_filter = request.args.get('league')

        # Default to current season if no filter specified
        if season_filter is None and current_season:
            season_filter = current_season.id

        query = db.session.query(DraftOrderHistory).options(
            joinedload(DraftOrderHistory.player),
            joinedload(DraftOrderHistory.team),
            joinedload(DraftOrderHistory.season),
            joinedload(DraftOrderHistory.league),
            joinedload(DraftOrderHistory.drafter)
        )

        if season_filter:
            query = query.filter(DraftOrderHistory.season_id == season_filter)
        if league_filter:
            query = query.filter(DraftOrderHistory.league_id == league_filter)

        draft_history_list = query.order_by(
            desc(DraftOrderHistory.season_id),
            DraftOrderHistory.league_id,
            DraftOrderHistory.draft_position
        ).all()

        # Group by season and league
        grouped_history = {}
        for pick in draft_history_list:
            season_key = f"{pick.season.name} (ID: {pick.season.id})"
            league_key = f"{pick.league.name} (ID: {pick.league.id})"

            if season_key not in grouped_history:
                grouped_history[season_key] = {}
            if league_key not in grouped_history[season_key]:
                grouped_history[season_key][league_key] = []

            grouped_history[season_key][league_key].append(pick)

        # Get statistics for the header
        total_all_picks = db.session.query(DraftOrderHistory).count()
        current_season_picks = 0
        if current_season:
            current_season_picks = db.session.query(DraftOrderHistory).filter_by(
                season_id=current_season.id
            ).count()

        stats = {
            'total_picks': total_all_picks,
            'current_season_picks': current_season_picks,
            'seasons_count': len(seasons),
            'filtered_picks': len(draft_history_list)
        }

        return render_template('admin_panel/draft/history_flowbite.html',
                             draft_history=grouped_history,
                             seasons=seasons,
                             leagues=leagues,
                             current_season=current_season,
                             current_season_filter=season_filter,
                             current_league_filter=league_filter,
                             total_picks=len(draft_history_list),
                             stats=stats)

    except Exception as e:
        logger.error(f"Error loading draft history: {e}", exc_info=True)
        return render_template('admin_panel/draft/history_flowbite.html',
                             draft_history={},
                             seasons=[],
                             leagues=[],
                             total_picks=0,
                             error=str(e))


# -----------------------------------------------------------
# Draft Pick Management
# -----------------------------------------------------------

@admin_panel_bp.route('/draft/edit/<int:pick_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def edit_draft_pick(pick_id):
    """Edit a specific draft pick."""
    pick = db.session.query(DraftOrderHistory).filter_by(id=pick_id).first()
    if not pick:
        return jsonify({'success': False, 'message': 'Draft pick not found'}), 404

    data = request.get_json()
    new_position = data.get('position')
    if new_position is not None:
        new_position = int(new_position)
    new_notes = data.get('notes', '').strip()
    position_mode = data.get('mode', 'cascading')

    position_changed = False
    swap_result = None

    if new_position and new_position != pick.draft_position:
        if position_mode == 'absolute':
            swap_result = DraftService.set_absolute_draft_position(db.session, pick_id, new_position)
        elif position_mode == 'smart':
            swap_result = DraftService.insert_draft_position_smart(db.session, pick_id, new_position)
        elif position_mode == 'insert':
            swap_result = DraftService.insert_draft_position(db.session, pick_id, new_position)
        else:
            swap_result = DraftService.swap_draft_positions(db.session, pick_id, new_position)

        if not swap_result['success']:
            return jsonify(swap_result), 400

        position_changed = True
        logger.info(f"Swapped draft pick {pick_id} from #{swap_result['old_position']} to #{swap_result['new_position']}")

    notes_changed = False
    if new_notes != pick.notes:
        pick.notes = new_notes if new_notes else None
        pick.updated_at = datetime.utcnow()
        notes_changed = True

    if position_changed or notes_changed:
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='draft_pick_edit',
            resource_type='draft_pick',
            resource_id=str(pick_id),
            new_value=f'Position: {new_position}, Notes: {new_notes[:50] if new_notes else ""}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

    message_parts = []
    if position_changed:
        message_parts.append(f"Moved from #{swap_result['old_position']} to #{swap_result['new_position']}")
    if notes_changed:
        message_parts.append("updated notes")

    message = f"Updated draft pick for {pick.player.name}"
    if message_parts:
        message += f" ({', '.join(message_parts)})"

    return jsonify({
        'success': True,
        'message': message,
        'pick': {
            'id': pick.id,
            'position': pick.draft_position,
            'notes': pick.notes,
            'updated_at': pick.updated_at.isoformat() if pick.updated_at else None
        },
        'affected_picks': swap_result['affected_picks'] if swap_result else 0
    })


@admin_panel_bp.route('/draft/delete/<int:pick_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_draft_pick(pick_id):
    """Delete a specific draft pick."""
    pick = db.session.query(DraftOrderHistory).filter_by(id=pick_id).first()
    if not pick:
        return jsonify({'success': False, 'message': 'Draft pick not found'}), 404

    player_name = pick.player.name
    team_name = pick.team.name
    position = pick.draft_position
    season_id = pick.season_id
    league_id = pick.league_id

    db.session.delete(pick)

    # Adjust subsequent picks
    subsequent_picks = db.session.query(DraftOrderHistory).filter(
        DraftOrderHistory.season_id == season_id,
        DraftOrderHistory.league_id == league_id,
        DraftOrderHistory.draft_position > position
    ).all()

    for subsequent_pick in subsequent_picks:
        subsequent_pick.draft_position -= 1
        subsequent_pick.updated_at = datetime.utcnow()

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='draft_pick_delete',
        resource_type='draft_pick',
        resource_id=str(pick_id),
        new_value=f'Deleted pick #{position} ({player_name} to {team_name})',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': f'Deleted draft pick #{position} ({player_name} to {team_name})'
    })


@admin_panel_bp.route('/draft/clear', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def clear_draft_history():
    """Clear draft history for a specific season and league."""
    data = request.get_json()
    season_id = data.get('season_id')
    league_id = data.get('league_id')

    if season_id:
        season_id = int(season_id)
    if league_id:
        league_id = int(league_id)

    if not season_id or not league_id:
        return jsonify({'success': False, 'message': 'Season ID and League ID are required'}), 400

    season = db.session.query(Season).filter_by(id=season_id).first()
    league = db.session.query(League).filter_by(id=league_id).first()

    if not season or not league:
        return jsonify({'success': False, 'message': 'Season or League not found'}), 404

    picks_count = db.session.query(DraftOrderHistory).filter(
        DraftOrderHistory.season_id == season_id,
        DraftOrderHistory.league_id == league_id
    ).count()

    if picks_count == 0:
        return jsonify({'success': False, 'message': 'No draft picks found'}), 404

    deleted_count = db.session.query(DraftOrderHistory).filter(
        DraftOrderHistory.season_id == season_id,
        DraftOrderHistory.league_id == league_id
    ).delete()

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='draft_history_clear',
        resource_type='draft_history',
        resource_id=f'{season_id}_{league_id}',
        new_value=f'Cleared {deleted_count} picks for {season.name} - {league.name}',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({
        'success': True,
        'message': f'Cleared {deleted_count} draft picks for {season.name} - {league.name}'
    })


@admin_panel_bp.route('/draft/normalize', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def normalize_draft_positions():
    """Normalize draft positions to ensure sequential numbering."""
    data = request.get_json()
    season_id = data.get('season_id')
    league_id = data.get('league_id')

    if season_id:
        season_id = int(season_id)
    if league_id:
        league_id = int(league_id)

    if not season_id or not league_id:
        return jsonify({'success': False, 'message': 'Season ID and League ID are required'}), 400

    season = db.session.query(Season).filter_by(id=season_id).first()
    league = db.session.query(League).filter_by(id=league_id).first()

    if not season or not league:
        return jsonify({'success': False, 'message': 'Season or League not found'}), 404

    result = DraftService.normalize_draft_positions(db.session, season_id, league_id)

    if result['success']:
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='draft_positions_normalize',
            resource_type='draft_history',
            resource_id=f'{season_id}_{league_id}',
            new_value=f'Normalized {result["changes_made"]} positions',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

    return jsonify(result)


# -----------------------------------------------------------
# Draft API Endpoints
# -----------------------------------------------------------

@admin_panel_bp.route('/draft/api/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_stats_api():
    """API endpoint for draft statistics."""
    try:
        season_id = request.args.get('season_id', type=int)
        league_id = request.args.get('league_id', type=int)

        query = db.session.query(DraftOrderHistory)

        if season_id:
            query = query.filter(DraftOrderHistory.season_id == season_id)
        if league_id:
            query = query.filter(DraftOrderHistory.league_id == league_id)

        total_picks = query.count()

        # Get picks per team
        from sqlalchemy import func
        team_picks = query.with_entities(
            DraftOrderHistory.team_id,
            func.count(DraftOrderHistory.id)
        ).group_by(DraftOrderHistory.team_id).all()

        return jsonify({
            'total_picks': total_picks,
            'team_picks': {str(team_id): count for team_id, count in team_picks},
            'filters': {
                'season_id': season_id,
                'league_id': league_id
            }
        })

    except Exception as e:
        logger.error(f"Error getting draft stats: {e}")
        return jsonify({'error': 'Internal Server Error'}), 500


# -----------------------------------------------------------
# Draft "On the Clock" — setup + live turn engine
# -----------------------------------------------------------

def _require_league(season_id, league_id):
    """Resolve and validate (season, league); returns (season, league) or (None, error_response)."""
    season = db.session.query(Season).filter_by(id=season_id).first()
    league = db.session.query(League).filter_by(id=league_id).first()
    if not season or not league:
        return None, (jsonify({'success': False, 'message': 'Season or league not found'}), 404)
    return (season, league), None


@admin_panel_bp.route('/draft/session/state')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_session_state():
    """Return the live clock state for a (season, league), or {exists: false}."""
    season_id = request.args.get('season_id', type=int)
    league_id = request.args.get('league_id', type=int)
    ds = draft_clock.get_session(db.session, season_id, league_id)
    if not ds:
        return jsonify({'success': True, 'exists': False})
    return jsonify({'success': True, 'exists': True, 'state': draft_clock.build_state(db.session, ds)})


@admin_panel_bp.route('/draft/session/setup', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def draft_session_setup():
    """Create/replace the draft order + format for a (season, league). Status -> setup."""
    data = request.get_json() or {}
    season_id = data.get('season_id')
    league_id = data.get('league_id')
    team_order = data.get('team_order') or []   # ordered list of team ids
    if not season_id or not league_id or not team_order:
        return jsonify({'success': False, 'message': 'season_id, league_id and team_order are required'}), 400

    resolved, err = _require_league(season_id, league_id)
    if err:
        return err

    # validate teams belong to this league
    valid_ids = {t.id for t in db.session.query(Team).filter(Team.league_id == league_id).all()}
    bad = [tid for tid in team_order if tid not in valid_ids]
    if bad:
        return jsonify({'success': False, 'message': f'Teams not in this league: {bad}'}), 400

    ds = draft_clock.get_session(db.session, season_id, league_id)
    if not ds:
        ds = DraftSession(season_id=season_id, league_id=league_id)
        db.session.add(ds)
        db.session.flush()
    if ds.status == 'active':
        return jsonify({'success': False, 'message': 'Draft is active; pause or reset before changing the order'}), 409

    ds.format = data.get('format', 'snake')
    ds.seconds_per_pick = int(data.get('seconds_per_pick', 90) or 0)
    timeout_action = (data.get('timeout_action') or 'alert').lower()
    ds.timeout_action = timeout_action if timeout_action in ('alert', 'skip', 'pause') else 'alert'
    ds.lock_to_clock = bool(data.get('lock_to_clock', True))
    ds.rounds = int(data.get('rounds') or 0)
    ds.status = 'setup'
    ds.current_overall_pick = None
    ds.current_round = None
    ds.current_team_id = None
    ds.pick_deadline = None

    # replace slots
    db.session.query(DraftPickSlot).filter_by(draft_session_id=ds.id).delete()
    for i, tid in enumerate(team_order, start=1):
        db.session.add(DraftPickSlot(draft_session_id=ds.id, team_id=tid, slot=i))

    AdminAuditLog.log_action(
        user_id=current_user.id, action='draft_session_setup', resource_type='draft_session',
        resource_id=str(ds.id), new_value=f'{len(team_order)} teams, {ds.format}, {ds.seconds_per_pick}s, {ds.rounds} rounds',
        ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'))

    return jsonify({'success': True, 'state': draft_clock.build_state(db.session, ds)})


@admin_panel_bp.route('/draft/setup')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def draft_setup_page():
    """Admin page to set the team pick order + format, then start the on-the-clock draft."""
    season = db.session.query(Season).filter_by(is_current=True).first()
    leagues = []
    if season:
        leagues = db.session.query(League).filter_by(season_id=season.id).order_by(League.name).all()
    league_id = request.args.get('league_id', type=int)
    if not league_id and leagues:
        league_id = leagues[0].id
    league = db.session.query(League).filter_by(id=league_id).first() if league_id else None

    teams = []
    state = None
    available_players = 0
    if league:
        teams = db.session.query(Team).filter_by(league_id=league.id).order_by(Team.name).all()
        ds = draft_clock.get_session(db.session, season.id, league.id) if season else None
        if ds:
            state = draft_clock.build_state(db.session, ds)
            # order teams by saved slot order when a session exists
            order = {s.team_id: s.slot for s in ds.slots}
            if order:
                teams = sorted(teams, key=lambda t: order.get(t.id, 999))

        # Per-team coach name + current roster size (real data from player_teams).
        for t in teams:
            coaches = draft_clock.get_team_coaches(db.session, t.id)
            t.coach_name = coaches[0]['name'] if coaches else None
            t.roster_count = len(t.players)

        # Players in pool = current players eligible for this league who are not
        # yet rostered on any team in this league (same definition the draft board uses).
        from sqlalchemy import or_, and_, exists
        from app.models import player_league
        team_id_set = {t.id for t in teams}
        belongs_to_league = or_(
            Player.primary_league_id == league.id,
            exists().where(
                and_(
                    player_league.c.player_id == Player.id,
                    player_league.c.league_id == league.id,
                )
            ),
        )
        eligible_players = (
            db.session.query(Player)
            .filter(belongs_to_league)
            .filter(Player.is_current_player.is_(True))
            .options(selectinload(Player.teams))
            .all()
        )
        available_players = sum(
            1 for p in eligible_players
            if not ({tm.id for tm in p.teams} & team_id_set)
        )

    return render_template(
        'admin_panel/draft/setup_flowbite.html',
        title='Draft Setup',
        season=season,
        leagues=leagues,
        current_league=league,
        teams=teams,
        draft_clock_state=state,
        available_players=available_players,
        shell='console',
    )


@admin_panel_bp.route('/draft/session/timer', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def draft_session_timer():
    """Adjust the per-pick time live. Optionally extend the current pick's deadline."""
    from datetime import timedelta
    data = request.get_json() or {}
    ds = draft_clock.get_session(db.session, data.get('season_id'), data.get('league_id'))
    if not ds:
        return jsonify({'success': False, 'message': 'No draft set up for this league'}), 404
    secs = data.get('seconds_per_pick')
    extend = data.get('extend_current')
    add_seconds = data.get('add_seconds')
    if secs is None and not extend and add_seconds is None:
        return jsonify({'success': False, 'message': 'seconds_per_pick, extend_current, or add_seconds is required'}), 400
    if secs is not None:
        ds.seconds_per_pick = max(0, int(secs))
    # Additive mode: add N seconds to the CURRENT pick's remaining time (does not change seconds_per_pick).
    if add_seconds is not None:
        if ds.status != 'active':
            return jsonify({'success': False, 'message': 'No active pick to adjust'}), 400
        try:
            delta = int(add_seconds)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'add_seconds must be an integer'}), 400
        now = datetime.utcnow()
        # Base off the live remaining time (or now, if the pick was untimed/overdue).
        base = ds.pick_deadline if (ds.pick_deadline and ds.pick_deadline > now) else now
        new_deadline = base + timedelta(seconds=delta)
        # Never let an adjustment push the deadline into the past.
        ds.pick_deadline = new_deadline if new_deadline > now else now
        ds.alerts_sent = 0
    # If live and asked to apply now, reset the current pick's clock to the (new or stored) length.
    elif ds.status == 'active' and extend:
        ds.pick_deadline = (datetime.utcnow() + timedelta(seconds=ds.seconds_per_pick)) if ds.seconds_per_pick else None
        ds.alerts_sent = 0
    state = draft_clock.build_state(db.session, ds)
    draft_clock.emit_clock(ds.league.name, state)
    return jsonify({'success': True, 'state': state})


@admin_panel_bp.route('/draft/session/start', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def draft_session_start():
    """Put the first team on the clock."""
    data = request.get_json() or {}
    ds = draft_clock.get_session(db.session, data.get('season_id'), data.get('league_id'))
    if not ds:
        return jsonify({'success': False, 'message': 'No draft set up for this league'}), 404
    team_ids = draft_clock.ordered_team_ids(db.session, ds)
    if not team_ids or not ds.rounds:
        return jsonify({'success': False, 'message': 'Set the pick order and rounds first'}), 400
    ds.status = 'active'
    ds.started_at = datetime.utcnow()
    ds.started_by = current_user.id
    ds.completed_at = None
    draft_clock.set_clock_to(ds, 1, team_ids)
    state = draft_clock.build_state(db.session, ds, team_ids=team_ids)
    AdminAuditLog.log_action(
        user_id=current_user.id, action='draft_session_start', resource_type='draft_session',
        resource_id=str(ds.id), ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'))
    draft_clock.emit_clock(ds.league.name, state)
    return jsonify({'success': True, 'state': state})


@admin_panel_bp.route('/draft/session/pause', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def draft_session_pause():
    data = request.get_json() or {}
    ds = draft_clock.get_session(db.session, data.get('season_id'), data.get('league_id'))
    if not ds or ds.status != 'active':
        return jsonify({'success': False, 'message': 'No active draft to pause'}), 400
    if ds.pick_deadline:
        remaining = (ds.pick_deadline - datetime.utcnow()).total_seconds()
        ds.pause_remaining_seconds = max(0, int(remaining))
    ds.status = 'paused'
    ds.pick_deadline = None
    state = draft_clock.build_state(db.session, ds)
    draft_clock.emit_clock(ds.league.name, state)
    return jsonify({'success': True, 'state': state})


@admin_panel_bp.route('/draft/session/resume', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def draft_session_resume():
    from datetime import timedelta
    data = request.get_json() or {}
    ds = draft_clock.get_session(db.session, data.get('season_id'), data.get('league_id'))
    if not ds or ds.status != 'paused':
        return jsonify({'success': False, 'message': 'No paused draft to resume'}), 400
    ds.status = 'active'
    if ds.seconds_per_pick:
        secs = ds.pause_remaining_seconds if ds.pause_remaining_seconds is not None else ds.seconds_per_pick
        ds.pick_deadline = datetime.utcnow() + timedelta(seconds=secs)
    ds.pause_remaining_seconds = None
    state = draft_clock.build_state(db.session, ds)
    draft_clock.emit_clock(ds.league.name, state)
    return jsonify({'success': True, 'state': state})


@admin_panel_bp.route('/draft/session/skip', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def draft_session_skip():
    """Advance the clock to the next team without recording a pick."""
    data = request.get_json() or {}
    ds = draft_clock.get_session(db.session, data.get('season_id'), data.get('league_id'))
    if not ds or ds.status not in ('active', 'paused'):
        return jsonify({'success': False, 'message': 'No live draft to advance'}), 400
    state = draft_clock.advance(db.session, ds)
    AdminAuditLog.log_action(
        user_id=current_user.id, action='draft_session_skip', resource_type='draft_session',
        resource_id=str(ds.id), new_value=f'skipped to pick {ds.current_overall_pick}',
        ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'))
    draft_clock.emit_clock(ds.league.name, state)
    return jsonify({'success': True, 'state': state})


@admin_panel_bp.route('/draft/session/reset', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def draft_session_reset():
    """Return a draft to setup (keeps the order + format; clears live progress)."""
    data = request.get_json() or {}
    ds = draft_clock.get_session(db.session, data.get('season_id'), data.get('league_id'))
    if not ds:
        return jsonify({'success': False, 'message': 'No draft to reset'}), 404
    ds.status = 'setup'
    ds.current_overall_pick = None
    ds.current_round = None
    ds.current_team_id = None
    ds.pick_deadline = None
    ds.pause_remaining_seconds = None
    ds.completed_at = None
    AdminAuditLog.log_action(
        user_id=current_user.id, action='draft_session_reset', resource_type='draft_session',
        resource_id=str(ds.id), ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'))
    state = draft_clock.build_state(db.session, ds)
    draft_clock.emit_clock(ds.league.name, state)
    return jsonify({'success': True, 'state': state})
