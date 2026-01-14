"""
Match helpers unit tests.

These tests verify match-related helper functions including:
- Match status determination (MatchStatus enum)
- Match event processing and deduplication
- Schedule display helpers for different week types
- Team standings calculations and score processing
- Player stats updates based on match events
"""
import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import patch, MagicMock, Mock

from app.models import (
    Match, Team, Season, League, Player, Standings,
    PlayerEvent, PlayerEventType, PlayerSeasonStats, PlayerCareerStats
)
from tests.factories import (
    UserFactory, PlayerFactory, TeamFactory, MatchFactory,
    AvailabilityFactory, SeasonFactory, LeagueFactory,
    ScheduleFactory, set_factory_session
)


# =============================================================================
# MATCH STATUS ENUM TESTS
# =============================================================================

@pytest.mark.unit
class TestMatchStatusEnum:
    """Test MatchStatus enum class methods."""

    def test_is_live_returns_true_for_running_status(self, app):
        """
        GIVEN a match with RUNNING status
        WHEN is_live is called
        THEN it should return True
        """
        from app.models.match_status import MatchStatus

        assert MatchStatus.is_live(MatchStatus.RUNNING) is True
        assert MatchStatus.is_live('running') is True

    def test_is_live_returns_false_for_non_running_statuses(self, app):
        """
        GIVEN a match with non-RUNNING status
        WHEN is_live is called
        THEN it should return False
        """
        from app.models.match_status import MatchStatus

        assert MatchStatus.is_live(MatchStatus.NOT_STARTED) is False
        assert MatchStatus.is_live(MatchStatus.COMPLETED) is False
        assert MatchStatus.is_live(MatchStatus.SCHEDULED) is False

    def test_is_finished_returns_true_for_completed_or_stopped(self, app):
        """
        GIVEN a match with COMPLETED or STOPPED status
        WHEN is_finished is called
        THEN it should return True
        """
        from app.models.match_status import MatchStatus

        assert MatchStatus.is_finished(MatchStatus.COMPLETED) is True
        assert MatchStatus.is_finished(MatchStatus.STOPPED) is True

    def test_is_finished_returns_false_for_active_statuses(self, app):
        """
        GIVEN a match with an active status
        WHEN is_finished is called
        THEN it should return False
        """
        from app.models.match_status import MatchStatus

        assert MatchStatus.is_finished(MatchStatus.RUNNING) is False
        assert MatchStatus.is_finished(MatchStatus.SCHEDULED) is False
        assert MatchStatus.is_finished(MatchStatus.NOT_STARTED) is False

    def test_is_active_returns_true_for_scheduled_or_running(self, app):
        """
        GIVEN a match with SCHEDULED or RUNNING status
        WHEN is_active is called
        THEN it should return True
        """
        from app.models.match_status import MatchStatus

        assert MatchStatus.is_active(MatchStatus.SCHEDULED) is True
        assert MatchStatus.is_active(MatchStatus.RUNNING) is True

    def test_is_active_returns_false_for_finished_statuses(self, app):
        """
        GIVEN a match that has finished
        WHEN is_active is called
        THEN it should return False
        """
        from app.models.match_status import MatchStatus

        assert MatchStatus.is_active(MatchStatus.COMPLETED) is False
        assert MatchStatus.is_active(MatchStatus.STOPPED) is False
        assert MatchStatus.is_active(MatchStatus.FAILED) is False

    def test_get_display_name_returns_human_readable_status(self, app):
        """
        GIVEN different match statuses
        WHEN get_display_name is called
        THEN it should return human-readable names
        """
        from app.models.match_status import MatchStatus

        assert MatchStatus.get_display_name(MatchStatus.NOT_STARTED) == 'Not Started'
        assert MatchStatus.get_display_name(MatchStatus.RUNNING) == 'Live'
        assert MatchStatus.get_display_name(MatchStatus.COMPLETED) == 'Completed'

    def test_get_color_class_returns_bootstrap_class(self, app):
        """
        GIVEN different match statuses
        WHEN get_color_class is called
        THEN it should return appropriate Bootstrap color classes
        """
        from app.models.match_status import MatchStatus

        assert MatchStatus.get_color_class(MatchStatus.RUNNING) == 'warning'
        assert MatchStatus.get_color_class(MatchStatus.COMPLETED) == 'success'
        assert MatchStatus.get_color_class(MatchStatus.FAILED) == 'danger'


# =============================================================================
# MATCH EVENT UTILITIES TESTS
# =============================================================================

@pytest.mark.unit
class TestMatchEventKey:
    """Test event_key function for generating unique event identifiers."""

    def test_event_key_generates_key_from_event_data(self, app):
        """
        GIVEN an event dictionary with clock, type, and athlete data
        WHEN event_key is called
        THEN it should generate a unique key string
        """
        from app.utils.match_events_utils import event_key

        event = {
            'clock': {'displayValue': "45'"},
            'type': {'text': 'Goal'},
            'athletesInvolved': [{'displayName': 'John Doe'}],
            'team': {'id': '123'}
        }

        key = event_key(event)

        assert "45'" in key
        assert 'Goal' in key
        assert 'John Doe' in key
        assert '123' in key

    def test_event_key_handles_missing_athlete_info(self, app):
        """
        GIVEN an event without athlete information
        WHEN event_key is called
        THEN it should still generate a valid key
        """
        from app.utils.match_events_utils import event_key

        event = {
            'clock': {'displayValue': "30'"},
            'type': {'text': 'Yellow Card'},
            'team': {'id': '456'}
        }

        key = event_key(event)

        assert "30'" in key
        assert 'Yellow Card' in key
        assert '456' in key

    def test_event_key_handles_empty_event(self, app):
        """
        GIVEN an empty event dictionary
        WHEN event_key is called
        THEN it should return a valid key without errors
        """
        from app.utils.match_events_utils import event_key

        event = {}

        key = event_key(event)

        # Should return something, not raise an exception
        assert key is not None
        assert isinstance(key, str)


@pytest.mark.unit
class TestNormalizeEventType:
    """Test normalize_event_type function for event type standardization."""

    def test_normalize_event_type_normalizes_goal_variations(self, app):
        """
        GIVEN different goal type variations
        WHEN normalize_event_type is called
        THEN it should return 'Goal' for all variations
        """
        from app.utils.match_events_utils import normalize_event_type

        assert normalize_event_type('Goal') == 'Goal'
        assert normalize_event_type('Header Goal') == 'Goal'
        assert normalize_event_type('Penalty') == 'Goal'
        assert normalize_event_type('Free Kick Goal') == 'Goal'

    def test_normalize_event_type_normalizes_card_variations(self, app):
        """
        GIVEN different card type variations
        WHEN normalize_event_type is called
        THEN it should return standardized card types
        """
        from app.utils.match_events_utils import normalize_event_type

        assert normalize_event_type('Yellow Card') == 'Yellow Card'
        assert normalize_event_type('Caution') == 'Yellow Card'
        assert normalize_event_type('Red Card') == 'Red Card'
        assert normalize_event_type('Sending Off') == 'Red Card'
        assert normalize_event_type('Dismissal') == 'Red Card'

    def test_normalize_event_type_normalizes_substitution_variations(self, app):
        """
        GIVEN different substitution type variations
        WHEN normalize_event_type is called
        THEN it should return 'Substitution'
        """
        from app.utils.match_events_utils import normalize_event_type

        assert normalize_event_type('Substitution') == 'Substitution'
        assert normalize_event_type('Tactical Substitution') == 'Substitution'
        assert normalize_event_type('Sub') == 'Substitution'

    def test_normalize_event_type_normalizes_var_variations(self, app):
        """
        GIVEN different VAR type variations
        WHEN normalize_event_type is called
        THEN it should return 'VAR Review'
        """
        from app.utils.match_events_utils import normalize_event_type

        assert normalize_event_type('VAR') == 'VAR Review'
        assert normalize_event_type('Video Review') == 'VAR Review'


@pytest.mark.unit
class TestGetNewEvents:
    """Test get_new_events function for event deduplication."""

    def test_get_new_events_returns_all_events_when_no_history(self, app):
        """
        GIVEN a list of events and no previous event keys
        WHEN get_new_events is called
        THEN it should return all events as new
        """
        from app.utils.match_events_utils import get_new_events

        events = [
            {'clock': {'displayValue': "10'"}, 'type': {'text': 'Goal'}, 'team': {'id': '1'}},
            {'clock': {'displayValue': "20'"}, 'type': {'text': 'Yellow Card'}, 'team': {'id': '2'}}
        ]

        new_events, current_keys = get_new_events(events, [])

        assert len(new_events) == 2
        assert len(current_keys) == 2

    def test_get_new_events_filters_duplicate_events(self, app):
        """
        GIVEN events where some match previous keys
        WHEN get_new_events is called
        THEN it should filter out duplicates
        """
        from app.utils.match_events_utils import get_new_events, event_key, event_fingerprint

        event1 = {'clock': {'displayValue': "10'"}, 'type': {'text': 'Goal'}, 'team': {'id': '1'}}
        event2 = {'clock': {'displayValue': "20'"}, 'type': {'text': 'Yellow Card'}, 'team': {'id': '2'}}

        # First call - both events are new
        events = [event1, event2]
        new_events, current_keys = get_new_events(events, [])

        # Second call with same events - should return no new events
        new_events2, _ = get_new_events(events, current_keys)

        assert len(new_events) == 2
        assert len(new_events2) == 0

    def test_get_new_events_handles_event_updates(self, app):
        """
        GIVEN an event that was updated (e.g., Goal -> Header Goal)
        WHEN get_new_events is called
        THEN it should not duplicate based on fingerprint
        """
        from app.utils.match_events_utils import get_new_events

        # Original event
        original_event = {
            'clock': {'displayValue': "45'"},
            'type': {'text': 'Goal'},
            'athletesInvolved': [{'displayName': 'Player A'}],
            'team': {'id': '1'}
        }

        # First detection
        _, first_keys = get_new_events([original_event], [])

        # Updated event (same minute, same player, different description)
        updated_event = {
            'clock': {'displayValue': "45'"},
            'type': {'text': 'Header Goal'},
            'athletesInvolved': [{'displayName': 'Player A'}],
            'team': {'id': '1'}
        }

        # Should not be detected as new due to fingerprint matching
        new_events, _ = get_new_events([updated_event], first_keys)

        assert len(new_events) == 0


# =============================================================================
# SCHEDULE DISPLAY HELPERS TESTS
# =============================================================================

@pytest.mark.unit
class TestGetMatchDisplayInfo:
    """Test get_match_display_info function for match display configuration."""

    def test_get_match_display_info_returns_regular_for_standard_match(self, db, app, match):
        """
        GIVEN a standard regular season match
        WHEN get_match_display_info is called
        THEN it should return regular match display info
        """
        from app.helpers.schedule_display import get_match_display_info

        # Ensure match is regular type
        match.week_type = 'REGULAR'
        match.is_special_week = False
        db.session.commit()

        result = get_match_display_info(match)

        assert result['type'] == 'regular'
        assert result['show_opponent'] is True
        assert result['show_time'] is True
        assert result['show_location'] is True

    def test_get_match_display_info_returns_playoff_for_playoff_match(self, db, app, match):
        """
        GIVEN a playoff match
        WHEN get_match_display_info is called
        THEN it should return playoff display info
        """
        from app.helpers.schedule_display import get_match_display_info

        match.is_playoff_game = True
        match.playoff_round = 1
        db.session.commit()

        result = get_match_display_info(match)

        assert result['type'] == 'playoff'
        assert 'trophy' in result['icon'].lower()

    def test_get_match_display_info_returns_fun_week_for_fun_type(self, db, app, match):
        """
        GIVEN a fun week match
        WHEN get_match_display_info is called
        THEN it should return fun week display info
        """
        from app.helpers.schedule_display import get_match_display_info

        match.week_type = 'FUN'
        match.is_special_week = True
        db.session.commit()

        result = get_match_display_info(match)

        assert result['type'] == 'fun'
        assert result['show_opponent'] is False
        assert 'Fun Week' in result['title']

    def test_get_match_display_info_returns_bye_for_bye_week(self, db, app, match):
        """
        GIVEN a bye week match
        WHEN get_match_display_info is called
        THEN it should return bye week display info with no time/location
        """
        from app.helpers.schedule_display import get_match_display_info

        match.week_type = 'BYE'
        match.is_special_week = True
        db.session.commit()

        result = get_match_display_info(match)

        assert result['type'] == 'bye'
        assert result['show_time'] is False
        assert result['show_location'] is False


@pytest.mark.unit
class TestGetScheduleDisplayInfo:
    """Test get_schedule_display_info function for schedule display configuration."""

    def test_get_schedule_display_info_returns_regular_info(self, db, app, schedule):
        """
        GIVEN a regular schedule entry
        WHEN get_schedule_display_info is called
        THEN it should return regular display configuration
        """
        from app.helpers.schedule_display import get_schedule_display_info

        result = get_schedule_display_info(schedule)

        assert result['type'] == 'regular'
        assert result['show_opponent'] is True


# =============================================================================
# TEAM STANDINGS CALCULATION TESTS
# =============================================================================

@pytest.mark.unit
class TestAdjustStandings:
    """Test adjust_standings function for standings calculations."""

    def test_adjust_standings_increments_wins_for_home_victory(self, db, app, season, league, team, opponent_team):
        """
        GIVEN a home team victory
        WHEN adjust_standings is called
        THEN it should increment home wins and away losses
        """
        from app.teams_helpers import adjust_standings

        home_standing = Standings(team_id=team.id, season_id=season.id, wins=0, losses=0, draws=0, played=0, goals_for=0, goals_against=0)
        away_standing = Standings(team_id=opponent_team.id, season_id=season.id, wins=0, losses=0, draws=0, played=0, goals_for=0, goals_against=0)
        home_standing.team = team
        away_standing.team = opponent_team

        adjust_standings(home_standing, away_standing, home_score=3, away_score=1)

        assert home_standing.wins == 1
        assert home_standing.losses == 0
        assert away_standing.wins == 0
        assert away_standing.losses == 1

    def test_adjust_standings_increments_wins_for_away_victory(self, db, app, season, league, team, opponent_team):
        """
        GIVEN an away team victory
        WHEN adjust_standings is called
        THEN it should increment away wins and home losses
        """
        from app.teams_helpers import adjust_standings

        home_standing = Standings(team_id=team.id, season_id=season.id, wins=0, losses=0, draws=0, played=0, goals_for=0, goals_against=0)
        away_standing = Standings(team_id=opponent_team.id, season_id=season.id, wins=0, losses=0, draws=0, played=0, goals_for=0, goals_against=0)
        home_standing.team = team
        away_standing.team = opponent_team

        adjust_standings(home_standing, away_standing, home_score=1, away_score=2)

        assert home_standing.wins == 0
        assert home_standing.losses == 1
        assert away_standing.wins == 1
        assert away_standing.losses == 0

    def test_adjust_standings_increments_draws_for_tie(self, db, app, season, league, team, opponent_team):
        """
        GIVEN a tied match
        WHEN adjust_standings is called
        THEN it should increment draws for both teams
        """
        from app.teams_helpers import adjust_standings

        home_standing = Standings(team_id=team.id, season_id=season.id, wins=0, losses=0, draws=0, played=0, goals_for=0, goals_against=0)
        away_standing = Standings(team_id=opponent_team.id, season_id=season.id, wins=0, losses=0, draws=0, played=0, goals_for=0, goals_against=0)
        home_standing.team = team
        away_standing.team = opponent_team

        adjust_standings(home_standing, away_standing, home_score=2, away_score=2)

        assert home_standing.draws == 1
        assert away_standing.draws == 1
        assert home_standing.wins == 0
        assert away_standing.wins == 0

    def test_adjust_standings_calculates_goal_difference_correctly(self, db, app, season, league, team, opponent_team):
        """
        GIVEN a match result
        WHEN adjust_standings is called
        THEN it should calculate goal difference correctly
        """
        from app.teams_helpers import adjust_standings

        home_standing = Standings(team_id=team.id, season_id=season.id, wins=0, losses=0, draws=0, played=0, goals_for=0, goals_against=0)
        away_standing = Standings(team_id=opponent_team.id, season_id=season.id, wins=0, losses=0, draws=0, played=0, goals_for=0, goals_against=0)
        home_standing.team = team
        away_standing.team = opponent_team

        adjust_standings(home_standing, away_standing, home_score=4, away_score=1)

        assert home_standing.goals_for == 4
        assert home_standing.goals_against == 1
        assert home_standing.goal_difference == 3
        assert away_standing.goals_for == 1
        assert away_standing.goals_against == 4
        assert away_standing.goal_difference == -3

    def test_adjust_standings_calculates_points_correctly(self, db, app, season, league, team, opponent_team):
        """
        GIVEN match results
        WHEN adjust_standings is called
        THEN it should calculate points (3 for win, 1 for draw)
        """
        from app.teams_helpers import adjust_standings

        home_standing = Standings(team_id=team.id, season_id=season.id, wins=0, losses=0, draws=0, played=0, goals_for=0, goals_against=0)
        away_standing = Standings(team_id=opponent_team.id, season_id=season.id, wins=0, losses=0, draws=0, played=0, goals_for=0, goals_against=0)
        home_standing.team = team
        away_standing.team = opponent_team

        # Home team wins
        adjust_standings(home_standing, away_standing, home_score=2, away_score=0)

        assert home_standing.points == 3
        assert away_standing.points == 0

    def test_adjust_standings_subtracts_correctly_when_reverting(self, db, app, season, league, team, opponent_team):
        """
        GIVEN standings that need to be reverted
        WHEN adjust_standings is called with subtract=True
        THEN it should subtract the stats correctly
        """
        from app.teams_helpers import adjust_standings

        # Start with existing standings
        home_standing = Standings(team_id=team.id, season_id=season.id, wins=1, losses=0, draws=0, played=1, goals_for=3, goals_against=1, goal_difference=2, points=3)
        away_standing = Standings(team_id=opponent_team.id, season_id=season.id, wins=0, losses=1, draws=0, played=1, goals_for=1, goals_against=3, goal_difference=-2, points=0)
        home_standing.team = team
        away_standing.team = opponent_team

        # Revert the 3-1 result
        adjust_standings(home_standing, away_standing, home_score=3, away_score=1, subtract=True)

        assert home_standing.wins == 0
        assert home_standing.played == 0
        assert home_standing.goals_for == 0
        assert away_standing.losses == 0


# =============================================================================
# MATCH REPORTED PROPERTY TESTS
# =============================================================================

@pytest.mark.unit
class TestMatchReportedProperty:
    """Test Match.reported property for score reporting detection."""

    def test_match_reported_returns_true_when_scores_set(self, db, app, match):
        """
        GIVEN a match with both scores set
        WHEN the reported property is accessed
        THEN it should return True
        """
        match.home_team_score = 2
        match.away_team_score = 1
        db.session.commit()

        assert match.reported is True

    def test_match_reported_returns_false_when_no_scores(self, db, app, match):
        """
        GIVEN a match without scores
        WHEN the reported property is accessed
        THEN it should return False
        """
        match.home_team_score = None
        match.away_team_score = None
        db.session.commit()

        assert match.reported is False

    def test_match_reported_returns_false_when_partial_scores(self, db, app, match):
        """
        GIVEN a match with only one score set
        WHEN the reported property is accessed
        THEN it should return False
        """
        match.home_team_score = 2
        match.away_team_score = None
        db.session.commit()

        assert match.reported is False


# =============================================================================
# MATCH VERIFICATION TESTS
# =============================================================================

@pytest.mark.unit
class TestMatchVerificationStatus:
    """Test Match verification properties and methods."""

    def test_fully_verified_returns_true_when_both_teams_verified(self, db, app, match, user):
        """
        GIVEN a match verified by both teams
        WHEN the fully_verified property is accessed
        THEN it should return True
        """
        match.home_team_verified = True
        match.home_team_verified_by = user.id
        match.home_team_verified_at = datetime.utcnow()
        match.away_team_verified = True
        match.away_team_verified_by = user.id
        match.away_team_verified_at = datetime.utcnow()
        db.session.commit()

        assert match.fully_verified is True

    def test_fully_verified_returns_false_when_one_team_not_verified(self, db, app, match, user):
        """
        GIVEN a match verified by only one team
        WHEN the fully_verified property is accessed
        THEN it should return False
        """
        match.home_team_verified = True
        match.home_team_verified_by = user.id
        match.away_team_verified = False
        db.session.commit()

        assert match.fully_verified is False

    def test_get_verification_status_returns_complete_status(self, db, app, match, user):
        """
        GIVEN a partially verified match
        WHEN get_verification_status is called
        THEN it should return complete verification details
        """
        match.home_team_score = 2
        match.away_team_score = 1
        match.home_team_verified = True
        match.home_team_verified_by = user.id
        match.home_team_verified_at = datetime.utcnow()
        match.away_team_verified = False
        db.session.commit()

        status = match.get_verification_status()

        assert status['reported'] is True
        assert status['home_team_verified'] is True
        assert status['away_team_verified'] is False
        assert status['fully_verified'] is False
        assert status['home_verifier'] == user.username


# =============================================================================
# CURRENT SEASON ID TESTS
# =============================================================================

@pytest.mark.unit
class TestCurrentSeasonId:
    """Test current_season_id function."""

    def test_current_season_id_returns_current_season(self, db, app):
        """
        GIVEN a current season exists
        WHEN current_season_id is called
        THEN it should return the current season's ID
        """
        from app.teams_helpers import current_season_id

        # First, set all seasons to not current
        Season.query.update({'is_current': False})
        db.session.commit()

        # Create a new season that is current
        new_season = Season(
            name='Current Test Season',
            league_type='CLASSIC',
            is_current=True
        )
        db.session.add(new_season)
        db.session.commit()

        result = current_season_id(db.session)

        assert result == new_season.id

    def test_current_season_id_returns_none_when_no_current_season(self, db, app):
        """
        GIVEN no current season exists
        WHEN current_season_id is called
        THEN it should return None
        """
        from app.teams_helpers import current_season_id

        # Remove all current seasons
        Season.query.update({'is_current': False})
        db.session.commit()

        result = current_season_id(db.session)

        assert result is None
