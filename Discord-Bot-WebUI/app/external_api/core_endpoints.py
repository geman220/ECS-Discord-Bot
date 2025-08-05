# app/external_api/core_endpoints.py

"""
Core CRUD endpoints for external API.
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import func, desc, and_, or_
from sqlalchemy.orm import joinedload

from flask import request, jsonify
from app.core import db
from app.models import (
    User, Player, Team, Match, League, Season, Availability,
    PlayerSeasonStats, PlayerCareerStats, Standings
)

from . import external_api_bp
from .auth import api_key_required
from .serializers import serialize_player, serialize_team, serialize_match, serialize_league
from .stats_utils import get_current_season, get_season_goal_leaders, get_season_assist_leaders

logger = logging.getLogger(__name__)


@external_api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint (no authentication required)."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '2.0.0',
        'modules': {
            'auth': 'loaded',
            'serializers': 'loaded',
            'stats_utils': 'loaded',
            'core_endpoints': 'loaded',
            'analytics': 'loaded'
        },
        'message': 'External API is running with modular architecture'
    })


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
        else:
            # Default to Pub League only, exclude ECS FC
            query = query.filter(
                Player.primary_league.has(
                    League.season.has(Season.league_type == 'Pub League')
                )
            )
        
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
        else:
            # Default to Pub League only, exclude ECS FC
            query = query.filter(
                Team.league.has(
                    League.season.has(Season.league_type == 'Pub League')
                )
            )
        
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
            query = query.filter(
                League.season.has(
                    and_(
                        Season.is_current == True,
                        Season.league_type == 'Pub League'
                    )
                )
            )
        
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
            query = query.filter(
                and_(
                    Season.is_current == True,
                    Season.league_type == 'Pub League'
                )
            )
        
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
                    serialize_league(league, include_teams=False, include_standings=False)
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
                    Player.is_current_player == True,
                    Player.primary_league.has(
                        League.season.has(Season.league_type == 'Pub League')
                    )
                )
            ).options(joinedload(Player.user)).limit(limit).all()
            
            results['players'] = [
                serialize_player(p, include_stats=False, include_demographics=False) 
                for p in players
            ]
        
        if search_type in ['all', 'teams']:
            # Search teams
            teams = Team.query.filter(
                and_(
                    Team.name.ilike(f'%{query_text}%'),
                    Team.league.has(
                        League.season.has(Season.league_type == 'Pub League')
                    )
                )
            ).options(joinedload(Team.league)).limit(limit).all()
            
            results['teams'] = [
                serialize_team(t, include_players=False) 
                for t in teams
            ]
        
        if search_type in ['all', 'leagues']:
            # Search leagues
            leagues = League.query.filter(
                and_(
                    League.name.ilike(f'%{query_text}%'),
                    League.season.has(Season.league_type == 'Pub League')
                )
            ).options(joinedload(League.season)).limit(limit).all()
            
            results['leagues'] = [
                serialize_league(l, include_teams=False, include_standings=False) 
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
                serialize_match(m, include_events=False, include_rsvps=False, include_detailed=False) 
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


@external_api_bp.route('/stats/summary', methods=['GET'])
@api_key_required
def get_stats_summary():
    """Get comprehensive statistics summary with fixed season handling."""
    try:
        season_id = request.args.get('season_id', type=int)
        league_id = request.args.get('league_id', type=int)
        
        # Always default to current season for goal/assist leaders to ensure current season data
        current_season = get_current_season()
        display_season_id = season_id if season_id else (current_season.id if current_season else None)
        
        # Base counts
        total_players = Player.query.filter(Player.is_current_player == True).count()
        total_teams = Team.query.count()
        total_matches = Match.query.count()
        completed_matches = Match.query.filter(Match.home_team_score.isnot(None)).count()
        
        # Filter by season if provided
        query_filter = []
        if display_season_id:
            query_filter.append(Team.league.has(League.season_id == display_season_id))
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
            Match.date >= (datetime.utcnow() - timedelta(days=30)).date()
        ).count()
        
        upcoming_matches = Match.query.filter(
            and_(
                Match.date >= datetime.utcnow().date(),
                Match.home_team_score.is_(None)
            )
        ).count()
        
        # Top performers - use current season by default for accurate "this season" results
        top_scorers = get_season_goal_leaders(season_id=display_season_id, limit=10)
        top_assists = get_season_assist_leaders(season_id=display_season_id, limit=10)
        
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
                    {'player_id': p.id, 'name': p.name, 'goals': int(p.season_goals)}
                    for p in top_scorers
                ],
                'top_assists': [
                    {'player_id': p.id, 'name': p.name, 'assists': int(p.season_assists)}
                    for p in top_assists
                ]
            },
            'filters_applied': {
                'season_id': display_season_id,
                'league_id': league_id,
                'using_current_season': display_season_id == (current_season.id if current_season else None)
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_stats_summary: {e}")
        return jsonify({'error': 'Internal server error'}), 500