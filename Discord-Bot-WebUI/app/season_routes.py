# app/season_routes.py

"""
Season Routes Module

This module provides endpoints and helper functions for managing seasons,
including creating new seasons (for both Pub League and ECS FC), performing
league rollovers, setting the current season, and deleting seasons along with
their associated leagues and teams.
"""

from flask import Blueprint, render_template, redirect, url_for, request, g, jsonify
from app.alert_helpers import show_success, show_error, show_warning, show_info
from flask_login import login_required, current_user
from sqlalchemy import func
from typing import Optional
import logging

from app.models import Season, League, Player, PlayerTeamSeason, Team, Schedule, User, Role
from app.models.players import player_teams, player_league
from app.models.core import user_roles
from sqlalchemy import text
from app.decorators import role_required

logger = logging.getLogger(__name__)

season_bp = Blueprint('season', __name__)


@season_bp.route('/', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_seasons():
    """
    Manage seasons: Display existing Pub League and ECS FC seasons and
    allow creation of new seasons via form submission.
    """
    session = g.db_session

    pub_league_seasons = session.query(Season).filter_by(league_type='Pub League').all()
    ecs_fc_seasons = session.query(Season).filter_by(league_type='ECS FC').all()

    if request.method == 'POST':
        season_name = request.form.get('season_name')
        ecs_fc_season_name = request.form.get('ecs_fc_season_name')

        if season_name:
            try:
                create_pub_league_season(session, season_name)
                show_success(f'Pub League Season "{season_name}" created successfully with Premier and Classic divisions.')
            except Exception as e:
                logger.error(f"Error creating Pub League season: {e}")
                show_error('Error occurred while creating Pub League season.')
                raise
        elif ecs_fc_season_name:
            try:
                create_ecs_fc_season(session, ecs_fc_season_name)
                show_success(f'ECS FC Season "{ecs_fc_season_name}" created successfully.')
            except Exception as e:
                logger.error(f"Error creating ECS FC season: {e}")
                show_error('Error occurred while creating ECS FC season.')
                raise
        else:
            show_error('Season name cannot be empty.')

        return redirect(url_for('publeague.season.manage_seasons'))

    return render_template('manage_seasons_flowbite.html', pub_league_seasons=pub_league_seasons, ecs_fc_seasons=ecs_fc_seasons, title='Manage Seasons')


def rollover_league(session, old_season: Season, new_season: Season) -> bool:
    """
    Perform league rollover from an old season to a new season.

    This comprehensive rollover process:
    1. Records team history for the old season in PlayerTeamSeason
    2. Updates players to belong to corresponding leagues in the new season
    3. Clears all current team assignments so players start as blank slates
    4. Clears secondary league assignments
    5. Creates fresh season stats records starting at 0
    6. Preserves all historical data and career stats
    7. Queues Discord role removal for old team roles

    Args:
        session: Database session.
        old_season (Season): The previous season.
        new_season (Season): The newly created season.

    Returns:
        bool: True if the rollover is successful.

    Raises:
        Exception: Propagates any exception after rolling back.
    """
    try:
        logger.info(f"Starting rollover from {old_season.name} to {new_season.name}")

        # Step 1: Record team history for old season and collect Discord role removal data
        players = session.query(Player).all()
        history_records = []
        discord_role_removals = []  # Collect player/team pairs for Discord role cleanup

        # Snapshot the season's FINAL per-team coach flags before player_teams is
        # wiped below. This is the only durable record of season-specific coaching
        # (player_teams.is_coach is current-only), so it powers cross-season coach
        # history. Keyed by (player_id, team_id).
        old_team_ids = [tid for (tid,) in (
            session.query(Team.id)
            .join(League, Team.league_id == League.id)
            .filter(League.season_id == old_season.id)
            .all()
        )]
        coach_flag = {}
        if old_team_ids:
            for r in session.execute(
                player_teams.select().where(player_teams.c.team_id.in_(old_team_ids))
            ).fetchall():
                coach_flag[(r.player_id, r.team_id)] = bool(r.is_coach)

        for player in players:
            # Get teams for the player that are in the old season.
            old_season_teams = [t for t in player.teams if t.league.season_id == old_season.id]
            for t in old_season_teams:
                is_coach_snapshot = coach_flag.get((player.id, t.id), False)
                # Check if this PlayerTeamSeason record already exists
                existing_record = session.query(PlayerTeamSeason).filter_by(
                    player_id=player.id,
                    team_id=t.id,
                    season_id=old_season.id
                ).first()

                if not existing_record:
                    history_records.append(PlayerTeamSeason(
                        player_id=player.id,
                        team_id=t.id,
                        season_id=old_season.id,
                        is_coach=is_coach_snapshot
                    ))
                elif existing_record.is_coach != is_coach_snapshot:
                    # A row from draft time may carry a stale flag — finalize it.
                    existing_record.is_coach = is_coach_snapshot

                # Collect Discord role removal data if player has Discord ID
                if player.discord_id:
                    discord_role_removals.append({
                        'player_id': player.id,
                        'team_id': t.id,
                        'team_name': t.name,
                        'discord_id': player.discord_id
                    })

        if history_records:
            session.bulk_save_objects(history_records)
            session.flush()
            logger.info(f"Recorded {len(history_records)} team history records")

        # Step 2: Update league associations
        old_leagues = session.query(League).filter_by(season_id=old_season.id).all()
        new_leagues = session.query(League).filter_by(season_id=new_season.id).all()
        old_league_ids = [l.id for l in old_leagues]

        # Create a mapping from old league IDs to new league IDs (by name)
        league_mapping = {
            old_league.id: next((nl.id for nl in new_leagues if nl.name == old_league.name), None)
            for old_league in old_leagues
        }

        logger.info(f"League mapping: {league_mapping}")

        # Update players' primary league associations - migrate ALL players (active and inactive)
        # This ensures inactive players are already in the correct league if they return later
        # The draft system filters on is_current_player anyway, so inactive players won't appear
        updated_players = 0
        for old_league in old_leagues:
            new_league_id = league_mapping.get(old_league.id)
            if new_league_id:
                logger.info(f"Migrating ALL players from {old_league.name} (ID: {old_league.id}) to new league (ID: {new_league_id})")

                # Update both league_id and primary_league_id for ALL players (not just active)
                # Use OR condition to catch players with either field matching
                league_updates = session.query(Player).filter(
                    (Player.league_id == old_league.id) | (Player.primary_league_id == old_league.id)
                ).update({
                    'league_id': new_league_id,
                    'primary_league_id': new_league_id,
                }, synchronize_session=False)

                updated_players += league_updates
                logger.info(f"Updated {league_updates} players from {old_league.name} to new season")

        logger.info(f"Updated league associations for {updated_players} total players (active + inactive)")

        # Step 2b: SAFETY - Also migrate any players from ANY old Pub League seasons
        # This catches players that might have been in leagues from seasons other than old_season
        # (e.g., if database was restored from a different environment)
        for new_league in new_leagues:
            # Find all old leagues with the same name across ALL old Pub League seasons
            all_old_same_name_leagues = session.query(League).join(Season).filter(
                Season.league_type == 'Pub League',
                Season.id != new_season.id,
                League.name == new_league.name
            ).all()

            for old_league in all_old_same_name_leagues:
                if old_league.id not in old_league_ids:  # Skip if already handled above
                    orphan_updates = session.query(Player).filter(
                        (Player.league_id == old_league.id) | (Player.primary_league_id == old_league.id)
                    ).update({
                        'league_id': new_league.id,
                        'primary_league_id': new_league.id,
                    }, synchronize_session=False)

                    if orphan_updates > 0:
                        logger.info(f"SAFETY: Migrated {orphan_updates} orphaned players from old {old_league.name} (ID: {old_league.id}, Season: {old_league.season_id}) to new league (ID: {new_league.id})")
                        updated_players += orphan_updates

        # Step 3: Update secondary league assignments (player_league) to new season
        # Instead of deleting, we update old league IDs to new league IDs
        logger.info("Updating secondary league assignments to new season...")
        updated_secondary = 0
        for old_league_id, new_league_id in league_mapping.items():
            if new_league_id:
                result = session.execute(
                    player_league.update().where(
                        player_league.c.league_id == old_league_id
                    ).values(league_id=new_league_id)
                )
                updated_secondary += result.rowcount
        logger.info(f"Updated {updated_secondary} secondary league assignments to new season")

        # Step 3b: SAFETY - Also migrate secondary league assignments from ANY old Pub League seasons
        # This catches players who have secondary/tertiary Pub League associations from other seasons
        for new_league in new_leagues:
            all_old_same_name_leagues = session.query(League).join(Season).filter(
                Season.league_type == 'Pub League',
                Season.id != new_season.id,
                League.name == new_league.name
            ).all()

            for old_league in all_old_same_name_leagues:
                if old_league.id not in old_league_ids:  # Skip if already handled above
                    result = session.execute(
                        player_league.update().where(
                            player_league.c.league_id == old_league.id
                        ).values(league_id=new_league.id)
                    )
                    if result.rowcount > 0:
                        logger.info(f"SAFETY: Migrated {result.rowcount} secondary league assignments from old {old_league.name} (ID: {old_league.id}) to new league (ID: {new_league.id})")
                        updated_secondary += result.rowcount

        # Step 4: Get teams from the OLD season only (not ECS FC or other seasons)
        old_season_team_ids = session.query(Team.id).join(
            League, Team.league_id == League.id
        ).filter(
            League.season_id == old_season.id
        ).all()
        old_season_team_ids = [tid[0] for tid in old_season_team_ids]
        logger.info(f"Found {len(old_season_team_ids)} teams in old season")

        # Step 5: Clear ONLY team assignments for teams in the OLD season
        # This preserves ECS FC team memberships and teams from other seasons
        if old_season_team_ids:
            logger.info("Clearing team assignments for OLD season teams only...")
            deleted_teams = session.execute(
                player_teams.delete().where(
                    player_teams.c.team_id.in_(old_season_team_ids)
                )
            ).rowcount
            logger.info(f"Removed {deleted_teams} team assignments (old season only)")

        # Step 6: Reset primary_team_id ONLY if it pointed to a team in the old season
        logger.info("Resetting primary team assignments for old season teams...")
        reset_primary = session.query(Player).filter(
            Player.primary_team_id.in_(old_season_team_ids)
        ).update({
            'primary_team_id': None
        }, synchronize_session=False)
        logger.info(f"Reset primary team for {reset_primary} players")

        # Step 7: Create fresh season stats records for new season
        logger.info("Creating fresh season stats records...")
        from app.models.stats import PlayerSeasonStats

        # Get all players who are now in the new season's leagues
        # (their primary_league_id was just updated to new league IDs)
        new_league_ids = [l.id for l in new_leagues]
        all_active_players = session.query(Player).filter(
            Player.primary_league_id.in_(new_league_ids),
            Player.is_current_player == True
        ).all() if new_league_ids else []

        new_season_stats = []
        for player in all_active_players:
            # Check if season stats already exist for this player/season
            existing_stats = session.query(PlayerSeasonStats).filter_by(
                player_id=player.id,
                season_id=new_season.id
            ).first()

            if not existing_stats:
                new_season_stats.append(PlayerSeasonStats(
                    player_id=player.id,
                    season_id=new_season.id,
                    league_id=player.primary_league_id,
                    goals=0,
                    assists=0,
                    yellow_cards=0,
                    red_cards=0
                ))

        if new_season_stats:
            session.bulk_save_objects(new_season_stats)
            logger.info(f"Created {len(new_season_stats)} fresh season stats records")

        session.commit()

        # Step 8: Queue Discord role removal tasks (after commit)
        # This ensures team assignments are cleared before removing Discord roles
        if discord_role_removals:
            logger.info(f"Queuing Discord role removal for {len(discord_role_removals)} player-team assignments...")
            _queue_discord_role_removals(discord_role_removals)

        # Step 9: Clear ALL draft caches to ensure fresh data after rollover
        # This is critical - without this, the draft page may show stale cached data
        logger.info("Clearing all draft caches after rollover...")
        try:
            from app.draft_cache_service import DraftCacheService
            # Clear caches for all Pub League divisions
            DraftCacheService.clear_all_league_caches('Premier')
            DraftCacheService.clear_all_league_caches('Classic')
            # Also clear ECS FC in case of cross-league effects
            DraftCacheService.clear_all_league_caches('ECS FC')
            logger.info("Draft caches cleared successfully")
        except Exception as cache_err:
            logger.warning(f"Could not clear draft caches: {cache_err}")
            # Don't fail rollover if cache clear fails

        # Step 10: Verify no orphaned players remain in old season leagues
        # This is a safety check that uses SeasonSyncService to find and auto-fix any stragglers
        logger.info("Verifying no orphaned players in old season leagues...")
        try:
            from app.services.season_sync_service import SeasonSyncService

            stale_players = SeasonSyncService.find_stale_players(session, new_season.league_type)
            if stale_players:
                logger.warning(f"Rollover left {len(stale_players)} orphaned players - auto-fixing...")
                fixed_count = 0
                for player in stale_players:
                    try:
                        if SeasonSyncService.sync_player_to_current_season(session, player):
                            fixed_count += 1
                    except Exception as sync_err:
                        logger.error(f"Could not sync orphaned player {player.id}: {sync_err}")

                if fixed_count > 0:
                    session.commit()
                    logger.info(f"Auto-fixed {fixed_count} orphaned players after rollover")
            else:
                logger.info("No orphaned players found - all players are in the new season")
        except Exception as orphan_err:
            logger.warning(f"Could not verify orphaned players: {orphan_err}")
            # Don't fail rollover if orphan check fails

        logger.info(f"Rollover completed successfully: {old_season.name} → {new_season.name}")
        return True

    except Exception as e:
        logger.error(f"Rollover failed: {str(e)}")
        session.rollback()
        raise


def _queue_discord_role_removals(role_removals: list) -> int:
    """
    Queue Discord role removal tasks for players after rollover.

    This removes old team-specific Discord roles (e.g., ECS-FC-PL-TEAM-A-Player)
    so players don't retain access to old team channels.

    Args:
        role_removals: List of dicts with player_id, team_id, team_name, discord_id

    Returns:
        Number of tasks queued.
    """
    queued = 0
    try:
        from app.tasks.tasks_discord import process_discord_role_updates

        # Rollover touches EVERY player, so the old one-remove-task-per-(player,team)
        # fan-out was the single biggest source of Discord 429s. Dedupe to one entry
        # per player and fire a SINGLE batched reconcile task. By the time it runs the
        # rosters are cleared, so reconciling each player to their expected role set
        # removes the stale team roles (and the bot paces the writes internally).
        seen = set()
        discord_ids = []
        for removal in role_removals:
            did = removal.get('discord_id')
            if did and str(did) not in seen:
                seen.add(str(did))
                discord_ids.append(str(did))

        if discord_ids:
            process_discord_role_updates.delay(discord_ids)
            queued = len(discord_ids)
            logger.info(f"Queued 1 batched Discord role reconcile for {queued} players (rollover cleanup)")

    except ImportError:
        logger.warning("Discord tasks not available - Discord roles will not be cleaned up automatically")
    except Exception as e:
        logger.error(f"Error queuing Discord role removals: {e}")

    return queued


def restore_season_memberships(session, target_season: Season) -> dict:
    """
    Restore player-team memberships from PlayerTeamSeason history when switching to a season.

    This allows switching between seasons with players automatically assigned to their
    correct teams for that season. IMPORTANT: This only affects teams/leagues in the
    target season's league type - ECS FC memberships are preserved when switching
    Pub League seasons and vice versa.

    Args:
        session: Database session.
        target_season (Season): The season to restore memberships for.

    Returns:
        dict: Summary of restoration with counts.
    """
    try:
        logger.info(f"Restoring player-team memberships for season: {target_season.name} ({target_season.league_type})")

        # Get all PlayerTeamSeason records for the target season
        season_assignments = session.query(PlayerTeamSeason).filter_by(
            season_id=target_season.id
        ).all()

        if not season_assignments:
            logger.info(f"No PlayerTeamSeason records found for {target_season.name} - this may be a new season")
            return {
                'success': True,
                'restored': 0,
                'cleared': 0,
                'message': 'No historical team assignments found for this season'
            }

        logger.info(f"Found {len(season_assignments)} historical team assignments to restore")

        # Get all leagues in the target season
        target_leagues = session.query(League).filter_by(season_id=target_season.id).all()
        target_league_ids = [league.id for league in target_leagues]

        # Get all teams in those leagues (ONLY these teams will be affected)
        target_teams = session.query(Team).filter(Team.league_id.in_(target_league_ids)).all()
        target_team_ids = [team.id for team in target_teams]

        # Get unique player IDs from the assignments
        player_ids = list(set([a.player_id for a in season_assignments]))

        # Step 1: Clear ONLY player_teams associations for teams in the TARGET season
        # This preserves ECS FC team memberships when restoring Pub League seasons
        logger.info(f"Clearing team assignments ONLY for teams in target season ({len(target_team_ids)} teams)...")

        cleared_count = session.execute(
            player_teams.delete().where(
                player_teams.c.player_id.in_(player_ids),
                player_teams.c.team_id.in_(target_team_ids)
            )
        ).rowcount
        logger.info(f"Cleared {cleared_count} existing team assignments (target season only)")

        # Step 2: Update secondary league associations - only for leagues in target season
        # Don't delete - update to point to correct leagues
        logger.info("Updating secondary league associations for target season leagues...")
        for target_league in target_leagues:
            # Find any other seasons of the same league type with same league name
            # and update player_league entries
            same_name_leagues = session.query(League).join(Season).filter(
                League.name == target_league.name,
                Season.league_type == target_season.league_type,
                League.id != target_league.id
            ).all()

            for old_league in same_name_leagues:
                session.execute(
                    player_league.update().where(
                        player_league.c.player_id.in_(player_ids),
                        player_league.c.league_id == old_league.id
                    ).values(league_id=target_league.id)
                )

        # Step 3: Restore player_teams associations from PlayerTeamSeason records
        restored_count = 0
        league_updates = {}

        for assignment in season_assignments:
            # Only restore if the team still exists and is in the target season
            team = session.query(Team).get(assignment.team_id)
            if not team or team.league_id not in target_league_ids:
                logger.warning(f"Skipping assignment: team {assignment.team_id} not found in target season")
                continue

            # Insert into player_teams, restoring the season-specific coach flag
            try:
                # Prefer the durable per-season snapshot; fall back to the global
                # Player.is_coach only for legacy rows recorded before is_coach
                # existed on PlayerTeamSeason.
                is_coach = bool(getattr(assignment, 'is_coach', False))
                if not is_coach:
                    player = session.query(Player).get(assignment.player_id)
                    is_coach = player.is_coach if player else False

                session.execute(
                    player_teams.insert().values(
                        player_id=assignment.player_id,
                        team_id=assignment.team_id,
                        is_coach=is_coach,  # Season-specific coach status
                        position='bench'
                    )
                )
                restored_count += 1

                # Track league for this player (use first team's league as primary)
                if assignment.player_id not in league_updates:
                    league_updates[assignment.player_id] = team.league_id

            except Exception as e:
                # May fail if already exists (duplicate) - that's OK
                logger.debug(f"Could not insert player_team for player {assignment.player_id}, team {assignment.team_id}: {e}")

        logger.info(f"Restored {restored_count} team assignments")

        # Step 4: Update player league associations and primary team
        # Only update primary_league_id if it matches the target season's league type
        for player_id, league_id in league_updates.items():
            player = session.query(Player).get(player_id)
            if player:
                # Update primary league to target season's league
                player.league_id = league_id
                player.primary_league_id = league_id

                # Set primary_team_id to first team in this season
                player_assignment = next(
                    (a for a in season_assignments if a.player_id == player_id),
                    None
                )
                if player_assignment:
                    player.primary_team_id = player_assignment.team_id

        logger.info(f"Updated league associations for {len(league_updates)} players")

        session.flush()

        return {
            'success': True,
            'restored': restored_count,
            'cleared': cleared_count,
            'players_updated': len(league_updates),
            'message': f'Restored {restored_count} team assignments for {len(league_updates)} players'
        }

    except Exception as e:
        logger.error(f"Error restoring season memberships: {e}")
        raise


def create_pub_league_season(session, season_name: str) -> Optional[Season]:
    """
    Create a new Pub League season with default Premier and Classic divisions.

    If an old season exists, mark it as not current and perform a rollover.

    Args:
        session: Database session.
        season_name (str): Name of the new season.

    Returns:
        Optional[Season]: The newly created season or None if it already exists.
    """
    season_name = season_name.strip()

    existing = session.query(Season).filter(
        func.lower(Season.name) == season_name.lower(),
        Season.league_type == 'Pub League'
    ).first()
    if existing:
        logger.warning(f'Season "{season_name}" already exists.')
        return None

    old_season = session.query(Season).filter_by(
        league_type='Pub League',
        is_current=True
    ).first()

    new_season = Season(
        name=season_name,
        league_type='Pub League',
        is_current=True
    )
    session.add(new_season)
    session.flush()

    # New Pub League season starts with team assignments hidden until the
    # reveal party (make_teams_public toggled back on by an admin).
    from app.services.team_visibility import reset_teams_reveal
    reset_teams_reveal(session)

    # Create default leagues for the new season.
    premier_league = League(name="Premier", season_id=new_season.id)
    classic_league = League(name="Classic", season_id=new_season.id)
    session.add(premier_league)
    session.add(classic_league)

    if old_season:
        old_season.is_current = False

        # Deactivate last season's Pub League roster BEFORE the rollover migrates
        # league_ids. A new season starts with NOBODY active — activation is
        # per-player and pass-driven (buying/linking a Classic|Premier pass calls
        # PlayerActivationService.activate_player_for_league, which flips
        # is_current_player back to True). Scoped strictly to the OLD Pub League
        # season's leagues via league_id/primary_league_id, so ECS FC players
        # (a different season/league_type) are never touched. Profiles, career
        # stats, and PlayerTeamSeason history are all preserved by rollover_league.
        old_pl_league_ids = [
            l.id for l in session.query(League).filter_by(season_id=old_season.id).all()
        ]
        if old_pl_league_ids:
            deactivated = session.query(Player).filter(
                (Player.league_id.in_(old_pl_league_ids)) |
                (Player.primary_league_id.in_(old_pl_league_ids)),
                Player.is_current_player == True
            ).update({Player.is_current_player: False}, synchronize_session=False)
            session.flush()
            logger.info(
                f"Season rollover: deactivated {deactivated} Pub League players "
                f"(is_current_player=False); they re-activate on pass purchase"
            )

        rollover_league(session, old_season, new_season)
    else:
        # No old current season found - still need to commit the new season/leagues
        logger.warning("No current Pub League season found for rollover")
        session.commit()

    # Additional safety check: Ensure ALL Pub League players (active + inactive) are in the new season
    # This handles edge cases where rollover might have missed some players
    # We migrate ALL players so inactive ones are ready if they return later
    session.flush()  # Ensure new leagues are committed first

    logger.info("Performing safety check for any remaining players in old Pub League seasons...")
    premier_league_id = session.query(League).filter_by(name="Premier", season_id=new_season.id).first().id
    classic_league_id = session.query(League).filter_by(name="Classic", season_id=new_season.id).first().id

    # Find ANY players still in old Pub League seasons (active or inactive)
    orphaned_premier = session.query(Player).join(League, Player.primary_league_id == League.id).join(Season, League.season_id == Season.id).filter(
        Season.league_type == 'Pub League',
        Season.id != new_season.id,
        League.name == 'Premier'
    ).count()

    orphaned_classic = session.query(Player).join(League, Player.primary_league_id == League.id).join(Season, League.season_id == Season.id).filter(
        Season.league_type == 'Pub League',
        Season.id != new_season.id,
        League.name == 'Classic'
    ).count()

    if orphaned_premier > 0 or orphaned_classic > 0:
        logger.warning(f"Found {orphaned_premier} Premier and {orphaned_classic} Classic players still in old seasons. Migrating them now...")

        # Migrate orphaned Premier players (all, not just active)
        if orphaned_premier > 0:
            migrated_premier = session.query(Player).join(League, Player.primary_league_id == League.id).join(Season, League.season_id == Season.id).filter(
                Season.league_type == 'Pub League',
                Season.id != new_season.id,
                League.name == 'Premier'
            ).update({
                Player.primary_league_id: premier_league_id,
                Player.league_id: premier_league_id
            }, synchronize_session=False)
            logger.info(f"Migrated {migrated_premier} orphaned Premier players (active + inactive)")

        # Migrate orphaned Classic players (all, not just active)
        if orphaned_classic > 0:
            migrated_classic = session.query(Player).join(League, Player.primary_league_id == League.id).join(Season, League.season_id == Season.id).filter(
                Season.league_type == 'Pub League',
                Season.id != new_season.id,
                League.name == 'Classic'
            ).update({
                Player.primary_league_id: classic_league_id,
                Player.league_id: classic_league_id
            }, synchronize_session=False)
            logger.info(f"Migrated {migrated_classic} orphaned Classic players (active + inactive)")

        session.commit()
    else:
        logger.info("No orphaned players found - all players are in the new season")
    
    # Step 4: Role-based validation to ensure players are in correct leagues for their roles
    logger.info("Performing role-based league validation...")
    
    # Find players with pl-premier role not in Premier league
    misplaced_premier = session.query(Player).join(User, Player.user_id == User.id).join(user_roles, User.id == user_roles.c.user_id).join(Role, user_roles.c.role_id == Role.id).filter(
        Role.name == 'pl-premier',
        Player.is_current_player == True,
        Player.primary_league_id != premier_league_id
    ).count()
    
    # Find players with pl-classic role not in Classic league  
    misplaced_classic = session.query(Player).join(User, Player.user_id == User.id).join(user_roles, User.id == user_roles.c.user_id).join(Role, user_roles.c.role_id == Role.id).filter(
        Role.name == 'pl-classic',
        Player.is_current_player == True,
        Player.primary_league_id != classic_league_id
    ).count()
    
    if misplaced_premier > 0 or misplaced_classic > 0:
        logger.warning(f"Found {misplaced_premier} Premier-role players in wrong league and {misplaced_classic} Classic-role players in wrong league")
        logger.info("Note: Players will stay in their current leagues as intended. Use user management to move players between leagues during the season if needed.")
    else:
        logger.info("All players are in leagues matching their roles")

    return new_season


def create_ecs_fc_season(session, season_name: str) -> Optional[Season]:
    """
    Create a new ECS FC season with its default league.

    If an old ECS FC season exists, mark it as not current and perform a rollover.
    Includes safety checks for orphaned players similar to create_pub_league_season().

    Args:
        session: Database session.
        season_name (str): Name of the new ECS FC season.

    Returns:
        Optional[Season]: The newly created season or None if it already exists.
    """
    season_name = season_name.strip()
    existing = session.query(Season).filter(
        func.lower(Season.name) == season_name.lower(),
        Season.league_type == 'ECS FC'
    ).first()

    if existing:
        logger.warning(f'Season "{season_name}" already exists for ECS FC.')
        return None

    old_season = session.query(Season).filter_by(
        league_type='ECS FC',
        is_current=True
    ).first()

    new_season = Season(
        name=season_name,
        league_type='ECS FC',
        is_current=True
    )
    session.add(new_season)
    session.flush()

    ecs_fc_league = League(name="ECS FC", season_id=new_season.id)
    session.add(ecs_fc_league)

    if old_season:
        old_season.is_current = False
        rollover_league(session, old_season, new_season)
    else:
        # No old current season found - still need to commit the new season/leagues
        logger.warning("No current ECS FC season found for rollover")
        session.commit()

    # Safety check: Ensure ALL ECS FC players (active + inactive) are in the new season
    # This handles edge cases where rollover might have missed some players
    # We migrate ALL players so inactive ones are ready if they return later
    session.flush()  # Ensure new league is committed first

    logger.info("Performing safety check for any remaining players in old ECS FC seasons...")
    ecs_fc_league_id = session.query(League).filter_by(name="ECS FC", season_id=new_season.id).first().id

    # Find ANY players still in old ECS FC seasons (active or inactive)
    orphaned_ecs_fc = session.query(Player).join(
        League, Player.primary_league_id == League.id
    ).join(
        Season, League.season_id == Season.id
    ).filter(
        Season.league_type == 'ECS FC',
        Season.id != new_season.id,
        League.name == 'ECS FC'
    ).count()

    if orphaned_ecs_fc > 0:
        logger.warning(f"Found {orphaned_ecs_fc} ECS FC players still in old seasons. Migrating them now...")

        # Migrate orphaned ECS FC players (all, not just active)
        migrated_ecs_fc = session.query(Player).join(
            League, Player.primary_league_id == League.id
        ).join(
            Season, League.season_id == Season.id
        ).filter(
            Season.league_type == 'ECS FC',
            Season.id != new_season.id,
            League.name == 'ECS FC'
        ).update({
            Player.primary_league_id: ecs_fc_league_id,
            Player.league_id: ecs_fc_league_id
        }, synchronize_session=False)
        logger.info(f"Migrated {migrated_ecs_fc} orphaned ECS FC players (active + inactive)")

        session.commit()
    else:
        logger.info("No orphaned ECS FC players found - all players are in the new season")

    # Role-based validation for ECS FC
    logger.info("Performing role-based league validation for ECS FC...")

    # Find players with ecs-fc role not in ECS FC league
    misplaced_ecs_fc = session.query(Player).join(
        User, Player.user_id == User.id
    ).join(
        user_roles, User.id == user_roles.c.user_id
    ).join(
        Role, user_roles.c.role_id == Role.id
    ).filter(
        Role.name == 'ecs-fc',
        Player.is_current_player == True,
        Player.primary_league_id != ecs_fc_league_id
    ).count()

    if misplaced_ecs_fc > 0:
        logger.warning(f"Found {misplaced_ecs_fc} ECS FC-role players in wrong league")
        logger.info("Note: Players will stay in their current leagues as intended. Use user management to move players between leagues during the season if needed.")
    else:
        logger.info("All ECS FC players are in leagues matching their roles")

    return new_season


@season_bp.route('/<int:season_id>/set_current', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def set_current_season(season_id):
    """
    Set the specified season as the current season for its league type.

    Args:
        season_id (int): The ID of the season to be set as current.

    Returns:
        A redirect response to the season management page.
    """
    session = g.db_session
    season = session.query(Season).get(season_id)
    if not season:
        show_error('Season not found.')
        return redirect(url_for('publeague.season.manage_seasons'))

    try:
        # Mark all seasons of this league type as not current.
        session.query(Season).filter_by(league_type=season.league_type).update({'is_current': False})
        season.is_current = True

        # Switching which Pub League season is current re-hides team
        # assignments until an admin re-runs the reveal.
        if season.league_type == 'Pub League':
            from app.services.team_visibility import reset_teams_reveal
            reset_teams_reveal(session)

        show_success(f'Season "{season.name}" is now the current season for {season.league_type}.')
    except Exception as e:
        logger.error(f"Error setting current season: {e}")
        show_error('Failed to set the current season.')
        raise

    return redirect(url_for('publeague.season.manage_seasons'))


def restore_players_to_previous_leagues(session, previous_season):
    """
    NOT IMPLEMENTED — do not wire this to any "revert rollover" action.

    This was a stub whose Premier/Classic branches were `pass` and which then
    logged success. Wiring a revert button to it would silently restore NOTHING
    while reporting success — a data-integrity landmine. The correct source of
    truth for reverting is the ``PlayerTeamSeason`` snapshot written by
    ``rollover_league`` (see ``restore_season_memberships``), or a database
    backup restore. Fail loudly until implemented against that snapshot.
    """
    raise NotImplementedError(
        "restore_players_to_previous_leagues is not implemented. Revert via a "
        "database backup restore or PlayerTeamSeason-based restore_season_memberships, "
        "not this stub."
    )


@season_bp.route('/delete/<int:season_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_season(season_id):
    """
    Delete the specified season along with its associated leagues, teams, and schedules.
    This is a comprehensive "undo" operation that:
    - Deletes all matches, schedules, teams, and leagues
    - Cleans up Discord channels and roles
    - Removes player team assignments
    - Restores the previous season as current
    - Essentially reverses everything created by the season wizard

    Args:
        season_id (int): The ID of the season to delete.

    Returns:
        A redirect response to the season management page.
    """
    session = g.db_session
    season = session.query(Season).get(season_id)
    if not season:
        show_error('Season not found.')
        return redirect(url_for('publeague.season.manage_seasons'))

    season_name = season.name
    was_current = season.is_current
    discord_cleanup_queued = False

    # Safety guard: a season holding reported match data carries real history
    # (stats, standings, awards) that must not be silently destroyed. Refuse
    # deletion outright when any match in the season has scores entered.
    # Unplayed seasons (e.g. a wizard-generated mistake) remain freely deletable.
    from app.models import Match
    from sqlalchemy import or_
    reported_match_count = session.query(Match).join(Schedule).filter(
        Schedule.season_id == season_id,
        or_(
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None)
        )
    ).count()
    if reported_match_count > 0:
        show_error(
            f'Cannot delete season "{season_name}": {reported_match_count} '
            f'match(es) have reported scores. This season holds real player '
            f'and team history (stats, standings, awards). If deletion is '
            f'genuinely required, contact a developer to do it manually.'
        )
        return redirect(url_for('publeague.season.manage_seasons'))

    try:
        logger.info(f"Starting comprehensive deletion of season: {season_name}")
        
        # Get all teams for Discord cleanup before deleting them
        teams_to_cleanup = []
        leagues = session.query(League).filter_by(season_id=season_id).all()
        
        for league in leagues:
            teams = session.query(Team).filter_by(league_id=league.id).all()
            for team in teams:
                # Only queue Discord cleanup for real teams (not placeholders) 
                # Note: Placeholder teams should no longer exist as real Team entities, but check for backward compatibility
                if team.name not in ['FUN WEEK', 'BYE', 'TST'] and team.discord_channel_id:
                    teams_to_cleanup.append({
                        'id': team.id,
                        'name': team.name,
                        'discord_channel_id': team.discord_channel_id,
                        'discord_coach_role_id': team.discord_coach_role_id,
                        'discord_player_role_id': team.discord_player_role_id
                    })
        
        # Queue Discord cleanup tasks before deleting teams
        if teams_to_cleanup:
            try:
                from app.tasks.discord_cleanup import cleanup_pub_league_discord_resources_celery_task
                cleanup_pub_league_discord_resources_celery_task.delay(season_id)
                discord_cleanup_queued = True
                logger.info(f"Queued Discord cleanup for {len(teams_to_cleanup)} teams")
            except Exception as e:
                logger.error(f"Failed to queue Discord cleanup: {e}")
                # Continue with deletion even if Discord cleanup fails
        
        # Delete draft order history for this season
        from app.models.league_features import DraftOrderHistory
        session.query(DraftOrderHistory).filter_by(season_id=season_id).delete()
        logger.info(f"Deleted draft order history for season {season_id}")
        
        # Delete player team assignments for this season
        session.query(PlayerTeamSeason).filter_by(season_id=season_id).delete()
        logger.info(f"Deleted player team assignments for season {season_id}")
        
        # Delete schedule templates first (they reference leagues and teams)
        for league in leagues:
            from app.models.matches import ScheduleTemplate
            session.query(ScheduleTemplate).filter_by(league_id=league.id).delete()
        
        # Delete associated leagues, teams, schedules, and matches
        for league in leagues:
            teams = session.query(Team).filter_by(league_id=league.id).all()
            for team in teams:
                # Delete scheduled messages first (they reference matches)
                from app.models import Match
                from app.models.communication import ScheduledMessage
                matches_to_delete = session.query(Match).filter(
                    (Match.home_team_id == team.id) | (Match.away_team_id == team.id)
                ).all()
                
                for match in matches_to_delete:
                    session.query(ScheduledMessage).filter_by(match_id=match.id).delete()
                
                # Delete matches after scheduled messages are deleted
                session.query(Match).filter(
                    (Match.home_team_id == team.id) | (Match.away_team_id == team.id)
                ).delete(synchronize_session=False)
                
                # Delete schedules after matches are deleted
                session.query(Schedule).filter_by(team_id=team.id).delete()
                
                session.delete(team)
            
            # Delete any league-specific configurations
            try:
                from app.models.matches import SeasonConfiguration
                session.query(SeasonConfiguration).filter_by(league_id=league.id).delete()
            except Exception:
                pass  # SeasonConfiguration might not exist
            
            # Delete auto schedule configs for this league
            try:
                from app.models.matches import AutoScheduleConfig
                session.query(AutoScheduleConfig).filter_by(league_id=league.id).delete()
            except Exception:
                pass  # AutoScheduleConfig might not exist
            
            # Delete week configurations for this league
            try:
                from app.models.matches import WeekConfiguration
                session.query(WeekConfiguration).filter_by(league_id=league.id).delete()
            except Exception:
                pass  # WeekConfiguration might not exist
            
            # Update players to remove league association
            from app.models.players import Player
            session.query(Player).filter_by(league_id=league.id).update({'league_id': None})
            session.query(Player).filter_by(primary_league_id=league.id).update({'primary_league_id': None})
            
            session.delete(league)
        
        # If this was the current season, restore the previous season as current
        previous_season = None
        if was_current:
            # Find the most recent season before this one
            previous_season = session.query(Season).filter(
                Season.id != season_id
            ).order_by(Season.id.desc()).first()
            
            if previous_season:
                previous_season.is_current = True
                session.add(previous_season)
                logger.info(f"Restored {previous_season.name} as current season")
                
                # No need to restore - all data is tied to seasons and will display correctly

        # Finally, delete the season itself
        session.delete(season)
        session.commit()
        
        # Build success message
        message_parts = [f'Season "{season_name}" has been completely deleted']
        
        if discord_cleanup_queued:
            message_parts.append('Discord channels and roles cleanup queued')
        
        if previous_season:
            message_parts.append(f'Restored "{previous_season.name}" as current season')
        elif was_current:
            message_parts.append('No previous season found to restore')
        
        message_parts.append('All teams, matches, and player assignments removed')
        
        show_success('. '.join(message_parts))
        logger.info(f"Successfully deleted season {season_name} and all associated data")
        
    except Exception as e:
        logger.error(f"Error deleting season {season_name}: {e}", exc_info=True)
        session.rollback()
        show_error(f'Failed to delete season "{season_name}". Please check logs for details.')
        raise

    return redirect(url_for('publeague.season.manage_seasons'))


# ===========================================================================
# Guided Season Rollover
# ===========================================================================
# A step-by-step admin flow (preview -> backup -> execute, plus restore) that
# wraps the same end-to-end season creation the Season Builder wizard uses.
# Routes are mounted under /publeague/seasons (see app/publeague.py).

@season_bp.route('/rollover', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def rollover_wizard():
    """Deprecated URL — the wizard now renders inside the admin-panel shell at
    admin_panel.season_rollover. Redirect so old bookmarks/links keep working.
    (The JSON companion routes below stay on this blueprint.)"""
    return redirect(url_for('admin_panel.season_rollover'))


@season_bp.route('/rollover/preview', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def rollover_preview():
    """Return a read-only dry-run preview of the proposed rollover (no writes)."""
    from app.season_rollover_service import build_rollover_preview

    session = g.db_session
    try:
        data = request.get_json() or {}
        league_type = data.get('league_type')
        if league_type not in ('Pub League', 'ECS FC'):
            return jsonify({'success': False, 'error': 'Invalid league type.'}), 400

        preview = build_rollover_preview(
            session=session,
            league_type=league_type,
            new_season_name=(data.get('new_season_name') or '').strip(),
            start_date=data.get('start_date'),
            team_counts=data.get('team_counts') or {},
            week_config_summary=data.get('week_config_summary') or {},
            delete_discord_channels=data.get('delete_discord_channels', True),
            create_discord_channels=data.get('create_discord_channels', True),
        )
        return jsonify(preview)
    except Exception as e:
        logger.error(f"Rollover preview failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to build preview.'}), 500


@season_bp.route('/rollover/backup', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def rollover_backup():
    """Create a persistent pg_dump backup before executing the rollover."""
    from app.season_rollover_service import create_database_backup

    try:
        result = create_database_backup()
        status = 200 if result.get('success') else 500
        return jsonify(result), status
    except Exception as e:
        logger.error(f"Rollover backup failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Backup failed.'}), 500


@season_bp.route('/rollover/backups', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def rollover_backups():
    """List existing backup files (newest first)."""
    from app.season_rollover_service import list_backups

    try:
        return jsonify({'success': True, 'backups': list_backups()})
    except Exception as e:
        logger.error(f"Listing backups failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Could not list backups.'}), 500


@season_bp.route('/rollover/backup/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def rollover_backup_delete():
    """Delete a single backup file. Global-Admin-only (they're large + destructive
    to lose the wrong one, but this is just removing a file, not the DB)."""
    from app.season_rollover_service import delete_database_backup

    data = request.get_json() or {}
    filename = data.get('filename')
    if not filename:
        return jsonify({'success': False, 'error': 'No backup filename provided.'}), 400
    try:
        result = delete_database_backup(filename)
        return jsonify(result), (200 if result.get('success') else 400)
    except Exception as e:
        logger.error(f"Rollover backup delete failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Delete failed.'}), 500


@season_bp.route('/rollover/discord-check', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def rollover_discord_check():
    """LIVE read from the Discord bot: cross-reference the current season's stored
    channel/role IDs against what actually exists in the guild, so admins see the
    ground truth of what will be removed and any DB<->Discord drift (a stored
    channel/role that's already gone). Read-only; never mutates Discord."""
    import os
    import requests

    data = request.get_json() or {}
    league_type = data.get('league_type') or 'Pub League'
    session = g.db_session

    bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
    guild_id = os.getenv('SERVER_ID')
    if not guild_id:
        return jsonify({'success': False, 'available': False,
                        'error': 'Discord guild (SERVER_ID) is not configured.'})

    try:
        ch = requests.get(f"{bot_api_url}/api/server/guilds/{guild_id}/channels", timeout=8)
        rl = requests.get(f"{bot_api_url}/api/server/guilds/{guild_id}/roles", timeout=8)
        if ch.status_code != 200 or rl.status_code != 200:
            return jsonify({'success': False, 'available': False,
                            'error': f'Bot API returned {ch.status_code}/{rl.status_code}.'})
        live_channels = {str(c.get('id')): c.get('name') for c in (ch.json() or [])}
        live_roles = {str(r.get('id')): r.get('name') for r in (rl.json() or [])}
    except Exception as e:
        logger.warning(f"Live Discord check failed: {e}")
        return jsonify({'success': False, 'available': False,
                        'error': 'Could not reach the Discord bot (is it running?).'})

    def _res(rid, table):
        if not rid:
            return None
        rid = str(rid)
        return {'id': rid, 'name': table.get(rid), 'exists': rid in table}

    def _season_teams(season):
        if not season:
            return None
        teams = session.query(Team).join(
            League, Team.league_id == League.id
        ).filter(League.season_id == season.id).order_by(Team.name).all()
        return {
            'name': season.name,
            'teams': [{
                'name': t.name,
                'channel': _res(t.discord_channel_id, live_channels),
                'player_role': _res(t.discord_player_role_id, live_roles),
                'coach_role': _res(t.discord_coach_role_id, live_roles),
            } for t in teams],
        }

    # current = the live season (pre-execute: the one to be deleted; post-execute:
    # the newly-created one — verify it was CREATED). previous = the most recent
    # non-current season (post-execute: the just-rolled one — verify it was CLEANED).
    current = session.query(Season).filter_by(
        league_type=league_type, is_current=True
    ).first()
    previous = session.query(Season).filter(
        Season.league_type == league_type, Season.is_current.is_(False)
    ).order_by(Season.id.desc()).first()

    return jsonify({
        'success': True, 'available': True,
        'current': _season_teams(current),
        'previous': _season_teams(previous),
    })


@season_bp.route('/rollover/execute', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def rollover_execute():
    """
    Execute the actual rollover: reuses the shared ``_execute_season_creation``
    helper (the same code the Season Builder wizard runs). Requires that a
    backup was created first (``backup_filename`` must exist) OR an explicit
    ``skip_backup=true`` acknowledgement.
    """
    from app.season_rollover_service import _safe_backup_path
    from app.auto_schedule_routes import _execute_season_creation

    session = g.db_session
    data = request.get_json() or {}

    backup_filename = data.get('backup_filename')
    skip_backup = bool(data.get('skip_backup'))

    # Backup gate: either a verified backup exists, or the admin explicitly
    # acknowledged skipping it.
    if not skip_backup:
        import os
        path = _safe_backup_path(backup_filename) if backup_filename else None
        # Require a real, non-empty backup file — a 0-byte or stale placeholder must
        # not satisfy the gate (that would give false confidence a backup exists).
        if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
            return jsonify({
                'success': False,
                'error': ('A valid (non-empty) database backup is required before '
                          'executing. Create a fresh backup first, or resend with '
                          'skip_backup=true to explicitly proceed without one.')
            }), 400

    # Deliberate-confirmation gate. Rollover is destructive and (without a backup)
    # irreversible, so require the admin to type ROLLOVER — mirroring the restore
    # gate, which the far-less-destructive restore already had.
    if str(data.get('confirm') or '').strip().upper() != 'ROLLOVER':
        return jsonify({
            'success': False,
            'error': 'Rollover not confirmed. Type ROLLOVER to confirm this destructive action.'
        }), 400

    # The wizard payload nested under "season" carries the exact shape the
    # Season Builder posts; fall back to the top-level data for flexibility.
    season_payload = data.get('season') or data.get('payload') or data
    try:
        payload, status = _execute_season_creation(session, season_payload)
        return jsonify(payload), status
    except Exception as e:
        logger.error(f"Rollover execute failed: {e}", exc_info=True)
        session.rollback()
        return jsonify({'error': 'An error occurred while executing the rollover.'}), 500


@season_bp.route('/rollover/restore', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def rollover_restore():
    """
    DESTRUCTIVE: restore the database from a backup file. Global-Admin-only and
    gated on an explicit confirm token (``confirm`` == 'RESTORE').
    """
    from app.season_rollover_service import restore_database_backup

    data = request.get_json() or {}
    filename = data.get('filename')
    confirm = data.get('confirm')

    if confirm != 'RESTORE':
        return jsonify({
            'success': False,
            'error': 'Restore not confirmed. Type RESTORE to confirm this destructive action.'
        }), 400
    if not filename:
        return jsonify({'success': False, 'error': 'No backup filename provided.'}), 400

    try:
        result = restore_database_backup(filename)
        status = 200 if result.get('success') else 500
        return jsonify(result), status
    except Exception as e:
        logger.error(f"Rollover restore failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Restore failed.'}), 500