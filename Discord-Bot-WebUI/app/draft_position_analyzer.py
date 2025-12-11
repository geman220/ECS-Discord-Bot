# app/draft_position_analyzer.py

"""
Position Analysis Utility for Draft System

Analyzes team position needs and calculates player fit scores to help coaches
make informed drafting decisions.
"""

import logging

logger = logging.getLogger(__name__)


class PositionAnalyzer:
    """Analyze team position needs and player fit scores."""

    # Map of position groups to individual position names
    POSITION_GROUPS = {
        'goalkeeper': ['goalkeeper', 'gk', 'keeper', 'goalie'],
        'defender': [
            'defender', 'defence', 'defense', 'cb', 'lb', 'rb',
            'center_back', 'centre_back', 'left_back', 'right_back',
            'full_back', 'fullback', 'wing_back', 'wingback',
            'lwb', 'rwb', 'def'
        ],
        'midfielder': [
            'midfielder', 'midfield', 'mid', 'cm', 'cdm', 'cam',
            'lm', 'rm', 'center_mid', 'centre_mid',
            'defensive_mid', 'attacking_mid', 'center_midfielder'
        ],
        'forward': [
            'forward', 'striker', 'st', 'lw', 'rw', 'winger',
            'cf', 'center_forward', 'centre_forward', 'wing',
            'left_wing', 'right_wing', 'attack', 'attacker'
        ]
    }

    # Ideal team composition (configurable)
    IDEAL_COMPOSITION = {
        'goalkeeper': 2,
        'defender': 4,
        'midfielder': 4,
        'forward': 3
    }

    @staticmethod
    def normalize_position(position):
        """
        Normalize a position string to lowercase and remove special characters.

        Args:
            position (str): Raw position string

        Returns:
            str: Normalized position string
        """
        if not position:
            return ''
        return position.lower().strip().replace(' ', '_').replace('-', '_')

    @classmethod
    def get_position_group(cls, position):
        """
        Get the position group for a given position.

        Args:
            position (str): Position name

        Returns:
            str: Position group name ('goalkeeper', 'defender', 'midfielder', 'forward') or None
        """
        normalized = cls.normalize_position(position)
        if not normalized:
            return None

        for group, positions in cls.POSITION_GROUPS.items():
            if normalized in positions:
                return group
        return None

    @classmethod
    def parse_position_preferences(cls, player):
        """
        Extract position preferences from Player model fields.

        Args:
            player: Player model instance

        Returns:
            dict: Dictionary with 'favorite', 'other', and 'not_play' lists
        """
        favorite = cls.normalize_position(player.favorite_position or '')

        # Parse comma-separated other positions
        other_raw = (player.other_positions or '').split(',')
        other = [cls.normalize_position(p) for p in other_raw if p.strip()]

        # Parse comma-separated positions not to play
        not_play_raw = (player.positions_not_to_play or '').split(',')
        not_play = [cls.normalize_position(p) for p in not_play_raw if p.strip()]

        return {
            'favorite': favorite,
            'other': other,
            'not_play': not_play,
        }

    @classmethod
    def calculate_team_needs(cls, team_players):
        """
        Calculate position openings based on current roster.

        Args:
            team_players (list): List of Player objects currently on team

        Returns:
            dict: Dictionary with 'current', 'ideal', and 'openings' counts per position group
        """
        counts = {
            'goalkeeper': 0,
            'defender': 0,
            'midfielder': 0,
            'forward': 0
        }

        # Count current players by position group
        for player in team_players:
            pos = cls.normalize_position(player.favorite_position or '')
            group = cls.get_position_group(pos)
            if group:
                counts[group] += 1

        # Calculate openings
        openings = {}
        for group, ideal_count in cls.IDEAL_COMPOSITION.items():
            openings[group] = max(0, ideal_count - counts[group])

        return {
            'current': counts,
            'ideal': cls.IDEAL_COMPOSITION,
            'openings': openings
        }

    @classmethod
    def calculate_fit_score(cls, player, team_needs):
        """
        Calculate how well player fits team's needs (0-100).

        Scoring:
        - 100: Favorite position has openings
        - 30: Other positions have openings
        - 0: No matching positions with openings

        Args:
            player: Player model instance
            team_needs (dict): Team needs dict from calculate_team_needs()

        Returns:
            int: Fit score (0-100)
        """
        prefs = cls.parse_position_preferences(player)
        score = 0

        # Check favorite position
        fav_group = cls.get_position_group(prefs['favorite'])
        if fav_group and team_needs['openings'].get(fav_group, 0) > 0:
            score = 100  # Strong fit
            return score  # Return early for best fit

        # Check other positions
        for other_pos in prefs['other']:
            other_group = cls.get_position_group(other_pos)
            if other_group and team_needs['openings'].get(other_group, 0) > 0:
                score = max(score, 30)  # Moderate fit

        return score

    @classmethod
    def get_fit_category(cls, score):
        """
        Get category label for fit score.

        Args:
            score (int): Fit score (0-100)

        Returns:
            str: Category ('strong', 'moderate', 'none')
        """
        if score >= 100:
            return 'strong'
        elif score >= 30:
            return 'moderate'
        else:
            return 'none'

    @classmethod
    def analyze_player_for_teams(cls, player, teams):
        """
        Analyze player fit for multiple teams.

        Args:
            player: Player model instance
            teams (list): List of Team model instances with players loaded

        Returns:
            dict: Dictionary mapping team_id to fit score
        """
        fit_scores = {}

        for team in teams:
            # Get only current players
            team_players = [p for p in team.players if p.is_current_player]
            team_needs = cls.calculate_team_needs(team_players)
            fit_score = cls.calculate_fit_score(player, team_needs)
            fit_scores[team.id] = {
                'score': fit_score,
                'category': cls.get_fit_category(fit_score),
                'needs': team_needs
            }

        return fit_scores
