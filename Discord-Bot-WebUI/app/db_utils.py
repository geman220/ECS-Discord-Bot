from app import db
from app.models import MLSMatch
from datetime import datetime, timedelta
import os
import sqlite3

def format_match_display_data(matches):
    for match in matches:
        if isinstance(match['date'], str):
            dt_object = datetime.fromisoformat(match['date'])
            match['formatted_date'] = dt_object.strftime('%m/%d/%Y %I:%M %p')
    return matches

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
        competition=competition
    )
    db.session.add(new_match)
    db.session.commit()

def update_mls_match(match_id, **kwargs):
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if match:
        for key, value in kwargs.items():
            setattr(match, key, value)
        db.session.commit()

def delete_mls_match(match_id):
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if match:
        db.session.delete(match)
        db.session.commit()

def get_upcoming_mls_matches(hours_ahead=24):
    now = datetime.utcnow()
    end_time = now + timedelta(hours=hours_ahead)
    return MLSMatch.query.filter(
        MLSMatch.date_time > now,
        MLSMatch.date_time <= end_time,
        MLSMatch.thread_created == False
    ).all()

def mark_mls_match_thread_created(match_id, thread_id):
    match = MLSMatch.query.filter_by(match_id=match_id).first()
    if match:
        match.thread_created = True
        match.discord_thread_id = thread_id
        db.session.commit()

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