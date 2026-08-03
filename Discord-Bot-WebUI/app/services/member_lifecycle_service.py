# app/services/member_lifecycle_service.py

"""
Member Lifecycle Service — the one copy of every member-hub write.

The portal's Members hub exposed 16 lifecycle actions; the mobile API had 3.
The other 13 lived as route bodies inside `app/admin_panel/routes/user_management/`,
reachable only by a session-cookie POST, so an admin on the phone had to open the
website to clear a pending signup.

This module holds those bodies. Both surfaces now call the SAME function:

    web    admin_panel/routes/user_management/*.py   (@login_required + @role_required)
    mobile app/mobile_api/admin_members.py           (@jwt_required + @jwt_role_required)

so the two can't drift the way the ECS FC notification paths did. Each function
returns ``(payload_dict, http_status)``; the caller only jsonifies it.

⚠️ SESSION: these functions use ``db.session`` directly and take no session
argument. That is deliberate, not laziness. The helpers they build on
(``apply_approval``, ``_reconcile_sub_roles``, ``resync_player_memberships``
callers, ``lock_user_for_role_update``) are already hardcoded to ``db.session``;
handing them a second session (``g.db_session``, what ``managed_session()``
yields inside a request) would put half the mutation in a transaction nobody
commits — writes vanish with no error. Callers MUST therefore be wrapped in
``@transactional``, which commits both sessions. Read helpers at the bottom of
this file DO take a session, because a read is safe on either.

⚠️ ACTOR: the web handlers read ``current_user``; mobile has a JWT identity and no
Flask-Login user. Every function takes ``actor_id``/``actor_username`` explicitly.
"""

import logging
from datetime import datetime

from app.core import db
from app.models.admin_config import AdminAuditLog

logger = logging.getLogger(__name__)


# Waitlist priority is a fixed vocabulary, NOT a rank number. 'auto' stores NULL
# and lets join time order the queue. Exposed through describe_member_options()
# so a client never has to carry this list.
WAITLIST_PRIORITIES = ('high', 'medium', 'normal', 'auto')

# Server-side ceiling for the worklist. Stated in every response: a silent cap
# reads as "that's everyone" (the /draft/available cap at 100 bit us that way).
WORKLIST_PER_PAGE_CAP = 100
WORKLIST_PER_PAGE_DEFAULT = 50


# ---------------------------------------------------------------------------
# result helpers
# ---------------------------------------------------------------------------

def _text(value, default=''):
    """Untrusted JSON value -> a stripped string, or None if it isn't a scalar.

    A JSON body can carry a list, dict or null where a string is expected, and
    ``(value or '').strip()`` raises AttributeError on those — turning what
    should be a clean 400 from the validator into a 500. Non-scalars return
    None so the caller's own validation rejects them; they must NOT collapse to
    '' where '' has a meaning (it clears a quick-profile pre-approval).

    Validation lives here rather than in the route because the web handlers
    share these functions and can be sent the same shapes.
    """
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    return None


def _ok(message, **extra):
    payload = {'success': True, 'message': message}
    payload.update(extra)
    return payload, 200


def _err(message, status=400, **extra):
    payload = {'success': False, 'message': message}
    payload.update(extra)
    return payload, status


def _audit(action, resource_type, resource_id, actor_id,
           old_value=None, new_value=None):
    """Audit-log wrapper that never takes the caller down with it.

    Request metadata is read here rather than passed in so both surfaces record
    the same shape. Outside a request context (CLI/Celery) it degrades to no IP.
    """
    try:
        from flask import request, has_request_context
        ip = request.remote_addr if has_request_context() else None
        ua = request.headers.get('User-Agent') if has_request_context() else None
        AdminAuditLog.log_action(
            user_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            old_value=old_value,
            new_value=new_value,
            ip_address=ip,
            user_agent=ua,
        )
    except Exception as exc:
        logger.warning(f"audit log skipped for {action}/{resource_id}: {exc}")


def _discord_queued(player):
    """Did this mutation queue a Discord role change the client should surface?

    The deferred helpers return nothing, so "queued" is exactly "the player has a
    Discord account to sync". Mobile renders a "Discord role updating…" hint off
    this, the same as it already does after a role change.
    """
    return bool(player is not None and getattr(player, 'discord_id', None))


# ---------------------------------------------------------------------------
# vocabularies (§3 — so no client hardcodes a league list)
# ---------------------------------------------------------------------------

def lane_clause(col, lane):
    """ilike predicate matching a membership lane against a stored league column.

    Stored lane values are not canonical — the same lane appears as 'Classic',
    'classic' and 'pub_league_classic' depending on which writer got there first,
    so this matches on a fragment rather than equality. Registry-driven: the
    hardcoded classic/premier/ecs_fc version returned None for a newer program,
    which silently turned that program's lane filter into "no filter".
    """
    if not lane:
        return None

    probe = str(lane).strip().replace('-', '_').lower()

    # ⚠️ An UNRECOGNISED lane must return None — "no filter", show everyone —
    # which is what the hardcoded classic/premier/ecs_fc version did. Returning
    # a pattern for it (e.g. 'undecided', or a stale bookmarked value) flips the
    # page from "all pending" to EMPTY, which reads as a program with no members
    # rather than as a filter that matched nothing.
    known = {'classic', 'premier', 'ecs_fc'}
    program = None
    try:
        from app.services import program_registry
        known |= {p.membership_lane for p in program_registry.all_programs()
                  if p.membership_lane}
        program = program_registry.by_membership_lane(probe)
    except Exception:
        pass
    if probe not in {str(k).replace('-', '_').lower() for k in known}:
        return None

    if probe == 'classic':
        return col.ilike('%classic%')
    if probe == 'premier':
        return col.ilike('%premier%')
    if probe == 'ecs_fc':
        return col.ilike('%ecs%')

    # Newer programs: the stored spelling drifts across separators AND between
    # the lane and the League display name, so match ANY of them. Do NOT collapse
    # this to one separator-stripped pattern ('pl_third' -> '%plthird%'): no
    # writer ever stores that, so it matches nothing.
    from sqlalchemy import or_
    variants = {str(lane),
                str(lane).replace('_', '-'),
                str(lane).replace('-', '_'),
                str(lane).replace('_', ' ').replace('-', ' ')}
    if program is not None:
        for value in (program.league_name, program.form_value,
                      program.display_name, program.short_name):
            if value:
                variants.add(str(value))

    clauses = [col.ilike(f'%{v}%') for v in sorted(variants) if v]
    if not clauses:
        return None
    return or_(*clauses) if len(clauses) > 1 else clauses[0]


def approve_league_type_values():
    """Every value ``approve_member`` accepts, split by what it does.

    Three vocabularies that genuinely disagree, which is why this is data and not
    a constant in the app: approving wants ``form_value or membership_lane``
    (e.g. ``pl_third``), waitlisting wants ``waitlist-<lane with hyphens>``
    (``waitlist-pl-third``), and the sub-pool endpoints want a LANE or a League
    display name. Offering a value the validator rejects is a 400 the admin
    cannot explain.
    """
    from app.services.integrity_service import approve_league_types
    from app.admin_panel.routes.user_management.approvals import waitlist_league_map
    from app.admin_panel.routes.user_management.member_hub import (
        _approve_program_options, _preapproval_values)

    league = [v for v in approve_league_types() if not str(v).startswith('sub-')]
    sub = [v for v in approve_league_types() if str(v).startswith('sub-')]
    return {
        'league': sorted(set(league)),
        'sub': sorted(set(sub)),
        'waitlist': sorted(waitlist_league_map().keys()),
        'programs': _approve_program_options(),
        'preapproval': sorted(_preapproval_values()),
    }


def sub_lane_options():
    """[{lane, label, accepts}] for the four sub-pool endpoints.

    ``lane`` is the membership lane (what ``GET /api/v1/programs`` calls
    ``membership_lane``); ``label`` is the League display name actually stored in
    ``SubstitutePool.league_type``. The web modal posts the label and the mobile
    spec assumed the lane, so ``resolve_sub_lane`` accepts either — this reports
    both rather than making a client guess which one is canonical.
    """
    from app.admin_panel.routes.user_management.member_hub import label_to_canon

    # resolve_sub_lane ALSO matches a program's form_value, so leaving it out
    # published a narrower set than the endpoints accept. Invisible today only
    # because every seeded program's form_value coincides with its lane or the
    # hyphen spelling — the first program where they diverge would have an
    # accepted spelling that this never advertised, while `approve.programs` in
    # the same response published it. Two vocabularies in one payload
    # disagreeing is exactly what this endpoint exists to prevent.
    form_values = {}
    try:
        from app.services import program_registry
        for p in program_registry.all_programs():
            if p.membership_lane and p.form_value:
                form_values[p.membership_lane] = p.form_value
    except Exception:
        pass

    out = []
    for label, lane in sorted(label_to_canon().items(), key=lambda kv: kv[1]):
        accepts = {lane, label, lane.replace('_', '-')}
        if form_values.get(lane):
            accepts.add(form_values[lane])
        out.append({
            'lane': lane,
            'label': label,
            'accepts': sorted(accepts),
            # Matching is case- and whitespace-insensitive on top of these, so
            # this is the canonical set, not an exhaustive one.
            'case_insensitive': True,
        })
    return out


def resolve_sub_lane(value):
    """Any spelling of a sub lane -> ``(lane, League display name)``.

    Accepts the League display name ('ECS FC'), the membership lane ('ecs_fc'),
    the hyphenated lane ('ecs-fc') and the program's form value, because the web
    modal, the program registry and the mobile spec each picked a different one.
    Returns ``(None, None)`` for anything else.

    ⚠️ EXACT matches only. It is tempting to fall back to
    ``league_membership_sync._norm_league_type``, but that is a SUBSTRING matcher
    ('anything containing "ecs"' -> ecs_fc), which is right for reading drifted
    stored values and badly wrong for validating admin input: 'specs' would
    resolve to ECS FC and a typo in a sub-remove would delete the wrong pool row
    instead of returning 400.
    """
    from app.admin_panel.routes.user_management.member_hub import (
        label_to_canon, _canonical_league_type)

    if not value:
        return None, None
    raw = str(value).strip()
    if not raw:
        return None, None
    mapping = label_to_canon()

    # League display name, case-insensitive.
    lane = next((ln for lbl, ln in mapping.items() if lbl.lower() == raw.lower()), None)

    if lane is None:
        # Membership lane, hyphen/underscore interchangeable.
        probe = raw.replace('-', '_').lower()
        lane = next((ln for ln in mapping.values()
                     if ln and ln.replace('-', '_').lower() == probe), None)

    if lane is None:
        # The program registry's form_value, for programs whose form value
        # differs from their lane.
        try:
            from app.services import program_registry
            for p in program_registry.all_programs():
                if p.membership_lane and (p.form_value or '').lower() == raw.lower():
                    lane = p.membership_lane
                    break
        except Exception:
            pass

    if lane is None:
        return None, None
    return lane, _canonical_league_type(lane)


def _quick_profile_statuses():
    """Values the worklist's qp_status filter accepts, from the enum itself."""
    try:
        from app.models.quick_profile import QuickProfileStatus
        return [s.value for s in QuickProfileStatus] + ['all']
    except Exception:
        return ['pending', 'claimed', 'linked', 'expired', 'all']


def _worklist_lane_values():
    """Values the worklist's `lane` filter accepts — underscore lanes only."""
    lanes = {'classic', 'premier', 'ecs_fc'}
    try:
        from app.services import program_registry
        lanes |= {p.membership_lane for p in program_registry.all_programs()
                  if p.membership_lane}
    except Exception:
        pass
    # 'undecided' is waitlist-tab only (no lane chosen yet).
    return sorted(lanes) + ['undecided']


def describe_member_options(session=None):
    """Everything a member-admin screen needs so it hardcodes nothing (§3)."""
    options = {
        'approve': approve_league_type_values(),
        'sub_lanes': sub_lane_options(),
        'waitlist_priorities': list(WAITLIST_PRIORITIES),
        'place_actions': ['add', 'remove', 'primary'],
        'worklist': {
            'tabs': ['all', 'pending', 'waitlist', 'subs', 'quick_profiles'],
            'per_page_default': WORKLIST_PER_PAGE_DEFAULT,
            'per_page_cap': WORKLIST_PER_PAGE_CAP,
            # The worklist FILTER vocabularies. These were missing, which made
            # "no client hardcodes a vocabulary" false for the busiest endpoint:
            # the filters are closed sets in the code but nothing validates
            # them, so a wrong value is never a 400 — active=no silently returns
            # EVERYONE, and sub_status/qp_status garbage silently returns an
            # empty list. A client had no way to learn the right spellings.
            'filters': {
                'approval': ['approved', 'pending', 'denied', 'all'],
                'active': ['true', 'false'],
                'season': ['active', 'inactive'],
                'sub_status': ['active', 'resting'],
                'qp_status': _quick_profile_statuses(),
                # ⚠️ lane= on the worklist takes the UNDERSCORE membership lane
                # ('ecs_fc'), plus 'undecided' on the waitlist tab. It does NOT
                # take the display-name/hyphen aliases that sub_lanes[].accepts
                # lists for the sub-pool MUTATIONS — those silently match
                # nothing here.
                'lane': _worklist_lane_values(),
            },
            'free_text': ['search', 'role', 'league', 'team'],
        },
    }
    try:
        from app.services.season_phase_service import is_waitlist_open
        options['waitlist_open'] = bool(is_waitlist_open(session or db.session))
    except Exception:
        # Same fallback as the Hub: assume open rather than hiding the option.
        options['waitlist_open'] = True
    return options


# ---------------------------------------------------------------------------
# 1.1 approval lifecycle
# ---------------------------------------------------------------------------

def approve_member(user_id, league_type, actor_id, actor_username, notes=''):
    """Approve a user into a league / sub pool, or park them on a waitlist lane.

    The whole mutation is ``apply_approval`` — shared with the integrity
    dashboard's reconcile actions — so approval is never "flip a boolean": it
    remaps roles, assigns the current-season league, enrolls or clears sub pools,
    clears waitlist state and defers a Discord sync.
    """
    from app.models import User
    from app.admin_panel.routes.user_management.approvals import (
        apply_approval, waitlist_league_map)
    from app.services.integrity_service import approve_league_types
    from app.utils.user_locking import (
        lock_user_for_role_update, LockAcquisitionError, UserNotFoundError)

    league_type = _text(league_type)
    notes = _text(notes) or ''

    try:
        with lock_user_for_role_update(user_id, session=db.session) as user:
            has_waitlist_role = any(r.name == 'pl-waitlist' for r in user.roles)

            # Approving from 'denied' is deliberate — see undeny_member for the
            # "back to the queue, no decision yet" path.
            if user.approval_status not in ('pending', 'denied') and not has_waitlist_role:
                return _err('User is not pending approval or on waitlist')

            wl_map = waitlist_league_map()
            valid_league_types = list(approve_league_types()) + list(wl_map.keys())
            if not league_type or league_type not in valid_league_types:
                return _err('Invalid league type',
                            valid_league_types=sorted(set(valid_league_types)))

            is_waitlist = league_type in wl_map
            # A waitlist -> waitlist move starts from 'waitlist:<lane>', not 'pending'.
            prior_status = (f'waitlist:{user.waitlist_league}'
                            if has_waitlist_role else (user.approval_status or 'pending'))

            try:
                apply_approval(user, league_type, approver_id=actor_id, notes=notes)
            except ValueError as ve:
                return _err(str(ve), 404)

            _audit(
                action=('waitlist_user' if is_waitlist else 'approve_user'),
                resource_type='user_approval', resource_id=user_id, actor_id=actor_id,
                old_value=prior_status,
                new_value=(f'waitlist:{wl_map[league_type]}'
                           if is_waitlist else f'approved:{league_type}'),
            )

            if is_waitlist:
                label = wl_map[league_type].replace('-', ' ').title()
                message = f'User {user.username} placed on the {label} waitlist'
                logger.info(f"User {user.id} waitlisted for {league_type} by {actor_id}")
            else:
                message = f'User {user.username} approved for {league_type.title()} league'
                logger.info(f"User {user.id} approved for {league_type} league by {actor_id}")

            payload = {
                'success': True,
                'message': message,
                'user_id': user.id,
                'league_type': league_type,
                'waitlisted': is_waitlist,
                'approved_by': actor_username,
                # Unset for waitlist routing — parking someone is not an approval.
                'approved_at': user.approved_at.isoformat() if user.approved_at else None,
                'discord_sync_queued': _discord_queued(user.player),
            }
        return payload, 200

    except UserNotFoundError:
        logger.warning(f"User {user_id} not found during approval")
        return _err('User not found.', 404)

    except LockAcquisitionError:
        # Usually a double-submit. If the other request already approved them,
        # answer success so the client doesn't show an error for a done action.
        db.session.rollback()
        existing = db.session.query(User).filter_by(id=user_id).first()
        if existing and existing.approval_status == 'approved':
            logger.info(f"User {user_id} already approved by a concurrent request")
            return {
                'success': True,
                'message': f'User {existing.username} approved for '
                           f'{existing.approval_league or "league"}',
                'user_id': existing.id,
                'league_type': existing.approval_league,
                'approved_at': (existing.approved_at.isoformat()
                                if existing.approved_at else None),
                'idempotent': True,
            }, 200
        logger.warning(f"Lock acquisition failed for user {user_id} during approval")
        return _err('User is currently being modified by another request. '
                    'Please try again.', 409)

    except Exception as e:
        logger.error(f"Error approving user {user_id}: {e}", exc_info=True)
        return _err('Error processing approval', 500)


def deny_member(user_id, actor_id, actor_username, notes=''):
    """Deny an application: revoke approval and strip the Discord footprint."""
    from app.models import User, Role
    from app.utils.user_locking import (
        lock_user_for_role_update, LockAcquisitionError, UserNotFoundError)
    from app.utils.deferred_discord import defer_discord_removal
    from app.services.league_membership_sync import resync_player_memberships

    notes = _text(notes) or ''

    try:
        with lock_user_for_role_update(user_id, session=db.session) as user:
            if user.approval_status != 'pending':
                return _err('User is not pending approval')

            unverified_role = db.session.query(Role).filter_by(name='pl-unverified').first()
            if unverified_role and unverified_role in user.roles:
                user.roles.remove(unverified_role)

            # approval_status and is_approved move together: denied => not approved.
            # Denial used to leave is_approved alone, so a denied Discord signup
            # (created approved) could still log in and use the app.
            user.approval_status = 'denied'
            user.is_approved = False
            user.approval_league = None
            user.approved_by = actor_id
            user.approved_at = datetime.utcnow()
            user.approval_notes = notes

            db.session.add(user)
            db.session.flush()

            # Phase-0 dual-write: retire their current-season spine rows.
            if user.player:
                resync_player_memberships(db.session, user.player.id)

            if user.player and user.player.discord_id:
                defer_discord_removal(user.player.id)
                logger.info(f"Queued Discord role removal for denied user {user.id}")

            _audit(action='deny_user', resource_type='user_approval',
                   resource_id=user_id, actor_id=actor_id,
                   old_value='pending', new_value='denied')

            logger.info(f"User {user.id} denied by {actor_id}")

            payload = {
                'success': True,
                'message': f'User {user.username} application denied',
                'user_id': user.id,
                'denied_by': actor_username,
                'denied_at': user.approved_at.isoformat(),
                'discord_sync_queued': _discord_queued(user.player),
            }
        return payload, 200

    except UserNotFoundError:
        logger.warning(f"User {user_id} not found during denial")
        return _err('User not found.', 404)

    except LockAcquisitionError:
        db.session.rollback()
        existing = db.session.query(User).filter_by(id=user_id).first()
        if existing and existing.approval_status == 'denied':
            logger.info(f"User {user_id} already denied by a concurrent request")
            return {
                'success': True,
                'message': f'User {existing.username} application denied',
                'user_id': existing.id,
                'denied_at': (existing.approved_at.isoformat()
                              if existing.approved_at else None),
                'idempotent': True,
            }, 200
        logger.warning(f"Lock acquisition failed for user {user_id} during denial")
        return _err('User is currently being modified by another request. '
                    'Please try again.', 409)

    except Exception as e:
        logger.error(f"Error denying user {user_id}: {e}", exc_info=True)
        return _err('Error processing denial', 500)


def undeny_member(user_id, actor_id, actor_username, notes=''):
    """Reverse a denial: put a denied person back in the pending queue.

    Restores the pre-decision state (pending + pl-unverified) rather than
    approving anyone — the admin still has to make the real call. The denial
    reason is kept in approval_notes so the history isn't lost.
    """
    from app.models import User, Role
    from app.utils.user_locking import (
        lock_user_for_role_update, LockAcquisitionError, UserNotFoundError)
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import resync_player_memberships

    try:
        with lock_user_for_role_update(user_id, session=db.session) as user:
            if user.approval_status != 'denied':
                return _err(f'User is not denied (status: {user.approval_status or "unknown"})')

            notes = _text(notes) or ''

            # Restore pl-unverified — only if they hold no league/sub/waitlist
            # role, so we never stack "awaiting a decision" on top of a decision.
            from app.services import program_registry as _pr_reg
            _decided = (set(_pr_reg.league_role_names())
                        | set(_pr_reg.sub_role_names()) | {'pl-waitlist'})
            if not any(r.name in _decided for r in (user.roles or [])):
                unverified_role = db.session.query(Role).filter_by(name='pl-unverified').first()
                if unverified_role and unverified_role not in user.roles:
                    user.roles.append(unverified_role)

            # is_approved stays False: undoing a denial is not an approval.
            # The BULK deny path doesn't clear approval_league, so record what
            # they were carrying before nulling it.
            _prior_league = user.approval_league
            user.approval_status = 'pending'
            user.is_approved = False
            user.approval_league = None
            user.approved_by = None
            user.approved_at = None

            _stamp = (f"[Denial reversed by {actor_username} on "
                      f"{datetime.utcnow().strftime('%Y-%m-%d')}"
                      + (f"; was on record for {_prior_league}" if _prior_league else "")
                      + "]")
            if notes:
                _stamp = f"{_stamp} {notes}"
            user.approval_notes = (f"{user.approval_notes}\n{_stamp}"
                                   if user.approval_notes else _stamp)

            db.session.add(user)
            db.session.flush()

            if user.player:
                resync_player_memberships(db.session, user.player.id)

            # only_add=True so this never strips anything an admin granted by
            # hand while they were denied.
            if user.player and user.player.discord_id:
                defer_discord_sync(user.player.id, only_add=True)
                logger.info(f"Queued Discord role sync for reinstated user {user.id}")

            _audit(action='undeny_user', resource_type='user_approval',
                   resource_id=user_id, actor_id=actor_id,
                   old_value='denied', new_value='pending')

            logger.info(f"User {user.id} denial reversed by {actor_id}")

            payload = {
                'success': True,
                'message': f'{user.username} is back in the pending queue',
                'user_id': user.id,
                'approval_status': 'pending',
                'reinstated_by': actor_username,
                'discord_sync_queued': _discord_queued(user.player),
            }
        return payload, 200

    except UserNotFoundError:
        logger.warning(f"User {user_id} not found during undeny")
        return _err('User not found.', 404)

    except LockAcquisitionError:
        db.session.rollback()
        existing = db.session.query(User).filter_by(id=user_id).first()
        if existing and existing.approval_status == 'pending':
            logger.info(f"User {user_id} already reinstated by a concurrent request")
            return {
                'success': True,
                'message': f'{existing.username} is back in the pending queue',
                'user_id': existing.id,
                'approval_status': 'pending',
                'idempotent': True,
            }, 200
        logger.warning(f"Lock acquisition failed for user {user_id} during undeny")
        return _err('User is currently being modified by another request. '
                    'Please try again.', 409)

    except Exception as e:
        logger.error(f"Error reversing denial for user {user_id}: {e}", exc_info=True)
        return _err('Error reversing denial', 500)


# ---------------------------------------------------------------------------
# 1.2 account activation
# ---------------------------------------------------------------------------

def set_member_activation(user_id, active, actor_id, reason=None):
    """Enable/disable the account and the player's this-season active flag.

    Activating also clears the draft cache so the player shows up in the draft
    pool immediately instead of after the next TTL.
    """
    from app.utils.user_locking import (
        lock_user_for_role_update, LockAcquisitionError, UserNotFoundError)
    from app.utils.deferred_discord import defer_discord_sync, defer_discord_removal
    from app.utils.deferred_cache import defer_clear_league_cache

    active = bool(active)
    try:
        league_name_for_cache = None
        with lock_user_for_role_update(user_id, session=db.session) as user:
            old_status = user.is_active
            user.is_active = active

            if user.player:
                user.player.is_current_player = active
                if active and user.player.primary_league:
                    league_name_for_cache = user.player.primary_league.name

            if user.player and user.player.discord_id:
                if active:
                    defer_discord_sync(user.player.id, only_add=False)
                    logger.info(f"Queued Discord role sync for activated user {user.id}")
                else:
                    defer_discord_removal(user.player.id)
                    logger.info(f"Queued Discord role removal for deactivated user {user.id}")

            # Reason is mobile-only (the web quick-toggle sends none), so the
            # audit value stays exactly 'True'/'False' for existing rows.
            new_value = str(active)
            _reason = _text(reason)
            if _reason:
                new_value = f'{new_value}: {_reason}'
            _audit(action=('activate_user_quick' if active else 'deactivate_user_quick'),
                   resource_type='user_management', resource_id=user_id, actor_id=actor_id,
                   old_value=str(old_status), new_value=new_value)

            username = user.username
            discord_queued = _discord_queued(user.player)

            # Deferred so Redis I/O doesn't extend the user row lock.
            if league_name_for_cache:
                defer_clear_league_cache(league_name_for_cache.lower())

        verb = 'activated' if active else 'deactivated'
        return _ok(f'User {username} {verb} successfully',
                   user_id=user_id, is_active=active,
                   discord_sync_queued=discord_queued)

    except UserNotFoundError:
        # lock_user_for_role_update raises this for an unknown id (its own
        # docstring wrongly says LockAcquisitionError, which is why the web
        # handler this was extracted from 500'd here). Every sibling route
        # answers 404, so a client can tell "stale id" from "server broken".
        logger.warning(f"User {user_id} not found during activation change")
        return _err('User not found.', 404)

    except LockAcquisitionError:
        db.session.rollback()
        return _err('User is currently being modified by another request. '
                    'Please try again.', 409)


# ---------------------------------------------------------------------------
# 1.3 team placement
# ---------------------------------------------------------------------------

def place_member(user_id, action, team_id, actor_id, is_coach=False):
    """TARGETED team placement: add to a team, remove, or set primary.

    Deliberately touches ONLY the roster (player_teams + PlayerTeamSeason +
    primary_team_id), then dual-writes the spine and syncs Discord. It never
    overwrites any other user/player field — unlike the comprehensive edit form,
    which is why that path must NOT be reused here.
    """
    from app.models import Team, PlayerTeamSeason, player_teams
    from sqlalchemy import update as _sa_update
    from app.utils.user_locking import (
        lock_user_for_role_update, LockAcquisitionError, UserNotFoundError)
    from app.utils.deferred_discord import defer_discord_sync, defer_discord_revoke
    from app.services.league_membership_sync import resync_player_memberships
    from app.services.player_division_service import align_player_to_drafted_division

    # _text returns None for a list/dict, which then fails this check as a clean
    # 400 rather than defaulting to 'add' -- a malformed action must never pick
    # a mutation for the caller.
    action = _text(action, default='add')
    is_coach = bool(is_coach)

    if action not in ('add', 'remove', 'primary'):
        return _err('Invalid action')
    try:
        team_id = int(team_id)
    except (TypeError, ValueError):
        return _err('A valid team_id is required')

    try:
        with lock_user_for_role_update(user_id, session=db.session) as user:
            if not user.player:
                return _err('User has no player record')
            player = user.player
            team = db.session.get(Team, team_id)
            if not team:
                return _err('Team not found', 404)
            season_id = team.league.season_id if team.league else None
            discord_queued = _discord_queued(player)

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
                    # Revoke exactly what they are no longer entitled to. The roster
                    # rows are already gone, so the shared calculator sees the
                    # post-removal truth: this team's -Player/-Coach roles come off,
                    # a division coach role only if they coach no other team in it.
                    # Candidates come from the REGISTRY — hardcoded to the original
                    # three, a newer program's coach kept their coach role forever.
                    _coach_candidates = []
                    try:
                        from app.services import program_registry
                        _coach_candidates = [
                            p.coach_role_name
                            for p in program_registry.all_programs(db.session)
                            if p.coach_role_name
                        ]
                    except Exception as _reg_err:
                        logger.warning(f"program registry unavailable for coach revoke "
                                       f"candidates ({_reg_err}); using the legacy three")
                    if not _coach_candidates:
                        _coach_candidates = ['ECS-FC-PL-PREMIER-COACH',
                                             'ECS-FC-PL-CLASSIC-COACH',
                                             'ECS-FC-PL-ECS-FC-COACH']
                    defer_discord_revoke(player.id, team_ids=[team.id],
                                         candidate_roles=_coach_candidates)
                message = f'{player.name} removed from {team.name}'

            elif action == 'primary':
                if player not in team.players:
                    return _err(f'{player.name} is not on {team.name} — place them there first.')
                player.primary_team_id = team.id
                if team.league:
                    player.primary_league_id = team.league_id
                # Keep the league association + pl-<division> Flask role in step
                # with the new primary so the division Discord role follows.
                try:
                    align_player_to_drafted_division(db.session, player.id, team)
                except Exception as _div_err:
                    logger.warning(f"Division alignment skipped for player {player.id}: {_div_err}")
                db.session.flush()
                resync_player_memberships(db.session, player.id)
                if player.discord_id:
                    defer_discord_sync(player.id, only_add=True)
                message = f'{team.name} set as {player.name}\'s primary team'

            else:  # add
                # Block double-rostering in the same non-ECS-FC league (mirrors the
                # draft guard; ECS FC intentionally allows multiple teams).
                is_ecs = 'ecs' in ((team.league.name if team.league else '') or '').lower()
                if not is_ecs:
                    dupe = next((t for t in player.teams
                                 if t.league_id == team.league_id and t.id != team.id), None)
                    if dupe:
                        return _err(f'{player.name} is already on {dupe.name} in this league '
                                    f'— remove them there first.')
                if player not in team.players:
                    team.players.append(player)
                # Set primary only if they have none — don't hijack an existing one.
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
                            player_id=player.id, team_id=team.id,
                            season_id=season_id, is_coach=is_coach))
                # Give them the drafted division's league association + pl-<division>
                # role (mirrors the draft path). Without it, placing a player on a
                # Premier team wrote the roster row and the TEAM role but never
                # ECS-FC-PL-PREMIER. Purely additive. No-op for ECS FC.
                try:
                    align_player_to_drafted_division(db.session, player.id, team)
                except Exception as _div_err:
                    logger.warning(f"Division alignment skipped for player {player.id}: {_div_err}")
                # A rostered player must not keep a conflicting sub role/pool in the
                # same division family, or the stale sub role fights their team role.
                sub_cleanup = None
                try:
                    from app.services.sub_status_service import remove_conflicting_sub_status
                    sub_cleanup = remove_conflicting_sub_status(
                        db.session, player.id,
                        performed_by_user_id=actor_id,
                        league_name=(team.league.name if team and team.league else None))
                except Exception as _sub_err:
                    logger.warning(f"sub-status cleanup skipped for player {player.id}: {_sub_err}")
                # A rostered player is IN — clear any stale waitlist so nobody is
                # left waiting for a spot they already have.
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
                    # Additive grant — placement never strips a role. The exception
                    # is a sub role we just revoked: leaving it would orphan the
                    # -SUB role, and -SUB is the one thing the reconcile allowlist
                    # permits stripping, so flip to a full reconcile for that case.
                    from app.services.sub_status_service import sub_status_removed
                    defer_discord_sync(player.id,
                                       only_add=not sub_status_removed(sub_cleanup))
                message = f'{player.name} placed on {team.name}{" as coach" if is_coach else ""}'

            _audit(action=f'member_place_{action}', resource_type='player_team',
                   resource_id=user_id, actor_id=actor_id,
                   new_value=f'{action}:team={team_id}:coach={is_coach}')

        return _ok(message, user_id=user_id, team_id=team_id, action=action,
                   is_coach=is_coach, discord_sync_queued=discord_queued)

    except LockAcquisitionError:
        return _err('User is being modified by another request. Try again.', 409)
    except UserNotFoundError:
        return _err('User not found', 404)
    except Exception as e:
        logger.error(f"member_place error for user {user_id}: {e}", exc_info=True)
        return _err('Failed to update team placement', 500)


# ---------------------------------------------------------------------------
# 1.4 substitute pool admin
# ---------------------------------------------------------------------------

def sub_assign(user_id, league_type, actor_id, active=True):
    """Add someone to a substitute pool for one lane, optionally resting.

    Writes the right pool table(s) — ECS FC lives in BOTH EcsFcSubPool and a
    SubstitutePool('ECS FC') twin, and the spine reads the twin FIRST — then
    reconciles the sub roles to actual membership. Subs never pay.
    """
    from app.models import User, League, Season
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import resync_player_memberships
    from app.admin_panel.routes.user_management.member_hub import (
        _pool_row_for_lane, _reconcile_sub_roles)

    lane, canonical = resolve_sub_lane(league_type)
    if lane is None:
        return _err('Invalid league', valid=sub_lane_options())

    make_active = bool(active)
    user = db.session.get(User, user_id)
    if not user or not user.player:
        return _err('This person has no player record')
    player = user.player
    now = datetime.utcnow()

    if lane == 'ecs_fc':
        ep = db.session.query(EcsFcSubPool).filter_by(player_id=player.id).first()
        if ep:
            ep.is_active = make_active
        else:
            db.session.add(EcsFcSubPool(player_id=player.id, is_active=make_active))
        # Keep the approval-created SubstitutePool('ECS FC') twin in sync — never
        # create or clobber a Pub row here.
        sp = _pool_row_for_lane(db.session, player.id, 'ecs_fc')
        if sp:
            sp.is_active = make_active
            sp.approved_at = sp.approved_at or now
            sp.approved_by = sp.approved_by or actor_id
    else:
        # Look up THIS lane's row. Filtering on player_id alone returns an
        # arbitrary row once someone subs for two programs, and rewriting its
        # league_type silently drops them from the other program's broadcast list.
        sp = _pool_row_for_lane(db.session, player.id, lane)
        if sp:
            sp.is_active = make_active
            sp.approved_at = sp.approved_at or now
            sp.approved_by = sp.approved_by or actor_id
        else:
            db.session.add(SubstitutePool(
                player_id=player.id, league_type=canonical, is_active=make_active,
                approved_at=now, approved_by=actor_id))

    db.session.flush()
    _reconcile_sub_roles(db.session, user, player)

    # Ensure they have a league so dispatch + Discord roles resolve (best-effort).
    if not player.league_id and not player.primary_league_id:
        s_type = 'ECS FC' if lane == 'ecs_fc' else 'Pub League'
        lg = (db.session.query(League).join(Season)
              .filter(Season.league_type == s_type, Season.is_current == True).first())
        if lg:
            player.league_id = lg.id
            player.primary_league_id = lg.id

    db.session.flush()
    resync_player_memberships(db.session, player.id)
    if player.discord_id:
        # Full allowlist-protected reconcile: get_expected_roles now includes the
        # -SUB role we reconciled, while team/division/coach roles are protected.
        defer_discord_sync(player.id, only_add=True)

    _audit(action='member_sub_assign', resource_type='substitute_pool',
           resource_id=user_id, actor_id=actor_id,
           new_value=f'{canonical}:{"active" if make_active else "resting"}')

    return _ok(f'Added to {canonical} subs ({"active" if make_active else "resting"})',
               user_id=user_id, lane=lane, league_type=canonical, active=make_active,
               discord_sync_queued=_discord_queued(player))


def sub_set_active(user_id, league_type, actor_id, active=True):
    """Rest/wake a sub for one lane, in BOTH pool tables where they apply."""
    from app.models import User
    from app.models.substitutes import EcsFcSubPool
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import resync_player_memberships
    from app.admin_panel.routes.user_management.member_hub import _pool_row_for_lane

    lane, canonical = resolve_sub_lane(league_type)
    if lane is None:
        return _err('Invalid league', valid=sub_lane_options())

    make_active = bool(active)
    user = db.session.get(User, user_id)
    if not user or not user.player:
        return _err('No player record')
    pid = user.player.id

    touched = False
    sp = _pool_row_for_lane(db.session, pid, lane)
    if sp:
        sp.is_active = make_active
        touched = True
    if lane == 'ecs_fc':
        ep = db.session.query(EcsFcSubPool).filter_by(player_id=pid).first()
        if ep:
            ep.is_active = make_active
            touched = True
    if not touched:
        return _err(f'Not in the {canonical} sub pool', 404)

    db.session.flush()
    resync_player_memberships(db.session, pid)
    if user.player.discord_id:
        defer_discord_sync(pid, only_add=True)

    _audit(action='member_sub_set_active', resource_type='substitute_pool',
           resource_id=user_id, actor_id=actor_id,
           new_value=f'{canonical}:{"active" if make_active else "resting"}')

    return _ok(('Woken' if make_active else 'Resting') + f' · {canonical}',
               user_id=user_id, lane=lane, league_type=canonical, active=make_active,
               discord_sync_queued=_discord_queued(user.player))


def sub_remove(user_id, league_type, actor_id):
    """Remove a sub from one lane, both pool tables, then reconcile roles."""
    from app.models import User
    from app.models.substitutes import EcsFcSubPool
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import resync_player_memberships
    from app.admin_panel.routes.user_management.member_hub import (
        _pool_row_for_lane, _delete_pool_row, _reconcile_sub_roles)

    lane, canonical = resolve_sub_lane(league_type)
    if lane is None:
        return _err('Invalid league', valid=sub_lane_options())

    user = db.session.get(User, user_id)
    if not user or not user.player:
        return _err('No player record')
    pid = user.player.id

    sp = _pool_row_for_lane(db.session, pid, lane)
    if sp:
        _delete_pool_row(db.session, sp)
    if lane == 'ecs_fc':
        ep = db.session.query(EcsFcSubPool).filter_by(player_id=pid).first()
        if ep:
            db.session.delete(ep)
    db.session.flush()
    _reconcile_sub_roles(db.session, user, player=user.player)
    db.session.flush()
    resync_player_memberships(db.session, pid)
    if user.player.discord_id:
        # Full reconcile: the removed lane's -SUB role is no longer expected and
        # the allowlist permits stripping it; team/division/coach roles are safe.
        defer_discord_sync(pid, only_add=False)

    _audit(action='member_sub_remove', resource_type='substitute_pool',
           resource_id=user_id, actor_id=actor_id, new_value=canonical)

    return _ok(f'Removed from {canonical} subs',
               user_id=user_id, lane=lane, league_type=canonical,
               discord_sync_queued=_discord_queued(user.player))


def sub_reject(user_id, league_type, actor_id):
    """Reject a PENDING sub-pool self-signup (``approved_at IS NULL``) for one lane.

    The legacy reject_player_from_pool endpoint targets a different flow
    (pre-rejecting someone NOT yet in the pool) and 400s on an existing pending
    row. An empty league_type rejects every pending signup the person has.

    Lane matching is NORMALIZED rather than an equality test on the stored
    league_type: the sibling endpoints all normalize, and a row stored as
    'pub_league_classic' would never match a literal 'Classic'.
    """
    from app.models import User
    from app.models.substitutes import SubstitutePool
    from app.utils.deferred_discord import defer_discord_sync
    from app.services.league_membership_sync import (
        resync_player_memberships, _norm_league_type)
    from app.admin_panel.routes.user_management.member_hub import (
        _delete_pool_row, _reconcile_sub_roles)

    lane, canonical = (None, None)
    if league_type:
        lane, canonical = resolve_sub_lane(league_type)
        if lane is None:
            return _err('Invalid league', valid=sub_lane_options())

    user = db.session.get(User, user_id)
    if not user or not user.player:
        return _err('User has no player record')
    pid = user.player.id

    rows = db.session.query(SubstitutePool).filter(
        SubstitutePool.player_id == pid,
        SubstitutePool.approved_at.is_(None)).all()
    if lane:
        # EXACT stored match first. _norm_league_type is substring-tolerant, so
        # rejecting 'Premier' would also delete a 'Premier Reserve' row belonging
        # to a program the registry cannot resolve — one lane's reject must never
        # take another program's signup with it. The normalized pass is the
        # fallback, and it is what makes a DRIFTED value ('pub_league_classic')
        # rejectable at all; the exact pass just stops it from over-reaching
        # whenever a canonically-named row exists.
        target = (canonical or '').strip().lower()
        exact = [r for r in rows if (r.league_type or '').strip().lower() == target]
        rows = exact or [r for r in rows if _norm_league_type(r.league_type) == lane]
    if not rows:
        return _err('No pending sub signup to reject', 404)

    for r in rows:
        _delete_pool_row(db.session, r)

    db.session.flush()
    # RECONCILE, don't strip. The old line removed this lane's sub role
    # unconditionally, without re-checking what pool membership survived — so a
    # player holding BOTH an approved row and a pending one for the same lane
    # (reachable without hand-editing: /substitutes/pool/join stores league_type
    # verbatim and matches by exact string, so 'classic' and 'Classic' coexist)
    # lost the role for their APPROVED membership to a "pending-only" reject,
    # and the queued reconcile then stripped the Discord -SUB role too. The two
    # sibling endpoints already reconcile; this one now matches them, which also
    # keeps player.is_sub honest.
    _reconcile_sub_roles(db.session, user, user.player)

    db.session.flush()
    resync_player_memberships(db.session, pid)
    if user.player.discord_id:
        defer_discord_sync(pid, only_add=False)  # allowlist permits the -SUB strip

    _audit(action='member_sub_reject', resource_type='substitute_pool',
           resource_id=user_id, actor_id=actor_id,
           new_value=canonical or 'all-pending')

    return _ok(f'Rejected the pending {canonical or "sub"} signup',
               user_id=user_id, lane=lane, league_type=canonical,
               rejected=len(rows), discord_sync_queued=_discord_queued(user.player))


# ---------------------------------------------------------------------------
# 1.5 waitlist
# ---------------------------------------------------------------------------

def remove_member_from_waitlist(user_id, actor_id, actor_username, reason='No reason provided'):
    """Take someone off the waitlist and land them back as an ordinary pending user."""
    from app.models import Role
    from app.utils.user_locking import (
        lock_user_for_role_update, LockAcquisitionError, UserNotFoundError)
    from app.utils.deferred_discord import defer_discord_sync

    reason = _text(reason) or 'No reason provided'
    try:
        with lock_user_for_role_update(user_id, session=db.session) as user:
            waitlist_role = db.session.query(Role).filter_by(name='pl-waitlist').first()
            if not waitlist_role:
                return _err('Waitlist role not found', 404)
            if waitlist_role not in user.roles:
                return _err('User is not on waitlist')

            user.roles.remove(waitlist_role)

            # Restore pl-unverified for anyone not already approved, so a removed
            # waitlister lands back as a pending user rather than role-less.
            # Approved returning players keep their real roles.
            if not user.is_approved and user.approval_status != 'approved':
                unverified_role = db.session.query(Role).filter_by(name='pl-unverified').first()
                if unverified_role and unverified_role not in user.roles:
                    user.roles.append(unverified_role)

            if hasattr(user, 'waitlist_joined_at'):
                user.waitlist_joined_at = None
            if hasattr(user, 'waitlist_league'):
                user.waitlist_league = None
            user.updated_at = datetime.utcnow()

            if user.player:
                try:
                    from app.services.league_membership_sync import resync_player_memberships
                    resync_player_memberships(db.session, user.player.id)
                except Exception as _lm_err:
                    logger.warning(f"league_membership sync skipped for user {user.id}: {_lm_err}")

            _audit(action='remove_from_waitlist', resource_type='user_waitlist',
                   resource_id=user_id, actor_id=actor_id,
                   old_value='on_waitlist', new_value=f'removed: {reason}')

            logger.info(f"User {user.id} ({user.username}) removed from waitlist by "
                        f"{actor_id} ({actor_username}). Reason: {reason}")

            db.session.flush()

            # RECONCILE, never blanket-remove. pl-waitlist is Flask-only, so coming
            # off the waitlist should cost nothing on Discord — a full removal here
            # used to strip every team/division/sub/referee role a rostered player had.
            if user.player and user.player.discord_id:
                defer_discord_sync(user.player.id, only_add=False)
                logger.info(f"Queued Discord role reconcile for user {user.id}")

            username = user.username
            discord_queued = _discord_queued(user.player)

        return _ok(f'User {username} removed from waitlist successfully',
                   user_id=user_id, discord_sync_queued=discord_queued)

    except UserNotFoundError:
        logger.warning(f"User {user_id} not found during waitlist removal")
        return _err('User not found.', 404)
    except LockAcquisitionError:
        logger.warning(f"Lock acquisition failed for user {user_id} during waitlist removal")
        return _err('User is currently being modified by another request. '
                    'Please try again.', 409)
    except Exception as e:
        logger.error(f"Error removing user {user_id} from waitlist: {e}", exc_info=True)
        return _err('Failed to remove user from waitlist', 500)


def set_waitlist_priority(user_id, priority, actor_id, actor_username):
    """Set the manual waitlist priority. 'auto' stores NULL (join-time ordering)."""
    from app.models import User

    try:
        user = db.session.query(User).filter_by(id=user_id).first()
        if not user:
            return _err('User not found', 404)

        # Validate the RAW value. Coercing a falsy priority to 'auto' here would
        # silently accept {"priority": ""} / null / 0 and clear a manual
        # priority the admin never meant to touch; the web handler 400s on those
        # and only an ABSENT key defaults to 'auto' (the caller supplies that).
        if priority not in WAITLIST_PRIORITIES:
            return _err(
                f'Invalid priority. Must be one of: {", ".join(WAITLIST_PRIORITIES)}',
                valid_priorities=list(WAITLIST_PRIORITIES))

        old_priority = user.waitlist_priority
        user.waitlist_priority = None if priority == 'auto' else priority
        user.updated_at = datetime.utcnow()

        _audit(action='update_waitlist_priority', resource_type='user_waitlist',
               resource_id=user_id, actor_id=actor_id,
               old_value=old_priority or 'auto', new_value=priority)

        logger.info(f"Waitlist priority updated for user {user.id} ({user.username}) "
                    f"from {old_priority or 'auto'} to {priority} by "
                    f"{actor_id} ({actor_username})")

        return _ok(f'Priority updated to {priority}',
                   user_id=user.id, priority=priority)

    except Exception as e:
        logger.error(f"Error updating waitlist priority for user {user_id}: {e}", exc_info=True)
        return _err('Failed to update priority', 500)


# ---------------------------------------------------------------------------
# 1.6 quick-profile pre-approval
# ---------------------------------------------------------------------------

def preapprove_quick_profile(profile_id, league_type, actor_id):
    """Pre-approve (or clear) a quick profile.

    A pre-approved profile auto-approves into the chosen league the moment the
    person claims their code (QuickProfile._apply_pre_approval). A waitlist-*
    value is applied phase-aware on claim: waitlist if open, else the plain
    league. An empty league_type clears the pre-approval.
    """
    from app.models import QuickProfile
    from app.admin_panel.routes.user_management.member_hub import _preapproval_values

    profile = db.session.get(QuickProfile, profile_id)
    if not profile:
        return _err('Quick profile not found', 404)

    league = _text(league_type)
    valid = _preapproval_values()
    if league is None:
        # '' legitimately CLEARS the pre-approval, so a non-scalar must not be
        # allowed to collapse into it and silently wipe one.
        return _err('Invalid league_type', valid_league_types=sorted(valid))
    if league and league not in valid:
        # Name the value AND what was allowed: "Invalid league" alone is
        # unactionable, and this rejecting a program the picker offered is the
        # bug worth seeing.
        logger.warning("QP pre-approval rejected league_type=%r (valid: %s)",
                       league, sorted(valid))
        return _err(f'Invalid league "{league}" — not a known program.',
                    valid_league_types=sorted(valid))

    if league:
        profile.pre_approved_league = league
        profile.pre_approved_by_user_id = actor_id
        profile.pre_approved_at = datetime.utcnow()
        msg = f'Pre-approved into {league} — auto-approves when they claim'
    else:
        profile.pre_approved_league = None
        profile.pre_approved_by_user_id = None
        profile.pre_approved_at = None
        msg = 'Pre-approval cleared'

    _audit(action='quick_profile_preapprove', resource_type='quick_profile',
           resource_id=profile_id, actor_id=actor_id,
           new_value=league or 'cleared')

    return _ok(msg, profile_id=profile_id,
               pre_approved_league=profile.pre_approved_league)


# ---------------------------------------------------------------------------
# 1.7 worklist (read)
# ---------------------------------------------------------------------------

def _serialize_member(user, sub_summary=None):
    """One worklist row. Deliberately no email — it is PII-encrypted at rest."""
    from app.services.league_membership_sync import _norm_league_type

    player = user.player
    lanes = []
    if player and sub_summary:
        for row in sub_summary.get(player.id, []):
            lanes.append({
                'lane': _norm_league_type(row['lane']) or row['lane'],
                'label': row['lane'],
                'status': row['status'],
            })

    teams = []
    primary_team = None
    teams_ok = True
    if player:
        try:
            teams = [{'id': t.id, 'name': t.name} for t in (player.teams or [])]
            if player.primary_team:
                primary_team = {'id': player.primary_team.id,
                                'name': player.primary_team.name}
        except Exception:
            # A worklist row must never 500 the whole list over one broken
            # relationship — but an empty list would read as "not on a team",
            # which is a different and wrong fact. Say the projection failed.
            teams_ok = False
            logger.warning(f"team projection failed for player {player.id}", exc_info=True)

    # Absolute, like every other image URL the mobile API returns
    # (see MobileAdminService.get_player_roles) — a bare path renders as a
    # broken image in the app, which has no base URL to resolve it against.
    picture = player.profile_picture_url if player else None
    if picture and picture.startswith('/'):
        try:
            from flask import request, has_request_context
            if has_request_context():
                picture = f"{request.host_url.rstrip('/')}{picture}"
        except Exception:
            pass

    return {
        'user_id': user.id,
        'username': user.username,
        'player_id': player.id if player else None,
        'name': (player.name if player else None) or user.username,
        'approval_status': user.approval_status,
        'is_approved': bool(user.is_approved),
        'is_active': bool(user.is_active),
        'approval_league': user.approval_league,
        'preferred_league': getattr(user, 'preferred_league', None),
        'waitlist_league': getattr(user, 'waitlist_league', None),
        'waitlist_priority': getattr(user, 'waitlist_priority', None),
        'waitlist_joined_at': (user.waitlist_joined_at.isoformat()
                               if getattr(user, 'waitlist_joined_at', None) else None),
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'roles': [r.name for r in (user.roles or [])],
        'is_current_player': bool(player.is_current_player) if player else False,
        'has_discord': bool(player.discord_id) if player else False,
        'profile_picture_url': picture,
        'primary_team': primary_team,
        'teams': teams,
        # False means "we could not read the roster", NOT "they have no teams".
        'teams_ok': teams_ok,
        'sub_lanes': lanes,
    }


def build_member_worklist(session, args, page=1, per_page=WORKLIST_PER_PAGE_DEFAULT):
    """The Members worklist as JSON — the same criteria as the web page.

    Reuses ``_all_tab_query`` / ``_sub_player_ids`` / ``_subs_list`` from the web
    module rather than re-deriving them, so a spreadsheet, a screen and a phone
    can never show a different set of people. That includes the default that
    HIDES denied users; ``hidden_denied`` reports how many the default is
    swallowing, because silently hiding them once made denied members look
    nonexistent to a searching admin.

    ``args`` is any mapping with ``.get`` (``request.args`` or a plain dict).
    """
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload
    from app.models import User, Role, Player, QuickProfile
    from app.models.quick_profile import QuickProfileStatus
    from app.admin_panel.routes.user_management.member_hub import (
        _all_tab_filters, _all_tab_query, _sub_player_ids, _subs_list)

    tab = (args.get('tab') or 'all').strip()
    # The web page calls the quick-profile tab 'quick'; the mobile spec asked for
    # 'quick_profiles'. Accept both rather than making one side wrong.
    if tab == 'quick_profiles':
        tab = 'quick'
    if tab not in ('all', 'pending', 'waitlist', 'subs', 'quick'):
        tab = 'all'

    search = (args.get('search') or '').strip()
    approval_filter = (args.get('approval') or '').strip()
    lane_filter = (args.get('lane') or '').strip()
    sub_status_filter = (args.get('sub_status') or '').strip()
    qp_status = (args.get('qp_status') or 'pending').strip()

    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(per_page or WORKLIST_PER_PAGE_DEFAULT)
    except (TypeError, ValueError):
        per_page = WORKLIST_PER_PAGE_DEFAULT
    per_page = max(1, min(per_page, WORKLIST_PER_PAGE_CAP))

    now = datetime.utcnow()
    not_denied = or_(User.approval_status != 'denied', User.approval_status.is_(None))

    pending_q = session.query(User).filter(*User.pending_approval_criteria())
    waitlist_q = (session.query(User).join(User.roles)
                  .filter(Role.name == 'pl-waitlist', not_denied))
    quick_pending_q = session.query(QuickProfile).filter(
        QuickProfile.status == QuickProfileStatus.PENDING.value,
        or_(QuickProfile.expires_at.is_(None), QuickProfile.expires_at > now),
    )
    sub_pids = _sub_player_ids(session)

    counts = {
        'all': session.query(User).count(),
        'pending': pending_q.count(),
        'waitlist': waitlist_q.count(),
        'subs': len(sub_pids),
        'quick_profiles': quick_pending_q.count(),
    }

    items, total, hidden_denied = [], 0, 0
    sub_summary = {}

    # Eager-load what _serialize_member touches. Without this a 100-row page
    # fires ~200 extra SELECTs for teams + primary_team INSIDE the open
    # transaction — and transaction HOLD TIME is the scarce resource here, not
    # query count (22 PgBouncer slots, 1 vCPU).
    _member_loads = (
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.teams),
        joinedload(User.player).joinedload(Player.primary_team),
    )

    if tab == 'waitlist':
        # Waitlist and approval are independent axes, so the list is built fresh
        # rather than off waitlist_q: denied-but-waitlisted people are hidden by
        # default but reachable with approval=denied / approval=all.
        def _waitlist_query(approval):
            q = (session.query(User).join(User.roles)
                 .filter(Role.name == 'pl-waitlist')
                 .options(*_member_loads))
            if approval == 'denied':
                q = q.filter(User.approval_status == 'denied')
            elif approval != 'all':
                q = q.filter(not_denied)
            if search:
                like = f'%{search}%'
                q = q.outerjoin(Player, Player.user_id == User.id).filter(
                    or_(Player.name.ilike(like), User.username.ilike(like)))
            if lane_filter == 'undecided':
                q = q.filter(or_(User.waitlist_league.is_(None), User.waitlist_league == '',
                                 User.waitlist_league.ilike('%not_sure%')))
            elif lane_filter:
                clause = lane_clause(User.waitlist_league, lane_filter)
                if clause is not None:
                    q = q.filter(clause)
            return q

        wq = _waitlist_query(approval_filter)
        # waitlist_joined_at is not unique, so it cannot order a paginated list
        # on its own — equal timestamps let a row repeat on page 2 while another
        # never appears at all. id is the tiebreaker.
        wq = wq.order_by(User.waitlist_joined_at.asc().nullslast(), User.id.asc())
        total = wq.count()
        rows = wq.limit(per_page).offset((page - 1) * per_page).all()
        items = [_serialize_member(u) for u in rows]
        # This tab hides denied by default too — say how many, same as All.
        if approval_filter not in ('all', 'denied'):
            hidden_denied = _waitlist_query('denied').count()

    elif tab == 'pending':
        pq = pending_q.options(*_member_loads)
        if search:
            like = f'%{search}%'
            pq = pq.outerjoin(Player, Player.user_id == User.id).filter(
                or_(Player.name.ilike(like), User.username.ilike(like)))
        if lane_filter:
            clauses = [c for c in (lane_clause(User.approval_league, lane_filter),
                                   lane_clause(User.preferred_league, lane_filter))
                       if c is not None]
            if clauses:
                pq = pq.filter(or_(*clauses))
        # created_at is not unique — id breaks the tie so pagination is stable.
        pq = pq.order_by(User.created_at.desc(), User.id.desc())
        total = pq.count()
        rows = pq.limit(per_page).offset((page - 1) * per_page).all()
        items = [_serialize_member(u) for u in rows]

    elif tab == 'subs':
        # Lane/status narrowing is a Python pass because a sub's lanes are merged
        # from two pool tables, not read off one filterable column — so the slice
        # has to happen after the filter, in Python too.
        users, sub_summary = _subs_list(session, sub_pids, search,
                                        lane_filter, sub_status_filter)
        total = len(users)
        start = (page - 1) * per_page
        items = [_serialize_member(u, sub_summary)
                 for u in users[start:start + per_page]]

    elif tab == 'quick':
        pq = session.query(QuickProfile)
        if qp_status and qp_status != 'all':
            pq = pq.filter(QuickProfile.status == qp_status)
        if search:
            pq = pq.filter(QuickProfile.player_name.ilike(f'%{search}%'))
        pq = pq.order_by(QuickProfile.created_at.desc(), QuickProfile.id.desc())
        total = pq.count()
        rows = pq.limit(per_page).offset((page - 1) * per_page).all()
        items = [p.to_dict() for p in rows]

    else:  # all
        filters = _all_tab_filters(args)
        # _all_tab_query is the SHARED criteria (it already orders by username);
        # only the eager loads and the id tiebreaker are added on top, so the
        # web page and this endpoint still select the same people.
        q = _all_tab_query(session, filters).options(*_member_loads).order_by(User.id)
        total = q.count()
        rows = q.limit(per_page).offset((page - 1) * per_page).all()
        items = [_serialize_member(u) for u in rows]
        # Say what the default is hiding. Denied members were UNFINDABLE before:
        # a search returned "no members", which reads as "no such person".
        if filters['approval'] not in ('all', 'denied'):
            hidden_denied = _all_tab_query(session, dict(filters, approval='denied')).count()

    pages = (total + per_page - 1) // per_page if per_page else 0

    return {
        'success': True,
        'tab': 'quick_profiles' if tab == 'quick' else tab,
        'items': items,
        'total': total,
        'page': page,
        'per_page': per_page,
        # Stated, never silent — a capped list that says nothing reads as complete.
        'per_page_cap': WORKLIST_PER_PAGE_CAP,
        'pages': pages,
        'counts': counts,
        'hidden_denied': hidden_denied,
        'filters': {
            'search': search,
            'role': (args.get('role') or '').strip(),
            'league': (args.get('league') or '').strip(),
            'team': (args.get('team') or '').strip(),
            'approval': approval_filter,
            'active': (args.get('active') or '').strip(),
            'season': (args.get('season') or '').strip(),
            'lane': lane_filter,
            'sub_status': sub_status_filter,
            'qp_status': qp_status,
        },
    }, 200


def list_sub_pools(session):
    """Every substitute pool, grouped by lane, with its members.

    The per-person sub screens answer "which pools is THIS person in?"; this
    answers the other direction — "who is in the Classic pool?" — which is the
    question an admin actually has at 7pm on a Thursday.

    ⚠️ NO mutations live here. The app's row actions reuse the existing
    per-person ``/admin/members/{id}/sub-assign|sub-active|sub-remove|sub-reject``
    endpoints, so the pool view and the member hub cannot drift into two
    different ideas of what "remove from pool" means.

    Includes PENDING members (``approved_at IS NULL``), because approving or
    rejecting a self-signup is half the reason to open this screen — unlike
    ``_sub_player_ids``, which deliberately counts only approved rows for the
    worklist badge. Denied users are excluded, matching every other live queue.

    ⚠️ A pool row whose player has no ``user_id`` cannot be actioned at all (the
    sub endpoints key on user id), and the client drops those rows. They are
    still returned, with ``user_id: null`` and counted in ``unlinked``, because
    a member silently missing from a pool list is how someone ends up wondering
    why the pool "lost" them.
    """
    from app.models import User, Player
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.services.league_membership_sync import _norm_league_type

    def _picture(player):
        pic = player.profile_picture_url if player else None
        if pic and pic.startswith('/'):
            try:
                from flask import request, has_request_context
                if has_request_context():
                    pic = f"{request.host_url.rstrip('/')}{pic}"
            except Exception:
                pass
        return pic

    def _member(player, *, is_approved, is_active, approved_at,
                requested_at, last_engaged_at):
        user = player.user if player else None
        return {
            'user_id': user.id if user else None,
            'player_id': player.id if player else None,
            'name': (player.name if player else None) or (user.username if user else None),
            'profile_picture_url': _picture(player),
            'is_approved': bool(is_approved),
            'is_active': bool(is_active),
            'approved_at': approved_at.isoformat() if approved_at else None,
            'requested_at': requested_at.isoformat() if requested_at else None,
            # Pool-level engagement (last_active_at), NOT the spine's
            # LeagueMembership.last_engaged_at — this screen is about the pool.
            'last_engaged_at': last_engaged_at.isoformat() if last_engaged_at else None,
        }

    denied_pids = {pid for (pid,) in session.query(Player.id)
                   .join(User, User.id == Player.user_id)
                   .filter(User.approval_status == 'denied').all()}

    # Eager-load player+user: a 200-row pool would otherwise fire ~400 lazy
    # SELECTs inside the open transaction, and hold time is the scarce resource.
    from sqlalchemy.orm import joinedload

    pools = {}

    # Display label per lane, from the registry — NOT the raw `league_type`
    # string, which is whatever the writing call site happened to store
    # ('classic', 'Classic', 'Pub League Classic' all normalize to one lane and
    # would otherwise each label the same pool differently.)
    labels = {}
    try:
        from app.services import program_registry
        for p in program_registry.all_programs(session):
            if p.membership_lane:
                labels[p.membership_lane] = (p.display_name or p.league_name
                                             or p.membership_lane)
    except Exception:
        logger.warning("sub pool labels fell back to lane names", exc_info=True)

    def _bucket(lane_raw):
        lane = _norm_league_type(lane_raw) or (lane_raw or 'unknown')
        if lane not in pools:
            pools[lane] = {
                'lane': lane,
                'label': labels.get(lane) or (lane_raw or lane),
                'members': [], 'unlinked': 0,
            }
        return pools[lane]

    for row in (session.query(SubstitutePool)
                .options(joinedload(SubstitutePool.player).joinedload(Player.user))
                .all()):
        if row.player_id in denied_pids:
            continue
        bucket = _bucket(row.league_type)
        member = _member(row.player,
                         is_approved=row.approved_at is not None,
                         is_active=row.is_active,
                         approved_at=row.approved_at,
                         requested_at=row.joined_pool_at or row.created_at,
                         last_engaged_at=row.last_active_at)
        bucket['members'].append(member)
        if member['user_id'] is None:
            bucket['unlinked'] += 1

    for row in (session.query(EcsFcSubPool)
                .options(joinedload(EcsFcSubPool.player).joinedload(Player.user))
                .all()):
        if row.player_id in denied_pids:
            continue
        bucket = _bucket('ECS FC')
        # EcsFcSubPool has no approval column — a row IS the approval, which is
        # why _sub_player_ids counts every one of them. Reporting is_approved
        # False here would render the whole ECS FC pool as "pending".
        member = _member(row.player,
                         is_approved=True, is_active=row.is_active,
                         approved_at=row.joined_pool_at,
                         requested_at=row.joined_pool_at,
                         last_engaged_at=row.last_active_at)
        # An ECS FC sub commonly holds BOTH an EcsFcSubPool row and a
        # SubstitutePool('ECS FC') twin; deduping on player keeps them from
        # appearing twice in one pool. Active wins, matching _sub_summary.
        existing = next((m for m in bucket['members']
                         if m['player_id'] == member['player_id']), None)
        if existing is None:
            bucket['members'].append(member)
            if member['user_id'] is None:
                bucket['unlinked'] += 1
        elif member['is_active'] and not existing['is_active']:
            existing.update(member)

    for bucket in pools.values():
        bucket['members'].sort(key=lambda m: (m['name'] or '').lower())

    ordered = sorted(pools.values(), key=lambda p: p['lane'])
    return {
        'success': True,
        'pools': ordered,
        'total_members': sum(len(p['members']) for p in ordered),
    }, 200


def get_member(session, user_id):
    """ONE worklist row, by user id — the same object ``items[]`` carries.

    Built from ``_serialize_member`` rather than a hand-rolled projection, so a
    field added to the list can never go missing from the detail view. Without
    this endpoint the app had to search the worklist by username and match on
    ``user_id``: an extra round-trip, and a matching risk whenever two accounts
    share a display name.

    Deliberately NOT filtered by approval status. This answers "show me this
    person", and the caller already has their id — hiding a denied member here
    would break the very lifecycle sheet that exists to un-deny them (the
    worklist's denied-by-default hiding is a LIST default, not an access rule).
    """
    from app.models import User

    user = session.query(User).get(user_id)
    if user is None:
        # A live handler's 404 must carry a message, or the mobile client's
        # feature-availability probe reads a bodyless 404 as "endpoint not
        # deployed" and hides the whole screen instead of showing the error.
        return _err('Member not found', 404)

    # The sub lanes come from two pool tables merged in the web helper; ask it
    # about this one player rather than re-deriving the merge here.
    sub_summary = {}
    if user.player:
        try:
            from app.admin_panel.routes.user_management.member_hub import _sub_summary
            sub_summary = _sub_summary(session, {user.player.id})
        except Exception:
            logger.warning(f"sub summary skipped for user {user_id}", exc_info=True)

    return {'success': True, 'member': _serialize_member(user, sub_summary)}, 200
