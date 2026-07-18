# app/sockets/draft.py

"""
Socket.IO Draft Handlers

Handlers for draft room management and player drafting operations.
"""

import logging

from flask import g
from flask_socketio import emit, join_room

from app.core import socketio
from app.core.session_manager import managed_session
from app.models.ecs_fc import is_ecs_fc_league
from app.sockets.utils import get_draft_lock, cleanup_draft_lock

logger = logging.getLogger(__name__)


@socketio.on('join_draft_room', namespace='/')
def handle_join_draft_room(data):
    """Handle joining a draft room for a specific league."""
    from flask_login import current_user

    if not current_user.is_authenticated:
        emit('error', {'message': 'Authentication required'})
        return

    league_name = data.get('league_name')
    if league_name:
        room = f'draft_{league_name}'
        join_room(room)
        emit('joined_room', {'room': room, 'league': league_name})
        logger.info(f"User {current_user.username} joined room: {room}")


@socketio.on('draft_player_enhanced', namespace='/')
def handle_draft_player_enhanced(data):
    """Handle player drafting with comprehensive error handling and race condition protection."""
    # Data validation first (before acquiring locks)
    player_id = data.get('player_id')
    team_id = data.get('team_id')
    league_name = data.get('league_name')
    position = data.get('position', 'bench')  # Position from pitch view, defaults to bench

    if not all([player_id, team_id, league_name]):
        print(f"🚫 Missing data: {data}")
        emit('draft_error', {'message': 'Missing required data: player_id, team_id, or league_name'})
        return

    # Convert to integers
    try:
        player_id = int(player_id)
        team_id = int(team_id)
    except ValueError:
        print(f"🚫 Invalid ID format")
        emit('draft_error', {'message': 'Invalid player or team ID format'})
        return

    # Acquire player-specific Redis distributed lock to prevent race conditions
    draft_lock = get_draft_lock(player_id)

    # Use blocking=True with the pre-configured blocking_timeout (5 seconds)
    # Redis lock.acquire() returns True if acquired, False if timeout
    if not draft_lock.acquire(blocking=True):
        print(f"🚫 Draft operation timeout for player {player_id} - possibly concurrent request")
        emit('draft_error', {'message': 'Draft operation in progress for this player, please wait'})
        return

    try:
        print(f"🎯 Draft player request: {data}")
        logger.info(f"🎯 Draft player request: {data}")

        # Authentication check using Flask-Login's current_user
        from flask_login import current_user

        print(f"🔍 Draft auth check: current_user.is_authenticated = {current_user.is_authenticated}")
        logger.info(f"🔍 Draft auth check: current_user.is_authenticated = {current_user.is_authenticated}")

        if not current_user.is_authenticated:
            print("🚫 Unauthenticated draft attempt")
            emit('draft_error', {'message': 'Authentication required'})
            return

        # Phase 5: Broadcast user activity to all clients in room
        player_name_from_request = data.get('player_name', 'a player')
        username = current_user.username if hasattr(current_user, 'username') else 'Someone'
        emit('user_drafting', {
            'username': username,
            'player_name': player_name_from_request,
            'team_name': None  # Will be filled after team is fetched
        }, room=f'draft_{league_name}')

        # Database operations - Split into 3 optimized transactions
        from app.models import Player, Team, League, player_teams, Season, PlayerTeamSeason
        from app.db_utils import mark_player_for_discord_update
        from app.draft_enhanced import DraftService
        from sqlalchemy.orm import joinedload

        # Normalize league name
        db_league_name = {
            'classic': 'Classic',
            'premier': 'Premier',
            'ecs_fc': 'ECS FC'
        }.get(league_name.lower(), league_name)

        # Store validated IDs for subsequent transactions
        league_id = None
        season_id = None
        player_name = None
        team_name = None

        try:
            # ===== TRANSACTION 1: Read-only validation (~100ms) =====
            with managed_session() as session:
                # Get league (check if its season is current)
                league = session.query(League).join(Season).filter(
                    League.name == db_league_name,
                    Season.is_current == True
                ).first()

                if not league:
                    print(f"🚫 League not found: {db_league_name}")
                    emit('draft_error', {'message': f'League "{db_league_name}" not found'})
                    return

                league_id = league.id
                season_id = league.season_id

                # Get player and team (lightweight query without joinedload)
                player = session.query(Player).filter(Player.id == player_id).first()
                team = session.query(Team).filter(
                    Team.id == team_id,
                    Team.league_id == league.id
                ).first()

                if not player:
                    print(f"🚫 Player not found: {player_id}")
                    emit('draft_error', {'message': f'Player with ID {player_id} not found'})
                    return

                if not team:
                    print(f"🚫 Team not found: {team_id}")
                    emit('draft_error', {'message': f'Team with ID {team_id} not found'})
                    return

                player_name = player.name
                team_name = team.name

                # On-the-clock enforcement (ADDITIVE: no-op when no active DraftSession exists,
                # so free-form drafts behave exactly as before).
                try:
                    from app import draft_clock
                    ds = draft_clock.get_session(session, season_id, league_id)
                    if (ds and ds.status == 'active' and ds.lock_to_clock
                            and ds.current_team_id and ds.current_team_id != team_id):
                        # Admins may draft OUT OF TURN (an extra pick / correction for a team
                        # that isn't on the clock). This does not consume the on-the-clock
                        # team's turn — the clock only advances when THAT team picks (below).
                        # Query the roles via the live session (current_user.has_role lazy-loads
                        # a relationship that may not be attached in the socket context).
                        is_admin = False
                        try:
                            from app.models.core import Role, user_roles
                            uid = getattr(current_user, 'id', None)
                            if uid:
                                is_admin = session.query(user_roles.c.user_id).join(
                                    Role, Role.id == user_roles.c.role_id
                                ).filter(
                                    user_roles.c.user_id == uid,
                                    Role.name.in_(['Global Admin', 'Pub League Admin']),
                                ).first() is not None
                        except Exception:
                            is_admin = False
                        if not is_admin:
                            on_clock = session.query(Team).filter(Team.id == ds.current_team_id).first()
                            on_clock_name = on_clock.name if on_clock else 'another team'
                            print(f"🚫 Out-of-turn pick blocked: {team_name} (on the clock: {on_clock_name})")
                            emit('draft_error', {'message': f"It's {on_clock_name}'s pick — they're on the clock"})
                            return
                        print(f"🛡️ Admin out-of-turn pick allowed: {team_name} (clock stays on team {ds.current_team_id})")
                except Exception as _clock_err:
                    logger.warning(f"Draft on-the-clock check skipped: {_clock_err}")

                # Comprehensive check for existing assignment
                existing_player_team = session.query(player_teams).filter(
                    player_teams.c.player_id == player_id,
                    player_teams.c.team_id.in_(
                        session.query(Team.id).filter(Team.league_id == league.id)
                    )
                ).first()

                # ECS FC allows multi-team membership, skip check for ECS FC leagues
                if existing_player_team and not is_ecs_fc_league(league.id):
                    existing_team = session.query(Team).filter(Team.id == existing_player_team.team_id).first()
                    team_name_existing = existing_team.name if existing_team else "unknown team"
                    print(f"🚫 Player {player.name} already assigned to {team_name_existing} in {league.name}")
                    emit('draft_error', {'message': f'Player "{player.name}" is already assigned to {team_name_existing} in {league.name}'})
                    return

                # Check PlayerTeamSeason for current season
                existing_pts = session.query(PlayerTeamSeason).filter(
                    PlayerTeamSeason.player_id == player_id,
                    PlayerTeamSeason.season_id == season_id,
                    PlayerTeamSeason.team_id.in_(
                        session.query(Team.id).filter(Team.league_id == league.id)
                    )
                ).first()

                # ECS FC allows multi-team membership, skip check for ECS FC leagues
                if existing_pts and not is_ecs_fc_league(league.id):
                    existing_team = session.query(Team).filter(Team.id == existing_pts.team_id).first()
                    team_name_existing = existing_team.name if existing_team else "unknown team"
                    print(f"🚫 Player {player.name} already has PlayerTeamSeason record with {team_name_existing} in season {season_id}")
                    emit('draft_error', {'message': f'Player "{player.name}" is already assigned to {team_name_existing} for this season'})
                    return
            # Transaction 1 committed automatically - connection released

            # ===== TRANSACTION 2: Core write + history, ALL under the FOR UPDATE lock =====
            # Claim the turn ATOMICALLY: lock the draft_session row FOR UPDATE so this
            # write + advance serialise against any concurrent pick (web OR mobile) for
            # this draft. A racing pick blocks here until we commit, then check_turn sees
            # the clock has moved and rejects it — that is what prevents a double-draft.
            #
            # H5/M3: the already-drafted RE-CHECK and the draft-history write are BOTH
            # done here under the lock now (they used to run unlocked — T1 and a later
            # T3). Unlocked, a web+mobile race on the same player could double-roster,
            # and two unserialised history writes could collide on the draft_position
            # unique constraint and silently drop a row. Under the lock, both are safe.
            advanced_clock = False
            ds_present = False
            draft_position = None
            with managed_session() as session:
                from app import draft_clock
                ds = draft_clock.get_session(session, season_id, league_id, for_update=True)
                ds_present = ds is not None
                if ds is not None:
                    is_admin = False
                    try:
                        from app.models.core import Role, user_roles
                        uid = getattr(current_user, 'id', None)
                        if uid:
                            is_admin = session.query(user_roles.c.user_id).join(
                                Role, Role.id == user_roles.c.role_id
                            ).filter(
                                user_roles.c.user_id == uid,
                                Role.name.in_(['Global Admin', 'Pub League Admin']),
                            ).first() is not None
                    except Exception:
                        is_admin = False
                    ok, code = draft_clock.check_turn(ds, team_id, is_admin, data.get('expected_pick'))
                    if not ok:
                        if code == 'stale':
                            emit('draft_error', {'message': 'The board moved on — refresh and try again'})
                        else:
                            oc = session.query(Team).filter(Team.id == ds.current_team_id).first()
                            emit('draft_error', {'message': f"It's {oc.name if oc else 'another team'}'s pick — they're on the clock"})
                        return

                # H5: re-check the already-drafted guard UNDER the lock (T1's identical
                # check is unlocked, so a concurrent mobile pick of the same player to a
                # DIFFERENT team could have committed since). ECS FC permits multi-team
                # membership and is exempt. This mirrors the mobile pick path.
                if not is_ecs_fc_league(league_id):
                    conflict = session.query(player_teams).filter(
                        player_teams.c.player_id == player_id,
                        player_teams.c.team_id != team_id,
                        player_teams.c.team_id.in_(
                            session.query(Team.id).filter(Team.league_id == league_id)
                        )
                    ).first()
                    if not conflict:
                        conflict = session.query(PlayerTeamSeason).filter(
                            PlayerTeamSeason.player_id == player_id,
                            PlayerTeamSeason.season_id == season_id,
                            PlayerTeamSeason.team_id != team_id,
                            PlayerTeamSeason.team_id.in_(
                                session.query(Team.id).filter(Team.league_id == league_id)
                            )
                        ).first()
                    if conflict:
                        oc = session.query(Team).filter(Team.id == conflict.team_id).first()
                        oc_name = oc.name if oc else 'another team'
                        print(f"🚫 Race guard (under lock): {player_name} already on {oc_name}")
                        emit('draft_error', {'message': f'Player "{player_name}" is already assigned to {oc_name}'})
                        return

                # Re-fetch player and team for this transaction
                player = session.query(Player).filter(Player.id == player_id).first()
                team = session.query(Team).options(
                    joinedload(Team.players)
                ).filter(Team.id == team_id).first()

                # Execute the draft with position support
                if player not in team.players:
                    # Insert directly into player_teams with position (instead of using ORM append)
                    from sqlalchemy import insert
                    stmt = insert(player_teams).values(
                        player_id=player_id,
                        team_id=team_id,
                        position=position
                    )
                    session.execute(stmt)
                    player.primary_team_id = team_id
                    print(f"🎯 Added {player_name} to {team_name} at position '{position}' and set as primary team (ID: {team_id})")
                else:
                    # Player already on team - update position if provided
                    from sqlalchemy import update
                    stmt = update(player_teams).where(
                        player_teams.c.player_id == player_id,
                        player_teams.c.team_id == team_id
                    ).values(position=position)
                    session.execute(stmt)
                    player.primary_team_id = team_id
                    print(f"🎯 {player_name} already on {team_name} - updated position to '{position}' and primary team ID to {team_id}")

                # Create PlayerTeamSeason record for current season
                player_team_season = PlayerTeamSeason(
                    player_id=player_id,
                    team_id=team_id,
                    season_id=season_id,
                    is_coach=bool(player.is_coach)  # best-effort; finalized at rollover
                )
                session.add(player_team_season)
                print(f"📝 Created new PlayerTeamSeason record for {player_name} to {team_name}")

                # Auto-promote a division coach (holder of the 'Premier Coach' / 'Classic Coach'
                # Flask role) who is drafted onto a team IN their division to that team's coach.
                # This flips player_teams.is_coach so the Discord role sync queued below grants
                # the division coach role. No-op for everyone who isn't a division coach.
                try:
                    from app.coach_assignment import apply_draft_coach_status
                    if apply_draft_coach_status(session, player_id, team_id,
                                                team.league.name, season_id):
                        print(f"👑 {player_name} is the {team.league.name} division coach — set as coach of {team_name}")
                except Exception as _coach_err:
                    logger.warning(f"Auto coach-assignment skipped for player {player_id}: {_coach_err}")

                # M3: record the draft pick in history UNDER THE LOCK (was an unlocked
                # T3) so draft_position allocation is serialised with the roster write —
                # no unique-constraint collision, no silently-lost history row.
                #
                # Wrapped in a SAVEPOINT (begin_nested): record_draft_pick flushes, and a
                # DB-level failure there (e.g. an ECS FC player re-drafted to a 2nd team
                # hits uq_draft_order_player_season_league) would otherwise poison the
                # WHOLE transaction and roll back the actual roster write + clock advance.
                # The savepoint confines a history-write failure to itself, so the pick
                # itself still commits — restoring the old "history failure is non-fatal"
                # guarantee while keeping the serialised position allocation.
                try:
                    with session.begin_nested():
                        draft_position = DraftService.record_draft_pick(
                            session=session,
                            player_id=player_id,
                            team_id=team_id,
                            league_id=league_id,
                            season_id=season_id,
                            drafted_by_user_id=current_user.id,
                            notes=f"Drafted via Socket by {current_user.username}"
                        )
                    print(f"📊 Draft pick #{draft_position} recorded for {player_name} to {team_name}")
                    logger.info(f"📊 Draft pick #{draft_position} recorded for {player_name} to {team_name}")
                except Exception as e:
                    # SAVEPOINT rolled back — the roster write + advance below stay intact.
                    print(f"⚠️ Failed to record draft pick (non-fatal): {str(e)}")
                    logger.error(f"Failed to record draft pick (non-fatal): {str(e)}")

                # Mark for Discord update (cheap flag write; safe under the lock)
                mark_player_for_discord_update(session, player_id)

                # Advance the clock UNDER THE SAME LOCK (only when the on-the-clock team made
                # this pick; an admin's out-of-turn add to a different team leaves it put).
                # M2: advance mutates the clock columns but SKIPS building the emit payload
                # (with_state=False) — build_state's ~5 read queries are moved out of the
                # lock (below) so the FOR UPDATE hold covers writes only.
                if ds is not None and ds.status == 'active':
                    if not ds.current_team_id or ds.current_team_id == team_id:
                        draft_clock.advance(session, ds, with_state=False)
                        advanced_clock = True
            # Transaction 2 committed automatically - lock + connection released

            # Ping the next team's coaches AFTER the lock is released (the .delay() is a
            # broker call — keep it out of the FOR UPDATE txn). ds is detached but its
            # advanced column attrs are loaded, so this read is safe.
            if advanced_clock:
                try:
                    draft_clock.queue_on_clock_push(ds)
                except Exception as _push_err:
                    logger.warning(f"on-the-clock push enqueue skipped: {_push_err}")

            # M2: build the clock state for the emit OUTSIDE the lock (pure reads). ds is
            # detached but its scalar columns are loaded (expire_on_commit=False), and
            # build_state only issues fresh reads via this new short session.
            clock_state = None
            if ds_present:
                try:
                    with managed_session() as _state_session:
                        clock_state = draft_clock.build_state(_state_session, ds)
                except Exception as _state_err:
                    logger.warning(f"Draft clock state build skipped: {_state_err}")

            # ===== Post-transaction: Queue async tasks and emit response =====
            # Queue Discord role assignment task AFTER all commits
            from app.tasks.tasks_discord import assign_roles_to_player_task
            assign_roles_to_player_task.delay(player_id=player_id, only_add=True)
            print(f"🎭 Queued Discord role update for {player_name} (only_add = True to keep existing roles)")
            logger.info(f"🎭 Queued Discord role update for {player_name} (only_add = True to keep existing roles)")

            # Fetch player data for response in a final read-only transaction
            with managed_session() as session:
                player = session.query(Player).filter(Player.id == player_id).first()

                # Roster-composition flags for the live per-team requirement counters.
                # 'new' = no team history in a PRIOR season (exclude the row we just wrote);
                # 'admin' = holds a Pub League Admin / Global Admin role.
                is_new_flag, is_admin_flag = False, False
                try:
                    from app.models import PlayerTeamSeason
                    from app.models.core import Role, user_roles
                    prior = session.query(PlayerTeamSeason.id).filter(
                        PlayerTeamSeason.player_id == player_id,
                        PlayerTeamSeason.season_id != season_id,
                    ).first()
                    is_new_flag = prior is None
                    if player and player.user_id:
                        arole = session.query(user_roles.c.user_id).join(
                            Role, Role.id == user_roles.c.role_id
                        ).filter(
                            user_roles.c.user_id == player.user_id,
                            Role.name.in_(['Pub League Admin', 'Global Admin']),
                        ).first()
                        is_admin_flag = arole is not None
                except Exception as _flag_err:
                    logger.warning(f"draft flags compute skipped: {_flag_err}")

                # Success response with full player data including all position fields
                response_data = {
                    'success': True,
                    'player': {
                        'id': player.id,
                        'name': player.name,
                        'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
                        'profile_picture_medium': getattr(player, 'profile_picture_medium', None) or player.profile_picture_url or '/static/img/default_player.png',
                        'profile_picture_webp': getattr(player, 'profile_picture_webp', None) or player.profile_picture_url or '/static/img/default_player.png',
                        'favorite_position': player.favorite_position or 'Any',
                        'other_positions': player.other_positions or '',
                        'positions_not_to_play': player.positions_not_to_play or '',
                        'is_ref': player.is_ref,
                        'career_goals': player.career_stats[0].goals if player.career_stats else 0,
                        'career_assists': player.career_stats[0].assists if player.career_stats else 0,
                        'career_yellow_cards': player.career_stats[0].yellow_cards if player.career_stats else 0,
                        'career_red_cards': player.career_stats[0].red_cards if player.career_stats else 0,
                        'avg_goals_per_season': (
                            round(player.career_stats[0].goals / max(len(player.teams) or 1, 1), 1)
                            if player.career_stats else 0
                        ),
                        'avg_assists_per_season': (
                            round(player.career_stats[0].assists / max(len(player.teams) or 1, 1), 1)
                            if player.career_stats else 0
                        ),
                        'league_experience_seasons': 0,
                        'attendance_estimate': 75,
                        'experience_level': 'New Player',
                        'prev_draft_position': None,  # New draft, no previous position yet
                        'current_position': position,  # Position on the pitch (from pitch view)
                        'is_new': is_new_flag,
                        'is_admin': is_admin_flag
                    },
                    'team_id': team_id,
                    'team_name': team_name,
                    'league_name': league_name,
                    'position': position,  # Include position at top level for easier access
                    'draft_position': locals().get('draft_position')  # overall pick # for the live history feed
                }

            # Broadcast to all clients in the draft room so everyone sees the update
            emit('player_drafted_enhanced', response_data, room=f'draft_{league_name}')
            print(f"✅ Successfully drafted {player_name} to {team_name} - broadcasted to room draft_{league_name}")
            logger.info(f"✅ Successfully drafted {player_name} to {team_name}")

            # The on-the-clock advance already happened UNDER THE LOCK in Transaction 2
            # (atomic with the write — see above). Just broadcast the captured state here.
            try:
                if clock_state:
                    emit('draft_clock_update', clock_state, room=f'draft_{league_name}')
            except Exception as _adv_err:
                logger.warning(f"Draft clock update emit skipped: {_adv_err}")

            # CRITICAL: Invalidate draft cache so page refresh shows correct data
            try:
                from app.draft_cache_service import DraftCacheService
                # Normalize league name for cache key
                db_league_name = {
                    'classic': 'Classic',
                    'premier': 'Premier',
                    'ecs_fc': 'ECS FC'
                }.get(league_name.lower(), league_name)
                deleted = DraftCacheService.invalidate_player_cache_ultra_safe(player_id, db_league_name)
                print(f"🗑️ Invalidated {deleted} cache keys for player {player_id} in {db_league_name}")
                logger.info(f"🗑️ Invalidated {deleted} cache keys after draft")
            except Exception as cache_error:
                print(f"⚠️ Cache invalidation failed (non-critical): {cache_error}")
                logger.warning(f"Cache invalidation failed: {cache_error}")

        except Exception as e:
            print(f"💥 Draft error: {str(e)}")
            logger.error(f"💥 Draft error: {str(e)}", exc_info=True)
            emit('draft_error', {'message': 'Internal server error occurred during draft'})

    except Exception as e:
        print(f"🚫 Authentication or validation error: {str(e)}")
        logger.error(f"Authentication or validation error: {str(e)}", exc_info=True)
        emit('draft_error', {'message': 'Authentication or validation failed'})
    finally:
        # Always release the lock
        draft_lock.release()
        cleanup_draft_lock(player_id)


@socketio.on('update_player_position', namespace='/')
def handle_update_player_position(data):
    """Handle updating a player's position on the pitch."""
    from app.models import Player, Team

    logger.info(f"Received position update request: {data}")

    try:
        # Validate required data
        required_fields = ['player_id', 'team_id', 'position', 'league_name']
        if not all(field in data for field in required_fields):
            emit('error', {'message': 'Missing required data'})
            return

        player_id = int(data['player_id'])
        team_id = int(data['team_id'])
        position = data['position']
        league_name = data['league_name']

        # Validate position
        valid_positions = ['gk', 'lb', 'cb', 'rb', 'lwb', 'rwb', 'cdm', 'cm', 'cam', 'lw', 'rw', 'st', 'bench']
        if position not in valid_positions:
            emit('error', {'message': f'Invalid position: {position}'})
            return

        with managed_session() as session:
            # Get player and team
            player = session.query(Player).filter(Player.id == player_id).first()
            team = session.query(Team).filter(Team.id == team_id).first()

            if not player:
                emit('error', {'message': 'Player not found'})
                return

            if not team:
                emit('error', {'message': 'Team not found'})
                return

            # Check if player is on this team
            if team not in player.teams:
                emit('error', {'message': 'Player is not on this team'})
                return

            # Update the position in player_teams table
            from sqlalchemy import text

            # Update the position field in the player_teams association table
            update_stmt = text("""
                UPDATE player_teams
                SET position = :position
                WHERE player_id = :player_id AND team_id = :team_id
            """)

            result = session.execute(update_stmt, {
                'position': position,
                'player_id': player_id,
                'team_id': team_id
            })

            if result.rowcount == 0:
                # Player might not be on the team yet - this shouldn't happen but let's handle it
                emit('error', {'message': 'Player-team relationship not found'})
                return

            session.commit()

            # Emit to all clients in the draft room
            room = f"draft_{league_name}"
            player_data = {
                'id': player.id,
                'name': player.name,
                'profile_picture_url': player.profile_picture_url,
                'favorite_position': player.favorite_position
            }

            emit('player_position_updated', {
                'player': player_data,
                'team_id': team_id,
                'team_name': team.name,
                'position': position,
                'league_name': league_name
            }, room=room)

            logger.info(f"Updated {player.name} position to {position} on team {team.name}")

    except Exception as e:
        logger.error(f"Error updating player position: {str(e)}", exc_info=True)
        emit('error', {'message': 'Failed to update player position'})


@socketio.on('remove_player_enhanced', namespace='/')
def handle_remove_player_enhanced(data):
    """Handle removing a player from a team (return to draft pool)."""
    try:
        print(f"🗑️ Remove player request: {data}")
        logger.info(f"🗑️ Remove player request: {data}")

        # Authentication check using Flask-Login's current_user
        from flask_login import current_user

        print(f"🔍 Remove auth check: current_user.is_authenticated = {current_user.is_authenticated}")
        logger.info(f"🔍 Remove auth check: current_user.is_authenticated = {current_user.is_authenticated}")

        if not current_user.is_authenticated:
            print("🚫 Unauthenticated remove attempt")
            emit('remove_error', {'message': 'Authentication required'})
            return

        # Data validation
        player_id = data.get('player_id')
        team_id = data.get('team_id')
        league_name = data.get('league_name')

        if not all([player_id, team_id, league_name]):
            print(f"🚫 Missing data for remove: {data}")
            emit('remove_error', {'message': 'Missing required data: player_id, team_id, or league_name'})
            return

        # Convert to integers
        try:
            player_id = int(player_id)
            team_id = int(team_id)
        except ValueError:
            print(f"🚫 Invalid ID format for remove")
            emit('remove_error', {'message': 'Invalid player or team ID format'})
            return

        # Database operations
        from app.models import Player, Team, League, player_teams, Season, PlayerTeamSeason
        from app.db_utils import mark_player_for_discord_update
        from sqlalchemy.orm import joinedload

        try:
            with managed_session() as session:
                # Normalize league name
                db_league_name = {
                    'classic': 'Classic',
                    'premier': 'Premier',
                    'ecs_fc': 'ECS FC'
                }.get(league_name.lower(), league_name)

                # Get league (check if its season is current)
                league = session.query(League).join(Season).filter(
                    League.name == db_league_name,
                    Season.is_current == True
                ).first()

                if not league:
                    print(f"🚫 League not found for remove: {db_league_name}")
                    emit('remove_error', {'message': f'League "{db_league_name}" not found'})
                    return

                # Get player and team (with players relationship eagerly loaded)
                player = session.query(Player).filter(Player.id == player_id).first()
                team = session.query(Team).options(
                    joinedload(Team.players)
                ).filter(
                    Team.id == team_id,
                    Team.league_id == league.id
                ).first()

                if not player:
                    print(f"🚫 Player not found for remove: {player_id}")
                    emit('remove_error', {'message': f'Player with ID {player_id} not found'})
                    return

                if not team:
                    print(f"🚫 Team not found for remove: {team_id}")
                    emit('remove_error', {'message': f'Team with ID {team_id} not found'})
                    return

                # Check if player is actually on this team
                if player not in team.players:
                    print(f"🚫 Player not on team for remove")
                    emit('remove_error', {'message': f'Player "{player.name}" is not on team "{team.name}"'})
                    return

                # Remove player from team using SQLAlchemy ORM
                team.players.remove(player)

                # Clear primary team if it matches the team being removed
                if player.primary_team_id == team_id:
                    player.primary_team_id = None
                    print(f"🗑️ Cleared primary team for {player.name}")

                # Delete the CURRENT-season PlayerTeamSeason row for this team.
                # get_current_season_teams (the role calculator's team source)
                # reads PTS for the current season, so a preserved row would make
                # any later batch reconcile (coach-sync, bulk approve, team sync)
                # RE-GRANT this team's Discord role to a player we just removed.
                # PAST-season PTS rows (different season_id) are the historical
                # record and are intentionally left untouched.
                from app.models import PlayerTeamSeason
                if league and league.season_id:
                    session.query(PlayerTeamSeason).filter_by(
                        player_id=player_id, team_id=team_id, season_id=league.season_id
                    ).delete(synchronize_session=False)

                # Remove from draft history and adjust subsequent picks
                try:
                    from app.draft_enhanced import DraftService
                    DraftService.remove_draft_pick(
                        session=session,
                        player_id=player_id,
                        season_id=league.season_id,
                        league_id=league.id
                    )
                    print(f"📊 Removed draft history for {player.name} and adjusted subsequent picks")
                    logger.info(f"📊 Removed draft history for {player.name} and adjusted subsequent picks")
                except Exception as e:
                    print(f"⚠️ Failed to remove draft history: {str(e)}")
                    logger.error(f"Failed to remove draft history: {str(e)}")
                    # Don't fail the entire operation if draft history removal fails

                # Get the exact same enhanced player data that's used during initial page load
                from app.draft_enhanced import DraftService
                try:
                    print(f"🔍 Getting enhanced player data for {player.name} (ID: {player.id}) using same method as page load...")

                    # Set up the Flask application context to match the route context
                    # The enhanced data method expects g.db_session to be available
                    g.db_session = session

                    # Use the exact same method that generates initial player data
                    # Use league.season_id to match exactly what the route does
                    enhanced_players = DraftService.get_enhanced_player_data([player], league.season_id)

                    if enhanced_players and len(enhanced_players) > 0:
                        # Use the first (and only) enhanced player data
                        enhanced_player = enhanced_players[0]
                        print(f"✅ Successfully got enhanced data for {player.name}")
                        print(f"   - League experience seasons: {enhanced_player.get('league_experience_seasons', 'N/A')}")
                        print(f"   - Experience level: {enhanced_player.get('experience_level', 'N/A')}")
                        print(f"   - Attendance estimate: {enhanced_player.get('attendance_estimate', 'N/A')}")

                        # Create response using the enhanced data (this ensures 100% consistency with page load)
                        player_data = {
                            'id': enhanced_player['id'],
                            'name': enhanced_player['name'],
                            'profile_picture_url': enhanced_player['profile_picture_url'],
                            'profile_picture_medium': enhanced_player.get('profile_picture_medium', enhanced_player['profile_picture_url']),
                            'profile_picture_webp': enhanced_player.get('profile_picture_webp', enhanced_player['profile_picture_url']),
                            'favorite_position': enhanced_player['favorite_position'],
                            'career_goals': enhanced_player['career_goals'],
                            'career_assists': enhanced_player['career_assists'],
                            'career_yellow_cards': enhanced_player['career_yellow_cards'],
                            'career_red_cards': enhanced_player['career_red_cards'],
                            'league_experience_seasons': enhanced_player['league_experience_seasons'],
                            'attendance_estimate': enhanced_player['attendance_estimate'],
                            'experience_level': enhanced_player['experience_level'],
                            'expected_weeks_available': enhanced_player['expected_weeks_available'],
                            'is_new': enhanced_player.get('is_new', False),
                            'is_admin': enhanced_player.get('is_admin', False)
                        }
                    else:
                        print(f"❌ No enhanced data returned for {player.name}, using fallback")
                        raise Exception("No enhanced player data returned")

                except Exception as e:
                    print(f"⚠️ Error getting enhanced player data for {player.id}: {e}")
                    logger.warning(f"Error getting enhanced player data for player {player.id}: {e}")

                    # Fallback to basic player data (should rarely be needed)
                    player_data = {
                        'id': player.id,
                        'name': player.name,
                        'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
                        'profile_picture_medium': getattr(player, 'profile_picture_medium', None) or player.profile_picture_url or '/static/img/default_player.png',
                        'profile_picture_webp': getattr(player, 'profile_picture_webp', None) or player.profile_picture_url or '/static/img/default_player.png',
                        'favorite_position': player.favorite_position or 'Any',
                        'other_positions': player.other_positions or '',
                        'positions_not_to_play': player.positions_not_to_play or '',
                        'career_goals': player.career_stats[0].goals if player.career_stats else 0,
                        'career_assists': player.career_stats[0].assists if player.career_stats else 0,
                        'career_yellow_cards': player.career_stats[0].yellow_cards if player.career_stats else 0,
                        'career_red_cards': player.career_stats[0].red_cards if player.career_stats else 0,
                        'league_experience_seasons': 0,
                        'attendance_estimate': None,  # No historical data for fallback case
                        'experience_level': 'New Player',
                        'expected_weeks_available': player.expected_weeks_available or 'All weeks',
                        'prev_draft_position': None,
                        'is_new': False,  # fallback path only; the counter re-seeds on refresh
                        'is_admin': False
                    }

                # Commit the transaction
                session.commit()

                # Capture values needed after the session is released
                player_name_local = player.name
                team_id_local = team.id
                team_name_local = team.name

                # Clean up Flask context that was set for DraftService.get_enhanced_player_data
                if hasattr(g, 'db_session'):
                    delattr(g, 'db_session')

            # ---- Session released; safe to do emit + cache + Celery below ----

            # Queue a TARGETED role removal for just this team's role. A full
            # reconcile (assign_roles_to_player_task / update_player_discord_roles)
            # does NOT strip it: the player's current-season PlayerTeamSeason row
            # is preserved (design invariant above), so get_current_season_teams
            # still reports this team and the role stays "expected". remove_player_
            # roles_task with team_id removes only ECS-FC-PL-<team>-Player, leaving
            # the player's other teams' roles intact.
            from app.tasks.tasks_discord import remove_player_roles_task
            remove_player_roles_task.delay(player_id=player_id, team_id=team_id_local)

            # Success response with full enhanced player data
            response_data = {
                'success': True,
                'player': player_data,
                'team_id': team_id_local,
                'team_name': team_name_local,
                'league_name': league_name
            }

            # Broadcast to all clients in the draft room so everyone sees the update
            emit('player_removed_enhanced', response_data, room=f'draft_{league_name}')
            print(f"✅ Successfully removed {player_name_local} from {team_name_local} - broadcasted to room draft_{league_name}")
            logger.info(f"✅ Successfully removed {player_name_local} from {team_name_local}")

            # CRITICAL: Invalidate draft cache so page refresh shows correct data
            try:
                from app.draft_cache_service import DraftCacheService
                deleted = DraftCacheService.invalidate_player_cache_ultra_safe(player_id, db_league_name)
                print(f"🗑️ Invalidated {deleted} cache keys for player {player_id} in {db_league_name}")
                logger.info(f"🗑️ Invalidated {deleted} cache keys after player removal")
            except Exception as cache_error:
                print(f"⚠️ Cache invalidation failed (non-critical): {cache_error}")
                logger.warning(f"Cache invalidation failed: {cache_error}")

            # (Role removal is handled by the targeted remove_player_roles_task
            # queued above — a full update_player_discord_roles reconcile here
            # would NOT remove the team role while the current-season
            # PlayerTeamSeason row is preserved, and could even re-add it.)

        except Exception as e:
            print(f"💥 Database error during player removal: {str(e)}")
            logger.error(f"💥 Database error during player removal: {str(e)}", exc_info=True)
            emit('remove_error', {'message': 'Database error occurred during player removal'})
            return

    except Exception as e:
        print(f"💥 Remove error: {str(e)}")
        logger.error(f"💥 Remove error: {str(e)}", exc_info=True)
        emit('remove_error', {'message': 'Internal server error occurred during player removal'})
