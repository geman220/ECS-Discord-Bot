"""
Availability model unit tests.

These tests verify the Availability model's core behaviors:
- RSVP response storage
- Match-Player relationships
- Response validation
- Timestamp tracking
"""
import pytest
from datetime import datetime

from app.models import Availability
from tests.factories import PlayerFactory, UserFactory, MatchFactory, AvailabilityFactory


@pytest.mark.unit
class TestAvailabilityCreation:
    """Test Availability creation behaviors."""

    def test_availability_can_be_created(self, db, player, match):
        """
        GIVEN a Player and a Match
        WHEN an Availability is created
        THEN it should be stored in the database
        """
        avail = Availability(
            match_id=match.id,
            player_id=player.id,
            discord_id=player.discord_id,
            response='yes'
        )
        db.session.add(avail)
        db.session.commit()

        assert avail.id is not None
        assert avail.response == 'yes'

    def test_availability_requires_match(self, db, player):
        """
        GIVEN an Availability without a match
        WHEN trying to create it
        THEN an error should occur
        """
        from sqlalchemy.exc import IntegrityError

        avail = Availability(
            player_id=player.id,
            discord_id=player.discord_id,
            response='yes'
        )
        db.session.add(avail)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()

    def test_availability_requires_discord_id(self, db, player, match):
        """
        GIVEN an Availability without a discord_id
        WHEN trying to create it
        THEN an error should occur
        """
        from sqlalchemy.exc import IntegrityError

        avail = Availability(
            match_id=match.id,
            player_id=player.id,
            response='yes'
        )
        db.session.add(avail)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


@pytest.mark.unit
class TestAvailabilityResponses:
    """Test Availability response behaviors."""

    def test_availability_accepts_yes_response(self, db, player, match):
        """
        GIVEN an Availability
        WHEN response is 'yes'
        THEN it should be stored
        """
        avail = AvailabilityFactory(
            match=match,
            player=player,
            discord_id=player.discord_id,
            response='yes'
        )
        db.session.commit()

        assert avail.response == 'yes'

    def test_availability_accepts_no_response(self, db, player, match):
        """
        GIVEN an Availability
        WHEN response is 'no'
        THEN it should be stored
        """
        avail = AvailabilityFactory(
            match=match,
            player=player,
            discord_id=player.discord_id,
            response='no'
        )
        db.session.commit()

        assert avail.response == 'no'

    def test_availability_accepts_maybe_response(self, db, player, match):
        """
        GIVEN an Availability
        WHEN response is 'maybe'
        THEN it should be stored
        """
        avail = AvailabilityFactory(
            match=match,
            player=player,
            discord_id=player.discord_id,
            response='maybe'
        )
        db.session.commit()

        assert avail.response == 'maybe'


@pytest.mark.unit
class TestAvailabilityRelationships:
    """Test Availability relationship behaviors."""

    def test_availability_match_relationship(self, db, player, match):
        """
        GIVEN an Availability linked to a Match
        WHEN accessing the relationship
        THEN the match should be accessible
        """
        avail = AvailabilityFactory(
            match=match,
            player=player,
            discord_id=player.discord_id,
            response='yes'
        )
        db.session.commit()

        assert avail.match == match
        assert avail in match.availability

    def test_availability_player_relationship(self, db, player, match):
        """
        GIVEN an Availability linked to a Player
        WHEN accessing the relationship
        THEN the player should be accessible
        """
        avail = AvailabilityFactory(
            match=match,
            player=player,
            discord_id=player.discord_id,
            response='yes'
        )
        db.session.commit()

        assert avail.player == player
        assert avail in player.availability


@pytest.mark.unit
class TestAvailabilityTimestamps:
    """Test Availability timestamp behaviors."""

    def test_availability_records_responded_at(self, db, player, match):
        """
        GIVEN a new Availability
        WHEN created
        THEN responded_at should be set
        """
        avail = AvailabilityFactory(
            match=match,
            player=player,
            discord_id=player.discord_id,
            response='yes'
        )
        db.session.commit()

        assert avail.responded_at is not None
        assert isinstance(avail.responded_at, datetime)


@pytest.mark.unit
class TestAvailabilitySerialization:
    """Test Availability serialization behaviors."""

    def test_to_dict_includes_required_fields(self, db, player, match):
        """
        GIVEN an Availability
        WHEN to_dict is called
        THEN all required fields should be included
        """
        avail = AvailabilityFactory(
            match=match,
            player=player,
            discord_id=player.discord_id,
            response='yes'
        )
        db.session.commit()

        result = avail.to_dict()

        assert 'id' in result
        assert 'match_id' in result
        assert 'player_id' in result
        assert 'discord_id' in result
        assert 'response' in result
        assert 'responded_at' in result
        assert result['response'] == 'yes'


@pytest.mark.unit
class TestAvailabilityDiscordSync:
    """Test Availability Discord sync behaviors."""

    def test_availability_tracks_sync_status(self, db, player, match):
        """
        GIVEN an Availability
        WHEN discord_sync_status is set
        THEN it should be stored
        """
        avail = AvailabilityFactory(
            match=match,
            player=player,
            discord_id=player.discord_id,
            response='yes',
            discord_sync_status='synced'
        )
        db.session.commit()

        assert avail.discord_sync_status == 'synced'

    def test_availability_tracks_sync_error(self, db, player, match):
        """
        GIVEN an Availability with sync error
        WHEN sync_error is set
        THEN it should be stored
        """
        avail = AvailabilityFactory(
            match=match,
            player=player,
            discord_id=player.discord_id,
            response='yes',
            discord_sync_status='error',
            sync_error='Failed to update Discord'
        )
        db.session.commit()

        assert avail.sync_error == 'Failed to update Discord'


@pytest.mark.unit
class TestAvailabilityUpdates:
    """Test Availability update behaviors."""

    def test_availability_response_can_be_changed(self, db, player, match):
        """
        GIVEN an existing Availability
        WHEN response is changed
        THEN the new response should be stored
        """
        avail = AvailabilityFactory(
            match=match,
            player=player,
            discord_id=player.discord_id,
            response='yes'
        )
        db.session.commit()

        avail.response = 'no'
        db.session.commit()

        refreshed = Availability.query.get(avail.id)
        assert refreshed.response == 'no'
