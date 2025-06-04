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
    
    if include_demographics:
        data.update({
            'pronouns': player.pronouns,
            'jersey_size': player.jersey_size,
            'phone_verified': player.is_phone_verified,
            'sms_consent': player.sms_consent_given,
            'expected_weeks_available': player.expected_weeks_available,
            'unavailable_dates': player.unavailable_dates,
            'willing_to_referee': player.willing_to_referee,
            'other_positions': player.other_positions,
            'positions_not_to_play': player.positions_not_to_play,
            'frequency_play_goal': player.frequency_play_goal,
            'additional_info': player.additional_info,
            'player_notes': player.player_notes,
            'team_swap_preference': player.team_swap,
            'user_info': {
                'username': player.user.username,
                'email': player.user.email,
                'created_at': player.user.created_at.isoformat() if player.user.created_at else None,
                'last_login': player.user.last_login.isoformat() if player.user.last_login else None,
                'is_approved': player.user.is_approved,
                'has_completed_onboarding': player.user.has_completed_onboarding,
                'email_notifications': player.user.email_notifications,
                'sms_notifications': player.user.sms_notifications,
                'discord_notifications': player.user.discord_notifications,
                'profile_visibility': player.user.profile_visibility,
                'roles': [role.name for role in player.user.roles] if player.user.roles else []
            }
        })
    
    if include_teams and player.teams:
        data['all_teams'] = []
        for team in player.teams:
            # Check if player is coach for this team
            team_association = db.session.query(player_teams).filter_by(
                player_id=player.id, 
                team_id=team.id
            ).first()
            is_coach_for_team = team_association.is_coach if team_association else False
            
            data['all_teams'].append({
                'id': team.id,
                'name': team.name,
                'league': team.league.name if team.league else None,
                'is_coach': is_coach_for_team,
                'discord_channel_id': team.discord_channel_id,
                'team_color': getattr(team, 'team_color', None)
            })
    
    if include_stats:
        # Season stats
        if player.season_stats:
            data['season_stats'] = []
            for stat in player.season_stats:
                season_data = {
                    'season_id': stat.season_id,
                    'season_name': stat.season.name if stat.season else None,
                    'matches_played': stat.matches_played or 0,
                    'goals': stat.goals or 0,
                    'assists': stat.assists or 0,
                    'yellow_cards': stat.yellow_cards or 0,
                    'red_cards': stat.red_cards or 0,
                    'clean_sheets': stat.clean_sheets or 0,
                    'saves': getattr(stat, 'saves', 0),
                    'minutes_played': getattr(stat, 'minutes_played', 0),
                    'goals_conceded': getattr(stat, 'goals_conceded', 0)
                }
                data['season_stats'].append(season_data)
        
        # Career stats
        if player.career_stats:
            career = player.career_stats[0]
            data['career_stats'] = {
                'total_matches': career.total_matches or 0,
                'total_goals': career.total_goals or 0,
                'total_assists': career.total_assists or 0,
                'total_yellow_cards': career.total_yellow_cards or 0,
                'total_red_cards': career.total_red_cards or 0,
                'total_clean_sheets': career.total_clean_sheets or 0,
                'total_saves': getattr(career, 'total_saves', 0),
                'total_minutes_played': getattr(career, 'total_minutes_played', 0),
                'goals_per_game': round((career.total_goals or 0) / max(career.total_matches or 1, 1), 2),
                'assists_per_game': round((career.total_assists or 0) / max(career.total_matches or 1, 1), 2)
            }
    
    return data


def serialize_team(team, include_players=False, include_matches=False, include_stats=False):
    """Serialize team data for API response with comprehensive information."""
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
            } if team.league.season else None
        } if team.league else None,
        'discord_channel_id': team.discord_channel_id,
        'discord_coach_role_id': team.discord_coach_role_id,
        'discord_player_role_id': team.discord_player_role_id,
        'team_color': getattr(team, 'team_color', None),
        'is_active': getattr(team, 'is_active', True),
        'kit_url': team.kit_url
    }
    
    if include_players and team.players:
        data['players'] = []
        data['coaches'] = []
        
        for player in team.players:
            player_data = serialize_player(player, include_stats=False, include_demographics=False)
            
            # Check if player is coach for this team
            team_association = db.session.query(player_teams).filter_by(
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
    data = {
        'id': match.id,
        'match_date': match.match_date.isoformat() if match.match_date else None,
        'home_score': match.home_team_score,
        'away_score': match.away_team_score,
        'is_verified': match.home_team_verified and match.away_team_verified,
        'location': match.location,
        'match_type': getattr(match, 'match_type', 'regular'),
        'discord_thread_id': match.discord_thread_id,
        'status': 'completed' if match.home_team_score is not None else 'scheduled',
        'result': None
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
        events = MatchEvent.query.filter_by(match_id=match.id).order_by(MatchEvent.minute).all()
        data['events'] = [
            {
                'minute': event.minute,
                'event_type': event.event_type,
                'player_name': event.player_name,
                'description': event.description,
                'team': event.team if hasattr(event, 'team') else None
            }
            for event in events
        ]
    
    if include_rsvps:
        availabilities = Availability.query.filter_by(match_id=match.id).all()
        rsvp_summary = {
            'available': len([a for a in availabilities if a.status == 'available']),
            'unavailable': len([a for a in availabilities if a.status == 'unavailable']),
            'maybe': len([a for a in availabilities if a.status == 'maybe']),
            'no_response': 0,
            'total_responses': len(availabilities)
        }
        
        # Calculate no_response based on team rosters
        team_players = set()
        if match.home_team:
            team_players.update([p.id for p in match.home_team.players])
        if match.away_team:
            team_players.update([p.id for p in match.away_team.players])
        
        responded_players = set([a.player_id for a in availabilities])
        rsvp_summary['no_response'] = len(team_players - responded_players)
        
        data['rsvps'] = rsvp_summary
        
        if include_detailed:
            data['detailed_rsvps'] = [
                {
                    'player_id': a.player_id,
                    'player_name': a.player.name if a.player else None,
                    'status': a.status,
                    'submitted_at': a.submitted_at.isoformat() if a.submitted_at else None,
                    'notes': a.notes
                }
                for a in availabilities
            ]
    
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
        
        data['standings'] = [
            {
                'position': standing.position or idx + 1,
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
            for idx, standing in enumerate(standings)
        ]
    
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
                query = query.filter(Match.match_date >= date_from_obj)
            except ValueError:
                return jsonify({'error': 'Invalid date_from format. Use ISO format.'}), 400
        
        if date_to:
            try:
                date_to_obj = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                query = query.filter(Match.match_date <= date_to_obj)
            except ValueError:
                return jsonify({'error': 'Invalid date_to format. Use ISO format.'}), 400
        
        if status == 'completed':
            query = query.filter(Match.home_team_score.isnot(None))
        elif status == 'scheduled':
            query = query.filter(Match.home_team_score.is_(None))
        
        # Order by match date
        query = query.order_by(desc(Match.match_date))
        
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
            Match.match_date >= datetime.now() - timedelta(days=30)
        ).count()
        
        upcoming_matches = Match.query.filter(
            and_(
                Match.match_date >= datetime.now(),
                Match.home_team_score.is_(None)
            )
        ).count()
        
        # Top performers
        top_scorers = db.session.query(
            PlayerSeasonStats.player_id,
            Player.name,
            func.sum(PlayerSeasonStats.goals).label('total_goals')
        ).join(Player).group_by(PlayerSeasonStats.player_id, Player.name).order_by(
            desc('total_goals')
        ).limit(5).all()
        
        top_assists = db.session.query(
            PlayerSeasonStats.player_id,
            Player.name,
            func.sum(PlayerSeasonStats.assists).label('total_assists')
        ).join(Player).group_by(PlayerSeasonStats.player_id, Player.name).order_by(
            desc('total_assists')
        ).limit(5).all()
        
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
        min_matches = request.args.get('min_matches', 1, type=int)
        
        # Build base query
        query = db.session.query(
            Player.id,
            Player.name,
            Player.favorite_position,
            func.coalesce(func.sum(PlayerSeasonStats.matches_played), 0).label('total_matches'),
            func.coalesce(func.sum(PlayerSeasonStats.goals), 0).label('total_goals'),
            func.coalesce(func.sum(PlayerSeasonStats.assists), 0).label('total_assists'),
            func.coalesce(func.sum(PlayerSeasonStats.yellow_cards), 0).label('total_yellows'),
            func.coalesce(func.sum(PlayerSeasonStats.red_cards), 0).label('total_reds'),
            func.coalesce(func.sum(PlayerSeasonStats.clean_sheets), 0).label('total_clean_sheets')
        ).outerjoin(PlayerSeasonStats).join(Player.user).filter(
            Player.is_current_player == True
        ).group_by(
            Player.id, Player.name, Player.favorite_position
        )
        
        # Apply filters
        if season_id:
            query = query.filter(
                or_(
                    PlayerSeasonStats.season_id == season_id,
                    PlayerSeasonStats.season_id.is_(None)
                )
            )
        
        if team_id:
            query = query.filter(Player.teams.any(Team.id == team_id))
        
        if position:
            query = query.filter(Player.favorite_position.ilike(f'%{position}%'))
        
        # Execute query
        stats = query.having(
            func.coalesce(func.sum(PlayerSeasonStats.matches_played), 0) >= min_matches
        ).order_by(desc('total_goals')).all()
        
        # Calculate analytics
        analytics_data = []
        for stat in stats:
            matches = max(stat.total_matches, 1)  # Avoid division by zero
            
            analytics_data.append({
                'player_id': stat.id,
                'name': stat.name,
                'position': stat.favorite_position,
                'matches_played': stat.total_matches,
                'goals': stat.total_goals,
                'assists': stat.total_assists,
                'yellow_cards': stat.total_yellows,
                'red_cards': stat.total_reds,
                'clean_sheets': stat.total_clean_sheets,
                'goals_per_match': round(stat.total_goals / matches, 2),
                'assists_per_match': round(stat.total_assists / matches, 2),
                'goal_contributions': stat.total_goals + stat.total_assists,
                'discipline_score': stat.total_yellows + (stat.total_reds * 2)
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
            'GET /api/external/v1/health'
        ]
    })


# Error handlers
@external_api_bp.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Endpoint not found'}), 404


@external_api_bp.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500