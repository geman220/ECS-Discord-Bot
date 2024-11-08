from datetime import datetime
import json
import os
import requests
from app import db
from flask import current_app
from app.models import Season

# Define the path to your JSON file
json_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'match_dates.json'))

def get_current_season_and_year():
    now = datetime.now()
    year = now.year
    season_name = "Spring" if now.month < 6 else "Fall"
    current_season = f"{year} {season_name}"
    
    # Ensure the season exists in the database
    season = Season.query.filter_by(name=current_season).first()
    if not season:
        raise Exception(f"Season '{current_season}' not found in the database.")
    
    return current_season, year

def load_match_dates():
    with open(json_file_path, 'r') as file:
        data = json.load(file)
    return data.get('matches', [])

def save_match_dates(matches):
    with open(json_file_path, 'w') as file:
        json.dump({"matches": matches}, file, indent=4)
