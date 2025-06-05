# app/external_api/serializers.py

"""
Data serialization utilities for external API endpoints.
"""

import logging
from datetime import datetime
from sqlalchemy import and_, or_

from app.core import db
from app.models import Match, player_teams

logger = logging.getLogger(__name__)


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
                team_association = db.session.query(player_teams).filter_by(
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
                            'matches_played': getattr(stat, 'matches_played', 0) or 0
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
            'is_active': True,
            'kit_url': team.kit_url
        }
    except Exception as e:
        logger.error(f"Error serializing team {getattr(team, 'id', 'unknown')}: {e}")
        return {
            'id': getattr(team, 'id', None),
            'name': getattr(team, 'name', 'Unknown'),
            'error': 'Partial data available'
        }
    
    if include_players and hasattr(team, 'players'):
        data['players'] = []
        try:
            for player in team.players:
                player_data = serialize_player(player, include_demographics=False)
                data['players'].append(player_data)
        except Exception as e:
            logger.warning(f"Error serializing players for team {team.id}: {e}")
            data['players'] = []
    
    if include_matches:
        # Get recent and upcoming matches
        data['recent_matches'] = []
        data['upcoming_matches'] = []
        try:
            # Recent completed matches (last 10)
            recent_matches = Match.query.filter(
                and_(
                    or_(
                        Match.home_team_id == team.id,
                        Match.away_team_id == team.id
                    ),
                    Match.home_team_score.isnot(None),
                    Match.date <= datetime.now().date()
                )
            ).order_by(Match.date.desc()).limit(10).all()
            
            for match in recent_matches:
                data['recent_matches'].append(serialize_match(match, include_rsvps=False, include_events=False))
            
            # Upcoming matches (next 10)
            upcoming_matches = Match.query.filter(
                and_(
                    or_(
                        Match.home_team_id == team.id,
                        Match.away_team_id == team.id
                    ),
                    Match.home_team_score.is_(None),
                    Match.date >= datetime.now().date()
                )
            ).order_by(Match.date.asc()).limit(10).all()
            
            for match in upcoming_matches:
                data['upcoming_matches'].append(serialize_match(match, include_rsvps=False, include_events=False))
                
        except Exception as e:
            logger.warning(f"Error serializing matches for team {team.id}: {e}")
            data['recent_matches'] = []
            data['upcoming_matches'] = []
    
    return data


def serialize_match(match, include_availability=False, include_events=False, include_rsvps=False, include_detailed=False):
    """Serialize match data for API response."""
    try:
        data = {
            'id': match.id,
            'date': match.date.isoformat() if match.date else None,
            'time': match.time.strftime('%H:%M') if match.time else None,
            'location': match.location,
            'field': getattr(match, 'field', match.location),
            'home_team': {
                'id': match.home_team.id,
                'name': match.home_team.name
            } if match.home_team else None,
            'away_team': {
                'id': match.away_team.id,
                'name': match.away_team.name
            } if match.away_team else None,
            'home_score': match.home_team_score,
            'away_score': match.away_team_score,
            'is_completed': match.home_team_score is not None,
            'referee': {
                'id': match.ref.id,
                'name': match.ref.name
            } if getattr(match, 'ref', None) else None,
            'league': {
                'id': match.home_team.league.id,
                'name': match.home_team.league.name
            } if match.home_team and match.home_team.league else None,
            'season': {
                'id': match.home_team.league.season.id,
                'name': match.home_team.league.season.name
            } if match.home_team and match.home_team.league and match.home_team.league.season else None
        }
    except Exception as e:
        logger.error(f"Error serializing match {getattr(match, 'id', 'unknown')}: {e}")
        return {
            'id': getattr(match, 'id', None),
            'error': 'Partial data available'
        }
    
    # Handle both include_availability (legacy) and include_rsvps (new API)
    if (include_availability or include_rsvps) and hasattr(match, 'availability'):
        data['availability'] = {
            'available': [],
            'unavailable': [],
            'maybe': []
        }
        try:
            for response in match.availability:
                player_data = {
                    'player_id': response.player_id,
                    'player_name': response.player.name if response.player else 'Unknown',
                    'response_date': response.responded_at.isoformat() if response.responded_at else None
                }
                
                # Add detailed information if requested
                if include_detailed and response.player:
                    try:
                        player_data.update({
                            'discord_id': getattr(response.player, 'discord_id', None),
                            'jersey_number': getattr(response.player, 'jersey_number', None),
                            'position': getattr(response.player, 'favorite_position', None),
                            'is_coach': getattr(response.player, 'is_coach', False),
                            'is_substitute': getattr(response.player, 'is_sub', False)
                        })
                    except Exception as e:
                        logger.warning(f"Error adding detailed player info for player {response.player_id}: {e}")
                
                # Normalize response values and categorize
                response_lower = response.response.lower()
                if response_lower in ['available', 'yes', 'attending']:
                    data['availability']['available'].append(player_data)
                elif response_lower in ['unavailable', 'no', 'not_attending']:
                    data['availability']['unavailable'].append(player_data)
                elif response_lower in ['maybe', 'tentative']:
                    data['availability']['maybe'].append(player_data)
        except Exception as e:
            logger.warning(f"Error serializing availability for match {match.id}: {e}")
    
    return data


def serialize_league(league, include_teams=False, include_standings=False):
    """Serialize league data for API response."""
    try:
        data = {
            'id': league.id,
            'name': league.name,
            'description': getattr(league, 'description', None),
            'season': {
                'id': league.season.id,
                'name': league.season.name,
                'is_current': league.season.is_current,
                'start_date': league.season.start_date.isoformat() if getattr(league.season, 'start_date', None) else None,
                'end_date': league.season.end_date.isoformat() if getattr(league.season, 'end_date', None) else None
            } if league.season else None,
            'team_count': len(league.teams) if hasattr(league, 'teams') else 0,
            'is_active': True  # Assuming all leagues in DB are active
        }
        
        if include_teams and hasattr(league, 'teams'):
            data['teams'] = [
                serialize_team(team, include_players=False, include_matches=False)
                for team in league.teams
            ]
        
        if include_standings:
            # Add standings data if requested
            # Note: This would need to be implemented based on your standings model/logic
            data['standings'] = []  # Placeholder for now
            
        return data
    except Exception as e:
        logger.error(f"Error serializing league {getattr(league, 'id', 'unknown')}: {e}")
        return {
            'id': getattr(league, 'id', None),
            'name': getattr(league, 'name', 'Unknown'),
            'error': 'Partial data available'
        }