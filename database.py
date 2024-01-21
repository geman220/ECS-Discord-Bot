# database.py

import sqlite3
from contextlib import contextmanager

DATABASE_PATH = 'predictions.db'

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        yield conn
    finally:
        conn.close()

def initialize_db():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS predictions
                     (match_id TEXT, user_id TEXT, prediction TEXT, timestamp DATETIME)''')
        c.execute('''CREATE TABLE IF NOT EXISTS match_threads
                     (thread_id TEXT, match_id TEXT)''')
        conn.commit()

def insert_match_thread(thread_id, match_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO match_threads VALUES (?, ?)", (thread_id, match_id))
        conn.commit()

def insert_prediction(match_id, user_id, prediction):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM predictions WHERE match_id=? AND user_id=?", (match_id, user_id))
        if c.fetchone():
            return False
        c.execute("INSERT INTO predictions VALUES (?, ?, ?, CURRENT_TIMESTAMP)", (match_id, user_id, prediction))
        conn.commit()
    return True

def get_predictions(match_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT prediction, COUNT(*) FROM predictions WHERE match_id=? GROUP BY prediction", (match_id,))
        return c.fetchall()

def load_match_threads():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM match_threads")
        return {thread_id: match_id for thread_id, match_id in c.fetchall()}
