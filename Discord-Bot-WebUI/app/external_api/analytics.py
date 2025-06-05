# app/external_api/analytics.py

"""
Analytics endpoints for external API.
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import func, desc, and_, or_

from flask import request, jsonify
from app.core import db
from app.models import (
    Player, Team, Match, League, Season, Availability,
    PlayerSeasonStats, PlayerCareerStats, Standings
)

from . import external_api_bp
from .auth import api_key_required
from .stats_utils import calculate_expected_attendance, get_substitution_urgency

logger = logging.getLogger(__name__)


def analyze_team_for_match(match, team, team_type):
    """Helper function to analyze a team's attendance for a specific match."""
    try:
        team_player_ids = [p.id for p in team.players]
        
        # Get RSVP data
        availabilities = Availability.query.filter(
            and_(
                Availability.match_id == match.id,
                Availability.player_id.in_(team_player_ids)
            )
        ).all()
        
        # Categorize responses - handle multiple response formats
        available_count = len([a for a in availabilities if a.response.lower() in ['available', 'yes', 'attending']])
        unavailable_count = len([a for a in availabilities if a.response.lower() in ['unavailable', 'no', 'not_attending']])
        maybe_count = len([a for a in availabilities if a.response.lower() in ['maybe', 'tentative']])
        
        responded_player_ids = set(a.player_id for a in availabilities if a.player_id)
        no_response_player_ids = set(team_player_ids) - responded_player_ids
        no_response_count = len(no_response_player_ids)
        
        # Get detailed player info
        available_players = Player.query.filter(
            Player.id.in_([a.player_id for a in availabilities if a.player_id and a.response.lower() in ['available', 'yes', 'attending']])
        ).all()
        
        maybe_players = Player.query.filter(
            Player.id.in_([a.player_id for a in availabilities if a.player_id and a.response.lower() in ['maybe', 'tentative']])
        ).all()
        
        no_response_players = Player.query.filter(
            Player.id.in_(no_response_player_ids)
        ).all()
        
        # Calculate expected attendance using standardized function
        expected_attendance = calculate_expected_attendance(available_count, maybe_count)
        
        return {
            'team_id': team.id,
            'team_name': team.name,
            'team_type': team_type,
            'total_roster': len(team.players),
            'confirmed_available': available_count,
            'confirmed_unavailable': unavailable_count,
            'maybe_available': maybe_count,
            'no_response_count': no_response_count,
            'expected_attendance': round(expected_attendance, 1),
            'response_rate_percent': round((len(responded_player_ids) / len(team_player_ids) * 100), 1) if team_player_ids else 0,
            'available_players': [
                {
                    'id': p.id,
                    'name': p.name,
                    'position': p.favorite_position
                } for p in available_players
            ],
            'maybe_players': [
                {
                    'id': p.id,
                    'name': p.name,
                    'position': p.favorite_position
                } for p in maybe_players
            ],
            'no_response_players': [
                {
                    'id': p.id,
                    'name': p.name,
                    'position': p.favorite_position
                } for p in no_response_players
            ]
        }
        
    except Exception as e:
        logger.error(f"Error analyzing team {team.id} for match {match.id}: {e}")
        return None


@external_api_bp.route('/analytics/player-stats', methods=['GET'])
@api_key_required
def get_player_analytics():
    """Get advanced player statistics and analytics."""
    try:
        season_id = request.args.get('season_id', type=int)
        team_id = request.args.get('team_id', type=int)
        position = request.args.get('position', '').strip()
        min_matches = request.args.get('min_matches', 0, type=int)
        
        # Build base query - LEFT JOIN to include players even without stats
        query = db.session.query(
            Player.id,
            Player.name,
            Player.favorite_position,
            func.coalesce(func.sum(PlayerSeasonStats.goals), 0).label('total_goals'),
            func.coalesce(func.sum(PlayerSeasonStats.assists), 0).label('total_assists'),
            func.coalesce(func.sum(PlayerSeasonStats.yellow_cards), 0).label('total_yellows'),
            func.coalesce(func.sum(PlayerSeasonStats.red_cards), 0).label('total_reds')
        ).outerjoin(
            PlayerSeasonStats,
            and_(
                Player.id == PlayerSeasonStats.player_id,
                PlayerSeasonStats.season_id == season_id if season_id else True
            )
        ).filter(
            Player.is_current_player == True
        ).group_by(
            Player.id, Player.name, Player.favorite_position
        )
        
        # Apply filters
        if team_id:
            query = query.filter(Player.teams.any(Team.id == team_id))
        
        if position:
            query = query.filter(Player.favorite_position.ilike(f'%{position}%'))
        
        # Execute query and order by goals
        stats = query.order_by(desc('total_goals')).all()
        
        # Calculate analytics
        analytics_data = []
        for stat in stats:
            # Calculate actual matches played for this player in the season
            player = Player.query.get(stat.id)
            actual_matches = 0
            if player and player.teams:
                team_ids = [team.id for team in player.teams]
                if team_ids:
                    match_filter = [
                        or_(
                            Match.home_team_id.in_(team_ids),
                            Match.away_team_id.in_(team_ids)
                        ),
                        Match.home_team_score.isnot(None)
                    ]
                    if season_id:
                        match_filter.append(
                            or_(
                                Match.home_team.has(Team.league.has(League.season_id == season_id)),
                                Match.away_team.has(Team.league.has(League.season_id == season_id))
                            )
                        )
                    actual_matches = Match.query.filter(and_(*match_filter)).count()
            
            # Use at least 1 to avoid division by zero
            matches_played = max(actual_matches, 1)
            
            # Apply min_matches filter after query
            if actual_matches < min_matches and min_matches > 0:
                continue
            
            analytics_data.append({
                'player_id': stat.id,
                'name': stat.name,
                'position': stat.favorite_position or 'Unknown',
                'matches_played': actual_matches,
                'goals': int(stat.total_goals),
                'assists': int(stat.total_assists),
                'yellow_cards': int(stat.total_yellows),
                'red_cards': int(stat.total_reds),
                'goals_per_match': round(stat.total_goals / matches_played, 2),
                'assists_per_match': round(stat.total_assists / matches_played, 2),
                'goal_contributions': int(stat.total_goals + stat.total_assists),
                'discipline_score': int(stat.total_yellows + (stat.total_reds * 2))
            })
        
        return jsonify({
            'analytics': analytics_data,
            'filters_applied': {
                'season_id': season_id,
                'team_id': team_id,
                'position': position,
                'min_matches': min_matches
            },
            'total_players': len(analytics_data)
        })
        
    except Exception as e:
        logger.error(f"Error in get_player_analytics: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/analytics/attendance', methods=['GET'])
@api_key_required
def get_attendance_analytics():
    """Get detailed attendance analytics and patterns."""
    try:
        season_id = request.args.get('season_id', type=int)
        team_id = request.args.get('team_id', type=int)
        league_id = request.args.get('league_id', type=int)
        min_matches = request.args.get('min_matches', 0, type=int)
        max_matches = request.args.get('max_matches', type=int)
        
        # Base query for matches with filters
        match_query = Match.query
        
        if season_id:
            match_query = match_query.filter(
                or_(
                    Match.home_team.has(Team.league.has(League.season_id == season_id)),
                    Match.away_team.has(Team.league.has(League.season_id == season_id))
                )
            )
        
        if league_id:
            match_query = match_query.filter(
                or_(
                    Match.home_team.has(Team.league_id == league_id),
                    Match.away_team.has(Team.league_id == league_id)
                )
            )
        
        if team_id:
            match_query = match_query.filter(
                or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
            )
        
        matches = match_query.all()
        match_ids = [m.id for m in matches]
        
        if not match_ids:
            return jsonify({
                'attendance_patterns': [],
                'summary': {'total_players': 0, 'total_matches': 0},
                'filters_applied': {
                    'season_id': season_id,
                    'team_id': team_id,
                    'league_id': league_id,
                    'min_matches': min_matches,
                    'max_matches': max_matches
                }
            })
        
        # Get attendance data for these matches
        attendance_query = db.session.query(
            Player.id,
            Player.name,
            Player.favorite_position,
            func.count(Availability.id).label('total_responses'),
            func.sum(func.case([(Availability.response == 'available', 1)], else_=0)).label('available_count'),
            func.sum(func.case([(Availability.response == 'unavailable', 1)], else_=0)).label('unavailable_count'),
            func.sum(func.case([(Availability.response == 'maybe', 1)], else_=0)).label('maybe_count')
        ).join(
            Availability, Player.id == Availability.player_id
        ).filter(
            Availability.match_id.in_(match_ids),
            Player.is_current_player == True
        ).group_by(
            Player.id, Player.name, Player.favorite_position
        )
        
        # Get all players for this scope to calculate no-response counts
        all_players_query = Player.query.filter(Player.is_current_player == True)
        
        if team_id:
            all_players_query = all_players_query.filter(Player.teams.any(Team.id == team_id))
        elif league_id:
            all_players_query = all_players_query.filter(
                Player.teams.any(Team.league_id == league_id)
            )
        
        all_players = all_players_query.all()
        attendance_stats = attendance_query.all()
        
        # Build comprehensive attendance data
        attendance_patterns = []
        player_response_map = {stat.id: stat for stat in attendance_stats}
        
        for player in all_players:
            stat = player_response_map.get(player.id)
            
            if stat:
                total_responses = int(stat.total_responses)
                available_count = int(stat.available_count or 0)
                unavailable_count = int(stat.unavailable_count or 0)
                maybe_count = int(stat.maybe_count or 0)
            else:
                total_responses = 0
                available_count = 0
                unavailable_count = 0
                maybe_count = 0
            
            no_response_count = len(match_ids) - total_responses
            
            # Apply filters
            if min_matches > 0 and available_count < min_matches:
                continue
            if max_matches and available_count > max_matches:
                continue
            
            # Calculate percentages
            total_possible = len(match_ids)
            attendance_rate = round((available_count / total_possible * 100), 1) if total_possible > 0 else 0
            response_rate = round((total_responses / total_possible * 100), 1) if total_possible > 0 else 0
            
            # Get player's teams
            player_teams = [{'id': team.id, 'name': team.name} for team in player.teams]
            
            attendance_patterns.append({
                'player_id': player.id,
                'name': player.name,
                'position': player.favorite_position or 'Unknown',
                'teams': player_teams,
                'attendance_stats': {
                    'total_possible_matches': total_possible,
                    'responses_given': total_responses,
                    'available_responses': available_count,
                    'unavailable_responses': unavailable_count,
                    'maybe_responses': maybe_count,
                    'no_responses': no_response_count,
                    'attendance_rate_percent': attendance_rate,
                    'response_rate_percent': response_rate
                },
                'attendance_category': (
                    'high_attendance' if attendance_rate >= 80 else
                    'medium_attendance' if attendance_rate >= 50 else
                    'low_attendance'
                ),
                'responsiveness': (
                    'very_responsive' if response_rate >= 90 else
                    'responsive' if response_rate >= 70 else
                    'needs_follow_up' if response_rate >= 40 else
                    'poor_response'
                )
            })
        
        # Sort by attendance rate (descending)
        attendance_patterns.sort(key=lambda x: x['attendance_stats']['attendance_rate_percent'], reverse=True)
        
        # Generate summary insights
        total_players = len(attendance_patterns)
        avg_attendance = sum(p['attendance_stats']['attendance_rate_percent'] for p in attendance_patterns) / max(total_players, 1)
        avg_response_rate = sum(p['attendance_stats']['response_rate_percent'] for p in attendance_patterns) / max(total_players, 1)
        
        low_attendance_count = len([p for p in attendance_patterns if p['attendance_category'] == 'low_attendance'])
        poor_response_count = len([p for p in attendance_patterns if p['responsiveness'] == 'poor_response'])
        
        return jsonify({
            'attendance_patterns': attendance_patterns,
            'summary': {
                'total_players': total_players,
                'total_matches_analyzed': len(match_ids),
                'average_attendance_rate': round(avg_attendance, 1),
                'average_response_rate': round(avg_response_rate, 1),
                'low_attendance_players': low_attendance_count,
                'poor_response_players': poor_response_count,
                'insights': {
                    'players_needing_follow_up': poor_response_count,
                    'players_with_low_attendance': low_attendance_count,
                    'overall_engagement': (
                        'excellent' if avg_response_rate >= 85 else
                        'good' if avg_response_rate >= 70 else
                        'needs_improvement'
                    )
                }
            },
            'filters_applied': {
                'season_id': season_id,
                'team_id': team_id,
                'league_id': league_id,
                'min_matches': min_matches,
                'max_matches': max_matches
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_attendance_analytics: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/analytics/substitution-needs', methods=['GET'])
@api_key_required
def get_substitution_needs():
    """Analyze which teams need substitutes for upcoming matches."""
    try:
        days_ahead = request.args.get('days_ahead', 14, type=int)
        league_id = request.args.get('league_id', type=int)
        team_id = request.args.get('team_id', type=int)
        min_players_threshold = request.args.get('min_players', 9, type=int)
        ideal_players = request.args.get('ideal_players', 15, type=int)
        
        # Get upcoming matches
        end_date = (datetime.now() + timedelta(days=days_ahead)).date()
        
        upcoming_matches_query = Match.query.filter(
            and_(
                Match.date >= datetime.now().date(),
                Match.date <= end_date,
                Match.home_team_score.is_(None)
            )
        )
        
        if league_id:
            upcoming_matches_query = upcoming_matches_query.filter(
                or_(
                    Match.home_team.has(Team.league_id == league_id),
                    Match.away_team.has(Team.league_id == league_id)
                )
            )
        
        if team_id:
            upcoming_matches_query = upcoming_matches_query.filter(
                or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
            )
        
        upcoming_matches = upcoming_matches_query.order_by(Match.date, Match.time).all()
        
        substitution_analysis = []
        
        for match in upcoming_matches:
            # Analyze both teams
            for team_type, team in [('home', match.home_team), ('away', match.away_team)]:
                if not team:
                    continue
                
                team_analysis = analyze_team_for_match(match, team, team_type)
                if not team_analysis:
                    continue
                
                # Calculate substitute needs
                confirmed_available = team_analysis['confirmed_available']
                potential_available = confirmed_available + team_analysis['maybe_available']
                
                # Determine substitute needs and urgency
                urgency = get_substitution_urgency(
                    confirmed_available, 
                    team_analysis['total_roster'], 
                    min_players_threshold, 
                    ideal_players
                )
                
                needs_subs = urgency in ['critical', 'high']
                
                # Calculate days until match
                days_until = (match.date - datetime.now().date()).days
                
                substitution_analysis.append({
                    'match_id': match.id,
                    'match_date': match.date.isoformat(),
                    'match_time': match.time.isoformat() if match.time else None,
                    'location': match.location,
                    'days_until_match': days_until,
                    'team': {
                        'id': team.id,
                        'name': team.name,
                        'league': team.league.name if team.league else None,
                        'team_type': team_type
                    },
                    'opponent': {
                        'id': match.away_team.id if team_type == 'home' else match.home_team.id,
                        'name': match.away_team.name if team_type == 'home' else match.home_team.name
                    } if (match.away_team and match.home_team) else None,
                    'roster_analysis': {
                        'total_roster_size': team_analysis['total_roster'],
                        'confirmed_available': confirmed_available,
                        'unavailable': team_analysis['confirmed_unavailable'],
                        'maybe_available': team_analysis['maybe_available'],
                        'no_response': team_analysis['no_response_count'],
                        'potential_available': potential_available,
                        'shortage_amount': max(0, min_players_threshold - confirmed_available)
                    },
                    'substitute_needs': {
                        'needs_substitutes': needs_subs,
                        'urgency': urgency,
                        'minimum_subs_needed': max(0, min_players_threshold - confirmed_available),
                        'recommended_subs': max(0, (min_players_threshold + 2) - potential_available)
                    },
                    'available_players': team_analysis['available_players'],
                    'no_response_players': [
                        {**p, 'needs_follow_up': True} 
                        for p in team_analysis['no_response_players']
                    ]
                })
        
        # Sort by urgency and date
        urgency_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'none': 4}
        substitution_analysis.sort(key=lambda x: (urgency_order[x['substitute_needs']['urgency']], x['match_date']))
        
        # Generate summary
        critical_matches = len([m for m in substitution_analysis if m['substitute_needs']['urgency'] == 'critical'])
        high_priority_matches = len([m for m in substitution_analysis if m['substitute_needs']['urgency'] == 'high'])
        matches_needing_subs = len([m for m in substitution_analysis if m['substitute_needs']['needs_substitutes']])
        
        return jsonify({
            'substitution_analysis': substitution_analysis,
            'summary': {
                'total_upcoming_matches': len(substitution_analysis),
                'matches_needing_substitutes': matches_needing_subs,
                'critical_shortage_matches': critical_matches,
                'high_priority_matches': high_priority_matches,
                'analysis_period_days': days_ahead,
                'recommendations': {
                    'immediate_action_needed': critical_matches > 0,
                    'total_subs_needed': sum(m['substitute_needs']['minimum_subs_needed'] for m in substitution_analysis),
                    'follow_up_required': sum(len(m['no_response_players']) for m in substitution_analysis)
                }
            },
            'filters_applied': {
                'days_ahead': days_ahead,
                'league_id': league_id,
                'team_id': team_id,
                'min_players_threshold': min_players_threshold
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_substitution_needs: {e}")
        return jsonify({'error': 'Internal server error'}), 500