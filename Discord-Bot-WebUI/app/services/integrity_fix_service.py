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

PUB_DIVISIONS = ('classic', 'premier')


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
    if league_type not in APPROVE_LEAGUE_TYPES:
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
    for rname in ('pl-classic', 'pl-premier', 'pl-ecs-fc'):
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
    player.primary_league_id = team.league_id
    player.league_id = team.league_id
    _sync_discord(player)
    return f"Primary league set to match '{team.name}'; Discord roles queued for re-sync."


def _fix_remove_coach_role(user_id, player_id, params, admin_id):
    """G9: drop a stale division Coach Flask role (Discord follows on sync)."""
    division = (params or {}).get('division')
    if division not in PUB_DIVISIONS:
        raise ValueError('Invalid division')
    user = _get_user(user_id)
    role = _get_role(f'{division.title()} Coach')
    if not role or role not in user.roles:
        return 'Already consistent — they no longer hold that coach role.'
    user.roles.remove(role)
    _sync_discord(user.player)
    return f'{division.title()} Coach role removed; Discord roles queued for re-sync.'


def _sub_league_type(params):
    lt = (params or {}).get('league_type')
    if lt not in ('Classic', 'Premier'):
        raise ValueError('Invalid sub league type')
    return lt


def _fix_add_sub_role(user_id, player_id, params, admin_id):
    """G5 (pool without role): grant the matching Sub Flask role."""
    lt = _sub_league_type(params)
    user = _get_user(user_id)
    role = _get_role(f'{lt} Sub')
    if not role:
        raise ValueError(f'Role {lt} Sub not found')
    if role in user.roles:
        return 'Already consistent — they already hold the sub role.'
    user.roles.append(role)
    _sync_discord(user.player)
    return f'{lt} Sub role granted; Discord roles queued for sync.'


def _fix_remove_sub_role(user_id, player_id, params, admin_id):
    """G5 (role without pool): drop the orphaned Sub Flask role."""
    lt = _sub_league_type(params)
    user = _get_user(user_id)
    role = _get_role(f'{lt} Sub')
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
    row = db.session.query(SubstitutePool).filter_by(player_id=player.id).first()
    if row is None:
        db.session.add(SubstitutePool(
            player_id=player.id, league_type=lt, is_active=True,
            approved_by=admin_id, approved_at=datetime.utcnow(),
        ))
        return f'Added to the active {lt} sub pool.'
    if row.is_active and row.league_type == lt:
        return 'Already consistent — active pool entry exists.'
    if row.is_active and row.league_type != lt:
        # One row per player: silently moving them would yank them out of the
        # other division's pool. That trade-off belongs in the pool UI.
        raise ValueError(
            f'They already have an active {row.league_type} pool entry; '
            'use the substitute pool page to move them between pools.')
    row.league_type = lt
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
    unified = db.session.query(SubstitutePool).filter_by(player_id=player.id).first()
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
    return fixer(user_id, player_id, params, admin_id)
