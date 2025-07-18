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
        Generate back-to-back round-robin pairings where each team plays exactly 2 games per week.
        
        Constraint-based approach:
        - Each team plays exactly 2 games per week (back-to-back)
        - Round-robin: don't repeat opponents until all teams have been played
        - Total matches per week = num_teams (since each team plays 2 games)
        
        Returns:
            List of weeks, where each week contains a list of (home_team_id, away_team_id) tuples
        """
        if self.num_teams % 2 != 0:
            raise ValueError("Back-to-back scheduling requires an even number of teams")
        
        team_ids = [team.id for team in self.teams]
        weekly_schedules = []
        
        # Track opponents for round-robin constraint
        team_opponents = {team_id: set() for team_id in team_ids}
        
        for week in range(self.weeks_count):
            week_matches = self._generate_back_to_back_week(team_ids, team_opponents, week)
            if week_matches:
                weekly_schedules.append(week_matches)
                
                # Update opponent tracking
                for home_id, away_id in week_matches:
                    team_opponents[home_id].add(away_id)
                    team_opponents[away_id].add(home_id)
        
        return weekly_schedules
    
    def _generate_back_to_back_week(self, team_ids: List[int], team_opponents: Dict[int, set], week_num: int) -> List[Tuple[int, int]]:
        """
        Generate matches for a single week using proper back-to-back pattern.
        
        For back-to-back scheduling with 8 teams, creates 4 pairs where each team
        plays different opponents in consecutive time slots:
        - Time 1: A vs B, C vs D
        - Time 2: D vs B, C vs A  (A plays B then C, B plays A then D, etc.)
        - Time 3: E vs F, G vs H
        - Time 4: F vs G, H vs E
        
        Args:
            team_ids: List of team IDs
            team_opponents: Dict tracking who each team has already played
            week_num: Current week number (for round-robin rotation)
            
        Returns:
            List of (home_team_id, away_team_id) tuples for this week
        """
        # Use circle method for round-robin
        teams = team_ids.copy()
        n = len(teams)
        
        if n % 2 != 0:
            raise ValueError("Need even number of teams")
        
        # Rotate teams for this week (except first team which stays fixed)
        if week_num > 0:
            # Perform rotations based on week number
            for _ in range(week_num):
                # Keep first team fixed, rotate others
                teams = [teams[0]] + [teams[-1]] + teams[1:-1]
        
        week_matches = []
        
        # Create 4 groups of 2 teams each for 8 teams
        # Each group will play back-to-back matches
        for i in range(0, n, 4):
            if i + 3 < n:
                # Get 4 teams for this group
                team_a = teams[i]
                team_b = teams[i + 1] 
                team_c = teams[i + 2]
                team_d = teams[i + 3]
                
                # Create back-to-back pattern for this group of 4
                # Time slot 1: A vs B, C vs D
                week_matches.append((team_a, team_b))
                week_matches.append((team_c, team_d))
                
                # Time slot 2: D vs B, C vs A (back-to-back for all teams)
                week_matches.append((team_d, team_b))
                week_matches.append((team_c, team_a))
        
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
        Generate time slots for back-to-back matches based on configured start times.
        
        For back-to-back scheduling:
        - Each team plays 2 consecutive games
        - 2 matches happen concurrently (North and South fields)
        - Time slots needed = num_teams / 2 (for 8 teams: 4 time slots)
        
        Returns:
            List of time objects for each match slot
        """
        time_slots = []
        
        # Use configured start time from wizard
        start_time = self.start_time
        if not start_time:
            # Fallback to defaults if not set
            if self.league.name == 'Premier':
                start_time = time(8, 20)  # Default Premier start
            elif self.league.name == 'Classic':
                start_time = time(13, 10)  # Default Classic start (1:10 PM)
            else:
                start_time = time(8, 0)   # General default
        
        current_time = datetime.combine(date.today(), start_time)
        
        # For back-to-back games, we need half the number of time slots
        # because 2 games happen concurrently on different fields
        num_time_slots = self.num_teams // 2
        
        for i in range(num_time_slots):
            time_slots.append(current_time.time())
            current_time += timedelta(minutes=self.match_duration_minutes)
        
        logger.info(f"Generated {len(time_slots)} time slots for {self.league.name} starting at {start_time}")
        for i, slot in enumerate(time_slots):
            logger.info(f"  Slot {i+1}: {slot}")
        
        return time_slots
    
    def _assign_matches_to_fields(self, matches: List[Tuple[int, int]], 
                                 time_slots: List[time]) -> List[Tuple[int, int, time, str, int]]:
        """
        Assign matches to time slots with concurrent play on North/South fields.
        
        Pattern for 8 teams playing back-to-back (matches come in groups of 4):
        Time 1: Match 1 North, Match 2 South  
        Time 2: Match 3 North, Match 4 South
        Time 3: Match 5 North, Match 6 South
        Time 4: Match 7 North, Match 8 South
        
        Args:
            matches: List of (home_team_id, away_team_id) tuples from back-to-back generator
            time_slots: Available time slots
            
        Returns:
            List of (home_team_id, away_team_id, time, field, match_order) tuples
        """
        assignments = []
        
        # Process matches in pairs (2 matches per time slot)
        time_index = 0
        
        for i in range(0, len(matches), 2):
            # Get current time slot
            if time_index >= len(time_slots):
                logger.warning(f"Not enough time slots for all matches. Need {len(matches)//2}, have {len(time_slots)}")
                break
                
            current_time = time_slots[time_index]
            
            # First match goes to North
            if i < len(matches):
                home_team_1, away_team_1 = matches[i]
                assignments.append((home_team_1, away_team_1, current_time, "North", time_index + 1))
            
            # Second match goes to South (if exists)
            if i + 1 < len(matches):
                home_team_2, away_team_2 = matches[i + 1]
                assignments.append((home_team_2, away_team_2, current_time, "South", time_index + 1))
            
            # Move to next time slot
            time_index += 1
        
        logger.info(f"Assigned {len(assignments)} matches to {time_index} time slots")
        
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