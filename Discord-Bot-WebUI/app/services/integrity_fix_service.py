# app/services/integrity_fix_service.py

"""
Resolution half of the admin integrity system (detection lives in
integrity_service.py). Each detector attaches `fix_actions` to its findings;
the integrity dashboard's Manage modal POSTs the chosen (code, action) to
/admin-panel/integrity/resolve, which dispatches here.

Contract: apply_fix runs INSIDE the route's @transactional block and uses
db.session throughout (mixing g.db_session writes in would silently lose
them). Discord work is queued via the deferred helpers so it dispatches
after commit. Every fixer re-checks its own precondition and returns an
"already consistent" message when the conflict no longer exists, so a stale
dashboard tab can't corrupt state. Raises ValueError for bad input (mapped
to HTTP 400 by the route).
"""

import logging
from datetime import datetime

from app.core import db
from app.utils.deferred_discord import defer_discord_sync, defer_discord_removal

logger = logging.getLogger(__name__)

PUB_DIVISIONS = ('classic', 'premier')          # fallback


def pub_divisions():
    """Lowercased League.name values treated as pub-league divisions.

    G8 (double-rostering) and the division fixers are blind to any program
    outside this tuple, so a newer program's members are neither checked nor
    fixable.

    ⚠️ Returns LOWERCASED LEAGUE NAMES, not membership lanes. Every call site
    compares against `func.lower(League.name)` or a form value derived from it,
    so returning lanes would silently match nothing for any program whose lane
    differs from its league name (e.g. lane 'pl_third' vs league 'Summer
    Sprint') -- the check would quietly pass instead of running.
    """
    try:
        from app.services import program_registry
        names = tuple((p.league_name or '').strip().lower()
                      for p in program_registry.all_programs()
                      if p.is_pub_league_like and p.league_name)
        if names:
            return names
    except Exception:
        pass
    return PUB_DIVISIONS


def _get_user(user_id):
    from app.models.core import User
    user = db.session.query(User).get(user_id) if user_id else None
    if not user:
        raise ValueError('User not found')
    return user


def _get_player(player_id):
    from app.models import Player
    player = db.session.query(Player).get(player_id) if player_id else None
    if not player:
        raise ValueError('Player not found')
    return player


def _get_role(name):
    from app.models import Role
    return db.session.query(Role).filter_by(name=name).first()


def _sync_discord(player, only_add=False):
    if player and player.discord_id:
        defer_discord_sync(player.id, only_add=only_add)


def _current_season_ids():
    from app.models import Season
    return [s for (s,) in db.session.query(Season.id).filter(
        Season.is_current == True).all()]  # noqa: E712


# --------------------------------------------------------------------------
# Fixers — each returns a human message describing what happened.
# --------------------------------------------------------------------------

def _fix_approve(user_id, player_id, params, admin_id):
    """G1/G2/G3: (re-)run the real approval flow for the chosen division.

    Reuses the exact mutation the Approvals page performs (apply_approval), so
    reconciling from the integrity dashboard cannot drift from a real approval:
    role mapping, approval_status/is_approved, current-season league assignment,
    and the deferred Discord sync all come from the one shared code path.
    """
    league_type = (params or {}).get('league_type')
    from app.services.integrity_service import APPROVE_LEAGUE_TYPES
    from app.services.integrity_service import approve_league_types
    if league_type not in approve_league_types():
        raise ValueError('Invalid division')
    if not user_id:
        raise ValueError('User not found')
    from app.utils.user_locking import (lock_user_for_role_update,
                                        LockAcquisitionError, UserNotFoundError)
    from app.admin_panel.routes.user_management.approvals import apply_approval
    try:
        with lock_user_for_role_update(user_id, session=db.session) as user:
            apply_approval(user, league_type, approver_id=admin_id)
            name = user.username
    except UserNotFoundError:
        raise ValueError('User not found')
    except LockAcquisitionError:
        # The failed FOR UPDATE NOWAIT leaves the transaction aborted — roll back
        # so the route's @transactional doesn't try to commit a poisoned session.
        db.session.rollback()
        raise ValueError('User is being modified by another request — try again.')
    label = league_type.replace('sub-', '').title() + (' Sub' if league_type.startswith('sub-') else '')
    return f"{name} approved for {label} and queued for Discord sync."


def _fix_deny_cleanup(user_id, player_id, params, admin_id):
    """G4: denied user still active/rostered — strip roster, league roles, flag."""
    from app.models import PlayerTeamSeason
    from app.models.players import player_teams
    user = _get_user(user_id)
    player = user.player
    did = []
    for rname in _all_league_role_names_for_fix():
        role = _get_role(rname)
        if role and role in user.roles:
            user.roles.remove(role)
            did.append(f'removed {rname}')
    if player:
        season_ids = _current_season_ids()
        n_live = db.session.execute(player_teams.delete().where(
            player_teams.c.player_id == player.id)).rowcount
        if n_live:
            did.append(f'removed {n_live} roster spot(s)')
        if season_ids:
            n_snap = db.session.query(PlayerTeamSeason).filter(
                PlayerTeamSeason.player_id == player.id,
                PlayerTeamSeason.season_id.in_(season_ids),
            ).delete(synchronize_session=False)
            if n_snap:
                did.append(f'removed {n_snap} season snapshot row(s)')
        if player.is_current_player:
            player.is_current_player = False
            did.append('cleared active flag')
        player.primary_team_id = None
        if player.discord_id:
            defer_discord_removal(player.id)
    if not did:
        return 'Already consistent — nothing to clean up.'
    return 'Cleaned up: ' + ', '.join(did) + '. Discord roles will be removed.'


def _fix_remove_from_team(user_id, player_id, params, admin_id):
    """G8: remove one PLAYING membership (keeps any coach row on the same team)."""
    from app.models import Team, PlayerTeamSeason
    from app.models.players import player_teams
    from sqlalchemy import and_
    team_id = (params or {}).get('team_id')
    if not team_id:
        raise ValueError('team_id required')
    player = _get_player(player_id)
    team = db.session.query(Team).get(team_id)
    if not team:
        raise ValueError('Team not found')
    n = db.session.execute(player_teams.delete().where(and_(
        player_teams.c.player_id == player.id,
        player_teams.c.team_id == team.id,
        player_teams.c.is_coach.isnot(True),
    ))).rowcount
    if not n:
        return f'Already consistent — no playing roster row on {team.name}.'
    season_ids = _current_season_ids()
    if season_ids:
        db.session.query(PlayerTeamSeason).filter(
            PlayerTeamSeason.player_id == player.id,
            PlayerTeamSeason.team_id == team.id,
            PlayerTeamSeason.season_id.in_(season_ids),
        ).delete(synchronize_session=False)
    if player.primary_team_id == team.id:
        # Repoint at a remaining membership so we don't create a G11 finding.
        remaining = db.session.query(player_teams.c.team_id).filter(
            player_teams.c.player_id == player.id).first()
        player.primary_team_id = remaining[0] if remaining else None
    _sync_discord(player)
    return f'Removed {player.name} from {team.name}; Discord roles queued for re-sync.'


def _fix_set_primary_team(user_id, player_id, params, admin_id):
    """G11: point primary_team_id at a team they are actually rostered on."""
    from app.models.players import player_teams
    from sqlalchemy import and_
    team_id = (params or {}).get('team_id')
    if not team_id:
        raise ValueError('team_id required')
    player = _get_player(player_id)
    member = db.session.query(player_teams.c.team_id).filter(and_(
        player_teams.c.player_id == player.id,
        player_teams.c.team_id == team_id,
    )).first()
    if not member:
        raise ValueError('Player is not rostered on that team')
    player.primary_team_id = team_id
    _sync_discord(player)
    return 'Primary team updated; Discord roles queued for re-sync.'


def _fix_clear_primary_team(user_id, player_id, params, admin_id):
    """G7/G11: clear a wrong/stale primary_team_id."""
    player = _get_player(player_id)
    if player.primary_team_id is None:
        return 'Already consistent — primary team is not set.'
    player.primary_team_id = None
    _sync_discord(player)
    return 'Primary team cleared.'


def _fix_align_league_to_team(user_id, player_id, params, admin_id):
    """G7: set primary (and legacy) league to the primary team's division."""
    from app.models import Team
    player = _get_player(player_id)
    if not player.primary_team_id:
        return 'Already consistent — no primary team set.'
    team = db.session.query(Team).get(player.primary_team_id)
    if not team:
        raise ValueError('Primary team no longer exists')
    if player.primary_league_id == team.league_id and player.league_id == team.league_id:
        return 'Already consistent — league already matches the team.'

    # Preserve the league being displaced as a secondary membership. Overwriting
    # primary_league_id outright dropped a dual-program player out of the other
    # program's draft pool, division alignment and season-stats creation --
    # silently, from one admin click on a dashboard that had flagged a perfectly
    # legitimate state.
    _displaced = player.primary_league_id
    player.primary_league_id = team.league_id
    player.league_id = team.league_id
    if _displaced and _displaced != team.league_id:
        try:
            from app.models import League
            _old = db.session.query(League).get(_displaced)
            if _old is not None and _old not in (player.other_leagues or []):
                player.other_leagues.append(_old)
        except Exception as _keep_err:
            logger.warning(f"could not preserve displaced league {_displaced} "
                           f"for player {player.id}: {_keep_err}")
    _sync_discord(player)
    return f"Primary league set to match '{team.name}'; Discord roles queued for re-sync."


def _fix_remove_coach_role(user_id, player_id, params, admin_id):
    """G9: drop a stale division Coach Flask role (Discord follows on sync)."""
    division = (params or {}).get('division')
    if division not in pub_divisions():
        raise ValueError('Invalid division')
    user = _get_user(user_id)
    # Registry-resolved. `f'{division.title()} Coach'` only works while the
    # coach role is the league name plus " Coach" -- "summer sprint" would
    # become "Summer Sprint Coach", a role that does not exist, so the fix
    # raised instead of resolving the finding.
    _coach_role = None
    try:
        from app.services import program_registry
        _pr = program_registry.by_league_name(division)
        if _pr:
            _coach_role = _pr.flask_coach_role
    except Exception:
        pass
    role = _get_role(_coach_role or f'{division.title()} Coach')
    if not role or role not in user.roles:
        return 'Already consistent — they no longer hold that coach role.'
    user.roles.remove(role)
    _sync_discord(user.player)
    # Name the role ACTUALLY removed. `division.title()` rebuilt it by
    # concatenation, so removing 'Summer Coach' reported "Summer Sprint
    # Coach role removed" -- a role that does not exist.
    return f'{role.name} role removed; Discord roles queued for re-sync.'


def _sub_league_type(params):
    """Validate the sub pool's league_type against the registry.

    This ran BEFORE every _sub_role_name_for() call and rejected anything
    outside ('Classic', 'Premier'), so the registry-backed role resolver could
    only ever be handed the two names the old concatenation already handled --
    the helper was dead in practice, and G5 findings for any newer program were
    unfixable with "Invalid sub league type".
    """
    lt = (params or {}).get('league_type')
    valid = None
    try:
        from app.services import program_registry
        valid = {p.league_name for p in program_registry.all_programs()
                 if p.is_pub_league_like and p.league_name}
    except Exception:
        valid = None
    if not valid:
        valid = {'Classic', 'Premier'}
    if lt not in valid:
        raise ValueError('Invalid sub league type')
    return lt


def _all_league_role_names_for_fix():
    """Every program's league role, for the deny-cleanup sweep.

    The G4 DETECTOR is registry-driven but this fixer was not, so a denied user
    holding only a newer program's role was flagged HIGH, the one-click fix
    reported success while removing nothing, and the finding reappeared on
    every scan -- an un-clearable row and a role that is never stripped.
    """
    try:
        from app.services.integrity_service import _all_league_role_names
        return tuple(_all_league_role_names())
    except Exception:
        return ('pl-classic', 'pl-premier', 'pl-ecs-fc')


def _sub_role_name_for(league_type):
    """The real `<X> Sub` Flask role name for a league_type.

    Built by string concatenation (`f'{lt} Sub'`), which only works while a
    program's sub role happens to be its League.name plus " Sub". A program
    whose league is "Summer Sprint" but whose sub role is "Summer Sub" produced
    "Summer Sprint Sub" -- a role that does not exist, so the fixer raised
    "Role ... not found" and the integrity finding could never be resolved.
    """
    try:
        from app.services import program_registry
        pr = program_registry.by_league_name(league_type)
        if pr and pr.flask_sub_role:
            return pr.flask_sub_role
    except Exception:
        pass
    return f'{league_type} Sub'


def _fix_add_sub_role(user_id, player_id, params, admin_id):
    """G5 (pool without role): grant the matching Sub Flask role."""
    lt = _sub_league_type(params)
    user = _get_user(user_id)
    _sub_role = _sub_role_name_for(lt)
    role = _get_role(_sub_role)
    if not role:
        raise ValueError(f'Role {_sub_role} not found')
    if role in user.roles:
        return 'Already consistent — they already hold the sub role.'
    user.roles.append(role)
    _sync_discord(user.player)
    return f'{lt} Sub role granted; Discord roles queued for sync.'


def _fix_remove_sub_role(user_id, player_id, params, admin_id):
    """G5 (role without pool): drop the orphaned Sub Flask role."""
    lt = _sub_league_type(params)
    user = _get_user(user_id)
    role = _get_role(_sub_role_name_for(lt))
    if not role or role not in user.roles:
        return 'Already consistent — they no longer hold the sub role.'
    user.roles.remove(role)
    _sync_discord(user.player)
    return f'{lt} Sub role removed; Discord roles queued for re-sync.'


def _fix_add_to_pool(user_id, player_id, params, admin_id):
    """G5 (role without pool): create/reactivate their pool membership."""
    from app.models.substitutes import SubstitutePool
    lt = _sub_league_type(params)
    player = _get_player(player_id)
    # ⚠️ MUST scope by league_type. This changeset drops the global
    # `substitute_pools.player_id` UNIQUE in favour of
    # UNIQUE(player_id, league_type), so an unscoped .first() returns an
    # ARBITRARY row: the "add to Classic pool" fix would grab the player's
    # Premier row and either refuse (a fix that can never succeed while the
    # right row sits one filter away) or repoint that other program's
    # membership and collide with the new constraint.
    row = db.session.query(SubstitutePool).filter_by(
        player_id=player.id, league_type=lt).first()
    if row is None:
        db.session.add(SubstitutePool(
            player_id=player.id, league_type=lt, is_active=True,
            approved_by=admin_id, approved_at=datetime.utcnow(),
        ))
        return f'Added to the active {lt} sub pool.'
    if row.is_active:
        return 'Already consistent — active pool entry exists.'
    # The query above is scoped to this league_type, so `row` can only ever BE
    # this lane. The old "already in another division's pool" branch existed
    # because player_id was globally UNIQUE (one row per player); with
    # UNIQUE(player_id, league_type) a player legitimately holds one row per
    # program, and reactivating this one does not disturb the others.
    row.is_active = True
    row.approved_by = admin_id
    row.approved_at = datetime.utcnow()
    row.last_active_at = datetime.utcnow()
    return f'Reactivated their {lt} sub pool entry.'


def _fix_deactivate_pool(user_id, player_id, params, admin_id):
    """G5 (pool without role): deactivate the orphaned pool membership."""
    from app.models.substitutes import SubstitutePool
    lt = _sub_league_type(params)
    player = _get_player(player_id)
    row = db.session.query(SubstitutePool).filter_by(
        player_id=player.id, league_type=lt, is_active=True).first()
    if not row:
        return 'Already consistent — no active pool entry.'
    row.is_active = False
    return f'{lt} sub pool entry deactivated.'


def _fix_sync_ecs_pools(user_id, player_id, params, admin_id):
    """G6: mirror the player into whichever ECS FC pool table is missing them."""
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    player = _get_player(player_id)
    # ECS FC's mirror row specifically -- see the note above about the dropped
    # global UNIQUE. Unscoped, this could pick up a Premier/Classic row and
    # sync it against EcsFcSubPool.
    unified = db.session.query(SubstitutePool).filter_by(
        player_id=player.id, league_type='ECS FC').first()
    dedicated = db.session.query(EcsFcSubPool).filter_by(player_id=player.id).first()
    unified_active = bool(unified and unified.is_active and unified.league_type == 'ECS FC')
    dedicated_active = bool(dedicated and dedicated.is_active)
    if unified_active and dedicated_active:
        return 'Already consistent — in both pools.'
    if not unified_active and not dedicated_active:
        return 'Already consistent — in neither pool.'
    if unified_active:
        if dedicated is None:
            db.session.add(EcsFcSubPool(player_id=player.id, is_active=True))
        else:
            dedicated.is_active = True
        return 'Mirrored into the ECS FC pool — both systems now see them.'
    # dedicated only → mirror into the unified table
    if unified is None:
        db.session.add(SubstitutePool(
            player_id=player.id, league_type='ECS FC', is_active=True,
            approved_by=admin_id, approved_at=datetime.utcnow(),
        ))
    elif not unified.is_active:
        unified.league_type = 'ECS FC'
        unified.is_active = True
        unified.approved_by = admin_id
        unified.approved_at = datetime.utcnow()
    else:
        raise ValueError(
            f'They have an active {unified.league_type} entry in the unified pool; '
            'use the substitute pool page to resolve this one.')
    return 'Mirrored into the unified pool — both systems now see them.'


def _fix_deactivate_ecs_pools(user_id, player_id, params, admin_id):
    """G6: remove from ECS FC sub duty on both sides."""
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    player = _get_player(player_id)
    did = False
    unified = db.session.query(SubstitutePool).filter_by(
        player_id=player.id, league_type='ECS FC', is_active=True).first()
    if unified:
        unified.is_active = False
        did = True
    dedicated = db.session.query(EcsFcSubPool).filter_by(
        player_id=player.id, is_active=True).first()
    if dedicated:
        dedicated.is_active = False
        did = True
    return ('ECS FC pool memberships deactivated on both sides.' if did
            else 'Already consistent — no active ECS FC pool entries.')


def _fix_mark_inactive(user_id, player_id, params, admin_id):
    """G12: clear is_current_player for an unrostered 'active' player."""
    player = _get_player(player_id)
    if not player.is_current_player:
        return 'Already consistent — not marked current.'
    player.is_current_player = False
    return f'{player.name} is no longer counted as a current player.'


def _fix_sync_league_id(user_id, player_id, params, admin_id):
    """G13: legacy league_id follows primary_league_id."""
    player = _get_player(player_id)
    if player.league_id == player.primary_league_id:
        return 'Already consistent.'
    player.league_id = player.primary_league_id
    return 'league_id synced to primary league.'


def _fix_clear_waitlist(user_id, player_id, params, admin_id):
    """G15: they have a spot — take them off the waitlist."""
    user = _get_user(user_id)
    did = False
    if user.waitlist_joined_at is not None:
        user.waitlist_joined_at = None
        did = True
    role = _get_role('pl-waitlist')
    if role and role in user.roles:
        user.roles.remove(role)
        did = True
    if did:
        _sync_discord(user.player)
        return 'Removed from the waitlist; positions behind them shift up.'
    return 'Already consistent — not on the waitlist.'


# (code, action) -> fixer. An action listed under a code it wasn't offered for is
# rejected, so the endpoint can't be used to run arbitrary mutations.
FIXERS = {
    ('G1', 'approve'): _fix_approve,
    ('G2', 'approve'): _fix_approve,
    ('G3', 'approve'): _fix_approve,
    ('G4', 'deny_cleanup'): _fix_deny_cleanup,
    ('G5', 'add_to_pool'): _fix_add_to_pool,
    ('G5', 'remove_sub_role'): _fix_remove_sub_role,
    ('G5', 'add_sub_role'): _fix_add_sub_role,
    ('G5', 'deactivate_pool'): _fix_deactivate_pool,
    ('G6', 'sync_ecs_pools'): _fix_sync_ecs_pools,
    ('G6', 'deactivate_ecs_pools'): _fix_deactivate_ecs_pools,
    ('G7', 'align_league_to_team'): _fix_align_league_to_team,
    ('G7', 'clear_primary_team'): _fix_clear_primary_team,
    ('G8', 'remove_from_team'): _fix_remove_from_team,
    ('G9', 'remove_coach_role'): _fix_remove_coach_role,
    ('G11', 'set_primary_team'): _fix_set_primary_team,
    ('G11', 'clear_primary_team'): _fix_clear_primary_team,
    ('G12', 'mark_inactive'): _fix_mark_inactive,
    ('G13', 'sync_league_id'): _fix_sync_league_id,
    ('G15', 'clear_waitlist'): _fix_clear_waitlist,
}


def apply_fix(code, action, user_id, player_id, params, admin_id) -> str:
    """Dispatch a resolve request. Returns a result message; raises ValueError
    for anything invalid. Runs inside the caller's transaction."""
    fixer = FIXERS.get((code, action))
    if not fixer:
        raise ValueError(f'Unknown fix {code}/{action}')
    result = fixer(user_id, player_id, params, admin_id)
    # Phase-0 dual-write: any integrity fix that changed roster/pool/coach/approval state
    # should re-sync the spine so the repair tools don't themselves drift it.
    if player_id:
        try:
            from app.services.league_membership_sync import resync_player_memberships
            resync_player_memberships(db.session, player_id)
        except Exception as _lm_err:
            logger.warning(f"league_membership sync skipped after integrity fix for player {player_id}: {_lm_err}")
    return result
