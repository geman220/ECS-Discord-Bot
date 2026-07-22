# app/sockets/draft.py

"""
Socket.IO Draft Handlers

Handlers for draft room management and player drafting operations.
"""

import logging

from flask import g, request
from flask_socketio import emit, join_room, leave_room

from app.core import socketio
from app.core.session_manager import managed_session
from app.models.ecs_fc import is_ecs_fc_league
from app.sockets.utils import get_draft_lock, cleanup_draft_lock

logger = logging.getLogger(__name__)


def _is_draft_admin(session, user_id) -> bool:
    """Pub League Admin / Global Admin, queried via the live session (the
    current_user.has_role relationship may not be attached in socket context)."""
    if not user_id:
        return False
    try:
        from app.models.core import Role, user_roles
        return session.query(user_roles.c.user_id).join(
            Role, Role.id == user_roles.c.role_id
        ).filter(
            user_roles.c.user_id == user_id,
            Role.name.in_(['Global Admin', 'Pub League Admin']),
        ).first() is not None
    except Exception:
        return False


def _user_coaches_team(session, user_id, team_id) -> bool:
    """True when the user is a player_teams.is_coach coach of this team."""
    if not user_id:
        return False
    from app.models import Player, player_teams
    return session.query(player_teams.c.team_id).join(
        Player, Player.id == player_teams.c.player_id
    ).filter(
        Player.user_id == user_id,
        player_teams.c.team_id == team_id,
        player_teams.c.is_coach == True,  # noqa: E712
    ).first() is not None


@socketio.on('join_draft_room', namespace='/')
def handle_join_draft_room(data):
    """Handle joining a draft room for a specific league."""
    from flask_login import current_user

    if not current_user.is_authenticated:
        emit('error', {'message': 'Authentication required'})
        return

    # Draft rooms broadcast live pick announcements (player -> team). The draft
    # pages are coach/admin-gated; gate the socket room the same way so a
    # regular player can't join and watch assignments land pre-reveal.
    try:
        with managed_session() as vis_session:
            from app.services.team_visibility import user_is_team_exempt
            from app.models import User
            user = vis_session.query(User).get(current_user.id)
            if not user_is_team_exempt(user, session=vis_session):
                emit('error', {'message': 'Not authorized for draft rooms'})
                return
    except Exception as e:
        logger.error(f"join_draft_room authorization check failed: {e}")
        emit('error', {'message': 'Not authorized for draft rooms'})
        return

    league_name = data.get('league_name')
    if league_name:
        room = f'draft_{league_name}'
        join_room(room)
        emit('joined_room', {'room': room, 'league': league_name})
        logger.info(f"User {current_user.username} joined room: {room}")

        # Re-sync the clock for THIS client. A reconnecting phone (sleep/lock,
        # network blip) re-joins the room but would otherwise show a stale clock
        # until the next transition. Read-only + best-effort: a failure here must
        # never break the join.
        try:
            from app import draft_clock
            from app.models import League, Season
            db_league_name = {
                'classic': 'Classic',
                'premier': 'Premier',
                'ecs_fc': 'ECS FC'
            }.get(str(league_name).lower(), league_name)
            with managed_session() as session:
                league = session.query(League).join(Season).filter(
                    League.name == db_league_name,
                    Season.is_current == True  # noqa: E712
                ).first()
                if league:
                    ds = draft_clock.get_session(session, league.season_id, league.id)
                    if ds:
                        emit('draft_clock_update', draft_clock.build_state(session, ds))
        except Exception as e:
            logger.debug(f"join_draft_room clock re-sync skipped: {e}")


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

        # Phase 5: activity banner data — broadcast AFTER T1 validation succeeds
        # (below) so blocked picks (ownership guard, out-of-turn, already
        # drafted) don't spam "X is drafting Y" to the room with no follow-up.
        player_name_from_request = data.get('player_name', 'a player')
        username = current_user.username if hasattr(current_user, 'username') else 'Someone'

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

                # Team-ownership guard: non-admin coaches may only draft players
                # onto a team THEY coach. The on-the-clock check below already
                # covers turn order during a locked session, but free-form mode
                # (no session) used to let any coach assign players to any team.
                _uid = getattr(current_user, 'id', None)
                if not _is_draft_admin(session, _uid) and not _user_coaches_team(session, _uid, team_id):
                    print(f"🚫 Non-coach draft to team {team_id} blocked for user {_uid}")
                    emit('draft_error', {'message': f'You can only draft players to your own team ({team_name} is not yours)'})
                    return

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

            # Validation + guards passed — now tell the room someone is mid-pick.
            emit('user_drafting', {
                'username': username,
                'player_name': player_name_from_request,
                'team_name': team_name
            }, room=f'draft_{league_name}')
            # Mirror to the mobile namespace so phones see web-board coaches
            # mid-pick too, not just other phones.
            socketio.emit('user_drafting', {
                'username': username,
                'player_name': player_name_from_request,
            }, room=f'draft_{league_name}', namespace='/draft')

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

                # A rostered player must not keep a Pub League sub role. Drop any
                # Classic/Premier sub-pool membership + Flask sub role in THIS txn
                # (so it commits with the roster write); the reconcile queued below
                # then strips the stale ECS-FC-PL-*-SUB Discord role. ECS FC sub
                # status is intentionally preserved. This is what stranded a player
                # moved to Premier while still carrying a Classic sub role.
                sub_cleanup = None
                try:
                    from app.services.sub_status_service import remove_conflicting_sub_status
                    sub_cleanup = remove_conflicting_sub_status(
                        session, player_id, performed_by_user_id=current_user.id
                    )
                except Exception as _sub_err:
                    logger.warning(f"Sub-status cleanup skipped for player {player_id}: {_sub_err}")

                # Self-heal any division drift: make the player's league association +
                # pl-<division> Flask role match the drafted team's division, dropping
                # the other division's stale role. No-op for clean data; when it heals
                # drift we force a full Discord reconcile below (like sub removal).
                division_align = None
                try:
                    from app.services.player_division_service import align_player_to_drafted_division
                    division_align = align_player_to_drafted_division(session, player_id, team)
                except Exception as _div_err:
                    logger.warning(f"Division alignment skipped for player {player_id}: {_div_err}")

                # Mark for Discord update (cheap flag write; safe under the lock)
                mark_player_for_discord_update(session, player_id)

                # Advance the clock UNDER THE SAME LOCK (only when the on-the-clock team made
                # this pick; an admin's out-of-turn add to a different team leaves it put).
                # PAUSED drafts advance too: check_turn allows picks while paused, so
                # without this a paused-state pick landed on the roster but the clock
                # never moved — the draft was stuck on the same team after resume. An
                # on-clock pick during a pause now advances AND auto-resumes with a
                # fresh full timer (the pause's purpose is over once the pick is made).
                # M2: advance mutates the clock columns but SKIPS building the emit payload
                # (with_state=False) — build_state's ~5 read queries are moved out of the
                # lock (below) so the FOR UPDATE hold covers writes only.
                if ds is not None and ds.status in ('active', 'paused'):
                    if not ds.current_team_id or ds.current_team_id == team_id:
                        if ds.status == 'paused':
                            ds.status = 'active'
                            ds.pause_remaining_seconds = None
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
            # Queue Discord role assignment task AFTER all commits.
            # Normally only_add=True (additive — never strips team/coach roles mid-draft).
            # BUT when we just removed a stale sub role above, only_add=True would leave
            # the ECS-FC-PL-*-SUB Discord role orphaned; flip to a full reconcile
            # (only_add=False) for THIS pick so the stale sub role is actually removed.
            from app.services.sub_status_service import sub_status_removed, sub_removal_notice
            from app.tasks.tasks_discord import assign_roles_to_player_task
            # Force a full reconcile (removals on) ONLY when we stripped a sub role —
            # that genuinely needs the stale ECS-FC-PL-*-SUB removed. Division
            # alignment is purely additive (an only_add=True sync grants the added
            # role), so it must NOT trigger a removal reconcile.
            _reconcile_removals = sub_status_removed(sub_cleanup)
            _sub_removal_notice = sub_removal_notice(sub_cleanup)
            if _sub_removal_notice:
                logger.info(f"📋 {_sub_removal_notice}")
            assign_roles_to_player_task.delay(player_id=player_id, only_add=not _reconcile_removals)
            _mode = "full reconcile (removing stale sub role)" if _reconcile_removals else "only_add=True"
            print(f"🎭 Queued Discord role update for {player_name} ({_mode})")
            logger.info(f"🎭 Queued Discord role update for {player_name} ({_mode})")

            # Fetch player data for response in a final read-only transaction
            with managed_session() as session:
                player = session.query(Player).filter(Player.id == player_id).first()

                # Roster-composition flags for the live per-team requirement counters.
                # 'new' = no team history in a PRIOR season (exclude the row we just wrote);
                # 'admin' = holds a Pub League Admin / Global Admin role.
                is_new_flag, is_admin_flag, is_nad_flag = False, False, False
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
                # NAD flag for the live roster/pool card shield — same source of
                # truth as the server-rendered badge (nad_board_service). Runs in
                # this POST-commit read session, memoized on g, never under the lock.
                try:
                    from app.services.nad_board_service import nad_player_id_set
                    _nad_key = f'_draft_nad_ids_{season_id}'
                    _nad_all = getattr(g, _nad_key, None)
                    if _nad_all is None:
                        _nad_all = nad_player_id_set(session, season_id=season_id)
                        setattr(g, _nad_key, _nad_all)
                    is_nad_flag = player_id in _nad_all
                except Exception as _nad_err:
                    logger.warning(f"draft NAD flag compute skipped: {_nad_err}")

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
                        'is_admin': is_admin_flag,
                        'is_nad': is_nad_flag
                    },
                    'team_id': team_id,
                    'team_name': team_name,
                    'league_name': league_name,
                    'position': position,  # Include position at top level for easier access
                    'draft_position': locals().get('draft_position'),  # overall pick # for the live history feed
                    # Non-blocking notice for the draft board when a stale Pub League
                    # sub role was auto-removed as part of this pick (or None).
                    'sub_removal_notice': _sub_removal_notice,
                }

            # Broadcast to all clients in the draft room so everyone sees the update.
            # Also mirror to the '/draft' namespace so the mobile app (which connects
            # there, not on the web '/' namespace) sees web-board picks live.
            # Fan out to exact + lowercased room variants (draft_clock.draft_rooms):
            # a client that loaded /draft/Classic joins draft_Classic while the
            # balanced/mobile boards join draft_classic — a single-casing emit
            # would silently skip one of them.
            from app.draft_clock import draft_rooms as _draft_rooms
            for _room in _draft_rooms(league_name):
                emit('player_drafted_enhanced', response_data, room=_room)
                socketio.emit('player_drafted_enhanced', response_data,
                              room=_room, namespace='/draft')
            print(f"✅ Successfully drafted {player_name} to {team_name} - broadcasted to room draft_{league_name}")
            logger.info(f"✅ Successfully drafted {player_name} to {team_name}")

            # The on-the-clock advance already happened UNDER THE LOCK in Transaction 2
            # (atomic with the write — see above). Broadcast the captured state via the
            # shared broadcaster: same rooms/namespaces as before (exact + lowercased),
            # PLUS it mirrors the state into the Redis poll cache so the mobile
            # GET /clock endpoint serves this pick's clock without touching the DB.
            try:
                if clock_state:
                    draft_clock.broadcast_draft('draft_clock_update', clock_state,
                                                league_name, db_league_name)
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

            # Team-ownership guard: only admins or this team's own coach may
            # rearrange its formation (mirrors the draft/remove guards).
            from flask_login import current_user
            if not getattr(current_user, 'is_authenticated', False):
                emit('error', {'message': 'Authentication required'})
                return
            _uid = getattr(current_user, 'id', None)
            if not _is_draft_admin(session, _uid) and not _user_coaches_team(session, _uid, team_id):
                emit('error', {'message': f'You can only manage positions on your own team ({team.name} is not yours)'})
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

            position_payload = {
                'player': player_data,
                'team_id': team_id,
                'team_name': team.name,
                'position': position,
                'league_name': league_name
            }
            emit('player_position_updated', position_payload, room=room)
            socketio.emit('player_position_updated', position_payload,
                          room=room, namespace='/draft')

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

                # Team-ownership guard: non-admin coaches may only remove players
                # from a team THEY coach (mirrors the draft-side guard).
                _uid = getattr(current_user, 'id', None)
                if not _is_draft_admin(session, _uid) and not _user_coaches_team(session, _uid, team_id):
                    print(f"🚫 Non-coach remove from team {team_id} blocked for user {_uid}")
                    emit('remove_error', {'message': f'You can only remove players from your own team ({team.name} is not yours)'})
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
                            'is_admin': enhanced_player.get('is_admin', False),
                            'is_nad': enhanced_player.get('is_nad', False)
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
                        'is_admin': False,
                        'is_nad': False
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
            # (web '/' + mobile '/draft' namespaces).
            # Same exact + lowercased room fan-out as the drafted broadcast.
            from app.draft_clock import draft_rooms as _draft_rooms
            for _room in _draft_rooms(league_name):
                emit('player_removed_enhanced', response_data, room=_room)
                socketio.emit('player_removed_enhanced', response_data,
                              room=_room, namespace='/draft')
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


# =============================================================================
# Mobile draft namespace ('/draft')
#
# The web board runs on the default '/' namespace (Flask-Login session cookies).
# The mobile app can't use those cookies, so it connects to a dedicated '/draft'
# namespace and authenticates the handshake with the same JWT it uses everywhere
# else (query ?token=, auth:{token}, or Authorization: Bearer). All draft
# broadcasts are fanned out to BOTH namespaces (see draft_clock.broadcast_draft and
# the socketio.emit(..., namespace='/draft') mirrors above), so a phone joined to
# draft_<league> receives every clock/roster change whether it originated on the
# web board, a REST admin action, the timeout task, or another phone.
# =============================================================================

def _extract_socket_token():
    """Pull the JWT off the handshake: Authorization: Bearer, ?token=, or the
    Socket.IO auth payload {token: ...}. Returns the raw token string or None."""
    # Authorization header
    auth_header = request.headers.get('Authorization', '') or ''
    if auth_header.startswith('Bearer '):
        return auth_header.split(' ', 1)[1].strip()
    # Query param
    token = request.args.get('token')
    if token:
        return token
    # Socket.IO auth dict (client passes auth={'token': ...})
    try:
        auth = getattr(request, 'event', {}) or {}
        # flask-socketio stashes the connect auth on the environ
        auth_data = request.environ.get('saved_auth') if request.environ else None
        if isinstance(auth_data, dict) and auth_data.get('token'):
            return auth_data['token']
    except Exception:
        pass
    return None


@socketio.on('connect', namespace='/draft')
def handle_draft_connect(auth=None):
    """Authenticate the mobile draft socket. A valid, approved user's token connects;
    anything else is rejected (return False) so only real members subscribe to draft
    rooms. Room membership itself happens via join_draft_room after connect."""
    # Flask-SocketIO passes the client's auth dict here on 5.x; stash the token.
    token = None
    if isinstance(auth, dict) and auth.get('token'):
        token = auth['token']
    if not token:
        token = _extract_socket_token()

    if not token:
        logger.info("draft namespace: connect rejected (no token)")
        return False

    try:
        from flask_jwt_extended import decode_token
        decoded = decode_token(token)
        raw_id = decoded.get('sub') or decoded.get('identity')
        user_id = int(raw_id) if raw_id is not None else None
    except Exception as e:
        logger.warning(f"draft namespace: rejecting token: {e}")
        return False

    if not user_id:
        return False

    # Confirm the user exists + is approved before letting them subscribe.
    from app.models import User
    with managed_session() as session:
        user = session.query(User).get(user_id)
        if not user or not user.is_approved:
            logger.info(f"draft namespace: connect rejected for user {user_id} (missing/unapproved)")
            return False
        username = user.username

    g.socket_user_id = user_id
    logger.info(f"draft namespace: {username} (id={user_id}) connected")
    emit('authentication_success', {'user_id': user_id, 'username': username})
    return True


@socketio.on('disconnect', namespace='/draft')
def handle_draft_disconnect(reason=None):
    """Rooms are cleaned up automatically by Flask-SocketIO on disconnect."""
    if reason:
        logger.debug(f"draft namespace disconnect: {reason}")


@socketio.on('join_draft_room', namespace='/draft')
def handle_join_draft_room_mobile(data):
    """Join draft_<league_name> on the '/draft' namespace. Payload {league_name}."""
    league_name = (data or {}).get('league_name')
    if not league_name:
        emit('error', {'message': 'league_name is required'})
        return

    # Draft rooms stream live player->team assignments. Same gate as the web
    # namespace: only coaches/admins may subscribe, or any player could watch
    # assignments land pre-reveal. g doesn't persist across socket events, so
    # re-resolve the user from the handshake token.
    user_id = getattr(g, 'socket_user_id', None)
    if not user_id:
        token = _extract_socket_token()
        if token:
            try:
                from flask_jwt_extended import decode_token
                decoded = decode_token(token)
                raw_id = decoded.get('sub') or decoded.get('identity')
                user_id = int(raw_id) if raw_id is not None else None
            except Exception as e:
                logger.debug(f"mobile join_draft_room token decode failed: {e}")
                user_id = None
    if not user_id:
        emit('error', {'message': 'Not authorized for draft rooms'})
        return
    try:
        from app.services.team_visibility import user_is_team_exempt
        from app.models import User
        with managed_session() as vis_session:
            user = vis_session.query(User).get(user_id)
            if not user_is_team_exempt(user, session=vis_session):
                emit('error', {'message': 'Not authorized for draft rooms'})
                return
    except Exception as e:
        logger.error(f"mobile join_draft_room authorization check failed: {e}")
        emit('error', {'message': 'Not authorized for draft rooms'})
        return

    room = f'draft_{league_name}'
    join_room(room)
    emit('joined_room', {'room': room, 'league': league_name})
    logger.debug(f"draft namespace: socket joined {room}")


@socketio.on('leave_draft_room', namespace='/draft')
def handle_leave_draft_room_mobile(data):
    """Leave draft_<league_name> on the '/draft' namespace. Payload {league_name}."""
    league_name = (data or {}).get('league_name')
    if not league_name:
        return
    room = f'draft_{league_name}'
    leave_room(room)
    emit('left_room', {'room': room, 'league': league_name})


@socketio.on('user_drafting', namespace='/draft')
def handle_user_drafting(data):
    """Relay a 'coach is mid-pick' banner hint to the rest of the room. Optional/cosmetic.
    Payload {league_name, username, player_name}."""
    data = data or {}
    league_name = data.get('league_name')
    if not league_name:
        return
    room = f'draft_{league_name}'
    # Broadcast to everyone else in the room (not the sender).
    emit('user_drafting', {
        'username': data.get('username'),
        'player_name': data.get('player_name'),
    }, room=room, include_self=False)
    # Mirror to the web namespace so the web board sees phone coaches mid-pick.
    socketio.emit('user_drafting', {
        'username': data.get('username'),
        'player_name': data.get('player_name'),
        'team_name': None,
    }, room=room, namespace='/')
