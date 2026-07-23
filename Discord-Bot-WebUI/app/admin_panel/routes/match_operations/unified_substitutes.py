# app/admin_panel/routes/match_operations/unified_substitutes.py

"""
Substitute Command Center (Phase 2)

ONE tabbed admin hub at /admin-panel/substitutes that replaces the scattered sub
pages: This Week (needs x ranked candidates), All Requests, Availability Grid,
Sub Pool, Poll Reconcile, and Settings.

This route stays READ-UNIFY + ACTION-DISPATCH: it reads through the unified adapter
and the availability service, and its actions dispatch to the EXISTING per-league
endpoints (assign / cancel / pool mgmt) plus the reach-out engine. The two original
pages (substitute_management, ecs_fc_sub_requests) are left untouched as fallbacks.

Authority for every assignment is gated through app.services.substitute_authority;
the target endpoints re-enforce it server-side.
"""

import logging
from datetime import datetime, timedelta

from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.models.admin_config import AdminConfig, AdminAuditLog
from app.services.unified_substitute_service import (
    get_unified_requests, get_unified_pool, get_hub_insights, get_week_needs,
)
from app.services.substitute_availability_service import (
    get_candidates_for_request, get_week_availability, upcoming_availability_date,
    player_sub_stats,
)
from app.services.substitute_authority import can_assign, is_admin, program_for_league_type

logger = logging.getLogger(__name__)

PER_PAGE = 25
ADMIN_ROLES = ['Global Admin', 'Pub League Admin', 'ECS FC Coach', 'ECS FC Admin']

# ---------------------------------------------------------------------------
# Settings schema — every tunable the Settings tab binds. Nothing is hardcoded;
# all values live in AdminConfig. (key, data_type, default).
# ---------------------------------------------------------------------------
_DEFAULT_POLL_Q = "Sub availability for Sunday {date} — which slot(s) can you play?"
_DEFAULT_MSG_GENERAL = (
    "{league} subs — can you play this Sunday at {slots}? Tap to let us know. "
    "We'll confirm a team if we need you."
)
_DEFAULT_MSG_TARGETED = (
    "Can you sub this {date} at {slot}? Let us know — we'll confirm the team if you're picked."
)
_DEFAULT_CONFIRM = (
    "You've been confirmed as a substitute for {team} on {date} at {time}, {location}. "
    "Please arrive {early} minutes early. Thanks for stepping up!"
)

SETTINGS_SCHEMA = [
    # Automated availability poll
    ('sub_availability_poll_enabled', 'boolean', True),
    ('sub_availability_poll_weekday', 'integer', 4),   # Mon=0 .. Sun=6; Friday=4
    ('sub_availability_poll_hour', 'integer', 14),
    ('sub_poll_open_hours', 'integer', 48),
    ('sub_availability_poll_only_needed', 'boolean', False),
    ('sub_poll_channel_id', 'string', ''),
    ('sub_poll_role_ids', 'string', ''),
    ('sub_poll_question', 'string', _DEFAULT_POLL_Q),
    # Reach-out defaults
    ('sub_reachout_default_channels', 'string', 'PUSH,DISCORD,EMAIL'),
    ('sub_reachout_allow_sms', 'boolean', False),
    ('sub_reachout_msg_general', 'string', _DEFAULT_MSG_GENERAL),
    ('sub_reachout_msg_targeted', 'string', _DEFAULT_MSG_TARGETED),
    # Requests & lifecycle
    ('sub_default_needed', 'integer', 1),
    ('sub_auto_expire_days', 'integer', 1),
    ('sub_notify_on_cancel', 'boolean', True),
    ('sub_pool_stale_days', 'integer', 120),
    # Assignment & balance
    ('sub_default_max_matches', 'integer', 3),
    ('sub_assignment_balance_mode', 'string', 'soft'),   # 'soft' | 'hard'
    ('sub_warn_on_conflict', 'boolean', True),
    # Notifications & confirmations
    ('sub_notify_on_response', 'string', 'coach_admins'),  # coach_admins | admins | coach
    ('sub_notify_not_selected', 'boolean', True),
    ('sub_arrive_early_min', 'integer', 15),
    ('sub_confirmation_msg', 'string', _DEFAULT_CONFIRM),
]

# TODO: replace with a live bot /api/discord/channels proxy (a separate change adds
# the bot endpoint). Until then the Settings tab reads the configured channel id and
# falls back to this static list so the selector renders and is bindable.
_FALLBACK_DISCORD_CHANNELS = [
    {'id': '1420461752344117300', 'name': '#pl-subs'},
    {'id': '', 'name': '#substitutes'},
    {'id': '', 'name': '#pub-league-general'},
    {'id': '', 'name': '#announcements'},
]


def _load_settings():
    """Read every schema key into a plain dict for the template."""
    out = {}
    for key, _dtype, default in SETTINGS_SCHEMA:
        out[key] = AdminConfig.get_setting(key, default)
    return out


def _current_season_id():
    """Current Pub League season id (availability pool is Pub-League-scoped)."""
    try:
        from app.utils.season_context import current_pub_league_season
        s = current_pub_league_season()
        return s.id if s else None
    except Exception:
        return None


def _resolve_week(arg):
    """Resolve the ?week=YYYY-MM-DD arg to a date, defaulting to next Sunday."""
    if arg:
        try:
            return datetime.strptime(arg, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            pass
    return upcoming_availability_date()


@admin_panel_bp.route('/substitutes')
@login_required
@role_required(ADMIN_ROLES)
def unified_substitutes():
    """Substitute Command Center — tabbed hub across Pub League + ECS FC."""
    try:
        league = request.args.get('league', 'all')
        if league not in ('all', 'pub_league', 'ecs_fc'):
            league = 'all'

        status = request.args.get('status', 'active')
        if status not in ('active', 'all', 'open', 'filled', 'cancelled', 'expired'):
            status = 'active'

        page = request.args.get('page', 1, type=int) or 1
        week_date = _resolve_week(request.args.get('week'))
        season_id = _current_season_id()

        # All Requests tab feed (paginated).
        items, total, page, pages = get_unified_requests(
            db.session, league=league, status=status, page=page, per_page=PER_PAGE
        )

        # This Week needs (both leagues, this Sunday).
        week_needs = get_week_needs(db.session, week_date, season_id)
        # Stamp per-need assignment authority for the current user (UI hint; the
        # target endpoints re-enforce it).
        for need in week_needs:
            program = program_for_league_type(need.get('league_type'))
            need['can_assign'] = can_assign(
                db.session, current_user.id,
                team_id=need.get('team_id'), program=program
            )

        # Enriched, full tri-state pool for the Sub Pool tab (+ reach-out picker).
        pool_members = get_unified_pool(db.session, season_id=season_id, include_inactive=True)
        active_pool = [m for m in pool_members if m['status'] == 'active']

        # Availability grid for this week (Pub League).
        week_availability = get_week_availability(
            db.session, week_date, league_type=None, season_id=season_id, available_only=False
        )

        insights = get_hub_insights(db.session, season_id)
        settings = _load_settings()

        # KPI band.
        open_needs = [n for n in week_needs if n['status'] == 'OPEN']
        slots_to_fill = sum(max(0, (n['needed'] - n['assigned'])) for n in open_needs)
        slots_needed = sum(n['needed'] for n in open_needs)
        ready_now = sum(1 for n in open_needs if n.get('candidate_count', 0) > 0)
        available_subs = len([a for a in week_availability if a.get('is_available')])

        kpis = {
            'open_requests': len(open_needs),
            'slots_to_fill': slots_to_fill,
            'slots_needed': slots_needed,
            'ready_now': ready_now,
            'available_subs': available_subs,
            'pool_size': len(pool_members),
            'active_pool': len(active_pool),
        }

        pool_counts = {
            'active': sum(1 for m in pool_members if m['status'] == 'active'),
            'break': sum(1 for m in pool_members if m['status'] == 'break'),
            'pending': sum(1 for m in pool_members if m['status'] == 'pending'),
        }

        # Week navigation labels.
        week_label = f"Week of {week_date.strftime('%b')} {week_date.day}"
        prev_week = (week_date - timedelta(days=7)).isoformat()
        next_week = (week_date + timedelta(days=7)).isoformat()

        try:
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='access_substitute_command_center',
                resource_type='match_operations',
                resource_id='substitute_command_center',
                new_value='Accessed substitute command center',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent'),
            )
        except Exception:
            pass

        return render_template(
            'admin_panel/substitutes_unified_flowbite.html',
            items=items, total=total, page=page, pages=pages, per_page=PER_PAGE,
            week_needs=week_needs,
            pool_members=pool_members,
            active_pool=active_pool,
            pool_counts=pool_counts,
            week_availability=week_availability,
            insights=insights,
            settings=settings,
            kpis=kpis,
            league_filter=league,
            status_filter=status,
            week_date=week_date.isoformat(),
            week_label=week_label,
            prev_week=prev_week,
            next_week=next_week,
            is_global_admin=is_admin(db.session, current_user.id),
            discord_channels=_discord_channels()[0],
        )
    except Exception as e:
        logger.error(f"Error loading substitute command center: {e}", exc_info=True)
        flash('Substitute Command Center unavailable. Verify database connection and substitute models.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


# ===========================================================================
# JSON sub-routes consumed by substitute-command-center.js
# ===========================================================================

def _serialize_pub_candidate(c):
    """Shape a pub-league availability candidate for the slide-over."""
    return {
        'player_id': c['player_id'],
        'name': c['name'],
        'avatar_url': c.get('avatar_url'),
        'league_type': c.get('league_type'),
        'preferred_position': c.get('preferred_position'),
        'time_slots': c.get('time_slots') or [],
        'match_ids': c.get('match_ids') or [],
        'source': c.get('source'),
        'is_available': c.get('is_available'),
        'response_rate': c.get('response_rate', 0),
        'matches_played': c.get('matches_played', 0),
        'subbed_this_season': c.get('subbed_this_season', 0),
        'conflict': c.get('conflict', False),
        'position_fit': c.get('position_fit'),
        'at_weekly_cap': c.get('at_weekly_cap', False),
        'max_matches_per_week': c.get('max_matches_per_week'),
    }


@admin_panel_bp.route('/substitutes/candidates-for-request')
@login_required
@role_required(ADMIN_ROLES)
def sub_candidates_for_request():
    """Ranked candidates for one OPEN request, for the This Week slide-over.

    Query: request_id, league ('pub_league' | 'ecs_fc').
    Pub League -> canonical availability pool. ECS FC -> its own available
    responses (EcsFcSubResponse where is_available).
    """
    from app.models.substitutes import (
        SubstituteRequest, EcsFcSubRequest, EcsFcSubResponse,
    )
    league = request.args.get('league', 'pub_league')
    try:
        request_id = int(request.args.get('request_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'request_id required'}), 400

    season_id = _current_season_id()

    if league == 'ecs_fc':
        req = db.session.query(EcsFcSubRequest).get(request_id)
        if not req:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        allowed = can_assign(db.session, current_user.id, team_id=req.team_id, program='ECS FC')
        if not allowed:
            # Fail closed: don't leak candidate rosters to someone who can't act.
            return jsonify({'success': True, 'candidates': [], 'can_assign': False,
                            'assign_url': url_for('admin.ecs_fc_subs.assign_substitute', request_id=request_id)})
        rows = (
            db.session.query(EcsFcSubResponse)
            .filter(EcsFcSubResponse.request_id == request_id,
                    EcsFcSubResponse.is_available.is_(True))
            .all()
        )
        # Parity with Pub League candidates: position-fit + conflict + balance ranking.
        from app.services.substitute_availability_service import _pos_tokens
        from app.models import player_teams
        needed_pos = _pos_tokens(getattr(req, 'positions_needed', None))
        conflict_pids = set()
        if req.team_id:
            rows_pt = db.session.execute(
                player_teams.select().where(player_teams.c.team_id == req.team_id)
            ).fetchall()
            conflict_pids = {rp.player_id for rp in rows_pt}
        candidates = []
        for r in rows:
            player = r.player
            stats = player_sub_stats(db.session, r.player_id, season_id) if player else {}
            cand_pos = set()
            if player:
                cand_pos = _pos_tokens(getattr(player, 'favorite_position', None)) \
                    | _pos_tokens(getattr(player, 'other_positions', None))
            candidates.append({
                'player_id': r.player_id,
                'name': player.name if player else f'Player {r.player_id}',
                'avatar_url': player.avatar_image_url if player else None,
                'league_type': 'ECS FC',
                'preferred_position': getattr(player, 'favorite_position', None) if player else None,
                'time_slots': [],
                'is_available': True,
                'response_rate': stats.get('response_rate', 0),
                'matches_played': stats.get('matches_played', 0),
                'subbed_this_season': stats.get('subbed_this_season', 0),
                'conflict': r.player_id in conflict_pids,
                'position_fit': (bool(needed_pos & cand_pos) if needed_pos else None),
                'at_weekly_cap': False,
                'source': 'ecs_response',
            })
        candidates.sort(key=lambda d: (
            d['conflict'], d.get('position_fit') is False,
            d['subbed_this_season'], -d['response_rate'],
        ))
        return jsonify({'success': True, 'candidates': candidates, 'can_assign': allowed,
                        'assign_url': url_for('admin.ecs_fc_subs.assign_substitute', request_id=request_id)})

    # Pub League
    req = db.session.query(SubstituteRequest).get(request_id)
    if not req:
        return jsonify({'success': False, 'error': 'Request not found'}), 404
    allowed = can_assign(db.session, current_user.id, team_id=req.team_id, program='Pub League')
    if not allowed:
        # Fail closed: Pub League candidates are admin-only (coaches request, admins assign).
        return jsonify({'success': True, 'candidates': [], 'can_assign': False,
                        'assign_url': url_for('admin_panel.assign_substitute'),
                        'match_id': req.match_id, 'team_id': req.team_id})
    cands = get_candidates_for_request(db.session, req, season_id)
    return jsonify({
        'success': True,
        'candidates': [_serialize_pub_candidate(c) for c in cands],
        'can_assign': allowed,
        'assign_url': url_for('admin_panel.assign_substitute'),
        'match_id': req.match_id,
        'team_id': req.team_id,
    })


@admin_panel_bp.route('/substitutes/assign', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
@transactional
def sub_assign_json():
    """JSON assign for the hub slide-over — returns a real success/error the JS can
    trust (the legacy flash+redirect endpoints always look like 200 to fetch, so the
    hub could never tell a denied/filled/unavailable assign from a real one).

    Enforces the authority invariant server-side (Pub League admins-only; ECS FC
    owning-coach-or-admin), honors partial fills (substitutes_needed), and fires the
    same confirmation notification as the legacy paths.

    Body: {request_id, league:'pub_league'|'ecs_fc', player_id, position?, notes?, send_confirmation?}
    """
    from app.models.substitutes import (
        SubstituteRequest, SubstituteResponse, SubstituteAssignment,
        EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment,
    )
    data = request.get_json(silent=True) or {}
    league = (data.get('league') or 'pub_league').strip().lower()
    try:
        request_id = int(data.get('request_id'))
        player_id = int(data.get('player_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'request_id and player_id are required'}), 400
    position = (data.get('position') or '').strip() or None
    notes = (data.get('notes') or '').strip() or None
    do_confirm = str(data.get('send_confirmation', True)).lower() not in ('false', '0', 'no', 'off')
    session = db.session
    now = datetime.utcnow()

    if league == 'ecs_fc':
        req = session.query(EcsFcSubRequest).get(request_id)
        if not req:
            return jsonify({'success': False, 'error': 'Request not found'}), 404
        if not can_assign(session, current_user.id, team_id=req.team_id, program='ECS FC'):
            return jsonify({'success': False, 'error': 'You can only assign subs for your own team'}), 403
        if req.status != 'OPEN':
            return jsonify({'success': False, 'error': 'This request has already been handled'}), 409
        resp = session.query(EcsFcSubResponse).filter_by(
            request_id=request_id, player_id=player_id, is_available=True).first()
        if not resp:
            return jsonify({'success': False, 'error': 'That player has not confirmed availability'}), 400
        if session.query(EcsFcSubAssignment).filter_by(request_id=request_id, player_id=player_id).first():
            return jsonify({'success': False, 'error': 'That player is already assigned'}), 409
        current = len(req.assignments or [])
        if current >= req.substitutes_needed:
            return jsonify({'success': False, 'error': 'This request is already fully staffed'}), 409
        assignment = EcsFcSubAssignment(
            request_id=request_id, player_id=player_id, assigned_by=current_user.id,
            position_assigned=position, notes=notes)
        session.add(assignment)
        session.flush()
        filled = (current + 1) >= req.substitutes_needed
        if filled:
            req.status = 'FILLED'
            req.filled_at = now
        try:
            from app.tasks.tasks_ecs_fc_subs import notify_assigned_substitute
            notify_assigned_substitute.delay(assignment.id)
        except Exception:
            logger.exception("Failed to queue ECS FC assignment notification")
        name = resp.player.name if resp.player else f'Player {player_id}'
        return jsonify({'success': True, 'filled': filled,
                        'message': f'{name} assigned' + (' — request filled' if filled else '')})

    # Pub League
    req = session.query(SubstituteRequest).get(request_id)
    if not req:
        return jsonify({'success': False, 'error': 'Request not found'}), 404
    if not can_assign(session, current_user.id, team_id=req.team_id, program='Pub League'):
        return jsonify({'success': False, 'error': 'Only admins assign Pub League subs'}), 403
    if req.status not in ('OPEN', 'PENDING', 'APPROVED'):
        return jsonify({'success': False, 'error': 'This request has already been handled'}), 409
    if session.query(SubstituteAssignment).filter_by(request_id=request_id, player_id=player_id).first():
        return jsonify({'success': False, 'error': 'That player is already assigned'}), 409
    current = len(req.assignments or [])
    if current >= req.substitutes_needed:
        return jsonify({'success': False, 'error': 'This request is already fully staffed'}), 409

    outreach_methods = None
    resp = session.query(SubstituteResponse).filter_by(request_id=request_id, player_id=player_id).first()
    if resp and resp.notification_methods:
        outreach_methods = resp.notification_methods
    assignment = SubstituteAssignment(
        request_id=request_id, player_id=player_id, assigned_by=current_user.id,
        assigned_at=now, position_assigned=position, notes=notes, outreach_methods=outreach_methods)
    session.add(assignment)
    session.flush()

    # Reliable stat attribution IN the assign transaction — send_confirmation (the
    # Pub League notify path) does NOT bump matches_played, and the notify TASK may
    # never run. Increment the pool counter + activity here so the count can't be lost.
    from app.models.substitutes import SubstitutePool as _SP
    pool = session.query(_SP).filter_by(player_id=player_id).first()
    if pool:
        pool.matches_played = (pool.matches_played or 0) + 1
        pool.last_active_at = now

    # Temp-sub roster row for stat attribution (same as the legacy path).
    try:
        from app.utils.substitute_helpers import create_temp_sub_assignment
        create_temp_sub_assignment(
            match_id=req.match_id, player_id=player_id, team_id=req.team_id,
            assigned_by=current_user.id, request_id=request_id,
            assignment_id=assignment.id, notes=notes, session=session)
    except Exception:
        logger.exception("Failed to create temp sub assignment (stat attribution)")

    filled = (current + 1) >= req.substitutes_needed
    if filled:
        req.status = 'FILLED'
        req.filled_at = now
    # Persist the assignment BEFORE send_confirmation: that method runs on the same
    # session and rolls it back on any internal error (e.g. a null match in message
    # formatting), which would silently discard this assignment while we return
    # success. Committing first makes the confirmation send a no-op-on-failure.
    session.commit()
    if do_confirm:
        try:
            from app.services.substitute_notification_service import get_notification_service
            get_notification_service().send_confirmation(assignment.id)
        except Exception:
            logger.exception("Failed to send assignment confirmation")
    from app.models import Player as _Pl
    _p = session.query(_Pl).get(player_id)
    name = _p.name if _p else f'Player {player_id}'
    return jsonify({'success': True, 'filled': filled,
                    'message': f'{name} assigned' + (' — request filled' if filled else '')})


@admin_panel_bp.route('/substitutes/week-availability')
@login_required
@role_required(ADMIN_ROLES)
def sub_week_availability():
    """Availability grid feed for a week. Query: week=YYYY-MM-DD, league_type?"""
    # Fail closed: the league-wide availability pool is admin-only info (coaches
    # only ever act on their own team's requests, not the whole pool).
    if not is_admin(db.session, current_user.id):
        return jsonify({'success': True, 'availability': [],
                        'week': _resolve_week(request.args.get('week')).isoformat()})
    week_date = _resolve_week(request.args.get('week'))
    league_type = request.args.get('league_type') or None
    season_id = _current_season_id()
    rows = get_week_availability(db.session, week_date, league_type=league_type,
                                 season_id=season_id, available_only=False)
    return jsonify({'success': True, 'availability': rows, 'week': week_date.isoformat()})


def _discord_channels():
    """Return (channels, source) for the poll channel selector.

    Reads the live text-channel list from the bot's /api/discord/channels (added to
    bot_rest_api.py). Uses sync `requests` — the gunicorn/gevent web process cannot
    use aiohttp/asyncio to reach the bot (see reference: aiohttp fails in gevent web).
    Falls back to the static list (merged with any configured id) if the bot is
    unreachable or not ready, so the selector always renders and the saved value sticks.
    """
    configured = AdminConfig.get_setting('sub_poll_channel_id', '')

    def _with_configured(chs):
        chs = [dict(c) for c in chs]
        if configured and not any(str(c.get('id')) == str(configured) for c in chs):
            chs.insert(0, {'id': configured, 'name': f'(configured) {configured}'})
        return chs

    try:
        import requests
        from app.config import Config
        url = f"{Config.BOT_API_URL.rstrip('/')}/api/discord/channels"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            body = resp.json()
            if body.get('success') and isinstance(body.get('channels'), list):
                return _with_configured(body['channels']), 'live'
    except Exception:
        logger.warning("Discord channels: bot unreachable, using fallback", exc_info=True)

    return _with_configured(_FALLBACK_DISCORD_CHANNELS), 'fallback'


@admin_panel_bp.route('/substitutes/discord-channels')
@login_required
@role_required(ADMIN_ROLES)
def sub_discord_channels():
    """JSON channel list for the live-refresh button (live from the bot, else fallback)."""
    channels, source = _discord_channels()
    return jsonify({'success': True, 'channels': channels, 'source': source})


@admin_panel_bp.route('/substitutes/settings-save', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Admin'])
@transactional
def sub_settings_save():
    """Persist the Settings tab into AdminConfig. Admins only.

    @transactional commits g.db_session, which is the session AdminConfig.set_setting
    writes to in a request context — committing db.session here instead would silently
    drop every write (see reference: two sessions = lost writes).
    """
    data = request.get_json(silent=True) or {}
    saved = 0
    errors = []
    for key, dtype, default in SETTINGS_SCHEMA:
        if key not in data:
            continue
        raw = data[key]
        try:
            if dtype == 'boolean':
                value = bool(raw)
            elif dtype == 'integer':
                value = int(raw)
            else:
                value = '' if raw is None else str(raw)
            AdminConfig.set_setting(key, value, category='substitutes',
                                    data_type=dtype, user_id=current_user.id)
            saved += 1
        except (TypeError, ValueError):
            errors.append(key)

    if errors:
        return jsonify({'success': False, 'saved': saved, 'invalid': errors,
                        'error': f"Invalid values for: {', '.join(errors)}"}), 400
    return jsonify({'success': True, 'saved': saved})


@admin_panel_bp.route('/substitutes/reachout-web', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def sub_reachout_web():
    """Session-auth reach-out (the web twin of mobile /api/v1/substitutes/reachout).

    Reuses the SAME send engine — substitute_notification_service.send_reachout —
    and the SubstituteReachout / SubstituteReachoutRecipient models. Only the
    request-handling wrapper is web-flavored (session cookie + CSRF instead of JWT);
    no notification/availability logic is reimplemented here.

    Body: {kind, league_type, match_date, time_slots, match_ids?, request_id?,
           recipient_player_ids?, channels?, message?}
    """
    from app.models.substitutes import (
        SubstituteRequest, SubstituteReachout, SubstituteReachoutRecipient,
        get_active_substitutes,
    )
    from app.models import Player
    from app.services.substitute_authority import can_request
    from app.services.substitute_notification_service import get_notification_service

    PUB = ('Classic', 'Premier')
    data = request.get_json(silent=True) or {}

    kind = (data.get('kind') or 'general').strip().lower()
    if kind not in ('general', 'targeted'):
        return jsonify({'success': False, 'error': "kind must be 'general' or 'targeted'"}), 400

    league_type = (data.get('league_type') or '').strip()
    if league_type not in PUB:
        return jsonify({'success': False, 'error': f"league_type must be one of {', '.join(PUB)}"}), 400

    try:
        match_date = datetime.strptime(str(data.get('match_date')), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'match_date must be YYYY-MM-DD'}), 400

    time_slots = [str(s) for s in (data.get('time_slots') or [])]
    try:
        match_ids = [int(m) for m in (data.get('match_ids') or [])]
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'match_ids must be integers'}), 400

    request_id = data.get('request_id')
    if request_id is not None:
        try:
            request_id = int(request_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'request_id must be an integer'}), 400

    recipient_player_ids = data.get('recipient_player_ids') or []
    if kind == 'targeted':
        try:
            recipient_player_ids = [int(p) for p in recipient_player_ids]
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'recipient_player_ids must be integers'}), 400
        if not recipient_player_ids:
            return jsonify({'success': False, 'error': 'recipient_player_ids required for targeted'}), 400

    channels = data.get('channels')
    channels_str = None
    if channels and isinstance(channels, list):
        picked = [str(c).strip().upper() for c in channels if str(c).strip()]
        # Org-wide "Allow SMS reach-outs" master switch (Settings). Per-recipient
        # consent is still enforced in get_player_channels; this is the admin kill switch.
        # Default False to match the Settings UI/schema (SMS reach-outs off unless
        # an admin explicitly enables the master switch).
        allow_sms = str(AdminConfig.get_setting('sub_reachout_allow_sms', False)).lower() \
            in ('true', '1', 'yes', 'on')
        if not allow_sms:
            picked = [c for c in picked if c != 'SMS']
        channels_str = ','.join(picked) or None
    message = (data.get('message') or '').strip() or None

    # Use a dedicated managed session (the proven mobile-endpoint pattern) so this
    # never mixes with g.db_session / db.session — send-then-commit is self-contained.
    from app.core.session_manager import managed_session
    user_id = current_user.id
    with managed_session() as session:
        # Authority: admins always; a coach only anchored to their own team's request.
        authorized = is_admin(session, user_id, program='Pub League')
        if not authorized:
            if request_id is None:
                return jsonify({'success': False, 'error': 'Only admins can run a pool-wide reach-out'}), 403
            anchor = session.query(SubstituteRequest).get(request_id)
            if not anchor:
                return jsonify({'success': False, 'error': 'Request not found'}), 404
            if not can_request(session, user_id, team_id=anchor.team_id, program='Pub League'):
                return jsonify({'success': False, 'error': "You can only reach out for your own team's requests"}), 403

        # Resolve recipients. league_type is authoritative: even a targeted pick is
        # constrained to subs eligible for THAT league, so a "Premier" reach-out can
        # never include Classic-only subs (and vice-versa).
        eligible_ids = {pe.player_id for pe in get_active_substitutes(league_type, session)}
        if kind == 'general':
            target_player_ids = list(eligible_ids)
        else:
            found = {pid for (pid,) in session.query(Player.id).filter(Player.id.in_(recipient_player_ids)).all()}
            target_player_ids = [pid for pid in recipient_player_ids if pid in found and pid in eligible_ids]

        seen = set()
        target_player_ids = [p for p in target_player_ids if not (p in seen or seen.add(p))]
        if not target_player_ids:
            return jsonify({'success': False, 'error': 'No recipients resolved'}), 400

        try:
            from app.mobile_api.substitutes import _current_pub_league_season_id
            season_id = _current_pub_league_season_id(session)
        except Exception:
            season_id = None

        reachout = SubstituteReachout(
            kind=kind, league_type=league_type, match_date=match_date, season_id=season_id,
            time_slots=time_slots, match_ids=match_ids, request_id=request_id,
            message=message, channels=channels_str, created_by=user_id,
            recipients_count=len(target_player_ids),
        )
        session.add(reachout)
        session.flush()

        recipients = []
        for pid in target_player_ids:
            rec = SubstituteReachoutRecipient(reachout_id=reachout.id, player_id=pid)
            rec.generate_token()
            session.add(rec)
            recipients.append(rec)
        session.flush()
        # Persist the reach-out + recipients (with valid response tokens) BEFORE
        # dispatch, so a mid-send crash can't leave DMs out with tokens whose rows
        # were rolled back (unmatchable replies).
        session.commit()

        try:
            send_results = get_notification_service().send_reachout(reachout, recipients, session=session)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Error sending web reach-out: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Reach-out could not be sent'}), 500

        return jsonify({
            'success': True,
            'reachout_id': reachout.id,
            'recipients_count': len(recipients),
            'notifications_sent': send_results.get('sent', 0),
            'per_channel_counts': send_results.get('per_channel_counts', {}),
        })
