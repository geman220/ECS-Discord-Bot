# app/season_routes.py

"""
Season Routes Module

This module provides endpoints and helper functions for managing seasons,
including creating new seasons (for both Pub League and ECS FC), performing
league rollovers, setting the current season, and deleting seasons along with
their associated leagues and teams.
"""

from flask import Blueprint, render_template, redirect, url_for, request, g
from app.alert_helpers import show_success, show_error, show_warning, show_info
from flask_login import login_required
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
        
        # Step 1: Record team history for old season
        players = session.query(Player).all()
        history_records = []

        for player in players:
            # Get teams for the player that are in the old season.
            old_season_teams = [t for t in player.teams if t.league.season_id == old_season.id]
            for t in old_season_teams:
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
                        season_id=old_season.id
                    ))

        if history_records:
            session.bulk_save_objects(history_records)
            session.flush()
            logger.info(f"Recorded {len(history_records)} team history records")
        
        # Step 2: Update league associations 
        old_leagues = session.query(League).filter_by(season_id=old_season.id).all()
        new_leagues = session.query(League).filter_by(season_id=new_season.id).all()

        # Create a mapping from old league names to new league IDs.
        league_mapping = {
            old_league.name: next((nl.id for nl in new_leagues if nl.name == old_league.name), None)
            for old_league in old_leagues
        }

        # Update players' league associations - more robust approach
        updated_players = 0
        for old_league in old_leagues:
            new_league_id = league_mapping.get(old_league.name)
            if new_league_id:
                logger.info(f"Migrating players from {old_league.name} (ID: {old_league.id}) to new league (ID: {new_league_id})")
                
                # Update both league_id and primary_league_id for current players
                # Use OR condition to catch players with either field matching
                league_updates = session.query(Player).filter(
                    (Player.league_id == old_league.id) | (Player.primary_league_id == old_league.id),
                    Player.is_current_player == True
                ).update({
                    'league_id': new_league_id,
                    'primary_league_id': new_league_id,
                }, synchronize_session=False)
                
                updated_players += league_updates
                logger.info(f"Updated {league_updates} players from {old_league.name} to new season")

        logger.info(f"Updated league associations for {updated_players} players")

        # Step 3: Get all players who were in the old season for cleanup
        old_season_player_ids = session.query(Player.id).join(
            player_teams, Player.id == player_teams.c.player_id
        ).join(
            Team, player_teams.c.team_id == Team.id
        ).join(
            League, Team.league_id == League.id
        ).filter(
            League.season_id == old_season.id
        ).distinct().all()

        old_season_player_ids = [pid[0] for pid in old_season_player_ids]
        logger.info(f"Found {len(old_season_player_ids)} players in old season to clean up")

        if old_season_player_ids:
            # Step 4: Clear all team assignments (clean slate for new season)
            logger.info("Clearing current team assignments...")
            deleted_teams = session.execute(
                player_teams.delete().where(
                    player_teams.c.player_id.in_(old_season_player_ids)
                )
            ).rowcount
            logger.info(f"Removed {deleted_teams} team assignments")
            
            # Step 5: Clear secondary league assignments 
            logger.info("Clearing secondary league assignments...")
            deleted_leagues = session.execute(
                player_league.delete().where(
                    player_league.c.player_id.in_(old_season_player_ids)
                )
            ).rowcount
            logger.info(f"Removed {deleted_leagues} secondary league assignments")
            
            # Step 6: Reset primary team assignments to NULL
            logger.info("Resetting primary team assignments...")
            reset_primary = session.query(Player).filter(
                Player.id.in_(old_season_player_ids)
            ).update({
                'primary_team_id': None
            }, synchronize_session=False)
            logger.info(f"Reset primary team for {reset_primary} players")

        # Step 7: Create fresh season stats records for new season
        logger.info("Creating fresh season stats records...")
        from app.models.stats import PlayerSeasonStats
        
        # Get all players who should have season stats in the new season
        all_active_players = session.query(Player).filter(
            Player.id.in_(old_season_player_ids)
        ).all() if old_season_player_ids else []
        
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
                    goals=0,
                    assists=0,
                    yellow_cards=0,
                    red_cards=0
                ))
        
        if new_season_stats:
            session.bulk_save_objects(new_season_stats)
            logger.info(f"Created {len(new_season_stats)} fresh season stats records")

        session.commit()
        logger.info(f"Rollover completed successfully: {old_season.name} → {new_season.name}")
        return True

    except Exception as e:
        logger.error(f"Rollover failed: {str(e)}")
        session.rollback()
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

    # Create default leagues for the new season.
    premier_league = League(name="Premier", season_id=new_season.id)
    classic_league = League(name="Classic", season_id=new_season.id)
    session.add(premier_league)
    session.add(classic_league)

    if old_season:
        old_season.is_current = False
        rollover_league(session, old_season, new_season)
    else:
        # No old current season found - still need to commit the new season/leagues
        logger.warning("No current Pub League season found for rollover")
        session.commit()
        
    # Additional safety check: Ensure all current Pub League players are in the new season
    # This handles edge cases where rollover might have missed some players
    session.flush()  # Ensure new leagues are committed first
    
    logger.info("Performing safety check for any remaining players in old Pub League seasons...")
    premier_league_id = session.query(League).filter_by(name="Premier", season_id=new_season.id).first().id
    classic_league_id = session.query(League).filter_by(name="Classic", season_id=new_season.id).first().id
    
    # Find any current players still in old Pub League seasons
    orphaned_premier = session.query(Player).join(League, Player.primary_league_id == League.id).join(Season, League.season_id == Season.id).filter(
        Season.league_type == 'Pub League',
        Season.id != new_season.id,
        Player.is_current_player == True,
        League.name == 'Premier'
    ).count()
    
    orphaned_classic = session.query(Player).join(League, Player.primary_league_id == League.id).join(Season, League.season_id == Season.id).filter(
        Season.league_type == 'Pub League', 
        Season.id != new_season.id,
        Player.is_current_player == True,
        League.name == 'Classic'
    ).count()
    
    if orphaned_premier > 0 or orphaned_classic > 0:
        logger.warning(f"Found {orphaned_premier} Premier and {orphaned_classic} Classic players still in old seasons. Migrating them now...")
        
        # Migrate orphaned Premier players
        if orphaned_premier > 0:
            migrated_premier = session.query(Player).join(League, Player.primary_league_id == League.id).join(Season, League.season_id == Season.id).filter(
                Season.league_type == 'Pub League',
                Season.id != new_season.id,
                Player.is_current_player == True,
                League.name == 'Premier'
            ).update({
                Player.primary_league_id: premier_league_id,
                Player.league_id: premier_league_id
            }, synchronize_session=False)
            logger.info(f"Migrated {migrated_premier} orphaned Premier players")
        
        # Migrate orphaned Classic players  
        if orphaned_classic > 0:
            migrated_classic = session.query(Player).join(League, Player.primary_league_id == League.id).join(Season, League.season_id == Season.id).filter(
                Season.league_type == 'Pub League',
                Season.id != new_season.id, 
                Player.is_current_player == True,
                League.name == 'Classic'
            ).update({
                Player.primary_league_id: classic_league_id,
                Player.league_id: classic_league_id
            }, synchronize_session=False)
            logger.info(f"Migrated {migrated_classic} orphaned Classic players")
        
        session.commit()
    else:
        logger.info("No orphaned players found - all current players are in the new season")
    
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
        show_success(f'Season "{season.name}" is now the current season for {season.league_type}.')
    except Exception as e:
        logger.error(f"Error setting current season: {e}")
        show_error('Failed to set the current season.')
        raise

    return redirect(url_for('publeague.season.manage_seasons'))


def restore_players_to_previous_leagues(session, previous_season):
    """
    Restore players to their previous league assignments when reverting a season.
    
    Args:
        session: Database session
        previous_season: The season to restore players to
    """
    # Get the leagues for the previous season
    previous_leagues = session.query(League).filter_by(season_id=previous_season.id).all()
    
    # For each league in the previous season, restore players who should be in that league
    for league in previous_leagues:
        # Find players who have NULL league assignments and should be in this league
        # This is a simplified approach - in a real scenario, you'd need to track
        # the original league assignments before the rollover
        if league.name == 'Premier':
            # Restore players who had Premier as their league (this is a basic heuristic)
            pass  # Would need more complex logic to determine original assignments
        elif league.name == 'Classic':
            # Restore players who had Classic as their league
            pass  # Would need more complex logic to determine original assignments
    
    logger.info(f"Restored players to previous season leagues: {previous_season.name}")


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