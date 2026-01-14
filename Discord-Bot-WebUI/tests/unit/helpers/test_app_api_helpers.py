"""
Unit tests for app/app_api_helpers.py

These tests verify the Mobile API helper functions:
- PKCE OAuth flow functions (generate_pkce_codes)
- Discord token exchange functions
- Player response building functions
- Match details and event handling functions
- Availability tracking functions
- Query building functions
"""
import pytest
import hashlib
import base64
from datetime import datetime, timedelta, date, time
from unittest.mock import patch, MagicMock, Mock

from app.models import (
    User, Player, Match, Season, Availability,
    PlayerSeasonStats, PlayerCareerStats, PlayerEvent, PlayerEventType
)
from tests.factories import (
    UserFactory, PlayerFactory, MatchFactory, SeasonFactory,
    TeamFactory, LeagueFactory, AvailabilityFactory, set_factory_session
)


# =============================================================================
# PKCE OAUTH FLOW TESTS
# =============================================================================

@pytest.mark.unit
class TestGeneratePKCECodes:
    """Test PKCE code generation for OAuth flow."""

    def test_generate_pkce_codes_returns_tuple(self, app):
        """
        GIVEN the PKCE code generation function
        WHEN called
        THEN a tuple of (code_verifier, code_challenge) should be returned
        """
        from app.app_api_helpers import generate_pkce_codes

        with app.app_context():
            result = generate_pkce_codes()

            assert isinstance(result, tuple)
            assert len(result) == 2

    def test_generate_pkce_codes_verifier_is_url_safe(self, app):
        """
        GIVEN the PKCE code generation function
        WHEN called
        THEN the code_verifier should be URL-safe
        """
        from app.app_api_helpers import generate_pkce_codes

        with app.app_context():
            code_verifier, _ = generate_pkce_codes()

            # URL-safe characters only
            assert all(c.isalnum() or c in '-_' for c in code_verifier)

    def test_generate_pkce_codes_challenge_is_sha256_of_verifier(self, app):
        """
        GIVEN the PKCE code generation function
        WHEN called
        THEN the code_challenge should be the base64url-encoded SHA256 of the verifier
        """
        from app.app_api_helpers import generate_pkce_codes

        with app.app_context():
            code_verifier, code_challenge = generate_pkce_codes()

            # Verify the challenge is derived from verifier
            expected_challenge = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode()).digest()
            ).decode().rstrip('=')

            assert code_challenge == expected_challenge

    def test_generate_pkce_codes_are_unique(self, app):
        """
        GIVEN multiple calls to PKCE code generation
        WHEN called multiple times
        THEN each call should generate unique codes
        """
        from app.app_api_helpers import generate_pkce_codes

        with app.app_context():
            codes = [generate_pkce_codes() for _ in range(5)]
            verifiers = [code[0] for code in codes]

            # All verifiers should be unique
            assert len(set(verifiers)) == 5


# =============================================================================
# DISCORD TOKEN EXCHANGE TESTS
# =============================================================================

@pytest.mark.unit
class TestExchangeDiscordCode:
    """Test Discord authorization code exchange."""

    def test_exchange_discord_code_calls_discord_api(self, app):
        """
        GIVEN valid OAuth parameters
        WHEN exchanging a Discord authorization code
        THEN the Discord API should be called with correct parameters
        """
        from app.app_api_helpers import exchange_discord_code

        with app.app_context():
            with patch('app.app_api_helpers.requests.post') as mock_post:
                mock_response = MagicMock()
                mock_response.ok = True
                mock_response.json.return_value = {'access_token': 'test_token'}
                mock_post.return_value = mock_response

                result = exchange_discord_code(
                    code='test_code',
                    redirect_uri='http://localhost/callback',
                    code_verifier='test_verifier'
                )

                mock_post.assert_called_once()
                call_args = mock_post.call_args
                assert 'https://discord.com/api/oauth2/token' in str(call_args)
                assert result['access_token'] == 'test_token'

    def test_exchange_discord_code_raises_on_failure(self, app):
        """
        GIVEN invalid OAuth parameters
        WHEN exchanging a Discord authorization code
        THEN a RequestException should be raised
        """
        from app.app_api_helpers import exchange_discord_code
        import requests

        with app.app_context():
            with patch('app.app_api_helpers.requests.post') as mock_post:
                mock_response = MagicMock()
                mock_response.ok = False
                mock_response.status_code = 401
                mock_response.text = 'Invalid code'
                mock_response.raise_for_status.side_effect = requests.RequestException('Invalid code')
                mock_post.return_value = mock_response

                with pytest.raises(requests.RequestException):
                    exchange_discord_code(
                        code='invalid_code',
                        redirect_uri='http://localhost/callback',
                        code_verifier='test_verifier'
                    )


@pytest.mark.unit
class TestGetDiscordUserData:
    """Test fetching Discord user data."""

    def test_get_discord_user_data_returns_user_info(self, app):
        """
        GIVEN a valid access token
        WHEN fetching Discord user data
        THEN user information should be returned
        """
        from app.app_api_helpers import get_discord_user_data

        with app.app_context():
            with patch('app.app_api_helpers.requests.get') as mock_get:
                mock_response = MagicMock()
                mock_response.json.return_value = {
                    'id': '123456789',
                    'username': 'testuser',
                    'email': 'test@example.com'
                }
                mock_get.return_value = mock_response

                result = get_discord_user_data('valid_token')

                assert result['id'] == '123456789'
                assert result['username'] == 'testuser'
                assert result['email'] == 'test@example.com'

    def test_get_discord_user_data_uses_bearer_auth(self, app):
        """
        GIVEN an access token
        WHEN fetching Discord user data
        THEN the Bearer authorization header should be set
        """
        from app.app_api_helpers import get_discord_user_data

        with app.app_context():
            with patch('app.app_api_helpers.requests.get') as mock_get:
                mock_response = MagicMock()
                mock_response.json.return_value = {'id': '123'}
                mock_get.return_value = mock_response

                get_discord_user_data('test_token')

                call_kwargs = mock_get.call_args[1]
                assert call_kwargs['headers']['Authorization'] == 'Bearer test_token'


# =============================================================================
# PLAYER RESPONSE BUILDING TESTS
# =============================================================================

@pytest.mark.unit
class TestBuildPlayerResponse:
    """Test player response data building."""

    def test_build_player_response_includes_basic_info(self, app, db, player, team):
        """
        GIVEN a player with basic information
        WHEN building a player response
        THEN basic player info should be included
        """
        from app.app_api_helpers import build_player_response

        with app.app_context():
            with app.test_request_context('/'):
                result = build_player_response(player)

                assert result['id'] == player.id
                assert result['name'] == player.name
                assert 'profile_picture_url' in result

    def test_build_player_response_includes_team_name(self, app, db, player, team):
        """
        GIVEN a player with a primary team
        WHEN building a player response
        THEN team name should be included
        """
        from app.app_api_helpers import build_player_response

        with app.app_context():
            # Set primary team
            player.primary_team_id = team.id
            db.session.commit()

            with app.test_request_context('/'):
                result = build_player_response(player)

                assert result['team_name'] == team.name

    def test_build_player_response_handles_no_team(self, app, db, user):
        """
        GIVEN a player without a primary team
        WHEN building a player response
        THEN team_name should be None
        """
        from app.app_api_helpers import build_player_response

        with app.app_context():
            set_factory_session(db.session)
            player = PlayerFactory(user=user)
            player.primary_team_id = None
            db.session.commit()

            with app.test_request_context('/'):
                result = build_player_response(player)

                assert result['team_name'] is None

    def test_build_player_response_uses_default_profile_picture(self, app, db, player):
        """
        GIVEN a player without a custom profile picture
        WHEN building a player response
        THEN the default profile picture URL should be used
        """
        from app.app_api_helpers import build_player_response

        with app.app_context():
            player.profile_picture_url = None
            db.session.commit()

            with app.test_request_context('/'):
                result = build_player_response(player)

                assert 'default_player.png' in result['profile_picture_url']


# =============================================================================
# PLAYER STATS TESTS
# =============================================================================

@pytest.mark.unit
class TestGetPlayerStats:
    """Test player statistics retrieval."""

    def test_get_player_stats_returns_season_and_career_stats(self, app, db, player, season):
        """
        GIVEN a player with season and career stats
        WHEN getting player stats
        THEN both season and career stats should be returned
        """
        from app.app_api_helpers import get_player_stats

        with app.app_context():
            # Create season stats
            season_stats = PlayerSeasonStats(
                player_id=player.id,
                season_id=season.id,
                goals=5,
                assists=3
            )
            db.session.add(season_stats)

            # Create career stats
            career_stats = PlayerCareerStats(
                player_id=player.id,
                goals=20,
                assists=15
            )
            db.session.add(career_stats)
            db.session.commit()

            result = get_player_stats(player, season, session=db.session)

            assert result['season_stats'] is not None
            assert result['season_stats']['goals'] == 5
            assert result['career_stats'] is not None
            assert result['career_stats']['goals'] == 20

    def test_get_player_stats_returns_none_when_no_stats(self, app, db, player, season):
        """
        GIVEN a player without stats
        WHEN getting player stats
        THEN None should be returned for missing stats
        """
        from app.app_api_helpers import get_player_stats

        with app.app_context():
            result = get_player_stats(player, season, session=db.session)

            assert result['season_stats'] is None
            assert result['career_stats'] is None


# =============================================================================
# MATCH DETAILS UPDATE TESTS
# =============================================================================

@pytest.mark.unit
class TestUpdateMatchDetails:
    """Test match details update functionality."""

    def test_update_match_details_updates_scores(self, app, db, match):
        """
        GIVEN a match and new score data
        WHEN updating match details
        THEN the scores should be updated
        """
        from app.app_api_helpers import update_match_details

        with app.app_context():
            data = {
                'home_team_score': 3,
                'away_team_score': 1,
                'notes': 'Great game!'
            }

            update_match_details(match, data, session=db.session)
            db.session.commit()

            assert match.home_team_score == 3
            assert match.away_team_score == 1
            assert match.notes == 'Great game!'

    def test_update_match_details_handles_none_values(self, app, db, match):
        """
        GIVEN a match and data with None values
        WHEN updating match details
        THEN None values should be applied
        """
        from app.app_api_helpers import update_match_details

        with app.app_context():
            # First set some values
            match.home_team_score = 2
            match.away_team_score = 2
            db.session.commit()

            # Then clear them
            data = {
                'home_team_score': None,
                'away_team_score': None,
                'notes': None
            }

            update_match_details(match, data, session=db.session)
            db.session.commit()

            assert match.home_team_score is None
            assert match.away_team_score is None


# =============================================================================
# MATCH EVENTS TESTS
# =============================================================================

@pytest.mark.unit
class TestAddMatchEvents:
    """Test adding events to a match."""

    def test_add_match_events_creates_events(self, app, db, match, player):
        """
        GIVEN a match and event data
        WHEN adding match events
        THEN events should be created and linked to the match
        """
        from app.app_api_helpers import add_match_events

        with app.app_context():
            events = [
                {
                    'player_id': player.id,
                    'event_type': PlayerEventType.GOAL,
                    'minute': '45'
                },
                {
                    'player_id': player.id,
                    'event_type': PlayerEventType.ASSIST,
                    'minute': '45'
                }
            ]

            add_match_events(match, events, session=db.session)
            db.session.commit()

            # Query for events
            match_events = db.session.query(PlayerEvent).filter_by(match_id=match.id).all()
            assert len(match_events) == 2

    def test_add_match_events_handles_empty_list(self, app, db, team, league):
        """
        GIVEN an empty events list
        WHEN adding match events
        THEN no new events should be added
        """
        from app.app_api_helpers import add_match_events

        with app.app_context():
            # Create a fresh match for this test to avoid cross-test contamination
            set_factory_session(db.session)
            fresh_match = MatchFactory(home_team=team)
            db.session.commit()

            # Get initial count of events for this specific match
            initial_count = db.session.query(PlayerEvent).filter_by(match_id=fresh_match.id).count()

            add_match_events(fresh_match, [], session=db.session)
            db.session.commit()

            # Verify no new events were added
            final_count = db.session.query(PlayerEvent).filter_by(match_id=fresh_match.id).count()
            assert final_count == initial_count


# =============================================================================
# AVAILABILITY UPDATE TESTS
# =============================================================================

@pytest.mark.unit
class TestUpdatePlayerAvailability:
    """Test player availability update functionality."""

    def test_update_player_availability_creates_new_record(self, app, db, match, player):
        """
        GIVEN a player without existing availability
        WHEN updating availability
        THEN a new availability record should be created
        """
        from app.app_api_helpers import update_player_availability

        with app.app_context():
            result = update_player_availability(
                match_id=match.id,
                player_id=player.id,
                discord_id=player.discord_id,
                response='yes',
                session=db.session
            )
            db.session.commit()

            assert result.id is not None
            assert result.response == 'yes'
            assert result.match_id == match.id
            assert result.player_id == player.id

    def test_update_player_availability_updates_existing_record(self, app, db, match, player):
        """
        GIVEN a player with existing availability
        WHEN updating availability
        THEN the existing record should be updated
        """
        from app.app_api_helpers import update_player_availability

        with app.app_context():
            # Create initial availability
            availability = Availability(
                match_id=match.id,
                player_id=player.id,
                discord_id=player.discord_id,
                response='yes'
            )
            db.session.add(availability)
            db.session.commit()
            original_id = availability.id

            # Update availability
            result = update_player_availability(
                match_id=match.id,
                player_id=player.id,
                discord_id=player.discord_id,
                response='no',
                session=db.session
            )
            db.session.commit()

            assert result.id == original_id
            assert result.response == 'no'

    def test_update_player_availability_sets_timestamp(self, app, db, match, player):
        """
        GIVEN availability update data
        WHEN updating availability
        THEN responded_at timestamp should be set
        """
        from app.app_api_helpers import update_player_availability

        with app.app_context():
            before_update = datetime.utcnow()

            result = update_player_availability(
                match_id=match.id,
                player_id=player.id,
                discord_id=player.discord_id,
                response='maybe',
                session=db.session
            )
            db.session.commit()

            assert result.responded_at is not None
            assert result.responded_at >= before_update


# =============================================================================
# TEAM PLAYERS AVAILABILITY TESTS
# =============================================================================

@pytest.mark.unit
class TestGetTeamPlayersAvailability:
    """Test team players availability retrieval."""

    def test_get_team_players_availability_returns_player_list(self, app, db, match, player):
        """
        GIVEN a match and team players
        WHEN getting team players availability
        THEN a list with player availability should be returned
        """
        from app.app_api_helpers import get_team_players_availability

        with app.app_context():
            # Create availability for player
            availability = Availability(
                match_id=match.id,
                player_id=player.id,
                discord_id=player.discord_id,
                response='yes'
            )
            db.session.add(availability)
            db.session.commit()

            result = get_team_players_availability(match, [player], session=db.session)

            assert len(result) == 1
            assert result[0]['id'] == player.id
            assert result[0]['name'] == player.name
            assert result[0]['availability'] == 'yes'

    def test_get_team_players_availability_shows_not_responded(self, app, db, match, player):
        """
        GIVEN a player without availability response
        WHEN getting team players availability
        THEN 'Not responded' should be shown
        """
        from app.app_api_helpers import get_team_players_availability

        with app.app_context():
            result = get_team_players_availability(match, [player], session=db.session)

            assert result[0]['availability'] == 'Not responded'


# =============================================================================
# MATCH EVENTS RETRIEVAL TESTS
# =============================================================================

@pytest.mark.unit
class TestGetMatchEvents:
    """Test match events retrieval with card counting."""

    def test_get_match_events_returns_expected_structure(self, app, db):
        """
        GIVEN a match (with or without events)
        WHEN getting match events
        THEN the result should have the expected structure with card counts and events list
        """
        from app.app_api_helpers import get_match_events

        with app.app_context():
            set_factory_session(db.session)

            # Create a completely fresh match that won't have events from other tests
            fresh_league = LeagueFactory()
            fresh_home_team = TeamFactory(league=fresh_league)
            fresh_away_team = TeamFactory(league=fresh_league)
            fresh_match = MatchFactory(home_team=fresh_home_team, away_team=fresh_away_team)
            db.session.commit()

            result = get_match_events(fresh_match)

            # Verify structure
            assert 'home_yellow_cards' in result
            assert 'away_yellow_cards' in result
            assert 'home_red_cards' in result
            assert 'away_red_cards' in result
            assert 'events' in result
            assert isinstance(result['events'], list)

    def test_get_match_events_counts_cards_correctly(self, app, db):
        """
        GIVEN a match with specific card events added
        WHEN getting match events
        THEN cards should be counted by team correctly
        """
        from app.app_api_helpers import get_match_events

        with app.app_context():
            set_factory_session(db.session)

            # Create completely isolated test data
            fresh_user = UserFactory()
            fresh_league = LeagueFactory()
            fresh_home_team = TeamFactory(league=fresh_league)
            fresh_away_team = TeamFactory(league=fresh_league)
            fresh_match = MatchFactory(home_team=fresh_home_team, away_team=fresh_away_team)
            fresh_player = PlayerFactory(user=fresh_user)
            fresh_player.primary_team_id = fresh_home_team.id
            db.session.commit()

            # Count events before adding new one
            initial_event_count = len(fresh_match.events)

            # Create yellow card event for home team player
            event = PlayerEvent(
                player_id=fresh_player.id,
                match_id=fresh_match.id,
                event_type=PlayerEventType.YELLOW_CARD,
                minute='30'
            )
            db.session.add(event)
            db.session.commit()

            # Expire and refresh to get fresh data
            db.session.expire(fresh_match)
            db.session.refresh(fresh_match)

            result = get_match_events(fresh_match)

            # The function should count the yellow card we just added
            assert result['home_yellow_cards'] >= 1
            assert len(result['events']) > initial_event_count

    def test_get_match_events_event_details_structure(self, app, db):
        """
        GIVEN a match with an event
        WHEN getting match events
        THEN each event should have required fields
        """
        from app.app_api_helpers import get_match_events

        with app.app_context():
            set_factory_session(db.session)

            # Create isolated test data
            fresh_user = UserFactory()
            fresh_league = LeagueFactory()
            fresh_home_team = TeamFactory(league=fresh_league)
            fresh_away_team = TeamFactory(league=fresh_league)
            fresh_match = MatchFactory(home_team=fresh_home_team, away_team=fresh_away_team)
            fresh_player = PlayerFactory(user=fresh_user, name='Test Event Player')
            fresh_player.primary_team_id = fresh_home_team.id
            db.session.commit()

            # Create a goal event
            event = PlayerEvent(
                player_id=fresh_player.id,
                match_id=fresh_match.id,
                event_type=PlayerEventType.GOAL,
                minute='45'
            )
            db.session.add(event)
            db.session.commit()

            db.session.expire(fresh_match)
            db.session.refresh(fresh_match)

            result = get_match_events(fresh_match)

            # Find our event in the results
            our_events = [e for e in result['events'] if e['player_id'] == fresh_player.id]
            assert len(our_events) >= 1

            event_data = our_events[0]
            assert 'id' in event_data
            assert 'player_id' in event_data
            assert 'player_name' in event_data
            assert 'match_id' in event_data
            assert 'minute' in event_data
            assert 'event_type' in event_data
            assert 'team' in event_data
            assert event_data['player_name'] == 'Test Event Player'


# =============================================================================
# PLAYER AVAILABILITY RETRIEVAL TESTS
# =============================================================================

@pytest.mark.unit
class TestGetPlayerAvailability:
    """Test single player availability retrieval."""

    def test_get_player_availability_returns_dict(self, app, db, match, player):
        """
        GIVEN a player with availability
        WHEN getting player availability
        THEN availability dict should be returned
        """
        from app.app_api_helpers import get_player_availability

        with app.app_context():
            availability = Availability(
                match_id=match.id,
                player_id=player.id,
                discord_id=player.discord_id,
                response='yes'
            )
            db.session.add(availability)
            db.session.commit()

            result = get_player_availability(match, player, session=db.session)

            assert result is not None
            assert result['response'] == 'yes'
            assert result['match_id'] == match.id

    def test_get_player_availability_returns_none_when_not_found(self, app, db, match, player):
        """
        GIVEN a player without availability
        WHEN getting player availability
        THEN None should be returned
        """
        from app.app_api_helpers import get_player_availability

        with app.app_context():
            result = get_player_availability(match, player, session=db.session)

            assert result is None


# =============================================================================
# MATCHES QUERY BUILDING TESTS
# =============================================================================

@pytest.mark.unit
class TestBuildMatchesQuery:
    """Test match query building with filters."""

    def test_build_matches_query_filters_by_team_id(self, app, db, match, team):
        """
        GIVEN a team_id filter
        WHEN building matches query
        THEN only matches for that team should be included
        """
        from app.app_api_helpers import build_matches_query

        with app.app_context():
            query = build_matches_query(
                team_id=team.id,
                player=None,
                session=db.session
            )
            matches = query.all()

            # All matches should include the team
            for m in matches:
                assert m.home_team_id == team.id or m.away_team_id == team.id

    def test_build_matches_query_filters_upcoming(self, app, db, team, league, season):
        """
        GIVEN upcoming=True filter
        WHEN building matches query
        THEN only future matches should be included
        """
        from app.app_api_helpers import build_matches_query

        with app.app_context():
            set_factory_session(db.session)

            # Create a future match
            future_match = MatchFactory(
                home_team=team,
                date=date.today() + timedelta(days=7)
            )
            db.session.commit()

            query = build_matches_query(
                team_id=team.id,
                player=None,
                upcoming=True,
                session=db.session
            )
            matches = query.all()

            for m in matches:
                assert m.date >= date.today()

    def test_build_matches_query_applies_limit(self, app, db, team):
        """
        GIVEN a limit parameter
        WHEN building matches query
        THEN result count should not exceed limit
        """
        from app.app_api_helpers import build_matches_query

        with app.app_context():
            query = build_matches_query(
                team_id=team.id,
                player=None,
                limit=5,
                session=db.session
            )
            matches = query.all()

            assert len(matches) <= 5


# =============================================================================
# PROCESS MATCHES DATA TESTS
# =============================================================================

@pytest.mark.unit
class TestProcessMatchesData:
    """Test match data processing."""

    def test_process_matches_data_converts_to_dicts(self, app, db):
        """
        GIVEN a list of matches
        WHEN processing matches data
        THEN list of dictionaries should be returned
        """
        from flask import g
        from app.app_api_helpers import process_matches_data

        with app.app_context():
            # Set g.db_session which is required by model serialization
            g.db_session = db.session

            set_factory_session(db.session)

            # Create completely isolated test data
            fresh_league = LeagueFactory()
            fresh_home_team = TeamFactory(league=fresh_league)
            fresh_away_team = TeamFactory(league=fresh_league)
            fresh_match = MatchFactory(home_team=fresh_home_team, away_team=fresh_away_team)
            db.session.commit()

            # Refresh to ensure relationships are loaded
            db.session.refresh(fresh_match)

            result = process_matches_data([fresh_match], player=None, session=db.session)

            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], dict)
            assert 'id' in result[0]
            assert result[0]['id'] == fresh_match.id

    def test_process_matches_data_includes_availability(self, app, db):
        """
        GIVEN include_availability=True
        WHEN processing matches data
        THEN availability should be included
        """
        from flask import g
        from app.app_api_helpers import process_matches_data

        with app.app_context():
            # Set g.db_session which is required by model serialization
            g.db_session = db.session

            set_factory_session(db.session)

            # Create completely isolated test data
            fresh_user = UserFactory()
            fresh_league = LeagueFactory()
            fresh_home_team = TeamFactory(league=fresh_league)
            fresh_away_team = TeamFactory(league=fresh_league)
            fresh_match = MatchFactory(home_team=fresh_home_team, away_team=fresh_away_team)
            fresh_player = PlayerFactory(user=fresh_user)
            db.session.commit()

            # Create availability
            availability = Availability(
                match_id=fresh_match.id,
                player_id=fresh_player.id,
                discord_id=fresh_player.discord_id,
                response='yes'
            )
            db.session.add(availability)
            db.session.commit()

            # Refresh match to ensure relationships are loaded
            db.session.refresh(fresh_match)

            result = process_matches_data(
                [fresh_match],
                player=fresh_player,
                include_availability=True,
                session=db.session
            )

            assert result[0]['availability'] is not None
            assert result[0]['availability']['response'] == 'yes'


# =============================================================================
# NOTIFY AVAILABILITY UPDATE TESTS
# =============================================================================

@pytest.mark.unit
class TestNotifyAvailabilityUpdate:
    """Test availability update notifications."""

    def test_notify_availability_update_triggers_tasks(self, app, db, match, player):
        """
        GIVEN availability update data
        WHEN notifying of availability update
        THEN background tasks should be triggered
        """
        with app.app_context():
            # Mock the tasks module that is imported inside notify_availability_update
            mock_discord_task = MagicMock()
            mock_frontend_task = MagicMock()

            with patch.dict('sys.modules', {
                'app.tasks': MagicMock(
                    notify_discord_of_rsvp_change_task=mock_discord_task,
                    notify_frontend_of_rsvp_change_task=mock_frontend_task
                )
            }):
                # Re-import to get the function with mocked dependencies
                import importlib
                import app.app_api_helpers as helpers_module
                importlib.reload(helpers_module)

                helpers_module.notify_availability_update(
                    match_id=match.id,
                    player_id=player.id,
                    response='yes',
                    session=db.session
                )

                mock_discord_task.delay.assert_called_once_with(match.id)
                mock_frontend_task.delay.assert_called_once_with(match.id, player.id, 'yes')


# =============================================================================
# UPDATE PLAYER MATCH AVAILABILITY TESTS
# =============================================================================

@pytest.mark.unit
class TestUpdatePlayerMatchAvailability:
    """Test player match availability update with validation."""

    def test_update_player_match_availability_returns_true_on_success(self, app, db, match, player):
        """
        GIVEN valid player and match
        WHEN updating player match availability
        THEN True should be returned
        """
        from app.app_api_helpers import update_player_match_availability

        with app.app_context():
            result = update_player_match_availability(
                match_id=match.id,
                player_id=player.id,
                new_response='yes',
                session=db.session
            )

            assert result is True

    def test_update_player_match_availability_returns_false_for_invalid_player(self, app, db, match):
        """
        GIVEN an invalid player_id
        WHEN updating player match availability
        THEN False should be returned
        """
        from app.app_api_helpers import update_player_match_availability

        with app.app_context():
            result = update_player_match_availability(
                match_id=match.id,
                player_id=99999,  # Non-existent player
                new_response='yes',
                session=db.session
            )

            assert result is False


# =============================================================================
# GET TEAM UPCOMING MATCHES TESTS
# =============================================================================

@pytest.mark.unit
class TestGetTeamUpcomingMatches:
    """Test team upcoming matches retrieval."""

    def test_get_team_upcoming_matches_returns_list(self, app, db, team):
        """
        GIVEN a team
        WHEN getting team upcoming matches
        THEN a list of match dicts should be returned
        """
        from app.app_api_helpers import get_team_upcoming_matches

        with app.app_context():
            result = get_team_upcoming_matches(team.id, session=db.session)

            assert isinstance(result, list)

    def test_get_team_upcoming_matches_limits_to_five(self, app, db, team, league, season):
        """
        GIVEN a team with many upcoming matches
        WHEN getting team upcoming matches
        THEN at most 5 matches should be returned
        """
        from app.app_api_helpers import get_team_upcoming_matches

        with app.app_context():
            set_factory_session(db.session)

            # Create multiple future matches
            for i in range(10):
                MatchFactory(
                    home_team=team,
                    date=date.today() + timedelta(days=i + 1)
                )
            db.session.commit()

            result = get_team_upcoming_matches(team.id, session=db.session)

            assert len(result) <= 5


# =============================================================================
# GET PLAYER RESPONSE DATA TESTS
# =============================================================================

@pytest.mark.unit
class TestGetPlayerResponseData:
    """Test full player response data building."""

    def test_get_player_response_data_basic_includes_minimal_info(self, app, db, player, team):
        """
        GIVEN full=False
        WHEN getting player response data
        THEN only basic info should be included
        """
        from app.app_api_helpers import get_player_response_data

        with app.app_context():
            with app.test_request_context('/'):
                result = get_player_response_data(player, full=False, session=db.session)

                assert 'id' in result
                assert 'name' in result
                assert 'phone' not in result

    def test_get_player_response_data_full_includes_all_info(self, app, db, player, team):
        """
        GIVEN full=True
        WHEN getting player response data
        THEN all player info should be included
        """
        from app.app_api_helpers import get_player_response_data

        with app.app_context():
            with app.test_request_context('/'):
                result = get_player_response_data(player, full=True, session=db.session)

                assert 'id' in result
                assert 'name' in result
                assert 'phone' in result
                assert 'is_coach' in result
                assert 'is_ref' in result
                assert 'discord_id' in result
                assert 'jersey_size' in result
                assert 'jersey_number' in result


# =============================================================================
# PROCESS DISCORD USER TESTS
# =============================================================================

@pytest.mark.unit
class TestProcessDiscordUser:
    """Test Discord user processing and local user creation."""

    def test_process_discord_user_creates_new_user_with_correct_attributes(self, app, db):
        """
        GIVEN Discord user data for a new user
        WHEN processing Discord user
        THEN a new User should be created with the Discord username and email
        """
        from flask import g
        from app.app_api_helpers import process_discord_user

        with app.app_context():
            g.db_session = db.session

            # Use a unique email to avoid conflicts
            import uuid
            unique_email = f'newuser_{uuid.uuid4().hex[:8]}@example.com'

            user_data = {
                'id': '123456789',
                'username': 'newdiscorduser',
                'email': unique_email
            }

            # Use no_autoflush to avoid the NOT NULL constraint on password_hash
            # when the function adds the user to the session
            with db.session.no_autoflush:
                result = process_discord_user(db.session, user_data)

            # Verify the user was created with correct attributes
            assert result is not None
            assert result.username == 'newdiscorduser'
            # User is not yet approved (OAuth flow users need approval)
            assert result.is_approved is False

    def test_process_discord_user_returns_existing_user(self, app, db):
        """
        GIVEN Discord user data for an existing user
        WHEN processing Discord user
        THEN the existing User should be returned
        """
        from flask import g
        from app.app_api_helpers import process_discord_user

        with app.app_context():
            g.db_session = db.session

            # Create existing user
            set_factory_session(db.session)
            existing_user = UserFactory(
                username='existinguser',
                email='existing@example.com'
            )
            db.session.commit()
            user_id = existing_user.id

            user_data = {
                'id': '123456789',
                'username': 'existinguser',
                'email': 'existing@example.com'
            }

            result = process_discord_user(db.session, user_data)

            assert result.id == user_id

    def test_process_discord_user_handles_email_lookup(self, app, db):
        """
        GIVEN existing user data in the database
        WHEN processing Discord user with matching email
        THEN the function should find and return the existing user

        This tests the core email hash lookup mechanism used by process_discord_user.
        """
        from flask import g
        from app.app_api_helpers import process_discord_user
        from app.utils.pii_encryption import create_hash

        with app.app_context():
            g.db_session = db.session

            # Use a unique email for this test
            import uuid
            test_email = f'lookup_test_{uuid.uuid4().hex[:8]}@example.com'

            # Create existing user
            set_factory_session(db.session)
            existing_user = UserFactory(
                username='lookupuser',
                email=test_email
            )
            db.session.commit()

            # Call process_discord_user with matching email
            user_data = {
                'id': '555666777',
                'username': 'lookupuser',
                'email': test_email
            }

            result = process_discord_user(db.session, user_data)

            # Should return the existing user, not create a new one
            assert result.id == existing_user.id
            assert result.username == 'lookupuser'
