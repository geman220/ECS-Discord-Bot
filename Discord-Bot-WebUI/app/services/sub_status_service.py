# app/services/sub_status_service.py

"""
Substitute-status cleanup for players who become rostered team members.

When a player is drafted onto a team (web/mobile draft) or moved between
divisions (admin comprehensive edit), any leftover Pub League substitute
status must be dropped. Otherwise the stale Flask sub role (`Classic Sub` /
`Premier Sub`) keeps producing a stale Discord role (`ECS-FC-PL-CLASSIC-SUB` /
`ECS-FC-PL-PREMIER-SUB`), which is what stranded "David Cravens" — moved to
Premier but still carrying his Classic sub role.

Design decisions (confirmed with the product owner):
  - Strip Classic AND Premier sub status when a player is rostered on ANY
    Pub League team. A rostered pub-league player is a player, not a sub.
  - INTENTIONALLY keep `ECS FC Sub` / EcsFcSubPool: a rostered Pub League
    player can still legitimately substitute for ECS FC (separate program).
  - Remove the pool membership (source of truth), not just the Flask role, so
    the sub board never shows a rostered player as an available sub.

This module only mutates DB state on the passed-in session; it NEVER commits and
NEVER performs Discord I/O. The caller owns the transaction and is responsible
for queuing the post-commit Discord role reconcile (with removals enabled) when
`roles_removed` is non-empty — see `sub_status_removed()`.
"""

import logging

logger = logging.getLogger(__name__)

# Pub League league_type values that conflict with being rostered.
# 'ECS FC' is deliberately excluded (see module docstring).
PUB_LEAGUE_SUB_LEAGUE_TYPES = ('Classic', 'Premier')          # fallback

# Flask role names that grant the corresponding Discord sub role.
PUB_LEAGUE_SUB_ROLE_NAMES = ('Classic Sub', 'Premier Sub')    # fallback

# Sub Flask role -> the pool it is backed by.
#   ('pl', <league_type>) -> SubstitutePool row with that league_type
#   ('ecs_fc', None)      -> the separate EcsFcSubPool row
SUB_ROLE_TO_POOL = {                                          # fallback
    'Classic Sub': ('pl', 'Classic'),
    'Premier Sub': ('pl', 'Premier'),
    'ECS FC Sub': ('ecs_fc', None),
}


def _registry_programs():
    try:
        from app.services import program_registry
        return list(program_registry.all_programs())
    except Exception:
        return []


def pub_league_sub_league_types():
    """League.name values whose sub status conflicts with being rostered."""
    progs = _registry_programs()
    names = tuple(p.league_name for p in progs if p.is_pub_league_like)
    return names or PUB_LEAGUE_SUB_LEAGUE_TYPES


def pub_league_sub_role_names():
    """Flask sub-role names for pub-league-like programs."""
    progs = _registry_programs()
    names = tuple(p.flask_sub_role for p in progs
                  if p.is_pub_league_like and p.flask_sub_role)
    return names or PUB_LEAGUE_SUB_ROLE_NAMES


def sub_role_to_pool():
    """Flask sub role -> (pool kind, league_type).

    ECS FC keeps its separate EcsFcSubPool table, which is why the value is a
    tuple rather than just a league_type. Every other program is backed by a
    SubstitutePool row keyed on its League.name.
    """
    progs = _registry_programs()
    if not progs:
        return dict(SUB_ROLE_TO_POOL)
    out = {}
    for p in progs:
        if not p.flask_sub_role:
            continue
        if p.is_pub_league_like:
            out[p.flask_sub_role] = ('pl', p.league_name)
        elif p.key == 'ecs_fc':
            # EcsFcSubPool is ECS FC's own legacy table -- it is not a generic
            # "non-pub-league" pool. Mapping every non-pub-league program here
            # would silently make a second such program share ECS FC's rows.
            out[p.flask_sub_role] = ('ecs_fc', None)
        else:
            # Backed by SubstitutePool keyed on its own League.name, like every
            # other program. Nothing else is special about ECS FC.
            out[p.flask_sub_role] = ('pl', p.league_name)
    return out or dict(SUB_ROLE_TO_POOL)


def deactivate_sub_pool_for_role(session, player_id, role_name, performed_by_user_id=None):
    """
    Deactivate the substitute-pool membership backing a given sub Flask role.

    Handles both the Pub League SubstitutePool (Classic/Premier, keyed by
    league_type) and the separate EcsFcSubPool. Does NOT touch the Flask role
    itself and does NOT commit. Returns True if a membership was deactivated.
    """
    mapping = sub_role_to_pool().get(role_name)
    if not mapping:
        return False
    kind, league_type = mapping

    if kind == 'pl':
        from app.models.substitutes import SubstitutePool, log_pool_action
        pool = session.query(SubstitutePool).filter(
            SubstitutePool.player_id == player_id,
            SubstitutePool.is_active == True,  # noqa: E712
            SubstitutePool.league_type == league_type,
        ).first()
        if pool is None:
            return False
        pool.is_active = False
        session.add(pool)
        try:
            log_pool_action(
                player_id=player_id, league_id=pool.league_id, action='REMOVED',
                notes=f"Auto-removed from {league_type} sub pool "
                      f"(rostered / division change)",
                performed_by=performed_by_user_id, pool_id=pool.id, session=session,
            )
        except Exception as e:
            logger.warning(f"Sub pool history log skipped for player {player_id}: {e}")
        return True

    from app.models.substitutes import EcsFcSubPool
    pool = session.query(EcsFcSubPool).filter(
        EcsFcSubPool.player_id == player_id,
        EcsFcSubPool.is_active == True,  # noqa: E712
    ).first()
    if pool is None:
        return False
    pool.is_active = False
    session.add(pool)
    return True


def detect_conflicting_sub_status(session, player):
    """
    Return the Pub League (Classic/Premier) sub status a rostered player still
    holds, without mutating anything. Used to surface a warning ("this rostered
    player is still on the X sub list — remove them?").

    Returns a dict: {'pool_league_types': [...], 'role_names': [...]}.
    Empty lists mean no conflict.
    """
    from app.models.substitutes import SubstitutePool

    pool_league_types = []
    if player is not None:
        pools = session.query(SubstitutePool).filter(
            SubstitutePool.player_id == player.id,
            SubstitutePool.is_active == True,  # noqa: E712
            SubstitutePool.league_type.in_(pub_league_sub_league_types()),
        ).all()
        pool_league_types = [p.league_type for p in pools]

    role_names = []
    if player is not None and player.user is not None:
        held = {r.name for r in player.user.roles}
        role_names = [n for n in pub_league_sub_role_names() if n in held]

    return {'pool_league_types': pool_league_types, 'role_names': role_names}


def _conflicting_sub_roles(league_name=None):
    """Sub roles that conflict with being rostered in `league_name`.

    ⚠️ "Conflicting" means THE SAME DIVISION FAMILY, not "every pub-league-like
    program". Programs that share a `season_league_type` are mutually exclusive
    divisions of one season (Premier vs Classic): you cannot be a rostered
    Premier player and a Premier sub. Programs on DIFFERENT season types are
    independent, concurrent leagues -- being rostered in one says nothing about
    your sub status in another, exactly as _assign_league_additively already
    decides for league membership.

    Left unscoped, getting drafted into Premier deactivated the player's pool
    row and stripped their sub role in every other program, and vice versa.
    """
    progs = _registry_programs()
    if not progs:
        return tuple(PUB_LEAGUE_SUB_ROLE_NAMES)
    if league_name:
        _self = next((p for p in progs
                      if (p.league_name or '').lower() == str(league_name).lower()), None)
        if _self is not None:
            fam = [p for p in progs
                   if p.is_pub_league_like
                   and p.season_league_type == _self.season_league_type
                   and p.flask_sub_role]
            if fam:
                return tuple(p.flask_sub_role for p in fam)
    return pub_league_sub_role_names()


def remove_conflicting_sub_status(session, player_id, performed_by_user_id=None,
                                  league_name=None):
    """
    Drop a player's substitute status in the division family they were just
    rostered into.

    Deactivates that family's active SubstitutePool rows, removes its sub Flask
    roles, and writes a pool-history audit row. Sub status in OTHER programs
    (and ECS FC) is left untouched -- pass `league_name` (the League they were
    rostered into) to get that scoping; without it the call falls back to the
    old all-pub-league-programs behaviour.

    Does NOT commit and does NOT touch Discord. Returns a summary dict:
        {
          'player_name': str | None,
          'pools_removed': ['Classic', ...],   # league_types deactivated
          'roles_removed': ['Classic Sub', ...],
        }
    `roles_removed` being non-empty is the caller's signal to queue a Discord
    role reconcile with removals enabled (see `sub_status_removed`).
    """
    from app.models import Player, Role

    summary = {'player_name': None, 'pools_removed': [], 'roles_removed': []}

    player = session.query(Player).get(player_id)
    if player is None:
        return summary
    summary['player_name'] = player.name

    held_roles = {r.name for r in player.user.roles} if player.user is not None else set()

    # For each Pub League sub role: deactivate its pool membership AND remove the
    # Flask role. Both are handled independently so data drift (role without pool,
    # or vice versa) is cleaned up either way. ECS FC sub status is never touched.
    # Both sides must come from the SAME source. pub_league_sub_role_names() is
    # registry-driven and can yield a role outside the static three-key legacy
    # dict, so subscripting SUB_ROLE_TO_POOL here raised KeyError -- on the
    # draft/roster path, which 500s a draft pick.
    _pool_map = sub_role_to_pool()
    for role_name in _conflicting_sub_roles(league_name):
        _mapped = _pool_map.get(role_name)
        if not _mapped:
            logger.warning(f"no pool mapping for sub role '{role_name}'; skipping")
            continue
        _, league_type = _mapped
        if deactivate_sub_pool_for_role(session, player_id, role_name, performed_by_user_id):
            summary['pools_removed'].append(league_type)
        if role_name in held_roles:
            role = session.query(Role).filter_by(name=role_name).first()
            if role is not None and role in player.user.roles:
                player.user.roles.remove(role)
                summary['roles_removed'].append(role_name)

    if summary['pools_removed'] or summary['roles_removed']:
        logger.info(
            f"Removed conflicting sub status for player {player_id} "
            f"({summary['player_name']}): pools={summary['pools_removed']} "
            f"roles={summary['roles_removed']}"
        )

    return summary


def sub_status_removed(summary):
    """True if `remove_conflicting_sub_status` actually stripped a sub role."""
    return bool(summary and summary.get('roles_removed'))


def sub_removal_notice(summary):
    """
    Build a short human-readable notice for the draft UI / logs, or None if
    nothing was removed. Explains what happened so it isn't a silent change.
    """
    if not summary:
        return None
    types = summary.get('pools_removed') or []
    if not types and not summary.get('roles_removed'):
        return None
    name = summary.get('player_name') or 'Player'
    league_label = ' & '.join(types) if types else 'substitute'
    return (f"{name} was removed from the {league_label} sub list "
            f"(now rostered on a team).")
