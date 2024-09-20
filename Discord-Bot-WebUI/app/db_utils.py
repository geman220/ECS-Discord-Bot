import os
import sqlite3
from datetime import datetime

# Define the correct path to the database file within the Docker container
PREDICTIONS_DB_PATH = os.path.join('/app', 'predictions.db')

def format_match_data(matches):
    for match in matches:
        if isinstance(match['date'], str):
            # Convert the date_time string to a datetime object
            match['date'] = datetime.fromisoformat(match['date'])
    return matches

def format_match_display_data(matches):
    for match in matches:
        if isinstance(match['date'], str):
            # Convert the string to a datetime object
            dt_object = datetime.fromisoformat(match['date'])
            # Format the date to MM/DD/YYYY HH:MM AM/PM
            match['formatted_date'] = dt_object.strftime('%m/%d/%Y %I:%M %p')
    return matches

def get_db_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Allows accessing columns by name
    return conn

def insert_match_schedule(match_id, opponent, date_time, is_home_game, summary_link, stats_link, commentary_link, venue, competition):
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO match_schedule 
               (match_id, opponent, date_time, is_home_game, match_summary_link, match_stats_link, match_commentary_link, venue, competition) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (match_id, opponent, date_time, is_home_game, summary_link, stats_link, commentary_link, venue, competition)
        )
        conn.commit()

def update_match_in_db(match_id, opponent, date_time, is_home_game, summary_link, stats_link, commentary_link, venue, competition):
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """UPDATE match_schedule 
               SET opponent = ?, date_time = ?, is_home_game = ?, match_summary_link = ?, match_stats_link = ?, match_commentary_link = ?, venue = ?, competition = ?
               WHERE match_id = ?""",
            (opponent, date_time, is_home_game, summary_link, stats_link, commentary_link, venue, competition, match_id)
        )
        conn.commit()

def delete_match_from_db(match_id):
    try:
        with get_db_connection(PREDICTIONS_DB_PATH) as conn:
            c = conn.cursor()
            # Delete using match_id
            c.execute(
                "DELETE FROM match_schedule WHERE match_id = ?",
                (match_id,)
            )
            conn.commit()
    except Exception as e:
        print(f"Error deleting match from DB: {e}")

def load_existing_dates():
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT date_time, competition FROM match_schedule")
        existing_dates = [(row[0], row[1]) for row in c.fetchall()]
    return existing_dates

def load_match_dates_from_db():
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT match_id, opponent, date_time, venue, is_home_game, match_summary_link, match_stats_link, match_commentary_link, competition FROM match_schedule")
        matches = [
            {
                'match_id': row['match_id'],
                'opponent': row['opponent'],
                'date': row['date_time'],
                'venue': row['venue'],
                'is_home_game': row['is_home_game'],
                'summary_link': row['match_summary_link'],
                'stats_link': row['match_stats_link'],
                'commentary_link': row['match_commentary_link'],
                'competition': row['competition']
            }
            for row in c.fetchall()
        ]
    return matches