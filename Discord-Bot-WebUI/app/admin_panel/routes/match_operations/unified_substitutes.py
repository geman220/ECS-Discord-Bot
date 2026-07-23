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
# Who can OPEN the hub and REQUEST/EDIT/CANCEL (Pub League coaches request-only, so
# they get in here) — but NOT the admin-only actions (assign / reach-out / pool mgmt /
# settings keep their stricter lists + can_assign, so a coach is still denied there).
HUB_ROLES = ADMIN_ROLES + ['Pub League Coach']

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


def _coerce_setting(value, dtype, default):
    """Coerce a stored AdminConfig value to its declared type for the template.

    parsed_value returns None for an integer whose stored string is empty/bad
    (see AdminConfig._parse_value) — which rendered the Settings tab's poll
    day/time as blank. Coercing here guarantees weekday/hour are real ints so
    the <select>/<input> bind, and every value round-trips as its schema type.
    """
    if value is None:
        return default
    try:
        if dtype == 'boolean':
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ('true', '1', 'yes', 'on')
        if dtype == 'integer':
            return int(value)
        return str(value)
    except (TypeError, ValueError):
        return default


def _load_settings():
    """Read every schema key into a typed plain dict for the template."""
    out = {}
    for key, dtype, default in SETTINGS_SCHEMA:
        out[key] = _coerce_setting(AdminConfig.get_setting(key, default), dtype, default)
    return out


def _reconcile_poll_summaries(session, limit=20):
    """Lightweight recent availability-poll list for the in-hub Reconcile tab.

    Summary only (date, leagues, distinct voter count) — the heavy per-poll
    voter↔request cross-check stays behind the drill-in to substitute_reconcile.
    """
    from app.models.discord_polls import DiscordPoll, DiscordPollVote
    from sqlalchemy import func
    polls = (
        session.query(DiscordPoll)
        .filter(DiscordPoll.poll_kind == 'availability')
        .order_by(DiscordPoll.created_at.desc())
        .limit(limit)
        .all()
    )
    if not polls:
        return []
    ids = [p.id for p in polls]
    counts = dict(
        session.query(
            DiscordPollVote.poll_id,
            func.count(func.distinct(DiscordPollVote.discord_user_id)),
        )
        .filter(DiscordPollVote.poll_id.in_(ids), DiscordPollVote.removed_at.is_(None))
        .group_by(DiscordPollVote.poll_id)
        .all()
    )
    out = []
    for p in polls:
        slot_map = p.slot_map or {}
        leagues = sorted({b.get('league_type') for b in slot_map.values() if b.get('league_type')})
        out.append({
            'id': p.id,
            'title': p.title,
            'match_date': p.match_date,
            'created_at': p.created_at,
            'voters': counts.get(p.id, 0),
            'leagues': leagues,
            'message_url': p.discord_message_url,
        })
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
@role_required(HUB_ROLES)
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
        reconcile_polls = _reconcile_poll_summaries(db.session)

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
            reconcile_polls=reconcile_polls,
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
        # Admins may over-assign (more than requested) — no hard cap on count.
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
    # Admins may over-assign (more than requested) — no hard cap on count.

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
        from web_config import Config
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


def _discord_roles():
    """Return (roles, source) for the poll ping-role PICKER — the live Discord
    role list from the bot's /api/discord/roles (mirrors _discord_channels; sync
    `requests` per the gevent-web rule). Falls back to any saved role ids so the
    picker still renders their chips if the bot is unreachable."""
    saved = [r.strip() for r in (AdminConfig.get_setting('sub_poll_role_ids', '') or '').split(',') if r.strip()]
    try:
        import requests
        from web_config import Config
        url = f"{Config.BOT_API_URL.rstrip('/')}/api/discord/roles"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            body = resp.json()
            if body.get('success') and isinstance(body.get('roles'), list):
                roles = [{'id': str(r.get('id')), 'name': r.get('name')} for r in body['roles']]
                return roles, 'live'
    except Exception:
        logger.warning("Discord roles: bot unreachable, using saved ids", exc_info=True)
    # Fallback: at least show the saved ids so selection round-trips.
    return [{'id': rid, 'name': f'(role {rid})'} for rid in saved], 'fallback'


@admin_panel_bp.route('/substitutes/discord-roles')
@login_required
@role_required(ADMIN_ROLES)
def sub_discord_roles():
    """JSON role list for the ping-role picker (live from the bot, else saved-id fallback)."""
    roles, source = _discord_roles()
    return jsonify({'success': True, 'roles': roles, 'source': source})


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


@admin_panel_bp.route('/substitutes/reachout-reach', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def sub_reachout_reach():
    """Per-channel reach counts for a resolved recipient set — the blast-size
    preview the reach-out modal shows before sending.

    Body: {player_ids:[...]} -> {success, counts:{PUSH,DISCORD,SMS,EMAIL}, total}.

    Tallies get_player_channels per player (which channels COULD deliver to them).
    Respects the org SMS master switch: if 'sub_reachout_allow_sms' is off, SMS is
    reported as 0 regardless of per-recipient consent — matching what a send would do.
    Best-effort per player: one bad row never breaks the count.
    """
    from app.models import Player
    from app.services.substitute_notification_service import get_notification_service

    data = request.get_json(silent=True) or {}
    raw_ids = data.get('player_ids') or []
    try:
        player_ids = [int(p) for p in raw_ids]
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'player_ids must be integers'}), 400

    # Dedupe, preserve order.
    seen = set()
    player_ids = [p for p in player_ids if not (p in seen or seen.add(p))]

    counts = {'PUSH': 0, 'DISCORD': 0, 'SMS': 0, 'EMAIL': 0}
    total = 0
    if player_ids:
        allow_sms = str(AdminConfig.get_setting('sub_reachout_allow_sms', False)).lower() \
            in ('true', '1', 'yes', 'on')
        svc = get_notification_service()
        players = db.session.query(Player).filter(Player.id.in_(player_ids)).all()
        total = len(players)
        for p in players:
            try:
                ch = svc.get_player_channels(p) or {}
            except Exception:
                logger.debug("get_player_channels failed for player %s in reach count",
                             getattr(p, 'id', None), exc_info=True)
                continue
            if ch.get('PUSH'):
                counts['PUSH'] += 1
            if ch.get('DISCORD'):
                counts['DISCORD'] += 1
            if ch.get('EMAIL'):
                counts['EMAIL'] += 1
            if allow_sms and ch.get('SMS'):
                counts['SMS'] += 1

    return jsonify({'success': True, 'counts': counts, 'total': total})


# ===========================================================================
# Coach/Admin sub-REQUEST creation, cancel, and the request picker options.
#
# These let a coach (own team) or admin CREATE a sub request straight from the
# hub with position + gender (M/F) + amount + notes. Pub League requests land
# OPEN and are NOT auto-contacted (the coordinator broadcasts via reach-out /
# notify-pool). ECS FC requests fire the ECS FC pool notification inline — parity
# with the mobile ECS FC create — since ECS FC has no separate broadcast step.
# Authority is gated through substitute_authority.can_request.
# ===========================================================================

def _resolve_needed(raw):
    """Coerce a requested count to an int in 1..10, defaulting from the org-wide
    'sub_default_needed' Setting when omitted/invalid."""
    default_needed = AdminConfig.get_setting('sub_default_needed', 1)
    try:
        needed = int(raw) if raw not in (None, '') else int(default_needed)
    except (TypeError, ValueError):
        try:
            needed = int(default_needed)
        except (TypeError, ValueError):
            needed = 1
    return max(1, min(needed, 10))


def _normalize_gender_pref(raw):
    """'male'/'female' pass through; anything else (incl. '' / 'any') -> None."""
    gp = (raw or '').strip().lower()
    return gp if gp in ('male', 'female') else None


@admin_panel_bp.route('/substitutes/request-create', methods=['POST'])
@login_required
@role_required(HUB_ROLES)
@transactional
def sub_request_create():
    """Coach/admin sub-REQUEST creation from the hub.

    Body: {
        league: 'pub_league' | 'ecs_fc',
        team_id, match_id,
        positions_needed?, gender_preference? ('male'|'female'|''),
        substitutes_needed? (int; default AdminConfig 'sub_default_needed', clamp 1..10),
        notes?
    }
    Returns: {success, request_id, duplicate?}
    """
    from app.models import Team, Match
    from app.models.substitutes import SubstituteRequest, EcsFcSubRequest
    from app.services.substitute_authority import can_request

    data = request.get_json(silent=True) or {}
    league = (data.get('league') or 'pub_league').strip().lower()
    if league not in ('pub_league', 'ecs_fc'):
        return jsonify({'success': False, 'error': "league must be 'pub_league' or 'ecs_fc'"}), 400

    try:
        team_id = int(data.get('team_id'))
        match_id = int(data.get('match_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'team_id and match_id are required'}), 400

    positions_needed = (data.get('positions_needed') or '').strip() or None
    notes = (data.get('notes') or '').strip() or None
    gender_preference = _normalize_gender_pref(data.get('gender_preference'))
    substitutes_needed = _resolve_needed(data.get('substitutes_needed'))

    session = db.session
    program = 'ECS FC' if league == 'ecs_fc' else 'Pub League'
    if not can_request(session, current_user.id, team_id=team_id, program=program):
        return jsonify({'success': False,
                        'error': 'You are not authorized to request subs for this team'}), 403

    if league == 'ecs_fc':
        from app.models.ecs_fc import EcsFcMatch
        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({'success': False, 'error': 'Match not found'}), 404
        # An ECS FC match belongs to exactly one team.
        if match.team_id != team_id:
            return jsonify({'success': False, 'error': 'Team is not part of this match'}), 400
        existing = session.query(EcsFcSubRequest).filter(
            EcsFcSubRequest.match_id == match_id,
            EcsFcSubRequest.team_id == team_id,
            EcsFcSubRequest.status == 'OPEN',
        ).first()
        if existing:
            return jsonify({'success': True, 'request_id': existing.id, 'duplicate': True,
                            'message': 'An open request already exists for this match'}), 200
        sub_request = EcsFcSubRequest(
            match_id=match_id, team_id=team_id, requested_by=current_user.id,
            positions_needed=positions_needed, gender_preference=gender_preference,
            substitutes_needed=substitutes_needed, notes=notes, status='OPEN',
        )
        session.add(sub_request)
        session.flush()
        new_id = sub_request.id
        # Commit BEFORE notify: notify_ecs_fc_pool queries the request back on
        # db.session and commits its own EcsFcSubResponse rows.
        session.commit()
        try:
            from app.services.substitute_notification_service import SubstituteNotificationService
            SubstituteNotificationService().notify_ecs_fc_pool(
                request_id=new_id, custom_message=notes, subs_needed=substitutes_needed,
            )
        except Exception:
            logger.exception("Failed to notify ECS FC pool for request %s", new_id)
        return jsonify({'success': True, 'request_id': new_id})

    # Pub League — lands OPEN, coordinator broadcasts later (NO auto-contact here).
    match = session.query(Match).get(match_id)
    if not match:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    if match.home_team_id != team_id and match.away_team_id != team_id:
        return jsonify({'success': False, 'error': 'Team is not part of this match'}), 400
    existing = session.query(SubstituteRequest).filter(
        SubstituteRequest.match_id == match_id,
        SubstituteRequest.team_id == team_id,
        SubstituteRequest.status.in_(['OPEN', 'PENDING']),
    ).first()
    if existing:
        return jsonify({'success': True, 'request_id': existing.id, 'duplicate': True,
                        'message': 'An open request already exists for this match/team'}), 200

    # Resolve the division league_type (Classic/Premier).
    from app.utils.substitute_helpers import resolve_league_type_from_match
    league_type = resolve_league_type_from_match(match, session)
    if league_type in (None, '', 'Pub League'):
        team_obj = session.query(Team).get(team_id)
        league_type = team_obj.league.name if team_obj and team_obj.league else 'Classic'

    sub_request = SubstituteRequest(
        match_id=match_id, team_id=team_id, requested_by=current_user.id,
        league_type=league_type, positions_needed=positions_needed,
        gender_preference=gender_preference, substitutes_needed=substitutes_needed,
        notes=notes, status='OPEN', source='web',
    )
    session.add(sub_request)
    session.flush()
    return jsonify({'success': True, 'request_id': sub_request.id})


@admin_panel_bp.route('/substitutes/request-cancel', methods=['POST'])
@login_required
@role_required(HUB_ROLES)
@transactional
def sub_request_cancel():
    """Cancel a sub request from the hub.

    Body: {league:'pub_league'|'ecs_fc', request_id}
    Authority: admin, OR the original requester, OR a coach who can_request for the
    request's team. Sets status CANCELLED (+cancelled_at for Pub League), commits,
    then queues notify_substitute_request_cancelled (itself gated by the
    'sub_notify_on_cancel' Setting). Returns {success}.
    """
    from app.models.substitutes import SubstituteRequest, EcsFcSubRequest
    from app.services.substitute_authority import can_request

    data = request.get_json(silent=True) or {}
    league = (data.get('league') or 'pub_league').strip().lower()
    if league not in ('pub_league', 'ecs_fc'):
        return jsonify({'success': False, 'error': "league must be 'pub_league' or 'ecs_fc'"}), 400
    try:
        request_id = int(data.get('request_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'request_id is required'}), 400

    session = db.session
    program = 'ECS FC' if league == 'ecs_fc' else 'Pub League'
    Model = EcsFcSubRequest if league == 'ecs_fc' else SubstituteRequest
    req = session.query(Model).get(request_id)
    if not req:
        return jsonify({'success': False, 'error': 'Request not found'}), 404

    authorized = (
        is_admin(session, current_user.id)
        or req.requested_by == current_user.id
        or can_request(session, current_user.id, team_id=req.team_id, program=program)
    )
    if not authorized:
        return jsonify({'success': False,
                        'error': 'You are not authorized to cancel this request'}), 403

    if req.status not in ('OPEN', 'PENDING', 'APPROVED'):
        return jsonify({'success': False,
                        'error': f'Cannot cancel a request with status {req.status}'}), 409

    req.status = 'CANCELLED'
    # Only Pub League's SubstituteRequest carries cancelled_at.
    if hasattr(req, 'cancelled_at'):
        req.cancelled_at = datetime.utcnow()
    session.commit()

    try:
        from app.tasks.tasks_substitute_pools import notify_substitute_request_cancelled
        notify_substitute_request_cancelled.delay(request_id, league)
    except Exception:
        logger.exception("Failed to queue cancellation notice for %s request %s", league, request_id)

    return jsonify({'success': True})


@admin_panel_bp.route('/substitutes/request-edit', methods=['POST'])
@login_required
@role_required(HUB_ROLES)
@transactional
def sub_request_edit():
    """Edit an OPEN sub request's details (coach for their own team, or admin).

    Body: {league, request_id, positions_needed?, gender_preference?('male'|'female'|''),
           substitutes_needed?(int), notes?}. Same authority as cancel. Editable only
           while OPEN/PENDING/APPROVED. Team + match are NOT editable here (cancel + recreate
           to move a request). Returns {success}.
    """
    from app.models.substitutes import SubstituteRequest, EcsFcSubRequest
    from app.services.substitute_authority import can_request

    data = request.get_json(silent=True) or {}
    league = (data.get('league') or 'pub_league').strip().lower()
    if league not in ('pub_league', 'ecs_fc'):
        return jsonify({'success': False, 'error': "league must be 'pub_league' or 'ecs_fc'"}), 400
    try:
        request_id = int(data.get('request_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'request_id is required'}), 400

    session = db.session
    program = 'ECS FC' if league == 'ecs_fc' else 'Pub League'
    Model = EcsFcSubRequest if league == 'ecs_fc' else SubstituteRequest
    req = session.query(Model).get(request_id)
    if not req:
        return jsonify({'success': False, 'error': 'Request not found'}), 404

    authorized = (
        is_admin(session, current_user.id)
        or req.requested_by == current_user.id
        or can_request(session, current_user.id, team_id=req.team_id, program=program)
    )
    if not authorized:
        return jsonify({'success': False, 'error': 'You are not authorized to edit this request'}), 403
    if req.status not in ('OPEN', 'PENDING', 'APPROVED'):
        return jsonify({'success': False, 'error': f'Cannot edit a request with status {req.status}'}), 409

    if 'positions_needed' in data:
        req.positions_needed = (data.get('positions_needed') or '').strip() or None
    if 'gender_preference' in data:
        gp = (data.get('gender_preference') or '').strip().lower()
        req.gender_preference = gp if gp in ('male', 'female') else None
    if 'notes' in data:
        req.notes = (data.get('notes') or '').strip() or None
    if 'substitutes_needed' in data:
        try:
            req.substitutes_needed = max(1, min(int(data.get('substitutes_needed')), 10))
        except (TypeError, ValueError):
            pass

    session.commit()
    return jsonify({'success': True, 'request_id': request_id})


@admin_panel_bp.route('/substitutes/request-options')
@login_required
@role_required(HUB_ROLES)
def sub_request_options():
    """Teams + upcoming matches the current user may create a sub request for.

    Coaches see their own teams; admins additionally see all current-season teams
    across BOTH programs. Each team lists up to 6 upcoming REGULAR non-self matches.
    Returns: {teams:[{id, name, program:'pub_league'|'ecs_fc',
                       league_type:'Classic'|'Premier'|'ECS FC',
                       matches:[{id, label, date}]}]}
    """
    from app.models import Team, Match, League, Season
    from app.models.ecs_fc import EcsFcMatch
    from app.services.substitute_authority import coach_team_ids

    session = db.session
    today = datetime.now().date()
    MATCH_CAP = 6

    team_ids = set(coach_team_ids(session, current_user.id))
    if is_admin(session, current_user.id):
        rows = (
            session.query(Team.id)
            .join(League, Team.league_id == League.id)
            .join(Season, League.season_id == Season.id)
            .filter(Season.is_current == True)
            .all()
        )
        team_ids.update(tid for (tid,) in rows)

    if not team_ids:
        return jsonify({'success': True, 'teams': []})

    teams = session.query(Team).filter(Team.id.in_(team_ids)).all()
    out = []
    for team in teams:
        league = team.league
        lname = (league.name if league else '') or ''
        is_ecs = 'ECS FC' in lname
        program = 'ecs_fc' if is_ecs else 'pub_league'
        league_type = 'ECS FC' if is_ecs else (lname or 'Classic')

        matches = []
        if is_ecs:
            rows = session.query(EcsFcMatch).filter(
                EcsFcMatch.team_id == team.id,
                EcsFcMatch.match_date >= today,
            ).order_by(EcsFcMatch.match_date, EcsFcMatch.match_time).limit(MATCH_CAP).all()
            for m in rows:
                matches.append({
                    'id': m.id,
                    'label': f'vs {m.opponent_name}' if m.opponent_name else 'Match',
                    'date': m.match_date.isoformat() if m.match_date else None,
                })
        else:
            rows = session.query(Match).filter(
                ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
                Match.week_type == 'REGULAR',
                Match.home_team_id != Match.away_team_id,
                Match.date >= today,
            ).order_by(Match.date, Match.time).limit(MATCH_CAP).all()
            opp_ids = {
                (m.away_team_id if m.home_team_id == team.id else m.home_team_id)
                for m in rows
            }
            name_by_id = {}
            if opp_ids:
                for t in session.query(Team).filter(Team.id.in_(opp_ids)).all():
                    name_by_id[t.id] = t.name
            for m in rows:
                opp_id = m.away_team_id if m.home_team_id == team.id else m.home_team_id
                matches.append({
                    'id': m.id,
                    'label': f"vs {name_by_id.get(opp_id, 'TBD')}",
                    'date': m.date.isoformat() if m.date else None,
                })

        out.append({
            'id': team.id,
            'name': team.name,
            'program': program,
            'league_type': league_type,
            'matches': matches,
        })

    # Teams with upcoming matches first, then alphabetical.
    out.sort(key=lambda t: (not t['matches'], (t['name'] or '').lower()))
    return jsonify({'success': True, 'teams': out})
