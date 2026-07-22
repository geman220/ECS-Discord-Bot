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

from flask import render_template, jsonify, abort, request
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
    summary = {}
    if not sub_pids:
        return summary
    for sp in session.query(SubstitutePool).filter(SubstitutePool.player_id.in_(sub_pids)).all():
        if sp.approved_at is None:
            continue
        summary.setdefault(sp.player_id, []).append(
            {'lane': sp.league_type, 'status': 'active' if sp.is_active else 'resting'})
    for ep in session.query(EcsFcSubPool).filter(EcsFcSubPool.player_id.in_(sub_pids)).all():
        summary.setdefault(ep.player_id, []).append(
            {'lane': 'ECS FC', 'status': 'active' if ep.is_active else 'resting'})
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

    tab = (request.args.get('tab') or 'all').strip()
    search = (request.args.get('search') or '').strip()
    role_filter = (request.args.get('role') or '').strip()
    league_filter = (request.args.get('league') or '').strip()
    approved_filter = (request.args.get('approved') or '').strip()
    active_filter = (request.args.get('active') or '').strip()
    page = request.args.get('page', 1, type=int)
    now = datetime.utcnow()

    # --- shared queue criteria (identical to the legacy pages, so counts can't drift) ---
    pending_q = db.session.query(User).filter(*User.pending_approval_criteria())
    waitlist_q = db.session.query(User).join(User.roles).filter(Role.name == 'pl-waitlist')
    quick_q = db.session.query(QuickProfile).filter(
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

    thirty_days_ago = now - timedelta(days=30)
    stats = {
        'total_members': db.session.query(User).count(),
        'active_players': db.session.query(Player).filter(Player.is_current_player == True).count(),
        'pending': pending_q.count(),
        'waitlist': waitlist_q.count(),
        'subs': len(sub_pids),
        'quick': quick_q.count(),
        'approved': db.session.query(User).filter(User.is_approved == True).count(),
        'recent': db.session.query(User).filter(User.created_at >= thirty_days_ago).count(),
    }
    counts = {'all': stats['total_members'], 'pending': stats['pending'],
              'waitlist': stats['waitlist'], 'subs': stats['subs'], 'quick': stats['quick']}

    all_roles = db.session.query(Role).order_by(Role.name).all()
    all_leagues = (db.session.query(League).options(joinedload(League.teams))
                   .join(Season).filter(Season.is_current == True).order_by(League.name).all())

    users, profiles, pagination, sub_summary = [], [], None, {}

    if tab == 'waitlist':
        wq = waitlist_q.options(joinedload(User.player))
        if search:
            like = f'%{search}%'
            wq = wq.outerjoin(Player, Player.user_id == User.id).filter(
                or_(Player.name.ilike(like), User.username.ilike(like)))
        users = wq.order_by(User.waitlist_joined_at.asc().nullslast()).all()

    elif tab == 'quick':
        pq = quick_q
        if search:
            pq = pq.filter(QuickProfile.player_name.ilike(f'%{search}%'))
        profiles = pq.order_by(QuickProfile.created_at.desc()).all()

    elif tab == 'subs':
        if sub_pids:
            sq = (db.session.query(User).options(joinedload(User.player), joinedload(User.roles))
                  .join(Player, Player.user_id == User.id).filter(Player.id.in_(sub_pids)))
            if search:
                like = f'%{search}%'
                sq = sq.filter(or_(Player.name.ilike(like), User.username.ilike(like)))
            users = sq.order_by(Player.name).all()
            sub_summary = _sub_summary(db.session, sub_pids)

    elif tab == 'pending':
        pq = pending_q.options(joinedload(User.player), joinedload(User.roles))
        if search:
            like = f'%{search}%'
            pq = pq.outerjoin(Player, Player.user_id == User.id).filter(
                or_(Player.name.ilike(like), User.username.ilike(like)))
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
        if approved_filter == 'true':
            q = q.filter(User.is_approved == True)
        elif approved_filter == 'false':
            q = q.filter(or_(User.is_approved == False, User.is_approved == None))
        if active_filter == 'true':
            q = q.filter(User.is_active == True)
        elif active_filter == 'false':
            q = q.filter(or_(User.is_active == False, User.is_active == None))
        if league_filter:
            try:
                lid = int(league_filter)
                q = q.filter(User.player.has(or_(Player.league_id == lid, Player.primary_league_id == lid)))
            except (ValueError, TypeError):
                pass
        q = q.order_by(User.username)
        pagination = q.paginate(page=page, per_page=50, error_out=False)
        users = pagination.items

    return render_template('admin_panel/members/worklist_flowbite.html',
                           tab=tab, search=search, counts=counts, stats=stats,
                           users=users, profiles=profiles, pagination=pagination,
                           sub_summary=sub_summary, roles=all_roles, leagues=all_leagues,
                           role_filter=role_filter, league_filter=league_filter,
                           approved_filter=approved_filter, active_filter=active_filter)


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
        out['audit'] = [{
            'action': a.action,
            'actor': (a.user.username if getattr(a, 'user', None) else 'system'),
            'when': a.timestamp.strftime('%Y-%m-%d %H:%M') if a.timestamp else '',
            'detail': (a.new_value or '')[:120],
        } for a in rows]
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


@admin_panel_bp.route('/members/<int:user_id>/sub-assign', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def member_sub_assign(user_id):
    """Assign this person to a substitute pool (Classic/Premier/ECS FC) and optionally make
    them active — self-contained (creates/reactivates the pool row, grants the sub role,
    re-syncs the spine, defers a Discord sync). Subs never pay, so no payment is involved.
    Body: {league_type: 'Classic'|'Premier'|'ECS FC', active: bool}.
    """
    from flask_login import current_user
    from datetime import datetime
    from app.core import db
    from app.models import User, Role, League, Season
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import resync_player_memberships

    data = request.get_json(silent=True) or {}
    league_type = (data.get('league_type') or '').strip()
    make_active = bool(data.get('active', True))
    role_map = {'Classic': 'Classic Sub', 'Premier': 'Premier Sub', 'ECS FC': 'ECS FC Sub'}
    if league_type not in role_map:
        return jsonify({'success': False, 'message': 'Invalid league'}), 400

    user = db.session.get(User, user_id)
    if not user or not user.player:
        return jsonify({'success': False, 'message': 'This person has no player record'}), 400
    player = user.player
    now = datetime.utcnow()

    if league_type == 'ECS FC':
        row = db.session.query(EcsFcSubPool).filter_by(player_id=player.id).first()
        if row:
            row.is_active = make_active
        else:
            db.session.add(EcsFcSubPool(player_id=player.id, is_active=make_active))
    else:
        row = db.session.query(SubstitutePool).filter_by(player_id=player.id).first()
        if row:
            # SubstitutePool.player_id is UNIQUE — a Pub sub lives in exactly ONE lane. If this
            # reassigns them to a different lane, strip the OLD lane's sub role so no stale
            # Discord/Flask role lingers (the row itself is moved, not duplicated).
            if row.league_type and row.league_type != league_type:
                old_role = db.session.query(Role).filter_by(name=role_map.get(row.league_type, '')).first()
                if old_role and old_role in user.roles:
                    user.roles.remove(old_role)
            row.league_type = league_type
            row.is_active = make_active
            row.approved_at = row.approved_at or now
            row.approved_by = row.approved_by or getattr(current_user, 'id', None)
        else:
            db.session.add(SubstitutePool(
                player_id=player.id, league_type=league_type, is_active=make_active,
                approved_at=now, approved_by=getattr(current_user, 'id', None)))

    role = db.session.query(Role).filter_by(name=role_map[league_type]).first()
    if role and role not in user.roles:
        user.roles.append(role)

    # Ensure the player has a league so dispatch + Discord roles resolve (best-effort).
    if not player.league_id and not player.primary_league_id:
        s_type = 'ECS FC' if league_type == 'ECS FC' else 'Pub League'
        lg = (db.session.query(League).join(Season)
              .filter(Season.league_type == s_type, Season.is_current == True).first())
        if lg:
            player.league_id = lg.id
            player.primary_league_id = lg.id

    db.session.flush()
    resync_player_memberships(db.session, player.id)
    if player.discord_id:
        defer_discord_sync(player.id, only_add=True)  # additive: grants the -SUB role
    return jsonify({'success': True,
                    'message': f'Added to {league_type} subs ({"active" if make_active else "resting"})'})


@admin_panel_bp.route('/members/<int:user_id>/sub-active', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def member_sub_set_active(user_id):
    """Rest/Wake a sub for one lane — self-contained AND handles BOTH pool tables (Pub League
    SubstitutePool + ECS FC EcsFcSubPool), so ECS FC subs are manageable from the Hub (the
    legacy set_pool_member_active only knows SubstitutePool). Body: {league_type, active}."""
    from app.core import db
    from app.models import User
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import resync_player_memberships

    data = request.get_json(silent=True) or {}
    league_type = (data.get('league_type') or '').strip()
    make_active = bool(data.get('active', True))
    if league_type not in ('Classic', 'Premier', 'ECS FC'):
        return jsonify({'success': False, 'message': 'Invalid league'}), 400
    user = db.session.get(User, user_id)
    if not user or not user.player:
        return jsonify({'success': False, 'message': 'No player record'}), 400
    pid = user.player.id

    if league_type == 'ECS FC':
        row = db.session.query(EcsFcSubPool).filter_by(player_id=pid).first()
    else:
        row = db.session.query(SubstitutePool).filter_by(player_id=pid, league_type=league_type).first()
    if not row:
        return jsonify({'success': False, 'message': f'Not in the {league_type} sub pool'}), 404
    row.is_active = make_active
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
    """Remove a sub from one lane's pool — self-contained AND both-pool-aware. Deletes the pool
    row + strips the lane's sub role (the allowlist permits -SUB removal). Body: {league_type}."""
    from app.core import db
    from app.models import User, Role
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import resync_player_memberships

    data = request.get_json(silent=True) or {}
    league_type = (data.get('league_type') or '').strip()
    role_map = {'Classic': 'Classic Sub', 'Premier': 'Premier Sub', 'ECS FC': 'ECS FC Sub'}
    if league_type not in role_map:
        return jsonify({'success': False, 'message': 'Invalid league'}), 400
    user = db.session.get(User, user_id)
    if not user or not user.player:
        return jsonify({'success': False, 'message': 'No player record'}), 400
    pid = user.player.id

    if league_type == 'ECS FC':
        row = db.session.query(EcsFcSubPool).filter_by(player_id=pid).first()
    else:
        row = db.session.query(SubstitutePool).filter_by(player_id=pid, league_type=league_type).first()
    if row:
        db.session.delete(row)
    role = db.session.query(Role).filter_by(name=role_map[league_type]).first()
    if role and role in user.roles:
        user.roles.remove(role)
    db.session.flush()
    resync_player_memberships(db.session, pid)
    if user.player.discord_id:
        defer_discord_sync(pid, only_add=False)  # allow the -SUB strip (allowlist permits it)
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
