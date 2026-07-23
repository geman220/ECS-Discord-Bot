# app/admin_panel/routes/user_management/member_hub.py

"""
Member Hub — the person-360 admin page (Phase 2 of the registration-lifecycle overhaul).

One screen for one person: approval + account, memberships (role/status per
league_type per season from the `league_membership` spine), sub status, payment,
quick-profile lineage, and Discord state. Read-model in
`app/services/member_hub_service.py`; actions link to the existing approve/deny/
sub-pool endpoints for now (inline transitions land in a later Phase-2 pass).

Design: ~/.claude/plans/registration-lifecycle-overhaul.md  §10.2
"""

import logging

from flask import render_template, jsonify, abort, request, url_for
from flask_login import login_required

from app.admin_panel import admin_panel_bp
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.services.member_hub_service import get_member_360

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/cutover-flags')
@login_required
@role_required(['Global Admin'])
def cutover_flags_page():
    """Parallel-run control: which subsystems read the new spine vs the legacy path.

    Defaults are the NEW system; turning a flag OFF fails back to legacy instantly
    (both are kept in sync by the dual-write, so no data is lost either way).
    """
    from app.services.cutover_flags import all_flags_status
    return render_template('admin_panel/cutover_flags_flowbite.html', flags=all_flags_status())


@admin_panel_bp.route('/cutover-flags/set', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def cutover_flags_set():
    """Toggle a cutover flag (True = new system, False = fail back to legacy)."""
    from app.services.cutover_flags import CUTOVER_FLAGS
    from app.models.admin_config import AdminConfig

    data = request.get_json(silent=True) or {}
    key = data.get('key') or request.form.get('key') or ''
    enabled = data.get('enabled')
    if enabled is None:
        enabled = request.form.get('enabled') in ('true', '1', 'on', True)

    if key not in CUTOVER_FLAGS:
        return jsonify({'success': False, 'message': 'Unknown cutover flag'}), 400

    # data_type='boolean' is REQUIRED: without it the value serializes as the string
    # "False", and bool("False") is True — so failback would never engage.
    AdminConfig.set_setting(key, bool(enabled), description=CUTOVER_FLAGS[key],
                            category='cutover', data_type='boolean')
    logger.info("Cutover flag %s set to %s by admin", key, bool(enabled))
    return jsonify({'success': True, 'key': key, 'enabled': bool(enabled),
                    'system': 'new (spine)' if enabled else 'legacy (failback)'})


def _sub_summary(session, sub_pids):
    """{player_id: [{'lane': 'Classic'|'Premier'|'ECS FC', 'status': 'active'|'resting'}]}
    for the Subs tab, from the live sub pools (Pub League SubstitutePool + EcsFcSubPool)."""
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.services.league_membership_sync import _norm_league_type
    if not sub_pids:
        return {}
    raw = {}
    for sp in session.query(SubstitutePool).filter(SubstitutePool.player_id.in_(sub_pids)).all():
        if sp.approved_at is None:
            continue
        raw.setdefault(sp.player_id, []).append(
            {'lane': sp.league_type, 'status': 'active' if sp.is_active else 'resting'})
    for ep in session.query(EcsFcSubPool).filter(EcsFcSubPool.player_id.in_(sub_pids)).all():
        raw.setdefault(ep.player_id, []).append(
            {'lane': 'ECS FC', 'status': 'active' if ep.is_active else 'resting'})
    # DEDUPE by normalized lane: an ECS FC sub commonly has BOTH a SubstitutePool('ECS FC')
    # twin AND an EcsFcSubPool row, which would otherwise render "ECS FC" twice. Active wins.
    summary = {}
    for pid, rows in raw.items():
        by_lane = {}
        for r in rows:
            key = _norm_league_type(r['lane']) or r['lane']
            if key not in by_lane or (r['status'] == 'active' and by_lane[key]['status'] != 'active'):
                by_lane[key] = r
        summary[pid] = list(by_lane.values())
    return summary


@admin_panel_bp.route('/members')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def members_worklist():
    """Members — the unified, SELF-CONTAINED member command center.

    The NEW primary surface for the whole person lifecycle. Tabs:
      * All Members    — every user, searchable/filterable, paginated (reach + manage anyone)
      * Pending Approval / Waitlist / Subs / Quick Profiles — the intake queues
    Every row links to the person's Member Hub (the single manage surface); the intake
    tabs also carry inline actions. Reuses the SAME shared query criteria + service
    endpoints as the legacy pages so nothing drifts. The legacy pages stay reachable from
    the old nav purely as burn-in fallback — this surface never links INTO them.
    """
    from datetime import datetime, timedelta
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload
    from app.core import db
    from app.models import User, Role, QuickProfile, Player, League, Season
    from app.models.quick_profile import QuickProfileStatus
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.services.league_membership_sync import _norm_league_type

    tab = (request.args.get('tab') or 'all').strip()
    search = (request.args.get('search') or '').strip()
    role_filter = (request.args.get('role') or '').strip()
    league_filter = (request.args.get('league') or '').strip()
    approval_filter = (request.args.get('approval') or '').strip()      # '' hides DENIED by default
    active_filter = (request.args.get('active') or '').strip()          # account active/disabled
    season_filter = (request.args.get('season') or '').strip()          # active this season y/n
    lane_filter = (request.args.get('lane') or '').strip()              # classic/premier/ecs_fc/undecided
    sub_status_filter = (request.args.get('sub_status') or '').strip()  # active/resting
    qp_status = (request.args.get('qp_status') or 'pending').strip()    # pending/claimed/linked/expired/all
    page = request.args.get('page', 1, type=int)
    now = datetime.utcnow()

    def _lane_clause(col, lane):
        """ilike pattern so a lane matches stored variants ('Classic'/'pub_league_classic')."""
        if lane == 'classic':
            return col.ilike('%classic%')
        if lane == 'premier':
            return col.ilike('%premier%')
        if lane == 'ecs_fc':
            return col.ilike('%ecs%')
        return None

    # --- shared queue criteria (identical to the legacy pages, so counts can't drift) ---
    # DENIED people are excluded from the waitlist everywhere (count + list): a denied person
    # will not play, so they only surface via the All tab's explicit "Denied" filter — you have
    # to go FIND them, they don't clutter the live queues.
    not_denied = or_(User.approval_status != 'denied', User.approval_status.is_(None))
    pending_q = db.session.query(User).filter(*User.pending_approval_criteria())
    waitlist_q = (db.session.query(User).join(User.roles)
                  .filter(Role.name == 'pl-waitlist', not_denied))
    quick_pending_q = db.session.query(QuickProfile).filter(
        QuickProfile.status == QuickProfileStatus.PENDING.value,
        or_(QuickProfile.expires_at.is_(None), QuickProfile.expires_at > now),
    )
    sub_pids = set()
    for (pid,) in db.session.query(SubstitutePool.player_id).filter(SubstitutePool.approved_at.isnot(None)).all():
        if pid:
            sub_pids.add(pid)
    for (pid,) in db.session.query(EcsFcSubPool.player_id).all():
        if pid:
            sub_pids.add(pid)
    # Exclude DENIED players from the sub set at the SOURCE so the count, KPI chips and the
    # rendered list all agree (denied people are hidden from live queues everywhere).
    if sub_pids:
        denied_pids = {pid for (pid,) in db.session.query(Player.id)
                       .join(User, User.id == Player.user_id)
                       .filter(Player.id.in_(sub_pids), User.approval_status == 'denied').all()}
        sub_pids -= denied_pids

    thirty_days_ago = now - timedelta(days=30)
    stats = {
        'total_members': db.session.query(User).count(),
        'active_players': db.session.query(Player).filter(Player.is_current_player == True).count(),
        'pending': pending_q.count(),
        'waitlist': waitlist_q.count(),
        'subs': len(sub_pids),
        'quick': quick_pending_q.count(),
        'approved': db.session.query(User).filter(User.is_approved == True).count(),
        'recent': db.session.query(User).filter(User.created_at >= thirty_days_ago).count(),
    }
    counts = {'all': stats['total_members'], 'pending': stats['pending'],
              'waitlist': stats['waitlist'], 'subs': stats['subs'], 'quick': stats['quick']}

    all_roles = db.session.query(Role).order_by(Role.name).all()
    all_leagues = (db.session.query(League).options(joinedload(League.teams))
                   .join(Season).filter(Season.is_current == True).order_by(League.name).all())

    # ---- Analytics view (folded in from the old /users/analytics page) ----
    # The user-ACCOUNT lifecycle: growth, approval funnel, role/league mix. It lives
    # here beside the intake queues it summarizes, sharing the same shell + tab bar.
    # Early-return before the per-tab worklist queries — none of them apply.
    if tab == 'analytics':
        from app.admin_panel.routes.user_management.helpers import get_user_analytics
        return render_template('admin_panel/members/analytics_flowbite.html',
                               tab='analytics', counts=counts, stats=stats,
                               analytics_data=get_user_analytics())

    users, profiles, pagination, sub_summary = [], [], None, {}

    if tab == 'waitlist':
        wq = waitlist_q.options(joinedload(User.player))
        if search:
            like = f'%{search}%'
            wq = wq.outerjoin(Player, Player.user_id == User.id).filter(
                or_(Player.name.ilike(like), User.username.ilike(like)))
        if lane_filter == 'undecided':
            wq = wq.filter(or_(User.waitlist_league.is_(None), User.waitlist_league == '',
                               User.waitlist_league.ilike('%not_sure%')))
        elif lane_filter:
            c = _lane_clause(User.waitlist_league, lane_filter)
            if c is not None:
                wq = wq.filter(c)
        users = wq.order_by(User.waitlist_joined_at.asc().nullslast()).all()

    elif tab == 'quick':
        pq = db.session.query(QuickProfile)
        if qp_status and qp_status != 'all':
            pq = pq.filter(QuickProfile.status == qp_status)
        if search:
            pq = pq.filter(QuickProfile.player_name.ilike(f'%{search}%'))
        profiles = pq.order_by(QuickProfile.created_at.desc()).limit(500).all()

    elif tab == 'subs':
        if sub_pids:
            sq = (db.session.query(User).options(joinedload(User.player), joinedload(User.roles))
                  .join(Player, Player.user_id == User.id)
                  .filter(Player.id.in_(sub_pids), not_denied))
            if search:
                like = f'%{search}%'
                sq = sq.filter(or_(Player.name.ilike(like), User.username.ilike(like)))
            users = sq.order_by(Player.name).all()
            sub_summary = _sub_summary(db.session, sub_pids)
            if lane_filter or sub_status_filter:
                def _keep(u):
                    for r in (sub_summary.get(u.player.id, []) if u.player else []):
                        lane_ok = (not lane_filter) or (_norm_league_type(r['lane']) == lane_filter)
                        stat_ok = (not sub_status_filter) or (r['status'] == sub_status_filter)
                        if lane_ok and stat_ok:
                            return True
                    return False
                users = [u for u in users if _keep(u)]

    elif tab == 'pending':
        pq = pending_q.options(joinedload(User.player), joinedload(User.roles))
        if search:
            like = f'%{search}%'
            pq = pq.outerjoin(Player, Player.user_id == User.id).filter(
                or_(Player.name.ilike(like), User.username.ilike(like)))
        if lane_filter:
            clauses = [c for c in (_lane_clause(User.approval_league, lane_filter),
                                   _lane_clause(User.preferred_league, lane_filter)) if c is not None]
            if clauses:
                pq = pq.filter(or_(*clauses))
        users = pq.order_by(User.created_at.desc()).all()

    else:
        tab = 'all'
        q = db.session.query(User).options(joinedload(User.roles), joinedload(User.player))
        if search:
            like = f'%{search}%'
            from app.utils.pii_encryption import create_hash
            email_hash = create_hash(search.lower()) if '@' in search else None
            if email_hash:
                q = q.filter(or_(User.username.ilike(like), User.email_hash == email_hash))
            else:
                q = q.outerjoin(Player, Player.user_id == User.id).filter(
                    or_(Player.name.ilike(like), User.username.ilike(like)))
        if role_filter:
            q = q.join(User.roles).filter(Role.name == role_filter)
        # Approval: DENIED are hidden by default (empty filter); opt in to see them.
        if approval_filter == 'approved':
            q = q.filter(User.is_approved == True)
        elif approval_filter == 'pending':
            q = q.filter(User.approval_status == 'pending')
        elif approval_filter == 'denied':
            q = q.filter(User.approval_status == 'denied')
        elif approval_filter != 'all':
            q = q.filter(or_(User.approval_status != 'denied', User.approval_status.is_(None)))
        if active_filter == 'true':
            q = q.filter(User.is_active == True)
        elif active_filter == 'false':
            q = q.filter(or_(User.is_active == False, User.is_active == None))
        # Active THIS SEASON = the player is a current player.
        if season_filter == 'active':
            q = q.filter(User.player.has(Player.is_current_player == True))
        elif season_filter == 'inactive':
            q = q.filter(or_(~User.player.has(), User.player.has(Player.is_current_player == False)))
        if league_filter:
            try:
                lid = int(league_filter)
                q = q.filter(User.player.has(or_(Player.league_id == lid, Player.primary_league_id == lid)))
            except (ValueError, TypeError):
                pass
        q = q.order_by(User.username)
        pagination = q.paginate(page=page, per_page=50, error_out=False)
        users = pagination.items

    # Waitlist open now? Gates the waitlist approve/pre-approve options (closed in break/offseason).
    try:
        from app.services.season_phase_service import is_waitlist_open
        waitlist_open = bool(is_waitlist_open(db.session))
    except Exception:
        waitlist_open = True

    any_filter = any([search, role_filter, league_filter, approval_filter, active_filter,
                      season_filter, lane_filter, sub_status_filter,
                      (qp_status and qp_status != 'pending')])

    # Active-filter chips: each links to the SAME view minus that one filter, so an admin
    # always sees WHAT is narrowing the list and can drop filters one at a time.
    _APPROVAL_LBL = {'approved': 'Approved', 'pending': 'Pending', 'denied': 'Denied', 'all': 'Incl. denied'}
    _ACTIVE_LBL = {'true': 'Enabled', 'false': 'Disabled'}
    _SEASON_LBL = {'active': 'Playing this season', 'inactive': 'Not active'}
    _LANE_LBL2 = {'classic': 'Classic', 'premier': 'Premier', 'ecs_fc': 'ECS FC', 'undecided': 'Undecided'}
    _SUBST_LBL = {'active': 'Active subs', 'resting': 'Resting subs'}
    _league_name = next((lg.name for lg in all_leagues if str(lg.id) == str(league_filter)), None)
    _params = [
        ('search', search, ('“%s”' % search) if search else None),
        ('role', role_filter, ('Role: %s' % role_filter) if role_filter else None),
        ('approval', approval_filter, _APPROVAL_LBL.get(approval_filter)),
        ('season', season_filter, _SEASON_LBL.get(season_filter)),
        ('active', active_filter, _ACTIVE_LBL.get(active_filter)),
        ('league', league_filter, ('League: %s' % (_league_name or ('#' + str(league_filter)))) if league_filter else None),
        ('lane', lane_filter, _LANE_LBL2.get(lane_filter)),
        ('sub_status', sub_status_filter, _SUBST_LBL.get(sub_status_filter)),
        ('qp_status', (qp_status if qp_status != 'pending' else ''),
         (qp_status.title() if (qp_status and qp_status != 'pending') else None)),
    ]

    def _url_drop(drop):
        kw = {'tab': tab}
        for p, val, _lbl in _params:
            if p != drop and val:
                kw[p] = val
        return url_for('admin_panel.members_worklist', **kw)

    active_chips = [{'label': lbl, 'remove_url': _url_drop(p)} for p, val, lbl in _params if val and lbl]
    result_total = pagination.total if pagination else (len(profiles) if tab == 'quick' else len(users))
    result_shown = len(profiles) if tab == 'quick' else len(users)

    # --- flow metrics (time / % / age) — informational, shown as non-filter stat chips ---
    from sqlalchemy import func as _func

    def _stat(label, value, tone='info', icon=None, hint=None):
        return {'label': label, 'value': value, 'tone': tone, 'stat': True, 'icon': icon, 'hint': hint}

    # func.avg(func.extract(...)) returns a Decimal in PostgreSQL — cast before float math.
    # Whole block guarded: these metrics are informational and must never 500 the page.
    try:
        _appr_secs = (db.session.query(_func.avg(_func.extract('epoch', User.approved_at - User.created_at)))
                      .filter(User.approved_at.isnot(None), User.approved_at >= now - timedelta(days=180),
                              User.approved_at >= User.created_at).scalar())
        avg_approve_days = round(float(_appr_secs or 0) / 86400.0, 1)
    except Exception:
        logger.exception("members: avg approve time failed")
        avg_approve_days = 0
    try:
        approved_30d = db.session.query(User).filter(User.approved_at.isnot(None),
                                                     User.approved_at >= thirty_days_ago).count()
    except Exception:
        approved_30d = 0
    conversion_pct = round(stats['approved'] / stats['total_members'] * 100) if stats['total_members'] else 0

    # --- per-tab KPI strip (filter chips = counts; stat chips = time/%/age) ---
    tab_kpis = []
    if tab == 'quick':
        qb = db.session.query(QuickProfile)
        qp_counts = {}
        for lbl, st, tone in [('Pending', 'pending', 'warning'), ('Claimed', 'claimed', 'success'),
                              ('Linked', 'linked', 'info'), ('Expired', 'expired', 'danger')]:
            cnt = qb.filter(QuickProfile.status == st).count()
            qp_counts[st] = cnt
            tab_kpis.append({'label': lbl, 'value': cnt, 'tone': tone, 'param': 'qp_status', 'val': st})
        _tot_qp = sum(qp_counts.values())
        _claimed_rate = round((qp_counts.get('claimed', 0) + qp_counts.get('linked', 0)) / _tot_qp * 100) if _tot_qp else 0
        tab_kpis.append(_stat('claimed', f'{_claimed_rate}%', 'success', 'ti-trending-up',
                              'Claimed or linked, of all quick profiles'))
    elif tab == 'waitlist':
        for lbl, lane, tone in [('Classic', 'classic', 'info'), ('Premier', 'premier', 'gold'),
                                ('ECS FC', 'ecs_fc', 'success')]:
            c = _lane_clause(User.waitlist_league, lane)
            tab_kpis.append({'label': lbl, 'value': (waitlist_q.filter(c).count() if c is not None else 0),
                             'tone': tone, 'param': 'lane', 'val': lane})
        und = waitlist_q.filter(or_(User.waitlist_league.is_(None), User.waitlist_league == '',
                                    User.waitlist_league.ilike('%not_sure%'))).count()
        tab_kpis.append({'label': 'Undecided', 'value': und, 'tone': 'neutral', 'param': 'lane', 'val': 'undecided'})
        _wl_dates = [d for (d,) in waitlist_q.with_entities(User.waitlist_joined_at).all() if d]
        if _wl_dates:
            tab_kpis.append(_stat('avg wait', f'{round(sum((now - d).days for d in _wl_dates) / len(_wl_dates), 1)}d',
                                  'info', 'ti-hourglass', 'Avg days current waitlisters have waited'))
            tab_kpis.append(_stat('oldest', f'{max((now - d).days for d in _wl_dates)}d',
                                  'warning', 'ti-clock', 'Longest anyone has been waiting'))
    elif tab == 'subs':
        full = _sub_summary(db.session, sub_pids)
        active_ct = sum(1 for pid in full if any(r['status'] == 'active' for r in full[pid]))
        lane_ct = {'classic': 0, 'premier': 0, 'ecs_fc': 0}
        for rows in full.values():
            for r in rows:
                n = _norm_league_type(r['lane'])
                if n in lane_ct:
                    lane_ct[n] += 1
        tab_kpis = [
            {'label': 'Active', 'value': active_ct, 'tone': 'success', 'param': 'sub_status', 'val': 'active'},
            {'label': 'Resting', 'value': max(len(full) - active_ct, 0), 'tone': 'neutral', 'param': 'sub_status', 'val': 'resting'},
            {'label': 'Classic', 'value': lane_ct['classic'], 'tone': 'info', 'param': 'lane', 'val': 'classic'},
            {'label': 'Premier', 'value': lane_ct['premier'], 'tone': 'gold', 'param': 'lane', 'val': 'premier'},
            {'label': 'ECS FC', 'value': lane_ct['ecs_fc'], 'tone': 'success', 'param': 'lane', 'val': 'ecs_fc'},
        ]
    elif tab == 'pending':
        for lbl, lane, tone in [('Classic', 'classic', 'info'), ('Premier', 'premier', 'gold'),
                                ('ECS FC', 'ecs_fc', 'success')]:
            clauses = [c for c in (_lane_clause(User.approval_league, lane),
                                   _lane_clause(User.preferred_league, lane)) if c is not None]
            tab_kpis.append({'label': lbl, 'value': (pending_q.filter(or_(*clauses)).count() if clauses else 0),
                             'tone': tone, 'param': 'lane', 'val': lane})
        _op = pending_q.order_by(User.created_at.asc()).first()
        if _op and _op.created_at:
            tab_kpis.append(_stat('oldest waiting', f'{(now - _op.created_at).days}d', 'warning', 'ti-clock',
                                  'How long the oldest pending application has waited'))
        tab_kpis.append(_stat('avg approve', f'{avg_approve_days}d', 'info', 'ti-hourglass',
                              'Avg days from signup to approval (last 180d)'))
    elif tab == 'all':
        tab_kpis = [
            {'label': 'Approved', 'value': stats['approved'], 'tone': 'success', 'param': 'approval', 'val': 'approved'},
            {'label': 'Playing now', 'value': stats['active_players'], 'tone': 'primary', 'param': 'season', 'val': 'active'},
            {'label': 'Pending', 'value': stats['pending'], 'tone': 'warning', 'param': 'approval', 'val': 'pending'},
            _stat('conversion', f'{conversion_pct}%', 'success', 'ti-trending-up', 'Approved, of all members'),
            _stat('avg approve', f'{avg_approve_days}d', 'info', 'ti-hourglass', 'Avg days signup → approval (last 180d)'),
            _stat('approved 30d', approved_30d, 'primary', 'ti-user-check', 'Approved in the last 30 days'),
            _stat('new 30d', stats['recent'], 'neutral', 'ti-sparkles', 'New sign-ups in the last 30 days'),
        ]

    return render_template('admin_panel/members/worklist_flowbite.html',
                           tab=tab, search=search, counts=counts, stats=stats,
                           users=users, profiles=profiles, pagination=pagination,
                           sub_summary=sub_summary, roles=all_roles, leagues=all_leagues,
                           role_filter=role_filter, league_filter=league_filter,
                           approval_filter=approval_filter, active_filter=active_filter,
                           season_filter=season_filter, lane_filter=lane_filter,
                           sub_status_filter=sub_status_filter, qp_status=qp_status,
                           any_filter=any_filter, tab_kpis=tab_kpis, waitlist_open=waitlist_open,
                           active_chips=active_chips, result_total=result_total, result_shown=result_shown)


@admin_panel_bp.route('/members/<int:user_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def member_hub(user_id):
    """Render the Member Hub person-360 page."""
    data = get_member_360(user_id)
    if data is None:
        abort(404)
    # Extra data for the inline user-management controls (roles + team placement).
    from app.core import db
    from app.models import User, Role, League, Season
    from sqlalchemy.orm import joinedload
    user = db.session.get(User, user_id)
    all_roles = db.session.query(Role).order_by(Role.name).all()
    user_role_ids = {r.id for r in user.roles} if user else set()
    leagues = (db.session.query(League).options(joinedload(League.teams))
               .join(Season).filter(Season.is_current == True)
               .order_by(League.name).all())
    primary_team_id = user.player.primary_team_id if (user and user.player) else None
    # Unique teams the player is on (a team can appear as both player + coach rows).
    _seen = {}
    for c in data.get('current_memberships', []):
        tid = c.get('team_id')
        if tid and tid not in _seen:
            _seen[tid] = {'team_id': tid, 'team_name': c.get('team_name'), 'lane_label': c.get('lane_label')}
    hub_teams = list(_seen.values())
    extras = _member_admin_extras(db.session, user)
    return render_template('admin_panel/members/member_hub_flowbite.html', m=data,
                           all_roles=all_roles, user_role_ids=user_role_ids, leagues=leagues,
                           primary_team_id=primary_team_id, hub_teams=hub_teams, extras=extras)


_AUDIT_LABELS = {
    'edit_user_comprehensive': 'Profile edited',
    'approve_user': 'Approved', 'approve_user_comprehensive': 'Approved',
    'user_approval': 'Approval decision',
    'deny_user': 'Denied',
    'assign_user_role': 'Roles changed', 'assign_user_roles': 'Roles changed',
    'remove_from_waitlist': 'Removed from waitlist',
    'update_waitlist_priority': 'Waitlist priority set',
    'activate_user_comprehensive': 'Account enabled',
    'deactivate_user_comprehensive': 'Account disabled',
    'delete_user': 'Account deleted',
    'member_place': 'Team placement changed',
    'member_sub_assign': 'Added to sub pool', 'member_sub_remove': 'Removed from sub pool',
}


def _humanize_audit(action, new_value):
    """Turn a raw audit row (function-name action + dict/str new_value) into a friendly
    (label, detail) pair — no raw `{'username': ...}` dumps on the member hub."""
    label = _AUDIT_LABELS.get(action, (action or 'change').replace('_', ' ').capitalize())
    raw = (new_value or '').strip()
    if not raw:
        return label, ''
    # Dict-ish payload (e.g. the comprehensive edit) -> summarize the meaningful fields.
    if raw.startswith('{'):
        try:
            import ast
            v = ast.literal_eval(raw)
            if isinstance(v, dict):
                parts = []
                if 'is_approved' in v:
                    parts.append('approved' if v['is_approved'] else 'not approved')
                if 'is_active' in v:
                    parts.append('active' if v['is_active'] else 'disabled')
                if v.get('approval_league'):
                    parts.append(str(v['approval_league']))
                if isinstance(v.get('roles'), list):
                    parts.append(f"{len(v['roles'])} role" + ('s' if len(v['roles']) != 1 else ''))
                return label, ' · '.join(parts)
        except Exception:
            pass
        return label, ''
    # Simple "approved:classic" / "waitlist:classic" style -> tidy separator.
    return label, raw.replace(':', ' · ').replace('_', ' ')[:80]


def _member_admin_extras(session, user):
    """The 'who is this person' admin record: order history, team/season history, per-season
    stats, the approver, and the audit trail. All read-only + guarded so a single missing
    table never blanks the hub. Returns a dict of lists/values for the template."""
    out = {'orders': [], 'team_history': [], 'season_stats': [], 'audit': [],
           'approver': None, 'metrics': None}
    if user is None:
        return out
    player = getattr(user, 'player', None)

    # Approver (authoritative "who approved" from the user record).
    try:
        if getattr(user, 'approved_by', None):
            from app.models import User as _U
            ap = session.get(_U, user.approved_by)
            out['approver'] = ap.username if ap else None
    except Exception:
        logger.exception("member extras: approver lookup failed")

    # Season-pass order history (orders where this user is the primary buyer).
    try:
        from app.models.pub_league_order import PubLeagueOrder
        orders = (session.query(PubLeagueOrder)
                  .filter(PubLeagueOrder.primary_user_id == user.id)
                  .order_by(PubLeagueOrder.created_at.desc()).limit(25).all())
        out['orders'] = [{
            'woo_order_id': o.woo_order_id,
            'season_name': o.season_name or (o.season.name if o.season else '—'),
            'status': o.status,
            'total_passes': o.total_passes,
            'linked_passes': o.linked_passes,
            'created_at': o.created_at.strftime('%Y-%m-%d') if o.created_at else '—',
        } for o in orders]
    except Exception:
        logger.exception("member extras: orders failed")

    if player is not None:
        # Team + season history (every season this player was rostered), with the team's
        # league so Classic->Premier movement is visible.
        try:
            from app.models.players import PlayerTeamSeason
            from app.models import Team, Season, League
            rows = (session.query(PlayerTeamSeason, Team.name, Season.name, League.name)
                    .join(Team, Team.id == PlayerTeamSeason.team_id)
                    .join(Season, Season.id == PlayerTeamSeason.season_id)
                    .outerjoin(League, League.id == Team.league_id)
                    .filter(PlayerTeamSeason.player_id == player.id)
                    .order_by(PlayerTeamSeason.season_id.desc()).all())
            out['team_history'] = [{
                'season_name': sname, 'team_name': tname, 'league': lname, 'is_coach': pts.is_coach,
            } for pts, tname, sname, lname in rows]
        except Exception:
            logger.exception("member extras: team history failed")

        # Engagement + performance metrics for the per-person review.
        try:
            out['metrics'] = _member_metrics(session, player, out['team_history'])
        except Exception:
            logger.exception("member extras: metrics failed")

        # Per-season stats.
        try:
            from app.models.stats import PlayerSeasonStats
            from app.models import Season
            srows = (session.query(PlayerSeasonStats, Season.name)
                     .outerjoin(Season, Season.id == PlayerSeasonStats.season_id)
                     .filter(PlayerSeasonStats.player_id == player.id)
                     .order_by(PlayerSeasonStats.season_id.desc()).all())
            out['season_stats'] = [{
                'season_name': sname or '—', 'goals': st.goals or 0, 'assists': st.assists or 0,
                'yellow': st.yellow_cards or 0, 'red': st.red_cards or 0,
            } for st, sname in srows]
        except Exception:
            logger.exception("member extras: season stats failed")

    # Audit trail — admin actions recorded against this user id.
    try:
        from app.models import AdminAuditLog, User as _U2
        from sqlalchemy.orm import joinedload
        rows = (session.query(AdminAuditLog).options(joinedload(AdminAuditLog.user))
                .filter(AdminAuditLog.resource_type.in_(
                    ['user', 'user_approval', 'user_management', 'user_waitlist', 'role']),
                    AdminAuditLog.resource_id == str(user.id))
                .order_by(AdminAuditLog.timestamp.desc()).limit(20).all())
        _audit = []
        for a in rows:
            label, detail = _humanize_audit(a.action, a.new_value)
            _audit.append({
                'action': label,
                'actor': (a.user.username if getattr(a, 'user', None) else 'system'),
                'when': a.timestamp.strftime('%Y-%m-%d %H:%M') if a.timestamp else '',
                'detail': detail,
            })
        out['audit'] = _audit
    except Exception:
        logger.exception("member extras: audit failed")

    return out


def _member_metrics(session, player, team_history):
    """Engagement + performance metrics for the single-person review: RSVP/attendance
    reliability, sub responsiveness, retention (seasons + league path), and the Classic
    coach-rating trend season-to-season. All guarded — a hiccup returns partial data."""
    m = {'attendance': None, 'sub': None, 'ratings_by_season': [],
         'seasons_played': 0, 'league_path': []}

    # Retention: distinct seasons played + the league path (Classic -> Premier movement).
    seen = []
    seen_names = set()
    for h in team_history:
        sn = h.get('season_name')
        if sn and sn not in seen_names:
            seen_names.add(sn)
            seen.append({'season': sn, 'league': h.get('league')})
    m['seasons_played'] = len(seen)
    m['league_path'] = list(reversed(seen))  # chronological (oldest -> newest)

    # RSVP / attendance reliability — pre-aggregated on PlayerAttendanceStats.
    st = getattr(player, 'attendance_stats', None)
    if st is not None:
        m['attendance'] = {
            'response_rate': round(st.response_rate or 0, 1),
            'attendance_rate': round(st.attendance_rate or 0, 1),
            'adjusted_rate': round(st.adjusted_attendance_rate or 0, 1),
            'reliability': round(st.reliability_score or 0, 1),
            'invited': st.total_matches_invited or 0,
            'responses': st.total_responses or 0,
            'yes': st.yes_responses or 0,
            'no_response': st.no_response_count or 0,
            'season_rate': round(st.season_attendance_rate or 0, 1),
            'last_match': st.last_match_date.strftime('%Y-%m-%d') if st.last_match_date else None,
        }

    # Sub responsiveness (Pub League pool + ECS FC pool combined).
    try:
        from app.models.substitutes import SubstitutePool, EcsFcSubPool
        sp = session.query(SubstitutePool).filter_by(player_id=player.id).first()
        ep = session.query(EcsFcSubPool).filter_by(player_id=player.id).first()
        if sp or ep:
            recv = (sp.requests_received if sp else 0) + (ep.requests_received if ep else 0)
            acc = (sp.requests_accepted if sp else 0) + (ep.requests_accepted if ep else 0)
            played = (sp.matches_played if sp else 0) + (ep.matches_played if ep else 0)
            m['sub'] = {'received': recv, 'accepted': acc, 'played': played,
                        'accept_rate': round((acc / recv * 100), 1) if recv else 0.0}
    except Exception:
        logger.exception("member metrics: sub failed")

    # Classic coach-rating trend — averages come from the rating service (source of truth).
    try:
        from app.models.ratings import PlayerSeasonRating
        from app.models import Season
        from app.services.classic_rating_service import get_player_averages
        sids = [r[0] for r in session.query(PlayerSeasonRating.season_id)
                .filter_by(player_id=player.id).distinct().all()]
        if sids:
            names = dict(session.query(Season.id, Season.name).filter(Season.id.in_(sids)).all())

            def _v(avgs, key):
                a = avgs.get(key, {}).get('avg')
                return round(float(a), 2) if a is not None else None

            for sid in sorted(sids, reverse=True):
                avgs = get_player_averages(session, sid, [player.id]).get(player.id, {})
                m['ratings_by_season'].append({
                    'season_name': names.get(sid, '—'),
                    'intensity': _v(avgs, 'intensity'),
                    'on_ball': _v(avgs, 'on_ball_skill'),
                    'spirit': _v(avgs, 'spirit'),
                    'knowledge': _v(avgs, 'knowledge_movement'),
                    'raters': max((avgs.get(k, {}).get('count', 0) or 0 for k in avgs), default=0),
                })
    except Exception:
        logger.exception("member metrics: classic ratings failed")

    return m


@admin_panel_bp.route('/members/<int:user_id>/data')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def member_hub_data(user_id):
    """JSON snapshot of the Member Hub view (for live refresh after an action)."""
    data = get_member_360(user_id)
    if data is None:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    return jsonify({'success': True, 'member': data})


@admin_panel_bp.route('/members/<int:user_id>/note', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def member_add_note(user_id):
    """Add an admin/coach/NAD note to this person (PlayerAdminNote thread)."""
    from flask_login import current_user
    from app.core import db
    from app.models import User
    from app.models.players import PlayerAdminNote

    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'message': 'Note cannot be empty'}), 400

    user = db.session.get(User, user_id)
    if not user or not user.player:
        return jsonify({'success': False, 'message': 'This person has no player record to note against'}), 400

    note = PlayerAdminNote(player_id=user.player.id,
                           author_id=getattr(current_user, 'id', None),
                           content=content)
    db.session.add(note)
    db.session.flush()
    return jsonify({'success': True, 'note': {
        'id': note.id, 'content': note.content,
        'author': getattr(current_user, 'username', 'you'),
        'created_at': note.created_at.strftime('%Y-%m-%d %H:%M') if note.created_at else 'just now',
    }})


@admin_panel_bp.route('/members/<int:user_id>/note/<int:note_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def member_delete_note(user_id, note_id):
    """Delete one admin note from this person's thread."""
    from app.core import db
    from app.models import User
    from app.models.players import PlayerAdminNote

    note = db.session.get(PlayerAdminNote, note_id)
    if not note:
        return jsonify({'success': False, 'message': 'Note not found'}), 404
    # Ownership guard (no cross-member note deletion via a mismatched URL).
    user = db.session.get(User, user_id)
    if not user or not user.player or note.player_id != user.player.id:
        return jsonify({'success': False, 'message': 'Note does not belong to this member'}), 400
    db.session.delete(note)
    return jsonify({'success': True})


@admin_panel_bp.route('/members/quick-profile/<int:profile_id>/detail')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def member_qp_detail(profile_id):
    """Quick-profile detail + its admin-note thread (self-contained, for the Members quick tab).

    PlayerAdminNote targets EITHER a player or a quick_profile; a walk-in has notes on the
    quick_profile_id until it's claimed, at which point they migrate to the player (see
    QuickProfile.mark_claimed). So a pending/expired profile's coach/admin notes live here."""
    from app.core import db
    from app.models import QuickProfile
    from app.models.players import PlayerAdminNote
    from sqlalchemy.orm import joinedload

    profile = db.session.get(QuickProfile, profile_id)
    if not profile:
        return jsonify({'success': False, 'message': 'Quick profile not found'}), 404
    data = profile.to_dict()
    if profile.claimed_by_player:
        data['linked_player'] = {'id': profile.claimed_by_player.id,
                                 'name': profile.claimed_by_player.name}
    notes = (db.session.query(PlayerAdminNote).options(joinedload(PlayerAdminNote.author))
             .filter(PlayerAdminNote.quick_profile_id == profile_id)
             .order_by(PlayerAdminNote.created_at.desc()).all())
    note_list = [{'id': n.id, 'content': n.content,
                  'author': (n.author.username if getattr(n, 'author', None) else 'system'),
                  'created_at': n.created_at.strftime('%Y-%m-%d %H:%M') if n.created_at else ''}
                 for n in notes]
    try:
        from app.services.season_phase_service import is_waitlist_open
        waitlist_open = bool(is_waitlist_open(db.session))
    except Exception:
        waitlist_open = True
    return jsonify({'success': True, 'profile': data, 'notes': note_list, 'waitlist_open': waitlist_open})


@admin_panel_bp.route('/members/quick-profile/<int:profile_id>/note', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def member_qp_note_add(profile_id):
    """Add an admin/coach note to a quick profile (PlayerAdminNote targeting quick_profile_id).
    Migrates to the player automatically if/when the profile is later claimed."""
    from flask_login import current_user
    from app.core import db
    from app.models import QuickProfile
    from app.models.players import PlayerAdminNote

    profile = db.session.get(QuickProfile, profile_id)
    if not profile:
        return jsonify({'success': False, 'message': 'Quick profile not found'}), 404
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'message': 'Note cannot be empty'}), 400
    note = PlayerAdminNote(quick_profile_id=profile_id,
                           author_id=getattr(current_user, 'id', None), content=content)
    db.session.add(note)
    db.session.flush()
    return jsonify({'success': True, 'note': {
        'id': note.id, 'content': note.content,
        'author': getattr(current_user, 'username', 'you'),
        'created_at': note.created_at.strftime('%Y-%m-%d %H:%M') if note.created_at else 'just now'}})


@admin_panel_bp.route('/members/quick-profile/<int:profile_id>/preapprove', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def member_qp_preapprove(profile_id):
    """Pre-approve (or clear) a quick profile so the person is auto-approved into the chosen
    league the moment they claim their code (see QuickProfile._apply_pre_approval). Accepts a
    league/sub type, or a waitlist-* type which is applied phase-aware on claim (waitlist if
    open, else the plain league). Body: {league_type} ('' clears)."""
    from flask_login import current_user
    from datetime import datetime
    from app.core import db
    from app.models import QuickProfile

    profile = db.session.get(QuickProfile, profile_id)
    if not profile:
        return jsonify({'success': False, 'message': 'Quick profile not found'}), 404
    data = request.get_json(silent=True) or {}
    league = (data.get('league_type') or '').strip()
    valid = {'classic', 'premier', 'ecs-fc', 'sub-classic', 'sub-premier', 'sub-ecs-fc',
             'waitlist-classic', 'waitlist-premier', 'waitlist-ecs-fc'}
    if league and league not in valid:
        return jsonify({'success': False, 'message': 'Invalid league'}), 400
    if league:
        profile.pre_approved_league = league
        profile.pre_approved_by_user_id = getattr(current_user, 'id', None)
        profile.pre_approved_at = datetime.utcnow()
        msg = f'Pre-approved into {league} — auto-approves when they claim'
    else:
        profile.pre_approved_league = None
        profile.pre_approved_by_user_id = None
        profile.pre_approved_at = None
        msg = 'Pre-approval cleared'
    return jsonify({'success': True, 'message': msg, 'pre_approved_league': profile.pre_approved_league})


# lane_label -> canonical normalized lane -> sub Flask role name.
_LANE_TO_SUBROLE = {'classic': 'Classic Sub', 'premier': 'Premier Sub', 'ecs_fc': 'ECS FC Sub'}
_LABEL_TO_CANON = {'Classic': 'classic', 'Premier': 'premier', 'ECS FC': 'ecs_fc'}


def _player_sub_lanes(session, player_id):
    """The normalized lanes this player is actually a sub in, read from BOTH pool tables.

    This app stores ECS FC subs in TWO places: the approval path writes an EcsFcSubPool row
    AND a SubstitutePool row with league_type='ECS FC' (the spine reads the SubstitutePool
    twin FIRST). SubstitutePool.player_id is UNIQUE, so there is at most one SubstitutePool
    row. Returns a set like {'classic'} or {'premier','ecs_fc'}."""
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.services.league_membership_sync import _norm_league_type
    lanes = set()
    sp = session.query(SubstitutePool).filter_by(player_id=player_id).first()
    # A PENDING (unapproved) SubstitutePool signup grants no sub role — only an approved row
    # counts, matching the spine's pending-vs-active distinction. EcsFcSubPool has no
    # approval concept (is_active only), so its presence always counts.
    if sp and sp.approved_at is not None:
        n = _norm_league_type(sp.league_type)
        if n:
            lanes.add(n)
    if session.query(EcsFcSubPool).filter_by(player_id=player_id).first():
        lanes.add('ecs_fc')
    return lanes


def _reconcile_sub_roles(session, user, player):
    """Add/remove the three sub Flask roles to MATCH the player's actual pool memberships,
    and refresh player.is_sub. Idempotent; robust to non-canonical stored league_type
    because it goes through _norm_league_type. Replaces fragile manual add/strip logic."""
    from app.models import Role
    lanes = _player_sub_lanes(session, player.id)
    for lane, rname in _LANE_TO_SUBROLE.items():
        role = session.query(Role).filter_by(name=rname).first()
        if not role:
            continue
        want, has = (lane in lanes), (role in user.roles)
        if want and not has:
            user.roles.append(role)
        elif has and not want:
            user.roles.remove(role)
    player.is_sub = bool(lanes)


@admin_panel_bp.route('/members/<int:user_id>/sub-assign', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def member_sub_assign(user_id):
    """Assign this person to a substitute pool (Classic/Premier/ECS FC) and optionally make
    them active — self-contained. Writes the right pool table(s), reconciles the sub roles to
    actual membership, re-syncs the spine, defers a Discord sync. Subs never pay.
    Body: {league_type: 'Classic'|'Premier'|'ECS FC', active: bool}.
    """
    from flask_login import current_user
    from datetime import datetime
    from app.core import db
    from app.models import User, League, Season
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import resync_player_memberships, _norm_league_type

    data = request.get_json(silent=True) or {}
    league_type = (data.get('league_type') or '').strip()
    make_active = bool(data.get('active', True))
    target = _LABEL_TO_CANON.get(league_type)
    if target is None:
        return jsonify({'success': False, 'message': 'Invalid league'}), 400

    user = db.session.get(User, user_id)
    if not user or not user.player:
        return jsonify({'success': False, 'message': 'This person has no player record'}), 400
    player = user.player
    now = datetime.utcnow()
    aid = getattr(current_user, 'id', None)

    if target == 'ecs_fc':
        ep = db.session.query(EcsFcSubPool).filter_by(player_id=player.id).first()
        if ep:
            ep.is_active = make_active
        else:
            db.session.add(EcsFcSubPool(player_id=player.id, is_active=make_active))
        # Keep the approval-created SubstitutePool('ECS FC') twin in sync — the spine reads
        # it FIRST, so approving/activating must update it too (never create/clobber a Pub row).
        sp = db.session.query(SubstitutePool).filter_by(player_id=player.id).first()
        if sp and _norm_league_type(sp.league_type) == 'ecs_fc':
            sp.is_active = make_active
            sp.approved_at = sp.approved_at or now
            sp.approved_by = sp.approved_by or aid
    else:
        canonical = 'Classic' if target == 'classic' else 'Premier'
        sp = db.session.query(SubstitutePool).filter_by(player_id=player.id).first()
        if sp:
            # SubstitutePool.player_id is UNIQUE (one Pub row per player), so this claims the
            # row for the chosen lane. ECS FC membership (if any) survives via EcsFcSubPool;
            # role reconciliation below fixes up every sub role from actual membership.
            sp.league_type = canonical
            sp.is_active = make_active
            sp.approved_at = sp.approved_at or now
            sp.approved_by = sp.approved_by or aid
        else:
            db.session.add(SubstitutePool(
                player_id=player.id, league_type=canonical, is_active=make_active,
                approved_at=now, approved_by=aid))

    db.session.flush()
    _reconcile_sub_roles(db.session, user, player)

    # Ensure the player has a league so dispatch + Discord roles resolve (best-effort).
    if not player.league_id and not player.primary_league_id:
        s_type = 'ECS FC' if target == 'ecs_fc' else 'Pub League'
        lg = (db.session.query(League).join(Season)
              .filter(Season.league_type == s_type, Season.is_current == True).first())
        if lg:
            player.league_id = lg.id
            player.primary_league_id = lg.id

    db.session.flush()
    resync_player_memberships(db.session, player.id)
    if player.discord_id:
        # Full allowlist-protected reconcile (the batching layer runs enforce_allowlist=True):
        # get_expected_roles now includes the -SUB role we reconciled, so it's granted, while
        # team/division/coach roles are protected from removal.
        defer_discord_sync(player.id, only_add=True)
    return jsonify({'success': True,
                    'message': f'Added to {league_type} subs ({"active" if make_active else "resting"})'})


@admin_panel_bp.route('/members/<int:user_id>/sub-active', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def member_sub_set_active(user_id):
    """Rest/Wake a sub for one lane — self-contained AND both-pool-aware. For ECS FC it updates
    BOTH the EcsFcSubPool row and the SubstitutePool('ECS FC') twin the spine reads first; the
    Pub match is by NORMALIZED lane (robust to non-canonical stored values). Body: {league_type, active}."""
    from app.core import db
    from app.models import User
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import resync_player_memberships, _norm_league_type

    data = request.get_json(silent=True) or {}
    league_type = (data.get('league_type') or '').strip()
    make_active = bool(data.get('active', True))
    target = _LABEL_TO_CANON.get(league_type)
    if target is None:
        return jsonify({'success': False, 'message': 'Invalid league'}), 400
    user = db.session.get(User, user_id)
    if not user or not user.player:
        return jsonify({'success': False, 'message': 'No player record'}), 400
    pid = user.player.id

    touched = False
    sp = db.session.query(SubstitutePool).filter_by(player_id=pid).first()
    if sp and _norm_league_type(sp.league_type) == target:
        sp.is_active = make_active
        touched = True
    if target == 'ecs_fc':
        ep = db.session.query(EcsFcSubPool).filter_by(player_id=pid).first()
        if ep:
            ep.is_active = make_active
            touched = True
    if not touched:
        return jsonify({'success': False, 'message': f'Not in the {league_type} sub pool'}), 404

    db.session.flush()
    resync_player_memberships(db.session, pid)
    if user.player.discord_id:
        defer_discord_sync(pid, only_add=True)
    return jsonify({'success': True,
                    'message': ('Woken' if make_active else 'Resting') + f' · {league_type}'})


@admin_panel_bp.route('/members/<int:user_id>/sub-remove', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def member_sub_remove(user_id):
    """Remove a sub from one lane — self-contained AND both-pool-aware. Deletes the matching
    row(s) in BOTH tables for ECS FC (incl. the SubstitutePool twin), then reconciles the sub
    roles to actual membership (strips only the removed lane's role). Body: {league_type}."""
    from app.core import db
    from app.models import User
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import resync_player_memberships, _norm_league_type

    data = request.get_json(silent=True) or {}
    league_type = (data.get('league_type') or '').strip()
    target = _LABEL_TO_CANON.get(league_type)
    if target is None:
        return jsonify({'success': False, 'message': 'Invalid league'}), 400
    user = db.session.get(User, user_id)
    if not user or not user.player:
        return jsonify({'success': False, 'message': 'No player record'}), 400
    pid = user.player.id

    sp = db.session.query(SubstitutePool).filter_by(player_id=pid).first()
    if sp and _norm_league_type(sp.league_type) == target:
        db.session.delete(sp)
    if target == 'ecs_fc':
        ep = db.session.query(EcsFcSubPool).filter_by(player_id=pid).first()
        if ep:
            db.session.delete(ep)
    db.session.flush()
    _reconcile_sub_roles(db.session, user, player=user.player)
    db.session.flush()
    resync_player_memberships(db.session, pid)
    if user.player.discord_id:
        # Full allowlist-protected reconcile: the now-removed lane's -SUB role is no longer in
        # get_expected_roles and the allowlist permits stripping -SUB, so it's removed; team,
        # division and coach roles are protected and preserved.
        defer_discord_sync(pid, only_add=False)
    return jsonify({'success': True, 'message': f'Removed from {league_type} subs'})


@admin_panel_bp.route('/members/<int:user_id>/sub-reject', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional(max_retries=3)
def member_sub_reject(user_id):
    """Reject a PENDING sub-pool self-signup (approved_at IS NULL) for one lane.

    The legacy reject_player_from_pool endpoint targets a different flow (pre-rejecting
    a player NOT yet in the pool), so it 400s on an existing pending row. This focused
    action deletes the pending SubstitutePool row, strips the matching sub Flask role,
    re-syncs the spine, and queues a Discord sync (the allowlist permits stripping the
    -SUB role). Body: {league_type: 'Classic'|'Premier'|'ECS FC'}.
    """
    from app.core import db
    from app.models import User, Role
    from app.models.substitutes import SubstitutePool
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import resync_player_memberships

    data = request.get_json(silent=True) or {}
    league_type = (data.get('league_type') or '').strip()
    role_map = {'Classic': 'Classic Sub', 'Premier': 'Premier Sub', 'ECS FC': 'ECS FC Sub'}

    user = db.session.get(User, user_id)
    if not user or not user.player:
        return jsonify({'success': False, 'message': 'User has no player record'}), 400
    pid = user.player.id

    q = db.session.query(SubstitutePool).filter(
        SubstitutePool.player_id == pid, SubstitutePool.approved_at.is_(None))
    if league_type:
        q = q.filter(SubstitutePool.league_type == league_type)
    rows = q.all()
    if not rows:
        return jsonify({'success': False, 'message': 'No pending sub signup to reject'}), 404

    for r in rows:
        db.session.delete(r)
    rname = role_map.get(league_type)
    if rname:
        role = db.session.query(Role).filter_by(name=rname).first()
        if role and role in user.roles:
            user.roles.remove(role)
    db.session.flush()
    resync_player_memberships(db.session, pid)
    if user.player.discord_id:
        defer_discord_sync(user.player.id, only_add=False)  # allowlist permits the -SUB role strip
    return jsonify({'success': True, 'message': f'Rejected the pending {league_type or "sub"} signup'})


@admin_panel_bp.route('/members/<int:user_id>/place', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional(max_retries=3)
def member_place(user_id):
    """TARGETED team placement: add the member's player to a team, or remove them.

    Deliberately touches ONLY the roster (player_teams + PlayerTeamSeason +
    primary_team_id), then dual-writes the spine and syncs Discord — it never
    overwrites any other user/player field (unlike the comprehensive edit form).
    Body: {action: 'add'|'remove', team_id: int, is_coach?: bool}.
    """
    from flask_login import current_user
    from app.core import db
    from app.models import Team, PlayerTeamSeason, player_teams
    from sqlalchemy import update as _sa_update
    from app.utils.user_locking import lock_user_for_role_update, LockAcquisitionError, UserNotFoundError
    from app.utils.deferred_discord import defer_discord_sync
    from app.tasks.tasks_discord import remove_player_roles_task
    from app.services.league_membership_sync import resync_player_memberships

    data = request.get_json(silent=True) or {}
    action = (data.get('action') or 'add').strip()
    is_coach = bool(data.get('is_coach'))

    if action not in ('add', 'remove', 'primary'):
        return jsonify({'success': False, 'message': 'Invalid action'}), 400
    try:
        team_id = int(data.get('team_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'A valid team_id is required'}), 400

    try:
        with lock_user_for_role_update(user_id, session=db.session) as user:
            if not user.player:
                return jsonify({'success': False, 'message': 'User has no player record'}), 400
            player = user.player
            team = db.session.get(Team, team_id)
            if not team:
                return jsonify({'success': False, 'message': 'Team not found'}), 404
            season_id = team.league.season_id if team.league else None

            if action == 'remove':
                if player in team.players:
                    team.players.remove(player)
                if player.primary_team_id == team.id:
                    player.primary_team_id = None
                    player.primary_league_id = None  # cleared along with the primary team
                if season_id:
                    db.session.query(PlayerTeamSeason).filter_by(
                        player_id=player.id, team_id=team.id, season_id=season_id
                    ).delete(synchronize_session=False)
                db.session.flush()
                resync_player_memberships(db.session, player.id)
                if player.discord_id:
                    # Targeted removal (bypasses the reconcile allowlist) strips THIS team's roles.
                    remove_player_roles_task.delay(player_id=player.id, team_id=team.id)
                message = f'{player.name} removed from {team.name}'
            elif action == 'primary':
                # Make an already-rostered team the player's PRIMARY (sets primary_league too).
                if player not in team.players:
                    return jsonify({'success': False,
                                    'message': f'{player.name} is not on {team.name} — place them there first.'}), 400
                player.primary_team_id = team.id
                if team.league:
                    player.primary_league_id = team.league_id
                db.session.flush()
                resync_player_memberships(db.session, player.id)
                if player.discord_id:
                    defer_discord_sync(player.id, only_add=True)
                message = f'{team.name} set as {player.name}\'s primary team'
            else:  # add
                # Block double-rostering in the same non-ECS-FC league (mirrors the draft guard;
                # ECS FC intentionally allows multiple teams).
                is_ecs = 'ecs' in ((team.league.name if team.league else '') or '').lower()
                if not is_ecs:
                    dupe = next((t for t in player.teams
                                 if t.league_id == team.league_id and t.id != team.id), None)
                    if dupe:
                        return jsonify({'success': False,
                                        'message': f'{player.name} is already on {dupe.name} in this league — remove them there first.'}), 400
                if player not in team.players:
                    team.players.append(player)
                # Set primary only if they have none yet — don't hijack an existing primary.
                if not player.primary_team_id:
                    player.primary_team_id = team.id
                    if team.league:
                        player.primary_league_id = team.league_id
                db.session.flush()
                db.session.execute(_sa_update(player_teams).where(
                    player_teams.c.player_id == player.id,
                    player_teams.c.team_id == team.id,
                ).values(is_coach=is_coach))
                if season_id:
                    pts = db.session.query(PlayerTeamSeason).filter_by(
                        player_id=player.id, team_id=team.id, season_id=season_id).first()
                    if pts:
                        pts.is_coach = is_coach
                    else:
                        db.session.add(PlayerTeamSeason(
                            player_id=player.id, team_id=team.id, season_id=season_id, is_coach=is_coach))
                # A rostered player must not keep a conflicting Pub League sub role/pool
                # (mirrors the draft path) — otherwise the stale sub role fights their team role.
                try:
                    from app.services.sub_status_service import remove_conflicting_sub_status
                    remove_conflicting_sub_status(db.session, player.id,
                                                  performed_by_user_id=getattr(current_user, 'id', None))
                except Exception as _sub_err:
                    logger.warning(f"sub-status cleanup skipped for player {player.id}: {_sub_err}")
                # A rostered player is IN — auto-clear any stale waitlist so we never leave
                # someone on the waitlist after placing them (they go to the normal pool).
                try:
                    from app.models import Role
                    wl_role = db.session.query(Role).filter_by(name='pl-waitlist').first()
                    if wl_role and wl_role in user.roles:
                        user.roles.remove(wl_role)
                        user.waitlist_league = None
                        if hasattr(user, 'waitlist_joined_at'):
                            user.waitlist_joined_at = None
                except Exception as _wl_err:
                    logger.warning(f"waitlist auto-clear skipped for player {player.id}: {_wl_err}")
                db.session.flush()
                resync_player_memberships(db.session, player.id)
                if player.discord_id:
                    defer_discord_sync(player.id, only_add=True)  # additive grant, never strips
                message = f'{player.name} placed on {team.name}{" as coach" if is_coach else ""}'

        return jsonify({'success': True, 'message': message})
    except LockAcquisitionError:
        return jsonify({'success': False, 'message': 'User is being modified by another request. Try again.'}), 409
    except UserNotFoundError:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    except Exception as e:
        logger.error(f"member_place error for user {user_id}: {e}")
        return jsonify({'success': False, 'message': 'Failed to update team placement'}), 500
