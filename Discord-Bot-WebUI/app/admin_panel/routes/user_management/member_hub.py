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


@admin_panel_bp.route('/members')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def members_worklist():
    """Unified Members worklist — the NEW primary intake surface.

    Tabs for the intake queues (Pending Approval / Waitlist / Quick Profiles), each row
    linking to the person's Member Hub. Reuses the existing shared query criteria so it
    can't drift from the legacy pages, which stay live as a one-click fallback.
    """
    from datetime import datetime
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload
    from app.core import db
    from app.models import User, Role, QuickProfile
    from app.models.quick_profile import QuickProfileStatus

    tab = (request.args.get('tab') or 'pending').strip()
    search = (request.args.get('search') or '').strip()
    now = datetime.utcnow()

    # Shared base queries (same criteria the legacy pages + badges use).
    pending_q = db.session.query(User).filter(*User.pending_approval_criteria())
    waitlist_q = db.session.query(User).join(User.roles).filter(Role.name == 'pl-waitlist')
    quick_q = db.session.query(QuickProfile).filter(
        QuickProfile.status == QuickProfileStatus.PENDING.value,
        or_(QuickProfile.expires_at.is_(None), QuickProfile.expires_at > now),
    )

    counts = {
        'pending': pending_q.count(),
        'waitlist': waitlist_q.count(),
        'quick': quick_q.count(),
    }

    users, profiles = [], []
    if tab == 'waitlist':
        wq = waitlist_q.options(joinedload(User.player))
        if search:
            wq = wq.filter(User.username.ilike(f'%{search}%'))
        users = wq.order_by(User.waitlist_joined_at.asc().nullslast()).all()
    elif tab == 'quick':
        profiles = quick_q.order_by(QuickProfile.created_at.desc()).all()
    else:
        tab = 'pending'
        pq = pending_q.options(joinedload(User.player), joinedload(User.roles))
        if search:
            pq = pq.filter(User.username.ilike(f'%{search}%'))
        users = pq.order_by(User.created_at.desc()).all()

    return render_template('admin_panel/members/worklist_flowbite.html',
                           tab=tab, search=search, counts=counts, users=users, profiles=profiles)


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
    return render_template('admin_panel/members/member_hub_flowbite.html', m=data,
                           all_roles=all_roles, user_role_ids=user_role_ids, leagues=leagues,
                           primary_team_id=primary_team_id, hub_teams=hub_teams)


@admin_panel_bp.route('/members/<int:user_id>/data')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def member_hub_data(user_id):
    """JSON snapshot of the Member Hub view (for live refresh after an action)."""
    data = get_member_360(user_id)
    if data is None:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    return jsonify({'success': True, 'member': data})


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
