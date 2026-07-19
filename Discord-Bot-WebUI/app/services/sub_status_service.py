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
PUB_LEAGUE_SUB_LEAGUE_TYPES = ('Classic', 'Premier')

# Flask role names that grant the corresponding Discord sub role.
PUB_LEAGUE_SUB_ROLE_NAMES = ('Classic Sub', 'Premier Sub')


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
            SubstitutePool.league_type.in_(PUB_LEAGUE_SUB_LEAGUE_TYPES),
        ).all()
        pool_league_types = [p.league_type for p in pools]

    role_names = []
    if player is not None and player.user is not None:
        held = {r.name for r in player.user.roles}
        role_names = [n for n in PUB_LEAGUE_SUB_ROLE_NAMES if n in held]

    return {'pool_league_types': pool_league_types, 'role_names': role_names}


def remove_conflicting_sub_status(session, player_id, performed_by_user_id=None):
    """
    Drop a player's Pub League (Classic/Premier) substitute status because they
    became a rostered team member.

    Deactivates any active Classic/Premier SubstitutePool row, removes the
    'Classic Sub' / 'Premier Sub' Flask roles, and writes a pool-history audit
    row. Leaves ECS FC sub status untouched.

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
    from app.models.substitutes import SubstitutePool, log_pool_action

    summary = {'player_name': None, 'pools_removed': [], 'roles_removed': []}

    player = session.query(Player).get(player_id)
    if player is None:
        return summary
    summary['player_name'] = player.name

    # 1) Deactivate any active Classic/Premier pool membership. player_id is
    #    UNIQUE on substitute_pools, so there is at most one row, but we filter
    #    on league_type so an ECS FC row is never touched.
    pool = session.query(SubstitutePool).filter(
        SubstitutePool.player_id == player_id,
        SubstitutePool.is_active == True,  # noqa: E712
        SubstitutePool.league_type.in_(PUB_LEAGUE_SUB_LEAGUE_TYPES),
    ).first()
    if pool is not None:
        pool.is_active = False
        session.add(pool)
        summary['pools_removed'].append(pool.league_type)
        try:
            log_pool_action(
                player_id=player_id,
                league_id=pool.league_id,
                action='REMOVED',
                notes=f"Auto-removed from {pool.league_type} sub pool "
                      f"(rostered on a team)",
                performed_by=performed_by_user_id,
                pool_id=pool.id,
                session=session,
            )
        except Exception as e:  # audit is best-effort; never block the roster write
            logger.warning(f"Sub pool history log skipped for player {player_id}: {e}")

    # 2) Remove the pub-league sub Flask roles (the source of the Discord role).
    if player.user is not None:
        for role_name in PUB_LEAGUE_SUB_ROLE_NAMES:
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
