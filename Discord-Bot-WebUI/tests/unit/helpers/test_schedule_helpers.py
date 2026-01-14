"""
Schedule helpers unit tests.

These tests verify the schedule-related module behaviors:
- AutoScheduleGenerator class for round-robin schedule generation
- Schedule display helpers for match visualization
- Date/time handling for matches
- Match scheduling logic and constraints

Key areas covered:
- Round-robin pairing generation
- Week constraint validation (C1-C6)
- Special week handling (FUN, TST, BYE, PLAYOFF, BONUS)
- Time slot generation for different leagues
- Match display info formatting
"""
import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import patch, MagicMock, Mock
from collections import defaultdict

from app.models import User, Team, Match, League, Season, Schedule
from tests.factories import (
    UserFactory, TeamFactory, MatchFactory, SeasonFactory,
    LeagueFactory, ScheduleFactory, set_factory_session
)


# =============================================================================
# AUTO SCHEDULE GENERATOR - INITIALIZATION TESTS
# =============================================================================

@pytest.mark.unit
class TestAutoScheduleGeneratorInit:
    """Test AutoScheduleGenerator initialization and setup."""

    def test_init_with_valid_league_creates_generator(self, db, app, league):
        """
        GIVEN a valid league with teams
        WHEN AutoScheduleGenerator is initialized
        THEN it should create a generator with correct league reference
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        # Create teams for the league
        for i in range(8):
            team = Team(name=f'Team {i+1}', league_id=league.id)
            db.session.add(team)
        db.session.commit()

        generator = AutoScheduleGenerator(league.id, db.session)

        assert generator.league_id == league.id
        assert generator.league is not None
        assert generator.num_teams == 8

    def test_init_with_invalid_league_raises_error(self, db, app):
        """
        GIVEN a non-existent league ID
        WHEN AutoScheduleGenerator is initialized
        THEN it should raise ValueError
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        with pytest.raises(ValueError) as exc_info:
            AutoScheduleGenerator(99999, db.session)

        assert "not found" in str(exc_info.value)

    def test_init_filters_out_placeholder_teams(self, db, app, league):
        """
        GIVEN a league with real teams and placeholder teams (FUN WEEK, BYE, TST)
        WHEN AutoScheduleGenerator is initialized
        THEN it should filter out placeholder teams from the team list
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        # Create real teams
        for i in range(6):
            team = Team(name=f'Team {i+1}', league_id=league.id)
            db.session.add(team)

        # Create placeholder teams
        for placeholder_name in ['FUN WEEK', 'BYE', 'TST']:
            team = Team(name=placeholder_name, league_id=league.id)
            db.session.add(team)

        db.session.commit()

        generator = AutoScheduleGenerator(league.id, db.session)

        # Should only count real teams, not placeholders
        assert generator.num_teams == 6
        team_names = [t.name for t in generator.teams]
        assert 'FUN WEEK' not in team_names
        assert 'BYE' not in team_names
        assert 'TST' not in team_names

    def test_init_with_fewer_than_two_teams_raises_error(self, db, app, league):
        """
        GIVEN a league with only 1 team
        WHEN AutoScheduleGenerator is initialized
        THEN it should raise ValueError
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        # Create only 1 team
        team = Team(name='Only Team', league_id=league.id)
        db.session.add(team)
        db.session.commit()

        with pytest.raises(ValueError) as exc_info:
            AutoScheduleGenerator(league.id, db.session)

        assert "at least 2 teams" in str(exc_info.value)


# =============================================================================
# AUTO SCHEDULE GENERATOR - CONFIGURATION TESTS
# =============================================================================

@pytest.mark.unit
class TestAutoScheduleGeneratorConfig:
    """Test AutoScheduleGenerator configuration methods."""

    def test_set_config_stores_values_correctly(self, db, app, league):
        """
        GIVEN a valid AutoScheduleGenerator
        WHEN set_config is called with parameters
        THEN it should store all configuration values
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        # Create 8 teams for valid generator
        for i in range(8):
            team = Team(name=f'Team {i+1}', league_id=league.id)
            db.session.add(team)
        db.session.commit()

        generator = AutoScheduleGenerator(league.id, db.session)
        generator.set_config(
            start_time=time(8, 20),
            match_duration_minutes=70,
            weeks_count=7,
            fields="North,South"
        )

        assert generator.start_time == time(8, 20)
        assert generator.match_duration_minutes == 70
        assert generator.weeks_count == 7
        assert generator.fields == ['North', 'South']

    def test_set_config_parses_multiple_fields(self, db, app, league):
        """
        GIVEN a field string with multiple fields
        WHEN set_config is called
        THEN it should parse fields into a list
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        for i in range(8):
            team = Team(name=f'Team {i+1}', league_id=league.id)
            db.session.add(team)
        db.session.commit()

        generator = AutoScheduleGenerator(league.id, db.session)
        generator.set_config(
            start_time=time(8, 0),
            match_duration_minutes=60,
            weeks_count=7,
            fields="North, South, West, East"
        )

        assert len(generator.fields) == 4
        assert 'North' in generator.fields
        assert 'South' in generator.fields
        assert 'West' in generator.fields
        assert 'East' in generator.fields


# =============================================================================
# AUTO SCHEDULE GENERATOR - PAIR KEY TESTS
# =============================================================================

@pytest.mark.unit
class TestAutoScheduleGeneratorPairKey:
    """Test pair key generation for constraint tracking."""

    def test_get_pair_key_returns_consistent_key(self, db, app, league):
        """
        GIVEN two team IDs
        WHEN _get_pair_key is called in different orders
        THEN it should return the same key
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        for i in range(8):
            team = Team(name=f'Team {i+1}', league_id=league.id)
            db.session.add(team)
        db.session.commit()

        generator = AutoScheduleGenerator(league.id, db.session)

        key1 = generator._get_pair_key(100, 200)
        key2 = generator._get_pair_key(200, 100)

        assert key1 == key2
        assert key1 == "100_200"

    def test_get_pair_key_format_is_min_max(self, db, app, league):
        """
        GIVEN two team IDs
        WHEN _get_pair_key is called
        THEN it should format as "{min}_{max}"
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        for i in range(8):
            team = Team(name=f'Team {i+1}', league_id=league.id)
            db.session.add(team)
        db.session.commit()

        generator = AutoScheduleGenerator(league.id, db.session)

        key = generator._get_pair_key(500, 100)

        assert key == "100_500"


# =============================================================================
# AUTO SCHEDULE GENERATOR - WEEK VALIDATION TESTS
# =============================================================================

@pytest.mark.unit
class TestAutoScheduleGeneratorWeekValidation:
    """Test week constraint validation logic."""

    def test_validate_week_constraints_passes_for_valid_week(self, db, app, league):
        """
        GIVEN a week where each team plays exactly 2 games
        WHEN _validate_week_constraints is called
        THEN it should return True
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        for i in range(8):
            team = Team(name=f'Team {i+1}', league_id=league.id)
            db.session.add(team)
        db.session.commit()

        generator = AutoScheduleGenerator(league.id, db.session)
        team_ids = [t.id for t in generator.teams]

        # Create valid week matches (each team plays twice)
        week_matches = [
            (team_ids[0], team_ids[1]),
            (team_ids[2], team_ids[3]),
            (team_ids[0], team_ids[2]),
            (team_ids[1], team_ids[3]),
            (team_ids[4], team_ids[5]),
            (team_ids[6], team_ids[7]),
            (team_ids[4], team_ids[6]),
            (team_ids[5], team_ids[7]),
        ]

        last_week_opponents = {tid: set() for tid in team_ids}

        result = generator._validate_week_constraints(week_matches, team_ids, last_week_opponents)

        assert result is True

    def test_validate_week_constraints_fails_for_c2_violation(self, db, app, league):
        """
        GIVEN a week where teams don't play exactly 2 games each
        WHEN _validate_week_constraints is called
        THEN it should return False (C2 violation)
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        for i in range(8):
            team = Team(name=f'Team {i+1}', league_id=league.id)
            db.session.add(team)
        db.session.commit()

        generator = AutoScheduleGenerator(league.id, db.session)
        team_ids = [t.id for t in generator.teams]

        # Invalid week - team_ids[0] only plays once
        week_matches = [
            (team_ids[0], team_ids[1]),
            (team_ids[2], team_ids[3]),
            (team_ids[2], team_ids[4]),
            (team_ids[3], team_ids[5]),
        ]

        last_week_opponents = {tid: set() for tid in team_ids}

        result = generator._validate_week_constraints(week_matches, team_ids, last_week_opponents)

        assert result is False

    def test_validate_week_constraints_fails_for_c3_violation(self, db, app, league):
        """
        GIVEN a week where teams face same opponent as last week
        WHEN _validate_week_constraints is called
        THEN it should return False (C3 violation - immediate rematch)
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        for i in range(8):
            team = Team(name=f'Team {i+1}', league_id=league.id)
            db.session.add(team)
        db.session.commit()

        generator = AutoScheduleGenerator(league.id, db.session)
        team_ids = [t.id for t in generator.teams]

        # Valid game count but C3 violation
        week_matches = [
            (team_ids[0], team_ids[1]),
            (team_ids[2], team_ids[3]),
            (team_ids[0], team_ids[2]),
            (team_ids[1], team_ids[3]),
            (team_ids[4], team_ids[5]),
            (team_ids[6], team_ids[7]),
            (team_ids[4], team_ids[6]),
            (team_ids[5], team_ids[7]),
        ]

        # Set up last week opponents to create C3 violation
        last_week_opponents = {tid: set() for tid in team_ids}
        last_week_opponents[team_ids[0]].add(team_ids[1])  # Team 0 played Team 1 last week
        last_week_opponents[team_ids[1]].add(team_ids[0])

        result = generator._validate_week_constraints(week_matches, team_ids, last_week_opponents)

        assert result is False


# =============================================================================
# AUTO SCHEDULE GENERATOR - TIME SLOT TESTS
# =============================================================================

@pytest.mark.unit
class TestAutoScheduleGeneratorTimeSlots:
    """Test time slot generation for different leagues."""

    def test_generate_time_slots_premier_league(self, db, app, season):
        """
        GIVEN a Premier league
        WHEN _generate_time_slots is called
        THEN it should return Premier League specification times
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        # Create Premier league
        league = League(name='Premier', season_id=season.id)
        db.session.add(league)
        db.session.flush()

        for i in range(8):
            team = Team(name=f'Team {i+1}', league_id=league.id)
            db.session.add(team)
        db.session.commit()

        generator = AutoScheduleGenerator(league.id, db.session)
        generator.set_config(start_time=time(8, 20), match_duration_minutes=70, weeks_count=7, fields="North,South")

        time_slots = generator._generate_time_slots()

        assert len(time_slots) == 4
        assert time_slots[0] == time(8, 20)
        assert time_slots[1] == time(9, 30)
        assert time_slots[2] == time(10, 40)
        assert time_slots[3] == time(11, 50)

    def test_generate_time_slots_classic_league(self, db, app, season):
        """
        GIVEN a Classic league
        WHEN _generate_time_slots is called
        THEN it should return Classic League specification times
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        # Create Classic league
        league = League(name='Classic', season_id=season.id)
        db.session.add(league)
        db.session.flush()

        for i in range(8):
            team = Team(name=f'Team {i+1}', league_id=league.id)
            db.session.add(team)
        db.session.commit()

        generator = AutoScheduleGenerator(league.id, db.session)
        generator.set_config(start_time=time(13, 10), match_duration_minutes=70, weeks_count=7, fields="North,South")

        time_slots = generator._generate_time_slots()

        assert len(time_slots) == 2
        assert time_slots[0] == time(13, 10)
        assert time_slots[1] == time(14, 20)


# =============================================================================
# AUTO SCHEDULE GENERATOR - DEFAULT SEASON CONFIG TESTS
# =============================================================================

@pytest.mark.unit
class TestDefaultSeasonConfiguration:
    """Test default season configuration creation."""

    def test_create_default_season_config_premier(self, db, app, league):
        """
        GIVEN a Premier league type
        WHEN create_default_season_configuration is called
        THEN it should return correct Premier defaults
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        config = AutoScheduleGenerator.create_default_season_configuration(
            league_id=league.id,
            league_type='PREMIER'
        )

        assert config.league_type == 'PREMIER'
        assert config.regular_season_weeks == 7
        assert config.playoff_weeks == 2
        assert config.has_fun_week is True
        assert config.has_tst_week is True
        assert config.has_bonus_week is True
        assert config.has_practice_sessions is False

    def test_create_default_season_config_classic(self, db, app, league):
        """
        GIVEN a Classic league type
        WHEN create_default_season_configuration is called
        THEN it should return correct Classic defaults
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        config = AutoScheduleGenerator.create_default_season_configuration(
            league_id=league.id,
            league_type='CLASSIC'
        )

        assert config.league_type == 'CLASSIC'
        assert config.regular_season_weeks == 8
        assert config.playoff_weeks == 1
        assert config.has_fun_week is False
        assert config.has_tst_week is False
        assert config.has_bonus_week is False

    def test_create_default_season_config_unknown_type_raises(self, db, app, league):
        """
        GIVEN an unknown league type
        WHEN create_default_season_configuration is called
        THEN it should raise ValueError
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        with pytest.raises(ValueError) as exc_info:
            AutoScheduleGenerator.create_default_season_configuration(
                league_id=league.id,
                league_type='UNKNOWN'
            )

        assert "Unknown league type" in str(exc_info.value)


# =============================================================================
# SCHEDULE DISPLAY - MATCH DISPLAY INFO TESTS
# =============================================================================

@pytest.mark.unit
class TestGetMatchDisplayInfo:
    """Test get_match_display_info function for match visualization."""

    def test_get_match_display_info_regular_match(self, db, app, match):
        """
        GIVEN a regular match without special week_type
        WHEN get_match_display_info is called
        THEN it should return regular match display info
        """
        from app.helpers.schedule_display import get_match_display_info

        result = get_match_display_info(match)

        assert result['type'] == 'regular'
        assert result['show_opponent'] is True
        assert result['show_time'] is True
        assert result['show_location'] is True
        assert result['css_class'] == 'regular-week'

    def test_get_match_display_info_playoff_match(self, db, app, match):
        """
        GIVEN a match marked as playoff game
        WHEN get_match_display_info is called
        THEN it should return playoff display info
        """
        from app.helpers.schedule_display import get_match_display_info

        match.is_playoff_game = True
        match.week_type = 'PLAYOFF'
        match.playoff_round = 1
        db.session.commit()

        result = get_match_display_info(match)

        assert result['type'] == 'playoff'
        assert 'Playoffs' in result['title']
        assert result['css_class'] == 'playoff-week'
        assert result['icon'] == 'ti-trophy'

    def test_get_match_display_info_fun_week(self, db, app, match):
        """
        GIVEN a match with FUN week type
        WHEN get_match_display_info is called
        THEN it should return fun week display info
        """
        from app.helpers.schedule_display import get_match_display_info

        match.week_type = 'FUN'
        db.session.commit()

        result = get_match_display_info(match)

        assert result['type'] == 'fun'
        assert result['title'] == 'Fun Week'
        assert result['show_opponent'] is False
        assert result['css_class'] == 'fun-week'
        assert result['icon'] == 'ti-star'

    def test_get_match_display_info_tst_week(self, db, app, match):
        """
        GIVEN a match with TST week type
        WHEN get_match_display_info is called
        THEN it should return TST display info
        """
        from app.helpers.schedule_display import get_match_display_info

        match.week_type = 'TST'
        db.session.commit()

        result = get_match_display_info(match)

        assert result['type'] == 'tst'
        assert result['title'] == 'The Soccer Tournament'
        assert result['css_class'] == 'tst-week'
        assert result['icon'] == 'ti-target'

    def test_get_match_display_info_bye_week(self, db, app, match):
        """
        GIVEN a match with BYE week type
        WHEN get_match_display_info is called
        THEN it should return BYE week display info
        """
        from app.helpers.schedule_display import get_match_display_info

        match.week_type = 'BYE'
        db.session.commit()

        result = get_match_display_info(match)

        assert result['type'] == 'bye'
        assert result['title'] == 'BYE Week'
        assert result['show_time'] is False
        assert result['show_location'] is False
        assert result['css_class'] == 'bye-week'


# =============================================================================
# SCHEDULE DISPLAY - SCHEDULE DISPLAY INFO TESTS
# =============================================================================

@pytest.mark.unit
class TestGetScheduleDisplayInfo:
    """Test get_schedule_display_info function for schedule visualization."""

    @patch('app.helpers.schedule_display._get_week_type_from_schedule')
    def test_get_schedule_display_info_playoff(self, mock_week_type, db, app, schedule):
        """
        GIVEN a playoff schedule entry
        WHEN get_schedule_display_info is called
        THEN it should return playoff display info
        """
        from app.helpers.schedule_display import get_schedule_display_info

        mock_week_type.return_value = 'PLAYOFF'

        result = get_schedule_display_info(schedule)

        assert result['type'] == 'playoff'
        assert result['title'] == 'Playoffs'
        assert result['subtitle'] == 'Teams TBD'
        assert result['css_class'] == 'playoff-week'

    @patch('app.helpers.schedule_display._get_week_type_from_schedule')
    def test_get_schedule_display_info_bonus(self, mock_week_type, db, app, schedule):
        """
        GIVEN a bonus week schedule entry
        WHEN get_schedule_display_info is called
        THEN it should return bonus week display info
        """
        from app.helpers.schedule_display import get_schedule_display_info

        mock_week_type.return_value = 'BONUS'

        result = get_schedule_display_info(schedule)

        assert result['type'] == 'bonus'
        assert result['title'] == 'Bonus Week'
        assert result['css_class'] == 'bonus-week'
        assert result['icon'] == 'ti-gift'

    @patch('app.helpers.schedule_display._get_week_type_from_schedule')
    def test_get_schedule_display_info_practice(self, mock_week_type, db, app, schedule):
        """
        GIVEN a practice session schedule entry
        WHEN get_schedule_display_info is called
        THEN it should return practice display info
        """
        from app.helpers.schedule_display import get_schedule_display_info

        mock_week_type.return_value = 'PRACTICE'

        result = get_schedule_display_info(schedule)

        assert result['type'] == 'practice'
        assert result['title'] == 'Practice Session'
        assert result['show_opponent'] is True
        assert result['css_class'] == 'practice-week'


# =============================================================================
# SCHEDULE DISPLAY - WEEK SUMMARY TESTS
# =============================================================================

@pytest.mark.unit
class TestGetWeekSummaryForDashboard:
    """Test get_week_summary_for_dashboard function."""

    def test_get_week_summary_empty_matches(self, db, app):
        """
        GIVEN no matches for a week
        WHEN get_week_summary_for_dashboard is called
        THEN it should return empty week summary
        """
        from app.helpers.schedule_display import get_week_summary_for_dashboard

        result = get_week_summary_for_dashboard(week_number=1, matches=[])

        assert result['type'] == 'empty'
        assert result['title'] == 'Week 1'
        assert result['matches'] == []

    def test_get_week_summary_regular_week(self, db, app, match):
        """
        GIVEN regular matches for a week
        WHEN get_week_summary_for_dashboard is called
        THEN it should return regular week summary
        """
        from app.helpers.schedule_display import get_week_summary_for_dashboard

        # Ensure match is regular type
        match.week_type = 'REGULAR'
        db.session.commit()

        result = get_week_summary_for_dashboard(week_number=1, matches=[match])

        assert result['type'] == 'regular'
        assert 'Regular Season' in result['title']
        assert result['css_class'] == 'regular-week'
        assert len(result['matches']) == 1


# =============================================================================
# SCHEDULE CONSTRAINT CHECKER TESTS
# =============================================================================

@pytest.mark.unit
class TestCheckScheduleConstraints:
    """Test schedule constraint checking static method."""

    def test_check_schedule_constraints_empty_schedule(self, db, app):
        """
        GIVEN an empty schedule
        WHEN check_schedule_constraints is called
        THEN it should report violations
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        result = AutoScheduleGenerator.check_schedule_constraints(
            matches=[],
            team_count=8,
            weeks_count=7
        )

        assert result['total_matches'] == 0
        assert result['expected_matches'] == 56  # 8 * 7
        assert result['all_constraints_satisfied'] is False

    def test_check_schedule_constraints_detects_pair_imbalance(self, db, app):
        """
        GIVEN a schedule where pairs don't appear twice
        WHEN check_schedule_constraints is called
        THEN it should detect C1 violations
        """
        from app.auto_schedule_generator import AutoScheduleGenerator

        # Create schedule with pair appearing only once
        matches = [
            {'home_team_id': 1, 'away_team_id': 2, 'week': 1, 'field': 'North', 'time': '08:20'},
        ]

        result = AutoScheduleGenerator.check_schedule_constraints(
            matches=matches,
            team_count=8,
            weeks_count=7
        )

        assert result['C1_double_round_robin'] is False
        assert len(result['violations']) > 0


# =============================================================================
# HELPER FUNCTIONS - OPPONENT NAME TESTS
# =============================================================================

@pytest.mark.unit
class TestGetOpponentName:
    """Test _get_opponent_name helper function."""

    def test_get_opponent_name_from_home_perspective(self, db, app, match, team, opponent_team):
        """
        GIVEN a match and home team perspective
        WHEN _get_opponent_name is called
        THEN it should return away team name
        """
        from app.helpers.schedule_display import _get_opponent_name

        match.home_team_id = team.id
        match.away_team_id = opponent_team.id
        db.session.commit()

        result = _get_opponent_name(match, team)

        assert result == opponent_team.name

    def test_get_opponent_name_from_away_perspective(self, db, app, match, team, opponent_team):
        """
        GIVEN a match and away team perspective
        WHEN _get_opponent_name is called
        THEN it should return home team name
        """
        from app.helpers.schedule_display import _get_opponent_name

        match.home_team_id = opponent_team.id
        match.away_team_id = team.id
        db.session.commit()

        result = _get_opponent_name(match, team)

        assert result == opponent_team.name

    def test_get_opponent_name_without_perspective(self, db, app, match, team, opponent_team):
        """
        GIVEN a match and no team perspective
        WHEN _get_opponent_name is called
        THEN it should return both team names
        """
        from app.helpers.schedule_display import _get_opponent_name

        match.home_team_id = team.id
        match.away_team_id = opponent_team.id
        db.session.commit()

        result = _get_opponent_name(match, team_perspective=None)

        assert team.name in result
        assert opponent_team.name in result
        assert 'vs' in result
