import sys
import os

# Add the parent directory of the 'app' package to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.models import Match, Team
from app import db
from tasks import post_discord_poll  # Import the Celery task

from datetime import datetime, timedelta

def get_upcoming_matches():
    # Fetch matches that are scheduled in the future
    return Match.query.filter(Match.date >= datetime.now().date()).all()

def schedule_polls():
    matches = get_upcoming_matches()  # Fetch matches from the database
    for match in matches:
        # Schedule the poll to be created 5 days before the match date
        poll_time = datetime.combine(match.date, match.time) - timedelta(days=5)
        
        if datetime.now() >= poll_time:
            # Directly trigger the poll for matches within the next 5 days
            post_discord_poll.apply_async(args=[match.id], eta=datetime.now())
        else:
            # Schedule the poll to be sent 5 days before the match date
            post_discord_poll.apply_async(args=[match.id], eta=poll_time)
