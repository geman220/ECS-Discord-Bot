# app/services/rsvp_snooze_service.py

"""
RSVP Reminder Snooze Service

Manages player snooze/break preferences for RSVP DM reminders.
Players can pause reminders for a set number of weeks or until end of season.

SESSION CONTRACT — read this before editing.

Every write here goes through the session the CALLER commits. This module used
to read via ``RsvpReminderSnooze.query`` (which binds to Flask-SQLAlchemy's
``db.session``) and write via ``db.session.add/delete``, while its callers — the
routes in ``app/routes/rsvp_reminder.py`` and the Celery reminder task — commit
``g.db_session`` / their own ``SessionLocal``. Those are DIFFERENT sessions,
nothing commits ``db.session``, and teardown calls ``db.session.remove()`` (a
rollback).

The result: a player tapped "snooze" on the Thursday reminder DM, the API replied
with a real ``snooze_until`` read straight off the in-memory object, and **nothing
was ever written** — so the reminders kept coming, forever, and un-snoozing was
equally a no-op.
"""

import logging
from datetime import timedelta

from flask import g, has_request_context

from app.core import db
from app.models.communication import RsvpReminderSnooze
from app.models.core import Season
from app.utils.pacific_time import pacific_today

logger = logging.getLogger(__name__)


def _resolve_session(session=None):
    """The session to read and write through — the one the caller commits."""
    if session is not None:
        return session
    if has_request_context() and getattr(g, 'db_session', None) is not None:
        return g.db_session
    return db.session


def get_snooze(player_id, session=None):
    """Get the active snooze for a player, or None if not snoozed."""
    db_session = _resolve_session(session)
    snooze = db_session.query(RsvpReminderSnooze).filter_by(player_id=player_id).first()
    if snooze and snooze.snooze_until >= pacific_today():
        return snooze
    return None


def set_snooze(player_id, duration_weeks, reason='web_ui', created_by=None, session=None):
    """
    Set or update a player's snooze.

    Args:
        player_id: The player ID
        duration_weeks: Number of weeks to snooze, or None for rest of season
        reason: Source of snooze ('dm_button', 'web_ui', 'admin')
        created_by: User ID of admin who set it, or None for self-service
        session: The session the caller will commit (defaults to the per-request one)

    Returns:
        The RsvpReminderSnooze instance
    """
    db_session = _resolve_session(session)

    if duration_weeks is not None:
        snooze_until = pacific_today() + timedelta(weeks=duration_weeks)
    else:
        snooze_until = _get_season_end_date(db_session)

    existing = db_session.query(RsvpReminderSnooze).filter_by(player_id=player_id).first()
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
        db_session.add(snooze)

    db_session.flush()
    logger.info(f"RSVP snooze set for player {player_id} until {snooze_until} (reason={reason})")
    return snooze


def clear_snooze(player_id, session=None):
    """Remove a player's snooze."""
    db_session = _resolve_session(session)
    snooze = db_session.query(RsvpReminderSnooze).filter_by(player_id=player_id).first()
    if snooze:
        db_session.delete(snooze)
        db_session.flush()
        logger.info(f"RSVP snooze cleared for player {player_id}")
        return True
    return False


def get_all_snoozed_player_ids(session=None):
    """Get set of player IDs with active snoozes."""
    db_session = _resolve_session(session)
    today = pacific_today()
    rows = db_session.query(RsvpReminderSnooze.player_id).filter(
        RsvpReminderSnooze.snooze_until >= today
    ).all()
    return {r.player_id for r in rows}


def get_all_snoozed_players(session=None):
    """Get all active snoozes with player info (for admin view)."""
    db_session = _resolve_session(session)
    today = pacific_today()
    return db_session.query(RsvpReminderSnooze).filter(
        RsvpReminderSnooze.snooze_until >= today
    ).all()


def cleanup_expired(session=None):
    """Delete expired snooze rows."""
    db_session = _resolve_session(session)
    today = pacific_today()
    count = db_session.query(RsvpReminderSnooze).filter(
        RsvpReminderSnooze.snooze_until < today
    ).delete()
    if count:
        db_session.flush()
        logger.info(f"Cleaned up {count} expired RSVP snoozes")
    return count


def _get_season_end_date(db_session):
    """End date for a "rest of season" snooze.

    Pub League and ECS FC each have their own is_current season row, so an
    unqualified is_current lookup returns whichever one the DB hands back first
    — and a player who reminders cover across both leagues could get un-snoozed
    early because we happened to grab the season that ends sooner. Take the
    LATEST end date among the current seasons so "rest of season" always means
    the rest of the season for them.
    """
    end_dates = [
        s.end_date for s in db_session.query(Season).filter_by(is_current=True).all()
        if s.end_date
    ]
    if end_dates:
        return max(end_dates)
    # Fallback: 12 weeks from now
    return pacific_today() + timedelta(weeks=12)
