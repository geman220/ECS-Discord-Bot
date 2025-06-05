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
    PlayerSeasonStats, PlayerCareerStats, Standings, TemporarySubAssignment, SubRequest
)

from . import external_api_bp
from .auth import api_key_required
from .stats_utils import calculate_expected_attendance, get_substitution_urgency

logger = logging.getLogger(__name__)


def get_substitution_description(confirmed_available, min_players, ideal_players):
    """Generate human-readable description of substitution situation for 8v8."""
    if confirmed_available < min_players:
        return f"Cannot field team - need {min_players - confirmed_available} more players"
    elif confirmed_available < min_players + 2:
        return f"Can field team but no substitutes - very tight"
    elif confirmed_available < min_players + 4:
        return f"Limited rotation - {confirmed_available - min_players} subs available"
    elif confirmed_available < ideal_players:
        return f"Good turnout but not optimal - {confirmed_available - min_players} subs"
    else:
        subs_available = confirmed_available - min_players
        return f"Excellent turnout - {subs_available} subs allows balanced rotation"


def get_sub_situation_summary(teams_needing_subs):
    """Generate summary of substitution needs across teams."""
    if not teams_needing_subs:
        return "Both teams have adequate attendance - no subs needed"
    elif len(teams_needing_subs) == 1:
        team = teams_needing_subs[0]
        return f"{team['team_type'].title()} team needs {team['subs_needed']} subs ({team['urgency']} priority)"
    else:
        total_subs = sum(team['subs_needed'] for team in teams_needing_subs)
        return f"Both teams need subs - total {total_subs} substitutes needed"


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
            func.sum(func.case((Availability.response == 'available', 1), else_=0)).label('available_count'),
            func.sum(func.case((Availability.response == 'unavailable', 1), else_=0)).label('unavailable_count'),
            func.sum(func.case((Availability.response == 'maybe', 1), else_=0)).label('maybe_count')
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
        min_players_threshold = request.args.get('min_players', 8, type=int)
        ideal_players = request.args.get('ideal_players', 13, type=int)
        
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
                
                needs_subs = urgency in ['critical', 'high', 'medium']
                
                # Check if coach has manually requested a substitute
                manual_sub_request = SubRequest.query.filter(
                    and_(
                        SubRequest.match_id == match.id,
                        SubRequest.team_id == team.id,
                        SubRequest.status.in_(['PENDING', 'APPROVED'])
                    )
                ).first()
                
                has_manual_request = manual_sub_request is not None
                
                # Team needs subs if either RSVP data indicates need OR coach manually requested
                needs_subs_final = needs_subs or has_manual_request
                
                # Only add teams that actually need substitutes
                if needs_subs_final:
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
                            'needs_substitutes': needs_subs_final,
                            'urgency': 'high' if has_manual_request and urgency in ['low', 'none'] else urgency,
                            'minimum_subs_needed': max(0, min_players_threshold - confirmed_available),
                            'recommended_subs_for_ideal': max(0, ideal_players - confirmed_available) if needs_subs_final else 0,
                            'current_situation': get_substitution_description(confirmed_available, min_players_threshold, ideal_players),
                            'manual_request': {
                                'has_request': has_manual_request,
                                'request_id': manual_sub_request.id if manual_sub_request else None,
                                'status': manual_sub_request.status if manual_sub_request else None,
                                'requested_at': manual_sub_request.created_at.isoformat() if manual_sub_request else None,
                                'notes': manual_sub_request.notes if manual_sub_request else None
                            }
                        },
                        'available_players': team_analysis['available_players'],
                        'no_response_players': [
                            {**p, 'needs_follow_up': True} 
                            for p in team_analysis['no_response_players']
                        ]
                    })
        
        # Sort by urgency and date, prioritizing manual requests
        urgency_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'none': 4}
        substitution_analysis.sort(key=lambda x: (
            urgency_order[x['substitute_needs']['urgency']], 
            not x['substitute_needs']['manual_request']['has_request'],  # Manual requests first
            x['match_date']
        ))
        
        # Generate summary
        critical_matches = len([m for m in substitution_analysis if m['substitute_needs']['urgency'] == 'critical'])
        high_priority_matches = len([m for m in substitution_analysis if m['substitute_needs']['urgency'] == 'high'])
        matches_needing_subs = len([m for m in substitution_analysis if m['substitute_needs']['needs_substitutes']])
        manual_requests = len([m for m in substitution_analysis if m['substitute_needs']['manual_request']['has_request']])
        
        return jsonify({
            'substitution_analysis': substitution_analysis,
            'summary': {
                'total_upcoming_matches': len(substitution_analysis),
                'matches_needing_substitutes': matches_needing_subs,
                'critical_shortage_matches': critical_matches,
                'high_priority_matches': high_priority_matches,
                'manual_sub_requests': manual_requests,
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


@external_api_bp.route('/analytics/substitute-requests', methods=['GET'])
@api_key_required
def get_substitute_requests():
    """Track which teams have requested substitutes and sub availability."""
    try:
        days_ahead = request.args.get('days_ahead', 14, type=int)
        league_id = request.args.get('league_id', type=int)
        season_id = request.args.get('season_id', type=int)
        team_id = request.args.get('team_id', type=int)
        
        # Get date range
        end_date = (datetime.now() + timedelta(days=days_ahead)).date()
        
        # Get substitute assignments for upcoming matches
        assignments_query = db.session.query(
            TemporarySubAssignment.match_id,
            TemporarySubAssignment.player_id,
            TemporarySubAssignment.team_id,
            TemporarySubAssignment.created_at,
            Match.date.label('match_date'),
            Match.time.label('match_time'),
            Match.location,
            Player.name.label('sub_name'),
            Player.favorite_position,
            Team.name.label('team_name')
        ).join(
            Match, TemporarySubAssignment.match_id == Match.id
        ).join(
            Player, TemporarySubAssignment.player_id == Player.id
        ).join(
            Team, TemporarySubAssignment.team_id == Team.id
        ).filter(
            and_(
                Match.date >= datetime.now().date(),
                Match.date <= end_date,
                Match.home_team_score.is_(None)
            )
        )
        
        if league_id:
            assignments_query = assignments_query.filter(Team.league_id == league_id)
        if season_id:
            assignments_query = assignments_query.filter(Team.league.has(League.season_id == season_id))
        if team_id:
            assignments_query = assignments_query.filter(Team.id == team_id)
        
        substitute_assignments = assignments_query.all()
        
        # Group assignments by match and team
        substitute_requests = []
        assignments_by_match_team = {}
        
        for assignment in substitute_assignments:
            key = (assignment.match_id, assignment.team_id)
            if key not in assignments_by_match_team:
                assignments_by_match_team[key] = {
                    'match_id': assignment.match_id,
                    'match_date': assignment.match_date.isoformat(),
                    'match_time': assignment.match_time.isoformat() if assignment.match_time else None,
                    'location': assignment.location,
                    'team_id': assignment.team_id,
                    'team_name': assignment.team_name,
                    'substitutes': [],
                    'total_subs_assigned': 0,
                    'requested_at': assignment.created_at.isoformat()
                }
            
            assignments_by_match_team[key]['substitutes'].append({
                'player_id': assignment.player_id,
                'name': assignment.sub_name,
                'position': assignment.favorite_position,
                'assigned_at': assignment.created_at.isoformat()
            })
            assignments_by_match_team[key]['total_subs_assigned'] += 1
        
        substitute_requests = list(assignments_by_match_team.values())
        
        # Get available substitute players (players not in their own teams' matches)
        substitute_players = Player.query.filter(
            and_(
                Player.is_current_player == True,
                Player.is_sub == True
            )
        ).all()
        
        available_substitutes = []
        for player in substitute_players:
            # Count how many assignments this player has in the period
            assignments_this_period = len([
                a for a in substitute_assignments 
                if a.player_id == player.id
            ])
            
            # Determine availability status
            if assignments_this_period >= 3:
                availability_status = 'overloaded'
            elif assignments_this_period >= 2:
                availability_status = 'busy'
            else:
                availability_status = 'available'
            
            available_substitutes.append({
                'player_id': player.id,
                'name': player.name,
                'position': player.favorite_position or 'Unknown',
                'phone': player.phone,
                'teams': [
                    {
                        'id': team.id,
                        'name': team.name,
                        'league': team.league.name if team.league else None
                    } for team in player.teams
                ],
                'assignments_this_period': assignments_this_period,
                'availability_status': availability_status
            })
        
        # Sort by availability status and then by assignments
        status_order = {'available': 0, 'busy': 1, 'overloaded': 2}
        available_substitutes.sort(key=lambda x: (status_order[x['availability_status']], x['assignments_this_period']))
        
        return jsonify({
            'substitute_requests': substitute_requests,
            'available_substitutes': available_substitutes,
            'summary': {
                'total_requests': len(substitute_requests),
                'total_subs_assigned': sum(r['total_subs_assigned'] for r in substitute_requests),
                'available_subs': len([s for s in available_substitutes if s['availability_status'] == 'available']),
                'busy_subs': len([s for s in available_substitutes if s['availability_status'] == 'busy']),
                'overloaded_subs': len([s for s in available_substitutes if s['availability_status'] == 'overloaded']),
                'fulfillment_capacity': 'good' if len([s for s in available_substitutes if s['availability_status'] == 'available']) > 5 else 'limited'
            },
            'filters_applied': {
                'days_ahead': days_ahead,
                'league_id': league_id,
                'season_id': season_id,
                'team_id': team_id
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_substitute_requests: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/analytics/match-insights', methods=['GET'])
@api_key_required
def get_match_insights():
    """Get detailed RSVP insights for specific matches."""
    try:
        match_id = request.args.get('match_id', type=int)
        team_id = request.args.get('team_id', type=int)
        league_id = request.args.get('league_id', type=int)
        days_ahead = request.args.get('days_ahead', 7, type=int)
        include_historical = request.args.get('include_historical', False, type=bool)
        
        # Build match query
        if match_id:
            matches_query = Match.query.filter(Match.id == match_id)
        else:
            end_date = (datetime.now() + timedelta(days=days_ahead)).date()
            matches_query = Match.query.filter(
                and_(
                    Match.date >= datetime.now().date(),
                    Match.date <= end_date
                )
            )
            
            if not include_historical:
                matches_query = matches_query.filter(Match.home_team_score.is_(None))
        
        if league_id:
            matches_query = matches_query.filter(
                or_(
                    Match.home_team.has(Team.league_id == league_id),
                    Match.away_team.has(Team.league_id == league_id)
                )
            )
        
        if team_id:
            matches_query = matches_query.filter(
                or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
            )
        
        matches = matches_query.order_by(Match.date, Match.time).all()
        
        match_insights = []
        
        for match in matches:
            days_until = (match.date - datetime.now().date()).days
            is_completed = match.home_team_score is not None
            
            # Determine match status
            if is_completed:
                match_status = 'completed'
            elif days_until <= 2:
                match_status = 'urgent'
            elif days_until <= 7:
                match_status = 'upcoming'
            else:
                match_status = 'future'
            
            # Analyze both teams
            home_analysis = analyze_team_for_match(match, match.home_team, 'home')
            away_analysis = analyze_team_for_match(match, match.away_team, 'away')
            
            # Calculate overall insights with 8v8 perspective
            total_expected = 0
            total_unavailable = 0
            total_awaiting = 0
            teams_needing_subs = []
            
            for analysis in [home_analysis, away_analysis]:
                if analysis:
                    total_expected += analysis['expected_attendance']
                    total_unavailable += analysis['confirmed_unavailable']
                    total_awaiting += analysis['no_response_count']
                    
                    # Check if this team needs subs (using 8v8 standards)
                    urgency = get_substitution_urgency(analysis['confirmed_available'], analysis['total_roster'], 8, 13)
                    if urgency in ['critical', 'high', 'medium']:
                        teams_needing_subs.append({
                            'team_name': analysis['team_name'],
                            'team_type': analysis['team_type'],
                            'confirmed_available': analysis['confirmed_available'],
                            'urgency': urgency,
                            'subs_needed': max(0, 13 - analysis['confirmed_available'])
                        })
            
            # Determine attendance outlook based on 8v8 standards
            avg_expected = total_expected / 2 if total_expected > 0 else 0
            if avg_expected >= 13:
                outlook = 'excellent'
            elif avg_expected >= 11:
                outlook = 'good'
            elif avg_expected >= 8:
                outlook = 'adequate'
            elif avg_expected >= 6:
                outlook = 'concerning'
            else:
                outlook = 'critical'
            
            match_insights.append({
                'match_id': match.id,
                'match_date': match.date.isoformat(),
                'match_time': match.time.isoformat() if match.time else None,
                'location': match.location,
                'days_until_match': days_until,
                'match_status': match_status,
                'is_completed': is_completed,
                'home_team_analysis': home_analysis,
                'away_team_analysis': away_analysis,
                'overall_insights': {
                    'total_expected_attendance': round(total_expected, 1),
                    'total_confirmed_unavailable': total_unavailable,
                    'total_awaiting_response': total_awaiting,
                    'attendance_outlook': outlook,
                    'requires_immediate_attention': outlook in ['critical', 'concerning'] and match_status in ['urgent', 'upcoming'],
                    'teams_needing_subs': teams_needing_subs,
                    'sub_situation_summary': get_sub_situation_summary(teams_needing_subs)
                }
            })
        
        # Sort by urgency and date
        status_order = {'urgent': 0, 'upcoming': 1, 'future': 2, 'completed': 3}
        match_insights.sort(key=lambda x: (status_order[x['match_status']], x['match_date']))
        
        # Generate summary
        urgent_matches = len([m for m in match_insights if m['match_status'] == 'urgent'])
        critical_outlook = len([m for m in match_insights if m['overall_insights']['attendance_outlook'] == 'critical'])
        
        return jsonify({
            'match_insights': match_insights,
            'summary': {
                'total_matches': len(match_insights),
                'urgent_matches': urgent_matches,
                'matches_with_critical_attendance': critical_outlook,
                'matches_needing_attention': len([m for m in match_insights if m['overall_insights']['requires_immediate_attention']]),
                'analysis_period_days': days_ahead
            },
            'filters_applied': {
                'match_id': match_id,
                'team_id': team_id,
                'league_id': league_id,
                'days_ahead': days_ahead,
                'include_historical': include_historical
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_match_insights: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/analytics/player-patterns', methods=['GET'])
@api_key_required
def get_player_patterns():
    """Analyze individual player availability patterns and predict future attendance."""
    try:
        player_id = request.args.get('player_id', type=int)
        team_id = request.args.get('team_id', type=int)
        league_id = request.args.get('league_id', type=int)
        season_id = request.args.get('season_id', type=int)
        days_lookback = request.args.get('days_lookback', 90, type=int)
        include_predictions = request.args.get('include_predictions', True, type=bool)
        
        # Get date range for analysis
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days_lookback)
        
        # Build player query - focus on Pub League only
        players_query = Player.query.filter(
            and_(
                Player.is_current_player == True,
                Player.primary_league.has(
                    League.season.has(Season.league_type == 'Pub League')
                )
            )
        )
        
        if player_id:
            players_query = players_query.filter(Player.id == player_id)
        if team_id:
            players_query = players_query.filter(Player.teams.any(Team.id == team_id))
        elif league_id:
            players_query = players_query.filter(Player.teams.any(Team.league_id == league_id))
        
        players = players_query.all()
        
        player_patterns = []
        
        for player in players:
            # Get player's teams
            player_teams = [
                {
                    'id': team.id,
                    'name': team.name,
                    'league': team.league.name if team.league else None
                } for team in player.teams
            ]
            
            # Get matches for this player's teams in the analysis period
            team_ids = [team.id for team in player.teams]
            if not team_ids:
                continue
            
            matches_query = Match.query.filter(
                and_(
                    Match.date >= start_date,
                    Match.date <= end_date,
                    or_(
                        Match.home_team_id.in_(team_ids),
                        Match.away_team_id.in_(team_ids)
                    )
                )
            )
            
            if season_id:
                matches_query = matches_query.filter(
                    or_(
                        Match.home_team.has(Team.league.has(League.season_id == season_id)),
                        Match.away_team.has(Team.league.has(League.season_id == season_id))
                    )
                )
            
            matches = matches_query.all()
            match_ids = [m.id for m in matches]
            
            if not match_ids:
                continue
            
            # Get availability responses for this player
            availabilities = Availability.query.filter(
                and_(
                    Availability.player_id == player.id,
                    Availability.match_id.in_(match_ids)
                )
            ).all()
            
            # Analyze patterns
            total_matches = len(match_ids)
            total_responses = len(availabilities)
            available_responses = len([a for a in availabilities if a.response.lower() in ['available', 'yes', 'attending']])
            unavailable_responses = len([a for a in availabilities if a.response.lower() in ['unavailable', 'no', 'not_attending']])
            maybe_responses = len([a for a in availabilities if a.response.lower() in ['maybe', 'tentative']])
            no_responses = total_matches - total_responses
            
            # Calculate rates
            response_rate = (total_responses / total_matches * 100) if total_matches > 0 else 0
            attendance_rate = (available_responses / total_matches * 100) if total_matches > 0 else 0
            
            # Analyze day-of-week preferences
            day_patterns = {}
            for availability in availabilities:
                match = next((m for m in matches if m.id == availability.match_id), None)
                if match:
                    day_name = match.date.strftime('%A')
                    if day_name not in day_patterns:
                        day_patterns[day_name] = {'total': 0, 'available': 0}
                    day_patterns[day_name]['total'] += 1
                    if availability.response.lower() in ['available', 'yes', 'attending']:
                        day_patterns[day_name]['available'] += 1
            
            # Calculate day preferences
            day_preferences = {}
            for day, counts in day_patterns.items():
                day_preferences[day] = {
                    'attendance_rate': round((counts['available'] / counts['total'] * 100), 1) if counts['total'] > 0 else 0,
                    'total_matches': counts['total']
                }
            
            # Determine reliability score
            if response_rate >= 90 and attendance_rate >= 80:
                reliability = 'highly_reliable'
            elif response_rate >= 70 and attendance_rate >= 60:
                reliability = 'reliable'
            elif response_rate >= 50 or attendance_rate >= 40:
                reliability = 'inconsistent'
            else:
                reliability = 'unreliable'
            
            # Generate predictions if requested
            predictions = {}
            if include_predictions and total_responses >= 5:
                # Simple prediction based on recent trends
                recent_matches = [m for m in matches if (end_date - m.date).days <= 30]
                recent_match_ids = [m.id for m in recent_matches]
                recent_availabilities = [a for a in availabilities if a.match_id in recent_match_ids]
                
                if recent_availabilities:
                    recent_attendance_rate = len([a for a in recent_availabilities if a.response.lower() in ['available', 'yes', 'attending']]) / len(recent_availabilities) * 100
                    predictions = {
                        'predicted_attendance_rate': round(recent_attendance_rate, 1),
                        'confidence': 'high' if len(recent_availabilities) >= 5 else 'medium' if len(recent_availabilities) >= 3 else 'low',
                        'trend': 'improving' if recent_attendance_rate > attendance_rate else 'declining' if recent_attendance_rate < attendance_rate else 'stable',
                        'based_on_matches': len(recent_availabilities)
                    }
            
            player_patterns.append({
                'player_id': player.id,
                'name': player.name,
                'position': player.favorite_position or 'Unknown',
                'teams': player_teams,
                'analysis_period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'days_analyzed': days_lookback
                },
                'attendance_patterns': {
                    'total_possible_matches': total_matches,
                    'total_responses': total_responses,
                    'available_responses': available_responses,
                    'unavailable_responses': unavailable_responses,
                    'maybe_responses': maybe_responses,
                    'no_responses': no_responses,
                    'response_rate_percent': round(response_rate, 1),
                    'attendance_rate_percent': round(attendance_rate, 1)
                },
                'day_of_week_preferences': day_preferences,
                'reliability_score': reliability,
                'predictions': predictions if include_predictions else None
            })
        
        # Sort by reliability and attendance rate
        reliability_order = {'highly_reliable': 0, 'reliable': 1, 'inconsistent': 2, 'unreliable': 3}
        player_patterns.sort(key=lambda x: (reliability_order[x['reliability_score']], -x['attendance_patterns']['attendance_rate_percent']))
        
        # Generate summary
        total_players = len(player_patterns)
        avg_response_rate = sum(p['attendance_patterns']['response_rate_percent'] for p in player_patterns) / max(total_players, 1)
        avg_attendance_rate = sum(p['attendance_patterns']['attendance_rate_percent'] for p in player_patterns) / max(total_players, 1)
        
        reliability_distribution = {}
        for pattern in player_patterns:
            rel = pattern['reliability_score']
            reliability_distribution[rel] = reliability_distribution.get(rel, 0) + 1
        
        return jsonify({
            'player_patterns': player_patterns,
            'summary': {
                'total_players_analyzed': total_players,
                'analysis_period_days': days_lookback,
                'average_response_rate': round(avg_response_rate, 1),
                'average_attendance_rate': round(avg_attendance_rate, 1),
                'reliability_distribution': reliability_distribution,
                'most_reliable_players': len([p for p in player_patterns if p['reliability_score'] == 'highly_reliable']),
                'players_needing_attention': len([p for p in player_patterns if p['reliability_score'] in ['inconsistent', 'unreliable']])
            },
            'filters_applied': {
                'player_id': player_id,
                'team_id': team_id,
                'league_id': league_id,
                'season_id': season_id,
                'days_lookback': days_lookback,
                'include_predictions': include_predictions
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_player_patterns: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/analytics/referee-assignments', methods=['GET'])
@api_key_required
def get_referee_assignments():
    """Track referee assignments and identify matches needing referees."""
    try:
        days_ahead = request.args.get('days_ahead', 14, type=int)
        league_id = request.args.get('league_id', type=int)
        season_id = request.args.get('season_id', type=int)
        include_completed = request.args.get('include_completed', False, type=bool)
        
        # Get date range
        end_date = (datetime.now() + timedelta(days=days_ahead)).date()
        
        # Build matches query
        matches_query = Match.query.filter(
            and_(
                Match.date >= datetime.now().date(),
                Match.date <= end_date
            )
        )
        
        if not include_completed:
            matches_query = matches_query.filter(Match.home_team_score.is_(None))
        
        if league_id:
            matches_query = matches_query.filter(
                or_(
                    Match.home_team.has(Team.league_id == league_id),
                    Match.away_team.has(Team.league_id == league_id)
                )
            )
        
        if season_id:
            matches_query = matches_query.filter(
                or_(
                    Match.home_team.has(Team.league.has(League.season_id == season_id)),
                    Match.away_team.has(Team.league.has(League.season_id == season_id))
                )
            )
        
        matches = matches_query.order_by(Match.date, Match.time).all()
        
        # Get all referees
        referees = Player.query.filter(
            and_(
                Player.is_current_player == True,
                Player.is_ref == True
            )
        ).all()
        
        referee_assignments = []
        matches_needing_referees = []
        referee_workload = {}
        
        for match in matches:
            days_until = (match.date - datetime.now().date()).days
            is_completed = match.home_team_score is not None
            
            # Check if match has a referee assigned
            # This would typically be in a separate referee_assignments table
            # For now, we'll simulate based on available data
            has_referee = hasattr(match, 'ref_id') and match.ref_id is not None
            
            if has_referee:
                # Add to referee assignments
                referee_assignments.append({
                    'match_id': match.id,
                    'match_date': match.date.isoformat(),
                    'match_time': match.time.isoformat() if match.time else None,
                    'location': match.location,
                    'home_team': match.home_team.name if match.home_team else None,
                    'away_team': match.away_team.name if match.away_team else None,
                    'referee_id': getattr(match, 'ref_id', None),
                    'referee_name': 'Assigned',  # Would get from referee table
                    'assignment_status': 'confirmed',
                    'days_until_match': days_until,
                    'is_completed': is_completed
                })
                
                # Track workload
                ref_id = getattr(match, 'ref_id', 'unknown')
                if ref_id not in referee_workload:
                    referee_workload[ref_id] = {
                        'referee_id': ref_id,
                        'referee_name': 'Assigned Referee',
                        'total_assignments': 0,
                        'upcoming_assignments': 0,
                        'completed_assignments': 0,
                        'matches': []
                    }
                
                referee_workload[ref_id]['total_assignments'] += 1
                if is_completed:
                    referee_workload[ref_id]['completed_assignments'] += 1
                else:
                    referee_workload[ref_id]['upcoming_assignments'] += 1
                
                referee_workload[ref_id]['matches'].append({
                    'match_id': match.id,
                    'date': match.date.isoformat(),
                    'teams': f"{match.home_team.name if match.home_team else 'TBD'} vs {match.away_team.name if match.away_team else 'TBD'}",
                    'is_completed': is_completed
                })
            else:
                # Add to matches needing referees
                priority = 'critical' if days_until <= 2 else 'high' if days_until <= 7 else 'medium'
                
                matches_needing_referees.append({
                    'match_id': match.id,
                    'match_date': match.date.isoformat(),
                    'match_time': match.time.isoformat() if match.time else None,
                    'location': match.location,
                    'home_team': match.home_team.name if match.home_team else None,
                    'away_team': match.away_team.name if match.away_team else None,
                    'league': match.home_team.league.name if match.home_team and match.home_team.league else None,
                    'days_until_match': days_until,
                    'priority': priority,
                    'needs_urgent_assignment': days_until <= 3
                })
        
        # Calculate summary statistics
        total_matches = len(matches)
        matches_with_refs = len(referee_assignments)
        matches_needing_refs = len(matches_needing_referees)
        critical_unassigned = len([m for m in matches_needing_referees if m['priority'] == 'critical'])
        high_priority_unassigned = len([m for m in matches_needing_referees if m['priority'] == 'high'])
        
        coverage_rate = (matches_with_refs / total_matches * 100) if total_matches > 0 else 0
        
        # Generate recommendations
        recommendations = {
            'immediate_action_needed': critical_unassigned > 0,
            'assignments_needed_this_week': len([m for m in matches_needing_referees if m['days_until_match'] <= 7]),
            'suggested_referee_recruitment': len(referees) < (total_matches / 4),  # Rough heuristic
            'workload_distribution': 'balanced' if len(referee_workload) > 0 and max(w['total_assignments'] for w in referee_workload.values()) <= 3 else 'uneven'
        }
        
        return jsonify({
            'referee_assignments': referee_assignments,
            'matches_needing_referees': sorted(matches_needing_referees, key=lambda x: (x['days_until_match'], x['priority'])),
            'referee_workload': list(referee_workload.values()),
            'summary': {
                'total_matches': total_matches,
                'matches_with_referees': matches_with_refs,
                'matches_needing_referees': matches_needing_refs,
                'critical_unassigned': critical_unassigned,
                'high_priority_unassigned': high_priority_unassigned,
                'total_available_referees': len(referees),
                'referee_coverage_rate': round(coverage_rate, 1),
                'recommendations': recommendations
            },
            'filters_applied': {
                'days_ahead': days_ahead,
                'league_id': league_id,
                'season_id': season_id,
                'include_completed': include_completed
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_referee_assignments: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/analytics/team-performance', methods=['GET'])
@api_key_required
def get_team_performance():
    """Analyze current season team performance, form, and standings."""
    try:
        season_id = request.args.get('season_id', type=int)
        league_id = request.args.get('league_id', type=int)
        team_id = request.args.get('team_id', type=int)
        include_form = request.args.get('include_form', True, type=bool)
        min_matches = request.args.get('min_matches', 0, type=int)
        
        # Get current season if not specified
        if not season_id:
            current_season = Season.query.filter(Season.is_current == True).first()
            season_id = current_season.id if current_season else None
        
        # Build teams query
        teams_query = Team.query
        
        if season_id:
            teams_query = teams_query.filter(Team.league.has(League.season_id == season_id))
        if league_id:
            teams_query = teams_query.filter(Team.league_id == league_id)
        if team_id:
            teams_query = teams_query.filter(Team.id == team_id)
        
        teams = teams_query.all()
        
        team_performance = []
        
        for team in teams:
            # Get team's matches for the season
            matches_query = Match.query.filter(
                and_(
                    or_(Match.home_team_id == team.id, Match.away_team_id == team.id),
                    Match.home_team_score.isnot(None)  # Only completed matches
                )
            )
            
            if season_id:
                matches_query = matches_query.filter(
                    or_(
                        Match.home_team.has(Team.league.has(League.season_id == season_id)),
                        Match.away_team.has(Team.league.has(League.season_id == season_id))
                    )
                )
            
            matches = matches_query.order_by(Match.date.desc()).all()
            
            # Apply min_matches filter
            if len(matches) < min_matches:
                continue
            
            # Calculate season statistics
            wins = 0
            draws = 0
            losses = 0
            goals_for = 0
            goals_against = 0
            
            recent_form = []
            
            for match in matches:
                is_home = match.home_team_id == team.id
                team_score = match.home_team_score if is_home else match.away_team_score
                opponent_score = match.away_team_score if is_home else match.home_team_score
                opponent_name = match.away_team.name if is_home else match.home_team.name
                
                goals_for += team_score
                goals_against += opponent_score
                
                # Determine result
                if team_score > opponent_score:
                    wins += 1
                    result = 'W'
                elif team_score < opponent_score:
                    losses += 1
                    result = 'L'
                else:
                    draws += 1
                    result = 'D'
                
                # Add to recent form (last 5 matches)
                if len(recent_form) < 5:
                    recent_form.append({
                        'match_id': match.id,
                        'date': match.date.isoformat(),
                        'opponent': opponent_name,
                        'result': result,
                        'score': f"{team_score}-{opponent_score}",
                        'home_away': 'H' if is_home else 'A'
                    })
            
            matches_played = len(matches)
            points = (wins * 3) + draws
            win_rate = (wins / matches_played * 100) if matches_played > 0 else 0
            avg_goals_for = goals_for / matches_played if matches_played > 0 else 0
            avg_goals_against = goals_against / matches_played if matches_played > 0 else 0
            goal_difference = goals_for - goals_against
            
            # Calculate performance metrics
            if win_rate >= 70:
                performance_level = 'excellent'
            elif win_rate >= 50:
                performance_level = 'good'
            elif win_rate >= 30:
                performance_level = 'average'
            else:
                performance_level = 'struggling'
            
            # Calculate recent form trend
            recent_results = [f['result'] for f in recent_form[:5]]
            recent_points = sum(3 if r == 'W' else 1 if r == 'D' else 0 for r in recent_results)
            recent_form_rating = recent_points / (len(recent_results) * 3) * 100 if recent_results else 0
            
            if recent_form_rating >= 70:
                form_trend = 'hot'
            elif recent_form_rating >= 40:
                form_trend = 'decent'
            elif len(recent_results) >= 3:
                form_trend = 'cold'
            else:
                form_trend = 'insufficient_data'
            
            # Determine strengths
            offensive_strength = 'high' if avg_goals_for >= 2.5 else 'medium' if avg_goals_for >= 1.5 else 'low'
            defensive_strength = 'high' if avg_goals_against <= 1.0 else 'medium' if avg_goals_against <= 2.0 else 'low'
            
            # Get league position from standings
            league_position = 1  # Would calculate from standings table
            if hasattr(team, 'standings') and team.standings:
                league_position = getattr(team.standings, 'position', 1)
            
            # Count upcoming matches
            upcoming_matches = Match.query.filter(
                and_(
                    or_(Match.home_team_id == team.id, Match.away_team_id == team.id),
                    Match.date >= datetime.now().date(),
                    Match.home_team_score.is_(None)
                )
            ).count()
            
            team_performance.append({
                'team_id': team.id,
                'team_name': team.name,
                'league': {
                    'id': team.league.id,
                    'name': team.league.name,
                    'season_id': team.league.season_id
                } if team.league else None,
                'league_position': league_position,
                'season_stats': {
                    'matches_played': matches_played,
                    'wins': wins,
                    'draws': draws,
                    'losses': losses,
                    'goals_for': goals_for,
                    'goals_against': goals_against,
                    'goal_difference': goal_difference,
                    'points': points,
                    'win_rate_percent': round(win_rate, 1),
                    'avg_goals_for_per_match': round(avg_goals_for, 2),
                    'avg_goals_against_per_match': round(avg_goals_against, 2)
                },
                'performance_metrics': {
                    'performance_level': performance_level,
                    'form_trend': form_trend,
                    'recent_form_rating': round(recent_form_rating, 1),
                    'offensive_strength': offensive_strength,
                    'defensive_strength': defensive_strength
                },
                'recent_form': recent_form if include_form else [],
                'upcoming_matches': upcoming_matches
            })
        
        # Sort by points and goal difference
        team_performance.sort(key=lambda x: (-x['season_stats']['points'], -x['season_stats']['goal_difference']))
        
        # Generate league summary
        total_teams = len(team_performance)
        if total_teams > 0:
            avg_goals_per_match = sum(t['season_stats']['avg_goals_for_per_match'] for t in team_performance) / total_teams
            highest_scoring_team = max(team_performance, key=lambda x: x['season_stats']['goals_for'])
            best_defense_team = min(team_performance, key=lambda x: x['season_stats']['goals_against'])
            
            league_summary = {
                'total_teams': total_teams,
                'average_goals_per_match_per_team': round(avg_goals_per_match, 2),
                'highest_scoring_team': {
                    'name': highest_scoring_team['team_name'],
                    'goals': highest_scoring_team['season_stats']['goals_for']
                },
                'best_defensive_team': {
                    'name': best_defense_team['team_name'],
                    'goals_against': best_defense_team['season_stats']['goals_against']
                },
                'competitive_balance': 'high' if max(t['season_stats']['points'] for t in team_performance) - min(t['season_stats']['points'] for t in team_performance) <= 10 else 'medium'
            }
        else:
            league_summary = {'total_teams': 0}
        
        return jsonify({
            'team_performance': team_performance,
            'league_summary': league_summary,
            'filters_applied': {
                'season_id': season_id,
                'league_id': league_id,
                'team_id': team_id,
                'include_form': include_form,
                'min_matches': min_matches
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_team_performance: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/analytics/player-status', methods=['GET'])
@api_key_required
def get_player_status():
    """Analyze player status including new players, onboarding, and activity levels."""
    try:
        season_id = request.args.get('season_id', type=int)
        league_id = request.args.get('league_id', type=int)
        status = request.args.get('status', 'all')
        include_onboarding = request.args.get('include_onboarding', True, type=bool)
        
        # Get current season if not specified
        if not season_id:
            current_season = Season.query.filter(Season.is_current == True).first()
            season_id = current_season.id if current_season else None
        
        # Build players query
        players_query = Player.query.filter(Player.is_current_player == True)
        
        if league_id:
            players_query = players_query.filter(Player.teams.any(Team.league_id == league_id))
        
        players = players_query.all()
        
        player_status_list = []
        
        # Calculate cutoff dates
        recent_cutoff = datetime.now() - timedelta(days=30)
        new_player_cutoff = datetime.now() - timedelta(days=60)
        
        for player in players:
            # Determine status categories
            status_categories = []
            
            # Check if new player
            user_created = getattr(player.user, 'created_at', None) if player.user else None
            if user_created and user_created >= new_player_cutoff:
                status_categories.append('new')
            
            # Check team assignments
            if not player.teams:
                status_categories.append('unassigned')
            
            # Check approval status
            if player.user and not getattr(player.user, 'is_approved', True):
                status_categories.append('pending_approval')
            
            # Check onboarding completion
            if include_onboarding and player.user:
                has_completed_onboarding = getattr(player.user, 'has_completed_onboarding', False)
                if not has_completed_onboarding:
                    status_categories.append('needs_onboarding')
            
            # Calculate activity metrics
            recent_matches = 0
            recent_responses = 0
            if player.teams:
                team_ids = [team.id for team in player.teams]
                recent_matches_query = Match.query.filter(
                    and_(
                        or_(
                            Match.home_team_id.in_(team_ids),
                            Match.away_team_id.in_(team_ids)
                        ),
                        Match.date >= recent_cutoff.date()
                    )
                )
                
                if season_id:
                    recent_matches_query = recent_matches_query.filter(
                        or_(
                            Match.home_team.has(Team.league.has(League.season_id == season_id)),
                            Match.away_team.has(Team.league.has(League.season_id == season_id))
                        )
                    )
                
                recent_match_list = recent_matches_query.all()
                recent_matches = len(recent_match_list)
                
                if recent_match_list:
                    recent_match_ids = [m.id for m in recent_match_list]
                    recent_responses = Availability.query.filter(
                        and_(
                            Availability.player_id == player.id,
                            Availability.match_id.in_(recent_match_ids)
                        )
                    ).count()
            
            # Determine engagement level
            if recent_matches > 0:
                response_rate = recent_responses / recent_matches
                if response_rate < 0.3:
                    status_categories.append('low_engagement')
                else:
                    status_categories.append('active_member')
            else:
                if not status_categories:  # No recent matches but no other issues
                    status_categories.append('active_member')
            
            # Apply status filter
            if status != 'all' and status not in status_categories:
                continue
            
            # Determine roles
            roles = []
            if player.is_coach:
                roles.append('coach')
            if player.is_ref:
                roles.append('referee')
            if player.is_sub:
                roles.append('substitute')
            if not roles or 'coach' not in roles:  # Default to player if no specific roles or if not only a coach
                roles.append('player')
            
            # Get team assignments
            team_assignments = [
                {
                    'team_id': team.id,
                    'team_name': team.name,
                    'league': team.league.name if team.league else None,
                    'is_coach': player.is_coach and team in player.teams  # Simplified logic
                } for team in player.teams
            ]
            
            # Activity metrics
            activity_metrics = {
                'recent_matches_available': recent_matches,
                'recent_responses_given': recent_responses,
                'response_rate_recent': round((recent_responses / recent_matches * 100), 1) if recent_matches > 0 else 0,
                'last_activity': None  # Would need to track this separately
            }
            
            # Account info
            account_info = {
                'user_id': player.user.id if player.user else None,
                'username': player.user.username if player.user else None,
                'email': player.user.email if player.user else None,
                'is_approved': getattr(player.user, 'is_approved', False) if player.user else False,
                'created_at': user_created.isoformat() if user_created else None,
                'has_completed_onboarding': getattr(player.user, 'has_completed_onboarding', False) if player.user else False
            }
            
            # Contact info
            contact_info = {
                'phone': player.phone,
                'discord_id': player.discord_id
            }
            
            # Determine if needs attention
            needs_attention = any(cat in ['pending_approval', 'needs_onboarding', 'low_engagement', 'unassigned'] for cat in status_categories)
            
            player_status_list.append({
                'player_id': player.id,
                'name': player.name,
                'status_categories': status_categories,
                'roles': roles,
                'team_assignments': team_assignments,
                'activity_metrics': activity_metrics,
                'account_info': account_info,
                'contact_info': contact_info,
                'needs_attention': needs_attention
            })
        
        # Generate summary
        total_players = len(player_status_list)
        new_players = len([p for p in player_status_list if 'new' in p['status_categories']])
        unassigned_players = len([p for p in player_status_list if 'unassigned' in p['status_categories']])
        pending_approval = len([p for p in player_status_list if 'pending_approval' in p['status_categories']])
        needs_onboarding = len([p for p in player_status_list if 'needs_onboarding' in p['status_categories']])
        low_engagement = len([p for p in player_status_list if 'low_engagement' in p['status_categories']])
        players_needing_attention = len([p for p in player_status_list if p['needs_attention']])
        
        # Role distribution
        role_distribution = {}
        for player in player_status_list:
            for role in player['roles']:
                role_distribution[role] = role_distribution.get(role, 0) + 1
        
        # Engagement health
        active_players = len([p for p in player_status_list if 'active_member' in p['status_categories']])
        engagement_health = 'excellent' if active_players / max(total_players, 1) >= 0.8 else 'good' if active_players / max(total_players, 1) >= 0.6 else 'needs_improvement'
        
        # Onboarding completion rate
        onboarding_completion_rate = 0
        if include_onboarding and total_players > 0:
            completed_onboarding = total_players - needs_onboarding
            onboarding_completion_rate = completed_onboarding / total_players * 100
        
        summary = {
            'total_players': total_players,
            'new_players': new_players,
            'unassigned_players': unassigned_players,
            'pending_approval': pending_approval,
            'needs_onboarding_completion': needs_onboarding,
            'low_engagement_players': low_engagement,
            'players_needing_attention': players_needing_attention,
            'role_distribution': role_distribution,
            'engagement_health': engagement_health,
            'onboarding_completion_rate': round(onboarding_completion_rate, 1)
        }
        
        return jsonify({
            'player_status': player_status_list,
            'summary': summary,
            'filters_applied': {
                'season_id': season_id,
                'league_id': league_id,
                'status': status,
                'include_onboarding': include_onboarding
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_player_status: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/analytics/debug/team-rsvps', methods=['GET'])
@api_key_required
def debug_team_rsvps():
    """Debug RSVP data for specific team and match."""
    try:
        team_name = request.args.get('team_name', '').strip()
        match_id = request.args.get('match_id', type=int)
        
        if not team_name and not match_id:
            return jsonify({'error': 'Either team_name or match_id parameter is required'}), 400
        
        # Find team
        team = None
        if team_name:
            team = Team.query.filter(Team.name.ilike(f'%{team_name}%')).first()
            if not team:
                return jsonify({'error': f'Team with name containing "{team_name}" not found'}), 404
        
        # Find match
        match = None
        if match_id:
            match = Match.query.get(match_id)
            if not match:
                return jsonify({'error': f'Match with ID {match_id} not found'}), 404
            
            # If team wasn't specified, determine which team from the match
            if not team:
                # Return debug info for both teams
                return jsonify({
                    'error': 'Match found but no team specified. Please specify team_name parameter.',
                    'match_teams': {
                        'home_team': {'id': match.home_team.id, 'name': match.home_team.name} if match.home_team else None,
                        'away_team': {'id': match.away_team.id, 'name': match.away_team.name} if match.away_team else None
                    }
                }), 400
        
        # If match not specified, find a recent match for the team
        if not match and team:
            match = Match.query.filter(
                or_(Match.home_team_id == team.id, Match.away_team_id == team.id)
            ).order_by(Match.date.desc()).first()
            
            if not match:
                return jsonify({'error': f'No matches found for team "{team.name}"'}), 404
        
        # Verify team is in the match
        if team and match and team.id not in [match.home_team_id, match.away_team_id]:
            return jsonify({'error': f'Team "{team.name}" is not playing in match {match.id}'}), 400
        
        # Get team players
        team_players = team.players
        team_player_ids = [p.id for p in team_players]
        team_discord_ids = [p.discord_id for p in team_players if p.discord_id]
        
        # Get RSVP data for this match
        all_match_availabilities = Availability.query.filter(Availability.match_id == match.id).all()
        team_availabilities = [a for a in all_match_availabilities if a.player_id in team_player_ids]
        
        # Process responses
        responses = []
        for availability in team_availabilities:
            player = next((p for p in team_players if p.id == availability.player_id), None)
            responses.append({
                'player_id': availability.player_id,
                'player_name': player.name if player else 'Unknown',
                'discord_id': player.discord_id if player else None,
                'response': availability.response,
                'responded_at': availability.responded_at.isoformat() if availability.responded_at else None,
                'notes': getattr(availability, 'notes', None)
            })
        
        # Sort by response type and then by name
        response_order = {'available': 0, 'unavailable': 1, 'maybe': 2}
        responses.sort(key=lambda x: (response_order.get(x['response'].lower(), 3), x['player_name']))
        
        debug_data = {
            'team': {
                'id': team.id,
                'name': team.name,
                'player_count': len(team_players),
                'player_ids': team_player_ids,
                'discord_ids': team_discord_ids
            },
            'match': {
                'id': match.id,
                'date': match.date.isoformat(),
                'time': match.time.isoformat() if match.time else None,
                'home_team': match.home_team.name if match.home_team else None,
                'away_team': match.away_team.name if match.away_team else None,
                'location': match.location,
                'is_completed': match.home_team_score is not None
            },
            'rsvp_data': {
                'total_match_availabilities': len(all_match_availabilities),
                'team_availabilities': len(team_availabilities),
                'response_breakdown': {
                    'available': len([r for r in responses if r['response'].lower() in ['available', 'yes', 'attending']]),
                    'unavailable': len([r for r in responses if r['response'].lower() in ['unavailable', 'no', 'not_attending']]),
                    'maybe': len([r for r in responses if r['response'].lower() in ['maybe', 'tentative']]),
                    'no_response': len(team_player_ids) - len(team_availabilities)
                },
                'responses': responses
            }
        }
        
        return jsonify(debug_data)
        
    except Exception as e:
        logger.error(f"Error in debug_team_rsvps: {e}")
        return jsonify({'error': 'Internal server error'}), 500