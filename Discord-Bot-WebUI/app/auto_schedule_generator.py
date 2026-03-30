# app/auto_schedule_generator.py

"""
Automatic Schedule Generator Module

This module provides functionality to generate randomized round-robin schedules
for soccer leagues with the following constraints:
- Teams play each other twice during regular season (once each, then repeating)
- Teams play 2 matches per day (back-to-back)
- Supports multiple fields (North, South, etc.)
- Configurable start times and match durations
- Ensures balanced scheduling across weeks
"""

import random
from datetime import datetime, timedelta, time, date
from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict
import logging

from app.models import (
    League, Team, AutoScheduleConfig, ScheduleTemplate, 
    Schedule, Match, WeekConfiguration, SeasonConfiguration
)

logger = logging.getLogger(__name__)


class ScheduleConstraintError(ValueError):
    """Raised when schedule constraints cannot be satisfied."""
    def __init__(self, violations):
        self.violations = violations
        super().__init__(f"Schedule constraint violations: {'; '.join(violations)}")


class AutoScheduleGenerator:
    """Generates randomized round-robin schedules for soccer leagues."""
    
    def __init__(self, league_id: int, session):
        """
        Initialize the schedule generator.
        
        Args:
            league_id: ID of the league to generate schedule for
            session: Database session
        """
        self.league_id = league_id
        self.session = session
        self.league = session.query(League).filter_by(id=league_id).first()
        if not self.league:
            raise ValueError(f"League with ID {league_id} not found")
        
        # Filter out placeholder teams (FUN WEEK, BYE, TST) - these are no longer real Team entities
        self.all_teams = list(self.league.teams)
        self.teams = [team for team in self.all_teams if team.name not in ['FUN WEEK', 'BYE', 'TST']]
        self.num_teams = len(self.teams)
        
        if self.num_teams < 2:
            raise ValueError("Need at least 2 teams to generate a schedule")
        
        # Create virtual placeholder teams for special weeks (not saved to database)
        self.placeholder_teams = self._create_virtual_placeholder_teams()
        
        self.config = None
        self.schedule_templates = []
        self.week_configurations = []
        self.season_config = None
        
        # Track team assignments for balancing
        self.team_field_count = defaultdict(lambda: defaultdict(int))  # team_id -> field -> count
        self.team_time_slots = defaultdict(list)  # team_id -> list of assigned times
        
    def _create_virtual_placeholder_teams(self) -> Dict[str, Team]:
        """
        Create virtual placeholder teams for special weeks that aren't saved to the database.
        These teams exist only for schedule generation purposes.
        
        Returns:
            Dictionary mapping placeholder names to virtual Team objects
        """
        placeholder_teams = {}
        
        # Create virtual Team objects for placeholders (negative IDs to avoid conflicts)
        virtual_id_counter = -1000
        
        for placeholder_name in ['FUN WEEK', 'BYE', 'TST']:
            # Check if placeholder already exists as a real team (for backward compatibility)
            existing_team = None
            for team in self.all_teams:
                if team.name == placeholder_name:
                    existing_team = team
                    break
            
            if existing_team:
                # Use existing team if found (backward compatibility)
                placeholder_teams[placeholder_name] = existing_team
                logger.info(f"Using existing placeholder team: {placeholder_name}")
            else:
                # Create virtual team (not saved to database)
                virtual_team = Team(
                    name=placeholder_name,
                    league_id=self.league_id,
                    id=virtual_id_counter  # Negative ID to avoid conflicts
                )
                placeholder_teams[placeholder_name] = virtual_team
                virtual_id_counter -= 1
                logger.info(f"Created virtual placeholder team: {placeholder_name}")
        
        return placeholder_teams
    
    def _get_team_by_id(self, team_id: int) -> Optional[Team]:
        """
        Get a team by ID, handling both real teams from database and virtual placeholder teams.
        
        Args:
            team_id: ID of the team to get
            
        Returns:
            Team object if found, None otherwise
        """
        # Check if it's a virtual placeholder team (negative ID)
        if team_id < 0:
            for placeholder_team in self.placeholder_teams.values():
                if placeholder_team.id == team_id:
                    return placeholder_team
            return None
        
        # Try to get from database for real teams
        return self.session.query(Team).filter_by(id=team_id).first()
        
    def set_config(self, start_time: time, match_duration_minutes: int = 70, 
                   weeks_count: int = 7, fields: str = "North,South") -> None:
        """
        Set configuration for schedule generation from wizard input.
        
        Args:
            start_time: When the first match of the day starts
            match_duration_minutes: Duration of each match in minutes
            weeks_count: Number of weeks in the regular season
            fields: Comma-separated field names
        """
        self.start_time = start_time
        self.match_duration_minutes = match_duration_minutes
        self.weeks_count = weeks_count
        self.fields = [field.strip().strip('{}') for field in fields.split(',')]
        
        logger.info(f"Schedule configuration set for {self.league.name}: start_time={start_time}, duration={match_duration_minutes}min, weeks={weeks_count}, fields={self.fields}")
        
        # Validate configuration for back-to-back scheduling
        if self.num_teams % 2 != 0:
            logger.warning(f"Odd number of teams ({self.num_teams}) may cause scheduling issues with back-to-back games")
        
        # Calculate expected matches per week
        expected_matches = self.num_teams  # Each team plays 2 games, so total matches = num_teams
        logger.info(f"Expected matches per week: {expected_matches} (with {self.num_teams} teams playing back-to-back)")
        
    def set_season_configuration(self, season_config: SeasonConfiguration) -> None:
        """
        Set the season configuration for the league.
        
        Args:
            season_config: SeasonConfiguration object with league settings
        """
        self.season_config = season_config
        
    def set_week_configurations(self, week_configs: List[Dict]) -> None:
        """
        Set week configurations for the schedule.
        
        Args:
            week_configs: List of dicts with keys: date, week_type, description
                         week_type can be 'REGULAR', 'FUN', 'TST', 'BYE'
        """
        self.week_configurations = []
        for i, config in enumerate(week_configs, 1):
            week_config = WeekConfiguration(
                league_id=self.league_id,
                week_date=config['date'],
                week_type=config['week_type'],
                week_order=i,
                description=config.get('description', ''),
                is_playoff_week=config.get('is_playoff_week', False),
                playoff_round=config.get('playoff_round', None),
                has_practice_session=config.get('has_practice_session', False),
                practice_game_number=config.get('practice_game_number', None)
            )
            self.week_configurations.append(week_config)
        
    def generate_round_robin_pairings(self) -> List[List[Tuple[int, int]]]:
        """
        Generate back-to-back round-robin pairings with proper constraint validation.

        Supports both 4-team and 8-team leagues:
        - 4 teams: Back-to-back with repeating round-robins
        - 8 teams: Double round-robin with full constraints

        Returns:
            List of weeks, where each week contains a list of (home_team_id, away_team_id) tuples
        """
        if self.num_teams == 4:
            return self._generate_4_team_pairings()
        elif self.num_teams == 8:
            return self._generate_8_team_pairings()
        else:
            raise ValueError(f"Scheduling requires 4 or 8 teams, got {self.num_teams}")

    def _generate_4_team_pairings(self) -> List[List[Tuple[int, int]]]:
        """
        Generate back-to-back pairings for 4 teams.

        Each week, each team plays 2 games (4 total matches per week).
        Uses a rotating pattern to ensure variety.
        """
        team_ids = [team.id for team in self.teams]
        A, B, C, D = team_ids[0], team_ids[1], team_ids[2], team_ids[3]

        # Define 3-week rotation pattern (covers all matchups twice = double round-robin)
        # Each week: 4 matches where each team plays twice
        base_pattern = [
            # Week pattern 1: A-B, C-D, A-C, B-D
            [(A, B), (C, D), (A, C), (B, D)],
            # Week pattern 2: A-D, B-C, B-A, D-C
            [(A, D), (B, C), (B, A), (D, C)],
            # Week pattern 3: C-A, D-B, D-A, C-B
            [(C, A), (D, B), (D, A), (C, B)],
        ]

        weekly_schedules = []
        for week in range(self.weeks_count):
            pattern_idx = week % len(base_pattern)
            week_matches = base_pattern[pattern_idx].copy()
            weekly_schedules.append(week_matches)
            logger.info(f"Generated week {week + 1} matches: {len(week_matches)} games")
            for i, (home, away) in enumerate(week_matches):
                logger.info(f"  Match {i + 1}: Team {home} vs Team {away}")

        return weekly_schedules

    def _generate_8_team_pairings(self) -> List[List[Tuple[int, int]]]:
        """
        Generate back-to-back double round-robin pairings for 8 teams.

        Uses a verified structural template with random team label permutation to satisfy:
        - C1: Each unordered pair appears exactly twice (once home/away, once reversed)
        - C2: Each team plays 2 games per Sunday in same window (back-to-back)
        - C3: No immediate rematch (no team plays same opponent in consecutive weeks)
        - C4: Each team: 7 home, 7 away games total
        - C5: Each team: ~7 North, ~7 South field assignments total
        - C6: Each team: 3 or 4 early-pairs and 4 or 3 late-pairs
        - C7: Every team plays all 7 opponents once before any repeats (complete single
              round-robin in first 7 games per team, no repeat until week 4)

        Returns:
            List of weeks, where each week contains a list of (home_team_id, away_team_id) tuples.
            Matches are ordered: [early_slot1_N, early_slot1_S, early_slot2_N, early_slot2_S,
                                  late_slot3_N, late_slot3_S, late_slot4_N, late_slot4_S]
        """
        if len(self.teams) != 8:
            raise ValueError("Premier League double round-robin requires exactly 8 teams")

        team_ids = [team.id for team in self.teams]

        # Apply random permutation for variety between seasons
        shuffled = random.sample(team_ids, len(team_ids))
        A, B, C, D, E, F, G, H = shuffled

        # Verified structural template: 7-week double round-robin
        # Each week has 8 matches split into early window (4 matches) and late window (4 matches)
        # Within each window, 4 teams play back-to-back (2 games each)
        #
        # Week ordering is chosen so that C7 is satisfied:
        # - Weeks 0-2: each team faces 6 unique opponents (no repeats)
        # - Week 3: each team's 7th unique opponent + first repeat
        #
        # C1: Each pair plays exactly twice (once each direction)
        # C3: No consecutive-week rematches (verified for this ordering)
        # C4: Each team has exactly 7 home, 7 away
        # Week ordering is [orig0, orig1, orig3, orig2, orig4, orig5, orig6]
        # Swapping original weeks 2 and 3 ensures C7: no repeat opponent before week 4
        raw_template = [
            # Week 0 (orig 0): Early={A,B,C,D}, Late={E,F,G,H}
            [(A, B), (C, D), (A, C), (B, D),
             (E, F), (G, H), (E, G), (F, H)],
            # Week 1 (orig 1): Early={A,B,E,F}, Late={C,D,G,H}
            [(A, E), (B, F), (A, F), (B, E),
             (C, G), (D, H), (C, H), (D, G)],
            # Week 2 (orig 3): Early={A,B,G,H}, Late={C,D,E,F}
            [(A, G), (B, H), (A, H), (B, G),
             (C, E), (D, F), (C, F), (D, E)],
            # Week 3 (orig 2): Early={A,B,C,D} reversed, Late={E,F,G,H} reversed
            [(B, A), (D, C), (A, D), (B, C),
             (F, E), (H, G), (E, H), (F, G)],
            # Week 4 (orig 4): Early={C,D,G,H}, Late={A,B,E,F}
            [(G, C), (H, D), (H, C), (G, D),
             (E, A), (F, B), (F, A), (E, B)],
            # Week 5 (orig 5): Early={C,D,E,F}, Late={A,B,G,H}
            [(E, C), (F, D), (F, C), (E, D),
             (G, A), (H, B), (H, A), (G, B)],
            # Week 6 (orig 6): Early={E,F,G,H}, Late={A,B,C,D}
            [(G, E), (H, F), (H, E), (G, F),
             (C, A), (D, B), (D, A), (C, B)],
        ]

        # Balance early/late windows across the season (C6)
        weeks_with_windows = self._balance_window_assignments(raw_template, team_ids)

        # Balance North/South field assignments within windows (C5)
        weeks = self._assign_fields_to_windows(weeks_with_windows, team_ids)

        # Validate all constraints
        self._validate_all_constraints(weeks, team_ids)

        # Log balance summary
        self._log_schedule_balance(weeks, team_ids)

        return weeks

    def _balance_window_assignments(self, weeks: List[List[Tuple[int, int]]],
                                      team_ids: List[int]) -> List[List[Tuple[int, int]]]:
        """
        For each week, optionally swap early and late windows to balance C6
        (each team gets ~3-4 early and ~4-3 late window appearances).

        The template already has valid window groups (positions 0-3 = early, 4-7 = late).
        We just decide whether to swap them for each week.
        """
        team_window_count = {tid: {'early': 0, 'late': 0} for tid in team_ids}
        result_weeks = []

        for week_matches in weeks:
            early_group = week_matches[:4]
            late_group = week_matches[4:]

            # Get teams in each group
            early_teams = set()
            for h, a in early_group:
                early_teams.add(h)
                early_teams.add(a)
            late_teams = set()
            for h, a in late_group:
                late_teams.add(h)
                late_teams.add(a)

            # Decide whether to swap: pick assignment that best balances C6
            early_deficit = sum(3.5 - team_window_count[t]['early'] for t in early_teams)
            late_as_early_deficit = sum(3.5 - team_window_count[t]['early'] for t in late_teams)

            if early_deficit >= late_as_early_deficit:
                # Keep as-is (current early group stays early)
                final_early, final_late = early_group, late_group
                final_early_teams, final_late_teams = early_teams, late_teams
            else:
                # Swap
                final_early, final_late = late_group, early_group
                final_early_teams, final_late_teams = late_teams, early_teams

            for t in final_early_teams:
                team_window_count[t]['early'] += 1
            for t in final_late_teams:
                team_window_count[t]['late'] += 1

            result_weeks.append(final_early + final_late)

        return result_weeks

    def _assign_fields_to_windows(self, weeks: List[List[Tuple[int, int]]],
                                    team_ids: List[int]) -> List[List[Tuple[int, int]]]:
        """
        Within each 4-match window, arrange matches into 2 time slots × 2 fields:
        [slot_N, slot_S, slot_N, slot_S]

        Balances North/South (C5) across the season using greedy assignment.

        Returns:
            Weeks with matches ordered: [e_s1_N, e_s1_S, e_s2_N, e_s2_S, l_s3_N, l_s3_S, l_s4_N, l_s4_S]
        """
        team_field_count = {tid: {'North': 0, 'South': 0} for tid in team_ids}
        result_weeks = []

        for week_matches in weeks:
            # Process early window (indices 0-3) and late window (indices 4-7) separately
            early = week_matches[:4]
            late = week_matches[4:]

            ordered_early = self._assign_fields_to_window_group(early, team_field_count)
            ordered_late = self._assign_fields_to_window_group(late, team_field_count)

            result_weeks.append(ordered_early + ordered_late)

        return result_weeks

    def _assign_fields_to_window_group(self, matches: List[Tuple[int, int]],
                                         team_field_count: Dict) -> List[Tuple[int, int]]:
        """
        Assign 4 matches in a window to 2 time slots × 2 fields (N/S).

        Each team in the window plays exactly 2 matches. We need to split
        4 matches into 2 pairs (slot 1 and slot 2), then assign N/S within each pair.

        Strategy: find the two pairs where no team appears in both matches of a pair
        (i.e., each pair is one match per team's two games). Then assign N/S greedily.

        Returns:
            [slot1_north, slot1_south, slot2_north, slot2_south]
        """
        # Find which teams are in this window
        teams_in_window = set()
        for h, a in matches:
            teams_in_window.add(h)
            teams_in_window.add(a)

        # Build team-to-match mapping
        team_matches = defaultdict(list)
        for i, (h, a) in enumerate(matches):
            team_matches[h].append(i)
            team_matches[a].append(i)

        # Find valid slot pairings: split 4 matches into 2 pairs of 2,
        # where each pair has no team in common (so different teams play in each slot)
        # Actually: each pair should have 4 distinct teams across its 2 matches
        # (2 matches × 2 teams = 4 teams, all different)
        from itertools import combinations

        valid_splits = []
        match_indices = list(range(4))
        for pair1 in combinations(match_indices, 2):
            pair2 = tuple(i for i in match_indices if i not in pair1)

            # Check pair1: all 4 teams in these 2 matches must be distinct
            p1_teams = set()
            for idx in pair1:
                p1_teams.add(matches[idx][0])
                p1_teams.add(matches[idx][1])

            p2_teams = set()
            for idx in pair2:
                p2_teams.add(matches[idx][0])
                p2_teams.add(matches[idx][1])

            if len(p1_teams) == 4 and len(p2_teams) == 4:
                valid_splits.append((list(pair1), list(pair2)))

        if not valid_splits:
            # Fallback: just use first two and last two
            valid_splits = [([0, 1], [2, 3])]

        # Pick the split - for now just use the first valid one
        slot1_indices, slot2_indices = valid_splits[0]

        slot1_matches = [matches[i] for i in slot1_indices]
        slot2_matches = [matches[i] for i in slot2_indices]

        # Assign North/South within each slot pair greedily
        ordered = []
        for slot_matches in [slot1_matches, slot2_matches]:
            m0, m1 = slot_matches

            # Calculate "north deficit" for each match's teams
            # Higher deficit = teams need more North games
            def north_need(match):
                h, a = match
                target = 7  # Target 7 North out of 14 total
                h_need = target - team_field_count[h].get('North', 0)
                a_need = target - team_field_count[a].get('North', 0)
                return h_need + a_need

            need0 = north_need(m0)
            need1 = north_need(m1)

            if need0 > need1:
                north_match, south_match = m0, m1
            elif need1 > need0:
                north_match, south_match = m1, m0
            else:
                # Tie: randomize
                if random.choice([True, False]):
                    north_match, south_match = m0, m1
                else:
                    north_match, south_match = m1, m0

            # Update field counts
            for team in [north_match[0], north_match[1]]:
                team_field_count[team]['North'] += 1
            for team in [south_match[0], south_match[1]]:
                team_field_count[team]['South'] += 1

            ordered.extend([north_match, south_match])

        return ordered

    def _validate_all_constraints(self, weeks: List[List[Tuple[int, int]]],
                                    team_ids: List[int]) -> None:
        """
        Validate all constraints C1-C7. Raises ScheduleConstraintError on failure.
        """
        violations = []

        # Flatten all matches
        all_matches = [(w, h, a) for w, week in enumerate(weeks) for h, a in week]

        # C1: Each unordered pair appears exactly twice
        pair_count = defaultdict(int)
        for _, h, a in all_matches:
            key = self._get_pair_key(h, a)
            pair_count[key] += 1

        for key, count in pair_count.items():
            if count != 2:
                violations.append(f"C1: Pair {key} plays {count} times (expected 2)")

        # C2: Each team plays exactly 2 games per week
        for w, week in enumerate(weeks):
            games_per_team = defaultdict(int)
            for h, a in week:
                games_per_team[h] += 1
                games_per_team[a] += 1
            for tid in team_ids:
                if games_per_team[tid] != 2:
                    violations.append(f"C2: Team {tid} plays {games_per_team[tid]} games in week {w+1}")

        # C3: No consecutive-week rematches
        for w in range(1, len(weeks)):
            prev_opp = defaultdict(set)
            for h, a in weeks[w - 1]:
                prev_opp[h].add(a)
                prev_opp[a].add(h)
            curr_opp = defaultdict(set)
            for h, a in weeks[w]:
                curr_opp[h].add(a)
                curr_opp[a].add(h)
            for tid in team_ids:
                common = prev_opp[tid] & curr_opp[tid]
                if common:
                    violations.append(f"C3: Team {tid} plays {common} in weeks {w} and {w+1}")

        # C4: 7 home / 7 away per team
        home_count = defaultdict(int)
        away_count = defaultdict(int)
        for _, h, a in all_matches:
            home_count[h] += 1
            away_count[a] += 1
        for tid in team_ids:
            if home_count[tid] != 7 or away_count[tid] != 7:
                violations.append(f"C4: Team {tid} has {home_count[tid]}H/{away_count[tid]}A (expected 7/7)")

        # C5: Field balance - check positional encoding
        # Positions 0,2,4,6 = North; 1,3,5,7 = South
        north_count = defaultdict(int)
        south_count = defaultdict(int)
        for week in weeks:
            for i, (h, a) in enumerate(week):
                if i % 2 == 0:  # North
                    north_count[h] += 1
                    north_count[a] += 1
                else:  # South
                    south_count[h] += 1
                    south_count[a] += 1
        for tid in team_ids:
            n, s = north_count.get(tid, 0), south_count.get(tid, 0)
            if abs(n - s) > 2:  # Allow ±1 from perfect 7/7
                violations.append(f"C5: Team {tid} has {n}N/{s}S (max deviation ±2)")

        # C6: Window balance - early (positions 0-3) vs late (positions 4-7)
        early_count = defaultdict(int)
        late_count = defaultdict(int)
        for week in weeks:
            for i, (h, a) in enumerate(week):
                if i < 4:
                    early_count[h] += 1
                    early_count[a] += 1
                else:
                    late_count[h] += 1
                    late_count[a] += 1
        for tid in team_ids:
            e, l = early_count.get(tid, 0), late_count.get(tid, 0)
            if abs(e - l) > 2:
                violations.append(f"C6: Team {tid} has {e} early/{l} late (max deviation ±2)")

        # C7: Complete single round-robin before repeats
        # No opponent should appear in two DIFFERENT weeks within weeks 0-2.
        # The earliest a repeat can occur is week 3 (the 4th week), which is acceptable
        # since 7 opponents across 4 weeks (8 games) requires exactly one repeat in week 4.
        for tid in team_ids:
            opponent_first_week = {}  # opponent -> first week index they were played
            for w_idx, week in enumerate(weeks):
                week_opponents = []
                for h, a in week:
                    if h == tid:
                        week_opponents.append(a)
                    elif a == tid:
                        week_opponents.append(h)

                for opp in week_opponents:
                    if opp in opponent_first_week:
                        first_week = opponent_first_week[opp]
                        if first_week < 3 and w_idx < 3:
                            # Repeat within the first 3 weeks (games 1-6)
                            violations.append(
                                f"C7: Team {tid} plays {opp} in week {first_week+1} "
                                f"and week {w_idx+1} (no repeats before week 4)"
                            )
                    else:
                        opponent_first_week[opp] = w_idx

            # Also verify all 7 opponents are covered by end of week 3 (7th opponent can be in week 4)
            if len(opponent_first_week) < len(team_ids) - 1:
                violations.append(
                    f"C7: Team {tid} only plays {len(opponent_first_week)} "
                    f"unique opponents (expected {len(team_ids) - 1})"
                )

        if violations:
            raise ScheduleConstraintError(violations)

    def _log_schedule_balance(self, weeks: List[List[Tuple[int, int]]], team_ids: List[int]) -> None:
        """Log balance statistics for the generated schedule."""
        north = defaultdict(int)
        south = defaultdict(int)
        early = defaultdict(int)
        late = defaultdict(int)
        home = defaultdict(int)
        away = defaultdict(int)

        for week in weeks:
            for i, (h, a) in enumerate(week):
                home[h] += 1
                away[a] += 1
                if i % 2 == 0:
                    north[h] += 1
                    north[a] += 1
                else:
                    south[h] += 1
                    south[a] += 1
                if i < 4:
                    early[h] += 1
                    early[a] += 1
                else:
                    late[h] += 1
                    late[a] += 1

        logger.info("Schedule balance summary:")
        for tid in sorted(team_ids):
            logger.info(
                f"  Team {tid}: {home[tid]}H/{away[tid]}A, "
                f"{north[tid]}N/{south[tid]}S, "
                f"{early[tid]}E/{late[tid]}L"
            )
    
    def _get_pair_key(self, team1_id: int, team2_id: int) -> str:
        """Get a consistent key for team pairs (unordered)."""
        return f"{min(team1_id, team2_id)}_{max(team1_id, team2_id)}"
    
    def _validate_week_constraints(self, week_matches: List[Tuple[int, int]], 
                                 team_ids: List[int], last_week_opponents: Dict[int, set]) -> bool:
        """
        Validate constraints for a single week.
        
        Args:
            week_matches: Matches for this week
            team_ids: All team IDs
            last_week_opponents: Teams each team played last week
            
        Returns:
            True if constraints are satisfied
        """
        # Check C2: Each team plays exactly 2 games
        team_game_count = {team_id: 0 for team_id in team_ids}
        for home_id, away_id in week_matches:
            team_game_count[home_id] += 1
            team_game_count[away_id] += 1
        
        if not all(count == 2 for count in team_game_count.values()):
            logger.warning("C2 violation: Not all teams play exactly 2 games this week")
            return False
        
        # Check C3: No immediate rematch
        for home_id, away_id in week_matches:
            if away_id in last_week_opponents.get(home_id, set()):
                logger.warning(f"C3 violation: Teams {home_id} and {away_id} played last week")
                return False
        
        return True
    
    def _validate_final_schedule(self, weekly_schedules: List[List[Tuple[int, int]]],
                               team_ids: List[int], home_away_count: Dict, pair_count: Dict) -> None:
        """
        Validate the entire schedule against all constraints.
        Raises ScheduleConstraintError if any violations are found.

        Args:
            weekly_schedules: Complete schedule
            team_ids: All team IDs
            home_away_count: Home/away game counts per team
            pair_count: Number of times each pair has played
        """
        logger.info("Validating final schedule constraints...")

        violations = []

        # C1: Double round-robin - each pair plays exactly twice
        for pair_key, count in pair_count.items():
            if count != 2:
                violations.append(f"C1: Pair {pair_key}: {count} games (should be 2)")

        # C4: Home/away balance - each team should have 7 home, 7 away
        for team_id in team_ids:
            home_count = home_away_count[team_id]['home']
            away_count = home_away_count[team_id]['away']
            if home_count != 7 or away_count != 7:
                violations.append(f"C4: Team {team_id} has {home_count}H/{away_count}A (should be 7H/7A)")

        # Total match count validation
        total_matches = sum(len(week) for week in weekly_schedules)
        expected_matches = len(team_ids) * 7  # 8 teams × 7 weeks × 2 games ÷ 2

        if total_matches != expected_matches:
            violations.append(f"Total matches: {total_matches} (expected {expected_matches})")

        if violations:
            logger.error(f"Schedule validation failed: {violations}")
            raise ScheduleConstraintError(violations)

        logger.info("Schedule validation complete. No violations found.")
    
    def generate_schedule_templates(self, week_configs: List = None) -> List[ScheduleTemplate]:
        """
        Generate schedule templates for the entire season including special weeks.
        
        Args:
            week_configs: List of WeekConfiguration objects or dict configurations
            
        Returns:
            List of ScheduleTemplate objects
        """
        if not self.start_time:
            raise ValueError("Configuration not set. Call set_config() first.")
        
        # Handle both WeekConfiguration objects and dict configurations
        if week_configs:
            logger.info(f"Week configs provided: {len(week_configs)} configurations")
            if isinstance(week_configs[0], dict):
                # Legacy dict format - convert to WeekConfiguration objects
                logger.info("Converting dict format week configs to WeekConfiguration objects")
                self.set_week_configurations(week_configs)
            else:
                # WeekConfiguration objects - use directly
                logger.info("Using WeekConfiguration objects directly")
                self.week_configurations = week_configs
        else:
            # No week configs provided - get from database
            logger.info("No week configs provided - querying database")
            self.week_configurations = self.session.query(WeekConfiguration).filter_by(
                league_id=self.league_id
            ).order_by(WeekConfiguration.week_order).all()
            logger.info(f"Found {len(self.week_configurations)} week configurations in database")
        
        # Log all week configurations for debugging
        logger.info(f"Final week configurations for league {self.league_id}:")
        for i, config in enumerate(self.week_configurations):
            logger.info(f"  Week {config.week_order}: {config.week_date} - Type: {config.week_type} - Playoff: {config.is_playoff_week}")
        
        # Generate round-robin pairings for regular weeks only
        weekly_pairings = self.generate_round_robin_pairings()
        
        templates = []
        regular_week_index = 0
        
        # Process each configured week
        for week_config in self.week_configurations:
            week_date = week_config.week_date
            week_type = week_config.week_type
            week_order = week_config.week_order
            
            logger.info(f"Processing Week {week_order} ({week_date}): Type={week_type}")
            
            if week_type == 'REGULAR':
                logger.info(f"  → Generating regular matches for week {week_order}")
                # Generate normal matches for this week
                if regular_week_index < len(weekly_pairings):
                    week_matches = weekly_pairings[regular_week_index]
                    regular_week_index += 1
                    
                    # Check if this week has practice sessions (Classic weeks 1 and 3)
                    has_practice = week_config.has_practice_session
                    
                    if has_practice and self.league.name == 'Classic':
                        # For Classic practice weeks, generate practice session at first time slot
                        # and regular matches at second time slot only
                        
                        # Generate time slots to get proper times
                        time_slots = self._generate_time_slots()
                        
                        # First, generate practice sessions for both fields at first time slot
                        practice_time = time_slots[0] if time_slots else self.start_time
                        
                        # Create PRACTICE entries for both fields
                        for field in ['North', 'South']:
                            # Create a special practice template
                            # Using same team ID for home and away indicates special event
                            template = ScheduleTemplate(
                                league_id=self.league_id,
                                week_number=week_order,
                                home_team_id=self.teams[0].id,  # Placeholder
                                away_team_id=self.teams[0].id,  # Same = special event
                                scheduled_date=week_date,
                                scheduled_time=practice_time,
                                field_name=field,
                                match_order=1,
                                week_type='PRACTICE',
                                is_special_week=True,
                                is_practice_game=True
                            )
                            templates.append(template)
                        
                        # Then generate regular matches at second time slot only
                        match_time = time_slots[1] if len(time_slots) > 1 else time_slots[0]
                        
                        # For practice weeks, only schedule half the matches (2 teams per field)
                        # This matches the example where only 2 matches are played at 1:50 PM
                        if len(week_matches) >= 2:
                            # First match pair on North
                            template = ScheduleTemplate(
                                league_id=self.league_id,
                                week_number=week_order,
                                home_team_id=week_matches[0][0],
                                away_team_id=week_matches[0][1],
                                scheduled_date=week_date,
                                scheduled_time=match_time,
                                field_name='North',
                                match_order=2,
                                week_type='REGULAR',
                                is_special_week=False,
                                is_practice_game=False
                            )
                            templates.append(template)
                            
                            # Second match pair on South
                            template = ScheduleTemplate(
                                league_id=self.league_id,
                                week_number=week_order,
                                home_team_id=week_matches[1][0],
                                away_team_id=week_matches[1][1],
                                scheduled_date=week_date,
                                scheduled_time=match_time,
                                field_name='South',
                                match_order=2,
                                week_type='REGULAR',
                                is_special_week=False,
                                is_practice_game=False
                            )
                            templates.append(template)
                    else:
                        # Regular week scheduling (no practice)
                        time_slots = self._generate_time_slots()
                        field_assignments = self._assign_matches_to_fields(week_matches, time_slots)
                        
                        for match_info in field_assignments:
                            home_team_id, away_team_id, match_time, field_name, match_order = match_info
                            
                            template = ScheduleTemplate(
                                league_id=self.league_id,
                                week_number=week_order,
                                home_team_id=home_team_id,
                                away_team_id=away_team_id,
                                scheduled_date=week_date,
                                scheduled_time=match_time,
                                field_name=field_name,
                                match_order=match_order,
                                week_type='REGULAR',
                                is_special_week=False,
                                is_practice_game=False
                            )
                            templates.append(template)
                        
            elif week_type == 'PLAYOFF':
                logger.info(f"  → Generating playoff week placeholders for week {week_order}")
                # Generate playoff week placeholders (to be filled in later)
                playoff_templates = self._generate_playoff_week_templates(
                    week_date, week_order, week_config.playoff_round
                )
                templates.extend(playoff_templates)
                logger.info(f"  → Added {len(playoff_templates)} playoff templates")
                
            elif week_type == 'MIXED':
                logger.info(f"  → Generating mixed week templates for week {week_order}")
                # MIXED weeks: Playoffs for Premier, Regular season for Classic
                if self.league.name.lower() == 'premier':
                    logger.info(f"  → Premier league - generating playoff templates")
                    playoff_templates = self._generate_playoff_week_templates(
                        week_date, week_order, week_config.playoff_round
                    )
                    templates.extend(playoff_templates)
                    logger.info(f"  → Added {len(playoff_templates)} playoff templates")
                elif self.league.name.lower() == 'classic':
                    logger.info(f"  → Classic league - generating regular season templates")
                    # Generate regular season matches for Classic during mixed week
                    # Use the same logic as REGULAR weeks
                    if regular_week_index < len(weekly_pairings):
                        week_matches = weekly_pairings[regular_week_index]
                        regular_week_index += 1
                        
                        # Regular week scheduling (no practice for mixed weeks)
                        time_slots = self._generate_time_slots()
                        field_assignments = self._assign_matches_to_fields(week_matches, time_slots)
                        
                        for match_info in field_assignments:
                            home_team_id, away_team_id, match_time, field_name, match_order = match_info
                            
                            template = ScheduleTemplate(
                                league_id=self.league_id,
                                week_number=week_order,
                                home_team_id=home_team_id,
                                away_team_id=away_team_id,
                                scheduled_date=week_date,
                                scheduled_time=match_time,
                                field_name=field_name,
                                match_order=match_order,
                                week_type='REGULAR',
                                is_special_week=False,
                                is_practice_game=False
                            )
                            templates.append(template)
                else:
                    logger.warning(f"  → Unknown league type for MIXED week: {self.league.name}")
                
            elif week_type == 'PRACTICE':
                logger.info(f"  → Generating PRACTICE week templates for week {week_order}")
                # PRACTICE weeks: Practice session at first time slot, then real matches
                if regular_week_index < len(weekly_pairings):
                    week_matches = weekly_pairings[regular_week_index]
                    regular_week_index += 1

                    time_slots = self._generate_time_slots()

                    # First, generate practice sessions for both fields at first time slot
                    practice_time = time_slots[0] if time_slots else self.start_time

                    # Create PRACTICE entries for both fields
                    for field_idx, field in enumerate(self.fields[:2]):  # North and South
                        template = ScheduleTemplate(
                            league_id=self.league_id,
                            week_number=week_order,
                            home_team_id=self.teams[0].id,  # Placeholder
                            away_team_id=self.teams[0].id,  # Same = special event
                            scheduled_date=week_date,
                            scheduled_time=practice_time,
                            field_name=field,
                            match_order=field_idx + 1,
                            week_type='PRACTICE',
                            is_special_week=True,
                            is_practice_game=True
                        )
                        templates.append(template)

                    # Then generate regular matches at second time slot
                    match_time = time_slots[1] if len(time_slots) > 1 else time_slots[0]

                    # For practice weeks, schedule matches at second time slot
                    match_order = 3  # After the 2 practice entries
                    for i, (home_id, away_id) in enumerate(week_matches[:2]):  # 2 matches for 4 teams
                        field_name = self.fields[i % len(self.fields)]
                        template = ScheduleTemplate(
                            league_id=self.league_id,
                            week_number=week_order,
                            home_team_id=home_id,
                            away_team_id=away_id,
                            scheduled_date=week_date,
                            scheduled_time=match_time,
                            field_name=field_name,
                            match_order=match_order + i,
                            week_type='REGULAR',  # Real matches have REGULAR type, even in practice weeks
                            is_special_week=False,
                            is_practice_game=False  # These are real matches, just in a practice week
                        )
                        templates.append(template)

                    logger.info(f"  → Added 2 practice slots + {min(2, len(week_matches))} matches for PRACTICE week")
                else:
                    logger.warning(f"  → No more pairings available for PRACTICE week {week_order}")

            elif week_type in ['FUN', 'TST', 'BYE', 'BONUS']:
                logger.info(f"  → Generating special week templates for {week_type} week {week_order}")
                # Generate special week matches
                special_templates = self._generate_special_week_templates(
                    week_type, week_date, week_order
                )
                templates.extend(special_templates)
                logger.info(f"  → Added {len(special_templates)} special week templates")
            else:
                logger.warning(f"  → Unknown week type '{week_type}' for week {week_order} - skipping")
        
        return templates
    
    def _generate_playoff_week_templates(self, week_date: date, week_order: int, playoff_round: int) -> List[ScheduleTemplate]:
        """
        Generate playoff week templates with real placeholder teams for later assignment.
        
        Creates the full match structure (2 back-to-back games per team) using the first
        real team as a placeholder. Admins can later edit these to assign actual teams
        based on regular season standings.
        
        Args:
            week_date: Date of the playoff week
            week_order: Order of the week in the season
            playoff_round: Round number of the playoffs (1, 2, etc.)
            
        Returns:
            List of ScheduleTemplate objects with real placeholder teams
        """
        templates = []
        
        if not self.teams:
            logger.warning(f"No teams available for playoff structure in league {self.league_id}")
            return templates
        
        # Use time slots for playoff structure
        time_slots = self._generate_time_slots()
        event_time = time_slots[0] if time_slots else time(10, 0)  # Default to 10:00 AM
        
        # For playoff weeks, create a single entry per team showing "Playoff Week!"
        # This is similar to how TST/FUN weeks work but for playoffs
        for i, team in enumerate(self.teams):
            field_name = self.fields[i % len(self.fields)]
            
            template = ScheduleTemplate(
                league_id=self.league_id,
                week_number=week_order,
                home_team_id=team.id,
                away_team_id=team.id,  # Same team = special event, shows as "Playoff Week!"
                scheduled_date=week_date,
                scheduled_time=event_time,
                field_name=field_name,
                match_order=1,
                week_type='PLAYOFF',
                is_special_week=True,  # Mark playoff weeks as special like TST/FUN
                is_playoff_game=True,
                playoff_round=playoff_round
            )
            templates.append(template)
        
        logger.info(f"Generated {len(templates)} playoff placeholder templates for round {playoff_round}")
        return templates
    
    def _generate_special_week_templates(self, week_type: str, week_date: date, week_order: int) -> List[ScheduleTemplate]:
        """
        Generate schedule templates for special weeks (FUN, TST, BYE).
        
        These are division-wide events rather than individual matches, so each team
        gets a single entry showing "TST Week!", "Fun Week!", or "BYE Week!" instead
        of duplicate "vs" matches.
        
        Args:
            week_type: Type of special week
            week_date: Date of the week
            week_order: Order of the week in the season
            
        Returns:
            List of ScheduleTemplate objects
        """
        templates = []
        
        # Use a single time slot for special week events (whole day events)
        time_slots = self._generate_time_slots()
        event_time = time_slots[0] if time_slots else time(10, 0)  # Default to 10:00 AM
        
        if week_type == 'BYE':
            # For BYE weeks, create a single entry per team showing "BYE Week!"
            for i, team in enumerate(self.teams):
                field_name = self.fields[i % len(self.fields)]
                
                template = ScheduleTemplate(
                    league_id=self.league_id,
                    week_number=week_order,
                    home_team_id=team.id,
                    away_team_id=team.id,  # Same team = special event, not a match
                    scheduled_date=week_date,
                    scheduled_time=event_time,
                    field_name=field_name,
                    match_order=1,
                    week_type='BYE',
                    is_special_week=True
                )
                templates.append(template)
                    
        elif week_type == 'FUN':
            # For FUN weeks, create a single entry per team showing "Fun Week!"
            for i, team in enumerate(self.teams):
                field_name = self.fields[i % len(self.fields)]
                
                template = ScheduleTemplate(
                    league_id=self.league_id,
                    week_number=week_order,
                    home_team_id=team.id,
                    away_team_id=team.id,  # Same team = special event, not a match
                    scheduled_date=week_date,
                    scheduled_time=event_time,
                    field_name=field_name,
                    match_order=1,
                    week_type='FUN',
                    is_special_week=True
                )
                templates.append(template)
                    
        elif week_type == 'TST':
            # For TST weeks, create a single entry per team showing "TST Week!"
            for i, team in enumerate(self.teams):
                field_name = self.fields[i % len(self.fields)]
                
                template = ScheduleTemplate(
                    league_id=self.league_id,
                    week_number=week_order,
                    home_team_id=team.id,
                    away_team_id=team.id,  # Same team = special event, not a match
                    scheduled_date=week_date,
                    scheduled_time=event_time,
                    field_name=field_name,
                    match_order=1,
                    week_type='TST',
                    is_special_week=True
                )
                templates.append(template)
                    
        elif week_type == 'BONUS':
            # For BONUS weeks, create a single entry per team showing "Bonus Week!"
            for i, team in enumerate(self.teams):
                field_name = self.fields[i % len(self.fields)]
                
                template = ScheduleTemplate(
                    league_id=self.league_id,
                    week_number=week_order,
                    home_team_id=team.id,
                    away_team_id=team.id,  # Same team = special event, not a match
                    scheduled_date=week_date,
                    scheduled_time=event_time,
                    field_name=field_name,
                    match_order=1,
                    week_type='BONUS',
                    is_special_week=True
                )
                templates.append(template)
        
        return templates
    
    def _generate_time_slots(self) -> List[time]:
        """
        Generate time slots for back-to-back matches based on league specification.
        
        Premier League: 08:20, 09:30, 10:40, 11:50 (spec times)
        Classic League: 13:10, 14:10 (or configured)
        
        Returns:
            List of time objects for each match slot
        """
        time_slots = []
        
        if self.league.name.lower() == 'premier':
            # Fixed Premier League times per specification
            time_slots = [
                time(8, 20),   # Early window slot 1
                time(9, 30),   # Early window slot 2  
                time(10, 40),  # Late window slot 1
                time(11, 50)   # Late window slot 2
            ]
            logger.info(f"Using Premier League specification times: {[str(t) for t in time_slots]}")
        elif self.league.name.lower() == 'classic':
            # Fixed Classic League times per specification
            time_slots = [
                time(13, 10),  # 1:10 PM - First time slot
                time(14, 20)   # 2:20 PM - Second time slot (back-to-back)
            ]
            logger.info(f"Using Classic League specification times: {[str(t) for t in time_slots]}")
        else:
            # General case - use configured times
            start_time = self.start_time or time(8, 0)
            current_time = datetime.combine(date.today(), start_time)
            
            num_time_slots = self.num_teams // 2
            for i in range(num_time_slots):
                time_slots.append(current_time.time())
                current_time += timedelta(minutes=self.match_duration_minutes)
        
        return time_slots
    
    def _assign_matches_to_fields(self, matches: List[Tuple[int, int]],
                                 time_slots: List[time]) -> List[Tuple[int, int, time, str, int]]:
        """
        Assign matches to time slots and fields.

        Supports both Premier (8 teams, 8 matches, 4 time slots) and Classic (4 teams, 4 matches, 2 time slots).

        Premier League pattern (8 teams, 4 time slots):
        08:20 - Slot 1: North & South (concurrent)
        09:30 - Slot 2: North & South (back-to-back with slot 1)
        10:40 - Slot 3: North & South (concurrent)
        11:50 - Slot 4: North & South (back-to-back with slot 3)

        Classic League pattern (4 teams, 2 time slots):
        13:10 - Slot 1: North & South (concurrent)
        14:20 - Slot 2: North & South (back-to-back with slot 1)

        Args:
            matches: List of (home_team_id, away_team_id) tuples
            time_slots: List of time objects

        Returns:
            List of (home_team_id, away_team_id, time, field, match_order) tuples
        """
        assignments = []

        # Handle Classic League (4 matches, 2 time slots)
        if len(matches) == 4 and len(time_slots) == 2:
            logger.info(f"Using Classic League assignment pattern (4 matches, 2 time slots)")
            # Classic League field assignment pattern:
            # Slot 1 (13:10): matches[0] -> North, matches[1] -> South
            # Slot 2 (14:20): matches[2] -> North, matches[3] -> South

            for i in range(0, 4, 2):
                time_slot_index = i // 2  # 0,1 for the 2 time slots
                current_time = time_slots[time_slot_index]

                # Assign first match to North field
                if i < len(matches):
                    home_team_1, away_team_1 = matches[i]
                    assignments.append((home_team_1, away_team_1, current_time, "North", time_slot_index + 1))

                # Assign second match to South field
                if i + 1 < len(matches):
                    home_team_2, away_team_2 = matches[i + 1]
                    assignments.append((home_team_2, away_team_2, current_time, "South", time_slot_index + 1))

            logger.info(f"Assigned {len(assignments)} Classic League matches:")
            for assignment in assignments:
                home, away, time_slot, field, order = assignment
                logger.info(f"  {time_slot} {field}: Team {home} vs Team {away}")

            return assignments

        # Handle Premier League (8 matches, 4 time slots)
        if len(matches) == 8 and len(time_slots) == 4:
            logger.info(f"Using Premier League assignment pattern (8 matches, 4 time slots)")
            # Premier League field assignment pattern:
            # Slot 1 (08:20): matches[0] -> North, matches[1] -> South
            # Slot 2 (09:30): matches[2] -> North, matches[3] -> South
            # Slot 3 (10:40): matches[4] -> North, matches[5] -> South
            # Slot 4 (11:50): matches[6] -> North, matches[7] -> South

            for i in range(0, 8, 2):
                time_slot_index = i // 2  # 0,1,2,3 for the 4 time slots
                current_time = time_slots[time_slot_index]

                # Assign first match to North field
                if i < len(matches):
                    home_team_1, away_team_1 = matches[i]
                    assignments.append((home_team_1, away_team_1, current_time, "North", time_slot_index + 1))

                # Assign second match to South field
                if i + 1 < len(matches):
                    home_team_2, away_team_2 = matches[i + 1]
                    assignments.append((home_team_2, away_team_2, current_time, "South", time_slot_index + 1))

            logger.info(f"Assigned {len(assignments)} Premier League matches:")
            for assignment in assignments:
                home, away, time_slot, field, order = assignment
                logger.info(f"  {time_slot} {field}: Team {home} vs Team {away}")

            return assignments

        # Fallback: generic assignment for other configurations
        logger.warning(f"Using fallback assignment pattern ({len(matches)} matches, {len(time_slots)} time slots)")
        match_order = 1
        for i, (home_id, away_id) in enumerate(matches):
            time_slot_index = i // 2  # 2 matches per time slot
            if time_slot_index < len(time_slots):
                current_time = time_slots[time_slot_index]
                field = "North" if i % 2 == 0 else "South"
                assignments.append((home_id, away_id, current_time, field, match_order))
                match_order += 1

        return assignments
    
    def save_templates(self, templates: List[ScheduleTemplate]) -> None:
        """
        Save schedule templates to the database.
        
        Args:
            templates: List of ScheduleTemplate objects to save
        """
        for template in templates:
            self.session.add(template)
        self.session.commit()
    
    def commit_templates_to_schedule(self, template_ids: List[int] = None) -> None:
        """
        Convert schedule templates to actual schedule entries and matches.
        
        Args:
            template_ids: Optional list of specific template IDs to commit.
                         If None, commits all uncommitted templates for this league.
        """
        if template_ids:
            templates = self.session.query(ScheduleTemplate).filter(
                ScheduleTemplate.id.in_(template_ids)
            ).all()
        else:
            templates = self.session.query(ScheduleTemplate).filter_by(
                league_id=self.league_id,
                is_committed=False
            ).all()
        
        from app.schedule_routes import ScheduleManager
        schedule_manager = ScheduleManager(self.session)
        
        for template in templates:
            # Create match using the existing schedule manager
            match_data = {
                'date': template.scheduled_date.strftime('%Y-%m-%d'),
                'time': template.scheduled_time.strftime('%H:%M'),
                'location': template.field_name,
                'team_a': template.home_team_id,
                'team_b': template.away_team_id,
                'week': str(template.week_number),
                'season_id': self.season_id,
                # Add special week information from template
                'week_type': template.week_type,
                'is_special_week': template.is_special_week,
                'is_playoff_game': template.is_playoff_game,
                'playoff_round': template.playoff_round
            }
            schedule_manager.create_match(match_data)
            
            # Mark template as committed
            template.is_committed = True
        
        self.session.commit()
    
    def delete_templates(self, template_ids: List[int] = None) -> None:
        """
        Delete schedule templates.
        
        Args:
            template_ids: Optional list of specific template IDs to delete.
                         If None, deletes all uncommitted templates for this league.
        """
        if template_ids:
            templates = self.session.query(ScheduleTemplate).filter(
                ScheduleTemplate.id.in_(template_ids)
            ).all()
        else:
            templates = self.session.query(ScheduleTemplate).filter_by(
                league_id=self.league_id,
                is_committed=False
            ).all()
        
        for template in templates:
            self.session.delete(template)
        
        self.session.commit()
    
    def get_templates_preview(self) -> Dict[str, List[Dict]]:
        """
        Get a preview of generated templates organized by week.
        
        Returns:
            Dictionary with week numbers as keys and lists of match info as values
        """
        templates = self.session.query(ScheduleTemplate).filter_by(
            league_id=self.league_id,
            is_committed=False
        ).order_by(ScheduleTemplate.week_number, ScheduleTemplate.scheduled_time).all()
        
        preview = defaultdict(list)
        
        for template in templates:
            # Handle both real teams and virtual placeholder teams
            home_team = self._get_team_by_id(template.home_team_id)
            away_team = self._get_team_by_id(template.away_team_id)
            
            match_info = {
                'id': template.id,
                'home_team': home_team.name if home_team else 'Unknown',
                'away_team': away_team.name if away_team else 'Unknown',
                'home_team_id': template.home_team_id,
                'away_team_id': template.away_team_id,
                'time': template.scheduled_time.strftime('%H:%M'),
                'field': template.field_name,
                'match_order': template.match_order,
                'date': template.scheduled_date.strftime('%Y-%m-%d'),
                'week_type': template.week_type,
                'is_special_week': template.is_special_week
            }
            
            preview[f"Week {template.week_number}"].append(match_info)
        
        return dict(preview)
    
    @staticmethod
    def create_default_season_configuration(league_id: int, league_type: str) -> SeasonConfiguration:
        """
        Create a default season configuration based on league type.
        
        Args:
            league_id: ID of the league
            league_type: Type of league (PREMIER, CLASSIC, ECS_FC)
            
        Returns:
            SeasonConfiguration object with appropriate defaults
        """
        if league_type.upper() == 'PREMIER':
            return SeasonConfiguration(
                league_id=league_id,
                league_type='PREMIER',
                regular_season_weeks=7,
                playoff_weeks=2,
                has_fun_week=True,
                has_tst_week=True,
                has_bonus_week=True,
                has_practice_sessions=False,
                practice_weeks=None,
                practice_game_number=1
            )
        elif league_type.upper() == 'CLASSIC':
            return SeasonConfiguration(
                league_id=league_id,
                league_type='CLASSIC',
                regular_season_weeks=8,
                playoff_weeks=1,
                has_fun_week=False,
                has_tst_week=False,
                has_bonus_week=False,
                has_practice_sessions=False,  # Default to False, will be set by wizard
                practice_weeks=None,  # Will be set by wizard
                practice_game_number=1
            )
        elif league_type.upper() == 'ECS_FC':
            return SeasonConfiguration(
                league_id=league_id,
                league_type='ECS_FC',
                regular_season_weeks=8,
                playoff_weeks=1,
                has_fun_week=False,
                has_tst_week=False,
                has_bonus_week=False,
                has_practice_sessions=False,
                practice_weeks=None,
                practice_game_number=1
            )
        else:
            raise ValueError(f"Unknown league type: {league_type}")
    
    @staticmethod
    def generate_week_configurations_from_season_config(season_config: SeasonConfiguration, 
                                                       start_date: date) -> List[Dict]:
        """
        Generate week configurations based on season configuration.
        
        Args:
            season_config: SeasonConfiguration object
            start_date: Starting date for the season
            
        Returns:
            List of week configuration dictionaries
        """
        week_configs = []
        current_date = start_date
        week_order = 1
        
        # Generate regular season weeks
        for week_num in range(1, season_config.regular_season_weeks + 1):
            has_practice = (season_config.has_practice_sessions and 
                          str(week_num) in season_config.get_practice_weeks_list())
            
            week_config = {
                'date': current_date,
                'week_type': 'REGULAR',
                'description': f'Regular Season Week {week_num}',
                'has_practice_session': has_practice,
                'practice_game_number': season_config.practice_game_number if has_practice else None,
                'is_playoff_week': False,
                'playoff_round': None
            }
            week_configs.append(week_config)
            current_date += timedelta(weeks=1)
        
        # Add fun week for Premier
        if season_config.has_fun_week:
            week_configs.append({
                'date': current_date,
                'week_type': 'FUN',
                'description': 'Fun Week',
                'has_practice_session': False,
                'practice_game_number': None,
                'is_playoff_week': False,
                'playoff_round': None
            })
            current_date += timedelta(weeks=1)
        
        # Add TST week for Premier
        if season_config.has_tst_week:
            week_configs.append({
                'date': current_date,
                'week_type': 'TST',
                'description': 'TST Week',
                'has_practice_session': False,
                'practice_game_number': None,
                'is_playoff_week': False,
                'playoff_round': None
            })
            current_date += timedelta(weeks=1)
        
        # Add playoff weeks
        for playoff_round in range(1, season_config.playoff_weeks + 1):
            week_configs.append({
                'date': current_date,
                'week_type': 'PLAYOFF',
                'description': f'Playoffs Round {playoff_round}',
                'has_practice_session': False,
                'practice_game_number': None,
                'is_playoff_week': True,
                'playoff_round': playoff_round
            })
            current_date += timedelta(weeks=1)
        
        # Add bonus week for Premier
        if season_config.has_bonus_week:
            week_configs.append({
                'date': current_date,
                'week_type': 'BONUS',
                'description': 'Bonus Week',
                'has_practice_session': False,
                'practice_game_number': None,
                'is_playoff_week': False,
                'playoff_round': None
            })
            current_date += timedelta(weeks=1)
        
        return week_configs
    
    @staticmethod
    def check_schedule_constraints(matches: List[Dict], team_count: int = 8, weeks_count: int = 7) -> Dict[str, bool]:
        """
        Check if a schedule satisfies all constraints from the 8-team double round-robin spec.
        
        Args:
            matches: List of match dictionaries with keys: home_team_id, away_team_id, week, field, time
            team_count: Expected number of teams (default 8)
            weeks_count: Expected number of weeks (default 7)
            
        Returns:
            Dictionary with constraint check results and details
        """
        results = {
            'total_matches': len(matches),
            'expected_matches': team_count * weeks_count,  # 8 teams × 7 weeks = 56 matches
            'C1_double_round_robin': True,
            'C2_back_to_back_windows': True,
            'C3_no_immediate_rematch': True,
            'C4_home_away_balance': True,
            'C5_north_south_balance': True,
            'C6_window_balance': True,
            'C7_round_robin_first': True,
            'violations': []
        }
        
        # Group matches by team and week
        team_matches = defaultdict(list)
        weekly_matches = defaultdict(list)
        pair_counts = defaultdict(int)
        
        for match in matches:
            home_id = match['home_team_id']
            away_id = match['away_team_id']
            week = match.get('week', 0)
            
            team_matches[home_id].append(match)
            team_matches[away_id].append(match)
            weekly_matches[week].append(match)
            
            # Count pair occurrences (unordered)
            pair_key = f"{min(home_id, away_id)}_{max(home_id, away_id)}"
            pair_counts[pair_key] += 1
        
        # C1: Double round-robin - each pair appears exactly twice
        team_ids = list(range(1, team_count + 1))  # Assuming teams are numbered 1-8
        expected_pairs = team_count * (team_count - 1) // 2  # 28 pairs for 8 teams
        
        for t1 in team_ids:
            for t2 in team_ids:
                if t1 < t2:  # Avoid duplicate pairs
                    pair_key = f"{t1}_{t2}"
                    count = pair_counts.get(pair_key, 0)
                    if count != 2:
                        results['C1_double_round_robin'] = False
                        results['violations'].append(f"Pair {t1}-{t2}: {count} games (should be 2)")
        
        # C2: Back-to-back windows - each team plays 2 games per week in same window
        for week, week_matches in weekly_matches.items():
            team_weekly_games = defaultdict(list)
            for match in week_matches:
                team_weekly_games[match['home_team_id']].append(match)
                team_weekly_games[match['away_team_id']].append(match)
            
            for team_id, games in team_weekly_games.items():
                if len(games) != 2:
                    results['C2_back_to_back_windows'] = False
                    results['violations'].append(f"Team {team_id} week {week}: {len(games)} games (should be 2)")
                
                # Check if games are in same window (consecutive time slots)
                if len(games) == 2:
                    times = [match.get('time', '08:20') for match in games]
                    # Implementation depends on time format - basic check for now
                    # Would need actual time parsing for full validation
        
        # C3: No immediate rematch - teams don't play consecutive weeks
        sorted_weeks = sorted(weekly_matches.keys())
        for i in range(len(sorted_weeks) - 1):
            week1, week2 = sorted_weeks[i], sorted_weeks[i + 1]
            
            # Get opponents for each team in both weeks
            week1_opponents = defaultdict(set)
            week2_opponents = defaultdict(set)
            
            for match in weekly_matches[week1]:
                home, away = match['home_team_id'], match['away_team_id']
                week1_opponents[home].add(away)
                week1_opponents[away].add(home)
            
            for match in weekly_matches[week2]:
                home, away = match['home_team_id'], match['away_team_id']
                week2_opponents[home].add(away)
                week2_opponents[away].add(home)
            
            # Check for repeats
            for team_id in team_ids:
                common_opponents = week1_opponents[team_id] & week2_opponents[team_id]
                if common_opponents:
                    results['C3_no_immediate_rematch'] = False
                    results['violations'].append(f"Team {team_id} plays {common_opponents} in consecutive weeks {week1}-{week2}")
        
        # C4: Home/away balance - each team should have equal home/away games
        for team_id in team_ids:
            home_count = sum(1 for match in matches if match['home_team_id'] == team_id)
            away_count = sum(1 for match in matches if match['away_team_id'] == team_id)
            expected_count = weeks_count  # 7 home, 7 away for 7 weeks
            
            if home_count != expected_count or away_count != expected_count:
                results['C4_home_away_balance'] = False
                results['violations'].append(f"Team {team_id}: {home_count}H/{away_count}A (should be {expected_count}H/{expected_count}A)")
        
        # C5: North/South balance - each team should play equal games on each field
        for team_id in team_ids:
            north_count = sum(1 for match in team_matches[team_id] if match.get('field', 'North') == 'North')
            south_count = sum(1 for match in team_matches[team_id] if match.get('field', 'South') == 'South')
            expected_count = weeks_count  # 7 North, 7 South for 7 weeks
            
            if north_count != expected_count or south_count != expected_count:
                results['C5_north_south_balance'] = False
                results['violations'].append(f"Team {team_id}: {north_count}N/{south_count}S (should be {expected_count}N/{expected_count}S)")
        
        # C7: Complete single round-robin before repeats
        # No opponent should appear in two different weeks within the first 3 weeks.
        # The earliest a repeat can occur is week 4 (index 3).
        sorted_weeks = sorted(weekly_matches.keys())
        for team_id in team_ids:
            opponent_first_week = {}
            for w_idx, week_key in enumerate(sorted_weeks):
                week_opps = []
                for match in weekly_matches[week_key]:
                    if match['home_team_id'] == team_id:
                        week_opps.append(match['away_team_id'])
                    elif match['away_team_id'] == team_id:
                        week_opps.append(match['home_team_id'])

                for opp in week_opps:
                    if opp in opponent_first_week:
                        first_week = opponent_first_week[opp]
                        if first_week < 3 and w_idx < 3:
                            results['C7_round_robin_first'] = False
                            results['violations'].append(
                                f"Team {team_id}: plays opponent {opp} in weeks "
                                f"{first_week+1} and {w_idx+1} (no repeats before week 4)"
                            )
                    else:
                        opponent_first_week[opp] = w_idx

        # Overall constraint satisfaction
        all_constraints_met = all([
            results['C1_double_round_robin'],
            results['C2_back_to_back_windows'],
            results['C3_no_immediate_rematch'],
            results['C4_home_away_balance'],
            results['C5_north_south_balance'],
            results['C7_round_robin_first']
        ])
        
        results['all_constraints_satisfied'] = all_constraints_met
        results['total_violations'] = len(results['violations'])
        
        return results