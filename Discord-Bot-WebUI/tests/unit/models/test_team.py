"""
Team model unit tests.

These tests verify the Team model's core behaviors:
- Team-League relationship
- Team-Player many-to-many relationship
- Team statistics properties (recent_form, top_scorer, etc.)
- Team serialization (to_dict)
- Discord integration fields
- Team active status
"""
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.exc import IntegrityError

from tests.factories import (
    TeamFactory, LeagueFactory, SeasonFactory, PlayerFactory, UserFactory, MatchFactory
)


@pytest.mark.unit
class TestTeamLeagueRelationship:
    """Test Team-League relationship behaviors."""

    def test_team_belongs_to_league(self, db, league):
        """
        GIVEN a Team and a League
        WHEN the team is created with a league_id
        THEN the team should be associated with the league
        """
        team = TeamFactory(name='Alpha FC', league=league)
        db.session.commit()

        assert team.league_id == league.id
        assert team.league == league
        assert team in league.teams

    def test_team_requires_league(self, db):
        """
        GIVEN a Team without a league
        WHEN attempting to create the team
        THEN an integrity error should be raised
        """
        from app.models import Team

        team = Team(name='No League Team')
        db.session.add(team)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()

    def test_multiple_teams_in_same_league(self, db, league):
        """
        GIVEN a League
        WHEN multiple teams are created in that league
        THEN all teams should be associated with the league
        """
        team1 = TeamFactory(name='Team Alpha', league=league)
        team2 = TeamFactory(name='Team Beta', league=league)
        team3 = TeamFactory(name='Team Gamma', league=league)
        db.session.commit()

        assert len(league.teams) == 3
        assert team1 in league.teams
        assert team2 in league.teams
        assert team3 in league.teams


@pytest.mark.unit
class TestTeamPlayerRelationship:
    """Test Team-Player many-to-many relationship behaviors."""

    def test_team_can_have_players(self, db, team):
        """
        GIVEN a Team
        WHEN players are added to the team
        THEN the relationship should be established
        """
        user1 = UserFactory(username='player1')
        user2 = UserFactory(username='player2')
        player1 = PlayerFactory(name='Player One', user=user1)
        player2 = PlayerFactory(name='Player Two', user=user2)

        player1.teams.append(team)
        player2.teams.append(team)
        db.session.commit()

        assert len(team.players) == 2
        assert player1 in team.players
        assert player2 in team.players

    def test_player_can_be_on_multiple_teams(self, db, league):
        """
        GIVEN a Player
        WHEN the player is added to multiple teams
        THEN the player should be associated with all teams
        """
        team1 = TeamFactory(name='Team Alpha', league=league)
        team2 = TeamFactory(name='Team Beta', league=league)

        user = UserFactory(username='multi_team_player')
        player = PlayerFactory(name='Multi Team Player', user=user)

        player.teams.append(team1)
        player.teams.append(team2)
        db.session.commit()

        assert len(player.teams) == 2
        assert team1 in player.teams
        assert team2 in player.teams
        assert player in team1.players
        assert player in team2.players

    def test_removing_player_from_team(self, db, team):
        """
        GIVEN a Player on a Team
        WHEN the player is removed from the team
        THEN the relationship should be removed
        """
        user = UserFactory(username='removed_player')
        player = PlayerFactory(name='Removed Player', user=user)
        player.teams.append(team)
        db.session.commit()

        assert player in team.players

        player.teams.remove(team)
        db.session.commit()

        assert player not in team.players
        assert team not in player.teams

    def test_team_with_no_players(self, db, league):
        """
        GIVEN a newly created Team
        WHEN no players have been added
        THEN the players list should be empty
        """
        team = TeamFactory(name='Empty Team', league=league)
        db.session.commit()

        assert team.players == []
        assert len(team.players) == 0


@pytest.mark.unit
class TestTeamDiscordFields:
    """Test Team Discord integration field behaviors."""

    def test_team_discord_channel_id(self, db, league):
        """
        GIVEN a Team
        WHEN discord_channel_id is set
        THEN it should be stored correctly
        """
        team = TeamFactory(name='Discord Team', league=league)
        team.discord_channel_id = '123456789012345678'
        db.session.commit()

        assert team.discord_channel_id == '123456789012345678'

    def test_team_discord_role_ids(self, db, league):
        """
        GIVEN a Team
        WHEN discord role IDs are set
        THEN they should be stored correctly
        """
        team = TeamFactory(name='Role Team', league=league)
        team.discord_coach_role_id = '111111111111111111'
        team.discord_player_role_id = '222222222222222222'
        db.session.commit()

        assert team.discord_coach_role_id == '111111111111111111'
        assert team.discord_player_role_id == '222222222222222222'

    def test_team_discord_fields_optional(self, db, league):
        """
        GIVEN a Team
        WHEN discord fields are not set
        THEN they should be None
        """
        team = TeamFactory(name='No Discord Team', league=league)
        db.session.commit()

        assert team.discord_channel_id is None
        assert team.discord_coach_role_id is None
        assert team.discord_player_role_id is None


@pytest.mark.unit
class TestTeamActiveStatus:
    """Test Team active status behaviors."""

    def test_team_is_active_by_default(self, db, league):
        """
        GIVEN a newly created Team
        WHEN no active status is specified
        THEN the team should be active by default
        """
        team = TeamFactory(name='Default Active Team', league=league)
        db.session.commit()

        assert team.is_active is True

    def test_team_can_be_deactivated(self, db, league):
        """
        GIVEN an active Team
        WHEN is_active is set to False
        THEN the team should be marked as inactive
        """
        team = TeamFactory(name='Inactive Team', league=league)
        team.is_active = False
        db.session.commit()

        assert team.is_active is False


@pytest.mark.unit
class TestTeamSerialization:
    """Test Team to_dict serialization behaviors."""

    @patch('app.team_performance_helpers.get_team_stats_cached')
    def test_team_to_dict_basic(self, mock_stats, db, league):
        """
        GIVEN a Team
        WHEN to_dict is called without include_players
        THEN it should return basic team data
        """
        mock_stats.return_value = {
            'top_scorer': 'N/A',
            'top_assist': 'N/A',
            'avg_goals_per_match': 0.0
        }

        team = TeamFactory(name='Serialized Team', league=league)
        team.discord_channel_id = '123456789'
        team.discord_coach_role_id = '111111111'
        team.discord_player_role_id = '222222222'
        db.session.commit()

        data = team.to_dict()

        assert data['id'] == team.id
        assert data['name'] == 'Serialized Team'
        assert data['league_id'] == league.id
        assert data['discord_channel_id'] == '123456789'
        assert data['discord_coach_role_id'] == '111111111'
        assert data['discord_player_role_id'] == '222222222'
        assert 'players' not in data

    @patch('app.team_performance_helpers.get_team_stats_cached')
    def test_team_to_dict_with_players(self, mock_stats, db, league, app):
        """
        GIVEN a Team with Players
        WHEN to_dict is called with include_players=True
        THEN it should include player data
        """
        mock_stats.return_value = {
            'top_scorer': 'N/A',
            'top_assist': 'N/A',
            'avg_goals_per_match': 0.0
        }

        team = TeamFactory(name='Team With Players', league=league)
        user = UserFactory(username='dict_player')
        player = PlayerFactory(name='Dict Player', user=user)
        player.teams.append(team)
        db.session.commit()

        with app.test_request_context():
            data = team.to_dict(include_players=True)

        assert 'players' in data
        assert len(data['players']) == 1
        assert data['players'][0]['name'] == 'Dict Player'


@pytest.mark.unit
class TestTeamStatisticsProperties:
    """Test Team statistics property behaviors."""

    def test_team_recent_form_no_matches(self, db, league):
        """
        GIVEN a Team with no matches
        WHEN recent_form is accessed
        THEN it should return an empty string
        """
        team = TeamFactory(name='No Matches Team', league=league)
        db.session.commit()

        assert team.recent_form == ''

    def test_team_recent_form_with_wins(self, db, league, season):
        """
        GIVEN a Team with winning matches
        WHEN recent_form is accessed
        THEN it should show wins (W)
        """
        team = TeamFactory(name='Winning Team', league=league)
        opponent = TeamFactory(name='Losing Team', league=league)
        db.session.commit()

        # Create a match where team won (home team with higher score)
        match = MatchFactory(
            home_team=team,
            away_team=opponent,
            season=season
        )
        match.home_team_score = 3
        match.away_team_score = 1
        db.session.commit()

        form = team.recent_form
        assert 'text-success' in form
        assert 'W' in form

    def test_team_recent_form_with_losses(self, db, league, season):
        """
        GIVEN a Team with losing matches
        WHEN recent_form is accessed
        THEN it should show losses (L)
        """
        team = TeamFactory(name='Losing Team', league=league)
        opponent = TeamFactory(name='Winning Team', league=league)
        db.session.commit()

        # Create a match where team lost (home team with lower score)
        match = MatchFactory(
            home_team=team,
            away_team=opponent,
            season=season
        )
        match.home_team_score = 0
        match.away_team_score = 2
        db.session.commit()

        form = team.recent_form
        assert 'text-danger' in form
        assert 'L' in form

    def test_team_recent_form_with_draw(self, db, league, season):
        """
        GIVEN a Team with a drawn match
        WHEN recent_form is accessed
        THEN it should show draw (D)
        """
        team = TeamFactory(name='Drawing Team', league=league)
        opponent = TeamFactory(name='Other Team', league=league)
        db.session.commit()

        # Create a match with a draw
        match = MatchFactory(
            home_team=team,
            away_team=opponent,
            season=season
        )
        match.home_team_score = 1
        match.away_team_score = 1
        db.session.commit()

        form = team.recent_form
        assert 'text-warning' in form
        assert 'D' in form

    @patch('app.team_performance_helpers.get_team_stats_cached')
    def test_team_top_scorer(self, mock_stats, db, league):
        """
        GIVEN a Team with player statistics
        WHEN top_scorer is accessed
        THEN it should return the top scorer name
        """
        mock_stats.return_value = {
            'top_scorer': 'John Doe (5 goals)',
            'top_assist': 'Jane Smith',
            'avg_goals_per_match': 2.5
        }

        team = TeamFactory(name='Stats Team', league=league)
        db.session.commit()

        assert team.top_scorer == 'John Doe (5 goals)'

    @patch('app.team_performance_helpers.get_team_stats_cached')
    def test_team_top_assist(self, mock_stats, db, league):
        """
        GIVEN a Team with player statistics
        WHEN top_assist is accessed
        THEN it should return the top assist provider name
        """
        mock_stats.return_value = {
            'top_scorer': 'John Doe',
            'top_assist': 'Jane Smith (8 assists)',
            'avg_goals_per_match': 2.5
        }

        team = TeamFactory(name='Assist Team', league=league)
        db.session.commit()

        assert team.top_assist == 'Jane Smith (8 assists)'

    @patch('app.team_performance_helpers.get_team_stats_cached')
    def test_team_avg_goals_per_match(self, mock_stats, db, league):
        """
        GIVEN a Team with match statistics
        WHEN avg_goals_per_match is accessed
        THEN it should return the average goals
        """
        mock_stats.return_value = {
            'top_scorer': 'John Doe',
            'top_assist': 'Jane Smith',
            'avg_goals_per_match': 2.75
        }

        team = TeamFactory(name='Goals Team', league=league)
        db.session.commit()

        assert team.avg_goals_per_match == 2.75

    @patch('app.team_performance_helpers.get_team_stats_cached')
    def test_team_popover_content(self, mock_stats, db, league):
        """
        GIVEN a Team with statistics
        WHEN popover_content is accessed
        THEN it should return formatted HTML content
        """
        mock_stats.return_value = {
            'top_scorer': 'John Doe',
            'top_assist': 'Jane Smith',
            'avg_goals_per_match': 2.0
        }

        team = TeamFactory(name='Popover Team', league=league)
        db.session.commit()

        content = team.popover_content

        assert '<strong>Recent Form:</strong>' in content
        assert '<strong>Top Scorer:</strong>' in content
        assert '<strong>Top Assist:</strong>' in content
        assert '<strong>Avg Goals/Match:</strong>' in content


@pytest.mark.unit
class TestTeamImageFields:
    """Test Team image and appearance field behaviors."""

    def test_team_kit_url(self, db, league):
        """
        GIVEN a Team
        WHEN kit_url is set
        THEN it should be stored correctly
        """
        team = TeamFactory(name='Kit Team', league=league)
        team.kit_url = 'https://example.com/kit.png'
        db.session.commit()

        assert team.kit_url == 'https://example.com/kit.png'

    def test_team_background_image_url(self, db, league):
        """
        GIVEN a Team
        WHEN background_image_url is set
        THEN it should be stored correctly
        """
        team = TeamFactory(name='Background Team', league=league)
        team.background_image_url = 'https://example.com/bg.jpg'
        db.session.commit()

        assert team.background_image_url == 'https://example.com/bg.jpg'

    def test_team_background_position_default(self, db, league):
        """
        GIVEN a Team
        WHEN background_position is not set
        THEN it should default to 'center'
        """
        from app.models import Team

        team = Team(name='Default Position Team', league_id=league.id)
        db.session.add(team)
        db.session.commit()

        assert team.background_position == 'center'

    def test_team_background_size_default(self, db, league):
        """
        GIVEN a Team
        WHEN background_size is not set
        THEN it should default to 'cover'
        """
        from app.models import Team

        team = Team(name='Default Size Team', league_id=league.id)
        db.session.add(team)
        db.session.commit()

        assert team.background_size == 'cover'
