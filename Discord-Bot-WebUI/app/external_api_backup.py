# app/external_api.py

"""
External API Module for Third-Party Integrations

This module provides secure, read-only API endpoints designed for external integrations
like ChatGPT Custom GPTs, analytics tools, and other third-party services.
All endpoints require API key authentication and provide comprehensive data
about players, teams, matches, demographics, statistics, and league information.
"""

import logging
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import func, desc, and_, or_
from sqlalchemy.orm import joinedload

from app.core import db
from app.models import (
    User, Player, Team, Match, League, Season, Availability,
    PlayerSeasonStats, PlayerCareerStats, Standings, player_teams
)
from app.database.db_models import MatchEvent, LiveMatch

# Set up module logger
logger = logging.getLogger(__name__)

# Create blueprint
external_api_bp = Blueprint('external_api', __name__, url_prefix='/api/external/v1')


def calculate_expected_attendance(available_count, maybe_count, maybe_factor=0.5):
    """
    Standardized attendance calculation used across all endpoints.
    
    Args:
        available_count: Number of players confirmed available
        maybe_count: Number of players marked as maybe
        maybe_factor: Weight given to maybe responses (default 0.5)
    
    Returns:
        Expected number of attendees
    """
    return available_count + (maybe_count * maybe_factor)


def get_substitution_urgency(expected_attendance, roster_size, min_players=9, ideal_players=15):
    """
    Standardized substitution urgency calculation for 9v9 format.
    
    Args:
        expected_attendance: Expected number of players
        roster_size: Total roster size
        min_players: Minimum players needed (default 9 for 9v9)
        ideal_players: Ideal number for rolling subs (default 15)
    
    Returns:
        urgency level: 'critical', 'high', 'medium', 'low', 'none'
    """
    if expected_attendance < min_players:
        return 'critical'  # Cannot field a team
    elif expected_attendance < min_players + 2:
        return 'high'      # Can barely field team, no subs
    elif expected_attendance < (ideal_players * 0.8):
        return 'medium'    # Limited substitution options
    elif expected_attendance < ideal_players:
        return 'low'       # Some substitution depth but not ideal
    else:
        return 'none'      # Good to excellent turnout


def api_key_required(f):
    """Decorator to require API key authentication for external endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        
        if not api_key:
            return jsonify({
                'error': 'API key required',
                'message': 'Please provide an API key in X-API-Key header or api_key parameter'
            }), 401
        
        # Get valid API keys from config
        valid_keys = current_app.config.get('EXTERNAL_API_KEYS', [])
        
        if api_key not in valid_keys:
            logger.warning(f"Invalid API key attempted: {api_key[:8]}...")
            return jsonify({
                'error': 'Invalid API key',
                'message': 'The provided API key is not valid'
            }), 401
        
        return f(*args, **kwargs)
    
    return decorated_function


def serialize_player(player, include_stats=False, include_teams=False, include_demographics=False):
    """Serialize player data for API response with comprehensive information."""
    try:
        data = {
            'id': player.id,
            'name': player.name,
            'jersey_number': player.jersey_number,
            'is_active': player.is_current_player,
            'is_coach': player.is_coach,
            'is_referee': player.is_ref,
            'is_substitute': player.is_sub,
            'discord_id': player.discord_id,
            'favorite_position': player.favorite_position,
            'profile_picture_url': player.profile_picture_url,
            'updated_at': player.updated_at.isoformat() if player.updated_at else None,
            'primary_league': {
                'id': player.primary_league.id,
                'name': player.primary_league.name
            } if player.primary_league else None,
            'primary_team': {
                'id': player.primary_team.id,
                'name': player.primary_team.name
            } if player.primary_team else None
        }
    except Exception as e:
        logger.error(f"Error in serialize_player base data for player {getattr(player, 'id', 'unknown')}: {e}")
        # Return minimal safe data if there's an error
        return {
            'id': getattr(player, 'id', None),
            'name': getattr(player, 'name', 'Unknown'),
            'error': 'Partial data available'
        }
    
    if include_demographics:
        data.update({
            'pronouns': getattr(player, 'pronouns', None),
            'jersey_size': getattr(player, 'jersey_size', None),
            'phone_verified': getattr(player, 'is_phone_verified', False),
            'sms_consent': getattr(player, 'sms_consent_given', False),
            'expected_weeks_available': getattr(player, 'expected_weeks_available', None),
            'unavailable_dates': getattr(player, 'unavailable_dates', None),
            'willing_to_referee': getattr(player, 'willing_to_referee', None),
            'other_positions': getattr(player, 'other_positions', None),
            'positions_not_to_play': getattr(player, 'positions_not_to_play', None),
            'frequency_play_goal': getattr(player, 'frequency_play_goal', None),
            'additional_info': getattr(player, 'additional_info', None),
            'player_notes': getattr(player, 'player_notes', None),
            'team_swap_preference': getattr(player, 'team_swap', None)
        })
        
        # User info with safe access
        if hasattr(player, 'user') and player.user:
            data['user_info'] = {
                'username': getattr(player.user, 'username', None),
                'email': getattr(player.user, 'email', None),
                'created_at': player.user.created_at.isoformat() if getattr(player.user, 'created_at', None) else None,
                'last_login': player.user.last_login.isoformat() if getattr(player.user, 'last_login', None) else None,
                'is_approved': getattr(player.user, 'is_approved', False),
                'has_completed_onboarding': getattr(player.user, 'has_completed_onboarding', False),
                'email_notifications': getattr(player.user, 'email_notifications', True),
                'sms_notifications': getattr(player.user, 'sms_notifications', True),
                'discord_notifications': getattr(player.user, 'discord_notifications', True),
                'profile_visibility': getattr(player.user, 'profile_visibility', 'everyone'),
                'roles': [role.name for role in player.user.roles] if getattr(player.user, 'roles', None) else []
            }
        else:
            data['user_info'] = None
    
    if include_teams and hasattr(player, 'teams') and player.teams:
        data['all_teams'] = []
        try:
            for team in player.teams:
                # Check if player is coach for this team
                team_association = g.db_session.query(player_teams).filter_by(
                    player_id=player.id, 
                    team_id=team.id
                ).first()
                is_coach_for_team = getattr(team_association, 'is_coach', False) if team_association else False
                
                team_data = {
                    'id': team.id,
                    'name': team.name,
                    'league': team.league.name if hasattr(team, 'league') and team.league else None,
                    'is_coach': is_coach_for_team,
                    'discord_channel_id': getattr(team, 'discord_channel_id', None),
                    'team_color': getattr(team, 'team_color', None)
                }
                data['all_teams'].append(team_data)
        except Exception as e:
            logger.warning(f"Error serializing teams for player {player.id}: {e}")
            data['all_teams'] = []
    
    if include_stats:
        # Season stats with safe access
        data['season_stats'] = []
        try:
            if hasattr(player, 'season_stats') and player.season_stats:
                for stat in player.season_stats:
                    try:
                        season_data = {
                            'season_id': getattr(stat, 'season_id', None),
                            'season_name': stat.season.name if hasattr(stat, 'season') and stat.season else None,
                            'goals': getattr(stat, 'goals', 0) or 0,
                            'assists': getattr(stat, 'assists', 0) or 0,
                            'yellow_cards': getattr(stat, 'yellow_cards', 0) or 0,
                            'red_cards': getattr(stat, 'red_cards', 0) or 0,
                            # These fields don't exist in the model, so we'll calculate or omit them
                            'matches_played': 0,  # Would need to be calculated from match data
                            'clean_sheets': 0,  # Goalkeeper-specific, not in base model
                            'saves': 0,  # Goalkeeper-specific, not in base model
                            'minutes_played': 0,  # Not tracked in base model
                            'goals_conceded': 0  # Goalkeeper-specific, not in base model
                        }
                        data['season_stats'].append(season_data)
                    except Exception as e:
                        logger.warning(f"Error serializing season stat for player {player.id}: {e}")
                        continue
        except Exception as e:
            logger.warning(f"Error accessing season_stats for player {player.id}: {e}")
        
        # Career stats with safe access
        data['career_stats'] = None
        try:
            if hasattr(player, 'career_stats') and player.career_stats:
                # career_stats is a relationship that returns a list
                career_stats_list = player.career_stats if isinstance(player.career_stats, list) else [player.career_stats]
                
                if career_stats_list and len(career_stats_list) > 0:
                    career = career_stats_list[0]
                    
                    # The model only has goals, assists, yellow_cards, red_cards
                    total_goals = getattr(career, 'goals', 0) or 0
                    total_assists = getattr(career, 'assists', 0) or 0
                    
                    # Calculate total matches from actual match participation
                    total_matches = 0
                    if hasattr(player, 'teams') and player.teams:
                        # Get matches for player's teams
                        team_ids = [team.id for team in player.teams]
                        if team_ids:
                            # Count matches where player's teams played and were completed
                            total_matches = Match.query.filter(
                                and_(
                                    or_(
                                        Match.home_team_id.in_(team_ids),
                                        Match.away_team_id.in_(team_ids)
                                    ),
                                    Match.home_team_score.isnot(None)  # Only completed matches
                                )
                            ).count()
                    
                    if total_matches == 0:
                        # Fallback: at least 1 to avoid division by zero
                        total_matches = 1
                    
                    data['career_stats'] = {
                        'total_matches': total_matches,
                        'total_goals': total_goals,
                        'total_assists': total_assists,
                        'total_yellow_cards': getattr(career, 'yellow_cards', 0) or 0,
                        'total_red_cards': getattr(career, 'red_cards', 0) or 0,
                        'total_clean_sheets': 0,  # Not tracked in model
                        'total_saves': 0,  # Not tracked in model
                        'total_minutes_played': 0,  # Not tracked in model
                        'goals_per_game': round(total_goals / max(total_matches, 1), 2),
                        'assists_per_game': round(total_assists / max(total_matches, 1), 2)
                    }
        except Exception as e:
            logger.warning(f"Error accessing career_stats for player {player.id}: {e}")
            data['career_stats'] = None
    
    return data


def serialize_team(team, include_players=False, include_matches=False, include_stats=False):
    """Serialize team data for API response with comprehensive information."""
    try:
        data = {
            'id': team.id,
            'name': team.name,
            'league': {
                'id': team.league.id,
                'name': team.league.name,
                'season': {
                    'id': team.league.season.id,
                    'name': team.league.season.name,
                    'is_current': team.league.season.is_current
                } if team.league and team.league.season else None
            } if team.league else None,
            'discord_channel_id': team.discord_channel_id,
            'discord_coach_role_id': team.discord_coach_role_id,
            'discord_player_role_id': team.discord_player_role_id,
            'team_color': None,  # Not in model
            'is_active': True,  # Not in model, assume active
            'kit_url': team.kit_url
        }
    except Exception as e:
        logger.error(f"Error serializing team {getattr(team, 'id', 'unknown')}: {e}")
        return {
            'id': getattr(team, 'id', None),
            'name': getattr(team, 'name', 'Unknown'),
            'error': 'Partial data available'
        }
    
    if include_players and team.players:
        data['players'] = []
        data['coaches'] = []
        
        for player in team.players:
            player_data = serialize_player(player, include_stats=False, include_demographics=False)
            
            # Check if player is coach for this team
            team_association = g.db_session.query(player_teams).filter_by(
                player_id=player.id, 
                team_id=team.id
            ).first()
            is_coach_for_team = team_association.is_coach if team_association else False
            
            if is_coach_for_team:
                data['coaches'].append(player_data)
            else:
                data['players'].append(player_data)
    
    if include_matches:
        # Get recent and upcoming matches
        all_matches = Match.query.filter(
            or_(Match.home_team_id == team.id, Match.away_team_id == team.id)
        ).order_by(desc(Match.match_date)).limit(20).all()
        
        recent_matches = [m for m in all_matches if m.home_team_score is not None][:10]
        upcoming_matches = [m for m in all_matches if m.home_team_score is None][:10]
        
        data['recent_matches'] = [
            serialize_match(match, include_teams=False, include_events=False)
            for match in recent_matches
        ]
        
        data['upcoming_matches'] = [
            serialize_match(match, include_teams=False, include_events=False)
            for match in upcoming_matches
        ]
    
    if include_stats:
        # Get team standings
        standings = Standings.query.filter_by(team_id=team.id).first()
        if standings:
            data['standings'] = {
                'wins': standings.wins,
                'losses': standings.losses,
                'draws': standings.draws,
                'goals_for': standings.goals_for,
                'goals_against': standings.goals_against,
                'goal_difference': standings.goal_difference,
                'points': standings.points,
                'position': standings.position
            }
        
        # Calculate additional team stats
        completed_matches = Match.query.filter(
            and_(
                or_(Match.home_team_id == team.id, Match.away_team_id == team.id),
                Match.home_team_score.isnot(None)
            )
        ).all()
        
        if completed_matches:
            total_goals_for = sum([
                (match.home_team_score if match.home_team_id == team.id else match.away_team_score)
                for match in completed_matches
            ])
            total_goals_against = sum([
                (match.away_team_score if match.home_team_id == team.id else match.home_team_score)
                for match in completed_matches
            ])
            
            data['calculated_stats'] = {
                'matches_played': len(completed_matches),
                'total_goals_for': total_goals_for,
                'total_goals_against': total_goals_against,
                'average_goals_per_match': round(total_goals_for / len(completed_matches), 2),
                'clean_sheets': len([m for m in completed_matches if 
                    (m.away_team_score == 0 if m.home_team_id == team.id else m.home_team_score == 0)])
            }
    
    return data


def serialize_match(match, include_teams=True, include_events=False, include_rsvps=False, include_detailed=False):
    """Serialize match data for API response with comprehensive information."""
    try:
        # Combine date and time fields
        match_datetime = None
        if match.date:
            if match.time:
                match_datetime = datetime.combine(match.date, match.time)
            else:
                match_datetime = datetime.combine(match.date, datetime.min.time())
        
        data = {
            'id': match.id,
            'match_date': match_datetime.isoformat() if match_datetime else None,
            'home_score': match.home_team_score,
            'away_score': match.away_team_score,
            'is_verified': match.home_team_verified and match.away_team_verified,
            'location': match.location,
            'match_type': 'regular',  # Not in model
            'discord_thread_id': getattr(match, 'discord_thread_id', None),  # Not in model
            'status': 'completed' if match.home_team_score is not None else 'scheduled',
            'result': None
        }
    except Exception as e:
        logger.error(f"Error serializing match {getattr(match, 'id', 'unknown')}: {e}")
        return {
            'id': getattr(match, 'id', None),
            'error': 'Partial data available'
        }
    
    # Calculate match result
    if match.home_team_score is not None and match.away_team_score is not None:
        if match.home_team_score > match.away_team_score:
            data['result'] = 'home_win'
        elif match.away_team_score > match.home_team_score:
            data['result'] = 'away_win'
        else:
            data['result'] = 'draw'
    
    if include_teams:
        data['home_team'] = serialize_team(match.home_team, include_players=False) if match.home_team else None
        data['away_team'] = serialize_team(match.away_team, include_players=False) if match.away_team else None
    
    if include_events:
        try:
            events = MatchEvent.query.filter_by(match_id=match.id).order_by(MatchEvent.minute).all()
            data['events'] = []
            for event in events:
                try:
                    event_data = {
                        'minute': event.minute,
                        'event_type': event.event_type,
                        'player_name': event.player.name if event.player else None,
                        'description': event.additional_data.get('description', '') if event.additional_data else '',
                        'team': event.team.name if event.team else None
                    }
                    data['events'].append(event_data)
                except Exception as e:
                    logger.warning(f"Error serializing event {event.id}: {e}")
                    continue
        except Exception as e:
            logger.warning(f"Error loading events for match {match.id}: {e}")
            data['events'] = []
    
    if include_rsvps:
        try:
            availabilities = Availability.query.filter_by(match_id=match.id).all()
            rsvp_summary = {
                'available': len([a for a in availabilities if a.response == 'available']),
                'unavailable': len([a for a in availabilities if a.response == 'unavailable']),
                'maybe': len([a for a in availabilities if a.response == 'maybe']),
                'no_response': 0,
                'total_responses': len(availabilities)
            }
            
            # Calculate no_response based on team rosters
            team_players = set()
            if match.home_team:
                team_players.update([p.id for p in match.home_team.players])
            if match.away_team:
                team_players.update([p.id for p in match.away_team.players])
            
            responded_players = set([a.player_id for a in availabilities if a.player_id])
            rsvp_summary['no_response'] = len(team_players - responded_players)
            
            data['rsvps'] = rsvp_summary
            
            if include_detailed:
                data['detailed_rsvps'] = []
                for a in availabilities:
                    try:
                        rsvp_data = {
                            'player_id': a.player_id,
                            'player_name': a.player.name if a.player else None,
                            'status': a.response,  # Model uses 'response' not 'status'
                            'submitted_at': a.responded_at.isoformat() if a.responded_at else None,  # Model uses 'responded_at'
                            'notes': None  # Not in model
                        }
                        data['detailed_rsvps'].append(rsvp_data)
                    except Exception as e:
                        logger.warning(f"Error serializing RSVP for availability {a.id}: {e}")
                        continue
        except Exception as e:
            logger.warning(f"Error loading RSVPs for match {match.id}: {e}")
            data['rsvps'] = {
                'available': 0,
                'unavailable': 0,
                'maybe': 0,
                'no_response': 0,
                'total_responses': 0
            }
    
    return data


def serialize_league(league, include_teams=False, include_standings=False):
    """Serialize league data for API response."""
    data = {
        'id': league.id,
        'name': league.name,
        'season': {
            'id': league.season.id,
            'name': league.season.name,
            'league_type': league.season.league_type,
            'is_current': league.season.is_current,
            'start_date': league.season.start_date.isoformat() if hasattr(league.season, 'start_date') and league.season.start_date else None,
            'end_date': league.season.end_date.isoformat() if hasattr(league.season, 'end_date') and league.season.end_date else None
        } if league.season else None
    }
    
    if include_teams:
        data['teams'] = [
            serialize_team(team, include_players=False, include_stats=include_standings)
            for team in league.teams
        ]
    
    if include_standings:
        standings = Standings.query.join(Team).filter(Team.league_id == league.id).order_by(
            desc(Standings.points), desc(Standings.goal_difference), desc(Standings.goals_for)
        ).all()
        
        data['standings'] = []
        for idx, standing in enumerate(standings):
            try:
                standings_data = {
                    'position': idx + 1,  # Calculate position based on order
                    'team': {
                        'id': standing.team.id,
                        'name': standing.team.name
                    },
                    'wins': standing.wins,
                    'losses': standing.losses,
                    'draws': standing.draws,
                    'goals_for': standing.goals_for,
                    'goals_against': standing.goals_against,
                    'goal_difference': standing.goal_difference,
                    'points': standing.points
                }
                data['standings'].append(standings_data)
            except Exception as e:
                logger.warning(f"Error serializing standing for team {getattr(standing, 'team_id', 'unknown')}: {e}")
                continue
    
    return data


# API Endpoints

@external_api_bp.route('/players', methods=['GET'])
@api_key_required
def get_players():
    """Get all players with optional filtering and pagination."""
    try:
        # Query parameters
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 50, type=int), 100)  # Max 100 per page
        search = request.args.get('search', '').strip()
        team_id = request.args.get('team_id', type=int)
        league_id = request.args.get('league_id', type=int)
        position = request.args.get('position', '').strip()
        include_stats = request.args.get('include_stats', 'false').lower() == 'true'
        include_teams = request.args.get('include_teams', 'false').lower() == 'true'
        include_demographics = request.args.get('include_demographics', 'false').lower() == 'true'
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        coaches_only = request.args.get('coaches_only', 'false').lower() == 'true'
        
        # Build query
        query = Player.query.options(
            joinedload(Player.primary_league),
            joinedload(Player.primary_team),
            joinedload(Player.teams).joinedload(Team.league),
            joinedload(Player.user).joinedload(User.roles)
        )
        
        if active_only:
            query = query.filter(Player.is_current_player == True)
        
        if coaches_only:
            query = query.filter(Player.is_coach == True)
        
        if search:
            query = query.filter(
                or_(
                    Player.name.ilike(f'%{search}%'),
                    Player.user.has(User.username.ilike(f'%{search}%'))
                )
            )
        
        if team_id:
            query = query.filter(Player.teams.any(Team.id == team_id))
        
        if league_id:
            query = query.filter(Player.primary_league_id == league_id)
        
        if position:
            query = query.filter(
                or_(
                    Player.favorite_position.ilike(f'%{position}%'),
                    Player.other_positions.ilike(f'%{position}%')
                )
            )
        
        # Execute query with pagination
        players_paginated = query.paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Serialize results
        players_data = [
            serialize_player(
                player, 
                include_stats=include_stats, 
                include_teams=include_teams,
                include_demographics=include_demographics
            )
            for player in players_paginated.items
        ]
        
        return jsonify({
            'players': players_data,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': players_paginated.total,
                'pages': players_paginated.pages,
                'has_next': players_paginated.has_next,
                'has_prev': players_paginated.has_prev
            },
            'filters_applied': {
                'search': search,
                'team_id': team_id,
                'league_id': league_id,
                'position': position,
                'active_only': active_only,
                'coaches_only': coaches_only
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_players: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/players/<int:player_id>', methods=['GET'])
@api_key_required
def get_player(player_id):
    """Get detailed information about a specific player."""
    try:
        include_stats = request.args.get('include_stats', 'true').lower() == 'true'
        include_teams = request.args.get('include_teams', 'true').lower() == 'true'
        include_demographics = request.args.get('include_demographics', 'true').lower() == 'true'
        
        player = Player.query.options(
            joinedload(Player.primary_league),
            joinedload(Player.primary_team),
            joinedload(Player.teams).joinedload(Team.league),
            joinedload(Player.season_stats).joinedload(PlayerSeasonStats.season),
            joinedload(Player.career_stats),
            joinedload(Player.user).joinedload(User.roles)
        ).get(player_id)
        
        if not player:
            return jsonify({'error': 'Player not found'}), 404
        
        return jsonify({
            'player': serialize_player(
                player, 
                include_stats=include_stats, 
                include_teams=include_teams,
                include_demographics=include_demographics
            )
        })
        
    except Exception as e:
        logger.error(f"Error in get_player: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/teams', methods=['GET'])
@api_key_required
def get_teams():
    """Get all teams with optional filtering and pagination."""
    try:
        # Query parameters
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 50, type=int), 100)
        search = request.args.get('search', '').strip()
        league_id = request.args.get('league_id', type=int)
        season_id = request.args.get('season_id', type=int)
        include_players = request.args.get('include_players', 'false').lower() == 'true'
        include_matches = request.args.get('include_matches', 'false').lower() == 'true'
        include_stats = request.args.get('include_stats', 'false').lower() == 'true'
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        
        # Build query
        query = Team.query.options(
            joinedload(Team.league).joinedload(League.season),
            joinedload(Team.players).joinedload(Player.user)
        )
        
        if active_only:
            query = query.filter(getattr(Team, 'is_active', True) == True)
        
        if search:
            query = query.filter(Team.name.ilike(f'%{search}%'))
        
        if league_id:
            query = query.filter(Team.league_id == league_id)
        
        if season_id:
            query = query.filter(Team.league.has(League.season_id == season_id))
        
        # Execute query with pagination
        teams_paginated = query.paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Serialize results
        teams_data = [
            serialize_team(
                team, 
                include_players=include_players, 
                include_matches=include_matches,
                include_stats=include_stats
            )
            for team in teams_paginated.items
        ]
        
        return jsonify({
            'teams': teams_data,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': teams_paginated.total,
                'pages': teams_paginated.pages,
                'has_next': teams_paginated.has_next,
                'has_prev': teams_paginated.has_prev
            },
            'filters_applied': {
                'search': search,
                'league_id': league_id,
                'season_id': season_id,
                'active_only': active_only
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_teams: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/teams/<int:team_id>', methods=['GET'])
@api_key_required
def get_team(team_id):
    """Get detailed information about a specific team."""
    try:
        include_players = request.args.get('include_players', 'true').lower() == 'true'
        include_matches = request.args.get('include_matches', 'true').lower() == 'true'
        include_stats = request.args.get('include_stats', 'true').lower() == 'true'
        
        team = Team.query.options(
            joinedload(Team.league).joinedload(League.season),
            joinedload(Team.players).joinedload(Player.user)
        ).get(team_id)
        
        if not team:
            return jsonify({'error': 'Team not found'}), 404
        
        return jsonify({
            'team': serialize_team(
                team, 
                include_players=include_players, 
                include_matches=include_matches,
                include_stats=include_stats
            )
        })
        
    except Exception as e:
        logger.error(f"Error in get_team: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/matches', methods=['GET'])
@api_key_required
def get_matches():
    """Get matches with comprehensive filtering and pagination."""
    try:
        # Query parameters
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 50, type=int), 100)
        team_id = request.args.get('team_id', type=int)
        league_id = request.args.get('league_id', type=int)
        season_id = request.args.get('season_id', type=int)
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        include_events = request.args.get('include_events', 'false').lower() == 'true'
        include_rsvps = request.args.get('include_rsvps', 'false').lower() == 'true'
        include_detailed_rsvps = request.args.get('include_detailed_rsvps', 'false').lower() == 'true'
        status = request.args.get('status')  # 'scheduled', 'completed'
        location = request.args.get('location', '').strip()
        
        # Build query
        query = Match.query.options(
            joinedload(Match.home_team).joinedload(Team.league),
            joinedload(Match.away_team).joinedload(Team.league)
        )
        
        if team_id:
            query = query.filter(
                or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
            )
        
        if league_id:
            query = query.filter(
                or_(
                    Match.home_team.has(Team.league_id == league_id),
                    Match.away_team.has(Team.league_id == league_id)
                )
            )
        
        if season_id:
            query = query.filter(
                or_(
                    Match.home_team.has(Team.league.has(League.season_id == season_id)),
                    Match.away_team.has(Team.league.has(League.season_id == season_id))
                )
            )
        
        if location:
            query = query.filter(Match.location.ilike(f'%{location}%'))
        
        if date_from:
            try:
                date_from_obj = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                query = query.filter(Match.date >= date_from_obj.date())
            except ValueError:
                return jsonify({'error': 'Invalid date_from format. Use ISO format.'}), 400
        
        if date_to:
            try:
                date_to_obj = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                query = query.filter(Match.date <= date_to_obj.date())
            except ValueError:
                return jsonify({'error': 'Invalid date_to format. Use ISO format.'}), 400
        
        if status == 'completed':
            query = query.filter(Match.home_team_score.isnot(None))
        elif status == 'scheduled':
            query = query.filter(Match.home_team_score.is_(None))
        
        # Order by match date
        query = query.order_by(desc(Match.date))
        
        # Execute query with pagination
        matches_paginated = query.paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Serialize results
        matches_data = [
            serialize_match(
                match, 
                include_events=include_events, 
                include_rsvps=include_rsvps,
                include_detailed=include_detailed_rsvps
            )
            for match in matches_paginated.items
        ]
        
        return jsonify({
            'matches': matches_data,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': matches_paginated.total,
                'pages': matches_paginated.pages,
                'has_next': matches_paginated.has_next,
                'has_prev': matches_paginated.has_prev
            },
            'filters_applied': {
                'team_id': team_id,
                'league_id': league_id,
                'season_id': season_id,
                'date_from': date_from,
                'date_to': date_to,
                'status': status,
                'location': location
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_matches: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/matches/<int:match_id>', methods=['GET'])
@api_key_required
def get_match(match_id):
    """Get detailed information about a specific match."""
    try:
        include_events = request.args.get('include_events', 'true').lower() == 'true'
        include_rsvps = request.args.get('include_rsvps', 'true').lower() == 'true'
        include_detailed_rsvps = request.args.get('include_detailed_rsvps', 'true').lower() == 'true'
        
        match = Match.query.options(
            joinedload(Match.home_team).joinedload(Team.league),
            joinedload(Match.away_team).joinedload(Team.league)
        ).get(match_id)
        
        if not match:
            return jsonify({'error': 'Match not found'}), 404
        
        return jsonify({
            'match': serialize_match(
                match, 
                include_events=include_events, 
                include_rsvps=include_rsvps,
                include_detailed=include_detailed_rsvps
            )
        })
        
    except Exception as e:
        logger.error(f"Error in get_match: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/leagues', methods=['GET'])
@api_key_required
def get_leagues():
    """Get all leagues with optional filtering."""
    try:
        season_id = request.args.get('season_id', type=int)
        include_teams = request.args.get('include_teams', 'false').lower() == 'true'
        include_standings = request.args.get('include_standings', 'false').lower() == 'true'
        current_only = request.args.get('current_only', 'false').lower() == 'true'
        
        query = League.query.options(joinedload(League.season))
        
        if season_id:
            query = query.filter(League.season_id == season_id)
        
        if current_only:
            query = query.filter(League.season.has(Season.is_current == True))
        
        if include_teams:
            query = query.options(joinedload(League.teams))
        
        leagues = query.all()
        
        leagues_data = [
            serialize_league(league, include_teams=include_teams, include_standings=include_standings)
            for league in leagues
        ]
        
        return jsonify({
            'leagues': leagues_data,
            'filters_applied': {
                'season_id': season_id,
                'current_only': current_only
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_leagues: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/seasons', methods=['GET'])
@api_key_required
def get_seasons():
    """Get all seasons with comprehensive information."""
    try:
        current_only = request.args.get('current_only', 'false').lower() == 'true'
        include_leagues = request.args.get('include_leagues', 'false').lower() == 'true'
        
        query = Season.query
        
        if current_only:
            query = query.filter(Season.is_current == True)
        
        if include_leagues:
            query = query.options(joinedload(Season.leagues))
        
        seasons = query.order_by(desc(Season.is_current), Season.name).all()
        
        seasons_data = []
        for season in seasons:
            season_data = {
                'id': season.id,
                'name': season.name,
                'league_type': season.league_type,
                'is_current': season.is_current,
                'start_date': getattr(season, 'start_date', None).isoformat() if hasattr(season, 'start_date') and getattr(season, 'start_date') else None,
                'end_date': getattr(season, 'end_date', None).isoformat() if hasattr(season, 'end_date') and getattr(season, 'end_date') else None
            }
            
            if include_leagues:
                season_data['leagues'] = [
                    serialize_league(league, include_teams=False)
                    for league in season.leagues
                ]
            
            seasons_data.append(season_data)
        
        return jsonify({
            'seasons': seasons_data,
            'filters_applied': {
                'current_only': current_only
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_seasons: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/stats/summary', methods=['GET'])
@api_key_required
def get_stats_summary():
    """Get comprehensive statistics summary."""
    try:
        season_id = request.args.get('season_id', type=int)
        league_id = request.args.get('league_id', type=int)
        
        # Default to current season if no season specified
        if not season_id:
            current_season = Season.query.filter(Season.is_current == True).first()
            if current_season:
                season_id = current_season.id
        
        # Base counts
        total_players = Player.query.filter(Player.is_current_player == True).count()
        total_teams = Team.query.count()
        total_matches = Match.query.count()
        completed_matches = Match.query.filter(Match.home_team_score.isnot(None)).count()
        
        # Filter by season if provided
        query_filter = []
        if season_id:
            query_filter.append(Team.league.has(League.season_id == season_id))
        if league_id:
            query_filter.append(Team.league_id == league_id)
        
        if query_filter:
            teams_in_scope = Team.query.filter(and_(*query_filter)).all()
            team_ids = [t.id for t in teams_in_scope]
            
            if team_ids:
                total_teams = len(team_ids)
                total_matches = Match.query.filter(
                    or_(
                        Match.home_team_id.in_(team_ids),
                        Match.away_team_id.in_(team_ids)
                    )
                ).count()
                completed_matches = Match.query.filter(
                    and_(
                        or_(
                            Match.home_team_id.in_(team_ids),
                            Match.away_team_id.in_(team_ids)
                        ),
                        Match.home_team_score.isnot(None)
                    )
                ).count()
        
        # Recent activity
        recent_matches = Match.query.filter(
            Match.date >= (datetime.now() - timedelta(days=30)).date()
        ).count()
        
        upcoming_matches = Match.query.filter(
            and_(
                Match.date >= datetime.now().date(),
                Match.home_team_score.is_(None)
            )
        ).count()
        
        # Top performers - filter by season if provided
        scorer_query = g.db_session.query(
            PlayerSeasonStats.player_id,
            Player.name,
            func.sum(PlayerSeasonStats.goals).label('total_goals')
        ).join(Player).group_by(PlayerSeasonStats.player_id, Player.name)
        
        assist_query = g.db_session.query(
            PlayerSeasonStats.player_id,
            Player.name,
            func.sum(PlayerSeasonStats.assists).label('total_assists')
        ).join(Player).group_by(PlayerSeasonStats.player_id, Player.name)
        
        if season_id:
            scorer_query = scorer_query.filter(PlayerSeasonStats.season_id == season_id)
            assist_query = assist_query.filter(PlayerSeasonStats.season_id == season_id)
        
        top_scorers = scorer_query.order_by(desc('total_goals')).limit(5).all()
        top_assists = assist_query.order_by(desc('total_assists')).limit(5).all()
        
        return jsonify({
            'summary': {
                'total_players': total_players,
                'total_teams': total_teams,
                'total_matches': total_matches,
                'completed_matches': completed_matches,
                'recent_matches_30_days': recent_matches,
                'upcoming_matches': upcoming_matches,
                'completion_rate': round((completed_matches / total_matches * 100), 2) if total_matches > 0 else 0,
                'top_scorers': [
                    {'player_id': p[0], 'name': p[1], 'goals': int(p[2])}
                    for p in top_scorers
                ],
                'top_assists': [
                    {'player_id': p[0], 'name': p[1], 'assists': int(p[2])}
                    for p in top_assists
                ]
            },
            'filters_applied': {
                'season_id': season_id,
                'league_id': league_id
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_stats_summary: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/search', methods=['GET'])
@api_key_required
def search_all():
    """Search across players, teams, matches, and leagues."""
    try:
        query_text = request.args.get('q', '').strip()
        if not query_text:
            return jsonify({'error': 'Query parameter "q" is required'}), 400
        
        limit = min(request.args.get('limit', 10, type=int), 50)
        search_type = request.args.get('type', 'all')  # 'all', 'players', 'teams', 'matches', 'leagues'
        
        results = {}
        
        if search_type in ['all', 'players']:
            # Search players
            players = Player.query.filter(
                and_(
                    or_(
                        Player.name.ilike(f'%{query_text}%'),
                        Player.favorite_position.ilike(f'%{query_text}%'),
                        Player.user.has(User.username.ilike(f'%{query_text}%'))
                    ),
                    Player.is_current_player == True
                )
            ).options(joinedload(Player.user)).limit(limit).all()
            
            results['players'] = [
                serialize_player(p, include_stats=False, include_demographics=False) 
                for p in players
            ]
        
        if search_type in ['all', 'teams']:
            # Search teams
            teams = Team.query.filter(
                Team.name.ilike(f'%{query_text}%')
            ).options(joinedload(Team.league)).limit(limit).all()
            
            results['teams'] = [
                serialize_team(t, include_players=False) 
                for t in teams
            ]
        
        if search_type in ['all', 'leagues']:
            # Search leagues
            leagues = League.query.filter(
                League.name.ilike(f'%{query_text}%')
            ).options(joinedload(League.season)).limit(limit).all()
            
            results['leagues'] = [
                serialize_league(l, include_teams=False) 
                for l in leagues
            ]
        
        if search_type in ['all', 'matches']:
            # Search matches by location
            matches = Match.query.filter(
                Match.location.ilike(f'%{query_text}%')
            ).options(
                joinedload(Match.home_team),
                joinedload(Match.away_team)
            ).limit(limit).all()
            
            results['matches'] = [
                serialize_match(m, include_events=False, include_rsvps=False) 
                for m in matches
            ]
        
        return jsonify({
            'results': results,
            'query': query_text,
            'search_type': search_type,
            'limit': limit
        })
        
    except Exception as e:
        logger.error(f"Error in search_all: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@external_api_bp.route('/analytics/player-stats', methods=['GET'])
@api_key_required
def get_player_analytics():
    """Get advanced player statistics and analytics."""
    try:
        season_id = request.args.get('season_id', type=int)
        team_id = request.args.get('team_id', type=int)
        position = request.args.get('position', '').strip()
        min_matches = request.args.get('min_matches', 0, type=int)  # Default to 0 to include all players
        
        # Build base query - LEFT JOIN to include players even without stats
        query = g.db_session.query(
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
                        Match.home_team_score.isnot(None)  # Only completed matches
                    ]
                    if season_id:
                        # Filter by season through team's league
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
                'clean_sheets': 0,  # Not tracked in base model
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
        logger.error(f"Error in get_player_analytics: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


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
        attendance_query = g.db_session.query(
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
        logger.error(f"Error in get_attendance_analytics: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@external_api_bp.route('/analytics/substitution-needs', methods=['GET'])
@api_key_required
def get_substitution_needs():
    """Analyze which teams need substitutes for upcoming matches."""
    try:
        days_ahead = request.args.get('days_ahead', 14, type=int)  # Look ahead 2 weeks by default
        league_id = request.args.get('league_id', type=int)
        team_id = request.args.get('team_id', type=int)
        min_players_threshold = request.args.get('min_players', 9, type=int)  # Absolute minimum (9v9 format)
        ideal_players = request.args.get('ideal_players', 15, type=int)  # Ideal for rolling subs
        
        # Get upcoming matches
        end_date = (datetime.now() + timedelta(days=days_ahead)).date()
        
        upcoming_matches_query = Match.query.filter(
            and_(
                Match.date >= datetime.now().date(),
                Match.date <= end_date,
                Match.home_team_score.is_(None)  # Not yet played
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
                
                # Get all availabilities for this match from this team's players
                team_player_ids = [p.id for p in team.players]
                
                # Debug: Check if we have team players
                if not team_player_ids:
                    logger.warning(f"Team {team.id} ({team.name}) has no players assigned")
                
                # Get ALL availabilities for this match
                all_match_availabilities = Availability.query.filter(
                    Availability.match_id == match.id
                ).all()
                
                # Filter to only those from this team's players (by player_id OR discord_id)
                team_discord_ids = [p.discord_id for p in team.players if p.discord_id]
                availabilities = []
                
                for avail in all_match_availabilities:
                    # Include if player_id matches a team member
                    if avail.player_id and avail.player_id in team_player_ids:
                        availabilities.append(avail)
                    # Or if discord_id matches a team member (when player_id is null)
                    elif avail.discord_id in team_discord_ids:
                        availabilities.append(avail)
                
                # Debug: Log availability count and response values
                logger.debug(f"Team {team.name} (Match {match.id}): {len(team_player_ids)} players, {len(availabilities)} RSVPs")
                if availabilities:
                    response_values = [a.response for a in availabilities]
                    logger.debug(f"Response values for {team.name}: {response_values}")
                
                # Count responses - check for multiple possible response formats
                available_players = [a for a in availabilities if a.response.lower() in ['available', 'yes', 'attending']]
                unavailable_players = [a for a in availabilities if a.response.lower() in ['unavailable', 'no', 'not_attending']]
                maybe_players = [a for a in availabilities if a.response.lower() in ['maybe', 'tentative']]
                
                # Get players who have responded (either by player_id or discord_id match)
                responded_player_ids = set()
                team_discord_to_player = {p.discord_id: p.id for p in team.players if p.discord_id}
                
                for avail in availabilities:
                    if avail.player_id:
                        responded_player_ids.add(avail.player_id)
                    elif avail.discord_id in team_discord_to_player:
                        responded_player_ids.add(team_discord_to_player[avail.discord_id])
                
                no_response_player_ids = set(team_player_ids) - responded_player_ids
                
                # Get actual player objects for better data
                available_player_objects = Player.query.filter(
                    Player.id.in_([a.player_id for a in available_players if a.player_id])
                ).all()
                
                no_response_players = Player.query.filter(
                    Player.id.in_(no_response_player_ids)
                ).all()
                
                # Calculate substitute needs (contextual based on roster and format)
                confirmed_available = len(available_players)
                potential_available = confirmed_available + len(maybe_players)
                total_roster = len(team.players)
                
                # Contextual substitute needs for 9v9 with rolling subs
                roster_attendance_rate = confirmed_available / max(total_roster, 1)
                
                # Determine substitute needs and urgency based on confirmed attendance
                # 9v9 format: Need 9 to field team, but rolling subs work better with 12+
                
                if confirmed_available < 9:
                    urgency = 'critical'  # Can't field a team
                    needs_subs = True
                elif confirmed_available < 10:
                    urgency = 'high'      # Can field team but zero subs
                    needs_subs = True
                elif confirmed_available < 12:
                    urgency = 'medium'    # Minimal substitution options (1-2 subs)
                    needs_subs = False    # Can manage but not ideal
                else:
                    urgency = 'low' if confirmed_available < 15 else 'none'
                    needs_subs = False    # Good to excellent depth
                
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
                        'team_type': team_type  # 'home' or 'away'
                    },
                    'opponent': {
                        'id': match.away_team.id if team_type == 'home' else match.home_team.id,
                        'name': match.away_team.name if team_type == 'home' else match.home_team.name
                    } if (match.away_team and match.home_team) else None,
                    'roster_analysis': {
                        'total_roster_size': total_roster,
                        'confirmed_available': confirmed_available,
                        'unavailable': len(unavailable_players),
                        'maybe_available': len(maybe_players),
                        'no_response': len(no_response_player_ids),
                        'potential_available': potential_available,
                        'shortage_amount': max(0, min_players_threshold - confirmed_available)
                    },
                    'substitute_needs': {
                        'needs_substitutes': needs_subs,
                        'urgency': urgency,
                        'minimum_subs_needed': max(0, min_players_threshold - confirmed_available),
                        'recommended_subs': max(0, (min_players_threshold + 2) - potential_available)  # Include buffer
                    },
                    'available_players': [
                        {
                            'id': p.id,
                            'name': p.name,
                            'position': p.favorite_position
                        } for p in available_player_objects
                    ],
                    'no_response_players': [
                        {
                            'id': p.id,
                            'name': p.name,
                            'position': p.favorite_position,
                            'needs_follow_up': True
                        } for p in no_response_players
                    ]
                })
        
        # Sort by urgency and date
        urgency_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
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
        logger.error(f"Error in get_substitution_needs: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@external_api_bp.route('/analytics/match-insights', methods=['GET'])
@api_key_required
def get_match_insights():
    """Get detailed insights for specific matches or upcoming matches."""
    try:
        match_id = request.args.get('match_id', type=int)
        team_id = request.args.get('team_id', type=int)
        league_id = request.args.get('league_id', type=int)
        days_ahead = request.args.get('days_ahead', 7, type=int)
        include_historical = request.args.get('include_historical', 'false').lower() == 'true'
        
        match_insights = []
        
        if match_id:
            # Get specific match
            matches = [Match.query.get(match_id)]
            if not matches[0]:
                return jsonify({'error': 'Match not found'}), 404
        else:
            # Get upcoming matches
            query = Match.query.filter(
                Match.date >= datetime.now().date(),
                Match.date <= (datetime.now() + timedelta(days=days_ahead)).date()
            )
            
            if not include_historical:
                query = query.filter(Match.home_team_score.is_(None))
            
            if team_id:
                query = query.filter(
                    or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
                )
            
            if league_id:
                query = query.filter(
                    or_(
                        Match.home_team.has(Team.league_id == league_id),
                        Match.away_team.has(Team.league_id == league_id)
                    )
                )
            
            matches = query.order_by(Match.date, Match.time).all()
        
        for match in matches:
            if not match:
                continue
                
            # Get RSVP data for both teams
            home_team_analysis = None
            away_team_analysis = None
            
            if match.home_team:
                home_team_analysis = analyze_team_for_match(match, match.home_team, 'home')
            
            if match.away_team:
                away_team_analysis = analyze_team_for_match(match, match.away_team, 'away')
            
            # Overall match analysis
            total_expected_attendance = 0
            total_confirmed_unavailable = 0
            total_no_response = 0
            
            if home_team_analysis:
                total_expected_attendance += home_team_analysis['expected_attendance']
                total_confirmed_unavailable += home_team_analysis['confirmed_unavailable']
                total_no_response += home_team_analysis['no_response_count']
            
            if away_team_analysis:
                total_expected_attendance += away_team_analysis['expected_attendance']
                total_confirmed_unavailable += away_team_analysis['confirmed_unavailable']
                total_no_response += away_team_analysis['no_response_count']
            
            # Determine match status
            days_until = (match.date - datetime.now().date()).days
            is_completed = match.home_team_score is not None
            
            match_status = 'completed' if is_completed else (
                'urgent' if days_until <= 2 else
                'upcoming' if days_until <= 7 else
                'future'
            )
            
            match_insight = {
                'match_id': match.id,
                'match_date': match.date.isoformat(),
                'match_time': match.time.isoformat() if match.time else None,
                'location': match.location,
                'days_until_match': days_until,
                'match_status': match_status,
                'is_completed': is_completed,
                'home_team_analysis': home_team_analysis,
                'away_team_analysis': away_team_analysis,
                'overall_insights': {
                    'total_expected_attendance': total_expected_attendance,
                    'total_confirmed_unavailable': total_confirmed_unavailable,
                    'total_awaiting_response': total_no_response,
                    'attendance_outlook': (
                        'excellent' if total_expected_attendance >= 30 else   # Both teams have great turnout (15+ each)
                        'good' if total_expected_attendance >= 24 else        # Good attendance (12+ each) 
                        'adequate' if total_expected_attendance >= 20 else    # Adequate (10+ each)
                        'concerning' if total_expected_attendance >= 18 else  # Just enough (9+ each)
                        'critical'                                            # Under minimum for competitive match
                    )
                }
            }
            
            match_insights.append(match_insight)
        
        return jsonify({
            'match_insights': match_insights,
            'summary': {
                'total_matches_analyzed': len(match_insights),
                'matches_with_good_attendance': len([m for m in match_insights if m['overall_insights']['attendance_outlook'] in ['excellent', 'good']]),
                'matches_needing_attention': len([m for m in match_insights if m['overall_insights']['attendance_outlook'] in ['concerning', 'critical']]),
                'total_players_awaiting_response': sum(m['overall_insights']['total_awaiting_response'] for m in match_insights)
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
        logger.error(f"Error in get_match_insights: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


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
        
        # Get detailed player info - handle multiple response formats
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
        include_predictions = request.args.get('include_predictions', 'true').lower() == 'true'
        
        # Build player query
        player_query = Player.query.filter(Player.is_current_player == True)
        
        if player_id:
            player_query = player_query.filter(Player.id == player_id)
        if team_id:
            player_query = player_query.filter(Player.teams.any(Team.id == team_id))
        if league_id:
            player_query = player_query.filter(Player.teams.any(Team.league_id == league_id))
            
        players = player_query.all()
        
        # Get relevant matches for the time period
        lookback_date = (datetime.now() - timedelta(days=days_lookback)).date()
        
        match_query = Match.query.filter(Match.date >= lookback_date)
        
        if season_id:
            match_query = match_query.filter(
                or_(
                    Match.home_team.has(Team.league.has(League.season_id == season_id)),
                    Match.away_team.has(Team.league.has(League.season_id == season_id))
                )
            )
        
        matches = match_query.all()
        match_ids = [m.id for m in matches]
        
        player_patterns = []
        
        for player in players:
            # Get player's team matches only
            player_team_ids = [t.id for t in player.teams]
            relevant_matches = [
                m for m in matches 
                if m.home_team_id in player_team_ids or m.away_team_id in player_team_ids
            ]
            relevant_match_ids = [m.id for m in relevant_matches]
            
            if not relevant_match_ids:
                continue
            
            # Get availability data
            availabilities = Availability.query.filter(
                and_(
                    Availability.player_id == player.id,
                    Availability.match_id.in_(relevant_match_ids)
                )
            ).all()
            
            # Analyze patterns
            total_matches = len(relevant_match_ids)
            total_responses = len(availabilities)
            
            available_responses = [a for a in availabilities if a.response == 'available']
            unavailable_responses = [a for a in availabilities if a.response == 'unavailable']
            maybe_responses = [a for a in availabilities if a.response == 'maybe']
            
            # Time-based patterns
            recent_matches = [m for m in relevant_matches if (datetime.now().date() - m.date).days <= 30]
            recent_match_ids = [m.id for m in recent_matches]
            recent_availabilities = [a for a in availabilities if a.match_id in recent_match_ids]
            recent_available = len([a for a in recent_availabilities if a.response == 'available'])
            
            # Calculate trends
            if len(recent_matches) > 0:
                recent_attendance_rate = round((recent_available / len(recent_matches) * 100), 1)
            else:
                recent_attendance_rate = 0
                
            overall_attendance_rate = round((len(available_responses) / total_matches * 100), 1) if total_matches > 0 else 0
            response_rate = round((total_responses / total_matches * 100), 1) if total_matches > 0 else 0
            
            # Day of week patterns (if we have enough data)
            day_patterns = {}
            if len(availabilities) >= 5:  # Only if we have reasonable data
                for avail in available_responses:
                    match = next((m for m in relevant_matches if m.id == avail.match_id), None)
                    if match:
                        day_name = match.date.strftime('%A')
                        day_patterns[day_name] = day_patterns.get(day_name, 0) + 1
            
            # Predict future availability
            prediction_confidence = 'low'
            predicted_attendance_rate = overall_attendance_rate
            
            if include_predictions and total_responses >= 3:
                # Simple prediction based on recent trend vs overall
                if abs(recent_attendance_rate - overall_attendance_rate) <= 10:
                    prediction_confidence = 'high'
                    predicted_attendance_rate = (recent_attendance_rate + overall_attendance_rate) / 2
                elif total_responses >= 8:
                    prediction_confidence = 'medium'
                    predicted_attendance_rate = (recent_attendance_rate * 0.7) + (overall_attendance_rate * 0.3)
                else:
                    predicted_attendance_rate = overall_attendance_rate
            
            # Categorize player reliability
            if response_rate >= 90 and overall_attendance_rate >= 80:
                reliability = 'highly_reliable'
            elif response_rate >= 70 and overall_attendance_rate >= 60:
                reliability = 'reliable'
            elif response_rate >= 50:
                reliability = 'inconsistent'
            else:
                reliability = 'unreliable'
            
            player_pattern = {
                'player_id': player.id,
                'name': player.name,
                'position': player.favorite_position,
                'teams': [{'id': t.id, 'name': t.name} for t in player.teams],
                'analysis_period': {
                    'days_analyzed': days_lookback,
                    'total_matches_in_period': total_matches,
                    'matches_responded_to': total_responses,
                    'recent_matches_30_days': len(recent_matches)
                },
                'attendance_patterns': {
                    'overall_attendance_rate': overall_attendance_rate,
                    'recent_attendance_rate': recent_attendance_rate,
                    'response_rate': response_rate,
                    'available_count': len(available_responses),
                    'unavailable_count': len(unavailable_responses),
                    'maybe_count': len(maybe_responses),
                    'no_response_count': total_matches - total_responses
                },
                'day_of_week_preferences': day_patterns,
                'reliability_score': reliability,
                'predictions': {
                    'predicted_attendance_rate': round(predicted_attendance_rate, 1),
                    'confidence': prediction_confidence,
                    'trend': (
                        'improving' if recent_attendance_rate > overall_attendance_rate + 5 else
                        'declining' if recent_attendance_rate < overall_attendance_rate - 5 else
                        'stable'
                    )
                } if include_predictions else None
            }
            
            player_patterns.append(player_pattern)
        
        # Sort by reliability and attendance rate
        player_patterns.sort(key=lambda x: (
            {'highly_reliable': 3, 'reliable': 2, 'inconsistent': 1, 'unreliable': 0}[x['reliability_score']],
            x['attendance_patterns']['overall_attendance_rate']
        ), reverse=True)
        
        # Generate insights
        total_players = len(player_patterns)
        reliable_players = len([p for p in player_patterns if p['reliability_score'] in ['highly_reliable', 'reliable']])
        declining_players = len([p for p in player_patterns if p.get('predictions', {}).get('trend') == 'declining'])
        
        return jsonify({
            'player_patterns': player_patterns,
            'summary': {
                'total_players_analyzed': total_players,
                'reliable_players': reliable_players,
                'unreliable_players': total_players - reliable_players,
                'players_with_declining_trend': declining_players,
                'average_response_rate': round(sum(p['attendance_patterns']['response_rate'] for p in player_patterns) / max(total_players, 1), 1),
                'average_attendance_rate': round(sum(p['attendance_patterns']['overall_attendance_rate'] for p in player_patterns) / max(total_players, 1), 1)
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
        logger.error(f"Error in get_player_patterns: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@external_api_bp.route('/analytics/referee-assignments', methods=['GET'])
@api_key_required
def get_referee_assignments():
    """Track referee assignments and identify matches needing refs."""
    try:
        days_ahead = request.args.get('days_ahead', 14, type=int)
        league_id = request.args.get('league_id', type=int)
        season_id = request.args.get('season_id', type=int)
        include_completed = request.args.get('include_completed', 'false').lower() == 'true'
        
        # Get matches in the specified timeframe
        end_date = (datetime.now() + timedelta(days=days_ahead)).date()
        
        match_query = Match.query.filter(
            and_(
                Match.date >= datetime.now().date(),
                Match.date <= end_date
            )
        )
        
        if not include_completed:
            match_query = match_query.filter(Match.home_team_score.is_(None))
        
        if league_id:
            match_query = match_query.filter(
                or_(
                    Match.home_team.has(Team.league_id == league_id),
                    Match.away_team.has(Team.league_id == league_id)
                )
            )
        
        if season_id:
            match_query = match_query.filter(
                or_(
                    Match.home_team.has(Team.league.has(League.season_id == season_id)),
                    Match.away_team.has(Team.league.has(League.season_id == season_id))
                )
            )
        
        matches = match_query.order_by(Match.date, Match.time).all()
        
        # Get all available referees
        available_refs = Player.query.filter(
            and_(
                Player.is_ref == True,
                Player.is_current_player == True
            )
        ).all()
        
        referee_analysis = []
        matches_needing_refs = []
        
        for match in matches:
            # Check if referee is assigned
            assigned_ref = None
            if match.ref_id:
                assigned_ref = Player.query.get(match.ref_id)
            
            days_until = (match.date - datetime.now().date()).days
            
            ref_info = {
                'match_id': match.id,
                'match_date': match.date.isoformat(),
                'match_time': match.time.isoformat() if match.time else None,
                'location': match.location,
                'days_until_match': days_until,
                'home_team': {
                    'id': match.home_team.id,
                    'name': match.home_team.name,
                    'league': match.home_team.league.name if match.home_team.league else None
                } if match.home_team else None,
                'away_team': {
                    'id': match.away_team.id,
                    'name': match.away_team.name,
                    'league': match.away_team.league.name if match.away_team.league else None
                } if match.away_team else None,
                'referee_assignment': {
                    'has_referee': assigned_ref is not None,
                    'referee_id': assigned_ref.id if assigned_ref else None,
                    'referee_name': assigned_ref.name if assigned_ref else None,
                    'referee_contact': assigned_ref.phone if assigned_ref and assigned_ref.phone else None
                },
                'urgency': (
                    'critical' if not assigned_ref and days_until <= 2 else
                    'high' if not assigned_ref and days_until <= 5 else
                    'medium' if not assigned_ref and days_until <= 10 else
                    'low' if assigned_ref else
                    'needs_assignment'
                )
            }
            
            referee_analysis.append(ref_info)
            
            if not assigned_ref:
                matches_needing_refs.append(ref_info)
        
        # Referee availability analysis
        ref_workload = {}
        for ref in available_refs:
            assigned_matches = [r for r in referee_analysis if r['referee_assignment']['referee_id'] == ref.id]
            ref_workload[ref.id] = {
                'referee_id': ref.id,
                'name': ref.name,
                'phone': ref.phone,
                'total_assigned': len(assigned_matches),
                'upcoming_matches': [
                    {
                        'match_id': m['match_id'],
                        'date': m['match_date'],
                        'teams': f"{m['home_team']['name'] if m['home_team'] else 'TBD'} vs {m['away_team']['name'] if m['away_team'] else 'TBD'}"
                    } for m in assigned_matches
                ],
                'availability_status': (
                    'overloaded' if len(assigned_matches) > 3 else
                    'busy' if len(assigned_matches) > 1 else
                    'available' if len(assigned_matches) <= 1 else
                    'free'
                )
            }
        
        # Summary statistics
        total_matches = len(referee_analysis)
        matches_with_refs = len([r for r in referee_analysis if r['referee_assignment']['has_referee']])
        critical_unassigned = len([r for r in referee_analysis if r['urgency'] == 'critical'])
        high_priority_unassigned = len([r for r in referee_analysis if r['urgency'] == 'high'])
        
        return jsonify({
            'referee_assignments': referee_analysis,
            'matches_needing_referees': matches_needing_refs,
            'referee_workload': list(ref_workload.values()),
            'summary': {
                'total_matches': total_matches,
                'matches_with_referees': matches_with_refs,
                'matches_needing_referees': len(matches_needing_refs),
                'critical_unassigned': critical_unassigned,
                'high_priority_unassigned': high_priority_unassigned,
                'total_available_referees': len(available_refs),
                'referee_coverage_rate': round((matches_with_refs / total_matches * 100), 1) if total_matches > 0 else 0,
                'recommendations': {
                    'immediate_action_needed': critical_unassigned > 0,
                    'refs_available_for_assignment': len([r for r in ref_workload.values() if r['availability_status'] in ['free', 'available']]),
                    'overloaded_referees': len([r for r in ref_workload.values() if r['availability_status'] == 'overloaded'])
                }
            },
            'filters_applied': {
                'days_ahead': days_ahead,
                'league_id': league_id,
                'season_id': season_id,
                'include_completed': include_completed
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_referee_assignments: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@external_api_bp.route('/analytics/substitute-requests', methods=['GET'])
@api_key_required
def get_substitute_requests():
    """Track which teams have requested substitutes and sub availability."""
    try:
        days_ahead = request.args.get('days_ahead', 14, type=int)
        league_id = request.args.get('league_id', type=int)
        season_id = request.args.get('season_id', type=int)
        team_id = request.args.get('team_id', type=int)
        
        # Get upcoming matches
        end_date = (datetime.now() + timedelta(days=days_ahead)).date()
        
        match_query = Match.query.filter(
            and_(
                Match.date >= datetime.now().date(),
                Match.date <= end_date,
                Match.home_team_score.is_(None)  # Only upcoming matches
            )
        )
        
        if league_id:
            match_query = match_query.filter(
                or_(
                    Match.home_team.has(Team.league_id == league_id),
                    Match.away_team.has(Team.league_id == league_id)
                )
            )
        
        if season_id:
            match_query = match_query.filter(
                or_(
                    Match.home_team.has(Team.league.has(League.season_id == season_id)),
                    Match.away_team.has(Team.league.has(League.season_id == season_id))
                )
            )
        
        if team_id:
            match_query = match_query.filter(
                or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
            )
        
        matches = match_query.order_by(Match.date, Match.time).all()
        
        # Check for temporary sub assignments (teams that have requested subs)
        from app.database.db_models import TemporarySubAssignment
        
        substitute_requests = []
        available_subs = []
        
        # Get all players marked as substitutes
        sub_players = Player.query.filter(
            and_(
                Player.is_sub == True,
                Player.is_current_player == True
            )
        ).all()
        
        for match in matches:
            # Check for temporary sub assignments for this match
            try:
                temp_subs = g.db_session.query(TemporarySubAssignment).filter(
                    TemporarySubAssignment.match_id == match.id
                ).all()
            except:
                # Table might not exist, skip temp sub tracking
                temp_subs = []
            
            days_until = (match.date - datetime.now().date()).days
            
            for team_type, team in [('home', match.home_team), ('away', match.away_team)]:
                if not team:
                    continue
                
                # Find temp subs assigned to this team for this match
                team_temp_subs = [ts for ts in temp_subs if ts.team_id == team.id]
                
                # Get RSVP data to determine if subs are needed
                team_player_ids = [p.id for p in team.players]
                
                # Debug team composition
                if not team_player_ids:
                    logger.warning(f"Team {team.id} ({team.name}) has no players assigned")
                
                # Get ALL availabilities for this match
                all_match_availabilities = Availability.query.filter(
                    Availability.match_id == match.id
                ).all()
                
                # Filter to only those from this team's players (by player_id OR discord_id)
                team_discord_ids = [p.discord_id for p in team.players if p.discord_id]
                availabilities = []
                
                for avail in all_match_availabilities:
                    # Include if player_id matches a team member
                    if avail.player_id and avail.player_id in team_player_ids:
                        availabilities.append(avail)
                    # Or if discord_id matches a team member (when player_id is null)
                    elif avail.discord_id in team_discord_ids:
                        availabilities.append(avail)
                
                # Debug RSVP data
                logger.debug(f"Team {team.name} (Match {match.id}): {len(team_player_ids)} players, {len(availabilities)} RSVPs")
                if availabilities:
                    response_values = [a.response for a in availabilities]
                    logger.debug(f"Response values for {team.name}: {response_values}")
                
                available_count = len([a for a in availabilities if a.response.lower() in ['available', 'yes', 'attending']])
                maybe_count = len([a for a in availabilities if a.response.lower() in ['maybe', 'tentative']])
                # Count actual responses (some might have discord_id but no player_id)
                responded_count = len(availabilities)  # All availabilities are responses
                no_response_count = len(team_player_ids) - responded_count
                
                # Determine if team likely needs subs (contextual based on roster size)
                expected_attendance = calculate_expected_attendance(available_count, maybe_count)
                roster_size = len(team_player_ids)
                
                # Calculate percentage of roster attending
                attendance_rate = expected_attendance / max(roster_size, 1)
                
                # 9v9 format: Need 9 to field team, but rolling subs work better with 12+
                if expected_attendance < 9:
                    needs_subs = True  # Critical - can't field a team
                elif expected_attendance < 10:
                    needs_subs = True  # High - can field team but zero subs
                else:
                    needs_subs = False  # Can manage with available players
                
                has_requested_subs = len(team_temp_subs) > 0
                
                sub_request_info = {
                    'match_id': match.id,
                    'match_date': match.date.isoformat(),
                    'match_time': match.time.isoformat() if match.time else None,
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
                    'substitute_status': {
                        'has_requested_subs': has_requested_subs,
                        'likely_needs_subs': needs_subs,
                        'subs_assigned': len(team_temp_subs),
                        'expected_attendance': round(expected_attendance, 1),
                        'players_not_responded': no_response_count
                    },
                    'assigned_substitutes': [
                        {
                            'player_id': ts.player_id,
                            'player_name': Player.query.get(ts.player_id).name if Player.query.get(ts.player_id) else 'Unknown',
                            'assigned_at': ts.created_at.isoformat() if ts.created_at else None,
                            'assigned_by': ts.assigned_by
                        } for ts in team_temp_subs
                    ],
                    'urgency': (
                        'critical' if needs_subs and not has_requested_subs and days_until <= 2 else
                        'high' if needs_subs and not has_requested_subs and days_until <= 5 else
                        'medium' if needs_subs and not has_requested_subs else
                        'resolved' if has_requested_subs else
                        'low'
                    )
                }
                
                substitute_requests.append(sub_request_info)
        
        # Analyze substitute availability
        for sub in sub_players:
            # Count how many matches this sub is assigned to
            try:
                assigned_matches = g.db_session.query(TemporarySubAssignment).filter(
                    and_(
                        TemporarySubAssignment.player_id == sub.id,
                        TemporarySubAssignment.match_id.in_([m.id for m in matches])
                    )
                ).count()
            except:
                assigned_matches = 0
            
            available_subs.append({
                'player_id': sub.id,
                'name': sub.name,
                'position': sub.favorite_position,
                'phone': sub.phone,
                'teams': [{'id': t.id, 'name': t.name} for t in sub.teams],
                'assignments_this_period': assigned_matches,
                'availability_status': (
                    'overloaded' if assigned_matches > 2 else
                    'busy' if assigned_matches > 0 else
                    'available'
                )
            })
        
        # Summary stats
        total_team_slots = len(substitute_requests)
        teams_requesting_subs = len([r for r in substitute_requests if r['substitute_status']['has_requested_subs']])
        teams_likely_needing_subs = len([r for r in substitute_requests if r['substitute_status']['likely_needs_subs']])
        critical_needs = len([r for r in substitute_requests if r['urgency'] == 'critical'])
        
        return jsonify({
            'substitute_requests': substitute_requests,
            'available_substitutes': available_subs,
            'summary': {
                'total_team_match_slots': total_team_slots,
                'teams_with_sub_requests': teams_requesting_subs,
                'teams_likely_needing_subs': teams_likely_needing_subs,
                'critical_substitute_needs': critical_needs,
                'total_available_subs': len(available_subs),
                'available_subs_not_assigned': len([s for s in available_subs if s['availability_status'] == 'available']),
                'substitute_fulfillment_rate': round((teams_requesting_subs / max(teams_likely_needing_subs, 1) * 100), 1),
                'recommendations': {
                    'immediate_action_needed': critical_needs > 0,
                    'subs_available_for_assignment': len([s for s in available_subs if s['availability_status'] == 'available']),
                    'teams_needing_follow_up': teams_likely_needing_subs - teams_requesting_subs
                }
            },
            'filters_applied': {
                'days_ahead': days_ahead,
                'league_id': league_id,
                'season_id': season_id,
                'team_id': team_id
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_substitute_requests: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@external_api_bp.route('/analytics/team-performance', methods=['GET'])
@api_key_required
def get_team_performance():
    """Analyze current season team performance, form, and standings."""
    try:
        season_id = request.args.get('season_id', type=int)
        league_id = request.args.get('league_id', type=int)
        team_id = request.args.get('team_id', type=int)
        include_form = request.args.get('include_form', 'true').lower() == 'true'
        min_matches = request.args.get('min_matches', 0, type=int)
        
        # Get current season if not specified
        if not season_id:
            current_season = Season.query.filter(Season.is_current == True).first()
            season_id = current_season.id if current_season else None
        
        if not season_id:
            return jsonify({'error': 'No current season found and no season_id provided'}), 400
        
        # Build team query
        team_query = Team.query.join(League).filter(League.season_id == season_id)
        
        if league_id:
            team_query = team_query.filter(Team.league_id == league_id)
        
        if team_id:
            team_query = team_query.filter(Team.id == team_id)
        
        teams = team_query.all()
        
        team_performance = []
        
        for team in teams:
            # Get all matches for this team in the season
            team_matches = Match.query.filter(
                and_(
                    or_(Match.home_team_id == team.id, Match.away_team_id == team.id),
                    or_(
                        Match.home_team.has(Team.league.has(League.season_id == season_id)),
                        Match.away_team.has(Team.league.has(League.season_id == season_id))
                    )
                )
            ).order_by(Match.date).all()
            
            # Filter completed matches
            completed_matches = [m for m in team_matches if m.home_team_score is not None]
            
            # Skip teams with fewer than min_matches
            if len(completed_matches) < min_matches:
                continue
            
            # Calculate basic stats
            wins = 0
            draws = 0
            losses = 0
            goals_for = 0
            goals_against = 0
            
            # Recent form (last 5 matches)
            recent_matches = completed_matches[-5:] if len(completed_matches) >= 5 else completed_matches
            recent_form = []
            recent_wins = 0
            
            for match in completed_matches:
                is_home = match.home_team_id == team.id
                team_score = match.home_team_score if is_home else match.away_team_score
                opponent_score = match.away_team_score if is_home else match.home_team_score
                
                goals_for += team_score
                goals_against += opponent_score
                
                if team_score > opponent_score:
                    wins += 1
                    result = 'W'
                elif team_score < opponent_score:
                    losses += 1
                    result = 'L'
                else:
                    draws += 1
                    result = 'D'
                
                # Track recent form
                if match in recent_matches:
                    recent_form.append({
                        'match_id': match.id,
                        'date': match.date.isoformat(),
                        'opponent': match.away_team.name if is_home else match.home_team.name,
                        'score': f"{team_score}-{opponent_score}",
                        'result': result,
                        'home_away': 'H' if is_home else 'A'
                    })
                    if result == 'W':
                        recent_wins += 1
            
            # Calculate derived stats
            total_matches = len(completed_matches)
            points = (wins * 3) + draws
            goal_difference = goals_for - goals_against
            
            # Win rates
            win_rate = round((wins / total_matches * 100), 1) if total_matches > 0 else 0
            recent_form_rating = round((recent_wins / len(recent_matches) * 100), 1) if recent_matches else 0
            
            # Calculate averages
            avg_goals_for = round(goals_for / total_matches, 2) if total_matches > 0 else 0
            avg_goals_against = round(goals_against / total_matches, 2) if total_matches > 0 else 0
            
            # Performance classification
            if win_rate >= 70:
                performance_level = 'excellent'
            elif win_rate >= 50:
                performance_level = 'good'
            elif win_rate >= 30:
                performance_level = 'average'
            else:
                performance_level = 'struggling'
            
            # Form trend
            if len(recent_matches) >= 3:
                if recent_form_rating >= 60:
                    form_trend = 'hot'
                elif recent_form_rating >= 40:
                    form_trend = 'decent'
                else:
                    form_trend = 'cold'
            else:
                form_trend = 'insufficient_data'
            
            # Calculate position (simplified - could be enhanced with actual standings table)
            team_stats = {
                'team_id': team.id,
                'team_name': team.name,
                'league': {
                    'id': team.league.id,
                    'name': team.league.name
                },
                'season_stats': {
                    'matches_played': total_matches,
                    'wins': wins,
                    'draws': draws,
                    'losses': losses,
                    'goals_for': goals_for,
                    'goals_against': goals_against,
                    'goal_difference': goal_difference,
                    'points': points,
                    'win_rate_percent': win_rate,
                    'avg_goals_for_per_match': avg_goals_for,
                    'avg_goals_against_per_match': avg_goals_against
                },
                'performance_metrics': {
                    'performance_level': performance_level,
                    'form_trend': form_trend,
                    'recent_form_rating': recent_form_rating,
                    'offensive_strength': (
                        'high' if avg_goals_for >= 2.5 else
                        'medium' if avg_goals_for >= 1.5 else
                        'low'
                    ),
                    'defensive_strength': (
                        'high' if avg_goals_against <= 1.0 else
                        'medium' if avg_goals_against <= 2.0 else
                        'low'
                    )
                },
                'recent_form': recent_form if include_form else None,
                'upcoming_matches': len([m for m in team_matches if m.home_team_score is None])
            }
            
            team_performance.append(team_stats)
        
        # Sort by points, then goal difference
        team_performance.sort(key=lambda x: (x['season_stats']['points'], x['season_stats']['goal_difference']), reverse=True)
        
        # Add league position
        for idx, team in enumerate(team_performance):
            team['league_position'] = idx + 1
        
        # Generate league insights
        if team_performance:
            total_teams = len(team_performance)
            avg_goals_per_match = sum(t['season_stats']['avg_goals_for_per_match'] for t in team_performance) / total_teams
            
            # Find leaders and strugglers
            top_team = team_performance[0] if team_performance else None
            bottom_team = team_performance[-1] if team_performance else None
            
            hot_teams = [t for t in team_performance if t['performance_metrics']['form_trend'] == 'hot']
            struggling_teams = [t for t in team_performance if t['performance_metrics']['performance_level'] == 'struggling']
            
            summary = {
                'total_teams': total_teams,
                'league_leader': {
                    'team_name': top_team['team_name'],
                    'points': top_team['season_stats']['points'],
                    'matches_played': top_team['season_stats']['matches_played']
                } if top_team else None,
                'most_struggling': {
                    'team_name': bottom_team['team_name'],
                    'points': bottom_team['season_stats']['points'],
                    'win_rate': bottom_team['season_stats']['win_rate_percent']
                } if bottom_team else None,
                'teams_in_good_form': len(hot_teams),
                'teams_struggling': len(struggling_teams),
                'average_goals_per_match': round(avg_goals_per_match, 2),
                'competitive_balance': (
                    'very_competitive' if top_team and bottom_team and (top_team['season_stats']['points'] - bottom_team['season_stats']['points']) <= 6 else
                    'competitive' if top_team and bottom_team and (top_team['season_stats']['points'] - bottom_team['season_stats']['points']) <= 12 else
                    'dominant_leaders'
                )
            }
        else:
            summary = {'total_teams': 0}
        
        return jsonify({
            'team_performance': team_performance,
            'league_summary': summary,
            'filters_applied': {
                'season_id': season_id,
                'league_id': league_id,
                'team_id': team_id,
                'include_form': include_form,
                'min_matches': min_matches
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_team_performance: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@external_api_bp.route('/debug/team-rsvps', methods=['GET'])
@api_key_required  
def debug_team_rsvps():
    """Debug endpoint to see raw RSVP data for a specific team and match."""
    try:
        team_name = request.args.get('team_name', '').strip()
        match_id = request.args.get('match_id', type=int)
        
        if not team_name and not match_id:
            return jsonify({'error': 'Either team_name or match_id required'}), 400
            
        # Find team by name if provided
        team = None
        if team_name:
            team = Team.query.filter(Team.name.ilike(f'%{team_name}%')).first()
            if not team:
                return jsonify({'error': f'Team not found: {team_name}'}), 404
        
        # Get match
        match = None
        if match_id:
            match = Match.query.get(match_id)
            if not match:
                return jsonify({'error': f'Match not found: {match_id}'}), 404
        
        # Get all availabilities for debugging
        if match and team:
            # Get team players
            team_player_ids = [p.id for p in team.players]
            team_discord_ids = [p.discord_id for p in team.players if p.discord_id]
            
            # Get all availabilities for this match
            all_availabilities = Availability.query.filter(Availability.match_id == match.id).all()
            
            # Filter to team
            team_availabilities = []
            for avail in all_availabilities:
                if avail.player_id and avail.player_id in team_player_ids:
                    team_availabilities.append(avail)
                elif avail.discord_id in team_discord_ids:
                    team_availabilities.append(avail)
            
            return jsonify({
                'team': {
                    'id': team.id,
                    'name': team.name,
                    'player_count': len(team.players),
                    'player_ids': team_player_ids,
                    'discord_ids': team_discord_ids
                },
                'match': {
                    'id': match.id,
                    'date': match.date.isoformat(),
                    'home_team': match.home_team.name,
                    'away_team': match.away_team.name
                },
                'rsvp_data': {
                    'total_match_availabilities': len(all_availabilities),
                    'team_availabilities': len(team_availabilities),
                    'responses': [
                        {
                            'player_id': a.player_id,
                            'discord_id': a.discord_id,
                            'response': a.response,
                            'responded_at': a.responded_at.isoformat() if a.responded_at else None
                        } for a in team_availabilities
                    ]
                }
            })
        
        return jsonify({'error': 'Both team_name and match_id required for debugging'}), 400
        
    except Exception as e:
        logger.error(f"Error in debug_team_rsvps: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@external_api_bp.route('/analytics/player-status', methods=['GET'])
@api_key_required
def get_player_status():
    """Analyze player status including new players, onboarding, and activity levels."""
    try:
        season_id = request.args.get('season_id', type=int)
        league_id = request.args.get('league_id', type=int)
        status_filter = request.args.get('status', '')  # 'new', 'inactive', 'unassigned', 'all'
        include_onboarding = request.args.get('include_onboarding', 'true').lower() == 'true'
        
        # Get current season if not specified
        if not season_id:
            current_season = Season.query.filter(Season.is_current == True).first()
            season_id = current_season.id if current_season else None
        
        # Build player query
        player_query = Player.query.filter(Player.is_current_player == True)
        
        if league_id:
            player_query = player_query.filter(Player.teams.any(Team.league_id == league_id))
        
        players = player_query.all()
        
        player_status_list = []
        
        for player in players:
            # Determine player status categories
            has_teams = len(player.teams) > 0
            has_completed_onboarding = player.user.has_completed_onboarding if player.user else False
            is_approved = player.user.is_approved if player.user else False
            
            # Check if player is new (created recently and/or no team assignments)
            is_new_player = False
            if player.user and player.user.created_at:
                days_since_creation = (datetime.utcnow() - player.user.created_at).days
                is_new_player = days_since_creation <= 30 or not has_teams
            
            # Check activity level based on RSVP responses
            recent_matches = []
            response_count = 0
            if season_id and has_teams:
                # Get matches for player's teams in current season
                team_ids = [t.id for t in player.teams]
                recent_match_query = Match.query.filter(
                    and_(
                        or_(Match.home_team_id.in_(team_ids), Match.away_team_id.in_(team_ids)),
                        Match.date >= (datetime.now() - timedelta(days=30)).date()
                    )
                )
                recent_matches = recent_match_query.all()
                
                # Count RSVP responses
                if recent_matches:
                    response_count = Availability.query.filter(
                        and_(
                            Availability.player_id == player.id,
                            Availability.match_id.in_([m.id for m in recent_matches])
                        )
                    ).count()
            
            # Determine activity level
            if recent_matches:
                response_rate = response_count / len(recent_matches)
                if response_rate >= 0.8:
                    activity_level = 'very_active'
                elif response_rate >= 0.5:
                    activity_level = 'active'
                elif response_rate >= 0.2:
                    activity_level = 'somewhat_active'
                else:
                    activity_level = 'inactive'
            else:
                activity_level = 'no_recent_matches'
            
            # Categorize player status
            status_categories = []
            if is_new_player:
                status_categories.append('new')
            if not has_teams:
                status_categories.append('unassigned')
            if not is_approved:
                status_categories.append('pending_approval')
            if not has_completed_onboarding:
                status_categories.append('needs_onboarding')
            if activity_level in ['inactive', 'somewhat_active']:
                status_categories.append('low_engagement')
            if not status_categories:
                status_categories.append('active_member')
            
            # Player roles and capabilities
            roles = []
            if player.is_coach:
                roles.append('coach')
            if player.is_ref:
                roles.append('referee')
            if player.is_sub:
                roles.append('substitute')
            if not roles:
                roles.append('player')
            
            player_status_info = {
                'player_id': player.id,
                'name': player.name,
                'status_categories': status_categories,
                'roles': roles,
                'team_assignments': [
                    {
                        'team_id': team.id,
                        'team_name': team.name,
                        'league': team.league.name if team.league else None
                    } for team in player.teams
                ],
                'activity_metrics': {
                    'activity_level': activity_level,
                    'recent_matches_count': len(recent_matches),
                    'rsvp_responses_count': response_count,
                    'response_rate_percent': round((response_count / len(recent_matches) * 100), 1) if recent_matches else 0
                },
                'account_info': {
                    'is_approved': is_approved,
                    'has_completed_onboarding': has_completed_onboarding,
                    'days_since_creation': (datetime.utcnow() - player.user.created_at).days if player.user and player.user.created_at else None,
                    'last_login': player.user.last_login.isoformat() if player.user and player.user.last_login else None,
                    'email_notifications': player.user.email_notifications if player.user else None,
                    'sms_notifications': player.user.sms_notifications if player.user else None
                } if include_onboarding else None,
                'contact_info': {
                    'phone': player.phone,
                    'phone_verified': player.is_phone_verified,
                    'discord_id': player.discord_id
                },
                'needs_attention': len([c for c in status_categories if c in ['pending_approval', 'needs_onboarding', 'unassigned', 'low_engagement']]) > 0
            }
            
            # Apply status filter
            if status_filter and status_filter != 'all':
                if status_filter not in status_categories:
                    continue
            
            player_status_list.append(player_status_info)
        
        # Sort by attention needed, then by name
        player_status_list.sort(key=lambda x: (not x['needs_attention'], x['name']))
        
        # Generate summary statistics
        total_players = len(player_status_list)
        new_players = len([p for p in player_status_list if 'new' in p['status_categories']])
        unassigned_players = len([p for p in player_status_list if 'unassigned' in p['status_categories']])
        pending_approval = len([p for p in player_status_list if 'pending_approval' in p['status_categories']])
        needs_onboarding = len([p for p in player_status_list if 'needs_onboarding' in p['status_categories']])
        inactive_players = len([p for p in player_status_list if 'low_engagement' in p['status_categories']])
        players_needing_attention = len([p for p in player_status_list if p['needs_attention']])
        
        # Role distribution
        role_counts = {}
        for player in player_status_list:
            for role in player['roles']:
                role_counts[role] = role_counts.get(role, 0) + 1
        
        summary = {
            'total_players': total_players,
            'new_players': new_players,
            'unassigned_players': unassigned_players,
            'pending_approval': pending_approval,
            'needs_onboarding_completion': needs_onboarding,
            'low_engagement_players': inactive_players,
            'players_needing_attention': players_needing_attention,
            'role_distribution': role_counts,
            'engagement_health': (
                'excellent' if inactive_players / max(total_players, 1) <= 0.1 else
                'good' if inactive_players / max(total_players, 1) <= 0.2 else
                'needs_improvement'
            ),
            'onboarding_completion_rate': round(((total_players - needs_onboarding) / max(total_players, 1) * 100), 1)
        }
        
        return jsonify({
            'player_status': player_status_list,
            'summary': summary,
            'filters_applied': {
                'season_id': season_id,
                'league_id': league_id,
                'status_filter': status_filter,
                'include_onboarding': include_onboarding
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_player_status: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


@external_api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint (no auth required)."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'api_version': 'v1',
        'endpoints': [
            'GET /api/external/v1/players',
            'GET /api/external/v1/players/{id}',
            'GET /api/external/v1/teams',
            'GET /api/external/v1/teams/{id}',
            'GET /api/external/v1/matches',
            'GET /api/external/v1/matches/{id}',
            'GET /api/external/v1/leagues',
            'GET /api/external/v1/seasons',
            'GET /api/external/v1/stats/summary',
            'GET /api/external/v1/search',
            'GET /api/external/v1/analytics/player-stats',
            'GET /api/external/v1/analytics/attendance',
            'GET /api/external/v1/analytics/substitution-needs',
            'GET /api/external/v1/analytics/match-insights',
            'GET /api/external/v1/analytics/player-patterns',
            'GET /api/external/v1/analytics/referee-assignments',
            'GET /api/external/v1/analytics/substitute-requests',
            'GET /api/external/v1/analytics/team-performance',
            'GET /api/external/v1/analytics/player-status',
            'GET /api/external/v1/health'
        ]
    })


# Error handlers
@external_api_bp.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Endpoint not found'}), 404


@external_api_bp.errorhandler(500)
def internal_error(error):
    g.db_session.rollback()
    return jsonify({'error': 'Internal server error'}), 500