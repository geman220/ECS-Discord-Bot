# app/services/player_division_service.py

"""
Ensure a drafted player HAS the drafted team's division association + division
Flask role, so they reliably receive that division's Discord role.

The draft runs per-division (the Premier draft only lists Premier players), so for
clean data this is a NO-OP. Its job is a narrow self-heal: a drifted player who is
drafted onto a Classic/Premier team but is MISSING that division's league
association or `pl-<division>` Flask role would otherwise not get the division
Discord role (both role calculators derive it from league associations + the
pl-* role). This adds what's missing.

PURELY ADDITIVE — by design it never removes anything:
  * Holding BOTH `pl-premier` and `pl-classic` is a legitimate, supported state in
    this codebase (see app/forms.py dual-division validation; get_expected_roles
    grants both), so we must NOT strip the "other" division on a draft.
  * It never displaces an existing primary league (that would drop a legit
    association and cause a removal reconcile to strip a real Discord role).
  * Removing a division (a genuine MOVE) is the admin edit form's job — it
    reconciles with removals and lets the admin decide. The draft only adds.
  * Because it only adds, the caller does NOT need a removal reconcile; an
    only_add=True sync grants the added role. `changed` is informational.

Scope: Classic <-> Premier only. ECS FC is untouched (a player can be in ECS FC
AND a Pub League division at once). Mutates only the passed session; NEVER commits
and NEVER does Discord I/O.
"""

import logging

logger = logging.getLogger(__name__)

# Pub League division name (lower) -> the pl-* Flask role that drives its Discord role.
DIVISION_LEAGUE_ROLE = {'premier': 'pl-premier', 'classic': 'pl-classic'}


def align_player_to_drafted_division(session, player_id, team):
    """
    Ensure a drafted player's league associations include the Classic/Premier team
    they were drafted onto, and that they hold the matching pl-<division> Flask
    role. PURELY ADDITIVE: never removes another division or displaces the primary.

    Returns {'changed': bool, 'league_set': str|None, 'role_added': str|None,
             'player_name': str|None}. `changed` means something was ADDED (used
             only for logging/notice — additive changes don't need a removal sync).
    """
    from app.models import Player, Role

    result = {'changed': False, 'league_set': None, 'role_added': None,
              'player_name': None}

    if team is None or team.league is None or not team.league.name:
        return result
    division = team.league.name.strip().lower()
    if division not in DIVISION_LEAGUE_ROLE:
        # ECS FC or a renamed league (e.g. "Premier Division") — leave everything
        # alone. Log the no-op so a league rename that silently disables the heal
        # is at least visible.
        logger.debug(f"Division align no-op for player {player_id}: team league "
                     f"'{team.league.name}' is not a bare Classic/Premier division")
        return result

    player = session.query(Player).get(player_id)
    if player is None:
        return result
    result['player_name'] = player.name

    # 1) Make sure the drafted division is among the player's league associations so
    #    the reconcile grants ECS-FC-PL-<DIV>. If they have NO primary league, set it
    #    as primary; otherwise ADD it to other_leagues (never displace the primary —
    #    a primary-league MOVE is the admin edit form's job).
    assoc_ids = set()
    if player.league_id:
        assoc_ids.add(player.league_id)
    if player.primary_league_id:
        assoc_ids.add(player.primary_league_id)
    assoc_ids.update(lg.id for lg in (player.other_leagues or []))

    if team.league_id not in assoc_ids:
        if player.primary_league_id is None:
            player.primary_league_id = team.league_id
            if player.league_id is None:
                player.league_id = team.league_id
        else:
            player.other_leagues.append(team.league)
        result['league_set'] = team.league.name
        result['changed'] = True

    if player.user is None:
        return result

    # 2) Ensure the drafted-division Flask role is present (additive only).
    want_role = DIVISION_LEAGUE_ROLE[division]
    if want_role not in {r.name for r in player.user.roles}:
        role = session.query(Role).filter_by(name=want_role).first()
        if role is not None and role not in player.user.roles:
            player.user.roles.append(role)
            result['role_added'] = want_role
            result['changed'] = True

    if result['changed']:
        logger.info(f"Division-aligned player {player_id} ({result['player_name']}) to "
                    f"'{division}' (additive): {result}")
    return result
