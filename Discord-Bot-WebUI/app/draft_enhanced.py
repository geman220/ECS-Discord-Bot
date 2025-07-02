# app/draft_enhanced.py

"""
Enhanced Draft System

A modern, scalable draft system with comprehensive player information,
real-time updates, and improved user experience. Consolidates all league
drafts into a single, maintainable system with advanced features.
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, g, jsonify, request
from flask_login import login_required, current_user
from flask_socketio import emit, join_room, leave_room, rooms
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql import exists, and_, or_, func
from sqlalchemy import text, desc

from app.core import socketio, db
from app.decorators import role_required
from app.db_utils import mark_player_for_discord_update
from app.models import (
    League, Player, Team, Season, PlayerSeasonStats, PlayerCareerStats,
    Match, PlayerEvent, player_teams, player_league, Availability,
    PlayerTeamHistory, Schedule, PlayerAttendanceStats, PlayerImageCache
)
from app.attendance_service import AttendanceService
from app.image_cache_service import ImageCacheService
from app.draft_cache_service import DraftCacheService
from app.sockets.session import socket_session
from app.tasks.tasks_discord import assign_roles_to_player_task, remove_player_roles_task

logger = logging.getLogger(__name__)
draft_enhanced = Blueprint('draft_enhanced', __name__, url_prefix='/draft')


class DraftService:
    """Service class for draft operations with enhanced functionality."""
    
    @staticmethod
    def get_league_data(league_name: str) -> Tuple[Optional[League], List[League]]:
        """Get current league and all leagues with the given name."""
        session = g.db_session
        
        all_leagues = session.query(League).filter(League.name == league_name).all()
        current_league = (
            session.query(League)
            .join(League.season)
            .filter(League.name == league_name)
            .filter_by(is_current=True)
            .one_or_none()
        )
        
        return current_league, all_leagues
    
    @staticmethod
    def get_enhanced_player_data(players: List[Player], current_season_id: Optional[int] = None) -> List[Dict]:
        """Get enhanced player data with comprehensive stats and profile info - OPTIMIZED."""
        if not players:
            return []
        
        player_ids = [p.id for p in players]
        start_time = datetime.now()
        logger.debug(f"Processing {len(player_ids)} players for enhanced data")
        
        # Batch load all supporting data - removed parallel execution due to Flask context issues
        attendance_start = datetime.now()
        attendance_data = AttendanceService.get_attendance_stats(player_ids)
        logger.debug(f"Attendance data loaded in {(datetime.now() - attendance_start).total_seconds():.2f}s")
        
        history_start = datetime.now()
        team_history_data = DraftService._batch_load_team_history(player_ids)
        logger.debug(f"Team history loaded in {(datetime.now() - history_start).total_seconds():.2f}s")
        
        image_start = datetime.now()
        image_data = ImageCacheService.get_player_image_data(player_ids)
        logger.debug(f"Image data loaded in {(datetime.now() - image_start).total_seconds():.2f}s")
        
        # Log performance for debugging (reduced verbosity)
        if len(player_ids) <= 5:
            for pid, data in image_data.items():
                logger.debug(f"Player {pid} image optimized: {data.get('is_optimized', False)}")
        else:
            logger.debug(f"Image data loaded for {len(image_data)} players")
        
        # Build enhanced player data using optimized approach
        enhanced_players = []
        
        # Pre-calculate season stats lookup if needed
        season_stats_lookup = {}
        if current_season_id:
            for player in players:
                season_stats_lookup[player.id] = next(
                    (s for s in player.season_stats if s.season_id == current_season_id),
                    None
                )
        
        # Process players in optimized batch
        for player in players:
            # Get cached data
            player_stats = attendance_data.get(player.id, {})
            teams_played_on = team_history_data.get(player.id, 0)
            player_images = image_data.get(player.id, {})
            season_stats = season_stats_lookup.get(player.id) if current_season_id else None
            
            # Build image URLs efficiently
            original_url = player.profile_picture_url or '/static/img/default_player.png'
            thumbnail_url = player_images.get('thumbnail_url', original_url)
            
            enhanced_data = {
                'id': player.id,
                'name': player.name,
                'profile_picture_url': thumbnail_url,
                'profile_picture_medium': player_images.get('medium_url', original_url),
                'profile_picture_webp': player_images.get('webp_url', original_url),
                'image_optimized': player_images.get('is_optimized', False),
                'player_notes': player.player_notes or '',
                'favorite_position': player.favorite_position or 'Any',
                'other_positions': player.other_positions or '',
                'expected_weeks_available': player.expected_weeks_available or 'All weeks',
                'unavailable_dates': player.unavailable_dates or '',
                'jersey_number': player.jersey_number,
                'is_sub': player.is_sub,
                'willing_to_referee': player.willing_to_referee == 'Yes',
                
                # Career stats with safe access
                'career_goals': player.career_stats[0].goals if player.career_stats else 0,
                'career_assists': player.career_stats[0].assists if player.career_stats else 0,
                'career_yellow_cards': player.career_stats[0].yellow_cards if player.career_stats else 0,
                'career_red_cards': player.career_stats[0].red_cards if player.career_stats else 0,
                
                # Season stats
                'season_goals': season_stats.goals if season_stats else 0,
                'season_assists': season_stats.assists if season_stats else 0,
                'season_yellow_cards': season_stats.yellow_cards if season_stats else 0,
                'season_red_cards': season_stats.red_cards if season_stats else 0,
                
                # League experience
                'league_experience_seasons': teams_played_on,
                'experience_level': 'Veteran' if teams_played_on >= 3 else 'Experienced' if teams_played_on >= 1 else 'New Player',
                
                # Team info - optimized list comprehension
                'current_teams': [{'id': t.id, 'name': t.name} for t in player.teams],
                'primary_team_id': player.primary_team_id,
                
                # Attendance metrics - preserve None for no historical data
                'rsvp_response_rate': player_stats.get('response_rate', None),
                'attendance_estimate': player_stats.get('adjusted_attendance_rate', None),  # None indicates no historical data
                'total_matches_invited': player_stats.get('total_matches_invited', 0),
                'reliability_score': player_stats.get('reliability_score', None),  # None indicates no historical data
                'has_attendance_data': bool(player_stats)  # Flag to indicate if player has any attendance history
            }
            
            enhanced_players.append(enhanced_data)
        
        total_time = (datetime.now() - start_time).total_seconds()
        logger.debug(f"Enhanced player data processing completed in {total_time:.2f}s for {len(enhanced_players)} players")
        
        return enhanced_players
    
    @staticmethod
    def _batch_load_attendance(player_ids: List[int], season_id: Optional[int] = None) -> Dict[int, Dict]:
        """Fast batch load of cached attendance data using AttendanceService."""
        try:
            # Use the cached attendance service for lightning-fast lookups
            attendance_data = AttendanceService.get_attendance_stats(player_ids)
            
            # Convert to the format expected by the rest of the draft system
            result = {}
            for player_id, stats in attendance_data.items():
                result[player_id] = {
                    'response_rate': stats['response_rate'],
                    'attendance_estimate': stats['adjusted_attendance_rate'],  # Use adjusted rate
                    'reliability_score': stats['reliability_score'],
                    'total_invited': stats['total_matches_invited'],
                    # These aren't available in cached stats but kept for compatibility
                    'yes_count': 0,  # Could be added to stats table if needed
                    'no_count': 0,
                    'maybe_count': 0,
                    'pending_count': 0
                }
            
            return result
            
        except Exception as e:
            logger.warning(f"Error loading cached attendance data, using defaults: {e}")
            # Fallback to default values if service fails
            return {player_id: {
                'response_rate': 0,
                'attendance_estimate': 50,
                'reliability_score': 25,
                'total_invited': 0,
                'yes_count': 0,
                'no_count': 0,
                'maybe_count': 0,
                'pending_count': 0
            } for player_id in player_ids}
    
    @staticmethod
    def _batch_load_team_history(player_ids: List[int]) -> Dict[int, int]:
        """Batch load team history counts for league experience using PlayerTeamSeason records."""
        from app.models import PlayerTeamSeason, player_teams
        session = g.db_session
        
        try:
            # Count unique team-season combinations from PlayerTeamSeason
            # This gives us the actual seasons a player has played
            season_counts = (
                session.query(
                    PlayerTeamSeason.player_id,
                    func.count(func.distinct(PlayerTeamSeason.team_id)).label('teams_count')
                )
                .filter(PlayerTeamSeason.player_id.in_(player_ids))
                .group_by(PlayerTeamSeason.player_id)
                .all()
            )
            
            result = {record.player_id: record.teams_count for record in season_counts}
            
            # Also check current team assignments for players who might not have PlayerTeamSeason records yet
            try:
                current_team_counts = (
                    session.query(
                        player_teams.c.player_id,
                        func.count(func.distinct(player_teams.c.team_id)).label('teams_count')
                    )
                    .filter(player_teams.c.player_id.in_(player_ids))
                    .group_by(player_teams.c.player_id)
                    .all()
                )
                
                # For players without PlayerTeamSeason records, use current team count
                for record in current_team_counts:
                    player_id = record.player_id
                    if player_id not in result:
                        result[player_id] = record.teams_count
                    
            except Exception as e:
                logger.debug(f"Error querying current teams: {e}")
            
        except Exception as e:
            logger.warning(f"Error loading team history: {e}")
            result = {}
        
        # Add default 0 for players with no history
        for player_id in player_ids:
            if player_id not in result:
                result[player_id] = 0
        
        logger.debug(f"Team history counts for players {player_ids[:5]}{'...' if len(player_ids) > 5 else ''}: {[(pid, result.get(pid, 0)) for pid in player_ids[:5]]}")
        
        return result
    
    @staticmethod
    def _calculate_league_experience(player: Player, current_season_id: Optional[int] = None) -> Dict:
        """Calculate player's experience within this specific league/division."""
        from app.models import PlayerTeamHistory, Team, League
        
        session = g.db_session
        
        # Get the current league for context
        current_league = None
        if current_season_id:
            current_league = session.query(League).join(League.season).filter_by(id=current_season_id).first()
        
        league_name = current_league.name if current_league else None
        
        # Count seasons played in this league
        seasons_played = 0
        total_matches = 0
        
        if league_name:
            # Get all team histories for teams in this league
            # Each team history entry = one season, since teams are recreated each season
            team_histories = (
                session.query(PlayerTeamHistory)
                .join(Team)
                .join(League)
                .filter(PlayerTeamHistory.player_id == player.id)
                .filter(League.name == league_name)
                .all()
            )
            
            seasons_played = len(team_histories)  # Each team = one season
            
            # Count total matches by counting PlayerEvents in this league
            from app.models import PlayerEvent, Match, Schedule
            match_events = (
                session.query(PlayerEvent)
                .join(Match)
                .join(Schedule)
                .join(League, Schedule.season_id == League.season_id)
                .filter(PlayerEvent.player_id == player.id)
                .filter(League.name == league_name)
                .all()
            )
            
            total_matches = len(set(event.match_id for event in match_events))
        
        return {
            'seasons': seasons_played,
            'total_matches': total_matches,
            'league_name': league_name,
            'experience_level': 'Veteran' if seasons_played >= 3 else 'Experienced' if seasons_played >= 1 else 'First Season'
        }
    
    
    @staticmethod
    def get_draft_analytics(league_name: str) -> Dict:
        """Get draft analytics for the league with caching."""
        # Try cache first
        cached_analytics = DraftCacheService.get_draft_analytics_cache(league_name)
        if cached_analytics:
            logger.debug(f"Using cached analytics for {league_name}")
            return cached_analytics
        
        current_league, _ = DraftService.get_league_data(league_name)
        if not current_league:
            return {}
        
        session = g.db_session
        teams = current_league.teams
        current_league_name = current_league.name
        
        analytics = {
            'total_teams': len(teams),
            'total_players_drafted': 0,
            'avg_players_per_team': 0,
            'teams_summary': [],
            'position_distribution': {},
            'draft_progress': 0
        }
        
        total_drafted = 0
        position_counts = {}
        
        for team in teams:
            team_players = [p for p in team.players if p.is_current_player]
            team_count = len(team_players)
            total_drafted += team_count
            
            # Count positions
            for player in team_players:
                pos = getattr(player, 'favorite_position', 'Unknown')
                position_counts[pos] = position_counts.get(pos, 0) + 1
            
            # Calculate average experience level for team
            avg_experience = 0
            if team_players:
                total_experience = 0
                for player in team_players:
                    # Get player's team history count as experience indicator
                    team_history_count = len([th for th in player.team_history if th.team.league.name == current_league_name]) if hasattr(player, 'team_history') else 0
                    total_experience += team_history_count
                avg_experience = total_experience / team_count
            
            analytics['teams_summary'].append({
                'team_id': team.id,
                'team_name': team.name,
                'player_count': team_count,
                'avg_experience_level': avg_experience
            })
        
        analytics['total_players_drafted'] = total_drafted
        analytics['avg_players_per_team'] = total_drafted / max(len(teams), 1)
        analytics['position_distribution'] = position_counts
        analytics['draft_progress'] = min(100, (total_drafted / (len(teams) * 15)) * 100)  # Assuming 15 players per team target
        
        # Cache the analytics before returning
        DraftCacheService.set_draft_analytics_cache(league_name, analytics)
        
        return analytics


@draft_enhanced.route('/<league_name>')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def draft_league(league_name: str):
    """Enhanced draft page for any league."""
    print(f"🔴 DRAFT_ENHANCED ROUTE HIT: {league_name}")
    logger.info(f"🔴 Enhanced draft route accessed: {league_name}")
    
    # Validate league name
    valid_leagues = ['classic', 'premier', 'ecs_fc']
    if league_name.lower() not in valid_leagues:
        flash(f'Invalid league name: {league_name}', 'danger')
        return redirect(url_for('main.index'))
    
    # Normalize league name for database lookup
    db_league_name = {
        'classic': 'Classic',
        'premier': 'Premier', 
        'ecs_fc': 'ECS FC'
    }.get(league_name.lower())
    
    current_league, all_leagues = DraftService.get_league_data(db_league_name)
    
    if not current_league:
        flash(f'No current {db_league_name} league found.', 'danger')
        return redirect(url_for('main.index'))
    
    if not all_leagues:
        flash(f'No {db_league_name} leagues found.', 'danger')
        return redirect(url_for('main.index'))
    
    # Get teams (excluding Practice teams)
    teams = [team for team in current_league.teams if team.name != "Practice"]
    team_ids = [t.id for t in teams]
    
    # Get all players eligible for this league
    league_ids = [l.id for l in all_leagues]
    belongs_to_league = or_(
        Player.primary_league_id.in_(league_ids),
        exists().where(
            and_(
                player_league.c.player_id == Player.id,
                player_league.c.league_id.in_(league_ids)
            )
        )
    )
    
    # OPTIMIZED: Single query approach with conditional filtering
    # Get all eligible players in one query with optimized loading
    all_players_query = (
        g.db_session.query(Player)
        .filter(belongs_to_league)
        .filter(Player.is_current_player.is_(True))
        .options(
            joinedload(Player.career_stats),
            joinedload(Player.season_stats),
            selectinload(Player.teams),
            # Pre-load attendance and image relationships if they exist
            # joinedload(Player.attendance_stats),  # Uncomment if relationship exists
            # joinedload(Player.image_cache)        # Uncomment if relationship exists
        )
        .order_by(Player.name.asc())
    ).all()
    
    logger.debug(f"Loaded {len(all_players_query)} total players for processing")
    
    # Separate players into available/drafted using Python filtering (faster than DB queries)
    available_players_raw = []
    drafted_players_raw = []
    
    # Build team lookup for faster filtering
    team_ids_set = set(team_ids)
    
    for player in all_players_query:
        player_team_ids = {team.id for team in player.teams}
        if player_team_ids.intersection(team_ids_set):
            drafted_players_raw.append(player)
        else:
            available_players_raw.append(player)
    
    logger.debug(f"Separated into {len(available_players_raw)} available and {len(drafted_players_raw)} drafted players")
    
    # Try to get cached data first
    cache_key_available = f"{db_league_name}_available"
    cache_key_drafted = f"{db_league_name}_drafted"
    
    available_players = DraftCacheService.get_enhanced_players_cache(db_league_name, 'available')
    drafted_players = DraftCacheService.get_enhanced_players_cache(db_league_name, 'drafted')
    
    # If cache miss, process data and cache results
    if available_players is None or drafted_players is None:
        logger.debug(f"Cache miss for {db_league_name} - processing enhanced data")
        
        # Process enhanced data sequentially (parallel execution removed due to Flask context issues)
        if available_players is None:
            available_players = DraftService.get_enhanced_player_data(
                available_players_raw,
                current_league.season_id
            )
            DraftCacheService.set_enhanced_players_cache(db_league_name, 'available', available_players)
        
        if drafted_players is None:
            drafted_players = DraftService.get_enhanced_player_data(
                drafted_players_raw,
                current_league.season_id
            )
            DraftCacheService.set_enhanced_players_cache(db_league_name, 'drafted', drafted_players)
    else:
        logger.debug(f"Using cached player data for {db_league_name}")
    
    # Organize drafted players by team
    drafted_by_team = {team.id: [] for team in teams}
    logger.debug(f"Available teams for drafting: {[team.id for team in teams]}")
    
    for player in drafted_players:
        logger.debug(f"Player {player['name']} current teams: {player['current_teams']}")
        for team_info in player['current_teams']:
            team_id = team_info['id']
            if team_id in drafted_by_team:
                drafted_by_team[team_id].append(player)
                logger.debug(f"Added player {player['name']} to team {team_id}")
                break
    
    logger.debug(f"Final drafted_by_team counts: {[(team_id, len(players)) for team_id, players in drafted_by_team.items()]}")
    
    # Get draft analytics
    analytics = DraftService.get_draft_analytics(db_league_name)
    
    return render_template(
        'draft_enhanced.html',
        title=f'{db_league_name} League Draft',
        league_name=league_name,
        db_league_name=db_league_name,
        teams=teams,
        available_players=available_players,
        drafted_players_by_team=drafted_by_team,
        analytics=analytics,
        current_season_id=current_league.season_id
    )


@draft_enhanced.route('/api/status')
@login_required
def draft_status():
    """Check draft system status."""
    return jsonify({
        'status': 'ok',
        'user': current_user.username if current_user.is_authenticated else None,
        'timestamp': datetime.now().isoformat()
    })


@draft_enhanced.route('/api/<league_name>/players')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def get_players_api(league_name: str):
    """API endpoint for getting player data with filtering and sorting."""
    # Validate league name
    db_league_name = {
        'classic': 'Classic',
        'premier': 'Premier',
        'ecs_fc': 'ECS FC'
    }.get(league_name.lower())
    
    if not db_league_name:
        return jsonify({'error': 'Invalid league name'}), 400
    
    # Get query parameters
    search = request.args.get('search', '').strip()
    position = request.args.get('position', '').strip()
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')
    status = request.args.get('status', 'available')  # available, drafted, all
    
    current_league, all_leagues = DraftService.get_league_data(db_league_name)
    if not current_league:
        return jsonify({'error': 'League not found'}), 404
    
    # Build query based on status
    if status == 'available':
        # Available players
        team_ids = [t.id for t in current_league.teams if t.name != "Practice"]
        not_in_teams = ~exists().where(
            and_(
                player_teams.c.player_id == Player.id,
                player_teams.c.team_id.in_(team_ids)
            )
        )
        query = (
            g.db_session.query(Player)
            .filter(Player.is_current_player.is_(True))
            .filter(not_in_teams)
        )
    elif status == 'drafted':
        # Drafted players
        team_ids = [t.id for t in current_league.teams if t.name != "Practice"]
        query = (
            g.db_session.query(Player)
            .join(player_teams, player_teams.c.player_id == Player.id)
            .filter(player_teams.c.team_id.in_(team_ids))
            .filter(Player.is_current_player.is_(True))
        )
    else:
        # All players
        query = (
            g.db_session.query(Player)
            .filter(Player.is_current_player.is_(True))
        )
    
    # Apply filters
    if search:
        query = query.filter(Player.name.ilike(f'%{search}%'))
    
    if position:
        # This would need a position field in Player model
        # query = query.filter(Player.favorite_position.ilike(f'%{position}%'))
        pass
    
    # Apply sorting
    if sort_by == 'name':
        query = query.order_by(Player.name.asc() if sort_order == 'asc' else Player.name.desc())
    elif sort_by == 'goals':
        # This would need custom sorting logic
        pass
    
    query = query.options(
        joinedload(Player.career_stats),
        joinedload(Player.season_stats),
        selectinload(Player.teams)
    )
    
    players = DraftService.get_enhanced_player_data(
        query.all(),
        current_league.season_id
    )
    
    return jsonify({
        'players': players,
        'total': len(players),
        'status': status,
        'filters': {
            'search': search,
            'position': position,
            'sort_by': sort_by,
            'sort_order': sort_order
        }
    })


@draft_enhanced.route('/api/draft-player', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def api_draft_player():
    """HTTP API endpoint for drafting players (fallback when sockets fail)."""
    try:
        data = request.get_json()
        player_id = data.get('player_id')
        team_id = data.get('team_id')
        league_name = data.get('league_name')
        
        if not all([player_id, team_id, league_name]):
            return jsonify({'error': 'Missing required data'}), 400
        
        session = g.db_session
        
        # Get the league and validate
        league = session.query(League).filter(
            League.name == league_name,
            League.is_active == True
        ).first()
        
        if not league:
            return jsonify({'error': 'League not found'}), 404
        
        # Get player and team
        player = session.query(Player).filter(Player.id == player_id).first()
        team = session.query(Team).filter(
            Team.id == team_id,
            Team.league_id == league.id
        ).first()
        
        if not player:
            return jsonify({'error': 'Player not found'}), 404
        if not team:
            return jsonify({'error': 'Team not found'}), 404
        
        # Check if player is already on a team in this league
        existing_assignment = session.query(player_teams).filter(
            player_teams.c.player_id == player_id,
            player_teams.c.team_id.in_(
                session.query(Team.id).filter(Team.league_id == league.id)
            )
        ).first()
        
        if existing_assignment:
            return jsonify({'error': 'Player already assigned to a team'}), 400
        
        # Add player to team
        team.players.append(player)
        session.commit()
        
        # Mark player for Discord update
        mark_player_for_discord_update(session, player_id)
        
        # Return response in the same format as socket handler
        return jsonify({
            'player': {
                'id': player.id,
                'name': player.name,
                'profile_picture_url': player.profile_picture_url,
                'experience_level': player.experience_level,
                'position': player.favorite_position
            },
            'team_id': team.id,
            'team_name': team.name,
            'league_name': league_name
        })
        
    except Exception as e:
        logger.error(f"Error in API draft player: {str(e)}", exc_info=True)
        session.rollback()
        return jsonify({'error': 'Internal server error'}), 500


#
# Enhanced Socket.IO Event Handlers
#

# Connect handler is handled by socket_handlers.py
# @socketio.on('connect')
# def handle_draft_connect():
#     """Handle client connection to default namespace."""
#     logger.info(f"Client connected to draft system: {current_user.username if current_user.is_authenticated else 'Anonymous'}")
#     emit('connected', {'message': 'Connected to draft system'})


# Socket handlers temporarily moved to socket_handlers.py due to blueprint registration issues
# This ensures they get registered properly with Flask-SocketIO

