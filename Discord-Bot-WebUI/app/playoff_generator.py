# app/playoff_generator.py

"""
Playoff Schedule Generator Module

This module generates playoff schedules with the following structure:
- Week 1: First half of round-robin matches within playoff groups
- Week 2 Morning: Second half of round-robin matches (completes group stage)
- Week 2 Afternoon: Placement games based on group standings
"""

import random
import logging
from datetime import date, time
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

from app.models import Team, Standings, Match, Schedule, ScheduleTemplate

logger = logging.getLogger(__name__)


class PlayoffGenerator:
    """Generates playoff schedules with group-based round-robin and placement games."""

    def __init__(self, league_id: int, season_id: int, session):
        """
        Initialize the playoff generator.

        Args:
            league_id: ID of the league
            season_id: ID of the current season
            session: Database session
        """
        self.league_id = league_id
        self.season_id = season_id
        self.session = session

        # Time slots for Premier League (default)
        self.time_slots = [
            time(8, 20),   # 08:20
            time(9, 30),   # 09:30
            time(10, 40),  # 10:40
            time(11, 50),  # 11:50
        ]

        # Fields
        self.fields = ['North', 'South']

    def get_top_teams_with_tiebreaking(self, num_teams: int = 8) -> List[Team]:
        """
        Get top teams from standings with random tie-breaking.

        Args:
            num_teams: Number of teams to retrieve (default 8)

        Returns:
            List of teams ordered by standings
        """
        # Get all standings for this season
        standings = self.session.query(Standings).filter_by(
            season_id=self.season_id
        ).join(Team).filter(
            Team.league_id == self.league_id
        ).all()

        if not standings:
            logger.error(f"No standings found for season {self.season_id}")
            return []

        # Group teams by points to identify ties
        points_groups = defaultdict(list)
        for standing in standings:
            points_groups[standing.points].append(standing)

        # Sort point values descending
        sorted_points = sorted(points_groups.keys(), reverse=True)

        # Build final ranking with tie-breaking
        ranked_teams = []
        for points in sorted_points:
            teams_with_points = points_groups[points]

            if len(teams_with_points) == 1:
                # No tie, add directly
                ranked_teams.append(teams_with_points[0].team)
            else:
                # Tie detected - use goal difference first
                teams_with_points.sort(key=lambda s: s.goal_difference, reverse=True)

                # Check for ties in goal difference
                gd_groups = defaultdict(list)
                for standing in teams_with_points:
                    gd_groups[standing.goal_difference].append(standing)

                for gd in sorted(gd_groups.keys(), reverse=True):
                    gd_tied_teams = gd_groups[gd]
                    if len(gd_tied_teams) > 1:
                        # Still tied after goal difference - randomize
                        logger.info(f"Tie detected: {len(gd_tied_teams)} teams with {points} points and {gd} GD - randomizing order")
                        random.shuffle(gd_tied_teams)

                    for standing in gd_tied_teams:
                        ranked_teams.append(standing.team)

            if len(ranked_teams) >= num_teams:
                break

        # Return top N teams
        top_teams = ranked_teams[:num_teams]
        logger.info(f"Top {num_teams} teams selected: {[t.name for t in top_teams]}")
        return top_teams

    def create_playoff_groups(self, teams: List[Team]) -> Tuple[List[Team], List[Team]]:
        """
        Split top 8 teams into two groups and randomly assign A/B labels.

        Group 1: positions 1, 4, 5, 8
        Group 2: positions 2, 3, 6, 7

        Args:
            teams: List of 8 teams ordered by standings

        Returns:
            Tuple of (Group A, Group B) where each is a list of 4 teams
        """
        if len(teams) != 8:
            raise ValueError(f"Expected 8 teams for playoffs, got {len(teams)}")

        # Create groups based on positions
        group1 = [teams[0], teams[3], teams[4], teams[7]]  # positions 1, 4, 5, 8
        group2 = [teams[1], teams[2], teams[5], teams[6]]  # positions 2, 3, 6, 7

        logger.info(f"Group 1: {[t.name for t in group1]}")
        logger.info(f"Group 2: {[t.name for t in group2]}")

        # Randomly assign which group is A or B
        if random.choice([True, False]):
            group_a, group_b = group1, group2
            logger.info("Group 1 assigned as Group A, Group 2 as Group B")
        else:
            group_a, group_b = group2, group1
            logger.info("Group 2 assigned as Group A, Group 1 as Group B")

        return group_a, group_b

    def _generate_group_round_robin(self, teams: List[Team]) -> List[List[Tuple[Team, Team]]]:
        """
        Generate round-robin schedule for a 4-team group using circle method.
        Organizes matches into rounds where no team plays twice in the same round.
        Higher seed is always home team.

        Args:
            teams: List of 4 teams (ordered by seed, with index 0 being highest seed)

        Returns:
            List of 3 rounds, each containing 2 match pairings (tuples of teams)
            Each round has non-overlapping matches (no team plays twice)
            In each tuple, the first team (home) is the higher seed
        """
        if len(teams) != 4:
            raise ValueError(f"Expected 4 teams, got {len(teams)}")

        # Teams are already ordered by seed (0=highest, 3=lowest)
        # We need to preserve seed order for home field advantage
        # But we can randomize the pairing order

        # Create seed-to-team mapping
        team_seeds = {i: team for i, team in enumerate(teams)}

        # Standard round-robin using circle method with fixed seeds
        # Seed 0 is highest, always home against others
        seed_pairings = [
            # Round 1
            [(0, 1), (2, 3)],
            # Round 2
            [(0, 2), (1, 3)],
            # Round 3
            [(0, 3), (1, 2)]
        ]

        # Randomly shuffle the rounds themselves
        random.shuffle(seed_pairings)

        # Randomly shuffle the order of matches within each round
        for round_matches in seed_pairings:
            random.shuffle(round_matches)

        # Convert seed pairings to team pairings (higher seed always home)
        rounds = []
        for round_seed_pairs in seed_pairings:
            round_team_pairs = []
            for seed_home, seed_away in round_seed_pairs:
                # Higher seed (lower number) is always home
                if seed_home < seed_away:
                    round_team_pairs.append((team_seeds[seed_home], team_seeds[seed_away]))
                else:
                    round_team_pairs.append((team_seeds[seed_away], team_seeds[seed_home]))
            rounds.append(round_team_pairs)

        logger.info(f"Generated 3 rounds with 2 matches each for group (total 6 matches, higher seed always home)")
        return rounds

    def generate_round_robin_matches(
        self,
        group_a: List[Team],
        group_b: List[Team],
        week1_date: date,
        week2_date: date
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Generate RANDOMIZED round-robin matches for both weeks.
        Uses proper round-robin scheduling to prevent team conflicts.

        Week 1: 2 rounds per group (4 matches per group = 8 total)
        Week 2 Morning: 1 round per group (2 matches per group = 4 total)

        Args:
            group_a: List of 4 teams in Group A
            group_b: List of 4 teams in Group B
            week1_date: Date for Week 1 playoff matches
            week2_date: Date for Week 2 playoff matches

        Returns:
            Tuple of (week1_matches, week2_morning_matches)
            Each match is a dict with: home_team, away_team, date, time, location
        """
        week1_matches = []
        week2_morning_matches = []

        # Generate round-robin rounds for each group (3 rounds per group)
        # Each round has 2 matches with no team conflicts
        group_a_rounds = self._generate_group_round_robin(group_a)
        group_b_rounds = self._generate_group_round_robin(group_b)

        # Week 1 - Group A: First 2 rounds (4 matches) at 8:20 and 9:30
        # Round 1 at 8:20
        for i, (team1, team2) in enumerate(group_a_rounds[0]):
            week1_matches.append({
                'home_team': team1,
                'away_team': team2,
                'date': week1_date,
                'time': self.time_slots[0],  # 8:20
                'location': self.fields[i],
                'week_number': None,
                'playoff_round': 1,
                'group': 'A'
            })

        # Round 2 at 9:30
        for i, (team1, team2) in enumerate(group_a_rounds[1]):
            week1_matches.append({
                'home_team': team1,
                'away_team': team2,
                'date': week1_date,
                'time': self.time_slots[1],  # 9:30
                'location': self.fields[i],
                'week_number': None,
                'playoff_round': 1,
                'group': 'A'
            })

        # Week 1 - Group B: First 2 rounds (4 matches) at 10:40 and 11:50
        # Round 1 at 10:40
        for i, (team1, team2) in enumerate(group_b_rounds[0]):
            week1_matches.append({
                'home_team': team1,
                'away_team': team2,
                'date': week1_date,
                'time': self.time_slots[2],  # 10:40
                'location': self.fields[i],
                'week_number': None,
                'playoff_round': 1,
                'group': 'B'
            })

        # Round 2 at 11:50
        for i, (team1, team2) in enumerate(group_b_rounds[1]):
            week1_matches.append({
                'home_team': team1,
                'away_team': team2,
                'date': week1_date,
                'time': self.time_slots[3],  # 11:50
                'location': self.fields[i],
                'week_number': None,
                'playoff_round': 1,
                'group': 'B'
            })

        # Week 2 Morning - Group B: Last round (2 matches) at 8:20
        for i, (team1, team2) in enumerate(group_b_rounds[2]):
            week2_morning_matches.append({
                'home_team': team1,
                'away_team': team2,
                'date': week2_date,
                'time': self.time_slots[0],  # 8:20
                'location': self.fields[i],
                'week_number': None,
                'playoff_round': 2,
                'group': 'B'
            })

        # Week 2 Morning - Group A: Last round (2 matches) at 9:30
        for i, (team1, team2) in enumerate(group_a_rounds[2]):
            week2_morning_matches.append({
                'home_team': team1,
                'away_team': team2,
                'date': week2_date,
                'time': self.time_slots[1],  # 9:30
                'location': self.fields[i],
                'week_number': None,
                'playoff_round': 2,
                'group': 'A'
            })

        logger.info(f"Generated {len(week1_matches)} Week 1 matches and {len(week2_morning_matches)} Week 2 morning matches with conflict-free scheduling")

        return week1_matches, week2_morning_matches

    def calculate_group_standings(self, group_teams: List[Team], playoff_round: int) -> List[Team]:
        """
        Calculate standings for a playoff group based on match results.

        Args:
            group_teams: List of teams in the group
            playoff_round: Playoff round to consider (1 or 2)

        Returns:
            List of teams ordered by playoff standings (1st to 4th)
        """
        # Get all playoff matches for these teams
        team_ids = [t.id for t in group_teams]

        playoff_matches = self.session.query(Match).filter(
            Match.is_playoff_game == True,
            Match.playoff_round <= playoff_round,
            Match.home_team_id.in_(team_ids),
            Match.away_team_id.in_(team_ids)
        ).all()

        # Calculate points for each team
        team_stats = defaultdict(lambda: {'points': 0, 'gd': 0, 'gf': 0, 'ga': 0})

        for match in playoff_matches:
            if match.home_team_score is None or match.away_team_score is None:
                # Match not yet reported
                continue

            home_score = match.home_team_score
            away_score = match.away_team_score

            # Update stats
            team_stats[match.home_team_id]['gf'] += home_score
            team_stats[match.home_team_id]['ga'] += away_score
            team_stats[match.away_team_id]['gf'] += away_score
            team_stats[match.away_team_id]['ga'] += home_score

            # Award points (soccer: win=3, draw=1, loss=0)
            # Note: In playoffs there are PKs, so draws shouldn't happen, but handle them anyway
            if home_score > away_score:
                team_stats[match.home_team_id]['points'] += 3
            elif away_score > home_score:
                team_stats[match.away_team_id]['points'] += 3
            else:
                team_stats[match.home_team_id]['points'] += 1
                team_stats[match.away_team_id]['points'] += 1

            # Calculate goal difference
            team_stats[match.home_team_id]['gd'] = team_stats[match.home_team_id]['gf'] - team_stats[match.home_team_id]['ga']
            team_stats[match.away_team_id]['gd'] = team_stats[match.away_team_id]['gf'] - team_stats[match.away_team_id]['ga']

        # Sort teams by points, then goal difference, then random
        def sort_key(team):
            stats = team_stats[team.id]
            return (stats['points'], stats['gd'], stats['gf'], random.random())

        sorted_teams = sorted(group_teams, key=sort_key, reverse=True)

        logger.info(f"Group standings: {[(t.name, team_stats[t.id]['points']) for t in sorted_teams]}")

        return sorted_teams

    def get_existing_playoff_matches(self) -> List[Match]:
        """
        Get existing playoff matches that need to be updated.

        Finds ALL playoff matches (both placeholders and confirmed) for rounds 1 and 2.
        This prevents duplicate creation when regenerating the schedule.

        Returns:
            List of Match objects that are playoff matches
        """
        from app.models import Match, Schedule, Team

        # Find ALL playoff matches for rounds 1 and 2 (not just placeholders)
        # This prevents creating duplicates when regenerating
        matches = self.session.query(Match).join(
            Team, Match.home_team_id == Team.id
        ).filter(
            Team.league_id == self.league_id,
            Match.is_playoff_game == True,
            Match.playoff_round.in_([1, 2])  # Only Week 1 and Week 2 morning
        ).order_by(Match.date, Match.time).all()

        logger.info(f"Found {len(matches)} existing playoff matches (rounds 1-2)")
        return matches

    def update_existing_matches(
        self,
        generated_matches: List[Dict],
        existing_matches: List[Match]
    ) -> Tuple[List[Match], List[Match]]:
        """
        Update existing playoff matches with generated matchups.
        Creates new matches only if there aren't enough existing matches.

        Matches by date/time/location to prevent duplicates when regenerating.

        Args:
            generated_matches: List of generated match dicts
            existing_matches: List of existing Match objects to update

        Returns:
            Tuple of (updated_matches, created_matches)
        """
        from app.models import Schedule, Match
        from app.schedule_routes import ScheduleManager

        updated = []
        created = []

        # Group existing matches by (date, time, location) for efficient lookup
        existing_by_slot = {}
        for match in existing_matches:
            key = (match.date, match.time, match.location)
            if key not in existing_by_slot:
                existing_by_slot[key] = match
            else:
                # If there are duplicates, we'll update the first one and ignore the rest
                logger.warning(f"Found duplicate match at {key}, will use match {match.id}")

        # Update or create matches based on date/time/location slots
        for match_data in generated_matches:
            slot_key = (match_data['date'], match_data['time'], match_data['location'])

            if slot_key in existing_by_slot:
                # Update existing match at this slot
                match = existing_by_slot[slot_key]

                # Update match teams
                match.home_team_id = match_data['home_team'].id
                match.away_team_id = match_data['away_team'].id
                match.is_playoff_game = True
                match.playoff_round = match_data['playoff_round']
                match.week_type = 'PLAYOFF'

                # Update time/date/location if they changed
                match.time = match_data['time']
                match.date = match_data['date']
                match.location = match_data['location']

                # Update associated schedule entries
                # Find ALL schedules for this date/time/location (may still have old placeholder team IDs)
                schedules = self.session.query(Schedule).filter(
                    Schedule.date == match_data['date'],
                    Schedule.time == match_data['time'],
                    Schedule.location == match_data['location']
                ).all()

                # Update the schedules to have the correct team_id and opponent
                home_id = match_data['home_team'].id
                away_id = match_data['away_team'].id

                if len(schedules) >= 2:
                    # Update first schedule to be for home team
                    schedules[0].team_id = home_id
                    schedules[0].opponent = away_id
                    schedules[0].week = str(match_data['week_number'])
                    # Update second schedule to be for away team
                    schedules[1].team_id = away_id
                    schedules[1].opponent = home_id
                    schedules[1].week = str(match_data['week_number'])
                elif len(schedules) == 1:
                    # Only one schedule exists, update it for home team and create one for away
                    schedules[0].team_id = home_id
                    schedules[0].opponent = away_id
                    schedules[0].week = str(match_data['week_number'])
                    # Create schedule for away team
                    from app.models import Season
                    away_schedule = Schedule(
                        week=str(match_data['week_number']),
                        date=match_data['date'],
                        time=match_data['time'],
                        opponent=home_id,
                        location=match_data['location'],
                        team_id=away_id,
                        season_id=self.season_id
                    )
                    self.session.add(away_schedule)

                updated.append(match)
                logger.info(
                    f"Updated match {match.id}: {match_data['home_team'].name} vs "
                    f"{match_data['away_team'].name} at {match_data['time']}"
                )
            else:
                # Create new match if we don't have enough placeholders
                schedule_manager = ScheduleManager(self.session)

                match_dict = {
                    'team_a': match_data['home_team'].id,
                    'team_b': match_data['away_team'].id,
                    'match_date': match_data['date'],
                    'match_time': match_data['time'],
                    'field': match_data['location'],
                    'week': str(match_data['week_number']),
                    'season_id': self.season_id,
                    'week_type': 'PLAYOFF',
                    'is_special_week': False,
                    'is_playoff_game': True,
                    'playoff_round': match_data['playoff_round']
                }

                schedules, new_match = schedule_manager.create_match(match_dict)
                created.append(new_match)
                logger.info(
                    f"Created new match: {match_data['home_team'].name} vs "
                    f"{match_data['away_team'].name} at {match_data['time']}"
                )

        logger.info(f"Updated {len(updated)} matches, created {len(created)} new matches")
        return updated, created

    def generate_placement_matches(
        self,
        group_a: List[Team],
        group_b: List[Team],
        week2_date: date
    ) -> List[Dict]:
        """
        Generate placement matches for Week 2 afternoon.

        Should be called after Week 2 morning matches are completed.

        Args:
            group_a: List of 4 teams in Group A (ordered by standings)
            group_b: List of 4 teams in Group B (ordered by standings)
            week2_date: Date for Week 2 matches

        Returns:
            List of placement match dicts
        """
        placement_matches = []

        # Teams should already be sorted by standings (1st, 2nd, 3rd, 4th)
        a1, a2, a3, a4 = group_a
        b1, b2, b3, b4 = group_b

        # 10:40 - 3rd Place Game and 5th Place Game
        placement_matches.append({
            'home_team': a2,
            'away_team': b2,
            'date': week2_date,
            'time': self.time_slots[2],
            'location': self.fields[0],
            'description': '3rd Place Game',
            'week_number': None,
            'playoff_round': 2
        })
        placement_matches.append({
            'home_team': a3,
            'away_team': b3,
            'date': week2_date,
            'time': self.time_slots[2],
            'location': self.fields[1],
            'description': '5th Place Game',
            'week_number': None,
            'playoff_round': 2
        })

        # 11:50 - Championship and 7th Place Game
        placement_matches.append({
            'home_team': a1,
            'away_team': b1,
            'date': week2_date,
            'time': self.time_slots[3],
            'location': self.fields[0],
            'description': 'Championship',
            'week_number': None,
            'playoff_round': 2
        })
        placement_matches.append({
            'home_team': a4,
            'away_team': b4,
            'date': week2_date,
            'time': self.time_slots[3],
            'location': self.fields[1],
            'description': '7th Place Game',
            'week_number': None,
            'playoff_round': 2
        })

        logger.info(f"Generated {len(placement_matches)} placement matches")

        return placement_matches
