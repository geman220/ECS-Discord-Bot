# app/utils/efficient_session_manager.py

from contextlib import contextmanager
from flask import current_app, g, has_request_context
import logging
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


class UserAuthData:
    """
    Lightweight user data structure for authentication without SQLAlchemy relationships.
    This avoids DetachedInstanceError while providing all needed auth data.
    """
    def __init__(self, id, username, is_active, roles, player_id=None, player_name=None, 
                 has_completed_onboarding=False, has_skipped_profile_creation=False):
        self.id = id
        self.username = username
        self.is_active = is_active
        self.is_authenticated = True
        self.is_anonymous = False
        self.roles = roles
        self.player_id = player_id
        self.player_name = player_name
        self.has_completed_onboarding = has_completed_onboarding
        self.has_skipped_profile_creation = has_skipped_profile_creation
    
    def has_role(self, role_name):
        return role_name.lower() in [r.lower() for r in self.roles]
    
    def has_permission(self, permission_name):
        # For now, simplified permission check
        return self.has_role('admin') or self.has_role('global admin')
    
    def get_id(self):
        return str(self.id)


class MatchData:
    """
    Lightweight match data structure to avoid DetachedInstanceError.
    """
    def __init__(self, match_id, date, time, home_team_id, away_team_id, 
                 home_team_name, away_team_name, home_players=None, away_players=None,
                 ref_id=None, home_verifier_id=None, away_verifier_id=None):
        self.id = match_id
        self.date = date
        self.time = time
        self.home_team_id = home_team_id
        self.away_team_id = away_team_id
        self.home_team_name = home_team_name
        self.away_team_name = away_team_name
        self.home_players = home_players or []
        self.away_players = away_players or []
        self.ref_id = ref_id
        self.home_verifier_id = home_verifier_id
        self.away_verifier_id = away_verifier_id

@contextmanager
def query_session():
    """
    Create a short-lived session specifically for single queries.
    
    This bypasses the request-scoped session for operations that:
    1. Don't need to be part of the main request transaction
    2. Are heavy/slow and would hold connections too long
    3. Are read-only operations
    
    Usage:
        with query_session() as session:
            user = session.query(User).get(user_id)
            # Session automatically closed after this block
    """
    # Use the same managed_session to prevent connection pool exhaustion
    from app.core.session_manager import managed_session
    with managed_session() as session:
        yield session

@contextmanager  
def bulk_operation_session():
    """
    Session for bulk operations that need longer connection time.
    
    Use for:
    - Data imports/exports
    - Batch updates
    - Complex reporting queries
    
    Has longer timeout (30s) but ensures proper cleanup.
    """
    # Use managed_session with longer timeout to prevent connection leaks
    from app.core.session_manager import managed_session
    with managed_session() as session:
        # Set longer timeout for bulk operations (if not using PgBouncer)
        from app.utils.pgbouncer_utils import set_session_timeout
        set_session_timeout(session, statement_timeout_seconds=30)
        yield session

def get_efficient_session():
    """
    Get the most appropriate session for the current context.
    
    Returns:
    - Request session if in request context and operation is part of main transaction
    - New query session if operation should be isolated
    """
    if has_request_context() and hasattr(g, 'db_session'):
        return g.db_session
    else:
        # Return a context manager for auto-cleanup
        return query_session()

class EfficientQuery:
    """
    Helper class for common query patterns with optimal session usage.
    """
    
    @staticmethod
    def get_user_for_auth(user_id):
        """
        Optimized user loading for authentication.
        Returns a lightweight user object with only essential data loaded.
        """
        with query_session() as session:
            from app.models import User, Role, Player
            from sqlalchemy.orm import selectinload
            
            user = session.query(User).options(
                selectinload(User.roles),
                selectinload(User.player)
            ).get(int(user_id))
            
            if user:
                # Create a minimal data structure instead of detaching
                return UserAuthData(
                    id=user.id,
                    username=user.username,
                    is_active=user.is_active,
                    roles=[role.name for role in user.roles],
                    player_id=user.player.id if user.player else None,
                    player_name=user.player.name if user.player else None,
                    has_completed_onboarding=user.has_completed_onboarding,
                    has_skipped_profile_creation=user.has_skipped_profile_creation
                )
            return None
    
    @staticmethod
    def get_player_profile(player_id):
        """
        Optimized player profile loading.
        Uses query session for heavy read operation.
        """
        with query_session() as session:
            from app.models import Player, PlayerEvent, Match, Team, User
            from sqlalchemy.orm import selectinload
            
            player = session.query(Player).options(
                selectinload(Player.teams),
                selectinload(Player.user).selectinload(User.roles),
                selectinload(Player.career_stats),
                selectinload(Player.season_stats),
                selectinload(Player.events).selectinload(PlayerEvent.match)
            ).get(player_id)
            
            if player:
                session.expunge(player)
            return player
    
    @staticmethod 
    def get_match_details(match_id):
        """
        Optimized match loading for reporting.
        Uses the current session when available for better efficiency.
        """
        # Use current session if available to avoid creating new connections
        if has_request_context() and hasattr(g, 'db_session'):
            session = g.db_session
            from app.models import Match, Team, Player
            from sqlalchemy.orm import selectinload
            
            match = session.query(Match).options(
                selectinload(Match.home_team).selectinload(Team.players),
                selectinload(Match.away_team).selectinload(Team.players)
            ).get(match_id)
            
            # Don't detach since we're using the request session
            return match
        else:
            # Fallback to isolated session with minimal eager loading
            with query_session() as session:
                from app.models import Match, Team, Player
                from sqlalchemy.orm import selectinload
                
                match = session.query(Match).options(
                    selectinload(Match.home_team).selectinload(Team.players),
                    selectinload(Match.away_team).selectinload(Team.players)
                ).get(match_id)
                
                if match:
                    session.expunge(match)
                return match
    
    @staticmethod
    def get_user_with_full_context(user_id):
        """
        Load user with all commonly accessed relationships for administrative operations.
        """
        with query_session() as session:
            from app.models import User, Role, Permission, Player, Team
            from sqlalchemy.orm import selectinload
            
            user = session.query(User).options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.player).selectinload(Player.teams)
            ).get(user_id)
            
            if user:
                session.expunge(user)
            return user
    
    @staticmethod
    def get_team_with_players(team_id):
        """
        Load team with all players for reporting and display purposes.
        """
        with query_session() as session:
            from app.models import Team, Player, User
            from sqlalchemy.orm import selectinload
            
            team = session.query(Team).options(
                selectinload(Team.players).selectinload(Player.user)
            ).get(team_id)
            
            if team:
                session.expunge(team)
            return team

    @staticmethod
    def safe_get_relationship_attribute(obj, relationship_path, default=None):
        """
        Safely access relationship attributes on potentially detached objects.
        
        Args:
            obj: The SQLAlchemy object
            relationship_path: Dot-separated path like 'home_team.name' or 'player.teams'
            default: Default value to return if access fails
            
        Returns:
            The attribute value or default if DetachedInstanceError occurs
        """
        try:
            current_obj = obj
            for attr in relationship_path.split('.'):
                if current_obj is None:
                    return default
                current_obj = getattr(current_obj, attr)
            return current_obj
        except Exception as e:
            logger.warning(f"DetachedInstanceError accessing {relationship_path}: {e}")
            return default