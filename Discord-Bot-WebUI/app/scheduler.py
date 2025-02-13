# app/scheduler.py

"""
Scheduler Module

This module handles scheduling tasks related to upcoming matches.
It fetches upcoming matches from the database and schedules Discord polls
to be sent 5 days before each match.
"""

import sys
import os
from datetime import datetime, timedelta

# Add the parent directory of the 'app' package to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

# Local application imports
from app.models import Match
from tasks import post_discord_poll


def get_upcoming_matches():
    """
    Fetch matches that are scheduled in the future.

    Returns:
        list: A list of Match objects with a date on or after today.
    """
    # Filter matches by date (today or later)
    return Match.query.filter(Match.date >= datetime.now().date()).all()


def schedule_polls():
    """
    Schedule Discord polls for upcoming matches.

    For each upcoming match, schedules a poll to be triggered 5 days before the match.
    If the current time is already within the 5-day window, the poll is triggered immediately.
    """
    matches = get_upcoming_matches()  # Fetch upcoming matches from the database

    for match in matches:
        # Calculate the time 5 days before the match datetime
        poll_time = datetime.combine(match.date, match.time) - timedelta(days=5)

        if datetime.now() >= poll_time:
            # If we're within the 5-day window, trigger the poll immediately
            post_discord_poll.apply_async(args=[match.id], eta=datetime.now())
        else:
            # Otherwise, schedule the poll for 5 days before the match
            post_discord_poll.apply_async(args=[match.id], eta=poll_time)