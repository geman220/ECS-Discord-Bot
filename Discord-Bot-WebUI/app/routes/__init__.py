# Routes package

from datetime import datetime
from app.models import Season

def get_current_season_and_year():
    """
    Determine the current season and year based on the current date.

    The season is determined as follows:
    - Spring: January through July (includes end of season + break)
    - Fall: August through December
    
    If the expected season doesn't exist, falls back to the most recent season.

    Returns:
        tuple: A tuple containing the current season (str) and the current year (int).

    Raises:
        Exception: If no seasons are found in the database.
    """
    now = datetime.now()
    year = now.year
    
    # More realistic season determination
    # Spring runs Jan-July (includes June end + July break)
    # Fall runs Aug-Dec (starts preparing in August, games in September)
    if now.month <= 7:
        season_name = "Spring"
    else:
        season_name = "Fall"
    
    current_season = f"{year} {season_name}"
    
    # First try to find the exact season
    season = Season.query.filter_by(name=current_season).first()
    if season:
        return current_season, year
    
    # If not found, try to find the most recent season marked as current
    season = Season.query.filter_by(is_current=True).first()
    if season:
        # Parse year from season name (assuming format "YYYY Season")
        parts = season.name.split()
        if parts and parts[0].isdigit():
            return season.name, int(parts[0])
        return season.name, year
    
    # Otherwise, get the most recent season by name
    all_seasons = Season.query.all()
    if not all_seasons:
        raise Exception("No seasons found in the database.")
    
    # Sort seasons by year and season name to find most recent
    def parse_season_key(s):
        parts = s.name.split()
        if len(parts) >= 2 and parts[0].isdigit():
            year_val = int(parts[0])
            # Fall comes after Spring in the same year
            season_val = 1 if "Spring" in s.name else 2
            return (year_val, season_val)
        return (0, 0)
    
    sorted_seasons = sorted(all_seasons, key=parse_season_key, reverse=True)
    most_recent = sorted_seasons[0]
    
    # Log what we're falling back to
    import logging
    logging.info(f"Season '{current_season}' not found, falling back to '{most_recent.name}'")
    
    # Parse year from the most recent season
    parts = most_recent.name.split()
    if parts and parts[0].isdigit():
        return most_recent.name, int(parts[0])
    
    return most_recent.name, year

__all__ = ['get_current_season_and_year']