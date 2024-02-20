# database.py

import sqlite3
import json
from contextlib import contextmanager

PREDICTIONS_DB_PATH = "predictions.db"
ORDERS_DB_PATH = "woo_orders.db"


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


def initialize_db():
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
        conn.commit()


def insert_order_extract(order_id, product_name, first_name, last_name, email_address, order_date, item_qty, item_price, order_status, order_note, product_variation, billing_address):
    with get_db_connection(ORDERS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO order_extract (order_id, product_name, first_name, last_name, email_address, order_date, item_qty, item_price, order_status, order_note, product_variation, billing_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, product_name, first_name, last_name, email_address, order_date, item_qty, item_price, order_status, order_note, product_variation, billing_address),
        )


def get_order_extract():
    with get_db_connection(ORDERS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM order_extract ORDER BY email_address, order_id")
        return c.fetchall()


def prep_order_extract():
    with get_db_connection(ORDERS_DB_PATH) as conn:
        conn.execute(
            "TRUNCATE TABLE order_extract"
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