# database.py

import sqlite3
import json
from contextlib import contextmanager

PREDICTIONS_DB_PATH = "predictions.db"
ORDERS_DB_PATH = "woo_orders.db"
PUB_LEAGUE_DB_PATH = "pub_league.db"


def get_latest_order_id():
    with get_db_connection(ORDERS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT order_id FROM woo_orders ORDER BY order_id DESC LIMIT 1")
        result = c.fetchone()
        return result[0] if result else None


def count_orders_for_multiple_subgroups(subgroups):
    counts = {}
    with get_db_connection(ORDERS_DB_PATH) as conn:
        c = conn.cursor()
        for subgroup in subgroups:
            query = """
                SELECT COUNT(DISTINCT order_id) FROM woo_orders
                WHERE order_data LIKE ?
            """
            wildcard_subgroup_name = (
                f'%"name": "Subgroup designation", "value": "{subgroup}"%'
            )
            c.execute(query, (wildcard_subgroup_name,))
            result = c.fetchone()
            counts[subgroup] = result[0] if result else 0
    return counts


def get_members_for_subgroup(subgroup):
    members = []
    with get_db_connection(ORDERS_DB_PATH) as conn:
        c = conn.cursor()
        query = """
            SELECT DISTINCT order_data FROM woo_orders
            WHERE order_data LIKE ?
        """
        wildcard_subgroup_name = (
            f'%"name": "Subgroup designation", "value": "{subgroup}"%'
        )
        c.execute(query, (wildcard_subgroup_name,))

        for row in c.fetchall():
            order_data = json.loads(row[0])
            billing_info = order_data.get("billing", {})
            member = {
                "first_name": billing_info.get("first_name", ""),
                "last_name": billing_info.get("last_name", ""),
                "email": billing_info.get("email", ""),
            }
            if member not in members:
                members.append(member)

    return members


@contextmanager
def get_db_connection(db_path):
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()
        

def initialize_predictions_db():
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS predictions
                     (match_id TEXT, user_id TEXT, prediction TEXT, timestamp DATETIME)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS match_threads
                     (thread_id TEXT, match_id TEXT)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS match_schedule (
                match_id TEXT, 
                opponent TEXT, 
                date_time DATETIME, 
                venue TEXT,
                is_home_game BOOLEAN,
                match_summary_link TEXT,
                match_stats_link TEXT,
                match_commentary_link TEXT,
                thread_created INTEGER DEFAULT 0,
                live_updates_active INTEGER DEFAULT 0
            )"""
        )
        c.execute("PRAGMA table_info(match_schedule)")
        columns = [row[1] for row in c.fetchall()]
        if 'competition' not in columns:
            c.execute("ALTER TABLE match_schedule ADD COLUMN competition TEXT DEFAULT 'usa.1'")
        
        conn.commit()


def insert_match_schedule(match_id, opponent, date_time, is_home_game, summary_link, stats_link, commentary_link, venue, competition):
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO match_schedule (match_id, opponent, date_time, is_home_game, match_summary_link, match_stats_link, match_commentary_link, venue, competition) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (match_id, opponent, date_time, is_home_game, summary_link, stats_link, commentary_link, venue, competition)
        )
        conn.commit()


def insert_match_thread(thread_id, match_id):
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO match_threads VALUES (?, ?)", (thread_id, match_id))
        conn.commit()


def insert_prediction(match_id, user_id, prediction):
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM predictions WHERE match_id=? AND user_id=?",
            (match_id, user_id),
        )
        if c.fetchone():
            return False
        c.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (match_id, user_id, prediction),
        )
        conn.commit()
    return True


def get_predictions(match_id):
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT prediction, COUNT(*) FROM predictions WHERE match_id=? GROUP BY prediction",
            (match_id,),
        )
        return c.fetchall()


def load_match_threads():
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM match_threads")
        return {thread_id: match_id for thread_id, match_id in c.fetchall()}


def reset_woo_orders_db():
    with get_db_connection(ORDERS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """DELETE FROM order_extract WHERE 1=1"""
        )
        c.execute(
            """DELETE FROM woo_orders WHERE 1=1"""
        )
        c.execute("""
            UPDATE latest_order_info 
            SET latest_order_id = '0'
            WHERE id = 1
        """)
        conn.commit()


def initialize_woo_orders_db():
    with get_db_connection(ORDERS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS woo_orders
                     (order_id TEXT PRIMARY KEY, order_data TEXT)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS order_extract
                     (order_id TEXT PRIMARY KEY,
                      product_name TEXT,
                      first_name TEXT,
                      last_name TEXT,
                      email_address TEXT,
                      order_date TEXT,
                      item_qty INTEGER,
                      item_price TEXT,
                      order_status TEXT,
                      order_note TEXT,
                      product_variation TEXT,
                      billing_address TEXT)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS latest_order_info
                     (id INTEGER PRIMARY KEY,
                      latest_order_id TEXT)"""
        )
        c.execute("""
            INSERT INTO latest_order_info (id, latest_order_id)
            VALUES (1, '0')
            ON CONFLICT(id) DO NOTHING
        """)
        conn.commit()


def update_latest_order_id(order_id):
    try:
        with get_db_connection(ORDERS_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO latest_order_info (id, latest_order_id)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET latest_order_id = excluded.latest_order_id
                """, (order_id,))
            conn.commit()
    except Exception as e:
        print(f"Error updating latest order ID: {e}")
        

def get_latest_order_id():
    with get_db_connection(ORDERS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT latest_order_id FROM latest_order_info WHERE id = 1")
        result = c.fetchone()
        return result[0] if result else None
    

def insert_order_extract(order_id, product_name, first_name, last_name, email_address, order_date, item_qty, item_price, order_status, order_note, product_variation, billing_address):
    with get_db_connection(ORDERS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO order_extract (order_id, product_name, first_name, last_name, email_address, order_date, item_qty, item_price, order_status, order_note, product_variation, billing_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, product_name, first_name, last_name, email_address, order_date, item_qty, item_price, order_status, order_note, product_variation, billing_address),
        )
        conn.commit()


def get_order_extract(product_title):
    with get_db_connection(ORDERS_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM order_extract WHERE product_name = ? ORDER BY email_address, order_id", (product_title,))
        rows = c.fetchall()
        return [dict(row) for row in rows]


def prep_order_extract():
    with get_db_connection(ORDERS_DB_PATH) as conn:
        conn.execute(
            "DELETE FROM order_extract"
        )
        conn.commit()


def update_woo_orders(order_id, order_data):
    with get_db_connection(ORDERS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO woo_orders (order_id, order_data) VALUES (?, ?)",
            (order_id, order_data),
        )
        conn.commit()


def load_existing_dates():
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT date_time, competition FROM match_schedule")
        existing_dates = [(row[0], row[1]) for row in c.fetchall()]
    return existing_dates


def initialize_pub_league_db():
    with get_db_connection(PUB_LEAGUE_DB_PATH) as conn:
        c = conn.cursor()
        
        c.execute(
            """CREATE TABLE IF NOT EXISTS leagues (
                league_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS teams (
                team_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                league_id INTEGER,
                FOREIGN KEY (league_id) REFERENCES leagues (league_id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS schedules (
                schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
                week INTEGER,
                date TEXT,
                time TEXT,
                opponent TEXT,
                team_id INTEGER,
                FOREIGN KEY (team_id) REFERENCES teams (team_id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS coaches (
                coach_id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_tag TEXT,
                team_id INTEGER,
                FOREIGN KEY (team_id) REFERENCES teams (team_id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS members (
                member_id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_tag TEXT,
                team_id INTEGER,
                FOREIGN KEY (team_id) REFERENCES teams (team_id)
            )"""
        )
        
        conn.commit()


def load_league_data(json_file):
    with open(json_file, 'r') as f:
        data = json.load(f)

    with get_db_connection(PUB_LEAGUE_DB_PATH) as conn:
        c = conn.cursor()

        for league_name, league_info in data['leagues'].items():
            # Insert league
            c.execute("INSERT OR IGNORE INTO leagues (name) VALUES (?)", (league_name,))
            c.execute("SELECT league_id FROM leagues WHERE name=?", (league_name,))
            league_id = c.fetchone()[0]

            for team_info in league_info['teams']:
                team_name = team_info['name']
                # Insert team
                c.execute("INSERT OR IGNORE INTO teams (name, league_id) VALUES (?, ?)", (team_name, league_id))
                c.execute("SELECT team_id FROM teams WHERE name=?", (team_name,))
                team_id = c.fetchone()[0]

                for match_info in team_info['schedule']:
                    week = match_info['week']
                    for match in match_info['matches']:
                        date = match['date']
                        time = match['time']
                        opponent = match['opponent']
                        # Insert schedule
                        c.execute("INSERT INTO schedules (week, date, time, opponent, team_id) VALUES (?, ?, ?, ?, ?)", (week, date, time, opponent, team_id))

        conn.commit()


def insert_coach(discord_tag, team_id):
    with get_db_connection(PUB_LEAGUE_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO coaches (discord_tag, team_id) VALUES (?, ?)", (discord_tag, team_id))
        conn.commit()


def insert_member(discord_tag, team_id):
    with get_db_connection(PUB_LEAGUE_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO members (discord_tag, team_id) VALUES (?, ?)", (discord_tag, team_id))
        conn.commit()