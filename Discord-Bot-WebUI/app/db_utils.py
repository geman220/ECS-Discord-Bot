from app import db
from app.models import MLSMatch
from datetime import datetime, timedelta
import os
import sqlite3
import logging

# Get the logger for this module
logger = logging.getLogger(__name__)

def format_match_display_data(matches):
    for match in matches:
        if isinstance(match['date'], str):
            dt_object = datetime.fromisoformat(match['date'])
            match['formatted_date'] = dt_object.strftime('%m/%d/%Y %I:%M %p')
    return matches

def insert_mls_match(match_id, opponent, date_time, is_home_game, summary_link, stats_link, commentary_link, venue, competition):
    try:
        new_match = MLSMatch(
            match_id=match_id,
            opponent=opponent,
            date_time=date_time,
            is_home_game=is_home_game,
            summary_link=summary_link,
            stats_link=stats_link,
            commentary_link=commentary_link,
            venue=venue,
            competition=competition
        )
        db.session.add(new_match)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error inserting MLS match {match_id}: {str(e)}")
        return False

def update_mls_match(match_id, **kwargs):
    try:
        match = MLSMatch.query.filter_by(match_id=match_id).first()
        if match:
            for key, value in kwargs.items():
                setattr(match, key, value)
            db.session.commit()
            return True
        else:
            logger.warning(f"MLS match {match_id} not found for update.")
            return False
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating MLS match {match_id}: {str(e)}")
        return False

def delete_mls_match(match_id):
    try:
        match = MLSMatch.query.filter_by(match_id=match_id).first()
        if match:
            db.session.delete(match)
            db.session.commit()
            return True
        else:
            logger.warning(f"MLS match {match_id} not found for deletion.")
            return False
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting MLS match {match_id}: {str(e)}")
        return False

def get_upcoming_mls_matches(hours_ahead=24):
    try:
        now = datetime.utcnow()
        end_time = now + timedelta(hours=hours_ahead)
        return MLSMatch.query.filter(
            MLSMatch.date_time > now,
            MLSMatch.date_time <= end_time,
            MLSMatch.thread_created == False
        ).all()
    except Exception as e:
        logger.error(f"Error fetching upcoming MLS matches: {str(e)}")
        return []

def mark_mls_match_thread_created(match_id, thread_id):
    try:
        match = MLSMatch.query.filter_by(match_id=match_id).first()
        if match:
            match.thread_created = True
            match.discord_thread_id = thread_id
            db.session.commit()
            return True
        else:
            logger.warning(f"MLS match {match_id} not found for marking thread creation.")
            return False
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking MLS match {match_id} thread created: {str(e)}")
        return False

def load_match_dates_from_db():
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