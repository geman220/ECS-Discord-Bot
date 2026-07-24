# app/tasks/tasks_discord.py

"""
Discord Tasks Module

This module defines several Celery tasks and async helpers that manage Discord-related
operations including updating player roles, processing role updates, creating and
cleaning up Discord resources, and fetching role status.

Tasks and helpers include:
  - update_player_discord_roles: Update a single player's Discord roles.
  - process_discord_role_updates: Batch process role updates for multiple players.
  - assign_roles_to_player_task: Assign or update roles for a specific player.
  - fetch_role_status: Retrieve and process the current role status of players.
  - remove_player_roles_task: Remove a player's Discord roles.
  - create_team_discord_resources_task: Create Discord resources for a team.
  - cleanup_team_discord_resources_task: Clean up Discord resources for a team.
  - update_team_discord_resources_task: Update Discord resources when team names change.
  
Helper async functions perform HTTP calls to the Discord bot API using aiohttp.
"""

import logging
import asyncio
import aiohttp
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import SQLAlchemyError

# Import optimized utilities
from app.utils.cache_manager import reference_cache, clear_player_cache
from app.utils.query_optimizer import (
    QueryOptimizer, 
    memory_efficient_session, 
    efficient_player_discord_batch,
    stream_players_with_discord_ids,
    BatchConfig
)
import traceback

from app.core import socketio
from app.decorators import celery_task
from app.models import Player, Team, User, PlayerTeamSeason, Season
from app.utils.task_session_manager import task_session
from app.discord_utils import (
    update_player_roles,
    rename_team_roles,
    create_discord_channel,
    get_expected_roles,
    fetch_user_roles,
    process_single_player_update,
    remove_role_from_member,
    get_role_id,
    get_member_roles,
    normalize_name
)
from web_config import Config
from app.utils.discord_request_handler import make_discord_request

logger = logging.getLogger(__name__)


def get_current_season_teams(session, player):
    """
    Get current season teams for a player using PlayerTeamSeason records.
    Falls back to direct team relationships if no current season records exist.

    Args:
        session: Database session
        player: Player object

    Returns:
        List of current season team dictionaries with id, name, and league_name
    """
    try:
        # Live per-team coach status from the player_teams association (the source
        # of truth an admin edits). Used to scope coach Discord roles to the
        # SPECIFIC team(s) a player coaches — so a Premier player who coaches a
        # Classic team gets only Classic coach access, not Premier.
        from app.models import player_teams as _pt
        coach_map = {
            row.team_id: bool(row.is_coach)
            for row in session.execute(
                _pt.select().where(_pt.c.player_id == player.id)
            ).fetchall()
        }

        # Get ALL current seasons (Pub League AND ECS FC can both be current)
        current_seasons = session.query(Season).filter_by(is_current=True).all()
        logger.info(f"[DEBUG] Player {player.id}: Found {len(current_seasons)} current seasons: {[(s.id, s.name, s.league_type) for s in current_seasons]}")

        if current_seasons:
            current_season_ids = [s.id for s in current_seasons]
            logger.info(f"[DEBUG] Player {player.id}: Current season IDs: {current_season_ids}")

            # Query teams through PlayerTeamSeason for ALL current seasons
            current_season_teams = session.query(Team).join(
                PlayerTeamSeason, Team.id == PlayerTeamSeason.team_id
            ).filter(
                PlayerTeamSeason.player_id == player.id,
                PlayerTeamSeason.season_id.in_(current_season_ids)
            ).all()

            logger.info(f"[DEBUG] Player {player.id}: Found {len(current_season_teams)} teams via PlayerTeamSeason: {[(t.id, t.name, t.league.name if t.league else None) for t in current_season_teams]}")

            # UNION both sources, never either/or. This used to return the
            # PlayerTeamSeason result the moment it was non-empty and only fall back
            # to player_teams when it was EMPTY — so a player with a PTS row for one
            # team (say a Premier draft pick) but only a player_teams row for another
            # (an ECS FC placement whose PTS row was never written) had the second
            # team silently dropped from their expected roles. The reconcile then
            # treated that live team role as unexpected: rostered, but losing the role.
            current_season_league_ids = {league.id for season in current_seasons
                                         for league in season.leagues}
            merged = {}
            for team in current_season_teams:
                merged[team.id] = team
            for team in player.teams:
                if team.league_id in current_season_league_ids and team.id not in merged:
                    logger.info(
                        f"[DEBUG] Player {player.id}: team {team.id} ({team.name}) is on "
                        f"player_teams with no current-season PlayerTeamSeason row — "
                        f"including it so its Discord role is not stripped"
                    )
                    merged[team.id] = team

            if merged:
                result = [{'id': team.id, 'name': team.name,
                           'league_name': team.league.name if team.league else None,
                           'is_coach': coach_map.get(team.id, False)}
                          for team in merged.values()]
                logger.info(f"[DEBUG] Player {player.id}: Returning teams: {result}")
                return result

        # Final fallback: return empty list to avoid assigning old roles
        logger.warning(f"No current season teams found for player {player.id}, returning empty list to avoid old roles")
        return []

    except Exception as e:
        logger.error(f"Error getting current season teams for player {player.id}: {e}")
        return []


def get_status_html(roles_match: bool) -> str:
    """
    Generate an HTML snippet indicating whether roles are in sync.
    
    Args:
        roles_match: True if current roles match expected roles.
        
    Returns:
        A span element as a string representing the status.
    """
    return (
        '<span class="badge bg-success">Synced</span>'
        if roles_match
        else '<span class="badge bg-warning">Out of Sync</span>'
    )


def create_error_result(player_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a standardized error result for a player.
    
    Args:
        player_info: Dictionary containing player's id, name, team, and league.
        
    Returns:
        A dictionary with error status and default values.
    """
    return {
        'id': player_info['id'],
        'name': player_info['name'],
        'team': player_info.get('team', 'No Team'),
        'league': player_info.get('league', 'No League'),
        'current_roles': [],
        'expected_roles': [],
        'status_html': '<span class="badge bg-danger">Error</span>',
        'last_verified': 'Never',
        'error': True
    }


# ---------------------------------------------------------------------------
# Shared expected-role calculator
#
# There used to be two near-identical copies of this logic — one in
# _execute_player_role_update_async (the reconcile) and one in
# _execute_assign_roles_async (the grant). They drifted repeatedly, and because
# the reconcile REMOVES anything the grant didn't produce (and vice versa), every
# divergence showed up as a Discord role flapping on and off. They now both call
# these two functions, so a change lands in both paths at once.
# ---------------------------------------------------------------------------

def _compute_expected_roles(data: Dict[str, Any], teams: Optional[List[Dict]] = None,
                            include_global: bool = True) -> List[str]:
    """Build the full set of Discord roles a player should hold.

    Args:
        data: the extracted player payload (teams, user_roles, league_names, ...).
        teams: override the team list. A SCOPED grant passes only its target team.
        include_global: False for a scoped grant — only the given teams' roles are
            produced. A caller passing False MUST also scope app_managed_roles to
            the same teams and pass pattern_sweep=False, or the reconcile will read
            the deliberately-partial result as "everything else is unexpected".
    """
    all_teams = [t for t in (data.get('teams') or []) if t]
    if teams is None:
        teams = all_teams
    else:
        teams = [t for t in teams if t]

    expected: List[str] = []

    def _add(role: str):
        if role not in expected:
            expected.append(role)

    # --- Per-team player + coach roles -------------------------------------
    # ECS FC teams included: every path that grants or revokes a team role names it
    # ECS-FC-PL-<team>-Player, so excluding ECS FC here never made it a no-op — it
    # just left the role matching the reconcile's catch-all and got it stripped.
    # The -Coach role is a REAL guild role carrying LEADERSHIP_PERMISSIONS on the
    # team channel, so it is expected (and managed) alongside the -Player role.
    for team in teams:
        if team.get('league_name') in ['Premier', 'Classic', 'ECS FC']:
            _add(f"ECS-FC-PL-{normalize_name(team['name'])}-Player")
            if team.get('is_coach'):
                _add(f"ECS-FC-PL-{normalize_name(team['name'])}-Coach")

    if include_global:
        user_roles = data.get('user_roles', [])
        league_names = data.get('league_names', [])

        # --- Division / league roles ---------------------------------------
        # Priority 1: Flask roles (most authoritative).
        if 'pl-premier' in user_roles:
            _add('ECS-FC-PL-PREMIER')
        if 'pl-classic' in user_roles:
            _add('ECS-FC-PL-CLASSIC')

        # ECS FC membership is a separate axis from Pub League currency: being
        # rostered on an ECS FC team is sufficient on its own. Deliberately NOT in
        # the managed list below, so a reconcile can only ever ADD it.
        if 'pl-ecs-fc' in user_roles or any(t.get('league_name') == 'ECS FC' for t in all_teams):
            _add('ECS-FC-PL-ECS-FC')

        # Priority 2: DB league associations (league_id / primary_league / other).
        for league_name in league_names:
            ln = (league_name or '').strip().lower()
            if ln == 'premier':
                _add('ECS-FC-PL-PREMIER')
            elif ln == 'classic':
                _add('ECS-FC-PL-CLASSIC')
            elif ln == 'ecs fc':
                _add('ECS-FC-PL-ECS-FC')

        # Priority 3: CURRENT-SEASON TEAM MEMBERSHIP. Being rostered on a Premier
        # team makes you a Premier player — full stop. Without this, a player placed
        # on a team by any path that doesn't also write the league association or the
        # pl-<division> Flask role (the member-hub Place button was one) got the team
        # role but never the division role, so they were on the roster with no
        # division channel access.
        for t in all_teams:
            ln = (t.get('league_name') or '').strip().lower()
            if ln == 'premier':
                _add('ECS-FC-PL-PREMIER')
            elif ln == 'classic':
                _add('ECS-FC-PL-CLASSIC')

        # --- Substitute roles ----------------------------------------------
        if 'Premier Sub' in user_roles:
            _add('ECS-FC-PL-PREMIER-SUB')
        if 'Classic Sub' in user_roles:
            _add('ECS-FC-PL-CLASSIC-SUB')
        if 'ECS FC Sub' in user_roles:
            _add('ECS-FC-LEAGUE-SUB')

        # --- Coach roles ----------------------------------------------------
        # Team-INDEPENDENT division coach roles (the Coaches panel), so a coach gets
        # their division role UP FRONT, before any team exists or drafting happens.
        if 'Premier Coach' in user_roles:
            _add('ECS-FC-PL-PREMIER-COACH')
        if 'Classic Coach' in user_roles:
            _add('ECS-FC-PL-CLASSIC-COACH')

        # Per-team coach roles, scoped to the league of each team the player actually
        # coaches (player_teams.is_coach) — NOT the global is_coach flag. A Premier
        # player coaching a Classic team gets CLASSIC-COACH only.
        for team in all_teams:
            if not team.get('is_coach'):
                continue
            coached_league = (team.get('league_name') or '').strip().lower()
            if coached_league == 'premier':
                _add('ECS-FC-PL-PREMIER-COACH')
            elif coached_league == 'classic':
                _add('ECS-FC-PL-CLASSIC-COACH')
            elif coached_league == 'ecs fc':
                _add('ECS-FC-PL-ECS-FC-COACH')

        if data.get('is_ref'):
            _add('Referee')

    # Approval gate: only APPROVED users keep app-managed league/team/coach/sub/
    # referee roles. Pending or denied users get an empty expected set, so a
    # reconcile strips those managed roles and no path ever grants them.
    #
    # FAIL-OPEN, deliberately: the gate fires ONLY on an explicit 'pending'/'denied'.
    # NULL, empty, or an unrecognised value is treated as approved. Two traps make
    # that necessary — `getattr(user, 'approval_status', 'approved')` returns None for
    # a NULL column (the default only covers a MISSING attribute), and
    # `dict.get(k, default)` then hands back that None instead of the default. So one
    # NULL row would empty this list. That used to be survivable, because the reconcile
    # allowlist blocks team/division/coach removal — but the explicit revoke path
    # bypasses the allowlist, where an empty expected set costs the player real roles.
    # An unknown status must never revoke.
    status = data.get('approval_status') or 'approved'
    if isinstance(status, str) and status.strip().lower() in ('pending', 'denied'):
        return []

    return expected


def _app_managed_roles(data: Dict[str, Any], teams: Optional[List[Dict]] = None,
                       include_global: bool = True) -> List[str]:
    """Roles this app is allowed to revoke for a player.

    ECS-FC-PL-ECS-FC and ECS-FC-PL-ECS-FC-COACH are intentionally absent: the ECS FC
    league/coach roles are add-only and never stripped by a reconcile.

    `teams` and `include_global` MUST mirror the matching _compute_expected_roles
    call. A scoped grant (include_global=False) produces expected roles for one team
    only, so the managed list has to shrink with it — otherwise the division, sub and
    referee roles would be "managed but not expected" and a reconcile in that mode
    would revoke the player's entire non-team footprint.
    """
    if teams is None:
        teams = data.get('teams') or []
    managed = [
        'ECS-FC-PL-PREMIER',
        'ECS-FC-PL-CLASSIC',
        'ECS-FC-PL-PREMIER-COACH',
        'ECS-FC-PL-CLASSIC-COACH',
        'ECS-FC-PL-PREMIER-SUB',
        'ECS-FC-PL-CLASSIC-SUB',
        'ECS-FC-LEAGUE-SUB',
        'Referee',
    ] if include_global else []
    # Team-specific player + coach roles, so losing a roster spot / coach status
    # still revokes them.
    for team in teams:
        if not team:
            continue
        managed.append(f"ECS-FC-PL-{normalize_name(team['name'])}-Player")
        managed.append(f"ECS-FC-PL-{normalize_name(team['name'])}-Coach")
    return managed


# Every non-team role name the calculators can emit. A revoke candidate outside this
# vocabulary (or the ECS-FC-PL-<team>-Player/-Coach pattern) is IGNORED: callers derive
# candidates from mapping tables that also contain match-only aliases, and a name no
# calculator produces can never appear in the expected set — so it would be revoked
# unconditionally, which is exactly how you strip a Discord role the app doesn't own.
_REVOCABLE_ROLE_VOCABULARY = {
    'ECS-FC-PL-PREMIER',
    'ECS-FC-PL-CLASSIC',
    'ECS-FC-PL-ECS-FC',
    'ECS-FC-PL-PREMIER-COACH',
    'ECS-FC-PL-CLASSIC-COACH',
    'ECS-FC-PL-ECS-FC-COACH',
    'ECS-FC-PL-PREMIER-SUB',
    'ECS-FC-PL-CLASSIC-SUB',
    'ECS-FC-LEAGUE-SUB',
    'ECS-FC-PL-UNVERIFIED',
    'REFEREE',
}


def _is_revocable_candidate(role_name: str) -> bool:
    """True if `role_name` is a role the calculators can produce (see vocabulary)."""
    up = normalize_name(role_name or '')
    if up in _REVOCABLE_ROLE_VOCABULARY:
        return True
    # Per-team roles are dynamic, so match them structurally.
    return up.startswith('ECS-FC-PL-') and (up.endswith('-PLAYER') or up.endswith('-COACH'))


def _roles_in_sync(current_roles, expected_roles) -> bool:
    """Is the member's Discord state consistent with the expected set?

    Compares only roles the app actually owns (_is_revocable_candidate), and only in
    the directions that matter: a missing expected role, or a lingering app-owned role
    that is no longer expected. Roles outside the app's vocabulary are ignored, so an
    unrelated ECS-FC-PL-* role on the server can't peg every player to "Out of Sync".
    """
    current = {normalize_name(r) for r in (current_roles or [])
               if _is_revocable_candidate(r)}
    expected = {normalize_name(r) for r in (expected_roles or [])
                if _is_revocable_candidate(r)}
    return current == expected


def _extract_player_role_data(session, player_id: int):
    """Extract player data for Discord role update."""
    try:
        player = session.query(Player).options(joinedload(Player.user)).get(player_id)
        if not player:
            raise ValueError(f"Player {player_id} not found")
    except SQLAlchemyError as e:
        logger.error(f"Database error in _extract_player_role_data: {e}")
        raise
    
    # Get all required data from database while session is available
    try:
        # Extract the basic player data and calculate roles in async phase
        # Use helper function to get only current season teams
        teams = get_current_season_teams(session, player)
        
        # Get Flask user roles for division role assignment
        user_roles = []
        try:
            if player.user:
                # Safely load roles with a separate query to avoid joinedload issues
                user_with_roles = session.query(User).options(joinedload(User.roles)).filter_by(id=player.user.id).first()
                if user_with_roles and user_with_roles.roles:
                    user_roles = [role.name for role in user_with_roles.roles]
        except SQLAlchemyError as e:
            logger.warning(f"Could not load user roles for player {player.id}: {e}")
            user_roles = []
        
        # Get league information for division role assignment
        league_names = []
        if player.league and player.league.name:
            league_names.append(player.league.name)
        if player.primary_league and player.primary_league.name:
            league_names.append(player.primary_league.name)
        for league in player.other_leagues:
            if league.name:
                league_names.append(league.name)
        
        # Approval status gates league-role assignment (pending/denied users get
        # no managed roles). Default to 'approved' when there is no linked user so
        # we never strip roles on genuinely-missing data — the gate only bites on
        # an EXPLICIT 'pending'/'denied'. (DB: users.approval_status NOT NULL.)
        approval_status = (getattr(player.user, 'approval_status', None) or 'approved') if player.user else 'approved'

        return {
            'player_id': player_id,
            'discord_id': player.discord_id,
            'name': player.name,
            'is_active': player.is_current_player,
            'is_coach': player.is_coach,
            'is_ref': player.is_ref,
            'approval_status': approval_status,
            'current_roles': player.discord_roles or [],
            'teams': teams,
            'user_roles': user_roles,
            'league_names': list(set(league_names)),  # Remove duplicates
            'force_update': False
        }
    except Exception as e:
        logger.error(f"Error extracting player data: {e}")
        raise


async def _execute_player_role_update_async(data):
    """Execute Discord role update without database session.

    Full-player reconcile: expected roles and the managed list both cover the
    player's WHOLE current-season footprint, so the pattern sweep is safe here.
    """
    expected_roles = _compute_expected_roles(data)
    app_managed_roles = _app_managed_roles(data)

    # Prepare data for async-only function
    player_data = {
        'id': data['player_id'],
        'name': data['name'],
        'discord_id': data['discord_id'],
        'current_roles': data.get('current_roles', []),
        'expected_roles': expected_roles,
        'app_managed_roles': app_managed_roles
    }

    # Perform the async Discord operations
    from app.discord_utils import update_player_roles_async_only
    result = await update_player_roles_async_only(
        player_data, force_update=data.get('force_update', False),
        enforce_allowlist=data.get('enforce_allowlist', True))

    # Return result with data needed for database update
    return {
        'success': result.get('success', False),
        'message': result.get('message', result.get('error', '')),
        'current_roles': result.get('current_roles', []),
        'roles_added': result.get('roles_added', []),
        'roles_removed': result.get('roles_removed', []),
        'player_id': data['player_id'],
        'sync_status': 'success' if result.get('success') else 'mismatch'
    }


def _update_player_after_role_sync(session, result):
    """Update player record after async role sync completes."""
    if not result.get('success'):
        return result
    
    player = session.query(Player).get(result['player_id'])
    if player:
        player.discord_roles = result.get('current_roles', [])
        player.discord_last_verified = datetime.utcnow()
        player.discord_needs_update = False
        player.last_sync_attempt = datetime.utcnow()
        player.sync_status = result.get('sync_status', 'success')
    
    return result


@celery_task(
    name='app.tasks.tasks_discord.update_player_discord_roles',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True
)
async def update_player_discord_roles(self, session, player_id: int) -> Dict[str, Any]:
    """
    Update Discord roles for a single player using two-phase pattern.
    
    Phase 1: Extract player data from database
    Phase 2: Update Discord roles via API (async, no DB session)
    Phase 3: Update player record with results
    
    Args:
        session: Database session (used only in phase 1).
        player_id: ID of the player to update.
        
    Returns:
        A dictionary with the update result.
    """
    try:
        # This task will be handled by the decorator's two-phase pattern
        # but also needs a final database update, so we handle that specially
        pass
    except SQLAlchemyError as e:
        logger.error(f"Database error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error(f"Error updating Discord roles for player {player_id}: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=30)


# This task needs special handling since it requires a final DB update
# We'll mark it with a special flag and handle it in the decorator
update_player_discord_roles._extract_data = _extract_player_role_data
update_player_discord_roles._execute_async = _execute_player_role_update_async
update_player_discord_roles._two_phase = True
update_player_discord_roles._requires_final_db_update = True
update_player_discord_roles._final_db_update = _update_player_after_role_sync


async def _update_player_discord_roles_async(session, player_id: int) -> Dict[str, Any]:
    """
    Async helper to update a player's Discord roles.
    
    Args:
        session: Database session.
        player_id: ID of the player.
        
    Returns:
        A dictionary with success status and role details.
    """
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        logger.error(f"No Discord ID or player not found for player_id {player_id}")
        return {'success': False, 'message': 'No Discord ID associated with player'}

    try:
        async with aiohttp.ClientSession() as aio_session:
            current_roles = await fetch_user_roles(session, player.discord_id, aio_session)
            expected_roles = await get_expected_roles(session, player)
            await process_single_player_update(session, player)
            final_roles = await fetch_user_roles(session, player.discord_id, aio_session)

        roles_match = set(final_roles) == set(expected_roles)
        status_html = get_status_html(roles_match)

        result = {
            'success': True,
            'player_data': {
                'id': player.id,
                'current_roles': final_roles,
                'expected_roles': expected_roles,
                'status_html': status_html,
                'last_verified': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'roles_match': roles_match
            }
        }

        logger.info(f"Successfully updated Discord roles for player {player.id}", extra={
            'roles_match': roles_match,
            'current_roles': final_roles,
            'expected_roles': expected_roles
        })
        return result

    except aiohttp.ClientError as e:
        logger.error(f"Discord API error for player {player_id}: {str(e)}", exc_info=True)
        return {'success': False, 'message': 'Discord API error', 'error': str(e)}


def _extract_batch_role_update_data(session, discord_ids: List[str] = None, only_add: bool = False,
                                    enforce_allowlist: bool = True):
    """Extract player data for batch Discord role updates using optimized batch processing.

    only_add=True downgrades the batch from a full reconcile (add + remove) to
    add-only. Repair-style callers ("Assign Roles" on a team page) want to GRANT
    missing roles, not revoke; a reconcile there means one bad expected-role
    calculation strips the whole roster's Discord access. Removal callers
    (rollover cleanup, sub-pool removal, nightly sync) keep the default reconcile.

    enforce_allowlist=False lets an INTENDED bulk removal (season rollover clearing old
    team/coach roles) strip roles the drift-guard allowlist normally protects. Safe for
    rollover because the batch uses one authoritative calculator and a rolled-over player's
    expected set is minimal. Default True everywhere else keeps the wipe protection.
    """
    try:
        if not discord_ids:
            # No-arg callers — the admin "Sync All Roles" buttons mark all
            # out-of-sync players discord_needs_update=True then dispatch
            # process_discord_role_updates.delay() with no ids. Previously this
            # raised TypeError (required positional) and silently no-op'd while
            # reporting success. Load the flagged players so the reconcile runs.
            discord_ids = [
                str(p.discord_id) for p in session.query(Player).filter(
                    Player.discord_id.isnot(None),
                    Player.discord_needs_update == True  # noqa: E712 (SQLAlchemy)
                ).all()
            ]
        if not discord_ids:
            return {'players': []}
        # Use optimized batch processing from query optimizer
        players_data = efficient_player_discord_batch(session, discord_ids)

        # efficient_player_discord_batch defaults every player to force_update=True
        # (full reconcile). Add-only callers flip it off here.
        if only_add:
            for pdata in players_data:
                pdata['force_update'] = False
        if not enforce_allowlist:
            for pdata in players_data:
                pdata['enforce_allowlist'] = False

        logger.info(
            f"Extracted batch role update data for {len(players_data)} players from "
            f"{len(discord_ids)} Discord IDs using optimized processing "
            f"(mode={'add-only' if only_add else 'reconcile'})"
        )
        return {'players': players_data}
        
    except SQLAlchemyError as e:
        logger.error(f"Database error in _extract_batch_role_update_data: {e}", exc_info=True)
        raise


async def _execute_batch_role_update_async(data):
    """Execute batch Discord role updates without database session."""
    players_data = data['players']
    results = []
    
    # Process each player
    for player_data in players_data:
        try:
            # Use the same logic as single player update
            result = await _execute_player_role_update_async(player_data)
            results.append({
                'id': player_data['id'],
                'discord_id': player_data['discord_id'],
                'status': 'synced' if result.get('success') else 'error',
                'success': result.get('success', False),
                'error': result.get('message', '') if not result.get('success') else None,
                'current_roles': result.get('current_roles', []),
                'roles_added': result.get('roles_added', []),
                'roles_removed': result.get('roles_removed', [])
            })
        except Exception as e:
            logger.error(f"Error processing player {player_data.get('name', 'unknown')}: {e}")
            results.append({
                'id': player_data['id'],
                'discord_id': player_data['discord_id'],
                'status': 'error',
                'success': False,
                'error': str(e)
            })
    
    return {
        'success': True,
        'results': results,
        'processed_count': len([r for r in results if r.get('status') == 'synced']),
        'error_count': len([r for r in results if r.get('status') != 'synced'])
    }


def _update_players_after_batch_role_sync(session, result):
    """Update player records after batch role sync completes."""
    if not result.get('success'):
        return result
    
    # Update each player's sync info based on the results
    for player_result in result.get('results', []):
        player = session.query(Player).get(player_result['id'])
        if player:
            player.discord_last_verified = datetime.utcnow()
            player.discord_needs_update = False
            player.last_sync_attempt = datetime.utcnow()
            player.sync_status = 'success' if player_result.get('status') == 'synced' else 'error'
            if not player_result.get('success'):
                player.sync_error = player_result.get('error')
            if player_result.get('current_roles'):
                player.discord_roles = player_result['current_roles']
    
    return result


@celery_task(
    name='app.tasks.tasks_discord.process_discord_role_updates',
    queue='discord'
)
async def process_discord_role_updates(self, session, discord_ids: List[str] = None,
                                       only_add: bool = False,
                                       enforce_allowlist: bool = True) -> Dict[str, Any]:
    """
    Process Discord role updates for multiple players using two-phase pattern.

    Args:
        session: Database session (used only in phase 1).
        discord_ids: List of Discord IDs to process.
        only_add: If True, only grant missing roles and never revoke. Use for
            repair/"assign" callers. Default False = full reconcile (add + remove).
        enforce_allowlist: Default True keeps the drift-guard allowlist (a reconcile can
            only strip sub/unverified roles). Pass False ONLY for an intended bulk removal
            like SEASON ROLLOVER clearing old team/coach roles — safe there because a
            rolled-over player's expected set is minimal and one authoritative calculator
            is used, so there's no inter-calculator drift to cause a wipe.

    Returns:
        A summary dictionary with counts and details of the processed results.
    """
    pass


# Attach phase methods
process_discord_role_updates._extract_data = _extract_batch_role_update_data
process_discord_role_updates._execute_async = _execute_batch_role_update_async
process_discord_role_updates._two_phase = True
process_discord_role_updates._requires_final_db_update = True
process_discord_role_updates._final_db_update = _update_players_after_batch_role_sync


def _extract_assign_roles_data(session, player_id: int, team_id: Optional[int] = None, only_add: bool = True):
    """Extract player data for role assignment."""
    player = session.query(Player).get(player_id)
    if not player:
        raise ValueError(f"Player {player_id} not found")
    
    # Get all player teams (current season only)
    teams = get_current_season_teams(session, player)

    # Get team info if specific team provided. is_coach is carried over from the
    # current-season list so a SCOPED grant still produces the team's -Coach role
    # for someone who actually coaches it (the scoped path can't re-derive it).
    target_team = None
    if team_id:
        team_row = session.query(Team).get(team_id)
        if team_row:
            target_team = {
                'id': team_row.id,
                'name': team_row.name,
                'league_name': team_row.league.name if team_row.league else None,
                'is_coach': next((t.get('is_coach', False) for t in teams
                                  if t.get('id') == team_row.id), False),
            }

    # Get Flask user roles for division role assignment
    user_roles = []
    if player.user and player.user.roles:
        user_roles = [role.name for role in player.user.roles]

    # League associations feed the shared calculator's Priority-2 division fallback.
    # This path used to omit them entirely, so it granted a division role only from
    # the pl-<division> Flask role while the reconcile also derived it from the DB
    # league — a divergence that made the division role flap between the two paths.
    league_names = []
    if player.league and player.league.name:
        league_names.append(player.league.name)
    if player.primary_league and player.primary_league.name:
        league_names.append(player.primary_league.name)
    for league in player.other_leagues:
        if league.name:
            league_names.append(league.name)

    # Approval gate input (see _compute_expected_roles). Default 'approved'
    # when there is no linked user so missing data never strips.
    approval_status = (getattr(player.user, 'approval_status', None) or 'approved') if player.user else 'approved'

    return {
        'player_id': player_id,
        'discord_id': player.discord_id,
        'name': player.name,
        'is_active': player.is_current_player,
        'is_coach': player.is_coach,
        'is_ref': player.is_ref,
        'approval_status': approval_status,
        'current_roles': player.discord_roles or [],
        'teams': teams,
        'user_roles': user_roles,
        'league_names': list(set(league_names)),
        'target_team': target_team,
        'only_add': only_add
    }


async def _execute_assign_roles_async(data):
    """Execute role assignment without database session.

    Two modes:
      * target_team set  -> SCOPED grant. Expected roles, the managed list and the
        pattern sweep are ALL narrowed to that one team, so a reconcile in this mode
        can only ever touch that team's roles. Previously only expected_roles was
        narrowed while the managed list still named every division/sub/referee role
        and the sweep was on, so an only_add=False call in this mode would have
        stripped the player's entire Discord footprint.
      * target_team None -> full-player grant/reconcile, identical to
        _execute_player_role_update_async (same shared calculator).
    """
    target_team = data.get('target_team')
    player_id = data.get('player_id')

    logger.info(f"[DEBUG] Player {player_id}: _execute_assign_roles_async called")
    logger.info(f"[DEBUG] Player {player_id}: target_team={target_team}")

    if target_team:
        scoped_teams = [target_team]
        expected_roles = _compute_expected_roles(data, teams=scoped_teams,
                                                 include_global=False)
        app_managed = _app_managed_roles(data, teams=scoped_teams,
                                         include_global=False)
        pattern_sweep = False
    else:
        expected_roles = _compute_expected_roles(data)
        app_managed = _app_managed_roles(data)
        pattern_sweep = True

    logger.info(f"[DEBUG] Player {player_id}: expected_roles={expected_roles}")

    player_data = {
        'id': data['player_id'],
        'name': data['name'],
        'discord_id': data['discord_id'],
        'current_roles': data.get('current_roles', []),
        'expected_roles': expected_roles,
        'app_managed_roles': app_managed,
    }

    # Execute role assignment
    from app.discord_utils import update_player_roles_async_only
    only_add_value = data.get('only_add', True)
    force_update_value = not only_add_value
    logger.info(f"Task parameters: only_add={only_add_value}, force_update={force_update_value}, "
                f"pattern_sweep={pattern_sweep}")
    result = await update_player_roles_async_only(
        player_data, force_update=force_update_value, pattern_sweep=pattern_sweep)

    return {
        'success': result.get('success', False),
        'message': result.get('message', result.get('error', '')),
        'current_roles': result.get('current_roles', []),
        'roles_added': result.get('roles_added', []),
        'roles_removed': result.get('roles_removed', []),
        'player_id': data['player_id'],
        'timestamp': datetime.utcnow().isoformat()
    }


def _update_player_after_assign_roles(session, result):
    """Update player record after role assignment."""
    if not result.get('success'):
        return result
    
    player = session.query(Player).get(result['player_id'])
    if player:
        player.discord_roles_updated = datetime.utcnow()
        if result.get('success'):
            player.discord_role_sync_status = 'completed'
        else:
            player.discord_role_sync_status = 'failed'
            player.sync_error = result.get('message')
        player.last_sync_attempt = datetime.utcnow()
        if result.get('current_roles'):
            player.discord_roles = result['current_roles']
    
    return result


@celery_task(
    name='app.tasks.tasks_discord.assign_roles_to_player_task',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True,
    rate_limit='50/s',
    ignore_result=True  # fire-and-forget role sync: don't accumulate result keys in Redis
)
async def assign_roles_to_player_task(self, session, player_id: int, team_id: Optional[int] = None, only_add: bool = True) -> Dict[str, Any]:
    """
    Assign or update Discord roles for a player using two-phase pattern.
    
    Args:
        session: Database session (used only in phase 1).
        player_id: ID of the player.
        team_id: Optional team ID to scope role assignment.
        only_add: If True, only add roles; if False, remove roles not in the expected set.
        
    Returns:
        A dictionary with success status and details of the role assignment.
    """
    pass


# Attach phase methods
assign_roles_to_player_task._extract_data = _extract_assign_roles_data
assign_roles_to_player_task._execute_async = _execute_assign_roles_async
assign_roles_to_player_task._requires_final_db_update = True
assign_roles_to_player_task._final_db_update = _update_player_after_assign_roles
assign_roles_to_player_task._two_phase = True


async def _assign_roles_async(session, player_id: int, team_id: Optional[int], only_add: bool) -> Dict[str, Any]:
    """
    Async helper to assign roles to a player via Discord API.
    
    Args:
        session: Database session.
        player_id: ID of the player.
        team_id: Optional team ID to determine specific role.
        only_add: Whether to only add roles.
        
    Returns:
        A dictionary with success status.
    """
    logger.info(f"==> Entering _assign_roles_async for player_id={player_id}, team_id={team_id}, only_add={only_add}")
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        logger.warning("No Discord ID or missing player.")
        return {'success': False, 'message': 'No Discord ID'}

    try:
        async with aiohttp.ClientSession() as aio_session:
            if team_id:
                team = session.query(Team).get(team_id)
                role_name = f"ECS-FC-PL-{normalize_name(team.name)}-Player"
                league_role_name = f"ECS-FC-PL-{team.league.name}"
                guild_id = Config.SERVER_ID

                # Retrieve role IDs and assign roles via the Discord API.
                role_id = await get_role_id(guild_id, role_name, aio_session)
                league_role_id = await get_role_id(guild_id, league_role_name, aio_session)

                if role_id:
                    await make_discord_request(
                        method='PUT',
                        url=f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{player.discord_id}/roles/{role_id}",
                        session=aio_session
                    )
                if league_role_id:
                    await make_discord_request(
                        method='PUT',
                        url=f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{player.discord_id}/roles/{league_role_id}",
                        session=aio_session
                    )
                return {'success': True}

            # Process role update for the player without team-specific roles.
            logger.debug(f"No team_id specified, calling process_single_player_update(only_add={only_add})")
            return await process_single_player_update(session, player, only_add=only_add)

    except Exception as e:
        logger.error(f"Exception assigning roles: {e}", exc_info=True)
        return {'success': False, 'message': str(e)}


def _extract_fetch_role_status_data(session):
    """Extract player data for role status fetching using optimized streaming."""
    try:
        # Use memory-efficient streaming from query optimizer
        all_players_data = []
        
        with memory_efficient_session(session, BatchConfig(batch_size=100)) as efficient_session:
            for batch_data in stream_players_with_discord_ids(efficient_session, batch_size=100):
                all_players_data.extend(batch_data)
        
        logger.info(f"Successfully processed {len(all_players_data)} players using optimized streaming")
        return {'players': all_players_data}
        
    except SQLAlchemyError as e:
        logger.error(f"Database error in _extract_fetch_role_status_data: {e}", exc_info=True)
        raise


async def _execute_fetch_role_status_async(data):
    """Execute role status fetching without database session."""
    players_data = data['players']
    results = []
    status_updates = []
    
    # Fetch roles for each player (simplified version of _fetch_roles_batch)
    async with aiohttp.ClientSession() as session:
        for player_data in players_data:
            try:
                # Get current roles from Discord
                roles = await get_member_roles(player_data['discord_id'], session)
                
                # Create result data
                teams_str = ", ".join(t['name'] for t in player_data['teams']) if player_data['teams'] else "No Team"
                leagues_str = ", ".join(sorted({t['league_name'] for t in player_data['teams'] if t['league_name']})) if player_data['teams'] else "No League"
                
                results.append({
                    'id': player_data['id'],
                    'name': player_data['name'],
                    'team': teams_str,
                    'league': leagues_str,
                    'current_roles': roles or [],
                    'expected_roles': [],  # Simplified for now
                    'status_html': '<span class="badge badge-success">Synced</span>',
                    'last_verified': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                    'roles_match': True
                })
                
                status_updates.append({
                    'id': player_data['id'],
                    'status': 'synced',
                    'current_roles': roles or []
                })
                
            except Exception as e:
                logger.error(f"Error fetching roles for player {player_data['name']}: {e}")
                results.append({
                    'id': player_data['id'],
                    'name': player_data['name'],
                    'team': "Error",
                    'league': "Error",
                    'error': str(e)
                })
                status_updates.append({
                    'id': player_data['id'],
                    'status': 'error',
                    'error': str(e)
                })
    
    return {
        'success': True,
        'role_results': results,
        'status_updates': status_updates,
        'fetched_at': datetime.utcnow().isoformat()
    }


def _update_players_after_fetch_role_status(session, result):
    """Update player records after role status fetch."""
    if not result.get('success'):
        return result
    
    # Update players with the latest role sync status
    for status in result.get('status_updates', []):
        player = session.query(Player).get(status['id'])
        if player:
            player.discord_role_sync_status = status['status']
            player.last_role_check = datetime.utcnow()
            if 'current_roles' in status:
                player.discord_roles = status['current_roles']
            if 'error' in status:
                player.sync_error = status['error']
    
    # Emit updated role status to clients
    try:
        from app import socketio
        socketio.emit('role_status_update', {
            'results': result['role_results'],
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.warning(f"Failed to emit socket event: {e}")
    
    return {
        'success': True,
        'results': result['role_results'],
        'fetched_at': result['fetched_at']
    }


@celery_task(name='app.tasks.tasks_discord.fetch_role_status', queue='discord')
async def fetch_role_status(self, session) -> Dict[str, Any]:
    """
    Fetch and update role status for players with a Discord ID using two-phase pattern.
    
    Args:
        session: Database session (used only in phase 1).
        
    Returns:
        A dictionary with success status, results, and timestamp.
    """
    pass


# Attach phase methods
fetch_role_status._extract_data = _extract_fetch_role_status_data
fetch_role_status._execute_async = _execute_fetch_role_status_async
fetch_role_status._two_phase = True
fetch_role_status._requires_final_db_update = True
fetch_role_status._final_db_update = _update_players_after_fetch_role_status


def process_role_results(session, players: List[Player], role_results: List[Dict]) -> Dict[str, Any]:
    """
    Process role results from Discord API and update player records.

    UNUSED / DO NOT WIRE UP AS-IS. It has no callers, and its expected-role step is
    still the placeholder stub below (`expected_roles = []`), so every player with any
    Discord role is reported 'mismatch'. Since a mismatch verdict sets
    discord_needs_update, and the no-arg process_discord_role_updates reconciles
    everything flagged that way, calling this would schedule a guild-wide reconcile.
    Use _compute_expected_roles + _roles_in_sync (as _fetch_roles_batch does) if this
    is ever revived.

    Args:
        session: Database session.
        players: List of Player objects.
        role_results: List of dictionaries with role status data.

    Returns:
        A dictionary with status updates and formatted role result data.
    """
    status_updates = []
    updated_role_results = []

    for player, result in zip(players, role_results):
        try:
            if isinstance(result, dict) and 'error' in result:
                status_updates.append({
                    'id': player.id,
                    'status': 'error',
                    'error': result['error']
                })
                updated_role_results.append(create_error_result({
                    'id': player.id,
                    'name': player.name,
                    'team': "No Team",
                    'league': "No League",
                }))
                continue

            current_roles = result.get('roles', [])
            teams_str = ", ".join(t.name for t in player.teams) if player.teams else "No Team"
            leagues_str = ", ".join(sorted({t.league.name for t in player.teams if t.league})) if player.teams else "No League"

            # In this example, expected_roles is an empty list; adjust as needed.
            expected_roles = []
            roles_match = set(current_roles) == set(expected_roles)

            status_updates.append({
                'id': player.id,
                'status': 'synced' if roles_match else 'mismatch',
                'current_roles': current_roles
            })

            updated_role_results.append({
                'id': player.id,
                'name': player.name,
                'team': teams_str,
                'league': leagues_str,
                'current_roles': current_roles,
                'expected_roles': expected_roles,
                'status_html': get_status_html(roles_match),
                'last_verified': datetime.utcnow().isoformat()
            })

        except Exception as e:
            logger.error(f"Error processing player {player.id}: {str(e)}")
            status_updates.append({
                'id': player.id,
                'status': 'error',
                'error': str(e)
            })
            updated_role_results.append(create_error_result({
                'id': player.id,
                'name': player.name,
                'team': "No Team",
                'league': "No League"
            }))

    return {
        'status_updates': status_updates,
        'role_results': updated_role_results
    }


async def _fetch_roles_batch(session, players: List[Player]) -> Dict[str, Any]:
    """
    Async helper to fetch Discord roles for a batch of players.
    
    Args:
        session: Database session.
        players: List of Player objects.
        
    Returns:
        A dictionary containing status updates and detailed role results.
    """
    status_updates = []
    role_results = []

    async with aiohttp.ClientSession() as aio_session:
        for player in players:
            try:
                current_roles = await fetch_user_roles(session, player.discord_id, aio_session)
                # Filter roles managed by our system.
                managed_prefixes = ["ECS-FC-PL-", "Referee"]
                managed_current = {r for r in current_roles if any(r.startswith(p) for p in managed_prefixes)}
                
                # Compute expected roles based on team and league data.
                # Same calculator the sync paths use. This block used to compute its
                # own expected set from player.teams + the GLOBAL is_coach flag, with
                # no ECS FC handling, no sub roles, no per-team coach roles and no
                # approval gate — so correctly-synced players (every ECS FC player,
                # every sub, every coach) were reported "Out of Sync" forever. That is
                # not cosmetic: the verdict below writes discord_needs_update, and the
                # no-arg process_discord_role_updates picks those players up, so a
                # wrong verdict here generated endless real Discord churn.
                expected_roles = set(_compute_expected_roles(
                    _extract_player_role_data(session, player.id)))

                # Compare only within the app's own vocabulary. An exact set equality
                # against every ECS-FC-PL-* role the member holds also flagged roles
                # the app deliberately does not manage.
                roles_match = _roles_in_sync(managed_current, expected_roles)
                status_html = get_status_html(roles_match)

                teams_str = ", ".join(t.name for t in player.teams) if player.teams else "No Team"
                leagues_str = ", ".join(sorted({t.league.name for t in player.teams if t.league})) if player.teams else "No League"

                status_updates.append({
                    'id': player.id,
                    'status': 'synced' if roles_match else 'mismatch',
                    'current_roles': list(current_roles)
                })

                role_results.append({
                    'id': player.id,
                    'name': player.name,
                    'team': teams_str,
                    'league': leagues_str,
                    'current_roles': list(current_roles),
                    'expected_roles': list(expected_roles),
                    'status_html': status_html,
                    'last_verified': datetime.utcnow().isoformat()
                })

            except Exception as e:
                logger.error(f"Error fetching roles for player {player.id}: {str(e)}")
                status_updates.append({'id': player.id, 'status': 'error', 'error': str(e)})
                role_results.append(create_error_result({
                    'id': player.id,
                    'name': player.name,
                    'team': "No Team",
                    'league': "No League"
                }))

    return {
        'status_updates': status_updates,
        'role_results': role_results
    }


async def _fetch_role_status_async(session, player_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Async helper to fetch role status for given player data.
    
    Args:
        session: Database session.
        player_data: List of dictionaries containing player IDs and names.
        
    Returns:
        A list of role status dictionaries.
    """
    results = []
    status_updates = []

    async with aiohttp.ClientSession() as aio_session:
        for p_info in player_data:
            try:
                player = session.query(Player).get(p_info['id'])
                if not player:
                    continue

                current_roles = await fetch_user_roles(session, player.discord_id, aio_session)
                managed_prefixes = ["ECS-FC-PL-", "Referee"]
                managed_current = {r for r in current_roles if any(r.startswith(p) for p in managed_prefixes)}

                # Same calculator the sync paths use. This block used to compute its
                # own expected set from player.teams + the GLOBAL is_coach flag, with
                # no ECS FC handling, no sub roles, no per-team coach roles and no
                # approval gate — so correctly-synced players (every ECS FC player,
                # every sub, every coach) were reported "Out of Sync" forever. That is
                # not cosmetic: the verdict below writes discord_needs_update, and the
                # no-arg process_discord_role_updates picks those players up, so a
                # wrong verdict here generated endless real Discord churn.
                expected_roles = set(_compute_expected_roles(
                    _extract_player_role_data(session, player.id)))

                # Compare only within the app's own vocabulary. An exact set equality
                # against every ECS-FC-PL-* role the member holds also flagged roles
                # the app deliberately does not manage.
                roles_match = _roles_in_sync(managed_current, expected_roles)
                status_html = get_status_html(roles_match)

                teams_str = ", ".join(t.name for t in player.teams) if player.teams else "No Team"
                leagues_str = ", ".join(sorted({t.league.name for t in player.teams if t.league})) if player.teams else "No League"

                status_updates.append({
                    'id': p_info['id'],
                    'status': 'synced' if roles_match else 'mismatch',
                    'current_roles': list(current_roles)
                })

                results.append({
                    'id': p_info['id'],
                    'name': p_info['name'],
                    'team': teams_str,
                    'league': leagues_str,
                    'current_roles': list(current_roles),
                    'expected_roles': list(expected_roles),
                    'status_html': status_html,
                    'last_verified': datetime.utcnow().isoformat()
                })

            except Exception as e:
                logger.error(f"Error processing player {p_info['id']}: {str(e)}")
                results.append(create_error_result(p_info))

    # Update players' role sync info
    for update in status_updates:
        player = session.query(Player).get(update['id'])
        if player:
            player.discord_role_sync_status = update['status']
            player.last_role_check = datetime.utcnow()
            if 'current_roles' in update:
                player.discord_roles = update['current_roles']
            if 'error' in update:
                player.sync_error = update['error']
    session.flush()

    socketio.emit('role_status_update', {
        'results': results,
        'timestamp': datetime.utcnow().isoformat()
    })

    status_counts = {
        'total': len(results),
        'synced': sum(1 for r in status_updates if r['status'] == 'synced'),
        'mismatch': sum(1 for r in status_updates if r['status'] == 'mismatch'),
        'error': sum(1 for r in status_updates if r['status'] == 'error')
    }

    logger.info("Role status check completed", extra={
        'stats': status_counts,
        'timestamp': datetime.utcnow().isoformat()
    })

    return results


def _extract_remove_roles_data(session, player_id: int, team_id: Optional[int] = None):
    """Extract player data for role removal.

    When team_id is provided, only roles scoped to that team are removed.
    When team_id is None, all of the player's team-scoped roles across their
    current-season teams are removed (used for user denial/deactivation flows).
    """
    try:
        # OPTIMIZED: Load minimal player data, avoid nested joinedloads
        player = session.query(Player).options(
            selectinload(Player.user).selectinload(User.roles)
        ).get(player_id)
    except SQLAlchemyError as e:
        logger.error(f"Database error in _extract_remove_roles_data: {e}")
        raise
    if not player:
        raise ValueError(f"Player {player_id} not found")

    target_teams = []
    if team_id is not None:
        target_team = session.query(Team).options(
            joinedload(Team.league)
        ).get(team_id)
        if not target_team:
            raise ValueError(f"Team {team_id} not found")
        target_teams.append({
            'id': target_team.id,
            'name': target_team.name,
            'league_name': target_team.league.name if target_team.league else None
        })
    else:
        # Remove roles across all of the player's current-season teams
        target_teams = get_current_season_teams(session, player)
        # Also include any other teams the player is associated with to catch stale roles
        for team in player.teams:
            entry = {
                'id': team.id,
                'name': team.name,
                'league_name': team.league.name if team.league else None
            }
            if not any(t['id'] == entry['id'] for t in target_teams):
                target_teams.append(entry)

    # Get Flask user roles for division role assignment
    user_roles = []
    try:
        if player.user and player.user.roles:
            user_roles = [role.name for role in player.user.roles]
    except Exception as e:
        logger.warning(f"Could not load user roles for player {player.id}: {e}")
        user_roles = []

    return {
        'player_id': player_id,
        'team_id': team_id,
        'discord_id': player.discord_id,
        'name': player.name,
        'current_roles': player.discord_roles or [],
        'user_roles': user_roles,
        'target_teams': target_teams,
    }


async def _execute_remove_roles_async(data):
    """Execute role removal without database session."""
    target_teams = data.get('target_teams', [])

    # Calculate roles to remove across all target teams
    roles_to_remove = []
    for team in target_teams:
        if team and team.get('league_name') in ['Premier', 'Classic', 'ECS FC']:
            roles_to_remove.append(f"ECS-FC-PL-{normalize_name(team['name'])}-Player")
            roles_to_remove.append(f"ECS-FC-PL-{normalize_name(team['name'])}-Coach")

    # Full offboarding (team_id is None: deny / deactivate / set-pending) must ALSO
    # strip division, sub, division-coach, and referee roles. Without this the user
    # keeps division-wide, sub-pool, and referee CHANNEL ACCESS after being removed,
    # because the team-scoped list above never contains those (they have no team
    # name and Referee has no ECS-FC-PL- prefix). Targeted removals (team_id set,
    # e.g. draft-remove) intentionally stay scoped to the one team.
    if data.get('team_id') is None:
        roles_to_remove.extend([
            'ECS-FC-PL-PREMIER',
            'ECS-FC-PL-CLASSIC',
            'ECS-FC-PL-ECS-FC',  # ECS FC league role — same leak as the two above
            'ECS-FC-PL-PREMIER-SUB',
            'ECS-FC-PL-CLASSIC-SUB',
            'ECS-FC-LEAGUE-SUB',
            'ECS-FC-PL-PREMIER-COACH',
            'ECS-FC-PL-CLASSIC-COACH',
            'ECS-FC-PL-ECS-FC-COACH',
            'Referee',
        ])

    # Prepare data for role removal
    player_data = {
        'id': data['player_id'],
        'name': data['name'],
        'discord_id': data['discord_id'],
        'current_roles': data.get('current_roles', []),
        'expected_roles': [],  # Empty - we want to remove roles
        'app_managed_roles': roles_to_remove  # Only these specific roles
    }

    # pattern_sweep is the difference between the two modes, and getting it wrong is
    # what silently revoked unrelated team roles:
    #   team_id set  -> SCOPED removal (draft-remove, member-hub Remove, undo pick).
    #     roles_to_remove names exactly one team's roles, but expected_roles is empty,
    #     so the ECS-FC-PL-*-Player/-Coach catch-all matched EVERY other team role the
    #     player held and stripped it too. A player on an ECS FC team who was removed
    #     from their Premier team lost their ECS FC team role as collateral. Off.
    #   team_id None -> FULL offboarding (deny / deactivate / set-pending). Sweeping
    #     really is the intent there: it also catches stale team roles from teams the
    #     player is no longer associated with in the DB at all. On.
    pattern_sweep = data.get('team_id') is None

    # enforce_allowlist=False: this is a TARGETED removal — roles_to_remove is an
    # explicit, intentional list the caller built, NOT a drift-driven reconcile. It must
    # execute in full, so the protected-role allowlist (which only guards drift
    # reconciles) is bypassed here.
    from app.discord_utils import update_player_roles_async_only
    result = await update_player_roles_async_only(
        player_data, force_update=True, enforce_allowlist=False,
        pattern_sweep=pattern_sweep)
    logger.info(
        f"Targeted role removal for {data.get('name')} "
        f"(team_id={data.get('team_id')}, pattern_sweep={pattern_sweep}): "
        f"requested={roles_to_remove} removed={result.get('roles_removed')}"
    )

    return {
        'success': result.get('success', False),
        'message': result.get('message', result.get('error', '')),
        'roles_removed': result.get('roles_removed', []),
        'player_id': data['player_id'],
        'team_id': data.get('team_id'),
        'processed_at': datetime.utcnow().isoformat()
    }


def _update_player_after_role_removal(session, result):
    """Update player record after role removal."""
    if not result.get('success'):
        return result

    player = session.query(Player).get(result['player_id'])
    if player:
        if result.get('success'):
            # Don't clear all roles, just update with current state
            player.discord_last_verified = datetime.utcnow()
            player.last_role_removal = datetime.utcnow()
            player.role_removal_status = 'completed'
        else:
            player.role_removal_status = 'failed'
            player.last_role_removal = datetime.utcnow()
            if result.get('message'):
                player.role_removal_error = result['message']

    return {
        'success': True,
        'message': 'Roles removed successfully',
        'player_id': result['player_id'],
        'team_id': result.get('team_id'),
        'processed_at': result['processed_at'],
        'roles_removed': result.get('roles_removed', [])
    }


@celery_task(
    name='app.tasks.tasks_discord.remove_player_roles_task',
    queue='discord',
    bind=True,
    max_retries=3,
    retry_backoff=True,
    ignore_result=True  # fire-and-forget role sync: don't accumulate result keys in Redis
)
async def remove_player_roles_task(self, session, player_id: int, team_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Remove Discord roles for a player using two-phase pattern.

    Args:
        session: Database session (used only in phase 1).
        player_id: ID of the player.
        team_id: Optional. If provided, only roles scoped to that team are removed.
                 If None, all of the player's team-scoped Discord roles are removed
                 (used for user denial / deactivation flows).

    Returns:
        A dictionary with the result and updated player info.
    """
    pass


# Attach phase methods
remove_player_roles_task._extract_data = _extract_remove_roles_data
remove_player_roles_task._execute_async = _execute_remove_roles_async
remove_player_roles_task._two_phase = True
remove_player_roles_task._requires_final_db_update = True
remove_player_roles_task._final_db_update = _update_player_after_role_removal


async def _remove_player_roles_async(session, player_id: int, team_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Async helper to remove a player's Discord roles.
    
    Args:
        session: Database session.
        player_id: ID of the player.
        team_id: Optional team ID to specify which role to remove.
        
    Returns:
        A dictionary with success status.
    """
    player = session.query(Player).get(player_id)
    if not player or not player.discord_id:
        logger.error(f"No Discord ID for player {player_id}") 
        return {'success': False, 'message': 'No Discord ID'}

    try:
        async with aiohttp.ClientSession() as aio_session:
            if team_id:
                team = session.query(Team).get(team_id)
                role_name = f"ECS-FC-PL-{normalize_name(team.name)}-Player"
                guild_id = int(Config.SERVER_ID)

                url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{player.discord_id}/roles"
                member_roles = await make_discord_request('GET', url, aio_session)
                
                if member_roles:
                    role_id = await get_role_id(guild_id, role_name, aio_session)
                    if role_id:
                        await remove_role_from_member(guild_id, player.discord_id, role_id, aio_session)
                        return {'success': True}

            return {'success': False, 'message': 'No team specified'}

    except Exception as e:
        logger.error(f"Error removing roles: {str(e)}", exc_info=True)
        return {'success': False, 'message': str(e)}


# ---------------------------------------------------------------------------
# Precise revocation
#
# A full reconcile CANNOT revoke a division/coach/team role: the protected-role
# allowlist (discord_utils._is_reconcile_removable) only lets it strip sub and
# unverified roles, because drift between calculators used to wipe the league.
# That safety net also meant an INTENDED removal — un-toggling pl-premier, or
# taking someone off the team they coached — silently left the Discord role in
# place forever.
#
# This task is the intended-removal counterpart: the caller names the roles it
# believes should come off, and the shared calculator gets the final say. A role
# is revoked only when the calculator agrees the player should no longer have it,
# so an admin action can never take a role the player is still entitled to.
# ---------------------------------------------------------------------------

def _extract_revoke_unexpected_data(session, player_id: int,
                                    candidate_roles: Optional[List[str]] = None,
                                    team_ids: Optional[List[int]] = None):
    """Extract player data plus the candidate roles to consider revoking."""
    data = _extract_player_role_data(session, player_id)

    candidates: List[str] = [r for r in (candidate_roles or []) if r]
    for tid in (team_ids or []):
        team = session.query(Team).get(tid)
        if team:
            candidates.append(f"ECS-FC-PL-{normalize_name(team.name)}-Player")
            candidates.append(f"ECS-FC-PL-{normalize_name(team.name)}-Coach")

    data['candidate_roles'] = candidates
    return data


async def _execute_revoke_unexpected_async(data):
    """Revoke only those candidate roles the shared calculator no longer expects."""
    from app.discord_utils import (
        update_player_roles_async_only, get_member_roles, normalize_name as _norm,
    )

    player_id = data.get('player_id')
    candidates = data.get('candidate_roles') or []
    if not candidates or not data.get('discord_id'):
        return {'success': True, 'roles_removed': [], 'roles_added': [],
                'current_roles': data.get('current_roles', []),
                'player_id': player_id, 'sync_status': 'success'}

    expected_norm = {_norm(r) for r in _compute_expected_roles(data)}

    # Read LIVE Discord roles rather than trusting player.discord_roles. The
    # reconcile only ever removes roles present in current_roles, so a stale cache
    # would make an intended revoke a silent no-op — the exact failure this task
    # exists to eliminate. Fall back to the cache if the bot is unreachable.
    try:
        _timeout = aiohttp.ClientTimeout(total=20, connect=5, sock_read=10)
        async with aiohttp.ClientSession(timeout=_timeout) as http_session:
            live_roles = await get_member_roles(data['discord_id'], http_session)
    except Exception as e:
        logger.warning(f"Live role fetch failed for player {player_id}, using cache: {e}")
        live_roles = None
    current_roles = live_roles if live_roles else (data.get('current_roles') or [])

    to_remove = []
    kept = []
    ignored = []
    for cand in candidates:
        cn = _norm(cand)
        if not _is_revocable_candidate(cand):
            ignored.append(cand)       # not a role any calculator produces
            continue
        if cn in expected_norm:
            kept.append(cand)          # calculator still entitles them to it
            continue
        if cn not in to_remove:
            to_remove.append(cn)

    if ignored:
        logger.warning(f"Player {player_id}: ignoring non-app-managed revoke "
                       f"candidates {ignored}")
    if kept:
        logger.info(f"Player {player_id}: keeping {kept} — still expected by the calculator")
    if not to_remove:
        return {'success': True, 'roles_removed': [], 'roles_added': [],
                'current_roles': current_roles, 'player_id': player_id,
                'sync_status': 'success'}

    player_data = {
        'id': player_id,
        'name': data['name'],
        'discord_id': data['discord_id'],
        'current_roles': current_roles,
        'expected_roles': [],          # nothing to grant; this is a revoke-only pass
        'app_managed_roles': to_remove,  # the ONLY roles eligible for removal
    }

    # enforce_allowlist=False (explicit, caller-chosen list) + pattern_sweep=False
    # (never touch anything outside that list).
    result = await update_player_roles_async_only(
        player_data, force_update=True, enforce_allowlist=False, pattern_sweep=False)

    logger.info(f"Player {player_id}: revoke pass requested={to_remove} "
                f"removed={result.get('roles_removed')}")

    return {
        'success': result.get('success', False),
        'message': result.get('message', result.get('error', '')),
        'current_roles': result.get('current_roles', []),
        'roles_added': [],
        'roles_removed': result.get('roles_removed', []),
        'player_id': player_id,
        'sync_status': 'success' if result.get('success') else 'mismatch',
    }


@celery_task(
    name='app.tasks.tasks_discord.revoke_unexpected_roles_task',
    queue='discord',
    max_retries=2
)
async def revoke_unexpected_roles_task(self, session, player_id: int,
                                       candidate_roles: Optional[List[str]] = None,
                                       team_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    """
    Revoke specific Discord roles, but only where the player is no longer entitled.

    Args:
        session: Database session (phase 1 only).
        player_id: player whose roles to re-check.
        candidate_roles: explicit Discord role names to consider revoking.
        team_ids: teams whose -Player/-Coach roles to consider revoking. Expanded to
            role names in phase 1.

    Every candidate is checked against the shared expected-role calculator; anything
    the player still legitimately has is kept. Safe to call after any roster or Flask
    role change.
    """
    pass


revoke_unexpected_roles_task._extract_data = _extract_revoke_unexpected_data
revoke_unexpected_roles_task._execute_async = _execute_revoke_unexpected_async
revoke_unexpected_roles_task._two_phase = True
revoke_unexpected_roles_task._requires_final_db_update = True
revoke_unexpected_roles_task._final_db_update = _update_player_after_role_sync


def _extract_create_team_data(session, team_id: int):
    """Extract team data for Discord resource creation."""
    # Force a fresh read from the database to avoid stale data
    session.expire_all()
    
    team = session.query(Team).options(
        joinedload(Team.league)
    ).get(team_id)
    
    if not team:
        # Try one more time with a fresh query in case of timing issues
        session.rollback()  # Clear any potential issues
        team = session.query(Team).filter(Team.id == team_id).first()
        
        if not team:
            logger.error(f"Team {team_id} not found after retry - skipping Discord resource creation")
            # Log more debug info
            team_count = session.query(Team).count()
            logger.debug(f"Total teams in database: {team_count}")
            recent_teams = session.query(Team).order_by(Team.id.desc()).limit(10).all()
            logger.debug(f"Recent team IDs: {[t.id for t in recent_teams]}")
            return None
    
    logger.info(f"Found team {team_id}: {team.name} in league {team.league.name if team.league else 'No League'}")

    # Read the reveal toggle here (phase 1 has the DB session) so the async
    # phase can create hidden channels while make_teams_public is off.
    from app.models.admin_config import AdminConfig
    cfg = session.query(AdminConfig).filter_by(key='make_teams_public', is_enabled=True).first()
    teams_public = cfg.parsed_value if cfg else True

    return {
        'team_id': team_id,
        'team_name': team.name,
        'league_name': team.league.name if team.league else None,
        'teams_public': teams_public
    }


async def _execute_create_team_discord_async(data):
    """Execute Discord resource creation without database session."""
    # Create Discord channel using async-only approach
    from app.discord_utils import create_discord_channel_async_only

    channel_result = await create_discord_channel_async_only(
        data['team_name'],
        data['league_name'],
        data['team_id'],
        teams_public=data.get('teams_public', True)
    )
    
    return {
        'success': channel_result.get('success', False),
        'message': channel_result.get('message', 'Discord resources created'),
        'channel_id': channel_result.get('channel_id'),
        'player_role_id': channel_result.get('player_role_id'),
        'coach_role_id': channel_result.get('coach_role_id'),
        'team_id': data['team_id']
    }


def _update_team_after_discord_creation(session, result):
    """Update team record after Discord resource creation."""
    if not result.get('success'):
        return result
    
    team = session.query(Team).get(result['team_id'])
    if team:
        if result.get('channel_id'):
            team.discord_channel_id = result['channel_id']
        if result.get('player_role_id'):
            team.discord_player_role_id = result['player_role_id']
        if result.get('coach_role_id'):
            team.discord_coach_role_id = result['coach_role_id']

    return {'success': True, 'message': 'Discord resources created'}


@celery_task(name='app.tasks.tasks_discord.create_team_discord_resources_task', queue='discord')
async def create_team_discord_resources_task(self, session, team_id: int):
    """
    Create Discord resources for a new team using two-phase pattern.
    
    Args:
        session: Database session (used only in phase 1).
        team_id: ID of the team.
        
    Returns:
        A dictionary indicating success or failure.
    """
    pass


# Attach phase methods - using both approaches for reliability
create_team_discord_resources_task._extract_data = _extract_create_team_data
create_team_discord_resources_task._execute_async = _execute_create_team_discord_async
create_team_discord_resources_task._requires_final_db_update = True
create_team_discord_resources_task._final_db_update = _update_team_after_discord_creation

# Also set the _two_phase attribute as a fallback
create_team_discord_resources_task._two_phase = True


def _extract_team_visibility_data(session, make_public: bool):
    """Collect current Pub League teams with Discord channel + player role IDs."""
    from app.models import League

    season = session.query(Season).filter_by(is_current=True, league_type='Pub League').first()
    teams = []
    if season:
        leagues = session.query(League).filter_by(season_id=season.id).all()
        for league in leagues:
            if league.name not in ('Premier', 'Classic'):
                continue
            for team in session.query(Team).filter_by(league_id=league.id).all():
                if team.discord_channel_id and team.discord_player_role_id:
                    teams.append({
                        'name': team.name,
                        'channel_id': team.discord_channel_id,
                        'player_role_id': team.discord_player_role_id
                    })
    else:
        logger.warning("sync_team_channel_visibility: no current Pub League season found")

    return {'make_public': bool(make_public), 'teams': teams}


async def _execute_team_visibility_async(data):
    """Flip the player-role view overwrite on every team channel."""
    from app.discord_utils import set_team_channel_player_visibility

    guild_id = int(Config.SERVER_ID)
    make_public = data['make_public']
    updated, failed = 0, []

    async with aiohttp.ClientSession() as session_http:
        for team in data['teams']:
            ok = await set_team_channel_player_visibility(
                guild_id, team['channel_id'], team['player_role_id'], make_public, session_http
            )
            if ok:
                updated += 1
            else:
                failed.append(team['name'])
            # Stay under Discord rate limits
            await asyncio.sleep(0.5)

    result = {
        'success': len(failed) == 0,
        'message': f"{'Revealed' if make_public else 'Hid'} {updated}/{len(data['teams'])} team channels",
        'updated': updated,
        'failed': failed
    }
    if failed:
        logger.error(f"sync_team_channel_visibility failed for teams: {failed}")
    else:
        logger.info(result['message'])
    return result


@celery_task(name='app.tasks.tasks_discord.sync_team_channel_visibility_task', queue='discord')
async def sync_team_channel_visibility_task(self, session, make_public: bool):
    """
    Sync every current Pub League team channel's player-role view permission
    with the make_teams_public toggle. Dispatched when the toggle changes.
    """
    pass


sync_team_channel_visibility_task._extract_data = _extract_team_visibility_data
sync_team_channel_visibility_task._execute_async = _execute_team_visibility_async
sync_team_channel_visibility_task._two_phase = True


async def delete_channel(channel_id: str) -> bool:
    """
    Async helper to delete a Discord channel.
    
    Args:
        channel_id: ID of the channel to delete.
        
    Returns:
        True if deletion was successful, False otherwise.
    """
    url = f"{Config.BOT_API_URL}/api/server/guilds/{Config.SERVER_ID}/channels/{channel_id}"
    async with aiohttp.ClientSession() as client:
        async with client.delete(url) as response:
            success = response.status == 200
            if success:
                logger.info(f"Deleted channel ID {channel_id}")
            return success


async def delete_role(role_id: str) -> bool:
    """
    Async helper to delete a Discord role.
    
    Args:
        role_id: ID of the role to delete.
        
    Returns:
        True if deletion was successful, False otherwise.
    """
    url = f"{Config.BOT_API_URL}/api/server/guilds/{Config.SERVER_ID}/roles/{role_id}"
    async with aiohttp.ClientSession() as client:
        async with client.delete(url) as response:
            success = response.status == 200
            if success:
                logger.info(f"Deleted role ID {role_id}")
            return success


@celery_task(name='app.tasks.tasks_discord.cleanup_team_discord_resources_task', queue='discord')
def cleanup_team_discord_resources_task(self, session, team_id: int):
    """
    Clean up Discord resources for a team.
    
    This task deletes the team's Discord channel and role if they exist, and updates the team record.
    
    Args:
        session: Database session.
        team_id: ID of the team.
        
    Returns:
        A dictionary indicating success or failure.
    
    Raises:
        Retries the task on error.
    """
    try:
        # Read the IDs without holding a row lock — Discord HTTP calls below
        # would otherwise extend the transaction past idle_in_transaction_session_timeout.
        team = session.query(Team).get(team_id)
        if not team:
            return {'success': False, 'message': 'Team not found'}

        channel_id = team.discord_channel_id
        role_id = team.discord_player_role_id

        # End the read transaction before the network calls so no lock is held.
        session.commit()

        from app.utils.sync_discord_client import get_sync_discord_client
        discord_client = get_sync_discord_client()

        channel_deleted = bool(channel_id) and discord_client.delete_channel(channel_id).get('success', False)
        role_deleted = bool(role_id) and discord_client.delete_role(role_id).get('success', False)

        # Brief locked write to clear the IDs we successfully deleted.
        if channel_deleted or role_deleted:
            team = session.query(Team).with_for_update().get(team_id)
            if team:
                if channel_deleted:
                    team.discord_channel_id = None
                if role_deleted:
                    team.discord_player_role_id = None
                session.flush()

        # Final commit happens in @celery_task decorator.
        return {'success': True, 'message': 'Discord resources cleaned up'}
            
    except Exception as e:
        # Rollback happens automatically in @celery_task decorator
        logger.error(f"Error cleaning up Discord resources: {str(e)}")
        raise self.retry(exc=e, countdown=30)


@celery_task(name='app.tasks.tasks_discord.delete_discord_resources_by_ids_task', queue='discord')
def delete_discord_resources_by_ids_task(self, session, channel_id: str = None, player_role_id: str = None, coach_role_id: str = None):
    """
    Delete Discord resources by their IDs directly.

    This task doesn't require the team to exist in the database - useful for cleanup
    after team deletion.

    Args:
        session: Database session (not used but required by decorator).
        channel_id: Discord channel ID to delete.
        player_role_id: Discord player role ID to delete.
        coach_role_id: Discord coach role ID to delete.

    Returns:
        A dictionary indicating success or failure.
    """
    results = {'channel': None, 'player_role': None, 'coach_role': None}

    try:
        from app.utils.sync_discord_client import get_sync_discord_client
        discord_client = get_sync_discord_client()

        if channel_id:
            result = discord_client.delete_channel(channel_id)
            results['channel'] = result.get('success', False)
            if results['channel']:
                logger.info(f"Deleted Discord channel {channel_id}")
            else:
                logger.warning(f"Failed to delete Discord channel {channel_id}: {result.get('message', 'Unknown error')}")

        if player_role_id:
            result = discord_client.delete_role(player_role_id)
            results['player_role'] = result.get('success', False)
            if results['player_role']:
                logger.info(f"Deleted Discord player role {player_role_id}")
            else:
                logger.warning(f"Failed to delete Discord player role {player_role_id}: {result.get('message', 'Unknown error')}")

        if coach_role_id:
            result = discord_client.delete_role(coach_role_id)
            results['coach_role'] = result.get('success', False)
            if results['coach_role']:
                logger.info(f"Deleted Discord coach role {coach_role_id}")
            else:
                logger.warning(f"Failed to delete Discord coach role {coach_role_id}: {result.get('message', 'Unknown error')}")

        return {'success': True, 'results': results}

    except Exception as e:
        logger.error(f"Error deleting Discord resources by IDs: {str(e)}")
        # Return failure rather than retry - resources may already be gone
        return {'success': False, 'message': str(e), 'results': results}


def _extract_update_team_data(session, team_id: int, new_team_name: str):
    """Extract team data for Discord resource update."""
    team = session.query(Team).options(joinedload(Team.league)).get(team_id)
    if not team:
        raise ValueError(f"Team {team_id} not found")
    
    return {
        'team_id': team_id,
        'old_team_name': team.name,
        'new_team_name': new_team_name,
        'league_name': team.league.name if team.league else None,
        'discord_coach_role_id': team.discord_coach_role_id,
        'discord_player_role_id': team.discord_player_role_id,
        'discord_channel_id': team.discord_channel_id
    }


async def _execute_update_team_discord_async(data):
    """Execute Discord resource update without database session."""
    import os
    import aiohttp
    from app.utils.discord_request_handler import make_discord_request
    
    # Use async-only version of rename team roles
    from app.discord_utils import rename_team_roles_async_only
    
    # Rename roles
    role_result = await rename_team_roles_async_only(
        data['old_team_name'],
        data['new_team_name'],
        data['discord_coach_role_id'],
        data['discord_player_role_id']
    )
    
    # Rename channel if it exists
    channel_success = True
    channel_message = ""
    if data.get('discord_channel_id'):
        try:
            bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
            url = f"{bot_api_url}/api/server/channels/{data['discord_channel_id']}"
            
            async with aiohttp.ClientSession() as session:
                response = await make_discord_request('PATCH', url, session, json={'new_name': data['new_team_name']})
                if response:
                    logger.info(f"Renamed channel to: {data['new_team_name']}")
                    channel_message = f"Channel renamed to: {data['new_team_name']}"
                else:
                    logger.error(f"Failed to rename channel")
                    channel_success = False
                    channel_message = f"Failed to rename channel"
        except Exception as e:
            logger.error(f"Error renaming channel: {e}")
            channel_success = False
            channel_message = f"Error renaming channel: {e}"
    else:
        channel_message = "No channel to rename"
    
    # Combine results
    overall_success = role_result.get('success', False) and channel_success
    combined_message = f"{role_result.get('message', '')}. {channel_message}"
    
    return {
        'success': overall_success,
        'message': combined_message,
        'team_id': data['team_id']
    }


@celery_task(name='app.tasks.tasks_discord.update_team_discord_resources_task', queue='discord')
async def update_team_discord_resources_task(self, session, team_id: int, new_team_name: str):
    """
    Update Discord resources when a team's name changes using two-phase pattern.
    
    Args:
        session: Database session (used only in phase 1).
        team_id: ID of the team.
        new_team_name: The new team name.
        
    Returns:
        A dictionary indicating success or failure.
    """
    pass


# Attach phase methods
update_team_discord_resources_task._extract_data = _extract_update_team_data
update_team_discord_resources_task._execute_async = _execute_update_team_discord_async
update_team_discord_resources_task._two_phase = True


async def _process_role_updates_batch(session, players: List[Player]) -> List[Dict[str, Any]]:
    """
    Async helper to process role updates for a batch of players.
    
    Args:
        session: Database session.
        players: List of Player objects.
        
    Returns:
        A list of dictionaries representing the update result for each player.
    """
    results = []
    for player in players:
        try:
            await update_player_roles(session, player, force_update=False)
            results.append({
                'player_id': player.id,
                'success': True,
                'status': 'synced'
            })
        except Exception as e:
            results.append({
                'player_id': player.id,
                'success': False,
                'status': 'error',
                'error': str(e)
            })
    return results