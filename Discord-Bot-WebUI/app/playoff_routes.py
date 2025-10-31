# app/playoff_routes.py

"""
Playoff Management Routes Module

This module provides routes for managing playoff assignments and scheduling.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, g
from flask_login import login_required, current_user

from app.decorators import role_required
from app.models import League, Team, Match, Schedule, Season, Standings, WeekConfiguration, ScheduledMessage, PlayerEvent, PlayerEventType, Player
from app.alert_helpers import show_success, show_error, show_warning
from app.playoff_generator import PlayoffGenerator
from app.schedule_routes import ScheduleManager

logger = logging.getLogger(__name__)

# Blueprint definition
playoff_bp = Blueprint('playoff', __name__, url_prefix='/admin/playoffs')


@playoff_bp.route('/league/<int:league_id>/manage', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_playoffs(league_id: int):
    """
    Show playoff management interface for a league.

    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)

    if not league:
        show_error('League not found')
        return redirect(url_for('auto_schedule.schedule_manager'))

    # Get playoff matches for this league
    playoff_matches = get_playoff_matches(session, league_id)

    # Get teams for this league
    teams = session.query(Team).filter_by(league_id=league_id).all()

    # Get current standings
    standings = get_league_standings(session, league_id)

    return render_template('admin/playoff_management.html',
                         league=league,
                         playoff_matches=playoff_matches,
                         teams=teams,
                         standings=standings,
                         title=f'Playoff Management - {league.name}')


@playoff_bp.route('/generator', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def playoff_generator_redirect():
    """
    Redirect to playoff generator for current season's Premier league.
    """
    session = g.db_session

    # Get current Pub League season
    from app.models import Season
    current_season = session.query(Season).filter_by(
        is_current=True,
        league_type='Pub League'
    ).first()

    if not current_season:
        show_error('No current Pub League season found')
        return redirect(url_for('auto_schedule.schedule_manager'))

    # Find Premier league in current season
    premier_league = session.query(League).filter_by(
        season_id=current_season.id,
        name='Premier'
    ).first()

    if not premier_league:
        show_error('Premier league not found in current season')
        return redirect(url_for('auto_schedule.schedule_manager'))

    return redirect(url_for('playoff.playoff_generator', league_id=premier_league.id))


@playoff_bp.route('/league/<int:league_id>/generator', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def playoff_generator(league_id: int):
    """
    Show automated playoff schedule generator interface.

    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)

    if not league:
        show_error('League not found')
        return redirect(url_for('auto_schedule.schedule_manager'))

    # Premier League only
    if league.name != 'Premier':
        show_error('Playoff generator is only available for Premier league')
        return redirect(url_for('auto_schedule.schedule_manager'))

    # Get current standings
    standings_list = get_league_standings(session, league_id)

    # Format standings for display
    standings = []
    for team in standings_list:
        standings.append({
            'team_name': team.name,
            'points': team.points if hasattr(team, 'points') else 0,
            'wins': team.wins if hasattr(team, 'wins') else 0,
            'losses': team.losses if hasattr(team, 'losses') else 0,
            'draws': team.draws if hasattr(team, 'draws') else 0,
            'goal_difference': team.goal_difference if hasattr(team, 'goal_difference') else 0
        })

    return render_template('admin/playoff_generator.html',
                         league=league,
                         standings=standings,
                         title=f'Playoff Generator - {league.name}')


@playoff_bp.route('/bracket', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def view_bracket_redirect():
    """
    Redirect to playoff bracket for current season's Premier league.
    """
    session = g.db_session

    # Get current Pub League season
    from app.models import Season
    current_season = session.query(Season).filter_by(
        is_current=True,
        league_type='Pub League'
    ).first()

    if not current_season:
        show_error('No current Pub League season found')
        return redirect(url_for('main.index'))

    # Find Premier league in current season
    premier_league = session.query(League).filter_by(
        season_id=current_season.id,
        name='Premier'
    ).first()

    if not premier_league:
        show_error('Premier league not found in current season')
        return redirect(url_for('main.index'))

    return redirect(url_for('playoff.view_bracket', league_id=premier_league.id))


@playoff_bp.route('/league/<int:league_id>/bracket', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def view_bracket(league_id: int):
    """
    View playoff bracket with match reporting capabilities.
    Optimized for mobile match reporting from the field.

    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)

    if not league:
        show_error('League not found')
        return redirect(url_for('main.index'))

    if not league.season:
        show_error('No active season found')
        return redirect(url_for('main.index'))

    # Get all playoff matches for this league
    playoff_matches = session.query(Match).join(
        Team, Match.home_team_id == Team.id
    ).filter(
        Team.league_id == league_id,
        Match.is_playoff_game == True
    ).order_by(Match.playoff_round, Match.date, Match.time).all()

    # Get all teams involved in playoffs for player dropdown
    playoff_team_ids = set()
    for match in playoff_matches:
        playoff_team_ids.add(match.home_team_id)
        playoff_team_ids.add(match.away_team_id)

    playoff_teams = session.query(Team).filter(Team.id.in_(playoff_team_ids)).all()

    # Build player choices for match reporting modals
    player_choices = {}
    for match in playoff_matches:
        # Get players from both teams
        home_players = session.query(Player).join(
            Player.teams
        ).filter(Team.id == match.home_team_id).all()

        away_players = session.query(Player).join(
            Player.teams
        ).filter(Team.id == match.away_team_id).all()

        player_choices[match.id] = {
            match.home_team.name if match.home_team else 'Home': {
                p.id: p.name for p in home_players
            },
            match.away_team.name if match.away_team else 'Away': {
                p.id: p.name for p in away_players
            }
        }

    # Get match events for each match (for editing)
    for match in playoff_matches:
        match.goal_scorers = session.query(PlayerEvent).filter_by(
            match_id=match.id,
            event_type=PlayerEventType.GOAL
        ).all()
        match.assists = session.query(PlayerEvent).filter_by(
            match_id=match.id,
            event_type=PlayerEventType.ASSIST
        ).all()
        match.yellow_cards = session.query(PlayerEvent).filter_by(
            match_id=match.id,
            event_type=PlayerEventType.YELLOW_CARD
        ).all()
        match.red_cards = session.query(PlayerEvent).filter_by(
            match_id=match.id,
            event_type=PlayerEventType.RED_CARD
        ).all()

    return render_template('playoff_bracket_view.html',
                         league=league,
                         season=league.season,
                         playoff_matches=playoff_matches,
                         player_choices=player_choices,
                         title=f'Playoff Bracket - {league.name}')


@playoff_bp.route('/league/<int:league_id>/assign', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def assign_playoff_matches(league_id: int):
    """
    Assign teams to playoff matches.
    
    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)
    
    if not league:
        show_error('League not found')
        return redirect(url_for('auto_schedule.schedule_manager'))
    
    try:
        # Get all playoff matches for this league
        playoff_matches = session.query(Match).join(
            Schedule, Match.schedule_id == Schedule.id
        ).join(
            Team, Schedule.team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True
        ).all()
        
        updates_made = 0
        
        for match in playoff_matches:
            home_team_key = f'home_team_{match.id}'
            away_team_key = f'away_team_{match.id}'
            description_key = f'description_{match.id}'
            
            if home_team_key in request.form and away_team_key in request.form:
                home_team_id = request.form[home_team_key]
                away_team_id = request.form[away_team_key]
                description = request.form.get(description_key, '')
                
                # Validate team assignments
                if home_team_id and away_team_id:
                    if home_team_id != away_team_id:
                        # Update match
                        match.home_team_id = int(home_team_id)
                        match.away_team_id = int(away_team_id)
                        match.notes = description
                        match.week_type = 'PLAYOFF'
                        match.is_playoff_game = True
                        updates_made += 1
                        
                        # Update associated schedule entries
                        home_schedule = session.query(Schedule).filter_by(
                            team_id=home_team_id,
                            week=match.schedule.week,
                            date=match.date
                        ).first()
                        if home_schedule:
                            home_schedule.opponent = int(away_team_id)
                        
                        away_schedule = session.query(Schedule).filter_by(
                            team_id=away_team_id,
                            week=match.schedule.week,
                            date=match.date
                        ).first()
                        if away_schedule:
                            away_schedule.opponent = int(home_team_id)
                    else:
                        show_warning(f'Cannot assign same team to both home and away for match {match.id}')
        
        session.commit()
        
        if updates_made > 0:
            show_success(f'Successfully assigned teams to {updates_made} playoff matches')
        else:
            show_warning('No playoff assignments were made')
            
    except Exception as e:
        logger.error(f"Error assigning playoff matches: {e}")
        session.rollback()
        show_error(f'Error assigning playoff matches: {str(e)}')
    
    return redirect(url_for('playoff.manage_playoffs', league_id=league_id))


@playoff_bp.route('/league/<int:league_id>/current-schedule', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def get_current_playoff_schedule(league_id: int):
    """
    Get the current playoff schedule if it exists.

    Returns the existing playoff schedule for display/editing.

    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)

    if not league:
        return jsonify({'success': False, 'error': 'League not found'}), 404

    if league.name != 'Premier':
        return jsonify({'success': False, 'error': 'Only available for Premier league'}), 400

    try:
        # Get existing playoff matches (non-placeholders)
        playoff_matches = session.query(Match).join(
            Team, Match.home_team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True,
            Match.home_team_id != Match.away_team_id,  # Not placeholders
            Match.playoff_round.in_([1, 2])  # Only Week 1 and Week 2 morning
        ).order_by(Match.date, Match.time).all()

        if not playoff_matches:
            return jsonify({'success': False, 'exists': False, 'message': 'No playoff schedule exists yet'})

        # Get teams from the matches to reconstruct groups
        playoff_team_ids = set()
        for match in playoff_matches:
            playoff_team_ids.add(match.home_team_id)
            playoff_team_ids.add(match.away_team_id)

        # Reconstruct groups by analyzing which teams play each other
        from collections import defaultdict
        team_opponents = defaultdict(set)
        for match in playoff_matches:
            team_opponents[match.home_team_id].add(match.away_team_id)
            team_opponents[match.away_team_id].add(match.home_team_id)

        # Find groups using BFS
        groups = []
        visited = set()
        for team_id in playoff_team_ids:
            if team_id in visited:
                continue
            group = set([team_id])
            queue = [team_id]
            visited.add(team_id)
            while queue:
                current = queue.pop(0)
                for opponent in team_opponents[current]:
                    if opponent not in visited:
                        visited.add(opponent)
                        group.add(opponent)
                        queue.append(opponent)
            groups.append(list(group))

        # Determine which group is A and which is B based on first match
        first_match = playoff_matches[0]
        group_a_ids = groups[0] if first_match.home_team_id in groups[0] else groups[1]
        group_b_ids = groups[1] if first_match.home_team_id in groups[0] else groups[0]

        group_a = [session.query(Team).get(tid) for tid in group_a_ids]
        group_b = [session.query(Team).get(tid) for tid in group_b_ids]

        # Format matches for display with deduplication
        matches_data = []
        seen_matches = set()  # Track unique matches by (date, time, home, away, location)

        for match in playoff_matches:
            # Skip matches that don't have valid teams loaded
            if not match.home_team or not match.away_team:
                logger.warning(f"Skipping match {match.id} - missing team data")
                continue

            # Skip if home and away are the same (placeholder)
            if match.home_team_id == match.away_team_id:
                logger.warning(f"Skipping match {match.id} - still a placeholder")
                continue

            # Create unique key for deduplication
            match_key = (
                match.date.isoformat() if match.date else '',
                match.time.strftime('%H:%M') if match.time else '',
                match.home_team_id,
                match.away_team_id,
                match.location or ''
            )

            # Skip if we've already seen this exact match
            if match_key in seen_matches:
                logger.warning(f"Skipping duplicate match {match.id}: {match.home_team.name} vs {match.away_team.name} at {match.time}")
                continue

            seen_matches.add(match_key)

            # Determine group based on team membership
            is_group_a = match.home_team_id in group_a_ids

            # Get week number from week configuration
            week_config = session.query(WeekConfiguration).filter_by(
                league_id=league_id,
                week_date=match.date
            ).first()

            matches_data.append({
                'week': f"Week {week_config.week_order}" if week_config else "Week ?",
                'week_number': week_config.week_order if week_config else None,
                'date': match.date.isoformat() if match.date else '',
                'time': match.time.strftime('%H:%M') if match.time else '',
                'home_team': match.home_team.name,
                'away_team': match.away_team.name,
                'location': match.location or '',
                'group': 'A' if is_group_a else 'B',
                'playoff_round': match.playoff_round
            })

        return jsonify({
            'success': True,
            'exists': True,
            'preview': {
                'group_a': [{'id': t.id, 'name': t.name} for t in group_a],
                'group_b': [{'id': t.id, 'name': t.name} for t in group_b],
                'matches': matches_data
            }
        })

    except Exception as e:
        logger.error(f"Error fetching current playoff schedule: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playoff_bp.route('/league/<int:league_id>/preview-schedule', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def preview_playoff_schedule(league_id: int):
    """
    Preview playoff schedule without committing changes.

    Returns the generated schedule for review before final confirmation.

    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)

    if not league:
        return jsonify({'success': False, 'error': 'League not found'}), 404

    # Premier League only check
    if league.name != 'Premier':
        return jsonify({
            'success': False,
            'error': 'Playoff generation is only available for Premier league'
        }), 400

    if not league.season:
        return jsonify({'success': False, 'error': 'No active season found'}), 400

    try:
        # Initialize playoff generator
        generator = PlayoffGenerator(league_id, league.season.id, session)

        # Get top 8 teams
        top_teams = generator.get_top_teams_with_tiebreaking(8)

        if len(top_teams) < 8:
            return jsonify({
                'success': False,
                'error': f'Not enough teams for playoffs. Need 8 teams, found {len(top_teams)}'
            }), 400

        # Create playoff groups
        group_a, group_b = generator.create_playoff_groups(top_teams)

        # Get playoff week dates from actual playoff matches (not week_configurations)
        # This handles MIXED weeks where Premier has playoffs but Classic doesn't
        # Note: We look for ALL playoff matches, not just placeholders, to handle regeneration
        from sqlalchemy import distinct
        playoff_dates = session.query(distinct(Match.date)).join(
            Team, Match.home_team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True
        ).order_by(Match.date).all()

        playoff_dates = [d[0] for d in playoff_dates]

        if len(playoff_dates) < 2:
            return jsonify({
                'success': False,
                'error': f'Need at least 2 playoff weeks with placeholder matches. Found {len(playoff_dates)} weeks.'
            }), 400

        week1_date = playoff_dates[0]
        week2_date = playoff_dates[1]

        # Get week numbers for the playoff dates
        week1_config = session.query(WeekConfiguration).filter_by(
            league_id=league_id,
            week_date=week1_date
        ).first()
        week2_config = session.query(WeekConfiguration).filter_by(
            league_id=league_id,
            week_date=week2_date
        ).first()

        # Generate round-robin matches (randomized)
        week1_matches, week2_morning_matches = generator.generate_round_robin_matches(
            group_a, group_b, week1_date, week2_date
        )

        # Set week numbers
        for match in week1_matches:
            match['week_number'] = week1_config.week_order if week1_config else None
        for match in week2_morning_matches:
            match['week_number'] = week2_config.week_order if week2_config else None

        # Format matches for preview
        all_matches = week1_matches + week2_morning_matches

        preview_data = {
            'group_a': [{'id': t.id, 'name': t.name} for t in group_a],
            'group_b': [{'id': t.id, 'name': t.name} for t in group_b],
            'standings': [
                {
                    'position': i + 1,
                    'team_name': t.name,
                    'team_id': t.id,
                    'group': 'A' if t in group_a else 'B'
                }
                for i, t in enumerate(top_teams)
            ],
            'matches': [
                {
                    'week': f"Week {m['week_number']}",
                    'date': m['date'].isoformat(),
                    'time': m['time'].strftime('%H:%M'),
                    'home_team': m['home_team'].name,
                    'away_team': m['away_team'].name,
                    'location': m['location'],
                    'group': m.get('group', ''),
                    'playoff_round': m['playoff_round']
                }
                for m in all_matches
            ]
        }

        logger.info(f"Generated playoff schedule preview for league {league_id}")

        return jsonify({
            'success': True,
            'preview': preview_data
        })

    except Exception as e:
        logger.error(f"Error generating playoff schedule preview: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playoff_bp.route('/league/<int:league_id>/generate-schedule', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def generate_playoff_schedule(league_id: int):
    """
    Generate and COMMIT full playoff schedule (Week 1 + Week 2 morning matches).

    This updates existing placeholder matches with the actual matchups.

    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)

    if not league:
        return jsonify({'success': False, 'error': 'League not found'}), 404

    # Premier League only check
    if league.name != 'Premier':
        return jsonify({
            'success': False,
            'error': 'Playoff generation is only available for Premier league'
        }), 400

    if not league.season:
        return jsonify({'success': False, 'error': 'No active season found'}), 400

    try:
        # Initialize playoff generator
        generator = PlayoffGenerator(league_id, league.season.id, session)

        # Get existing playoff matches (both placeholders and already-updated matches)
        # This allows regeneration after initial schedule has been applied
        existing_matches = session.query(Match).join(
            Team, Match.home_team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True,
            Match.playoff_round.in_([1, 2])  # Only Week 1 and Week 2 morning matches
        ).order_by(Match.date, Match.time).all()

        if not existing_matches:
            return jsonify({
                'success': False,
                'error': 'No existing playoff matches found. Please create playoff matches first.'
            }), 400

        # Get top 8 teams with tie-breaking
        top_teams = generator.get_top_teams_with_tiebreaking(8)

        if len(top_teams) < 8:
            return jsonify({
                'success': False,
                'error': f'Not enough teams for playoffs. Need 8 teams, found {len(top_teams)}'
            }), 400

        # Create playoff groups (randomized)
        group_a, group_b = generator.create_playoff_groups(top_teams)

        # Get playoff week dates from actual playoff matches
        # Look for ALL playoff matches, not just placeholders
        from sqlalchemy import distinct
        playoff_dates = session.query(distinct(Match.date)).join(
            Team, Match.home_team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True
        ).order_by(Match.date).all()

        playoff_dates = [d[0] for d in playoff_dates]

        if len(playoff_dates) < 2:
            return jsonify({
                'success': False,
                'error': f'Need at least 2 playoff weeks with placeholder matches. Found {len(playoff_dates)} weeks.'
            }), 400

        week1_date = playoff_dates[0]
        week2_date = playoff_dates[1]

        # Get week numbers for the playoff dates
        week1_config = session.query(WeekConfiguration).filter_by(
            league_id=league_id,
            week_date=week1_date
        ).first()
        week2_config = session.query(WeekConfiguration).filter_by(
            league_id=league_id,
            week_date=week2_date
        ).first()

        # Generate round-robin matches (randomized within groups)
        week1_matches, week2_morning_matches = generator.generate_round_robin_matches(
            group_a, group_b, week1_date, week2_date
        )

        # Set week numbers
        for match in week1_matches:
            match['week_number'] = week1_config.week_order if week1_config else None
        for match in week2_morning_matches:
            match['week_number'] = week2_config.week_order if week2_config else None

        all_matches = week1_matches + week2_morning_matches

        # Update existing placeholder matches (and create new ones if needed)
        updated_matches, created_matches = generator.update_existing_matches(all_matches, existing_matches)

        session.commit()

        total_count = len(updated_matches) + len(created_matches)
        logger.info(f"Updated {len(updated_matches)} matches, created {len(created_matches)} matches for league {league_id}")

        message_parts = []
        if updated_matches:
            message_parts.append(f'Updated {len(updated_matches)} existing matches')
        if created_matches:
            message_parts.append(f'Created {len(created_matches)} new matches')

        return jsonify({
            'success': True,
            'message': f'Successfully {" and ".join(message_parts)}',
            'updated_count': len(updated_matches),
            'created_count': len(created_matches),
            'total_count': total_count,
            'group_a': [t.name for t in group_a],
            'group_b': [t.name for t in group_b]
        })

    except Exception as e:
        logger.error(f"Error generating playoff schedule: {e}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@playoff_bp.route('/league/<int:league_id>/apply-schedule', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def apply_playoff_schedule(league_id: int):
    """
    Apply edited playoff schedule from preview.

    Accepts the edited match data from the frontend and updates the database.

    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)

    if not league:
        return jsonify({'success': False, 'error': 'League not found'}), 404

    if not league.season:
        return jsonify({'success': False, 'error': 'No active season found'}), 400

    try:
        data = request.get_json()
        matches_data = data.get('matches', [])

        if not matches_data:
            return jsonify({'success': False, 'error': 'No match data provided'}), 400

        # Get existing playoff matches (both placeholders and already-updated matches)
        # This allows re-applying/regenerating after initial schedule has been applied
        existing_matches = session.query(Match).join(
            Team, Match.home_team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True,
            Match.playoff_round.in_([1, 2])  # Only Week 1 and Week 2 morning matches
        ).order_by(Match.date, Match.time).all()

        if len(existing_matches) < len(matches_data):
            return jsonify({
                'success': False,
                'error': f'Not enough placeholder matches. Found {len(existing_matches)}, need {len(matches_data)}'
            }), 400

        # Create a lookup of team names to IDs
        all_teams = session.query(Team).filter_by(league_id=league_id).all()
        team_lookup = {team.name: team.id for team in all_teams}

        # Update matches
        updated_count = 0
        for i, match_data in enumerate(matches_data):
            if i >= len(existing_matches):
                break

            match = existing_matches[i]
            home_team_name = match_data.get('home_team')
            away_team_name = match_data.get('away_team')

            if home_team_name not in team_lookup or away_team_name not in team_lookup:
                logger.error(f"Team not found: {home_team_name} or {away_team_name}")
                continue

            # Update match
            home_id = team_lookup[home_team_name]
            away_id = team_lookup[away_team_name]
            match.home_team_id = home_id
            match.away_team_id = away_id
            match.is_playoff_game = True
            match.playoff_round = match_data.get('playoff_round', 1)
            match.week_type = 'PLAYOFF'

            # Update date/time/location if provided
            if 'date' in match_data:
                from datetime import datetime
                match.date = datetime.strptime(match_data['date'], '%Y-%m-%d').date()
            if 'time' in match_data:
                from datetime import datetime
                match.time = datetime.strptime(match_data['time'], '%H:%M').time()
            if 'location' in match_data:
                match.location = match_data['location']

            # Update associated Schedule records so team pages show correct opponents
            # Find ALL schedules for this match's date/time (they might still have old placeholder team IDs)
            schedules = session.query(Schedule).filter(
                Schedule.date == match.date,
                Schedule.time == match.time,
                Schedule.location == match.location
            ).all()

            # Update the schedules to have the correct team_id and opponent
            if len(schedules) >= 2:
                # Update first schedule to be for home team
                schedules[0].team_id = home_id
                schedules[0].opponent = away_id
                # Update second schedule to be for away team
                schedules[1].team_id = away_id
                schedules[1].opponent = home_id
            elif len(schedules) == 1:
                # Only one schedule exists (placeholder scenario), update it for home team
                schedules[0].team_id = home_id
                schedules[0].opponent = away_id
                # Create schedule for away team
                away_schedule = Schedule(
                    week=schedules[0].week,
                    date=match.date,
                    time=match.time,
                    opponent=home_id,
                    location=match.location,
                    team_id=away_id,
                    season_id=league.season.id
                )
                session.add(away_schedule)

            updated_count += 1

        session.commit()

        logger.info(f"Applied edited playoff schedule for league {league_id}: {updated_count} matches updated")

        return jsonify({
            'success': True,
            'message': f'Successfully updated {updated_count} playoff matches',
            'updated_count': updated_count
        })

    except Exception as e:
        logger.error(f"Error applying playoff schedule: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@playoff_bp.route('/league/<int:league_id>/resend-playoff-rsvps', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def resend_playoff_rsvps(league_id: int):
    """
    Resend RSVP messages for playoff matches.

    Creates new ScheduledMessage records and queues them to send immediately.
    Use this if playoff schedule was updated after RSVPs were already sent.

    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)

    if not league:
        return jsonify({'success': False, 'error': 'League not found'}), 404

    if not league.season:
        return jsonify({'success': False, 'error': 'No active season found'}), 400

    try:
        # Get Week 1 playoff matches only (Week 2 will send via normal scheduled process)
        playoff_matches = session.query(Match).join(
            Team, Match.home_team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True,
            Match.playoff_round == 1,  # Only Week 1
            Match.home_team_id != Match.away_team_id  # Not placeholders
        ).all()

        if not playoff_matches:
            return jsonify({
                'success': False,
                'error': 'No playoff matches found to resend RSVPs for'
            }), 400

        created_messages = []

        for match in playoff_matches:
            # Create new ScheduledMessage for immediate sending
            scheduled_message = ScheduledMessage(
                match_id=match.id,
                message_type='AVAILABILITY',
                scheduled_send_time=datetime.utcnow(),  # Send immediately
                status='PENDING'
            )
            session.add(scheduled_message)
            session.flush()  # Get the ID
            created_messages.append(scheduled_message)

        session.commit()

        # Queue all messages to send immediately
        from app.tasks.tasks_rsvp import send_availability_message
        for msg in created_messages:
            send_availability_message.apply_async(
                kwargs={'scheduled_message_id': msg.id},
                countdown=5
            )

        # Also update the Match records with notification status
        for match in playoff_matches:
            match.last_discord_notification = datetime.utcnow()
            match.notification_status = 'resent'

        session.commit()

        logger.info(f"Queued {len(created_messages)} playoff RSVP messages to resend for league {league_id}")

        return jsonify({
            'success': True,
            'message': f'Successfully queued {len(created_messages)} RSVP messages to resend',
            'count': len(created_messages)
        })

    except Exception as e:
        logger.error(f"Error resending playoff RSVPs: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@playoff_bp.route('/league/<int:league_id>/generate-placement-games', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def generate_placement_games(league_id: int):
    """
    Generate placement games for Week 2 afternoon.

    Should be called after Week 2 morning matches are completed.

    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)

    if not league:
        return jsonify({'success': False, 'error': 'League not found'}), 404

    if not league.season:
        return jsonify({'success': False, 'error': 'No active season found'}), 400

    try:
        # Initialize playoff generator
        generator = PlayoffGenerator(league_id, league.season.id, session)

        # Get all playoff matches to determine groups
        playoff_matches = session.query(Match).filter(
            Match.is_playoff_game == True,
            Match.playoff_round == 1
        ).join(Team, Match.home_team_id == Team.id).filter(
            Team.league_id == league_id
        ).all()

        if not playoff_matches:
            return jsonify({
                'success': False,
                'error': 'No playoff matches found. Generate playoff schedule first.'
            }), 400

        # Extract teams from playoff matches to reconstruct groups
        # We need to figure out which teams are in which group
        # This is a bit tricky - we'll need to look at who plays whom

        # Get all unique teams in playoffs
        playoff_team_ids = set()
        for match in playoff_matches:
            playoff_team_ids.add(match.home_team_id)
            playoff_team_ids.add(match.away_team_id)

        # Reconstruct groups by looking at match patterns
        # Teams that play each other are in the same group
        from collections import defaultdict
        team_opponents = defaultdict(set)

        for match in playoff_matches:
            team_opponents[match.home_team_id].add(match.away_team_id)
            team_opponents[match.away_team_id].add(match.home_team_id)

        # Find connected components (groups)
        groups = []
        visited = set()

        for team_id in playoff_team_ids:
            if team_id in visited:
                continue

            # BFS to find all teams in this group
            group = set([team_id])
            queue = [team_id]
            visited.add(team_id)

            while queue:
                current = queue.pop(0)
                for opponent in team_opponents[current]:
                    if opponent not in visited:
                        visited.add(opponent)
                        group.add(opponent)
                        queue.append(opponent)

            groups.append(list(group))

        if len(groups) != 2:
            return jsonify({
                'success': False,
                'error': f'Expected 2 playoff groups, found {len(groups)}'
            }), 400

        # Convert team IDs to Team objects
        group_a_teams = [session.query(Team).get(tid) for tid in groups[0]]
        group_b_teams = [session.query(Team).get(tid) for tid in groups[1]]

        # Calculate group standings
        group_a_sorted = generator.calculate_group_standings(group_a_teams, playoff_round=2)
        group_b_sorted = generator.calculate_group_standings(group_b_teams, playoff_round=2)

        # Get Week 2 date from actual playoff matches
        from sqlalchemy import distinct
        playoff_dates = session.query(distinct(Match.date)).join(
            Team, Match.home_team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True
        ).order_by(Match.date).all()

        playoff_dates = [d[0] for d in playoff_dates]

        if len(playoff_dates) < 2:
            return jsonify({
                'success': False,
                'error': f'Need at least 2 playoff weeks with placeholder matches. Found {len(playoff_dates)} weeks.'
            }), 400

        week2_date = playoff_dates[1]

        # Generate placement matches
        placement_matches = generator.generate_placement_matches(
            group_a_sorted, group_b_sorted, week2_date
        )

        # Create matches using ScheduleManager
        schedule_manager = ScheduleManager(session)
        created_matches = []

        for match_data in placement_matches:
            match_dict = {
                'team_a': match_data['home_team'].id,
                'team_b': match_data['away_team'].id,
                'match_date': match_data['date'],
                'match_time': match_data['time'],
                'field': match_data['location'],
                'week': str(match_data['week_number']),
                'season_id': league.season.id,
                'week_type': 'PLAYOFF',
                'is_special_week': False,
                'is_playoff_game': True,
                'playoff_round': match_data['playoff_round'],
                'notes': match_data.get('description', '')
            }

            try:
                schedules, match = schedule_manager.create_match(match_dict)
                created_matches.append(match)
            except Exception as e:
                logger.error(f"Error creating placement match: {e}")
                raise

        session.commit()

        logger.info(f"Generated {len(created_matches)} placement matches for league {league_id}")

        return jsonify({
            'success': True,
            'message': f'Successfully generated {len(created_matches)} placement matches'
        })

    except Exception as e:
        logger.error(f"Error generating placement games: {e}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@playoff_bp.route('/league/<int:league_id>/auto-assign', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def auto_assign_playoffs(league_id: int):
    """
    Auto-assign playoff teams based on current standings.
    
    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)
    
    if not league:
        return jsonify({'success': False, 'error': 'League not found'}), 404
    
    try:
        # Get current standings
        standings = get_league_standings(session, league_id)
        
        if len(standings) < 4:
            return jsonify({'success': False, 'error': 'Not enough teams for playoffs (minimum 4 required)'}), 400
        
        # Get playoff matches ordered by week and time
        playoff_matches = session.query(Match).join(
            Schedule, Match.schedule_id == Schedule.id
        ).join(
            Team, Schedule.team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True
        ).order_by(Match.date, Match.time).all()
        
        if not playoff_matches:
            return jsonify({'success': False, 'error': 'No playoff matches found'}), 400
        
        # Assign teams based on league type
        if league.name == 'Premier':
            # Premier: 2 weeks, 3 matches total
            # Week 1: #1 vs #4, #2 vs #3
            # Week 2: Winner vs Winner (will be manually set later)
            if len(playoff_matches) >= 2:
                # Semifinal 1: #1 vs #4
                playoff_matches[0].home_team_id = standings[0].id
                playoff_matches[0].away_team_id = standings[3].id
                playoff_matches[0].notes = 'Semifinal #1'
                
                # Semifinal 2: #2 vs #3
                playoff_matches[1].home_team_id = standings[1].id
                playoff_matches[1].away_team_id = standings[2].id
                playoff_matches[1].notes = 'Semifinal #2'
                
                # Final match (if exists) - leave as TBD
                if len(playoff_matches) >= 3:
                    playoff_matches[2].notes = 'Championship Final - TBD'
                    
        else:  # Classic
            # Classic: 1 week, 2 matches
            # Match 1: #1 vs #2, Match 2: #3 vs #4
            if len(playoff_matches) >= 2:
                # Championship match 1: #1 vs #2
                playoff_matches[0].home_team_id = standings[0].id
                playoff_matches[0].away_team_id = standings[1].id
                playoff_matches[0].notes = 'Championship Match #1'
                
                # Championship match 2: #3 vs #4
                playoff_matches[1].home_team_id = standings[2].id
                playoff_matches[1].away_team_id = standings[3].id
                playoff_matches[1].notes = 'Championship Match #2'
        
        # Update all assigned matches
        for match in playoff_matches:
            match.week_type = 'PLAYOFF'
            match.is_playoff_game = True
        
        session.commit()
        
        return jsonify({'success': True, 'message': 'Playoff teams auto-assigned based on standings'})
        
    except Exception as e:
        logger.error(f"Error auto-assigning playoffs: {e}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# API Blueprint for public/player-facing endpoints
from flask import Blueprint
api_playoffs_bp = Blueprint('api_playoffs', __name__, url_prefix='/api/playoffs')


@api_playoffs_bp.route('/bracket/<int:league_id>', methods=['GET'])
@login_required
def get_bracket_data(league_id: int):
    """
    Get playoff bracket data for frontend display.

    Returns group stage matches, standings, and placement finals.

    Args:
        league_id: ID of the league
    """
    session = g.db_session
    league = session.query(League).get(league_id)

    if not league or not league.season:
        return jsonify({'success': False, 'error': 'League or season not found'}), 404

    try:
        # Get all playoff matches for this league
        playoff_matches = session.query(Match).join(
            Team, Match.home_team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True
        ).order_by(Match.playoff_round, Match.date, Match.time).all()

        if not playoff_matches:
            return jsonify({
                'success': True,
                'groupA': None,
                'groupB': None,
                'placementMatches': [],
                'status': 'not_started'
            })

        # Separate matches by round
        group_stage_matches = [m for m in playoff_matches if m.playoff_round in [1, 2] and not (m.notes and any(word in m.notes.lower() for word in ['championship', 'place']))]
        placement_matches = [m for m in playoff_matches if m.notes and any(word in m.notes.lower() for word in ['championship', 'place'])]

        # Extract teams and reconstruct groups
        playoff_team_ids = set()
        for match in group_stage_matches:
            playoff_team_ids.add(match.home_team_id)
            playoff_team_ids.add(match.away_team_id)

        # Build opponent mapping
        from collections import defaultdict
        team_opponents = defaultdict(set)
        for match in group_stage_matches:
            team_opponents[match.home_team_id].add(match.away_team_id)
            team_opponents[match.away_team_id].add(match.home_team_id)

        # Find groups using BFS
        groups = []
        visited = set()
        for team_id in playoff_team_ids:
            if team_id in visited:
                continue
            group = set([team_id])
            queue = [team_id]
            visited.add(team_id)
            while queue:
                current = queue.pop(0)
                for opponent in team_opponents[current]:
                    if opponent not in visited:
                        visited.add(opponent)
                        group.add(opponent)
                        queue.append(opponent)
            groups.append(list(group))

        if len(groups) < 2:
            # Groups not yet established - return empty data
            return jsonify({
                'success': True,
                'groupA': None,
                'groupB': None,
                'placementMatches': [],
                'status': 'not_started'
            })

        # Convert to Team objects
        group_a_teams = [session.query(Team).get(tid) for tid in groups[0]]
        group_b_teams = [session.query(Team).get(tid) for tid in groups[1]]

        # Calculate standings for each group
        generator = PlayoffGenerator(league_id, league.season.id, session)

        # Determine which round to use for standings calculation
        max_round_reported = 1
        for match in group_stage_matches:
            if match.home_team_score is not None and match.away_team_score is not None:
                max_round_reported = max(max_round_reported, match.playoff_round or 1)

        group_a_standings = generator.calculate_group_standings(group_a_teams, playoff_round=max_round_reported)
        group_b_standings = generator.calculate_group_standings(group_b_teams, playoff_round=max_round_reported)

        # Calculate detailed stats for standings
        def calculate_standings_dict(teams, group_name):
            standings_list = []
            for team in teams:
                # Calculate stats from playoff matches
                team_matches = [m for m in group_stage_matches if m.home_team_id == team.id or m.away_team_id == team.id]

                points = 0
                goals_for = 0
                goals_against = 0

                for match in team_matches:
                    if match.home_team_score is None or match.away_team_score is None:
                        continue

                    if match.home_team_id == team.id:
                        goals_for += match.home_team_score
                        goals_against += match.away_team_score
                        if match.home_team_score > match.away_team_score:
                            points += 3
                        elif match.home_team_score == match.away_team_score:
                            points += 1
                    else:
                        goals_for += match.away_team_score
                        goals_against += match.home_team_score
                        if match.away_team_score > match.home_team_score:
                            points += 3
                        elif match.away_team_score == match.home_team_score:
                            points += 1

                goal_difference = goals_for - goals_against

                standings_list.append({
                    'team_id': team.id,
                    'team_name': team.name,
                    'points': points,
                    'goals_for': goals_for,
                    'goals_against': goals_against,
                    'goal_difference': goal_difference
                })

            # Sort by points, then GD, then GF
            standings_list.sort(key=lambda x: (x['points'], x['goal_difference'], x['goals_for']), reverse=True)
            return standings_list

        group_a_standings_dict = calculate_standings_dict(group_a_teams, 'A')
        group_b_standings_dict = calculate_standings_dict(group_b_teams, 'B')

        # Format matches
        def format_match(match):
            return {
                'id': match.id,
                'home_team_id': match.home_team_id,
                'home_team_name': match.home_team.name if match.home_team else 'TBD',
                'away_team_id': match.away_team_id,
                'away_team_name': match.away_team.name if match.away_team else 'TBD',
                'home_team_score': match.home_team_score,
                'away_team_score': match.away_team_score,
                'date': match.date.isoformat() if match.date else None,
                'time': match.time.strftime('%H:%M') if match.time else None,
                'location': match.location,
                'playoff_round': match.playoff_round,
                'description': match.notes or ''
            }

        # Separate group stage matches by group
        group_a_match_list = [format_match(m) for m in group_stage_matches if m.home_team_id in groups[0]]
        group_b_match_list = [format_match(m) for m in group_stage_matches if m.home_team_id in groups[1]]

        # Format placement matches
        placement_match_list = [format_match(m) for m in placement_matches]

        # Determine overall status
        group_stage_complete = all(
            m.home_team_score is not None and m.away_team_score is not None
            for m in group_stage_matches
        )

        if placement_matches and all(m.home_team_score is not None and m.away_team_score is not None for m in placement_matches):
            status = 'completed'
        elif placement_matches:
            status = 'placement_finals'
        elif group_stage_complete:
            status = 'week2_morning'
        elif any(m.playoff_round == 2 for m in group_stage_matches):
            status = 'week2_morning'
        else:
            status = 'group_stage'

        return jsonify({
            'success': True,
            'groupA': {
                'teams': [{'id': t.id, 'name': t.name} for t in group_a_teams],
                'matches': group_a_match_list,
                'standings': group_a_standings_dict
            },
            'groupB': {
                'teams': [{'id': t.id, 'name': t.name} for t in group_b_teams],
                'matches': group_b_match_list,
                'standings': group_b_standings_dict
            },
            'placementMatches': placement_match_list,
            'status': status
        })

    except Exception as e:
        logger.error(f"Error fetching bracket data: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


def get_playoff_matches(session, league_id: int) -> Dict[str, List[Match]]:
    """
    Get playoff matches organized by week.
    
    Args:
        session: Database session
        league_id: ID of the league
        
    Returns:
        Dictionary with week names as keys and lists of matches as values
    """
    matches = session.query(Match).join(
        Schedule, Match.schedule_id == Schedule.id
    ).join(
        Team, Schedule.team_id == Team.id
    ).filter(
        Team.league_id == league_id,
        Match.is_playoff_game == True
    ).order_by(Match.date, Match.time).all()
    
    # Group matches by week
    weeks = {}
    for match in matches:
        schedule = session.query(Schedule).get(match.schedule_id)
        if schedule:
            week_key = f"Week {schedule.week}"
            if week_key not in weeks:
                weeks[week_key] = []
            weeks[week_key].append(match)
    
    return weeks


def check_and_generate_placement_games(session, match: Match) -> bool:
    """
    Check if placement games should be auto-generated after a match is reported.

    This is called after each playoff match is reported. It checks if:
    1. The match is a playoff round 2 match (Week 2 morning)
    2. All other playoff round 2 matches are complete
    3. Placement games haven't already been generated

    If all conditions are met, it automatically generates the placement games.

    Args:
        session: Database session
        match: The match that was just reported

    Returns:
        True if placement games were generated, False otherwise
    """
    try:
        # Only check if this is a playoff round 2 match
        if not match.is_playoff_game or match.playoff_round != 2:
            return False

        # Get the league from the match
        league = match.home_team.league if match.home_team else None
        if not league or not league.season:
            return False

        league_id = league.id
        season_id = league.season.id

        # Check if all playoff round 2 matches are complete (have scores)
        round_2_matches = session.query(Match).filter(
            Match.is_playoff_game == True,
            Match.playoff_round == 2
        ).join(Team, Match.home_team_id == Team.id).filter(
            Team.league_id == league_id
        ).all()

        # Check if there are any incomplete round 2 matches (except placement games which have descriptions)
        incomplete_matches = [
            m for m in round_2_matches
            if (m.home_team_score is None or m.away_team_score is None)
            and not m.notes  # Placement games have descriptions in notes
        ]

        if incomplete_matches:
            logger.info(f"{len(incomplete_matches)} playoff round 2 matches still incomplete. Not generating placement games yet.")
            return False

        # Check if placement games already exist
        placement_games = session.query(Match).filter(
            Match.is_playoff_game == True,
            Match.playoff_round == 2,
            Match.notes.in_(['Championship', '3rd Place Game', '5th Place Game', '7th Place Game'])
        ).join(Team, Match.home_team_id == Team.id).filter(
            Team.league_id == league_id
        ).count()

        if placement_games > 0:
            logger.info("Placement games already exist. Skipping generation.")
            return False

        # All conditions met - generate placement games!
        logger.info(f"All playoff round 2 matches complete. Auto-generating placement games for league {league_id}")

        # Initialize playoff generator
        generator = PlayoffGenerator(league_id, season_id, session)

        # Get all playoff matches to determine groups
        playoff_matches = session.query(Match).filter(
            Match.is_playoff_game == True,
            Match.playoff_round == 1
        ).join(Team, Match.home_team_id == Team.id).filter(
            Team.league_id == league_id
        ).all()

        # Reconstruct groups from playoff matches
        playoff_team_ids = set()
        for m in playoff_matches:
            playoff_team_ids.add(m.home_team_id)
            playoff_team_ids.add(m.away_team_id)

        # Build opponent mapping
        from collections import defaultdict
        team_opponents = defaultdict(set)
        for m in playoff_matches:
            team_opponents[m.home_team_id].add(m.away_team_id)
            team_opponents[m.away_team_id].add(m.home_team_id)

        # Find groups using BFS
        groups = []
        visited = set()
        for team_id in playoff_team_ids:
            if team_id in visited:
                continue
            group = set([team_id])
            queue = [team_id]
            visited.add(team_id)
            while queue:
                current = queue.pop(0)
                for opponent in team_opponents[current]:
                    if opponent not in visited:
                        visited.add(opponent)
                        group.add(opponent)
                        queue.append(opponent)
            groups.append(list(group))

        if len(groups) != 2:
            logger.error(f"Expected 2 playoff groups, found {len(groups)}. Cannot generate placement games.")
            return False

        # Convert to Team objects and calculate standings
        group_a_teams = [session.query(Team).get(tid) for tid in groups[0]]
        group_b_teams = [session.query(Team).get(tid) for tid in groups[1]]

        group_a_sorted = generator.calculate_group_standings(group_a_teams, playoff_round=2)
        group_b_sorted = generator.calculate_group_standings(group_b_teams, playoff_round=2)

        # Get Week 2 date from actual playoff matches
        from sqlalchemy import distinct
        playoff_dates = session.query(distinct(Match.date)).join(
            Team, Match.home_team_id == Team.id
        ).filter(
            Team.league_id == league_id,
            Match.is_playoff_game == True
        ).order_by(Match.date).all()

        playoff_dates = [d[0] for d in playoff_dates]

        if len(playoff_dates) < 2:
            logger.error(f"Need at least 2 playoff weeks with placeholder matches. Found {len(playoff_dates)} weeks.")
            return False

        week2_date = playoff_dates[1]

        # Generate placement matches
        placement_matches = generator.generate_placement_matches(
            group_a_sorted, group_b_sorted, week2_date
        )

        # Create matches
        schedule_manager = ScheduleManager(session)
        created_count = 0

        for match_data in placement_matches:
            match_dict = {
                'team_a': match_data['home_team'].id,
                'team_b': match_data['away_team'].id,
                'match_date': match_data['date'],
                'match_time': match_data['time'],
                'field': match_data['location'],
                'week': str(match_data['week_number']),
                'season_id': season_id,
                'week_type': 'PLAYOFF',
                'is_special_week': False,
                'is_playoff_game': True,
                'playoff_round': match_data['playoff_round'],
                'notes': match_data.get('description', '')
            }

            schedules, created_match = schedule_manager.create_match(match_dict)
            created_count += 1

        logger.info(f"Auto-generated {created_count} placement matches for league {league_id}")
        return True

    except Exception as e:
        logger.error(f"Error auto-generating placement games: {e}", exc_info=True)
        return False


def get_league_standings(session, league_id: int) -> List[Team]:
    """
    Get current standings for a league.

    Args:
        session: Database session
        league_id: ID of the league

    Returns:
        List of teams ordered by standings
    """
    # Get league and current season
    league = session.query(League).get(league_id)
    if not league or not league.season:
        return []

    # Get standings using PlayoffGenerator (which has proper tie-breaking logic)
    generator = PlayoffGenerator(league_id, league.season.id, session)

    # Get all teams (not just top 8) for display
    standings = session.query(Standings).filter_by(
        season_id=league.season.id
    ).join(Team).filter(
        Team.league_id == league_id
    ).all()

    if not standings:
        return []

    # Sort by points, then goal difference, then goals for
    standings.sort(key=lambda s: (s.points, s.goal_difference, s.goals_for), reverse=True)

    # Return teams with their stats attached
    teams = []
    for standing in standings:
        team = standing.team
        team.points = standing.points
        team.wins = standing.wins
        team.losses = standing.losses
        team.draws = standing.draws
        team.goals_for = standing.goals_for
        team.goals_against = standing.goals_against
        team.goal_difference = standing.goal_difference
        team.played = standing.played
        teams.append(team)

    return teams