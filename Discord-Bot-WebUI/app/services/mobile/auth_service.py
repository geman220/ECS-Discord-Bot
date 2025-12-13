# app/services/mobile/auth_service.py

"""
Mobile Authentication Service

Handles authentication operations for mobile clients including:
- Email/password login
- Discord OAuth
- 2FA verification
- Token management
"""

import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

from sqlalchemy.orm import Session
from flask_jwt_extended import create_access_token

from app.services.base_service import BaseService, ServiceResult, ValidationError, NotFoundError
from app.models import User, Player

logger = logging.getLogger(__name__)


@dataclass
class AuthResult:
    """Result of an authentication operation."""
    success: bool
    access_token: Optional[str] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    requires_2fa: bool = False
    message: str = ""


class MobileAuthService(BaseService):
    """
    Service for mobile authentication operations.

    Handles all authentication-related business logic for mobile clients,
    separating it from route handlers.
    """

    def __init__(self, session: Session):
        super().__init__(session)

    def authenticate_with_password(
        self,
        email: str,
        password: str
    ) -> AuthResult:
        """
        Authenticate user with email and password.

        Args:
            email: User's email address
            password: User's password

        Returns:
            AuthResult with token if successful
        """
        self._log_operation_start("password_auth", email=email)

        if not email or not password:
            return AuthResult(
                success=False,
                message="Missing email or password"
            )

        user = self.session.query(User).filter_by(email=email.lower()).first()

        if not user or not user.check_password(password):
            self._log_operation_error("password_auth", Exception("Invalid credentials"))
            return AuthResult(
                success=False,
                message="Invalid email or password"
            )

        if not user.is_approved:
            return AuthResult(
                success=False,
                message="Account not approved"
            )

        # Check if 2FA is required
        if user.is_2fa_enabled:
            return AuthResult(
                success=True,
                user_id=user.id,
                requires_2fa=True,
                message="2FA verification required"
            )

        # Generate access token
        access_token = create_access_token(identity=str(user.id))

        self._log_operation_success("password_auth", user_id=user.id)

        return AuthResult(
            success=True,
            access_token=access_token,
            user_id=user.id,
            username=user.username,
            message="Authentication successful"
        )

    def verify_2fa_token(
        self,
        user_id: int,
        token: str
    ) -> AuthResult:
        """
        Verify 2FA token and return access token if valid.

        Args:
            user_id: The user's ID
            token: The 2FA token from authenticator app

        Returns:
            AuthResult with access token if valid
        """
        self._log_operation_start("2fa_verification", user_id=user_id)

        if not user_id or not token:
            return AuthResult(
                success=False,
                message="Missing user_id or token"
            )

        user = self.session.query(User).get(user_id)

        if not user:
            return AuthResult(
                success=False,
                message="User not found"
            )

        if not user.verify_totp(token):
            self._log_operation_error("2fa_verification", Exception("Invalid token"))
            return AuthResult(
                success=False,
                message="Invalid 2FA token"
            )

        access_token = create_access_token(identity=str(user.id))

        self._log_operation_success("2fa_verification", user_id=user.id)

        return AuthResult(
            success=True,
            access_token=access_token,
            user_id=user.id,
            username=user.username,
            message="2FA verification successful"
        )

    def process_discord_auth(
        self,
        discord_user_data: Dict[str, Any]
    ) -> AuthResult:
        """
        Process Discord OAuth authentication.

        Args:
            discord_user_data: User data from Discord API

        Returns:
            AuthResult with access token if successful
        """
        self._log_operation_start("discord_auth", discord_id=discord_user_data.get('id'))

        discord_id = discord_user_data.get('id')
        if not discord_id:
            return AuthResult(
                success=False,
                message="Invalid Discord user data"
            )

        # Find existing user by Discord ID
        player = self.session.query(Player).filter_by(discord_id=str(discord_id)).first()

        if player and player.user_id:
            user = self.session.query(User).get(player.user_id)
            if user:
                access_token = create_access_token(identity=str(user.id))
                self._log_operation_success("discord_auth", user_id=user.id)
                return AuthResult(
                    success=True,
                    access_token=access_token,
                    user_id=user.id,
                    username=user.username,
                    message="Discord authentication successful"
                )

        # User not found - they need to register
        return AuthResult(
            success=False,
            message="No account linked to this Discord ID. Please register first."
        )

    def get_user_profile_data(
        self,
        user_id: int,
        include_stats: bool = False
    ) -> ServiceResult[Dict[str, Any]]:
        """
        Get user profile data for mobile client.

        Args:
            user_id: The user's ID
            include_stats: Whether to include player statistics

        Returns:
            ServiceResult with profile data
        """
        self._log_operation_start("get_profile", user_id=user_id)

        user = self.session.query(User).get(user_id)
        if not user:
            return ServiceResult.fail("User not found", "USER_NOT_FOUND")

        player = self.session.query(Player).filter_by(user_id=user_id).first()

        profile_data = {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "is_approved": user.is_approved,
            "has_player_profile": player is not None
        }

        if player:
            profile_data["player"] = {
                "id": player.id,
                "name": player.name,
                "jersey_number": player.jersey_number,
                "favorite_position": player.favorite_position,
                "discord_id": player.discord_id,
                "primary_team_id": player.primary_team_id
            }

            if include_stats:
                # Add stats if requested
                profile_data["stats"] = self._get_player_stats(player)

        self._log_operation_success("get_profile", user_id=user_id)

        return ServiceResult.ok(profile_data)

    def _get_player_stats(self, player: Player) -> Dict[str, Any]:
        """Get statistics for a player."""
        from app.models import Season, PlayerSeasonStats

        current_season = self.session.query(Season).filter_by(is_current=True).first()

        if not current_season:
            return {}

        stats = self.session.query(PlayerSeasonStats).filter_by(
            player_id=player.id,
            season_id=current_season.id
        ).first()

        if stats:
            return {
                "goals": stats.goals,
                "assists": stats.assists,
                "games_played": stats.games_played,
                "yellow_cards": stats.yellow_cards,
                "red_cards": stats.red_cards
            }

        return {}
