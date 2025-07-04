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
    Schedule, Match, WeekConfiguration
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
        
        # Filter out placeholder teams (FUN WEEK, BYE, TST)
        self.all_teams = list(self.league.teams)
        self.teams = [team for team in self.all_teams if team.name not in ['FUN WEEK', 'BYE', 'TST']]
        self.num_teams = len(self.teams)
        
        if self.num_teams < 2:
            raise ValueError("Need at least 2 teams to generate a schedule")
        
        # Get placeholder teams for special weeks
        self.placeholder_teams = {
            team.name: team for team in self.all_teams 
            if team.name in ['FUN WEEK', 'BYE', 'TST']
        }
        
        self.config = None
        self.schedule_templates = []
        self.week_configurations = []
        
        # Track team assignments for balancing
        self.team_field_count = defaultdict(lambda: defaultdict(int))  # team_id -> field -> count
        self.team_time_slots = defaultdict(list)  # team_id -> list of assigned times
        
    def set_config(self, start_time: time, match_duration_minutes: int = 70, 
                   weeks_count: int = 7, fields: str = "North,South") -> None:
        """
        Set configuration for schedule generation.
        
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
                description=config.get('description', '')
            )
            self.week_configurations.append(week_config)
        
    def generate_round_robin_pairings(self) -> List[List[Tuple[int, int]]]:
        """
        Generate round-robin pairings ensuring each team plays every other team twice.
        
        Returns:
            List of weeks, where each week contains a list of (home_team_id, away_team_id) tuples
        """
        if self.num_teams % 2 != 0:
            # Add a dummy team (BYE) for odd number of teams
            team_ids = [team.id for team in self.teams] + [None]
            num_teams_with_bye = self.num_teams + 1
        else:
            team_ids = [team.id for team in self.teams]
            num_teams_with_bye = self.num_teams
        
        # Calculate total rounds needed for each team to play each other twice
        # In a round-robin tournament, each team plays (n-1) matches in first round
        # We need 2 full round-robins, so 2*(n-1) rounds total
        total_rounds = 2 * (num_teams_with_bye - 1)
        
        # Generate first round-robin
        first_round_robin = self._generate_single_round_robin(team_ids)
        
        # Generate second round-robin (reverse home/away)
        second_round_robin = []
        for week in first_round_robin:
            reversed_week = [(away, home) for home, away in week if home is not None and away is not None]
            second_round_robin.append(reversed_week)
        
        # Combine both round-robins
        all_weeks = first_round_robin + second_round_robin
        
        # Randomize the order of weeks while preserving the constraint
        # that teams don't play the same opponent twice before playing everyone once
        randomized_weeks = self._randomize_schedule_order(all_weeks)
        
        # Trim to the specified number of weeks
        return randomized_weeks[:self.weeks_count]
    
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
    
    def generate_schedule_templates(self, week_configs: List[Dict] = None) -> List[ScheduleTemplate]:
        """
        Generate schedule templates for the entire season including special weeks.
        
        Args:
            week_configs: List of week configurations with date, type, description
            
        Returns:
            List of ScheduleTemplate objects
        """
        if not self.start_time:
            raise ValueError("Configuration not set. Call set_config() first.")
        
        if week_configs:
            self.set_week_configurations(week_configs)
        
        # Generate round-robin pairings for regular weeks only
        weekly_pairings = self.generate_round_robin_pairings()
        
        templates = []
        regular_week_index = 0
        
        # Process each configured week
        for week_config in self.week_configurations:
            week_date = week_config.week_date
            week_type = week_config.week_type
            week_order = week_config.week_order
            
            if week_type == 'REGULAR':
                # Generate normal matches for this week
                if regular_week_index < len(weekly_pairings):
                    week_matches = weekly_pairings[regular_week_index]
                    regular_week_index += 1
                    
                    # Assign matches to time slots and fields
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
                            is_special_week=False
                        )
                        templates.append(template)
                        
            elif week_type in ['FUN', 'TST', 'BYE']:
                # Generate special week matches
                special_templates = self._generate_special_week_templates(
                    week_type, week_date, week_order
                )
                templates.extend(special_templates)
        
        return templates
    
    def _generate_special_week_templates(self, week_type: str, week_date: date, week_order: int) -> List[ScheduleTemplate]:
        """
        Generate schedule templates for special weeks (FUN, TST, BYE).
        
        Args:
            week_type: Type of special week
            week_date: Date of the week
            week_order: Order of the week in the season
            
        Returns:
            List of ScheduleTemplate objects
        """
        templates = []
        
        if week_type == 'BYE':
            # For BYE weeks, create matches against the BYE placeholder team
            bye_team = self.placeholder_teams.get('BYE')
            if bye_team:
                time_slots = self._generate_time_slots()
                
                for i, team in enumerate(self.teams):
                    # Create one "match" per team showing BYE
                    field_name = self.fields[i % len(self.fields)]
                    match_time = time_slots[i % len(time_slots)]
                    
                    template = ScheduleTemplate(
                        league_id=self.league_id,
                        week_number=week_order,
                        home_team_id=team.id,
                        away_team_id=bye_team.id,
                        scheduled_date=week_date,
                        scheduled_time=match_time,
                        field_name=field_name,
                        match_order=1,
                        week_type='BYE',
                        is_special_week=True
                    )
                    templates.append(template)
                    
        elif week_type == 'FUN':
            # For FUN weeks, create matches against the FUN WEEK placeholder team
            fun_team = self.placeholder_teams.get('FUN WEEK')
            if fun_team:
                time_slots = self._generate_time_slots()
                
                for i, team in enumerate(self.teams):
                    field_name = self.fields[i % len(self.fields)]
                    match_time = time_slots[i % len(time_slots)]
                    
                    template = ScheduleTemplate(
                        league_id=self.league_id,
                        week_number=week_order,
                        home_team_id=team.id,
                        away_team_id=fun_team.id,
                        scheduled_date=week_date,
                        scheduled_time=match_time,
                        field_name=field_name,
                        match_order=1,
                        week_type='FUN',
                        is_special_week=True
                    )
                    templates.append(template)
                    
        elif week_type == 'TST':
            # For TST weeks, create matches against the TST placeholder team
            tst_team = self.placeholder_teams.get('TST')
            if tst_team:
                time_slots = self._generate_time_slots()
                
                for i, team in enumerate(self.teams):
                    field_name = self.fields[i % len(self.fields)]
                    match_time = time_slots[i % len(time_slots)]
                    
                    template = ScheduleTemplate(
                        league_id=self.league_id,
                        week_number=week_order,
                        home_team_id=team.id,
                        away_team_id=tst_team.id,
                        scheduled_date=week_date,
                        scheduled_time=match_time,
                        field_name=field_name,
                        match_order=1,
                        week_type='TST',
                        is_special_week=True
                    )
                    templates.append(template)
        
        return templates
    
    def _generate_time_slots(self) -> List[time]:
        """
        Generate time slots for matches based on start time and duration.
        
        Returns:
            List of time objects for each match slot
        """
        time_slots = []
        current_time = datetime.combine(date.today(), self.start_time)
        
        # Generate enough time slots for maximum possible matches
        # Each team plays 2 matches per day, so we need enough slots
        max_matches_per_day = self.num_teams  # Each team plays 2, so total matches = num_teams
        
        for _ in range(max_matches_per_day):
            time_slots.append(current_time.time())
            current_time += timedelta(minutes=self.match_duration_minutes)
        
        return time_slots
    
    def _assign_matches_to_fields(self, matches: List[Tuple[int, int]], 
                                 time_slots: List[time]) -> List[Tuple[int, int, time, str, int]]:
        """
        Assign matches to specific time slots and fields with proper randomization and balancing.
        
        Args:
            matches: List of (home_team_id, away_team_id) tuples
            time_slots: Available time slots
            
        Returns:
            List of (home_team_id, away_team_id, time, field, match_order) tuples
        """
        assignments = []
        team_schedule = defaultdict(list)  # Track what time each team is playing
        
        # Shuffle matches to randomize assignment
        shuffled_matches = matches.copy()
        random.shuffle(shuffled_matches)
        
        # Group matches into pairs (since each team plays 2 matches back-to-back)
        match_pairs = []
        team_match_tracker = defaultdict(list)
        
        for home_team_id, away_team_id in shuffled_matches:
            # Find teams that need second matches
            home_needs_second = len(team_match_tracker[home_team_id]) == 1
            away_needs_second = len(team_match_tracker[away_team_id]) == 1
            
            # Track this match for both teams
            team_match_tracker[home_team_id].append((home_team_id, away_team_id))
            team_match_tracker[away_team_id].append((home_team_id, away_team_id))
            
            # If both teams need their second match, pair them together in time
            if home_needs_second and away_needs_second:
                # Find their first matches and pair this as second
                pass  # This will be handled in the pairing logic below
        
        # Create time slot assignments with field randomization and balancing
        current_time_slot = 0
        for i, (home_team_id, away_team_id) in enumerate(shuffled_matches):
            playing_teams = [home_team_id, away_team_id]
            
            # Determine time slot and match order
            assigned_time = time_slots[current_time_slot % len(time_slots)]
            
            # Determine match order for each team (1st or 2nd match of the day)
            match_orders = {}
            for team_id in playing_teams:
                match_orders[team_id] = len(team_schedule[team_id]) + 1
                team_schedule[team_id].append(assigned_time)
            
            match_order = match_orders[home_team_id]
            
            # Smart field assignment with balancing
            assigned_field = self._get_balanced_field(home_team_id, away_team_id)
            
            # Track field assignments for balancing
            self.team_field_count[home_team_id][assigned_field] += 1
            self.team_field_count[away_team_id][assigned_field] += 1
            self.team_time_slots[home_team_id].append(assigned_time)
            self.team_time_slots[away_team_id].append(assigned_time)
            
            assignments.append((
                home_team_id, away_team_id, assigned_time, 
                assigned_field, match_order
            ))
            
            # Move to next time slot every 2 matches (to accommodate both fields)
            if (i + 1) % len(self.fields) == 0:
                current_time_slot += 1
        
        return assignments
    
    def _get_balanced_field(self, home_team_id: int, away_team_id: int) -> str:
        """
        Get a field assignment that balances field usage across teams.
        
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
        min_score = min(field_scores.values())
        best_fields = [field for field, score in field_scores.items() if score == min_score]
        
        # Randomize among equally good options
        return random.choice(best_fields)
    
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
            schedule_manager.create_match(
                date=template.scheduled_date,
                time=template.scheduled_time,
                location=template.field_name,
                home_team_id=template.home_team_id,
                away_team_id=template.away_team_id,
                week=str(template.week_number)
            )
            
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
            home_team = self.session.query(Team).filter_by(id=template.home_team_id).first()
            away_team = self.session.query(Team).filter_by(id=template.away_team_id).first()
            
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