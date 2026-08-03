# app/admin_panel/routes/user_management/approvals.py

"""
User Approvals Routes

Routes for user approval workflow:
- User approvals management page
- Approve/deny users
- User details for approval modal
"""

import logging
from datetime import datetime, timedelta

from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.models.core import User, Role
from app.models.ecs_fc import is_ecs_fc_team
from app.models.quick_profile import QuickProfile, QuickProfileStatus
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.utils.deferred_discord import defer_discord_sync
from app.utils.deferred_cache import defer_clear_league_cache
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task
from app.utils.user_helpers import safe_current_user
from app.services.league_membership_sync import resync_player_memberships

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/users')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def user_management():
    """User management hub - redirects to the main users page."""
    return redirect(url_for('admin_panel.users_comprehensive'))


@admin_panel_bp.route('/users/approvals')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def user_approvals():
    """User approvals management page with filtering."""
    try:
        current_user_safe = safe_current_user

        # Get filter parameters
        status_filter = request.args.get('status', '').strip()
        league_filter = request.args.get('league', '').strip()
        search_query = request.args.get('search', '').strip()

        # Build query for users
        query = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        )

        # Apply status filter (default to pending if not specified)
        if status_filter == 'approved':
            query = query.filter(User.approval_status == 'approved')
        elif status_filter == 'denied':
            query = query.filter(User.approval_status == 'denied')
        elif status_filter == 'all':
            pass  # No filter, show all
        else:
            # Default to pending — but EXCLUDE users parked on the waitlist (they
            # are 'pending' + hold the pl-waitlist role and live on the waitlist
            # page, not this needs-a-decision queue). One shared criteria helper so
            # this list, the count badge, and every other pending counter agree.
            query = query.filter(*User.pending_approval_criteria())
            status_filter = 'pending'

        # Apply league filter
        if league_filter:
            # Filter by roles that match league patterns
            if league_filter == 'pl-classic':
                query = query.join(User.roles).filter(Role.name.ilike('%classic%'))
            elif league_filter == 'pl-premier':
                query = query.join(User.roles).filter(Role.name.ilike('%premier%'))
            elif league_filter == 'ecs-fc':
                query = query.join(User.roles).filter(
                    or_(Role.name.ilike('%ecs%fc%'), Role.name.ilike('%ecsfc%'))
                )

        # Apply search filter (email is encrypted, search by username only)
        if search_query:
            search_term = f'%{search_query}%'
            query = query.filter(User.username.ilike(search_term))

        # Order by creation date
        pending_users = query.order_by(User.created_at.desc()).all()

        # Get recent approval actions (always show recent activity)
        recent_actions = []
        try:
            recent_actions = db.session.query(User).options(
                joinedload(User.player),
                joinedload(User.roles)
            ).filter(
                User.approval_status.in_(['approved', 'denied']),
                User.approved_at.isnot(None)
            ).order_by(User.approved_at.desc()).limit(20).all()

            # Add approved_by_user information
            for user in recent_actions:
                if user.approved_by:
                    user.approved_by_user = db.session.query(User).filter_by(id=user.approved_by).first()
        except Exception as e:
            logger.error(f"Error loading recent actions: {str(e)}")
            recent_actions = []

        # Count statistics. pending_count mirrors the pending LIST (waitlisted users
        # excluded) so the badge matches what the admin actually sees to act on.
        stats = {
            'pending_count': User.count_pending_approvals(db.session),
            'total_approved': db.session.query(func.count(User.id)).filter(User.approval_status == 'approved').scalar(),
            'total_denied': db.session.query(func.count(User.id)).filter(User.approval_status == 'denied').scalar()
        }

        # Get audit log entries for user approvals
        audit_logs = []
        try:
            audit_logs = db.session.query(AdminAuditLog).options(
                joinedload(AdminAuditLog.user)
            ).filter(
                AdminAuditLog.resource_type == 'user_approval'
            ).order_by(AdminAuditLog.timestamp.desc()).limit(20).all()
        except Exception as e:
            logger.error(f"Error loading audit logs: {str(e)}")
            audit_logs = []

        # Field-created quick profiles that haven't been claimed yet. These are
        # walk-in players an admin captured (name + photo + notes + claim code)
        # who don't have a real account until they register with the code. We
        # surface them here as an "unclaimed" group so the board can see them
        # alongside real pending users — WITHOUT creating orphan User rows.
        # (Only shown in the pending / all views; hidden when reviewing
        # approved/denied history.)
        field_profiles = []
        if status_filter in ('pending', 'all'):
            try:
                field_profiles = db.session.query(QuickProfile).filter(
                    QuickProfile.status == QuickProfileStatus.PENDING.value,
                    QuickProfile.expires_at > datetime.utcnow()
                ).order_by(QuickProfile.created_at.desc()).limit(100).all()
            except Exception as e:
                logger.error(f"Error loading field quick profiles: {str(e)}")
                field_profiles = []

        # Stranded claimed/linked profiles: a profile that WAS claimed or linked but
        # whose player has no User account (a legacy-roster orphan, user_id IS NULL)
        # or whose player row is missing entirely. These never reach the pending
        # queue because every list here is User-driven, so they silently vanished —
        # exactly how walk-in prospects fell into limbo. Surface them with a
        # "Create account" action that mints/re-queues an account so they flow into
        # the normal approvals list. New links/claims can't land here anymore
        # (link/claim now ensure an account), so this only clears the backlog.
        limbo_profiles = []
        if status_filter in ('pending', 'all'):
            try:
                from app.models import Player
                limbo_profiles = db.session.query(QuickProfile).options(
                    joinedload(QuickProfile.claimed_by_player)
                ).outerjoin(
                    Player, Player.id == QuickProfile.claimed_by_player_id
                ).filter(
                    QuickProfile.status.in_([
                        QuickProfileStatus.CLAIMED.value,
                        QuickProfileStatus.LINKED.value,
                    ]),
                    or_(Player.id.is_(None), Player.user_id.is_(None))
                ).order_by(QuickProfile.created_at.desc()).limit(100).all()
            except Exception as e:
                logger.error(f"Error loading stranded quick profiles: {str(e)}")
                limbo_profiles = []

        # Waiting-room review notes (coach/admin fit notes) for the prospects on
        # this page — pending players and field/quick profiles share one note system.
        # Loaded in two grouped queries and keyed for the template so admins can read
        # the coach input while deciding. Author is eager-loaded for attribution.
        notes_by_player = {}
        notes_by_quick_profile = {}
        try:
            from app.models.players import PlayerAdminNote
            _player_ids = [u.player.id for u in pending_users if u.player]
            _qp_ids = [qp.id for qp in field_profiles]
            if _player_ids:
                for n in db.session.query(PlayerAdminNote).options(
                    joinedload(PlayerAdminNote.author).joinedload(User.player)
                ).filter(PlayerAdminNote.player_id.in_(_player_ids)).order_by(
                    PlayerAdminNote.created_at.desc()
                ):
                    notes_by_player.setdefault(n.player_id, []).append(n)
            if _qp_ids:
                for n in db.session.query(PlayerAdminNote).options(
                    joinedload(PlayerAdminNote.author).joinedload(User.player)
                ).filter(PlayerAdminNote.quick_profile_id.in_(_qp_ids)).order_by(
                    PlayerAdminNote.created_at.desc()
                ):
                    notes_by_quick_profile.setdefault(n.quick_profile_id, []).append(n)
        except Exception as e:
            logger.error(f"Error loading waiting-room notes: {str(e)}")

        return render_template(
            'admin_panel/users/user_approvals_flowbite.html',
            pending_users=pending_users,
            recent_actions=recent_actions,
            audit_logs=audit_logs,
            field_profiles=field_profiles,
            limbo_profiles=limbo_profiles,
            notes_by_player=notes_by_player,
            notes_by_quick_profile=notes_by_quick_profile,
            stats=stats,
            # Pass filter values back to template for form persistence
            status_filter=status_filter,
            league_filter=league_filter,
            search_query=search_query
        )
    except Exception as e:
        logger.error(f"Error loading user approvals: {e}")
        flash('User approvals unavailable. Check database connectivity and user models.', 'error')
        return redirect(url_for('admin_panel.users_comprehensive'))


# Approval "outcome" vocabulary. The six league/sub types below place a person
# INTO a league (as member or sub). The three waitlist-* types park them on a
# per-league holding lane instead. approve_user validates against the union.
# ⚠️ FALLBACK ONLY. Resolve through sub_league_display() -- never index this
# dict directly. approve_user validates `league_type` against the
# registry-driven approve_league_types(), so a newer program's 'sub-<lane>' is
# ACCEPTED by the gate and then missing from this literal. The miss is not an
# error: `league_type in SUB_LEAGUE_DISPLAY` is simply False, the request falls
# into the full-MEMBER branch, and that branch deactivates every SubstitutePool
# and EcsFcSubPool row the person has. Approving someone as a new program's sub
# therefore wiped their existing Classic/ECS FC sub memberships and enrolled
# them in nothing, while flagging them a paid active player.
_SUB_LEAGUE_DISPLAY_FALLBACK = {
    'sub-classic': 'Classic',
    'sub-premier': 'Premier',
    'sub-ecs-fc': 'ECS FC',
}


def sub_league_display(league_type):
    """League display name for a 'sub-<lane>' approval outcome, or None."""
    if not league_type or not str(league_type).startswith('sub-'):
        return None
    lane = str(league_type)[len('sub-'):]
    try:
        from app.services import program_registry
        for _pr in program_registry.all_programs():
            if (_pr.membership_lane or '').replace('_', '-') == lane.replace('_', '-'):
                return _pr.league_name
            if (_pr.form_value or '') == lane:
                return _pr.league_name
    except Exception as _sd_err:
        logger.warning(f"program registry unavailable resolving '{league_type}': {_sd_err}")
    return _SUB_LEAGUE_DISPLAY_FALLBACK.get(league_type)


def sub_league_displays():
    """Every league display name that has a substitute lane."""
    names = set(_SUB_LEAGUE_DISPLAY_FALLBACK.values())
    try:
        from app.services import program_registry
        names.update(p.league_name for p in program_registry.all_programs()
                     if p.league_name)
    except Exception:
        pass
    return names
# FALLBACK ONLY -- resolve through waitlist_league_map(). A program missing from
# the literal simply could not be waitlisted for: the outcome value was rejected
# with a 400 and there was no other route in.
_WAITLIST_LEAGUE_MAP_FALLBACK = {
    'waitlist-classic': 'classic',
    'waitlist-premier': 'premier',
    'waitlist-ecs-fc': 'ecs-fc',
}


def waitlist_league_map():
    """'waitlist-<lane>' outcome -> the waitlist lane stored on the player."""
    out = dict(_WAITLIST_LEAGUE_MAP_FALLBACK)
    try:
        from app.services import program_registry
        for _pr in program_registry.all_programs():
            _lane = (_pr.form_value or _pr.membership_lane or '').replace('_', '-')
            if _lane:
                out[f'waitlist-{_lane}'] = _lane
    except Exception:
        pass
    return out


# Back-compat alias for any reader expecting the old name.
WAITLIST_LEAGUE_MAP = _WAITLIST_LEAGUE_MAP_FALLBACK


def _enroll_in_substitute_pool(session, player, league_display: str, approver_id: int):
    """Enroll a player in the substitute pool for a league (current season).

    ⚠️ SubstitutePool is keyed on (player_id, league_type) -- NOT on player_id
    alone. A player may legitimately be a sub in several programs at once.
    Upsert on BOTH columns.

    This used to do `filter_by(player_id=...).first()` and overwrite that row's
    league_type. Once a player could hold two rows that had two failure modes:
    approving an existing Classic sub as a Summer sub REPOINTED their Classic
    row (silently removing them from the Classic broadcast list while they kept
    the Classic Sub role), and for a player who already held two rows the UPDATE
    could collide with uq_substitute_pool_player_league_type and 500 the
    approval.

    ECS FC additionally mirrors into the legacy EcsFcSubPool table, which the
    integrity checker requires to stay in sync. The Discord 'X Sub' role is
    granted by apply_approval's role_mapping; the deferred sync there propagates
    it — we don't touch roles here. Season is implicit (is_active=True), the
    pool has no season_id.
    """
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    now = datetime.utcnow()

    existing = session.query(SubstitutePool).filter_by(
        player_id=player.id, league_type=league_display).first()
    if existing:
        existing.is_active = True
        existing.approved_by = approver_id
        existing.approved_at = now
    else:
        session.add(SubstitutePool(
            player_id=player.id,
            league_type=league_display,
            is_active=True,
            approved_by=approver_id,
            approved_at=now,
        ))

    if league_display == 'ECS FC':
        ecs = session.query(EcsFcSubPool).filter_by(player_id=player.id).first()
        if ecs:
            ecs.is_active = True
        else:
            session.add(EcsFcSubPool(player_id=player.id, is_active=True))

    player.is_sub = True
    logger.info(f"Enrolled player {player.id} in {league_display} substitute pool")


def _apply_waitlist(user, league: str, approver_id: int, notes=None):
    """Park a reviewed prospect on the per-league waitlist (a holding lane).

    Waitlist is NOT approval: is_approved stays False. We deliberately keep
    approval_status='pending' (NOT a new 'waitlist' value) because the ENTIRE
    waitlist system — the waitlist page query, remove-from-waitlist, the integrity
    G15 fixer, deny_user — keys off the pl-waitlist ROLE and assumes waitlisted
    users are 'pending'. A distinct status silently strands them on every one of
    those paths. The "parked, not in the pending queue" separation is instead done
    by EXCLUDING pl-waitlist role-holders from the approvals pending list (see
    user_approvals). Any league/sub roles and active pool rows are cleared so a
    waitlisted person is never simultaneously an active sub/member.
    """
    # Strip league + sub + unverified roles; add pl-waitlist.
    # Registry-driven: a program missing from a hardcoded list keeps its stale
    # sub/league role through being waitlisted.
    from app.services import program_registry
    strip_roles = (['pl-unverified'] + list(program_registry.league_role_names())
                   + list(program_registry.sub_role_names()))
    for rname in strip_roles:
        r = db.session.query(Role).filter_by(name=rname).first()
        if r and r in user.roles:
            user.roles.remove(r)
    waitlist_role = db.session.query(Role).filter_by(name='pl-waitlist').first()
    if waitlist_role and waitlist_role not in user.roles:
        user.roles.append(waitlist_role)

    user.approval_status = 'pending'
    user.is_approved = False
    user.approval_league = None
    if user.waitlist_joined_at is None:
        user.waitlist_joined_at = datetime.utcnow()
    user.waitlist_league = league
    if notes is not None:
        user.approval_notes = notes

    # A waitlisted person is not an active sub — deactivate any pool rows.
    if user.player:
        from app.models.substitutes import SubstitutePool, EcsFcSubPool
        for row in db.session.query(SubstitutePool).filter_by(player_id=user.player.id).all():
            row.is_active = False
        for row in db.session.query(EcsFcSubPool).filter_by(player_id=user.player.id).all():
            row.is_active = False
        user.player.is_current_player = False

    db.session.add(user)
    db.session.flush()

    # Phase-0 dual-write: mirror this transition into the league_membership spine.
    if user.player:
        resync_player_memberships(db.session, user.player.id)

    if user.player and user.player.discord_id:
        defer_discord_sync(user.player.id, only_add=False)
        logger.info(f"Queued Discord role sync for waitlisted user {user.id}")


def apply_approval(user, league_type: str, approver_id: int, notes=None):
    """Core approval mutation: role mapping, approval fields, current-season league
    assignment, substitute-pool enrollment, and deferred Discord sync. Caller owns
    locking, league_type validation, auditing, and the transaction (uses db.session
    throughout).

    Handles three outcome families:
      * league member (classic / premier / ecs-fc)
      * substitute (sub-classic / sub-premier / sub-ecs-fc) — also enrolls in the pool
      * waitlist (waitlist-classic / waitlist-premier / waitlist-ecs-fc) — holding lane

    Shared by the approve_user route and the integrity dashboard's reconcile
    actions (G1 pending-rostered, G2 approval drift, G3 missing league role) —
    "re-run approval" means exactly this block, so keeping one copy prevents the
    two paths from drifting. (Integrity paths only ever pass the six league/sub
    types, never waitlist-*.)

    Raises ValueError if the mapped Role row does not exist.
    """
    # Waitlist routing is a separate lane, not an approval — handle and return.
    _wl_map = waitlist_league_map()
    if league_type in _wl_map:
        _apply_waitlist(user, _wl_map[league_type], approver_id, notes)
        return

    role_mapping = {
        'classic': 'pl-classic',
        'premier': 'pl-premier',
        'ecs-fc': 'pl-ecs-fc',
        'sub-classic': 'Classic Sub',
        'sub-premier': 'Premier Sub',
        'sub-ecs-fc': 'ECS FC Sub'
    }

    # Registry fallback BEFORE subscripting. approve_league_types() is now
    # registry-derived and the three validators let a newer program's value
    # through, so a bare role_mapping[league_type] turned a clean
    # "400 Invalid league type" into an uncaught KeyError -> 500.
    new_role_name = role_mapping.get(league_type)
    if not new_role_name:
        try:
            from app.services import program_registry
            _prog = program_registry.by_form_value(league_type)
            if _prog:
                new_role_name = (_prog.flask_sub_role
                                 if str(league_type).startswith('sub-')
                                 else _prog.flask_league_role)
        except Exception as _reg_err:
            logger.warning(f"registry lookup failed for league_type "
                           f"'{league_type}': {_reg_err}")
    if not new_role_name:
        raise ValueError(f'Unknown league type: {league_type}')
    new_role = db.session.query(Role).filter_by(name=new_role_name).first()
    if not new_role:
        raise ValueError(f'Role {new_role_name} not found')

    # Remove the pl-unverified role
    unverified_role = db.session.query(Role).filter_by(name='pl-unverified').first()
    if unverified_role and unverified_role in user.roles:
        user.roles.remove(unverified_role)

    # Remove the pl-waitlist role (if user was on waitlist)
    waitlist_role = db.session.query(Role).filter_by(name='pl-waitlist').first()
    if waitlist_role and waitlist_role in user.roles:
        user.roles.remove(waitlist_role)

    # Remove any existing league/sub roles before adding the new one — prevents role
    # accumulation AND cross-division sub leaks. The live sub matcher keys off the
    # 'X Sub' role name (not the pool's league_type), so a stale 'Premier Sub' left
    # on a player being approved as 'Classic Sub' would still surface them as an
    # active Premier sub. Strip every league/sub role except the one we're granting.
    from app.services import program_registry as _pr_reg
    for role_name in (list(_pr_reg.league_role_names())
                      + list(_pr_reg.sub_role_names())):
        if role_name != new_role_name:  # Don't remove the one we're about to add
            existing_role = db.session.query(Role).filter_by(name=role_name).first()
            if existing_role and existing_role in user.roles:
                user.roles.remove(existing_role)
                logger.info(f"Removed old role {role_name} from user {user.id}")

    # Add the new approved role
    if new_role not in user.roles:
        user.roles.append(new_role)

    # Update user approval status
    user.approval_status = 'approved'
    user.is_approved = True
    user.approval_league = league_type
    user.approved_by = approver_id
    user.approved_at = datetime.utcnow()
    if notes is not None:
        user.approval_notes = notes

    # Clear waitlist state - user now has a spot (leaving the holding lane)
    user.waitlist_joined_at = None
    user.waitlist_league = None

    # Assign player to current season league based on league_type
    if user.player and league_type:
        from app.services.season_sync_service import SeasonSyncService

        # Map league_type to league name and type
        league_type_mapping = {
            'classic': ('Classic', 'Pub League'),
            'premier': ('Premier', 'Pub League'),
            'ecs-fc': ('ECS FC', 'ECS FC'),
            'sub-classic': ('Classic', 'Pub League'),
            'sub-premier': ('Premier', 'Pub League'),
            'sub-ecs-fc': ('ECS FC', 'ECS FC'),
        }

        mapping = league_type_mapping.get(league_type)
        if not mapping:
            # Registry lookup for any program not in the legacy dict. Strips the
            # 'sub-' prefix the same way the dict's sub-* entries do -- a sub is
            # approved into the SAME league as a full member, the difference is
            # carried by the Flask sub role, not by the league.
            try:
                from app.services import program_registry
                program = program_registry.by_form_value(league_type)
                if program:
                    mapping = (program.league_name, program.season_league_type)
            except Exception as _reg_err:
                logger.warning(f"program registry lookup failed for approval "
                               f"league_type '{league_type}': {_reg_err}")
        if mapping:
            league_name, season_league_type = mapping
            current_league = SeasonSyncService.get_current_league_by_name(
                db.session, league_name, season_league_type
            )
            if current_league:
                # Route through the shared additive helper instead of the
                # unconditional two-line overwrite. Approving a Premier player
                # into another program used to evict their Premier
                # primary_league_id, dropping them out of the Premier draft
                # pool (predicate: primary_league_id == league OR player_league
                # row) with no error anywhere.
                from app.pub_league.services import PlayerActivationService
                PlayerActivationService._assign_league_additively(
                    db.session, user.player, current_league)
                # Two-axis model: approval grants MEMBERSHIP (is_approved).
                # For pay-per-season Pub League divisions (Classic/Premier),
                # "active this season" (is_current_player) is granted by
                # PAYMENT — linking a pass — NOT by approval, so we do not
                # flip it here (that would let an approved-but-unpaid user in
                # for free). ECS FC and subs have no season pass, so approval
                # activates them directly.
                # Registry-driven: a program with requires_pass=True must NOT be
                # activated by approval. The literal ('classic', 'premier') meant
                # any newer PAID program fell through to the else-branch and got
                # is_current_player=True for free -- approval alone would hand
                # out a season pass. Subs never pay, so the sub-* variants stay
                # activated by approval regardless of the program's pass rule.
                _is_sub_lane = str(league_type).startswith('sub-')
                # ⚠️ DEFAULT TRUE. is_current_player means "paid this season", so
                # an UNKNOWN program must be treated as pay-to-play: failing open
                # here hands out a free season pass. The previous default of
                # False did exactly that whenever by_form_value returned None
                # (partially seeded registry, or classic/premier set inactive) --
                # and the except branch was stricter than the success branch,
                # which is backwards.
                _needs_pass = True
                try:
                    from app.services import program_registry
                    _prog = program_registry.by_form_value(league_type)
                    if _prog is not None:
                        _needs_pass = bool(_prog.requires_pass)
                    else:
                        logger.warning(
                            f"approval: no program for league_type '{league_type}'; "
                            f"treating as pay-to-play (not activating)")
                except Exception as _pp_err:
                    logger.warning(f"approval: requires_pass lookup failed for "
                                   f"'{league_type}': {_pp_err}; treating as pay-to-play")
                # Subs never pay, so they are activated by approval regardless.
                if _is_sub_lane or not _needs_pass:
                    user.player.is_current_player = True
                logger.info(f"Assigned player {user.player.id} to current season league {current_league.id} ({league_name})")

                # Clear draft cache so player appears immediately.
                # Deferred until after commit so Redis I/O doesn't
                # extend the user row lock.
                defer_clear_league_cache(league_name.lower())
            else:
                logger.warning(f"Could not find current season league for type '{league_type}'")

    if user.player:
        _sub_display = sub_league_display(league_type)
        if _sub_display:
            # Substitute approvals must actually enroll the player in the pool —
            # granting the 'X Sub' role alone left them a sub in name only, never
            # surfacing in sub-request matching. Subs have no season pass, so they
            # are active immediately; set is_current_player here (NOT only inside the
            # current-league branch above) so enrollment isn't a silent no-op when no
            # current-season league row is found — the matcher filters is_current_player.
            user.player.is_current_player = True
            _enroll_in_substitute_pool(db.session, user.player, _sub_display, approver_id)
        else:
            # Full-league member: they are not a sub OF THIS DIVISION FAMILY.
            #
            # ⚠️ Scoped, not global. Being rostered in one program says nothing
            # about sub status in a concurrent, independent program -- someone
            # can legitimately play Premier and sub for Summer. Deactivating
            # every row silently removed people from unrelated pools; is_sub is
            # only cleared when nothing active is left anywhere.
            from app.models.substitutes import SubstitutePool, EcsFcSubPool
            _family_names = None
            try:
                from app.services import program_registry
                _self = program_registry.by_league_name(league_name) if league_name else None
                if _self is not None:
                    _family_names = [p.league_name for p in program_registry.all_programs()
                                     if p.season_league_type == _self.season_league_type
                                     and p.league_name]
            except Exception as _fam_err:
                logger.warning(f"could not scope sub cleanup for '{league_name}': {_fam_err}")

            _q = db.session.query(SubstitutePool).filter_by(
                player_id=user.player.id, is_active=True)
            if _family_names:
                _q = _q.filter(SubstitutePool.league_type.in_(_family_names))
            for row in _q.all():
                row.is_active = False
            # EcsFcSubPool only conflicts with an ECS FC membership.
            if not _family_names or 'ECS FC' in _family_names:
                for row in db.session.query(EcsFcSubPool).filter_by(
                        player_id=user.player.id, is_active=True).all():
                    row.is_active = False

            _still_sub = (
                db.session.query(SubstitutePool).filter_by(
                    player_id=user.player.id, is_active=True).first() is not None
                or db.session.query(EcsFcSubPool).filter_by(
                    player_id=user.player.id, is_active=True).first() is not None)
            user.player.is_sub = bool(_still_sub)

    db.session.add(user)
    db.session.flush()

    # Phase-0 dual-write: mirror this approval (league / sub) into the spine.
    if user.player:
        resync_player_memberships(db.session, user.player.id)

    # Queue Discord role sync for AFTER transaction commits
    if user.player and user.player.discord_id:
        defer_discord_sync(user.player.id, only_add=False)
        logger.info(f"Queued Discord role sync for approved user {user.id}")


def _approval_body():
    """The approve/deny/undeny body, form OR JSON.

    These three shipped as `request.form` readers because they were only ever
    hit by the Hub's HTML forms. The mobile client posts JSON to the SAME
    mutations, so read both — `get_json(silent=True)` because Flask 3 raises
    400/415 on a non-JSON body before any `or {}` fallback can run.
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return request.form


@admin_panel_bp.route('/users/approvals/approve/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional(max_retries=3)
def approve_user(user_id: int):
    """Approve a user for a league / sub pool, or park them on a waitlist lane.

    Body: `league_type` (required) + `notes`. The mutation itself lives in
    `app/services/member_lifecycle_service.py` and is shared with
    `POST /api/v1/admin/members/<id>/approve` — one copy, so the phone and the
    website can never disagree about what approval does.
    """
    from app.services.member_lifecycle_service import approve_member
    body = _approval_body()
    current_user_safe = safe_current_user
    payload, status = approve_member(
        user_id=user_id,
        league_type=body.get('league_type'),
        actor_id=current_user_safe.id,
        actor_username=current_user_safe.username,
        notes=body.get('notes'),
    )
    # Discord sync and cache clears dispatch automatically after the
    # @transactional decorator commits, via after_this_request hooks.
    return jsonify(payload), status


@admin_panel_bp.route('/users/approvals/deny/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional(max_retries=3)
def deny_user(user_id: int):
    """Deny a pending application. Shared mutation — see approve_user."""
    from app.services.member_lifecycle_service import deny_member
    body = _approval_body()
    current_user_safe = safe_current_user
    payload, status = deny_member(
        user_id=user_id,
        actor_id=current_user_safe.id,
        actor_username=current_user_safe.username,
        notes=body.get('notes'),
    )
    return jsonify(payload), status


@admin_panel_bp.route('/users/approvals/undeny/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional(max_retries=3)
def undeny_user(user_id: int):
    """Reverse a denial: put a denied person back into the pending queue.

    Deny was a one-way door — it set approval_status='denied' + is_approved=False
    and stripped pl-unverified, and every other path then refused to touch the
    person, so a mis-click left no way back short of raw SQL. This restores the
    pre-decision state rather than approving anyone. Shared mutation — see
    approve_user.
    """
    from app.services.member_lifecycle_service import undeny_member
    body = _approval_body()
    current_user_safe = safe_current_user
    payload, status = undeny_member(
        user_id=user_id,
        actor_id=current_user_safe.id,
        actor_username=current_user_safe.username,
        notes=body.get('notes'),
    )
    return jsonify(payload), status


@admin_panel_bp.route('/users/approvals/process', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def process_user_approval():
    """Legacy route for bulk approval processing."""
    try:
        action = request.form.get('action')
        user_id = request.form.get('user_id')

        if action == 'approve_all':
            # Approve all pending users — but NOT those parked on the waitlist
            # (pending + pl-waitlist role). Sweeping them in would approve them
            # with no league assigned and yank them off the waitlist unintentionally.
            pending_users = db.session.query(User).filter(*User.pending_approval_criteria()).all()
            approved_count = 0

            for user in pending_users:
                # Redirect to individual approval with default league
                try:
                    # This is a simplified bulk approval - in practice you might want more control
                    if user.approval_status == 'pending':
                        user.approval_status = 'approved'
                        user.is_approved = True
                        user.approved_by = current_user.id
                        user.approved_at = datetime.utcnow()
                        approved_count += 1
                except Exception as e:
                    logger.error(f"Error bulk approving user {user.id}: {e}")

            db.session.commit()

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='approve_all',
                resource_type='user_approval',
                resource_id='bulk',
                new_value=f"Approved {approved_count} users",
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            flash(f'{approved_count} pending users approved successfully', 'success')

        return redirect(url_for('admin_panel.user_approvals'))
    except Exception as e:
        logger.error(f"Error processing user approval: {e}")
        flash('User approval processing failed. Check database connectivity and role assignment.', 'error')
        return redirect(url_for('admin_panel.user_approvals'))


@admin_panel_bp.route('/users/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def get_user_details():
    """Get detailed information about a user for the approval modal."""
    try:
        user_id = request.args.get('user_id')

        user = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).get(user_id)

        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        user_data = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'approval_status': user.approval_status,
            'approval_league': user.approval_league,
            'approval_notes': user.approval_notes,
            'is_approved': user.is_approved,
            'roles': [role.name for role in user.roles],
            'player': {
                'id': user.player.id,
                'name': user.player.name,
                'discord_id': user.player.discord_id,
                'is_current_player': user.player.is_current_player,
                'is_sub': user.player.is_sub,
                'is_coach': user.player.is_coach,
                'phone': user.player.phone,
                'jersey_size': user.player.jersey_size,
                'pronouns': user.player.pronouns,
                'favorite_position': user.player.favorite_position,
                'profile_picture_url': user.player.profile_picture_url
            } if user.player else None
        }

        return jsonify({'success': True, 'user': user_data})

    except Exception as e:
        logger.error(f"Error getting user details for {user_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'Error retrieving user details'}), 500


@admin_panel_bp.route('/api/users/<int:user_id>/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def user_details_api(user_id):
    """Get detailed user information for modal display."""
    try:
        user = db.session.query(User).options(
            joinedload(User.player),
            joinedload(User.roles)
        ).get(user_id)

        if not user:
            logger.warning(f"User ID {user_id} not found in database - may be stale data in UI")
            return jsonify({
                'success': False,
                'error': f'User with ID {user_id} not found. Please refresh the page.',
                'user_id': user_id
            }), 404

        user_data = {
            'id': user.id,
            'first_name': getattr(user, 'first_name', None),
            'last_name': getattr(user, 'last_name', None),
            'username': user.username,
            'email': user.email,
            'real_name': user.player.name if user.player else None,
            'phone': getattr(user, 'phone', None),
            'discord_username': getattr(user, 'discord_username', None),
            'status': getattr(user, 'status', user.approval_status),
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'last_login': getattr(user, 'last_login', None),
            'role': user.roles[0].name if user.roles else None,
            'all_roles': [role.name for role in user.roles],
            'roles': [role.id for role in user.roles],  # Array of role IDs for form
            'approval_status': user.approval_status,
            'approval_league': user.approval_league,
            'approval_notes': user.approval_notes,
            'is_approved': user.is_approved,
            'is_active': user.is_active,
            # Lifecycle axes (birth -> death): where this person sits on each
            # independent track, so the modal can render an at-a-glance strip.
            'on_waitlist': any(r.name == 'pl-waitlist' for r in user.roles),
            'waitlist_league': user.waitlist_league,
            'waitlist_joined_at': user.waitlist_joined_at.isoformat() if user.waitlist_joined_at else None,
        }

        # Add profile information if available
        if user.player:
            # Get all team IDs for players on multiple teams
            all_team_ids = [team.id for team in user.player.teams] if user.player.teams else []
            # Get secondary leagues (other_leagues relationship)
            other_league_ids = [lg.id for lg in user.player.other_leagues] if user.player.other_leagues else []

            # Find secondary team (first team that's not the primary team)
            secondary_team_id = None
            secondary_league_id = other_league_ids[0] if other_league_ids else None
            for team in user.player.teams:
                if team.id != user.player.primary_team_id:
                    secondary_team_id = team.id
                    # Also get that team's league if we don't have a secondary league yet
                    if not secondary_league_id and team.league_id:
                        secondary_league_id = team.league_id
                    break

            # Get ECS FC team IDs (for multi-team selection)
            ecs_fc_team_ids = [
                team.id for team in user.player.teams
                if is_ecs_fc_team(team.id)
            ] if user.player.teams else []

            # Get league names for direct type detection
            primary_league_name = user.player.primary_league.name if user.player.primary_league else None
            other_league_names = [lg.name for lg in user.player.other_leagues] if user.player.other_leagues else []

            # Per-team coach status (team_id -> is_coach) for the modal's per-tier
            # coach checkboxes — coach is scoped to a specific team membership, so
            # this lets the modal pre-check the right team's coach box.
            from app.models import player_teams as _pt
            team_coach_map = {
                str(row.team_id): bool(row.is_coach)
                for row in db.session.execute(
                    _pt.select().where(_pt.c.player_id == user.player.id)
                ).fetchall()
            }

            user_data['has_player'] = True
            user_data['player'] = {
                'id': user.player.id,
                'name': user.player.name,
                'league_id': user.player.primary_league_id,
                'primary_league_name': primary_league_name,
                'team_id': user.player.primary_team_id,
                'secondary_league_id': secondary_league_id,
                'secondary_team_id': secondary_team_id,
                'other_league_ids': other_league_ids,
                'other_league_names': other_league_names,
                'team_ids': all_team_ids,
                'ecs_fc_team_ids': ecs_fc_team_ids,
                'is_current_player': user.player.is_current_player,
                'is_sub': user.player.is_sub,
                'discord_id': user.player.discord_id,
                'jersey_size': user.player.jersey_size,
                'phone': user.player.phone,
                'pronouns': user.player.pronouns,
                'favorite_position': user.player.favorite_position,
                'profile_picture_url': user.player.profile_picture_url,
                'team_coach_map': team_coach_map
            }
        else:
            user_data['has_player'] = False
            user_data['player'] = None

        return jsonify({'success': True, 'user': user_data})

    except Exception as e:
        logger.error(f"Error getting user details: {e}")
        return jsonify({'success': False, 'error': 'Failed to get user details'}), 500
