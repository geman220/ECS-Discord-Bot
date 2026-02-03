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
    print(f"🏠 Join draft room request: {data}")
    logger.info(f"🏠 Join draft room request: {data}")

    # Check authentication using Flask-Login's current_user
    from flask_login import current_user

    print(f"🔍 Authentication check: current_user.is_authenticated = {current_user.is_authenticated}")
    logger.info(f"🔍 Authentication check: current_user.is_authenticated = {current_user.is_authenticated}")

    if not current_user.is_authenticated:
        print("🚫 Unauthenticated user tried to join draft room")
        emit('error', {'message': 'Authentication required'})
        return

    league_name = data.get('league_name')
    if league_name:
        room = f'draft_{league_name}'
        join_room(room)
        emit('joined_room', {'room': room, 'league': league_name})
        print(f"🏠 User {current_user.username} joined room: {room}")
        logger.info(f"🏠 User {current_user.username} joined room: {room}")


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

            # ===== TRANSACTION 2: Core write operation (~200ms) =====
            with managed_session() as session:
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
                    season_id=season_id
                )
                session.add(player_team_season)
                print(f"📝 Created new PlayerTeamSeason record for {player_name} to {team_name}")
            # Transaction 2 committed automatically - connection released

            # ===== TRANSACTION 3: History & Discord marker (~50ms) =====
            with managed_session() as session:
                # Record the draft pick in history
                try:
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
                    print(f"⚠️ Failed to record draft pick: {str(e)}")
                    logger.error(f"Failed to record draft pick: {str(e)}")
                    # Don't fail the entire operation if draft history fails

                # Mark for Discord update
                mark_player_for_discord_update(session, player_id)
            # Transaction 3 committed automatically - connection released

            # ===== Post-transaction: Queue async tasks and emit response =====
            # Queue Discord role assignment task AFTER all commits
            from app.tasks.tasks_discord import assign_roles_to_player_task
            assign_roles_to_player_task.delay(player_id=player_id, only_add=True)
            print(f"🎭 Queued Discord role update for {player_name} (only_add = True to keep existing roles)")
            logger.info(f"🎭 Queued Discord role update for {player_name} (only_add = True to keep existing roles)")

            # Fetch player data for response in a final read-only transaction
            with managed_session() as session:
                player = session.query(Player).filter(Player.id == player_id).first()

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
                        'current_position': position  # Position on the pitch (from pitch view)
                    },
                    'team_id': team_id,
                    'team_name': team_name,
                    'league_name': league_name,
                    'position': position  # Include position at top level for easier access
                }

            # Broadcast to all clients in the draft room so everyone sees the update
            emit('player_drafted_enhanced', response_data, room=f'draft_{league_name}')
            print(f"✅ Successfully drafted {player_name} to {team_name} - broadcasted to room draft_{league_name}")
            logger.info(f"✅ Successfully drafted {player_name} to {team_name}")

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

                # Remove PlayerTeamSeason records for current season
                season_records = session.query(PlayerTeamSeason).filter(
                    PlayerTeamSeason.player_id == player_id,
                    PlayerTeamSeason.team_id == team_id,
                    PlayerTeamSeason.season_id == league.season_id
                ).all()

                for record in season_records:
                    session.delete(record)
                    print(f"🗑️ Removed PlayerTeamSeason record: {record.id}")
                    logger.info(f"🗑️ Removed PlayerTeamSeason record: {record.id}")

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
                            'expected_weeks_available': enhanced_player['expected_weeks_available']
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
                        'prev_draft_position': None
                    }

                # Commit the transaction
                session.commit()

                # Queue Discord role update task AFTER commit to ensure team removal is reflected
                from app.tasks.tasks_discord import assign_roles_to_player_task
                assign_roles_to_player_task.delay(player_id=player_id, only_add=False)

                # Success response with full enhanced player data
                response_data = {
                    'success': True,
                    'player': player_data,
                    'team_id': team.id,
                    'team_name': team.name,
                    'league_name': league_name
                }

                # Broadcast to all clients in the draft room so everyone sees the update
                emit('player_removed_enhanced', response_data, room=f'draft_{league_name}')
                print(f"✅ Successfully removed {player.name} from {team.name} - broadcasted to room draft_{league_name}")
                logger.info(f"✅ Successfully removed {player.name} from {team.name}")

                # CRITICAL: Invalidate draft cache so page refresh shows correct data
                try:
                    from app.draft_cache_service import DraftCacheService
                    deleted = DraftCacheService.invalidate_player_cache_ultra_safe(player_id, db_league_name)
                    print(f"🗑️ Invalidated {deleted} cache keys for player {player_id} in {db_league_name}")
                    logger.info(f"🗑️ Invalidated {deleted} cache keys after player removal")
                except Exception as cache_error:
                    print(f"⚠️ Cache invalidation failed (non-critical): {cache_error}")
                    logger.warning(f"Cache invalidation failed: {cache_error}")

                # Clean up Flask context
                if hasattr(g, 'db_session'):
                    delattr(g, 'db_session')

            # Trigger Discord role update task (will remove roles since player is no longer on team)
            from app.tasks.tasks_discord import update_player_discord_roles
            try:
                task = update_player_discord_roles.delay(player_id)
                print(f"🤖 Discord role update task queued: {task.id}")
                logger.info(f"🤖 Discord role update task queued for player {player_id}: {task.id}")
            except Exception as e:
                print(f"⚠️ Failed to queue Discord role update: {str(e)}")
                logger.warning(f"Failed to queue Discord role update: {str(e)}")

        except Exception as e:
            print(f"💥 Database error during player removal: {str(e)}")
            logger.error(f"💥 Database error during player removal: {str(e)}", exc_info=True)
            emit('remove_error', {'message': 'Database error occurred during player removal'})
            return

    except Exception as e:
        print(f"💥 Remove error: {str(e)}")
        logger.error(f"💥 Remove error: {str(e)}", exc_info=True)
        emit('remove_error', {'message': 'Internal server error occurred during player removal'})
