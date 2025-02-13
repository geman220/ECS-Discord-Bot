# app/routes.py

"""
Routes Module

This module provides helper functions to determine the current season and year,
and to load/save match dates from/to a JSON file.
"""

from datetime import datetime
import json
import os

from app.models import Season

# Define the absolute path to the JSON file containing match dates.
JSON_FILE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'match_dates.json'))


def get_current_season_and_year():
    """
    Determine the current season and year based on the current date.

    The season is defined as "Spring" if the current month is before June;
    otherwise, it's "Fall". The function then verifies that the season exists
    in the database.

    Returns:
        tuple: A tuple containing the current season (str) and the current year (int).

    Raises:
        Exception: If the season is not found in the database.
    """
    now = datetime.now()
    year = now.year
    season_name = "Spring" if now.month < 6 else "Fall"
    current_season = f"{year} {season_name}"
    
    # Ensure the season exists in the database.
    season = Season.query.filter_by(name=current_season).first()
    if not season:
        raise Exception(f"Season '{current_season}' not found in the database.")
    
    return current_season, year


def load_match_dates():
    """
    Load match dates from the JSON file.

    Returns:
        list: A list of match dates from the 'matches' key in the JSON file.
    """
    with open(JSON_FILE_PATH, 'r') as file:
        data = json.load(file)
    return data.get('matches', [])


def save_match_dates(matches):
    """
    Save match dates to the JSON file.

    Args:
        matches (list): A list of match dates to be saved.
    """
    with open(JSON_FILE_PATH, 'w') as file:
        json.dump({"matches": matches}, file, indent=4)