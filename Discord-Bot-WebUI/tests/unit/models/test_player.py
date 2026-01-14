"""
Player model unit tests.

These tests verify the Player model's core behaviors:
- Team relationships (many-to-many)
- Discord ID uniqueness
- Coach/referee flags
- Profile data management
"""
import pytest
from datetime import datetime
from sqlalchemy.exc import IntegrityError

from tests.factories import PlayerFactory, UserFactory, TeamFactory, LeagueFactory, SeasonFactory


@pytest.mark.unit
class TestPlayerTeamRelationship:
    """Test Player-Team relationship behaviors."""

    def test_player_can_belong_to_team(self, db, team):
        """
        GIVEN a Player and a Team
        WHEN the player is added to the team
        THEN the relationship should be established
        """
        user = UserFactory(username='team_player')
        player = PlayerFactory(name='Team Player', user=user)
        player.teams.append(team)
        db.session.commit()

        assert team in player.teams
        assert player in team.players

    def test_player_can_belong_to_multiple_teams(self, db, league):
        """
        GIVEN a Player
        WHEN assigned to multiple teams
        THEN all team relationships should be established
        """
        user = UserFactory(username='multi_team')
        player = PlayerFactory(name='Multi Team', user=user)

        team1 = TeamFactory(name='Team Alpha', league=league)
        team2 = TeamFactory(name='Team Beta', league=league)

        player.teams.append(team1)
        player.teams.append(team2)
        db.session.commit()

        assert len(player.teams) == 2
        assert team1 in player.teams
        assert team2 in player.teams

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

        player.teams.remove(team)
        db.session.commit()

        assert team not in player.teams


@pytest.mark.unit
class TestPlayerDiscordId:
    """Test Player Discord ID behaviors."""

    def test_player_can_have_discord_id(self, db):
        """
        GIVEN a Player
        WHEN discord_id is set
        THEN it should be stored
        """
        user = UserFactory(username='discord_player')
        player = PlayerFactory(
            name='Discord Player',
            user=user,
            discord_id='123456789012345678'
        )
        db.session.commit()

        assert player.discord_id == '123456789012345678'

    def test_discord_id_must_be_unique(self, db):
        """
        GIVEN an existing Player with a discord_id
        WHEN another player tries to use the same discord_id
        THEN an integrity error should be raised
        """
        user1 = UserFactory(username='discord_1')
        user2 = UserFactory(username='discord_2')

        player1 = PlayerFactory(
            name='First Discord',
            user=user1,
            discord_id='same_discord_id_123'
        )
        db.session.commit()

        # Try to create another player with same discord_id
        player2 = PlayerFactory.build(
            name='Second Discord',
            user=user2,
            discord_id='same_discord_id_123'
        )
        db.session.add(player2)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


@pytest.mark.unit
class TestPlayerRoleFlags:
    """Test Player role flag behaviors."""

    def test_player_can_be_coach(self, db):
        """
        GIVEN a Player
        WHEN is_coach is set to True
        THEN the player should be marked as a coach
        """
        user = UserFactory(username='coach_player')
        player = PlayerFactory(
            name='Coach Player',
            user=user,
            is_coach=True
        )
        db.session.commit()

        assert player.is_coach is True

    def test_player_can_be_referee(self, db):
        """
        GIVEN a Player
        WHEN is_ref is set to True
        THEN the player should be marked as a referee
        """
        user = UserFactory(username='ref_player')
        player = PlayerFactory(
            name='Referee Player',
            user=user,
            is_ref=True
        )
        db.session.commit()

        assert player.is_ref is True

    def test_player_can_be_substitute(self, db):
        """
        GIVEN a Player
        WHEN is_sub is set to True
        THEN the player should be marked as a substitute
        """
        user = UserFactory(username='sub_player')
        player = PlayerFactory(
            name='Sub Player',
            user=user,
            is_sub=True
        )
        db.session.commit()

        assert player.is_sub is True


@pytest.mark.unit
class TestPlayerUserRelationship:
    """Test Player-User relationship behaviors."""

    def test_player_must_have_user(self, db):
        """
        GIVEN a Player
        WHEN created without a user
        THEN an error should occur
        """
        from app.models import Player

        player = Player(name='No User Player')
        db.session.add(player)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()

    def test_player_user_relationship(self, db):
        """
        GIVEN a Player with a User
        WHEN accessing the relationship
        THEN the player should be linked to the user
        """
        user = UserFactory(username='player_user_rel')
        player = PlayerFactory(name='User Player Rel', user=user)
        db.session.commit()

        # Verify player -> user relationship
        assert player.user == user
        assert player.user_id == user.id


@pytest.mark.unit
class TestPlayerJerseyInfo:
    """Test Player jersey information behaviors."""

    def test_player_jersey_number(self, db):
        """
        GIVEN a Player
        WHEN jersey_number is set
        THEN it should be stored
        """
        user = UserFactory(username='jersey_player')
        player = PlayerFactory(
            name='Jersey Player',
            user=user,
            jersey_number=10
        )
        db.session.commit()

        assert player.jersey_number == 10

    def test_player_jersey_size(self, db):
        """
        GIVEN a Player
        WHEN jersey_size is set
        THEN it should be stored
        """
        user = UserFactory(username='size_player')
        player = PlayerFactory(
            name='Size Player',
            user=user,
            jersey_size='L'
        )
        db.session.commit()

        assert player.jersey_size == 'L'


@pytest.mark.unit
class TestPlayerPrimaryTeam:
    """Test Player primary team behaviors."""

    def test_player_can_have_primary_team(self, db, team):
        """
        GIVEN a Player with a primary team
        WHEN primary_team_id is set
        THEN the relationship should be established
        """
        user = UserFactory(username='primary_team')
        player = PlayerFactory(
            name='Primary Team Player',
            user=user,
            primary_team_id=team.id
        )
        db.session.commit()

        assert player.primary_team == team

    def test_player_primary_team_can_be_none(self, db):
        """
        GIVEN a Player without a primary team
        WHEN primary_team_id is None
        THEN primary_team should be None
        """
        user = UserFactory(username='no_primary')
        player = PlayerFactory(
            name='No Primary Player',
            user=user,
            primary_team_id=None
        )
        db.session.commit()

        assert player.primary_team is None
