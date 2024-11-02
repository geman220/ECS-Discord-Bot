from app import db
from app.models import MLSMatch
from datetime import datetime, timedelta
from contextlib import contextmanager
from app.decorators import db_operation, query_operation, session_context
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

@db_operation 
def insert_mls_match(match_id, opponent, date_time, is_home_game, summary_link, stats_link, commentary_link, venue, competition):
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
    db.session.flush()
    return new_match

@db_operation
def update_mls_match(match_id, **kwargs):
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        logger.warning(f"MLS match {match_id} not found for update.")
        return False
        
    for key, value in kwargs.items():
        setattr(match, key, value)
    return True

@db_operation
def delete_mls_match(match_id):
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        logger.warning(f"MLS match {match_id} not found for deletion.")
        return False
    db.session.delete(match)
    return True

@query_operation
def get_upcoming_mls_matches(hours_ahead=24):
    now = datetime.utcnow()
    end_time = now + timedelta(hours=hours_ahead)
    return MLSMatch.query.filter(
        MLSMatch.date_time > now,
        MLSMatch.date_time <= end_time,
        MLSMatch.thread_created == False
    ).all()

@db_operation
def mark_mls_match_thread_created(match_id, thread_id):
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if not match:
        logger.warning(f"MLS match {match_id} not found for marking thread creation.")
        return False
    match.thread_created = True
    match.discord_thread_id = thread_id
    return True

@query_operation
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

@contextmanager
def db_transaction():
    try:
        yield db.session
        db.session.commit()
    except Exception as e:
        db.session.rollback()  
        raise
    finally:
        db.session.close()

def safe_commit(session):
    try:
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error committing: {e}")
        return False