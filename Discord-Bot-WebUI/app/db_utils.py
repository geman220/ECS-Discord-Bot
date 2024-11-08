from app.models import MLSMatch, Player, Team
from datetime import datetime, timedelta
from contextlib import contextmanager
from sqlalchemy.orm import joinedload
from app.decorators import db_operation, query_operation, session_context
import os
import sqlite3
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def format_match_display_data(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Format match display data with proper date formatting."""
    formatted_matches = []
    for match in matches:
        match_copy = match.copy()
        if isinstance(match_copy['date'], str):
            dt_object = datetime.fromisoformat(match_copy['date'])
            match_copy['formatted_date'] = dt_object.strftime('%m/%d/%Y %I:%M %p')
        formatted_matches.append(match_copy)
    return formatted_matches

@db_operation
def insert_mls_match(
    match_id: str,
    opponent: str,
    date_time: datetime,
    is_home_game: bool,
    summary_link: str,
    stats_link: str,
    commentary_link: str,
    venue: str,
    competition: str
) -> MLSMatch:
    """Insert a new MLS match with proper session management."""
    new_match = MLSMatch(
        match_id=match_id,
        opponent=opponent,
        date_time=date_time,
        is_home_game=is_home_game,
        summary_link=summary_link,
        stats_link=stats_link,
        commentary_link=commentary_link,
        venue=venue,
        competition=competition,
        live_reporting_status='not_started',
        live_reporting_scheduled=False,
        live_reporting_started=False,
        thread_created=False
    )
    db.session.add(new_match)
    return new_match

@db_operation
def update_mls_match(match_id: str, **kwargs) -> bool:
    """Update MLS match with proper session management."""
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        logger.warning(f"MLS match {match_id} not found for update.")
        return False
        
    for key, value in kwargs.items():
        setattr(match, key, value)
    return True

@db_operation
def delete_mls_match(match_id: str) -> bool:
    """Delete MLS match with proper session management."""
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        logger.warning(f"MLS match {match_id} not found for deletion.")
        return False
    db.session.delete(match)
    return True

@query_operation
def get_upcoming_mls_matches(hours_ahead: int = 24) -> List[MLSMatch]:
    """Get upcoming MLS matches with proper session management."""
    now = datetime.utcnow()
    end_time = now + timedelta(hours=hours_ahead)
    return MLSMatch.query.filter(
        MLSMatch.date_time > now,
        MLSMatch.date_time <= end_time,
        MLSMatch.thread_created == False
    ).all()

@db_operation
def mark_mls_match_thread_created(match_id: str, thread_id: str) -> bool:
    """Mark MLS match thread as created with proper session management."""
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        logger.warning(f"MLS match {match_id} not found for marking thread creation.")
        return False
    match.thread_created = True
    match.discord_thread_id = thread_id
    return True

@query_operation
def load_match_dates_from_db() -> List[Dict[str, Any]]:
    """Load match dates from database with proper session management."""
    matches = MLSMatch.query.all()
    return [
        {
            'match_id': match.match_id,
            'opponent': match.opponent,
            'date': match.date_time.isoformat(),
            'venue': match.venue,
            'is_home_game': match.is_home_game,
            'summary_link': match.summary_link,
            'stats_link': match.stats_link,
            'commentary_link': match.commentary_link,
            'competition': match.competition
        }
        for match in matches
    ]

def safe_commit() -> bool:
    """Safely commit changes to the database with proper error handling."""
    try:
        with session_context() as session:
            session.commit()
            return True
    except Exception as e:
        logger.error(f"Error committing: {e}")
        return False

@db_operation
def bulk_update_matches(updates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bulk update matches with proper session management."""
    try:
        success_count = 0
        failed_ids = []
        
        for update in updates:
            match_id = update.pop('match_id', None)
            if not match_id:
                continue
                
            match = MLSMatch.query.filter_by(match_id=match_id).first()
            if match:
                for key, value in update.items():
                    setattr(match, key, value)
                success_count += 1
            else:
                failed_ids.append(match_id)
        
        return {
            'success': True,
            'updated_count': success_count,
            'failed_ids': failed_ids
        }
    except Exception as e:
        logger.error(f"Error in bulk update: {e}")
        return {
            'success': False,
            'error': str(e)
        }

@query_operation
def get_match_by_id(match_id: str) -> Optional[MLSMatch]:
    """Get a single match by ID with proper session management."""
    return MLSMatch.query.filter_by(match_id=match_id).first()

@db_operation
def update_player_discord_info(player_id: int, current_roles: List[str], verified_time: datetime) -> bool:
    """Update player's Discord role information."""
    try:
        player = Player.query.get(player_id)
        if player:
            player.discord_roles = current_roles
            player.discord_last_verified = verified_time
            player.discord_needs_update = False
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating Discord info for player {player_id}: {str(e)}")
        return False

@db_operation
def mark_player_for_discord_update(player_id: int) -> bool:
    """Mark a player for Discord role update."""
    try:
        player = Player.query.get(player_id)
        if player:
            player.discord_needs_update = True
            return True
        return False
    except Exception as e:
        logger.error(f"Error marking player {player_id} for Discord update: {str(e)}")
        return False

@db_operation
def update_discord_channel_id(team_id: int, channel_id: str) -> bool:
    """Update team's Discord channel ID."""
    try:
        team = Team.query.get(team_id)
        if team:
            team.discord_channel_id = channel_id
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating Discord channel ID for team {team_id}: {str(e)}")
        return False

@db_operation
def update_discord_role_ids(team_id: int, coach_role_id: str = None, player_role_id: str = None) -> bool:
    """Update team's Discord role IDs."""
    try:
        team = Team.query.get(team_id)
        if team:
            if coach_role_id is not None:
                team.discord_coach_role_id = coach_role_id
            if player_role_id is not None:
                team.discord_player_role_id = player_role_id
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating Discord role IDs for team {team_id}: {str(e)}")
        return False

@query_operation
def get_players_needing_discord_update() -> List[Player]:
    """Get all players that need Discord role updates."""
    from datetime import datetime, timedelta
    threshold_date = datetime.utcnow() - timedelta(days=90)
    return Player.query.filter(
        (Player.discord_id.isnot(None)) &
        (
            (Player.discord_needs_update == True) |
            (Player.discord_last_verified.is_(None)) |
            (Player.discord_last_verified < threshold_date)
        )
    ).options(
        joinedload(Player.team),
        joinedload(Player.team).joinedload(Team.league)
    ).all()