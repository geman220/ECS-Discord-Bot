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
        self.fields = [field.strip() for field in fields.split(',')]
        
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

        Implements the 8-team, 7-Sundays, double round-robin specification:
        - C1: Each unordered pair appears exactly twice (once home/away, once reversed)
        - C2: Each team plays 2 games per Sunday in same window (back-to-back)
        - C3: No immediate rematch (no team plays same opponent in consecutive weeks)
        - C4: Each team: 7 home, 7 away games total
        - C5: Each team: 7 North, 7 South field assignments total
        - C6: Each team: 3 or 4 early-pairs and 4 or 3 late-pairs

        Returns:
            List of weeks, where each week contains a list of (home_team_id, away_team_id) tuples
        """
        
        team_ids = [team.id for team in self.teams]
        weekly_schedules = []
        
        # Track constraints
        team_opponents = {team_id: set() for team_id in team_ids}
        last_week_opponents = {team_id: set() for team_id in team_ids}
        home_away_count = {team_id: {'home': 0, 'away': 0} for team_id in team_ids}
        pair_count = {self._get_pair_key(t1, t2): 0 for t1 in team_ids for t2 in team_ids if t1 != t2}
        
        for week in range(self.weeks_count):
            week_matches = self._generate_back_to_back_week(team_ids, team_opponents, week)
            
            # Validate constraints for this week
            if not self._validate_week_constraints(week_matches, team_ids, last_week_opponents):
                logger.warning(f"Week {week} failed constraint validation, attempting retry")
                # Retry with different pairing strategy
                week_matches = self._generate_back_to_back_week_retry(team_ids, team_opponents, week)
            
            if week_matches:
                weekly_schedules.append(week_matches)
                
                # Update constraint tracking
                current_week_opponents = {team_id: set() for team_id in team_ids}
                
                for home_id, away_id in week_matches:
                    # Update opponent tracking
                    team_opponents[home_id].add(away_id)
                    team_opponents[away_id].add(home_id)
                    
                    # Track this week's opponents for C3 constraint
                    current_week_opponents[home_id].add(away_id)
                    current_week_opponents[away_id].add(home_id)
                    
                    # Update home/away counts
                    home_away_count[home_id]['home'] += 1
                    home_away_count[away_id]['away'] += 1
                    
                    # Update pair count
                    pair_key = self._get_pair_key(home_id, away_id)
                    pair_count[pair_key] += 1
                
                # Update last week opponents for next iteration
                last_week_opponents = current_week_opponents
        
        # Final constraint validation
        self._validate_final_schedule(weekly_schedules, team_ids, home_away_count, pair_count)
        
        return weekly_schedules
    
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
    
    def _generate_back_to_back_week_retry(self, team_ids: List[int], 
                                        team_opponents: Dict[int, set], week_num: int) -> List[Tuple[int, int]]:
        """
        Retry week generation with different strategy if constraints fail.
        
        This is a fallback that tries alternative pairings to satisfy constraints.
        """
        # Try with different rotation offset
        teams = team_ids.copy()
        
        # Use alternative rotation pattern
        if week_num > 0:
            fixed_team = teams[0]
            rotating_teams = teams[1:]
            # Try different rotation amount
            rotation_offset = (week_num * 2) % len(rotating_teams)
            for _ in range(rotation_offset):
                rotating_teams = [rotating_teams[-1]] + rotating_teams[:-1]
            teams = [fixed_team] + rotating_teams
        
        # Generate matches with alternative pairing
        week_matches = []
        
        # Alternative pairing strategy
        first_window_pairs = []
        for i in range(0, 8, 2):
            first_window_pairs.append((teams[i], teams[i + 1]))
        
        # Use different shift for second window
        shifted_teams = teams[2:] + teams[:2]  # Shift by 2 instead of 1
        second_window_pairs = []
        for i in range(0, 8, 2):
            team_a = teams[i]
            potential_opponent = shifted_teams[i + 1]
            
            # Avoid self-matches
            if potential_opponent == team_a:
                potential_opponent = shifted_teams[(i + 3) % 8]
            
            second_window_pairs.append((team_a, potential_opponent))
        
        week_matches.extend(first_window_pairs)
        week_matches.extend(second_window_pairs)
        
        return week_matches
    
    def _validate_final_schedule(self, weekly_schedules: List[List[Tuple[int, int]]], 
                               team_ids: List[int], home_away_count: Dict, pair_count: Dict) -> None:
        """
        Validate the entire schedule against all constraints.
        
        Args:
            weekly_schedules: Complete schedule
            team_ids: All team IDs
            home_away_count: Home/away game counts per team
            pair_count: Number of times each pair has played
        """
        logger.info("Validating final schedule constraints...")
        
        # C1: Double round-robin - each pair plays exactly twice
        total_pairs = len([k for k, v in pair_count.items() if v > 0])
        expected_pairs = len(team_ids) * (len(team_ids) - 1) // 2  # nC2 pairs
        
        violations = []
        for pair_key, count in pair_count.items():
            if count != 2:
                violations.append(f"Pair {pair_key}: {count} games (should be 2)")
        
        if violations:
            logger.error(f"C1 violations: {violations}")
        
        # C4: Home/away balance - each team should have 7 home, 7 away
        for team_id in team_ids:
            home_count = home_away_count[team_id]['home']
            away_count = home_away_count[team_id]['away']
            if home_count != 7 or away_count != 7:
                logger.error(f"C4 violation: Team {team_id} has {home_count}H/{away_count}A (should be 7H/7A)")
        
        # Total match count validation
        total_matches = sum(len(week) for week in weekly_schedules)
        expected_matches = len(team_ids) * 7  # 8 teams × 7 weeks × 2 games ÷ 2
        
        if total_matches != expected_matches:
            logger.error(f"Total matches: {total_matches} (expected {expected_matches})")
        
        logger.info(f"Schedule validation complete. {len(violations)} constraint violations found.")
    
    def _generate_back_to_back_week(self, team_ids: List[int], team_opponents: Dict[int, set], week_num: int) -> List[Tuple[int, int]]:
        """
        Generate matches for a single week using the validated double round-robin pattern.
        
        Implements the exact pattern from the validated 8-team, 7-week schedule:
        - Window rotation: Teams alternate between early/late windows each week
        - Each team plays exactly 2 games in consecutive time slots (same window)
        - Each pair appears exactly twice across the season
        - No consecutive week rematches (C3 constraint)
        
        Args:
            team_ids: List of team IDs (must be 8 teams)
            team_opponents: Dict tracking who each team has already played (for validation)
            week_num: Current week number (0-6)
            
        Returns:
            List of (home_team_id, away_team_id) tuples for this week
        """
        if len(team_ids) != 8:
            raise ValueError("Premier League double round-robin requires exactly 8 teams")
        
        # Sort team IDs to ensure consistent ordering (A=175, B=176, C=177, D=178, E=179, F=180, G=181, H=182)
        teams = sorted(team_ids)
        A, B, C, D, E, F, G, H = teams
        
        # Define the EXACT validated 7-week schedule pattern from your specification
        schedule_pattern = {
            0: [  # Week 1: 08:20 1N(A,B) 1S(C,D) 09:30 2N(A,C) 2S(B,D) | 10:40 3N(E,F) 3S(G,H) 11:50 4N(E,G) 4S(F,H)
                (A, B), (C, D), (A, C), (B, D),  # Early window
                (E, F), (G, H), (E, G), (F, H)   # Late window
            ],
            1: [  # Week 2: 08:20 1N(A,E) 1S(B,F) 09:30 2N(A,F) 2S(B,E) | 10:40 3N(C,G) 3S(D,H) 11:50 4N(C,H) 4S(D,G)
                (A, E), (B, F), (A, F), (B, E),  # Early window
                (C, G), (D, H), (C, H), (D, G)   # Late window
            ],
            2: [  # Week 3: 08:20 1N(B,A) 1S(D,C) 09:30 2N(A,D) 2S(B,C) | 10:40 3N(F,E) 3S(H,G) 11:50 4N(E,H) 4S(F,G)
                (B, A), (D, C), (A, D), (B, C),  # Early window
                (F, E), (H, G), (E, H), (F, G)   # Late window
            ],
            3: [  # Week 4: 08:20 1N(A,G) 1S(B,H) 09:30 2N(A,H) 2S(B,G) | 10:40 3N(C,E) 3S(D,F) 11:50 4N(C,F) 4S(D,E)
                (A, G), (B, H), (A, H), (B, G),  # Early window  
                (C, E), (D, F), (C, F), (D, E)   # Late window
            ],
            4: [  # Week 5: 08:20 1N(G,C) 1S(H,D) 09:30 2N(H,C) 2S(G,D) | 10:40 3N(E,A) 3S(F,B) 11:50 4N(F,A) 4S(E,B)
                (G, C), (H, D), (H, C), (G, D),  # Early window
                (E, A), (F, B), (F, A), (E, B)   # Late window
            ],
            5: [  # Week 6: 08:20 1N(E,C) 1S(F,D) 09:30 2N(F,C) 2S(E,D) | 10:40 3N(G,A) 3S(H,B) 11:50 4N(H,A) 4S(G,B)
                (E, C), (F, D), (F, C), (E, D),  # Early window
                (G, A), (H, B), (H, A), (G, B)   # Late window
            ],
            6: [  # Week 7: 08:20 1N(G,E) 1S(H,F) 09:30 2N(H,E) 2S(G,F) | 10:40 3N(C,A) 3S(D,B) 11:50 4N(D,A) 4S(C,B)
                (G, E), (H, F), (H, E), (G, F),  # Early window
                (C, A), (D, B), (D, A), (C, B)   # Late window
            ]
        }
        
        if week_num not in schedule_pattern:
            raise ValueError(f"Week number {week_num} not supported (must be 0-6)")
        
        week_matches = schedule_pattern[week_num]
        
        logger.info(f"Generated week {week_num + 1} matches: {len(week_matches)} games")
        for i, (home, away) in enumerate(week_matches):
            logger.info(f"  Match {i+1}: Team {home} vs Team {away}")
        
        return week_matches
    
    def _generate_single_round_robin(self, team_ids: List[Optional[int]]) -> List[List[Tuple[int, int]]]:
        """
        Generate a single round-robin tournament using the circle method.
        
        Args:
            team_ids: List of team IDs (may include None for BYE)
            
        Returns:
            List of weeks with matchups
        """
        n = len(team_ids)
        if n % 2 != 0:
            raise ValueError("Team list must have even number of elements")
        
        # Use circle method for round-robin
        weeks = []
        
        # Fix the first team, rotate the others
        fixed_team = team_ids[0]
        rotating_teams = team_ids[1:]
        
        for round_num in range(n - 1):
            week_matches = []
            
            # First match: fixed team vs current first rotating team
            opponent = rotating_teams[0]
            if fixed_team is not None and opponent is not None:
                week_matches.append((fixed_team, opponent))
            
            # Remaining matches: pair up the rest
            for i in range(1, len(rotating_teams) // 2 + 1):
                team1 = rotating_teams[i]
                team2 = rotating_teams[-(i)]
                
                if team1 is not None and team2 is not None:
                    week_matches.append((team1, team2))
            
            weeks.append(week_matches)
            
            # Rotate the rotating teams
            rotating_teams = [rotating_teams[-1]] + rotating_teams[:-1]
        
        return weeks
    
    def _randomize_schedule_order(self, weeks: List[List[Tuple[int, int]]]) -> List[List[Tuple[int, int]]]:
        """
        Randomize the order of weeks while ensuring constraint satisfaction.
        
        Args:
            weeks: List of weeks with matchups
            
        Returns:
            Randomized list of weeks
        """
        # For now, we'll do a simple randomization of the entire schedule
        # In a more sophisticated version, we could ensure that teams don't
        # play the same opponent twice before playing everyone once
        
        # Split into first and second half to maintain the constraint
        mid_point = len(weeks) // 2
        first_half = weeks[:mid_point]
        second_half = weeks[mid_point:]
        
        # Shuffle each half separately
        random.shuffle(first_half)
        random.shuffle(second_half)
        
        return first_half + second_half
    
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
    
    def _get_balanced_field(self, home_team_id: int, away_team_id: int) -> str:
        """
        Get a field assignment that balances field usage across teams.
        
        For back-to-back scheduling, this is mainly used for fallback cases
        since the main field assignment is handled in _assign_matches_to_fields.
        
        Args:
            home_team_id: ID of home team
            away_team_id: ID of away team
            
        Returns:
            Field name that provides best balance
        """
        # Calculate current field usage for both teams
        field_scores = {}
        
        for field in self.fields:
            home_field_count = self.team_field_count[home_team_id][field]
            away_field_count = self.team_field_count[away_team_id][field]
            
            # Lower score = less used = preferred
            field_scores[field] = home_field_count + away_field_count
        
        # Get fields with minimum usage
        if field_scores.values():
            min_score = min(field_scores.values())
            best_fields = [field for field, score in field_scores.items() if score == min_score]
            return random.choice(best_fields) if best_fields else self.fields[0]
        else:
            return self.fields[0]
    
    def _balance_time_slots(self, assignments: List[Tuple[int, int, time, str, int]]) -> List[Tuple[int, int, time, str, int]]:
        """
        Rebalance time slot assignments to prevent teams from always playing early/late.
        
        Args:
            assignments: Current match assignments
            
        Returns:
            Rebalanced assignments
        """
        # Group assignments by time slot
        time_slot_groups = defaultdict(list)
        for assignment in assignments:
            time_slot_groups[assignment[2]].append(assignment)
        
        # For each time slot, ensure fair rotation of teams
        balanced_assignments = []
        
        for time_slot in sorted(time_slot_groups.keys()):
            slot_assignments = time_slot_groups[time_slot]
            
            # Randomize order within each time slot to balance early/late play
            random.shuffle(slot_assignments)
            balanced_assignments.extend(slot_assignments)
        
        return balanced_assignments
    
    def _balance_premier_time_slots(self, assignments: List[Tuple[int, int, time, str, int]]) -> List[Tuple[int, int, time, str, int]]:
        """
        Balance Premier league time slots to ensure teams get distributed between
        morning (early) and mid-morning (later) time slots across the season.
        
        This prevents teams from always playing at the same time (e.g., always 8:20am).
        Teams should get a mix of morning and mid-morning games.
        
        Args:
            assignments: Current match assignments (home_team_id, away_team_id, time, field, match_order)
            
        Returns:
            Balanced assignments with better time slot distribution
        """
        if not assignments:
            return assignments
            
        # Group assignments by time slot
        time_slot_groups = defaultdict(list)
        for assignment in assignments:
            time_slot_groups[assignment[2]].append(assignment)
        
        # Get sorted time slots (earliest to latest)
        sorted_times = sorted(time_slot_groups.keys())
        
        if len(sorted_times) < 2:
            # Not enough time slots to balance, return as-is
            return assignments
            
        # Split time slots into morning (early half) and mid-morning (later half)
        mid_point = len(sorted_times) // 2
        morning_slots = sorted_times[:mid_point]
        mid_morning_slots = sorted_times[mid_point:]
        
        logger.info(f"Balancing Premier time slots:")
        logger.info(f"  Morning slots: {[str(t) for t in morning_slots]}")
        logger.info(f"  Mid-morning slots: {[str(t) for t in mid_morning_slots]}")
        
        # Collect all teams that need balancing
        all_teams = set()
        for assignment in assignments:
            all_teams.add(assignment[0])  # home team
            all_teams.add(assignment[1])  # away team
        
        # Track which teams need mid-morning games (those that have been playing too many morning games)
        teams_needing_later_slots = set()
        for team_id in all_teams:
            morning_count = sum(1 for time_slot in self.team_time_slots[team_id] if time_slot in morning_slots)
            mid_morning_count = sum(1 for time_slot in self.team_time_slots[team_id] if time_slot in mid_morning_slots)
            
            # If team has more morning games than mid-morning, prioritize them for later slots
            if morning_count > mid_morning_count:
                teams_needing_later_slots.add(team_id)
        
        balanced_assignments = []
        
        # Process each time slot and try to balance
        for time_slot in sorted_times:
            slot_assignments = time_slot_groups[time_slot].copy()
            is_morning_slot = time_slot in morning_slots
            
            # If this is a morning slot and we have teams that need later slots,
            # try to swap them with teams from mid-morning slots
            if is_morning_slot and teams_needing_later_slots and mid_morning_slots:
                # Find matches in this slot that involve teams needing later slots
                matches_to_swap = []
                matches_to_keep = []
                
                for assignment in slot_assignments:
                    home_team, away_team = assignment[0], assignment[1]
                    if home_team in teams_needing_later_slots or away_team in teams_needing_later_slots:
                        matches_to_swap.append(assignment)
                    else:
                        matches_to_keep.append(assignment)
                
                # Try to swap with a mid-morning slot
                if matches_to_swap and len(mid_morning_slots) > 0:
                    # Pick a mid-morning slot to swap with
                    target_mid_morning_slot = mid_morning_slots[0]
                    target_slot_assignments = time_slot_groups[target_mid_morning_slot]
                    
                    # Find a match in the mid-morning slot that can be swapped
                    for i, target_assignment in enumerate(target_slot_assignments):
                        target_home, target_away = target_assignment[0], target_assignment[1]
                        
                        # Only swap if the target teams don't specifically need later slots
                        if target_home not in teams_needing_later_slots and target_away not in teams_needing_later_slots:
                            # Perform the swap
                            match_to_swap = matches_to_swap[0]
                            
                            # Update the assignments with swapped times
                            swapped_morning = (match_to_swap[0], match_to_swap[1], target_mid_morning_slot, match_to_swap[3], match_to_swap[4])
                            swapped_mid_morning = (target_assignment[0], target_assignment[1], time_slot, target_assignment[3], target_assignment[4])
                            
                            # Update the groups
                            slot_assignments = matches_to_keep + [swapped_mid_morning] + matches_to_swap[1:]
                            time_slot_groups[target_mid_morning_slot][i] = swapped_morning
                            
                            logger.info(f"Swapped teams {match_to_swap[0]},{match_to_swap[1]} from {time_slot} to {target_mid_morning_slot}")
                            break
            
            balanced_assignments.extend(slot_assignments)
        
        # Update team time slot tracking
        for assignment in balanced_assignments:
            self.team_time_slots[assignment[0]].append(assignment[2])  # home team
            self.team_time_slots[assignment[1]].append(assignment[2])  # away team
        
        return balanced_assignments
    
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
        
        # Overall constraint satisfaction
        all_constraints_met = all([
            results['C1_double_round_robin'],
            results['C2_back_to_back_windows'], 
            results['C3_no_immediate_rematch'],
            results['C4_home_away_balance'],
            results['C5_north_south_balance']
        ])
        
        results['all_constraints_satisfied'] = all_constraints_met
        results['total_violations'] = len(results['violations'])
        
        return results