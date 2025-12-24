"""
Profile Visibility Service
===========================

Determines what profile information a viewer can see based on:
- The profile owner's visibility setting (private, teammates, everyone)
- The viewer's relationship to the profile owner
- The viewer's role (admin, coach)

Visibility Levels:
- private: Only photo and name visible to others
- teammates: Profile visible to current season teammates
- everyone: Profile visible to all logged-in users

Always Visible (regardless of setting):
- Profile photo
- Player name

Always Hidden (requires specific permission):
- Email (requires view_player_contact_info permission)
- Phone (requires view_player_contact_info permission)
- Stats (existing permission system - globally hidden for non-admins)
- Admin notes (requires view_player_admin_notes permission)

Conditionally Visible (based on profile_visibility):
- Preferred position
- Other positions
- Positions not to play
- Team history
- Current team
- Jersey size
- League info
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ProfileVisibilityService:
    """
    Service for determining profile visibility based on user settings and relationships.
    """

    # Information categories
    ALWAYS_VISIBLE = {'photo', 'name'}
    REQUIRES_PERMISSION = {'email', 'phone', 'stats', 'admin_notes'}
    VISIBILITY_CONTROLLED = {
        'position', 'other_positions', 'positions_not_to_play',
        'team_history', 'current_team', 'jersey_size', 'league_info',
        'discord_id', 'team_swap', 'availability', 'willing_to_referee'
    }

    @staticmethod
    def can_view_profile_details(
        viewer_user,
        profile_owner_user,
        profile_owner_player,
        viewer_roles: list,
        viewer_teams_current_season: list = None,
        owner_teams_current_season: list = None
    ) -> Dict[str, bool]:
        """
        Determine what profile information the viewer can see.

        Args:
            viewer_user: The User object of the person viewing the profile
            profile_owner_user: The User object of the profile being viewed
            profile_owner_player: The Player object of the profile being viewed
            viewer_roles: List of role names for the viewer
            viewer_teams_current_season: List of team IDs the viewer is on this season
            owner_teams_current_season: List of team IDs the profile owner is on this season

        Returns:
            Dict with visibility flags for each category
        """
        # Default to showing nothing beyond basics
        visibility = {
            'can_view_photo': True,  # Always visible
            'can_view_name': True,   # Always visible
            'can_view_position': False,
            'can_view_team_history': False,
            'can_view_current_team': False,
            'can_view_jersey_size': False,
            'can_view_league_info': False,
            'can_view_availability': False,
            'can_view_detailed_profile': False,  # Combined flag for form/edit view
            'is_restricted': False,  # Flag to show "Profile is private" message
            'visibility_level': 'private',  # For debugging/display
        }

        if not viewer_user or not profile_owner_user:
            visibility['is_restricted'] = True
            return visibility

        # Get profile visibility setting (default to 'everyone' for backwards compatibility)
        profile_visibility = getattr(profile_owner_user, 'profile_visibility', 'everyone') or 'everyone'
        visibility['visibility_level'] = profile_visibility

        # Check if viewer is the profile owner
        is_own_profile = viewer_user.id == profile_owner_user.id

        # Check if viewer is admin or coach
        is_admin = any(role in ['Global Admin', 'Pub League Admin'] for role in viewer_roles)
        is_coach = 'Pub League Coach' in viewer_roles

        # Admin/Coach override - they always see everything
        if is_admin or is_coach:
            visibility.update({
                'can_view_position': True,
                'can_view_team_history': True,
                'can_view_current_team': True,
                'can_view_jersey_size': True,
                'can_view_league_info': True,
                'can_view_availability': True,
                'can_view_detailed_profile': True,
                'is_restricted': False,
            })
            logger.debug(f"Admin/Coach viewing profile {profile_owner_user.id} - full access granted")
            return visibility

        # Own profile - always full access
        if is_own_profile:
            visibility.update({
                'can_view_position': True,
                'can_view_team_history': True,
                'can_view_current_team': True,
                'can_view_jersey_size': True,
                'can_view_league_info': True,
                'can_view_availability': True,
                'can_view_detailed_profile': True,
                'is_restricted': False,
            })
            logger.debug(f"User viewing own profile {profile_owner_user.id} - full access granted")
            return visibility

        # Apply visibility settings
        if profile_visibility == 'everyone':
            # Everyone can see profile details
            visibility.update({
                'can_view_position': True,
                'can_view_team_history': True,
                'can_view_current_team': True,
                'can_view_jersey_size': True,
                'can_view_league_info': True,
                'can_view_availability': True,
                'can_view_detailed_profile': True,
                'is_restricted': False,
            })
            logger.debug(f"Profile {profile_owner_user.id} visibility=everyone - full access")

        elif profile_visibility == 'teammates':
            # Check if viewer is a teammate in current season
            is_teammate = False
            if viewer_teams_current_season and owner_teams_current_season:
                # Check for any overlapping teams
                viewer_team_ids = set(viewer_teams_current_season)
                owner_team_ids = set(owner_teams_current_season)
                is_teammate = bool(viewer_team_ids & owner_team_ids)

            if is_teammate:
                visibility.update({
                    'can_view_position': True,
                    'can_view_team_history': True,
                    'can_view_current_team': True,
                    'can_view_jersey_size': True,
                    'can_view_league_info': True,
                    'can_view_availability': True,
                    'can_view_detailed_profile': True,
                    'is_restricted': False,
                })
                logger.debug(f"Profile {profile_owner_user.id} visibility=teammates - viewer is teammate - full access")
            else:
                visibility['is_restricted'] = True
                logger.debug(f"Profile {profile_owner_user.id} visibility=teammates - viewer NOT teammate - restricted")

        elif profile_visibility == 'private':
            # Only photo and name visible
            visibility['is_restricted'] = True
            logger.debug(f"Profile {profile_owner_user.id} visibility=private - restricted to basics")

        return visibility

    @staticmethod
    def get_viewer_current_season_teams(viewer_player, current_season, session) -> list:
        """
        Get the team IDs the viewer is on for the current season.

        Args:
            viewer_player: The Player object for the viewer
            current_season: The current Season object
            session: Database session

        Returns:
            List of team IDs
        """
        if not viewer_player or not current_season:
            return []

        from app.models import PlayerTeamSeason

        team_ids = session.query(PlayerTeamSeason.team_id).filter(
            PlayerTeamSeason.player_id == viewer_player.id,
            PlayerTeamSeason.season_id == current_season.id
        ).all()

        return [t[0] for t in team_ids]

    @staticmethod
    def get_owner_current_season_teams(owner_player, current_season, session) -> list:
        """
        Get the team IDs the profile owner is on for the current season.

        Args:
            owner_player: The Player object for the profile owner
            current_season: The current Season object
            session: Database session

        Returns:
            List of team IDs
        """
        if not owner_player or not current_season:
            return []

        from app.models import PlayerTeamSeason

        team_ids = session.query(PlayerTeamSeason.team_id).filter(
            PlayerTeamSeason.player_id == owner_player.id,
            PlayerTeamSeason.season_id == current_season.id
        ).all()

        return [t[0] for t in team_ids]


# Convenience function for quick access
def get_profile_visibility(
    viewer_user,
    profile_owner_user,
    profile_owner_player,
    viewer_roles: list,
    current_season=None,
    session=None
) -> Dict[str, bool]:
    """
    Convenience function to get profile visibility flags.

    This is the main entry point for checking profile visibility.
    """
    service = ProfileVisibilityService()

    # Get current season team info if we have session
    viewer_teams = []
    owner_teams = []

    if session and current_season:
        # Get viewer's player object
        from app.models import Player
        viewer_player = session.query(Player).filter_by(user_id=viewer_user.id).first() if viewer_user else None

        if viewer_player:
            viewer_teams = service.get_viewer_current_season_teams(viewer_player, current_season, session)
        if profile_owner_player:
            owner_teams = service.get_owner_current_season_teams(profile_owner_player, current_season, session)

    return service.can_view_profile_details(
        viewer_user=viewer_user,
        profile_owner_user=profile_owner_user,
        profile_owner_player=profile_owner_player,
        viewer_roles=viewer_roles,
        viewer_teams_current_season=viewer_teams,
        owner_teams_current_season=owner_teams
    )
