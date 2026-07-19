# app/mobile_api/draft.py

"""
Mobile API Draft Endpoints

Provides draft system functionality for mobile clients:
- View draft status and analytics
- Get available/drafted players
- Draft players to teams
- Remove players from teams
- Position analysis for teams
"""

import logging
from flask import jsonify, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql import exists, and_, or_
from sqlalchemy import func

from app.mobile_api import mobile_api_v2
from app.constants.positions import label_for
from app.decorators import jwt_role_required
from app.core.session_manager import managed_session
from app.models import (
    User, Player, Team, League, Season,
    player_teams, player_league, DraftOrderHistory, PlayerTeamSeason,
    DraftSession, DraftPickSlot
)
from app.draft_enhanced import DraftService
from app.draft_cache_service import DraftCacheService
from app.db_utils import mark_player_for_discord_update
from app.models.ecs_fc import is_ecs_fc_league
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task

logger = logging.getLogger(__name__)

# Valid leagues for drafting
VALID_LEAGUES = {
    'classic': 'Classic',
    'premier': 'Premier',
    'ecs_fc': 'ECS FC'
}


def get_db_league_name(league_name: str) -> str:
    """Convert URL league name to database league name."""
    return VALID_LEAGUES.get(league_name.lower())


# Roles allowed to VIEW/pick on the draft (coaches + admins)
DRAFT_ROLES = ['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin']
# Roles allowed to RUN the clock (start/skip/undo/pause/resume/end) — admins only
DRAFT_ADMIN_ROLES = ['Pub League Admin', 'Global Admin']

# Valid pitch slots for a drafted player (mirrors the web board's update_player_position
# vocabulary; lm/rm included so the mobile 4-4-2 has its wide-mid slots).
VALID_PITCH_POSITIONS = {
    'gk', 'lb', 'cb', 'rb', 'lwb', 'rwb', 'cdm', 'cm', 'cam',
    'lm', 'rm', 'lw', 'rw', 'st', 'bench',
}


def _current_league(session, db_league_name):
    """Resolve the current-season League row for a DB league name (or None)."""
    return session.query(League).join(Season).filter(
        League.name == db_league_name,
        Season.is_current == True  # noqa: E712
    ).first()


def _user_is_admin(session, user_id) -> bool:
    """True if the user holds a Pub League Admin / Global Admin role (session query,
    so it works outside a request/current_user context)."""
    from app.models.core import Role, user_roles
    return session.query(user_roles.c.user_id).join(
        Role, Role.id == user_roles.c.role_id
    ).filter(
        user_roles.c.user_id == user_id,
        Role.name.in_(DRAFT_ADMIN_ROLES),
    ).first() is not None


def _my_coached_team_ids(session, user_id, league_id):
    """Team ids in this league that the user coaches (player_teams.is_coach). Any one
    coach of a team counts as that team being 'in the draft'."""
    rows = session.query(player_teams.c.team_id).join(
        Player, Player.id == player_teams.c.player_id
    ).join(Team, Team.id == player_teams.c.team_id).filter(
        Player.user_id == user_id,
        player_teams.c.is_coach == True,  # noqa: E712
        Team.league_id == league_id,
    ).all()
    return [r[0] for r in rows]


def _emit_to_draft_rooms(event, payload, url_name, db_name):
    """Emit a draft socket event to every room the web board / mobile app might have
    joined, on BOTH the web ('/') and mobile ('/draft') namespaces. The web board
    joins draft_<getLeagueName()> (casing varies: url slug vs DB name); the mobile
    client joins draft_<url_name>. Delegates to the shared broadcaster so the room +
    namespace fan-out stays identical to the web routes and the timeout task."""
    from app import draft_clock
    draft_clock.broadcast_draft(event, payload, url_name, db_name)


@mobile_api_v2.route('/draft/leagues', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_draft_leagues():
    """
    Get list of leagues available for drafting.

    Returns:
        JSON with list of leagues and their draft status
    """
    with managed_session() as session:
        # Get current season
        current_season = session.query(Season).filter_by(
            is_current=True,
            league_type='Pub League'
        ).first()

        if not current_season:
            return jsonify({
                "leagues": [],
                "message": "No current season found"
            }), 200

        # Get leagues for current season
        leagues = session.query(League).filter_by(
            season_id=current_season.id
        ).all()

        league_data = []
        for league in leagues:
            team_count = len([t for t in league.teams if t.name != "Practice"])

            # Count total players drafted
            total_drafted = 0
            for team in league.teams:
                if team.name != "Practice":
                    total_drafted += len([p for p in team.players if p.is_current_player])

            league_data.append({
                "id": league.id,
                "name": league.name,
                "url_name": league.name.lower().replace(' ', '_'),
                "season_id": league.season_id,
                "season_name": current_season.name,
                "team_count": team_count,
                "total_drafted": total_drafted
            })

        return jsonify({"leagues": league_data}), 200


@mobile_api_v2.route('/draft/<league_name>/status', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_draft_status(league_name: str):
    """
    Get draft status and analytics for a league.

    Args:
        league_name: URL-friendly league name (classic, premier, ecs_fc)

    Returns:
        JSON with draft analytics and status
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        # Get current league
        current_league = (
            session.query(League)
            .join(League.season)
            .filter(League.name == db_league_name)
            .filter(Season.is_current == True)
            .first()
        )

        if not current_league:
            return jsonify({"msg": f"No current {db_league_name} league found"}), 404

        # Get teams (excluding Practice)
        teams = [t for t in current_league.teams if t.name != "Practice"]

        # Calculate analytics
        teams_data = []
        total_drafted = 0
        position_counts = {}

        for team in teams:
            team_players = [p for p in team.players if p.is_current_player]
            team_count = len(team_players)
            total_drafted += team_count

            # Count positions
            for player in team_players:
                pos = label_for(player.favorite_position) or 'Unknown'
                position_counts[pos] = position_counts.get(pos, 0) + 1

            teams_data.append({
                "id": team.id,
                "name": team.name,
                "player_count": team_count
            })

        # Get available player count
        team_ids = [t.id for t in teams]
        all_leagues = session.query(League).filter(League.name == db_league_name).all()
        league_ids = [l.id for l in all_leagues]

        # Players belonging to this league
        belongs_to_league = or_(
            Player.primary_league_id.in_(league_ids),
            exists().where(
                and_(
                    player_league.c.player_id == Player.id,
                    player_league.c.league_id.in_(league_ids)
                )
            )
        )

        # Not on any current team
        not_drafted = ~exists().where(
            and_(
                player_teams.c.player_id == Player.id,
                player_teams.c.team_id.in_(team_ids)
            )
        )

        available_count = session.query(func.count(Player.id)).filter(
            belongs_to_league,
            not_drafted,
            Player.is_current_player == True
        ).scalar()

        # Get latest draft pick
        latest_pick = session.query(DraftOrderHistory).filter(
            DraftOrderHistory.league_id == current_league.id,
            DraftOrderHistory.season_id == current_league.season_id
        ).order_by(DraftOrderHistory.draft_position.desc()).first()

        return jsonify({
            "league_id": current_league.id,
            "league_name": db_league_name,
            "season_id": current_league.season_id,
            "teams": teams_data,
            "total_teams": len(teams),
            "total_drafted": total_drafted,
            "available_count": available_count,
            "avg_players_per_team": round(total_drafted / max(len(teams), 1), 1),
            "position_distribution": position_counts,
            "draft_progress": min(100, (total_drafted / (len(teams) * 15)) * 100),
            "latest_pick_position": latest_pick.draft_position if latest_pick else 0
        }), 200


@mobile_api_v2.route('/draft/<league_name>/available', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_available_players(league_name: str):
    """
    Get available (undrafted) players for a league.

    Args:
        league_name: URL-friendly league name

    Query Parameters:
        search: Filter by player name (optional)
        position: Filter by position (optional)
        page: Page number for pagination (default: 1)
        per_page: Items per page (default: 50, max: 100)

    Returns:
        JSON with list of available players
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    # Get query parameters
    search = request.args.get('search', '').strip()
    position = request.args.get('position', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)

    with managed_session() as session:
        # Get current league and all historical leagues with same name
        current_league, all_leagues = DraftService.get_league_data(db_league_name)

        if not current_league:
            return jsonify({"msg": f"No current {db_league_name} league found"}), 404

        # Get team IDs for current league
        teams = [t for t in current_league.teams if t.name != "Practice"]
        team_ids = [t.id for t in teams]
        league_ids = [l.id for l in all_leagues]

        # Build query for available players
        belongs_to_league = or_(
            Player.primary_league_id.in_(league_ids),
            exists().where(
                and_(
                    player_league.c.player_id == Player.id,
                    player_league.c.league_id.in_(league_ids)
                )
            )
        )

        # Check if this is an ECS FC league
        is_ecs_fc = is_ecs_fc_league(current_league.id)

        query = (
            session.query(Player)
            .join(Player.user)  # Join to User to check approval status
            .filter(belongs_to_league)
            .filter(Player.is_current_player == True)
            .filter(User.is_approved == True)  # Only include approved users
            .options(
                joinedload(Player.career_stats),
                joinedload(Player.season_stats),
                selectinload(Player.teams),
                joinedload(Player.user)  # Eager load user for performance
            )
        )

        # For Pub League: exclude players already on a team
        # For ECS FC: include all players (multi-team allowed)
        if not is_ecs_fc:
            not_drafted = ~exists().where(
                and_(
                    player_teams.c.player_id == Player.id,
                    player_teams.c.team_id.in_(team_ids)
                )
            )
            query = query.filter(not_drafted)

        # Apply search filter
        if search:
            query = query.filter(Player.name.ilike(f'%{search}%'))

        # Apply position filter
        if position:
            query = query.filter(Player.favorite_position.ilike(f'%{position}%'))

        # Get total count before pagination
        total_count = query.count()

        # Apply pagination
        query = query.order_by(Player.name.asc())
        query = query.offset((page - 1) * per_page).limit(per_page)

        players_raw = query.all()

        # Get enhanced player data
        players = DraftService.get_enhanced_player_data(
            players_raw,
            current_league.season_id
        )

        # For ECS FC: add existing team information for multi-team support
        if is_ecs_fc:
            team_ids_set = set(team_ids)
            for i, player_data in enumerate(players):
                raw_player = players_raw[i]
                existing_teams = [
                    {"id": team.id, "name": team.name}
                    for team in raw_player.teams
                    if team.id in team_ids_set
                ]
                player_data['existing_ecs_fc_teams'] = existing_teams

        return jsonify({
            "players": players,
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "total_pages": (total_count + per_page - 1) // per_page,
            "is_ecs_fc_league": is_ecs_fc
        }), 200


@mobile_api_v2.route('/draft/<league_name>/teams', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_draft_teams(league_name: str):
    """
    Get teams for a league with roster counts.

    Args:
        league_name: URL-friendly league name

    Returns:
        JSON with list of teams and their rosters
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        current_league, _ = DraftService.get_league_data(db_league_name)

        if not current_league:
            return jsonify({"msg": f"No current {db_league_name} league found"}), 404

        teams = [t for t in current_league.teams if t.name != "Practice"]

        teams_data = []
        for team in teams:
            team_players = [p for p in team.players if p.is_current_player]

            # Count positions on team
            position_counts = {}
            for player in team_players:
                pos = label_for(player.favorite_position) or 'Unknown'
                position_counts[pos] = position_counts.get(pos, 0) + 1

            teams_data.append({
                "id": team.id,
                "name": team.name,
                "player_count": len(team_players),
                "position_breakdown": position_counts
            })

        return jsonify({"teams": teams_data}), 200


@mobile_api_v2.route('/draft/<league_name>/team/<int:team_id>/roster', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_team_roster(league_name: str, team_id: int):
    """
    Get detailed roster for a specific team.

    Args:
        league_name: URL-friendly league name
        team_id: Team ID

    Returns:
        JSON with team roster and player details
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        current_league, _ = DraftService.get_league_data(db_league_name)

        if not current_league:
            return jsonify({"msg": f"No current {db_league_name} league found"}), 404

        # Get team
        team = session.query(Team).filter(
            Team.id == team_id,
            Team.league_id == current_league.id
        ).first()

        if not team:
            return jsonify({"msg": f"Team not found in {db_league_name}"}), 404

        # Get team players with enhanced data
        team_players = [p for p in team.players if p.is_current_player]
        players = DraftService.get_enhanced_player_data(
            team_players,
            current_league.season_id
        )

        return jsonify({
            "team_id": team.id,
            "team_name": team.name,
            "player_count": len(players),
            "players": players
        }), 200


@mobile_api_v2.route('/draft/<league_name>/pick', methods=['POST'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def draft_player(league_name: str):
    """
    Draft a player to a team.

    Args:
        league_name: URL-friendly league name

    Expected JSON:
        player_id: ID of player to draft
        team_id: ID of team to draft player to

    Returns:
        JSON with draft result
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    player_id = data.get('player_id')
    team_id = data.get('team_id')
    position = (data.get('position') or 'bench')  # pitch-view slot; 'bench' from a list pick

    if not player_id or not team_id:
        return jsonify({"msg": "Missing player_id or team_id"}), 400

    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Get current user
        user = session.query(User).get(current_user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        # Get league from current season
        league = session.query(League).join(Season).filter(
            League.name == db_league_name,
            Season.is_current == True
        ).first()

        if not league:
            return jsonify({"msg": "League not found"}), 404

        # Get player and team
        player = session.query(Player).get(player_id)
        team = session.query(Team).filter(
            Team.id == team_id,
            Team.league_id == league.id
        ).first()

        if not player:
            return jsonify({"msg": "Player not found"}), 404
        if not team:
            return jsonify({"msg": "Team not found in this league"}), 404

        from app import draft_clock
        from sqlalchemy import update as _sa_update

        # ---- Claim the turn ATOMICALLY. Lock the draft_session row FOR UPDATE so this
        # pick serialises against any other pick (web or mobile) for this draft. While we
        # hold the lock we (re)check the turn AND the already-drafted guard, do the write,
        # and advance — all in one transaction. A racing second pick blocks here until we
        # commit, then sees the clock already moved and is rejected: no double-draft. ----
        ds = draft_clock.get_session(session, league.season_id, league.id, for_update=True)
        is_admin = _user_is_admin(session, current_user_id)

        # Turn check under the lock (no-op in free-form / paused; admins may go out of turn).
        ok, code = draft_clock.check_turn(ds, team_id, is_admin, data.get('expected_pick'))
        if not ok:
            if code == 'stale':
                return jsonify({"success": False, "msg": "The board moved on — refresh and try again.",
                                "stale": True}), 409
            on_clock = session.query(Team).filter(Team.id == ds.current_team_id).first()
            on_clock_name = on_clock.name if on_clock else 'another team'
            return jsonify({"success": False,
                            "msg": f"It's {on_clock_name}'s pick — they're on the clock",
                            "on_the_clock": True}), 409

        # Already-drafted guard, re-checked UNDER the lock (closes the free-form race too).
        existing = session.query(player_teams).filter(
            player_teams.c.player_id == player_id,
            player_teams.c.team_id.in_(
                session.query(Team.id).filter(Team.league_id == league.id)
            )
        ).first()
        if existing and not is_ecs_fc_league(league.id):
            return jsonify({"success": False, "msg": "Player is already on a team in this league"}), 400

        # Add player to team (with pitch-view position, matching the web socket path)
        if player not in team.players:
            team.players.append(player)
        player.primary_team_id = team_id
        session.flush()  # ensure the player_teams row exists before we set its position
        session.execute(_sa_update(player_teams).where(
            player_teams.c.player_id == player_id,
            player_teams.c.team_id == team_id,
        ).values(position=position))

        # Create PlayerTeamSeason record for current season
        player_team_season = PlayerTeamSeason(
            player_id=player_id,
            team_id=team_id,
            season_id=league.season_id,
            is_coach=bool(player.is_coach)  # best-effort; finalized at rollover
        )
        session.add(player_team_season)
        logger.info(f"Created PlayerTeamSeason record for {player.name} to {team.name} in season {league.season_id}")

        # Auto-promote a division coach drafted onto a team in their division (mirrors web).
        try:
            from app.coach_assignment import apply_draft_coach_status
            apply_draft_coach_status(session, player_id, team_id, team.league.name, league.season_id)
        except Exception as _coach_err:
            logger.warning(f"Mobile auto coach-assignment skipped for player {player_id}: {_coach_err}")

        # A rostered player must not keep a Pub League sub role. Drop any
        # Classic/Premier sub-pool membership + Flask sub role in THIS txn; the
        # Discord reconcile queued post-commit then strips the stale sub role.
        # ECS FC sub status is intentionally preserved. Mirrors the web socket path.
        sub_cleanup = None
        try:
            from app.services.sub_status_service import remove_conflicting_sub_status
            sub_cleanup = remove_conflicting_sub_status(
                session, player_id, performed_by_user_id=current_user_id
            )
        except Exception as _sub_err:
            logger.warning(f"Mobile sub-status cleanup skipped for player {player_id}: {_sub_err}")

        # Record draft pick. SAVEPOINT (begin_nested) so a history-write DB failure
        # (e.g. an ECS FC player re-drafted to a 2nd team hits the player-uniqueness
        # constraint) confines the rollback to the savepoint and does NOT poison the
        # transaction that holds the actual roster write + clock advance.
        draft_position = 0
        try:
            with session.begin_nested():
                draft_position = DraftService.record_draft_pick(
                    session=session,
                    player_id=player_id,
                    team_id=team_id,
                    league_id=league.id,
                    season_id=league.season_id,
                    drafted_by_user_id=current_user_id,
                    notes=f"Drafted via mobile API by {user.username}"
                )
        except Exception as e:
            logger.error(f"Failed to record draft pick (non-fatal): {e}")
            draft_position = 0

        # Advance the clock UNDER THE SAME LOCK (only when the on-the-clock team picked;
        # an admin's out-of-turn add leaves the clock put). Commit on with-exit releases
        # the lock atomically after the write + advance are both persisted.
        clock_payload = None
        advanced = False
        if ds and ds.status == 'active':
            if not ds.current_team_id or ds.current_team_id == team_id:
                clock_payload = draft_clock.advance(session, ds)
                advanced = True
            else:
                clock_payload = draft_clock.build_state(session, ds)

        # Capture everything needed for the response + broadcasts while still attached.
        url_name = league_name.lower()
        player_name = player.name
        player_pos_label = label_for(player.favorite_position)
        team_name = team.name
        try:
            enhanced = DraftService.get_enhanced_player_data([player], league.season_id)[0]
        except Exception:
            enhanced = {
                'id': player.id, 'name': player.name,
                'favorite_position': player.favorite_position or 'Any',
                'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
            }
    # ---- lock released (transaction committed) ----

    # Post-commit side effects (NO lock held — never do broker/Discord/cache I/O inside
    # the FOR UPDATE txn): coach push, Discord, cache, live broadcasts. `ds` is detached
    # here but its column attributes were loaded/advanced above, so reads are safe.
    if advanced:
        draft_clock.queue_on_clock_push(ds)  # ping the NEXT team's coaches
    with managed_session() as s2:
        mark_player_for_discord_update(s2, player_id)
    assign_roles_to_player_task.delay(player_id=player_id, only_add=True)
    DraftCacheService.clear_all_league_caches(db_league_name)

    _emit_to_draft_rooms('player_drafted_enhanced', {
        'success': True, 'player': enhanced, 'team_id': team_id, 'team_name': team_name,
        'league_name': url_name, 'position': position, 'draft_position': draft_position,
    }, url_name, db_league_name)
    if clock_payload:
        _emit_to_draft_rooms('draft_clock_update', clock_payload, url_name, db_league_name)

    return jsonify({
        "success": True,
        "message": f"{player_name} drafted to {team_name}",
        "player": {"id": player_id, "name": player_name, "position": player_pos_label},
        "team": {"id": team_id, "name": team_name},
        "draft_position": draft_position,
        "clock": clock_payload
    }), 200


@mobile_api_v2.route('/draft/<league_name>/pick/<int:player_id>', methods=['DELETE'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def remove_player_from_team(league_name: str, player_id: int):
    """
    Remove a player from their team (return to available pool).

    Args:
        league_name: URL-friendly league name
        player_id: ID of player to remove

    Returns:
        JSON with removal result
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        # Get league from current season
        league = session.query(League).join(Season).filter(
            League.name == db_league_name,
            Season.is_current == True
        ).first()

        if not league:
            return jsonify({"msg": "League not found"}), 404

        # Get player
        player = session.query(Player).options(
            selectinload(Player.teams)
        ).get(player_id)

        if not player:
            return jsonify({"msg": "Player not found"}), 404

        # Find which team the player is on in this league
        team = None
        for t in player.teams:
            if t.league_id == league.id:
                team = t
                break

        if not team:
            return jsonify({"msg": "Player is not on a team in this league"}), 400

        team_name = team.name

        # Remove player from team
        team.players.remove(player)

        # Clear primary team if it was this team
        if player.primary_team_id == team.id:
            player.primary_team_id = None

        # Remove from draft history
        try:
            DraftService.remove_draft_pick(
                session=session,
                player_id=player_id,
                season_id=league.season_id,
                league_id=league.id
            )
        except Exception as e:
            logger.error(f"Failed to remove draft pick record: {e}")

        session.commit()

        # Mark player for Discord update and remove roles
        mark_player_for_discord_update(session, player_id)
        remove_player_roles_task.delay(player_id=player_id, team_id=team.id)

        # Invalidate cache
        DraftCacheService.clear_all_league_caches(db_league_name)

        # Broadcast so the web board / other phones drop the card live.
        _emit_to_draft_rooms('player_removed_enhanced', {
            'success': True,
            'player': {'id': player_id, 'name': player.name},
            'team_id': team.id,
            'team_name': team_name,
            'league_name': league_name.lower(),
        }, league_name.lower(), db_league_name)

        return jsonify({
            "success": True,
            "message": f"{player.name} removed from {team_name}",
            "player_id": player_id,
            "player_name": player.name
        }), 200


@mobile_api_v2.route('/draft/<league_name>/team/<int:team_id>/analysis', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_team_position_analysis(league_name: str, team_id: int):
    """
    Get position analysis for a team showing needs and recommended players.

    Args:
        league_name: URL-friendly league name
        team_id: Team ID

    Returns:
        JSON with position needs and player recommendations
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        try:
            from app.draft_position_analyzer import PositionAnalyzer
        except ImportError:
            return jsonify({"msg": "Position analyzer not available"}), 500

        # Get league from current season
        league = session.query(League).join(Season).filter(
            League.name == db_league_name,
            Season.is_current == True
        ).first()

        if not league:
            return jsonify({"msg": "League not found"}), 404

        # Get team
        team = session.query(Team).filter(
            Team.id == team_id,
            Team.league_id == league.id
        ).first()

        if not team:
            return jsonify({"msg": "Team not found in this league"}), 404

        # Get current team players
        team_players = [p for p in team.players if p.is_current_player]

        # Calculate team needs
        team_needs = PositionAnalyzer.calculate_team_needs(team_players)

        # Get available players
        all_teams = session.query(Team).filter(Team.league_id == league.id).all()
        drafted_player_ids = set()
        for t in all_teams:
            drafted_player_ids.update([p.id for p in t.players])

        available_players = session.query(Player).filter(
            Player.is_current_player == True,
            ~Player.id.in_(drafted_player_ids)
        ).limit(50).all()  # Limit for performance

        # Calculate fit scores
        player_recommendations = []
        for player in available_players:
            fit_score = PositionAnalyzer.calculate_fit_score(player, team_needs)
            if fit_score > 0:
                player_recommendations.append({
                    "player_id": player.id,
                    "player_name": player.name,
                    "position": label_for(player.favorite_position),
                    "fit_score": fit_score,
                    "fit_category": PositionAnalyzer.get_fit_category(fit_score)
                })

        # Sort by fit score descending
        player_recommendations.sort(key=lambda x: x['fit_score'], reverse=True)

        return jsonify({
            "team_id": team.id,
            "team_name": team.name,
            "current_roster_size": len(team_players),
            "position_needs": team_needs,
            "recommended_players": player_recommendations[:20]  # Top 20
        }), 200


@mobile_api_v2.route('/draft/<league_name>/history', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'ECS FC Coach', 'Pub League Admin', 'Global Admin'])
def get_draft_history(league_name: str):
    """
    Get draft order history for a league.

    Args:
        league_name: URL-friendly league name

    Query Parameters:
        season_id: Browse a PRIOR season's draft (default: current season)
        page: Page number (default: 1)
        per_page: Items per page (default: 50, max: 100)

    Returns:
        JSON with draft history
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    season_id = request.args.get('season_id', type=int)

    with managed_session() as session:
        if season_id:
            # Past-season browse: each season has its own League row with the same
            # name, so resolve the league for THAT (name, season).
            league = session.query(League).filter(
                League.name == db_league_name,
                League.season_id == season_id
            ).first()
        else:
            # Default to the current-season league.
            league = session.query(League).join(Season).filter(
                League.name == db_league_name,
                Season.is_current == True
            ).first()

        if not league:
            return jsonify({"msg": "League not found"}), 404

        # Get draft history
        query = session.query(DraftOrderHistory).options(
            joinedload(DraftOrderHistory.player),
            joinedload(DraftOrderHistory.team),
            joinedload(DraftOrderHistory.drafter)
        ).filter(
            DraftOrderHistory.league_id == league.id,
            DraftOrderHistory.season_id == league.season_id
        ).order_by(DraftOrderHistory.draft_position.asc())

        total_count = query.count()

        query = query.offset((page - 1) * per_page).limit(per_page)
        picks = query.all()

        # Batch-load the drafted FIELD position (pitch slot: 'st','bench','gk',...) for
        # the picks on this page. It lives on player_teams.position — NOT on
        # DraftOrderHistory — and is keyed by (player_id, team_id) so an ECS FC
        # multi-team player resolves to the correct roster spot. One query, no N+1.
        slot_by_key = {}
        _keys = [(p.player_id, p.team_id) for p in picks if p.player_id and p.team_id]
        if _keys:
            _pids = list({pid for pid, _ in _keys})
            _tids = list({tid for _, tid in _keys})
            for r in session.query(
                player_teams.c.player_id, player_teams.c.team_id, player_teams.c.position
            ).filter(
                player_teams.c.player_id.in_(_pids),
                player_teams.c.team_id.in_(_tids),
            ).all():
                slot_by_key[(r.player_id, r.team_id)] = r.position

        history = []
        for pick in picks:
            history.append({
                "position": pick.draft_position,
                # Drafted pitch slot ('st','bench','gk',...). Null if the roster spot
                # was since removed. Web shows this as "(ST)"; see the socket
                # player_drafted_enhanced 'position' field — same vocabulary.
                "field_position": slot_by_key.get((pick.player_id, pick.team_id)),
                "player": {
                    "id": pick.player.id,
                    "name": pick.player.name
                } if pick.player else None,
                "team": {
                    "id": pick.team.id,
                    "name": pick.team.name
                } if pick.team else None,
                # Draft-prep / edit note for this pick (DraftOrderHistory.notes).
                "notes": pick.notes,
                # Drafter attribution: flat `drafted_by` (kept for back-compat) plus a
                # nested `drafter` object the client also accepts. Only the username is
                # available on the User row here.
                "drafted_by": pick.drafter.username if pick.drafter else None,
                "drafter": {"username": pick.drafter.username} if pick.drafter else None,
                "drafted_at": pick.created_at.isoformat() if pick.created_at else None
            })

        return jsonify({
            "history": history,
            "season_id": league.season_id,
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "total_pages": (total_count + per_page - 1) // per_page
        }), 200


# =============================================================================
# On-the-clock draft: live clock state + admin clock controls (mobile parity
# with the web board). All mutations broadcast draft_clock_update (and, where a
# roster changes, player_drafted_enhanced / player_removed_enhanced) to the web
# socket rooms so the web board and every coach's phone stay in sync.
# =============================================================================

@mobile_api_v2.route('/draft/<league_name>/clock', methods=['GET'])
@jwt_required()
@jwt_role_required(DRAFT_ROLES)
def get_draft_clock(league_name: str):
    """Live on-the-clock state for the app to poll.

    Returns the full clock (whose turn, round/pick, server deadline, up-next,
    format incl. 'rotating', progress) plus, for the requesting coach:
      - my_team_ids: teams they coach in this league
      - on_clock_for_me: True when it's their team's pick (drives the in-app
        beep/vibrate; the push covers them when the app isn't foregrounded)
      - is_admin: whether they may run the clock controls
    `active` is False when no draft has been set up yet (free-form mode).
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    current_user_id = int(get_jwt_identity())
    with managed_session() as session:
        from app import draft_clock
        league = _current_league(session, db_league_name)
        if not league:
            return jsonify({"msg": f"No current {db_league_name} league found"}), 404

        my_ids = _my_coached_team_ids(session, current_user_id, league.id)
        is_admin = _user_is_admin(session, current_user_id)

        ds = draft_clock.get_session(session, league.season_id, league.id)
        if not ds:
            return jsonify({
                "active": False,
                "clock": None,
                "my_team_ids": my_ids,
                "on_clock_for_me": False,
                "is_admin": is_admin,
            }), 200

        state = draft_clock.build_state(session, ds)
        return jsonify({
            "active": ds.status in ('active', 'paused'),
            "clock": state,
            "my_team_ids": my_ids,
            "on_clock_for_me": bool(ds.current_team_id and ds.current_team_id in my_ids),
            "is_admin": is_admin,
        }), 200


def _clock_control(league_name, mutate, allow_states, err_msg, push_next=False):
    """Shared plumbing for the admin clock-control endpoints: resolve league + ds,
    guard status, apply `mutate(session, ds) -> state`, broadcast, and return.

    push_next=True fires the 'you're on the clock' push for the team the clock
    now points at (used by start/skip)."""
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        from app import draft_clock
        league = _current_league(session, db_league_name)
        if not league:
            return jsonify({"success": False, "msg": f"No current {db_league_name} league found"}), 404
        # Lock the session row so an admin clock change serialises against a concurrent
        # pick (which also locks it) — no double-advance across web/mobile.
        ds = draft_clock.get_session(session, league.season_id, league.id, for_update=True)
        if not ds or (allow_states is not None and ds.status not in allow_states):
            return jsonify({"success": False, "msg": err_msg}), 400
        state = mutate(session, ds, draft_clock, league)
        if push_next:
            draft_clock.queue_on_clock_push(ds)
        # commit happens on managed_session exit; broadcast after building the payload
    _emit_to_draft_rooms('draft_clock_update', state, league_name.lower(), db_league_name)
    return jsonify({"success": True, "state": state}), 200


@mobile_api_v2.route('/draft/<league_name>/start', methods=['POST'])
@jwt_required()
@jwt_role_required(DRAFT_ADMIN_ROLES)
def start_draft_clock(league_name: str):
    """Put the first team on the clock."""
    def _mutate(session, ds, draft_clock, league):
        from datetime import datetime
        team_ids = draft_clock.ordered_team_ids(session, ds)
        if not team_ids or not ds.rounds:
            raise ValueError('Set the pick order and rounds first')
        ds.status = 'active'
        ds.started_at = datetime.utcnow()
        ds.started_by = int(get_jwt_identity())
        ds.completed_at = None
        draft_clock.set_clock_to(ds, 1, team_ids)
        return draft_clock.build_state(session, ds, team_ids=team_ids)
    try:
        return _clock_control(league_name, _mutate, allow_states=None,
                              err_msg='No draft set up for this league', push_next=True)
    except ValueError as e:
        return jsonify({"success": False, "msg": str(e)}), 400


@mobile_api_v2.route('/draft/<league_name>/skip', methods=['POST'])
@jwt_required()
@jwt_role_required(DRAFT_ADMIN_ROLES)
def skip_draft_clock(league_name: str):
    """Advance the clock past the on-the-clock team WITHOUT recording a pick — the
    team forfeits this pick (e.g. a coach-held spot). Does not touch rosters."""
    def _mutate(session, ds, draft_clock, league):
        return draft_clock.advance(session, ds)
    return _clock_control(league_name, _mutate, allow_states=('active', 'paused'),
                          err_msg='No live draft to advance', push_next=True)


@mobile_api_v2.route('/draft/<league_name>/pause', methods=['POST'])
@jwt_required()
@jwt_role_required(DRAFT_ADMIN_ROLES)
def pause_draft_clock(league_name: str):
    def _mutate(session, ds, draft_clock, league):
        from datetime import datetime
        if ds.pick_deadline:
            ds.pause_remaining_seconds = max(0, int((ds.pick_deadline - datetime.utcnow()).total_seconds()))
        ds.status = 'paused'
        ds.pick_deadline = None
        return draft_clock.build_state(session, ds)
    return _clock_control(league_name, _mutate, allow_states=('active',),
                          err_msg='No active draft to pause')


@mobile_api_v2.route('/draft/<league_name>/resume', methods=['POST'])
@jwt_required()
@jwt_role_required(DRAFT_ADMIN_ROLES)
def resume_draft_clock(league_name: str):
    def _mutate(session, ds, draft_clock, league):
        from datetime import datetime, timedelta
        ds.status = 'active'
        if ds.seconds_per_pick:
            # `or`, not `is not None`: a stored 0 means "no time left" -> give a fresh clock.
            secs = ds.pause_remaining_seconds or ds.seconds_per_pick
            ds.pick_deadline = datetime.utcnow() + timedelta(seconds=secs)
        ds.pause_remaining_seconds = None
        return draft_clock.build_state(session, ds)
    return _clock_control(league_name, _mutate, allow_states=('paused',),
                          err_msg='No paused draft to resume')


@mobile_api_v2.route('/draft/<league_name>/end', methods=['POST'])
@jwt_required()
@jwt_role_required(DRAFT_ADMIN_ROLES)
def end_draft_clock(league_name: str):
    """End the draft immediately (admin stop)."""
    def _mutate(session, ds, draft_clock, league):
        return draft_clock.complete(session, ds)
    return _clock_control(league_name, _mutate, allow_states=('active', 'paused'),
                          err_msg='No live draft to end')


@mobile_api_v2.route('/draft/<league_name>/back', methods=['POST'])
@jwt_required()
@jwt_role_required(DRAFT_ADMIN_ROLES)
def back_draft_clock(league_name: str):
    """Move the clock BACK one pick (admin correction). Does NOT un-draft a player —
    use undo-last for that. Optional body {team_id} guards against rewinding when the
    last action was an out-of-turn add that never advanced the clock."""
    data = request.get_json(silent=True) or {}
    undone_team_id = data.get('team_id')

    def _mutate(session, ds, draft_clock, league):
        team_ids = draft_clock.ordered_team_ids(session, ds)
        should_step = True
        if undone_team_id and ds.status != 'complete':
            prev = (ds.current_overall_pick or 1) - 1
            on_clock_prev = draft_clock.team_on_clock(team_ids, ds.format, prev)[0] if prev >= 1 else None
            should_step = (on_clock_prev == int(undone_team_id))
        if should_step:
            return draft_clock.step_back(session, ds)
        return draft_clock.build_state(session, ds, team_ids=team_ids)
    return _clock_control(league_name, _mutate, allow_states=('active', 'paused', 'complete'),
                          err_msg='No live draft to step back')


@mobile_api_v2.route('/draft/<league_name>/undo-last', methods=['POST'])
@jwt_required()
@jwt_role_required(DRAFT_ADMIN_ROLES)
def undo_last_pick(league_name: str):
    """Undo the most recent pick: remove that player from their team AND step the
    clock back onto them. The real 'oops' button. Broadcasts the removal + clock."""
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        from app import draft_clock
        league = _current_league(session, db_league_name)
        if not league:
            return jsonify({"success": False, "msg": f"No current {db_league_name} league found"}), 404

        # Lock the session row FIRST so the whole undo (read last pick → remove → step back)
        # serialises against any concurrent pick, which also locks it. ds may be None if the
        # draft was never set up as an on-the-clock session (pure free-form) — that's fine.
        ds = draft_clock.get_session(session, league.season_id, league.id, for_update=True)

        last = session.query(DraftOrderHistory).filter(
            DraftOrderHistory.league_id == league.id,
            DraftOrderHistory.season_id == league.season_id
        ).order_by(DraftOrderHistory.draft_position.desc()).first()
        if not last or not last.player_id or not last.team_id:
            return jsonify({"success": False, "msg": "Nothing to undo"}), 400

        undo_player_id = last.player_id
        undo_team_id = last.team_id

        player = session.query(Player).options(selectinload(Player.teams)).get(undo_player_id)
        team = session.query(Team).filter(Team.id == undo_team_id).first()
        player_name = player.name if player else 'Player'
        team_name = team.name if team else 'team'

        # Remove from the team roster (mirrors the DELETE endpoint's removal).
        if player and team and team in player.teams:
            team.players.remove(player)
        if player and player.primary_team_id == undo_team_id:
            player.primary_team_id = None
        try:
            DraftService.remove_draft_pick(
                session=session, player_id=undo_player_id,
                season_id=league.season_id, league_id=league.id
            )
        except Exception as e:
            logger.error(f"undo-last: failed to remove draft pick record: {e}")

        # Step the clock back onto the undone pick, but only if that pick actually
        # advanced the clock (guards an out-of-turn add — same logic as /back).
        clock_state = None
        if ds:
            team_ids = draft_clock.ordered_team_ids(session, ds)
            should_step = True
            if ds.status != 'complete':
                prev = (ds.current_overall_pick or 1) - 1
                on_clock_prev = draft_clock.team_on_clock(team_ids, ds.format, prev)[0] if prev >= 1 else None
                should_step = (on_clock_prev == undo_team_id)
            clock_state = draft_clock.step_back(session, ds) if should_step else \
                draft_clock.build_state(session, ds, team_ids=team_ids)
        # commit on exit

    with managed_session() as s2:
        mark_player_for_discord_update(s2, undo_player_id)
    remove_player_roles_task.delay(player_id=undo_player_id, team_id=undo_team_id)
    DraftCacheService.clear_all_league_caches(db_league_name)

    url_name = league_name.lower()
    _emit_to_draft_rooms('player_removed_enhanced', {
        'success': True,
        'player': {'id': undo_player_id, 'name': player_name},
        'team_id': undo_team_id,
        'team_name': team_name,
        'league_name': url_name,
    }, url_name, db_league_name)
    if clock_state:
        _emit_to_draft_rooms('draft_clock_update', clock_state, url_name, db_league_name)

    return jsonify({
        "success": True,
        "message": f"Undid {player_name} → {team_name}",
        "player_id": undo_player_id,
        "team_id": undo_team_id,
        "state": clock_state,
    }), 200


# =============================================================================
# Draft setup (configure + optionally start the on-the-clock session) — admin only.
# Mobile equivalent of the web /admin_panel/draft/session/setup + /start routes.
# =============================================================================

@mobile_api_v2.route('/draft/<league_name>/setup', methods=['POST'])
@jwt_required()
@jwt_role_required(DRAFT_ADMIN_ROLES)
def setup_draft_session(league_name: str):
    """Create/replace the on-the-clock config for a league, and optionally start it.

    Body: team_order (required, ordered team ids), format, seconds_per_pick, rounds,
    min_new_players, min_admins, timeout_action, lock_to_clock, start.
    When start=true the first team is put on the clock (status -> active); otherwise
    the config is saved and status stays 'setup'.

    Response: {success, state} where state is the clock object (same shape as
    GET /clock's `clock`), so the app can drive the board straight from the reply.
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    data = request.get_json() or {}
    team_order = data.get('team_order') or []
    if not team_order:
        return jsonify({"success": False, "msg": "team_order is required"}), 400

    from datetime import datetime
    from app import draft_clock

    started = False
    with managed_session() as session:
        league = _current_league(session, db_league_name)
        if not league:
            return jsonify({"success": False, "msg": f"No current {db_league_name} league found"}), 404

        # Validate every team belongs to THIS league (no cross-league pick order).
        valid_ids = {t[0] for t in session.query(Team.id).filter(Team.league_id == league.id).all()}
        bad = [tid for tid in team_order if tid not in valid_ids]
        if bad:
            return jsonify({"success": False, "msg": f"Teams not in this league: {bad}"}), 400

        # Lock the session row so setup serialises against any live pick/clock change.
        ds = draft_clock.get_session(session, league.season_id, league.id, for_update=True)
        if not ds:
            ds = DraftSession(season_id=league.season_id, league_id=league.id)
            session.add(ds)
            session.flush()
        elif ds.status == 'active':
            return jsonify({"success": False,
                            "msg": "Draft is active — pause or reset before changing the order"}), 409

        fmt = (data.get('format') or 'snake').lower()
        ds.format = fmt if fmt in ('snake', 'linear', 'rotating') else 'snake'
        ds.seconds_per_pick = max(0, int(data.get('seconds_per_pick', 90) or 0))
        timeout_action = (data.get('timeout_action') or 'alert').lower()
        ds.timeout_action = timeout_action if timeout_action in ('alert', 'skip', 'pause') else 'alert'
        ds.lock_to_clock = bool(data.get('lock_to_clock', True))
        ds.rounds = max(0, int(data.get('rounds') or 0))
        ds.min_new_players = max(0, int(data.get('min_new_players') or 0))
        ds.min_admins = max(0, int(data.get('min_admins') or 0))
        # reset live state to a clean 'setup'
        ds.status = 'setup'
        ds.current_overall_pick = None
        ds.current_round = None
        ds.current_team_id = None
        ds.pick_deadline = None
        ds.pause_remaining_seconds = None
        ds.completed_at = None

        # Replace the pick-order slots (bulk delete executes immediately, so the
        # unique (session, slot)/(session, team) constraints don't trip on re-add).
        session.query(DraftPickSlot).filter_by(draft_session_id=ds.id).delete()
        for i, tid in enumerate(team_order, start=1):
            session.add(DraftPickSlot(draft_session_id=ds.id, team_id=tid, slot=i))
        session.flush()

        if data.get('start'):
            team_ids = draft_clock.ordered_team_ids(session, ds)
            if not team_ids or not ds.rounds:
                return jsonify({"success": False, "msg": "Set the pick order and rounds first"}), 400
            ds.status = 'active'
            ds.started_at = datetime.utcnow()
            ds.started_by = int(get_jwt_identity())
            draft_clock.set_clock_to(ds, 1, team_ids)
            started = True

        state = draft_clock.build_state(session, ds)
    # ---- committed ----

    if started:
        draft_clock.queue_on_clock_push(ds)  # ping the first team's coaches
    _emit_to_draft_rooms('draft_clock_update', state, league_name.lower(), db_league_name)
    return jsonify({"success": True, "state": state}), 200


# =============================================================================
# Reposition a drafted player's pitch slot — admin or the player's own coach.
# Mobile equivalent of the update_player_position socket event. Path-shaped to
# match the Flutter contract (/pick/<player_id>/position).
# =============================================================================

@mobile_api_v2.route('/draft/<league_name>/pick/<int:player_id>/position', methods=['PATCH'])
@jwt_required()
@jwt_role_required(DRAFT_ROLES)
def reposition_drafted_player(league_name: str, player_id: int):
    """Update the pitch slot (gk..bench) on an existing player_teams row.

    Body: {team_id, position}. Admins may reposition any team's player; a coach may
    only reposition on a team they coach. Broadcasts player_position_updated so the
    web board + other phones move the card live.
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    data = request.get_json() or {}
    team_id = data.get('team_id')
    position = (data.get('position') or '').lower()
    if not team_id:
        return jsonify({"success": False, "msg": "team_id is required"}), 400
    if position not in VALID_PITCH_POSITIONS:
        return jsonify({"success": False, "msg": f"Invalid position: {position}"}), 400

    current_user_id = int(get_jwt_identity())
    from sqlalchemy import update as _sa_update

    with managed_session() as session:
        league = _current_league(session, db_league_name)
        if not league:
            return jsonify({"success": False, "msg": f"No current {db_league_name} league found"}), 404

        # Team must be in this league.
        team = session.query(Team).filter(Team.id == team_id, Team.league_id == league.id).first()
        if not team:
            return jsonify({"success": False, "msg": "Team not found in this league"}), 404

        # Permission: admin, or a coach of THIS team.
        if not _user_is_admin(session, current_user_id):
            if int(team_id) not in _my_coached_team_ids(session, current_user_id, league.id):
                return jsonify({"success": False, "msg": "You don't coach this team"}), 403

        result = session.execute(_sa_update(player_teams).where(
            player_teams.c.player_id == player_id,
            player_teams.c.team_id == team_id,
        ).values(position=position))
        if result.rowcount == 0:
            return jsonify({"success": False, "msg": "Player is not on this team"}), 404

        player = session.query(Player).get(player_id)
        player_name = player.name if player else 'Player'
        team_name = team.name
        profile_url = player.profile_picture_url if player else None
        fav = player.favorite_position if player else None
    # ---- committed ----

    _emit_to_draft_rooms('player_position_updated', {
        'player': {'id': player_id, 'name': player_name,
                   'profile_picture_url': profile_url, 'favorite_position': fav},
        'team_id': team_id,
        'team_name': team_name,
        'position': position,
        'league_name': league_name.lower(),
    }, league_name.lower(), db_league_name)

    return jsonify({"success": True, "player_id": player_id,
                    "team_id": team_id, "position": position}), 200


# =============================================================================
# Seasons with draft history (drives the mobile past-season picker) — view roles.
# =============================================================================

@mobile_api_v2.route('/draft/<league_name>/seasons', methods=['GET'])
@jwt_required()
@jwt_role_required(DRAFT_ROLES)
def get_draft_seasons(league_name: str):
    """Seasons that have at least one recorded pick for a league of this name, newest
    first. Returns a bare array [{id, name, is_current}] per the mobile contract."""
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    with managed_session() as session:
        rows = session.query(
            Season.id, Season.name, Season.is_current
        ).join(League, League.season_id == Season.id).join(
            DraftOrderHistory, DraftOrderHistory.league_id == League.id
        ).filter(
            League.name == db_league_name
        ).distinct().order_by(Season.id.desc()).all()

        seasons = [
            {"id": r.id, "name": r.name, "is_current": bool(r.is_current)}
            for r in rows
        ]
        return jsonify(seasons), 200


# =============================================================================
# Admin history editing (M6): edit a pick's number/slot/notes, and normalize the
# pick sequence. Admin only — mirrors the web edit-pick modal + normalize button.
# =============================================================================

@mobile_api_v2.route('/draft/<league_name>/pick/<int:player_id>', methods=['PATCH'])
@jwt_required()
@jwt_role_required(DRAFT_ADMIN_ROLES)
def edit_draft_pick(league_name: str, player_id: int):
    """Edit an existing pick for this player in the current-season league.

    Body (all optional): draft_position (int), position (pitch slot str), notes (str),
    mode ('cascading'|'smart'|'absolute'|'insert', default 'cascading') — how a
    draft_position change re-sequences the other picks. Mirrors the web edit modal.
    """
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    data = request.get_json() or {}
    new_position = data.get('draft_position')
    new_slot = data.get('position')
    new_notes = data.get('notes')
    mode = (data.get('mode') or 'cascading').lower()

    with managed_session() as session:
        league = _current_league(session, db_league_name)
        if not league:
            return jsonify({"success": False, "msg": f"No current {db_league_name} league found"}), 404

        pick = session.query(DraftOrderHistory).filter(
            DraftOrderHistory.league_id == league.id,
            DraftOrderHistory.season_id == league.season_id,
            DraftOrderHistory.player_id == player_id,
        ).first()
        if not pick:
            return jsonify({"success": False, "msg": "No draft pick for this player"}), 404

        from datetime import datetime
        position_changed = False
        swap_result = None

        # 1) Pick number (draft_position) — re-sequences per `mode`.
        if new_position is not None and int(new_position) != pick.draft_position:
            new_position = int(new_position)
            if mode == 'absolute':
                swap_result = DraftService.set_absolute_draft_position(session, pick.id, new_position)
            elif mode == 'smart':
                swap_result = DraftService.insert_draft_position_smart(session, pick.id, new_position)
            elif mode == 'insert':
                swap_result = DraftService.insert_draft_position(session, pick.id, new_position)
            else:
                swap_result = DraftService.swap_draft_positions(session, pick.id, new_position)
            if not swap_result.get('success'):
                return jsonify(swap_result), 400
            position_changed = True

        # 2) Pitch slot — lives on player_teams.position, keyed by (player, team).
        slot_changed = False
        if new_slot is not None:
            slot = str(new_slot).lower()
            if slot not in VALID_PITCH_POSITIONS:
                return jsonify({"success": False, "msg": f"Invalid position: {new_slot}"}), 400
            from sqlalchemy import update as _sa_update
            session.execute(_sa_update(player_teams).where(
                player_teams.c.player_id == player_id,
                player_teams.c.team_id == pick.team_id,
            ).values(position=slot))
            slot_changed = True

        # 3) Notes.
        notes_changed = False
        if new_notes is not None:
            cleaned = (new_notes or '').strip() or None
            if cleaned != pick.notes:
                pick.notes = cleaned
                pick.updated_at = datetime.utcnow()
                notes_changed = True

        response = {
            "success": True,
            "pick": {
                "player_id": player_id,
                "team_id": pick.team_id,
                "draft_position": pick.draft_position,
                "notes": pick.notes,
            },
            "position_changed": position_changed,
            "slot_changed": slot_changed,
            "notes_changed": notes_changed,
            "affected_picks": swap_result.get('affected_picks', 0) if swap_result else 0,
        }
    # ---- committed ----

    DraftCacheService.clear_all_league_caches(db_league_name)
    return jsonify(response), 200


@mobile_api_v2.route('/draft/<league_name>/normalize-positions', methods=['POST'])
@jwt_required()
@jwt_role_required(DRAFT_ADMIN_ROLES)
def normalize_draft_positions(league_name: str):
    """Re-sequence the current-season league's pick numbers to close gaps
    (1,2,4,7 -> 1,2,3,4). Returns the normalize result plus the live clock."""
    db_league_name = get_db_league_name(league_name)
    if not db_league_name:
        return jsonify({"msg": f"Invalid league name: {league_name}"}), 400

    from app import draft_clock

    with managed_session() as session:
        league = _current_league(session, db_league_name)
        if not league:
            return jsonify({"success": False, "msg": f"No current {db_league_name} league found"}), 404

        result = DraftService.normalize_draft_positions(session, league.season_id, league.id)

        ds = draft_clock.get_session(session, league.season_id, league.id)
        clock = draft_clock.build_state(session, ds) if ds else None
        result['clock'] = clock
    # ---- committed ----

    DraftCacheService.clear_all_league_caches(db_league_name)
    return jsonify(result), 200
