# app/services/rsvp_snooze_service.py

"""
RSVP Reminder Snooze Service

Manages player snooze/break preferences for RSVP DM reminders.
Players can pause reminders for a set number of weeks or until end of season.
"""

import logging
from datetime import date, timedelta

from app.core import db
from app.models.communication import RsvpReminderSnooze
from app.models.core import Season

logger = logging.getLogger(__name__)


def get_snooze(player_id):
    """Get the active snooze for a player, or None if not snoozed."""
    snooze = RsvpReminderSnooze.query.filter_by(player_id=player_id).first()
    if snooze and snooze.snooze_until >= date.today():
        return snooze
    return None


def set_snooze(player_id, duration_weeks, reason='web_ui', created_by=None):
    """
    Set or update a player's snooze.

    Args:
        player_id: The player ID
        duration_weeks: Number of weeks to snooze, or None for rest of season
        reason: Source of snooze ('dm_button', 'web_ui', 'admin')
        created_by: User ID of admin who set it, or None for self-service

    Returns:
        The RsvpReminderSnooze instance
    """
    if duration_weeks is not None:
        snooze_until = date.today() + timedelta(weeks=duration_weeks)
    else:
        # Rest of season - find current season end date
        snooze_until = _get_season_end_date()

    existing = RsvpReminderSnooze.query.filter_by(player_id=player_id).first()
    if existing:
        existing.snooze_until = snooze_until
        existing.duration_weeks = duration_weeks
        existing.reason = reason
        existing.created_by = created_by
        snooze = existing
    else:
        snooze = RsvpReminderSnooze(
            player_id=player_id,
            snooze_until=snooze_until,
            duration_weeks=duration_weeks,
            reason=reason,
            created_by=created_by
        )
        db.session.add(snooze)

    db.session.flush()
    logger.info(f"RSVP snooze set for player {player_id} until {snooze_until} (reason={reason})")
    return snooze


def clear_snooze(player_id):
    """Remove a player's snooze."""
    snooze = RsvpReminderSnooze.query.filter_by(player_id=player_id).first()
    if snooze:
        db.session.delete(snooze)
        db.session.flush()
        logger.info(f"RSVP snooze cleared for player {player_id}")
        return True
    return False


def get_all_snoozed_player_ids():
    """Get set of player IDs with active snoozes."""
    today = date.today()
    rows = db.session.query(RsvpReminderSnooze.player_id).filter(
        RsvpReminderSnooze.snooze_until >= today
    ).all()
    return {r.player_id for r in rows}


def get_all_snoozed_players():
    """Get all active snoozes with player info (for admin view)."""
    today = date.today()
    return RsvpReminderSnooze.query.filter(
        RsvpReminderSnooze.snooze_until >= today
    ).all()


def cleanup_expired():
    """Delete expired snooze rows."""
    today = date.today()
    count = RsvpReminderSnooze.query.filter(
        RsvpReminderSnooze.snooze_until < today
    ).delete()
    if count:
        db.session.flush()
        logger.info(f"Cleaned up {count} expired RSVP snoozes")
    return count


def _get_season_end_date():
    """Get the end date of the current season, or a fallback 12 weeks out."""
    current_season = Season.query.filter_by(is_current=True).first()
    if current_season and current_season.end_date:
        return current_season.end_date
    # Fallback: 12 weeks from now
    return date.today() + timedelta(weeks=12)
