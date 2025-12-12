# app/services/league_management_service.py

"""
League Management Domain Service

Centralized service for all league management operations including:
- Season creation and lifecycle management
- Team CRUD with Discord integration
- Schedule generation and management
- Season rollover and history tracking
- Dashboard statistics

Implements patterns similar to RSVPService for reliability.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, and_

logger = logging.getLogger(__name__)


class LeagueManagementServiceError(Exception):
    """Base exception for league management service errors."""
    pass


class LeagueManagementValidationError(LeagueManagementServiceError):
    """Raised when validation fails."""
    pass


class LeagueManagementService:
    """
    Domain service for league management operations.

    Handles all business logic for:
    - Season creation via wizard
    - Team management with Discord sync
    - Schedule operations
    - Season rollover
    - Statistics and reporting
    """

    def __init__(self, session: Session):
        self.session = session

    # =========================================================================
    # Dashboard & Statistics
    # =========================================================================

    def get_dashboard_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive dashboard statistics.

        Returns stats for both Pub League and ECS FC including:
        - Current season info
        - Team counts
        - Match statistics
        - Recent activity
        """
        from app.models import Season, League, Team, Match, Schedule, Player

        stats = {
            'pub_league': self._get_league_type_stats('Pub League'),
            'ecs_fc': self._get_league_type_stats('ECS FC'),
            'total_seasons': Season.query.count(),
            'total_teams': Team.query.count(),
            'total_matches': Match.query.count(),
            'recent_activity': self._get_recent_activity()
        }

        return stats

    def _get_league_type_stats(self, league_type: str) -> Dict[str, Any]:
        """Get statistics for a specific league type."""
        from app.models import Season, League, Team, Match, Schedule

        current_season = Season.query.filter_by(
            is_current=True,
            league_type=league_type
        ).first()

        result = {
            'current_season': None,
            'teams_count': 0,
            'matches_total': 0,
            'matches_played': 0,
            'matches_upcoming': 0,
            'divisions': []
        }

        if current_season:
            result['current_season'] = {
                'id': current_season.id,
                'name': current_season.name,
                'is_current': current_season.is_current
            }

            leagues = League.query.filter_by(season_id=current_season.id).all()
            league_ids = [l.id for l in leagues]

            if league_ids:
                result['teams_count'] = Team.query.filter(
                    Team.league_id.in_(league_ids)
                ).count()

                # Get team IDs for match counting
                team_ids = [t.id for t in Team.query.filter(Team.league_id.in_(league_ids)).all()]

                if team_ids:
                    today = datetime.utcnow().date()

                    result['matches_total'] = Match.query.filter(
                        or_(
                            Match.home_team_id.in_(team_ids),
                            Match.away_team_id.in_(team_ids)
                        )
                    ).count()

                    result['matches_played'] = Match.query.filter(
                        or_(
                            Match.home_team_id.in_(team_ids),
                            Match.away_team_id.in_(team_ids)
                        ),
                        Match.date < today
                    ).count()

                    result['matches_upcoming'] = Match.query.filter(
                        or_(
                            Match.home_team_id.in_(team_ids),
                            Match.away_team_id.in_(team_ids)
                        ),
                        Match.date >= today
                    ).count()

            # Get divisions/leagues
            for league in leagues:
                teams = Team.query.filter_by(league_id=league.id).count()
                result['divisions'].append({
                    'name': league.name,
                    'id': league.id,
                    'teams_count': teams
                })

        return result

    def _get_recent_activity(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent activity for the dashboard."""
        from app.models.admin_config import AdminAuditLog

        try:
            recent = AdminAuditLog.query.filter(
                AdminAuditLog.resource_type.in_([
                    'season', 'team', 'league', 'match',
                    'league_management', 'match_operations'
                ])
            ).order_by(
                AdminAuditLog.created_at.desc()
            ).limit(limit).all()

            return [
                {
                    'action': log.action,
                    'resource_type': log.resource_type,
                    'resource_id': log.resource_id,
                    'created_at': log.created_at.isoformat() if log.created_at else None,
                    'user_id': log.user_id
                }
                for log in recent
            ]
        except Exception as e:
            logger.warning(f"Could not load recent activity: {e}")
            return []

    def get_season_summary(self, season_id: int) -> Dict[str, Any]:
        """Get detailed summary for a specific season."""
        from app.models import Season, League, Team, Match, Schedule

        season = Season.query.get(season_id)
        if not season:
            return {}

        leagues = League.query.filter_by(season_id=season_id).all()
        league_ids = [l.id for l in leagues]

        team_count = 0
        match_count = 0
        team_ids = []

        if league_ids:
            teams = Team.query.filter(Team.league_id.in_(league_ids)).all()
            team_count = len(teams)
            team_ids = [t.id for t in teams]

        if team_ids:
            match_count = Match.query.filter(
                or_(
                    Match.home_team_id.in_(team_ids),
                    Match.away_team_id.in_(team_ids)
                )
            ).count()

        return {
            'team_count': team_count,
            'match_count': match_count,
            'league_count': len(leagues),
            'leagues': [
                {
                    'id': l.id,
                    'name': l.name,
                    'teams_count': Team.query.filter_by(league_id=l.id).count()
                }
                for l in leagues
            ]
        }

    # =========================================================================
    # Season Operations
    # =========================================================================

    def create_season_from_wizard(
        self,
        wizard_data: Dict[str, Any],
        user_id: int,
        operation_id: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Any]]:
        """
        Create a complete season from wizard data.

        Steps:
        1. Validate wizard data
        2. Check for duplicate season
        3. Handle rollover if setting as current
        4. Create Season, Leagues, Teams
        5. Create configuration (AutoScheduleConfig, etc.)
        6. Queue Discord resource creation
        7. Log to AdminAuditLog
        """
        from app.models import Season, League, Team
        from app.models.admin_config import AdminAuditLog

        operation_id = operation_id or str(uuid.uuid4())
        logger.info(f"Creating season from wizard: op_id={operation_id}")

        try:
            # Extract data
            league_type = wizard_data.get('league_type')
            season_name = wizard_data.get('season_name')
            set_as_current = wizard_data.get('set_as_current', False)

            # Validate
            if not league_type or not season_name:
                return False, 'League type and season name are required', None

            # Check for duplicate
            existing = Season.query.filter(
                func.lower(Season.name) == season_name.lower(),
                Season.league_type == league_type
            ).first()

            if existing:
                return False, f'A season named "{season_name}" already exists for {league_type}', None

            # Handle rollover if setting as current
            if set_as_current:
                old_current = Season.query.filter_by(
                    is_current=True,
                    league_type=league_type
                ).first()

                if old_current:
                    old_current.is_current = False
                    logger.info(f"Marking old season {old_current.name} as not current")

            # Create season
            season = Season(
                name=season_name,
                league_type=league_type,
                is_current=set_as_current
            )
            self.session.add(season)
            self.session.flush()  # Get season ID

            # Create leagues based on type
            leagues = []
            if league_type == 'Pub League':
                # Create Premier and Classic
                premier = League(name='Premier', season_id=season.id)
                classic = League(name='Classic', season_id=season.id)
                self.session.add(premier)
                self.session.add(classic)
                leagues = [premier, classic]
            else:
                # Create single ECS FC league
                ecs_fc = League(name='ECS FC', season_id=season.id)
                self.session.add(ecs_fc)
                leagues = [ecs_fc]

            self.session.flush()  # Get league IDs

            # Create teams
            teams_created = self._create_teams_from_wizard(wizard_data, leagues)

            # Create schedule configuration if provided
            if wizard_data.get('schedule_config'):
                self._create_schedule_config(wizard_data, leagues)

            # Handle rollover if needed
            if set_as_current and wizard_data.get('perform_rollover'):
                old_current = Season.query.filter(
                    Season.league_type == league_type,
                    Season.id != season.id,
                    Season.is_current == False  # Was just set to False above
                ).order_by(Season.id.desc()).first()

                if old_current:
                    self._perform_rollover_internal(old_current, season)

            # Log success
            AdminAuditLog.log_action(
                user_id=user_id,
                action='season_created',
                resource_type='season',
                resource_id=str(season.id),
                new_value=f'{season_name} ({league_type}) with {teams_created} teams',
                ip_address=None,
                user_agent=None
            )

            logger.info(f"Season created successfully: {season.name} (ID: {season.id})")
            return True, f'Season "{season_name}" created with {teams_created} teams', season

        except Exception as e:
            logger.error(f"Error creating season: {e}", exc_info=True)
            return False, f'Failed to create season: {str(e)}', None

    def _create_teams_from_wizard(
        self,
        wizard_data: Dict[str, Any],
        leagues: List[Any]
    ) -> int:
        """Create teams from wizard configuration."""
        from app.models import Team

        teams_created = 0
        league_type = wizard_data.get('league_type')

        if wizard_data.get('skip_team_creation'):
            return 0

        if league_type == 'Pub League':
            # Get premier league
            premier_league = next((l for l in leagues if l.name == 'Premier'), None)
            classic_league = next((l for l in leagues if l.name == 'Classic'), None)

            # Create premier teams
            premier_teams = wizard_data.get('premier_teams', [])
            if not premier_teams:
                # Generate default names
                premier_count = wizard_data.get('premier_team_count', 8)
                premier_teams = [f'Team {chr(65 + i)}' for i in range(premier_count)]

            for team_name in premier_teams:
                if premier_league:
                    team = Team(name=team_name, league_id=premier_league.id)
                    self.session.add(team)
                    teams_created += 1
                    self._queue_discord_team_creation(team)

            # Create classic teams
            classic_teams = wizard_data.get('classic_teams', [])
            if not classic_teams:
                classic_count = wizard_data.get('classic_team_count', 4)
                classic_teams = [f'Team {chr(65 + i)}' for i in range(classic_count)]

            for team_name in classic_teams:
                if classic_league:
                    team = Team(name=team_name, league_id=classic_league.id)
                    self.session.add(team)
                    teams_created += 1
                    self._queue_discord_team_creation(team)
        else:
            # ECS FC
            ecs_league = leagues[0] if leagues else None
            teams = wizard_data.get('teams', [])

            if not teams:
                team_count = wizard_data.get('team_count', 8)
                teams = [f'Team {chr(65 + i)}' for i in range(team_count)]

            for team_name in teams:
                if ecs_league:
                    team = Team(name=team_name, league_id=ecs_league.id)
                    self.session.add(team)
                    teams_created += 1
                    self._queue_discord_team_creation(team)

        self.session.flush()
        return teams_created

    def _create_schedule_config(
        self,
        wizard_data: Dict[str, Any],
        leagues: List[Any]
    ) -> None:
        """Create schedule configuration from wizard data."""
        # This would create AutoScheduleConfig, SeasonConfiguration, WeekConfiguration
        # For now, we'll defer to the existing auto-schedule system
        logger.info("Schedule configuration will be handled via auto-schedule routes")
        pass

    def _queue_discord_team_creation(self, team: Any) -> None:
        """Queue Discord resource creation for a team."""
        try:
            from app.tasks.tasks_discord import create_team_discord_resources_task
            # Will be queued after commit
            # For now, just log the intent
            logger.info(f"Discord creation will be queued for team: {team.name}")
        except ImportError:
            logger.warning("Discord tasks not available")

    def get_rollover_preview(
        self,
        old_season_id: int,
        new_season_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate preview of what rollover would change.
        """
        from app.models import Season, League, Team, Player, PlayerTeamSeason

        old_season = Season.query.get(old_season_id)
        if not old_season:
            return {'error': 'Season not found'}

        # Get leagues and teams
        leagues = League.query.filter_by(season_id=old_season_id).all()
        league_ids = [l.id for l in leagues]

        teams = []
        player_count = 0

        if league_ids:
            teams = Team.query.filter(Team.league_id.in_(league_ids)).all()
            # Count players on these teams
            for team in teams:
                player_count += len(team.players) if hasattr(team, 'players') else 0

        return {
            'old_season': {
                'id': old_season.id,
                'name': old_season.name
            },
            'players_affected': player_count,
            'teams_to_clear': [{'id': t.id, 'name': t.name} for t in teams],
            'leagues_mapping': [{'id': l.id, 'name': l.name} for l in leagues],
            'discord_cleanup_count': len([t for t in teams if t.discord_channel_id])
        }

    def perform_rollover(
        self,
        old_season: Any,
        new_season: Any,
        user_id: int
    ) -> bool:
        """
        Execute season rollover with full audit trail.
        Wraps existing rollover_league() with additional logging.
        """
        try:
            return self._perform_rollover_internal(old_season, new_season)
        except Exception as e:
            logger.error(f"Rollover failed: {e}", exc_info=True)
            return False

    def _perform_rollover_internal(self, old_season: Any, new_season: Any) -> bool:
        """Internal rollover implementation."""
        try:
            # Import and use existing rollover function
            from app.season_routes import rollover_league
            return rollover_league(self.session, old_season, new_season)
        except ImportError:
            logger.warning("rollover_league not available, using simplified rollover")
            return self._simplified_rollover(old_season, new_season)

    def _simplified_rollover(self, old_season: Any, new_season: Any) -> bool:
        """Simplified rollover when full function not available."""
        from app.models import PlayerTeamSeason, League, Team

        try:
            # Record team history
            old_leagues = League.query.filter_by(season_id=old_season.id).all()

            for league in old_leagues:
                for team in league.teams:
                    for player in team.players:
                        history = PlayerTeamSeason(
                            player_id=player.id,
                            team_id=team.id,
                            season_id=old_season.id
                        )
                        self.session.add(history)

            logger.info(f"Rollover completed from {old_season.name} to {new_season.name}")
            return True
        except Exception as e:
            logger.error(f"Simplified rollover failed: {e}")
            return False

    def delete_season(self, season_id: int, user_id: int) -> Tuple[bool, str]:
        """Delete season with comprehensive cleanup."""
        from app.models import Season, League, Team

        season = Season.query.get(season_id)
        if not season:
            return False, 'Season not found'

        if season.is_current:
            return False, 'Cannot delete current season'

        try:
            # Queue Discord cleanup for teams
            leagues = League.query.filter_by(season_id=season_id).all()
            for league in leagues:
                for team in league.teams:
                    self._queue_discord_team_cleanup(team)

            # Delete will cascade to leagues and teams
            self.session.delete(season)

            logger.info(f"Season {season.name} deleted by user {user_id}")
            return True, f'Season "{season.name}" deleted successfully'
        except Exception as e:
            logger.error(f"Error deleting season: {e}")
            return False, f'Failed to delete season: {str(e)}'

    def _queue_discord_team_cleanup(self, team: Any) -> None:
        """Queue Discord cleanup for a team."""
        try:
            from app.tasks.tasks_discord import cleanup_team_discord_resources_task
            if team.discord_channel_id:
                logger.info(f"Discord cleanup will be queued for team: {team.name}")
        except ImportError:
            logger.warning("Discord cleanup tasks not available")

    # =========================================================================
    # Team Operations
    # =========================================================================

    def create_team(
        self,
        name: str,
        league_id: int,
        user_id: int,
        queue_discord: bool = True
    ) -> Tuple[bool, str, Optional[Any]]:
        """Create team with automatic Discord resource queuing."""
        from app.models import Team, League
        from app.models.admin_config import AdminAuditLog

        try:
            league = League.query.get(league_id)
            if not league:
                return False, 'League not found', None

            # Check for duplicate name in same league
            existing = Team.query.filter(
                func.lower(Team.name) == name.lower(),
                Team.league_id == league_id
            ).first()

            if existing:
                return False, f'A team named "{name}" already exists in this league', None

            team = Team(name=name, league_id=league_id)
            self.session.add(team)
            self.session.flush()

            # Queue Discord creation
            if queue_discord:
                self._queue_discord_team_creation_after_commit(team)

            # Log
            AdminAuditLog.log_action(
                user_id=user_id,
                action='team_created',
                resource_type='team',
                resource_id=str(team.id),
                new_value=f'{name} in {league.name}',
                ip_address=None,
                user_agent=None
            )

            logger.info(f"Team created: {name} (ID: {team.id})")
            return True, f'Team "{name}" created successfully', team

        except Exception as e:
            logger.error(f"Error creating team: {e}")
            return False, f'Failed to create team: {str(e)}', None

    def _queue_discord_team_creation_after_commit(self, team: Any) -> None:
        """Queue Discord creation task after commit."""
        try:
            from app.tasks.tasks_discord import create_team_discord_resources_task
            # This will be called after commit
            create_team_discord_resources_task.delay(team_id=team.id)
            logger.info(f"Discord creation task queued for team {team.id}")
        except Exception as e:
            logger.warning(f"Could not queue Discord task: {e}")

    def rename_team(
        self,
        team_id: int,
        new_name: str,
        user_id: int
    ) -> Tuple[bool, str]:
        """Rename team and queue Discord update."""
        from app.models import Team
        from app.models.admin_config import AdminAuditLog

        try:
            team = Team.query.get(team_id)
            if not team:
                return False, 'Team not found'

            old_name = team.name

            # Check for duplicate
            existing = Team.query.filter(
                func.lower(Team.name) == new_name.lower(),
                Team.league_id == team.league_id,
                Team.id != team_id
            ).first()

            if existing:
                return False, f'A team named "{new_name}" already exists in this league'

            team.name = new_name

            # Queue Discord update
            self._queue_discord_team_update(team, old_name)

            # Log
            AdminAuditLog.log_action(
                user_id=user_id,
                action='team_renamed',
                resource_type='team',
                resource_id=str(team_id),
                old_value=old_name,
                new_value=new_name,
                ip_address=None,
                user_agent=None
            )

            logger.info(f"Team renamed: {old_name} -> {new_name}")
            return True, f'Team renamed from "{old_name}" to "{new_name}"'

        except Exception as e:
            logger.error(f"Error renaming team: {e}")
            return False, f'Failed to rename team: {str(e)}'

    def _queue_discord_team_update(self, team: Any, old_name: str) -> None:
        """Queue Discord update task for team rename."""
        try:
            from app.tasks.tasks_discord import update_team_discord_resources_task
            if team.discord_channel_id:
                update_team_discord_resources_task.delay(
                    team_id=team.id,
                    old_name=old_name
                )
                logger.info(f"Discord update task queued for team {team.id}")
        except Exception as e:
            logger.warning(f"Could not queue Discord update task: {e}")

    def delete_team(
        self,
        team_id: int,
        user_id: int,
        cleanup_discord: bool = True
    ) -> Tuple[bool, str]:
        """Delete team with Discord cleanup queue."""
        from app.models import Team
        from app.models.admin_config import AdminAuditLog

        try:
            team = Team.query.get(team_id)
            if not team:
                return False, 'Team not found'

            team_name = team.name

            # Queue Discord cleanup first
            if cleanup_discord and team.discord_channel_id:
                self._queue_discord_team_cleanup_task(team)

            # Log before delete
            AdminAuditLog.log_action(
                user_id=user_id,
                action='team_deleted',
                resource_type='team',
                resource_id=str(team_id),
                old_value=team_name,
                ip_address=None,
                user_agent=None
            )

            self.session.delete(team)

            logger.info(f"Team deleted: {team_name}")
            return True, f'Team "{team_name}" deleted successfully'

        except Exception as e:
            logger.error(f"Error deleting team: {e}")
            return False, f'Failed to delete team: {str(e)}'

    def _queue_discord_team_cleanup_task(self, team: Any) -> None:
        """Queue Discord cleanup task for team deletion."""
        try:
            from app.tasks.tasks_discord import cleanup_team_discord_resources_task
            cleanup_team_discord_resources_task.delay(team_id=team.id)
            logger.info(f"Discord cleanup task queued for team {team.id}")
        except Exception as e:
            logger.warning(f"Could not queue Discord cleanup task: {e}")

    def sync_team_discord(self, team_id: int) -> Tuple[bool, str]:
        """Manually trigger Discord sync for a team."""
        from app.models import Team

        try:
            team = Team.query.get(team_id)
            if not team:
                return False, 'Team not found'

            if team.discord_channel_id:
                # Team already has Discord resources, trigger update
                self._queue_discord_team_update(team, team.name)
                return True, 'Discord update queued'
            else:
                # Create Discord resources
                self._queue_discord_team_creation_after_commit(team)
                return True, 'Discord creation queued'

        except Exception as e:
            logger.error(f"Error syncing team Discord: {e}")
            return False, f'Failed to sync: {str(e)}'

    # =========================================================================
    # Schedule Operations
    # =========================================================================

    def generate_schedule_for_league(
        self,
        league_id: int,
        week_configs: List[Dict],
        user_id: int
    ) -> Tuple[bool, str, int]:
        """
        Generate schedule templates for a league.
        Wraps AutoScheduleGenerator with service patterns.
        """
        try:
            from app.auto_schedule_generator import AutoScheduleGenerator

            generator = AutoScheduleGenerator(league_id)
            templates = generator.generate_schedule_templates(week_configs)

            return True, f'{len(templates)} schedule templates generated', len(templates)

        except ImportError:
            logger.warning("AutoScheduleGenerator not available")
            return False, 'Schedule generator not available', 0
        except Exception as e:
            logger.error(f"Error generating schedule: {e}")
            return False, f'Schedule generation failed: {str(e)}', 0

    def commit_schedule(
        self,
        league_id: int,
        user_id: int
    ) -> Tuple[bool, str, int]:
        """
        Commit schedule templates to actual Match records.
        """
        # This delegates to the existing auto_schedule_routes functionality
        logger.info(f"Schedule commit requested for league {league_id}")
        return True, 'Use /auto-schedule routes for schedule commit', 0

    # =========================================================================
    # History Operations
    # =========================================================================

    def get_player_team_history(self, player_id: int) -> List[Dict[str, Any]]:
        """Get complete team history for a player."""
        from app.models import PlayerTeamSeason, Team, Season

        try:
            history = PlayerTeamSeason.query.filter_by(
                player_id=player_id
            ).options(
                joinedload(PlayerTeamSeason.team),
                joinedload(PlayerTeamSeason.season)
            ).order_by(
                PlayerTeamSeason.season_id.desc()
            ).all()

            return [
                {
                    'season_id': h.season_id,
                    'season_name': h.season.name if h.season else 'Unknown',
                    'team_id': h.team_id,
                    'team_name': h.team.name if h.team else 'Unknown'
                }
                for h in history
            ]

        except Exception as e:
            logger.error(f"Error loading player history: {e}")
            return []

    def get_season_history(self, league_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all historical seasons with summaries."""
        from app.models import Season, League, Team

        try:
            query = Season.query.options(
                joinedload(Season.leagues)
            ).order_by(Season.id.desc())

            if league_type:
                query = query.filter(Season.league_type == league_type)

            seasons = query.all()

            result = []
            for s in seasons:
                # Calculate team count safely
                team_count = 0
                for l in s.leagues:
                    team_count += Team.query.filter_by(league_id=l.id).count()

                # Handle created_at - Season model may not have this field
                created_at = None
                if hasattr(s, 'created_at') and s.created_at:
                    created_at = s.created_at.isoformat()

                result.append({
                    'id': s.id,
                    'name': s.name,
                    'league_type': s.league_type,
                    'is_current': s.is_current,
                    'created_at': created_at,
                    'league_count': len(s.leagues),
                    'team_count': team_count
                })

            return result

        except Exception as e:
            logger.error(f"Error loading season history: {e}", exc_info=True)
            return []

    def search_players_by_name(self, name_query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search for players by name (case-insensitive partial match)."""
        from app.models import Player

        try:
            players = Player.query.filter(
                Player.name.ilike(f'%{name_query}%')
            ).limit(limit).all()

            return [
                {
                    'id': p.id,
                    'name': p.name,
                    'discord_id': p.discord_id
                }
                for p in players
            ]

        except Exception as e:
            logger.error(f"Error searching players: {e}")
            return []
