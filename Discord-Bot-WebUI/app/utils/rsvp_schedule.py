# app/utils/rsvp_schedule.py

"""
When the RSVP request gets posted to a team channel.

ONE source of truth. This used to be three separate copies of "6 days before"
that had already drifted apart:

    tasks_rsvp.py:1110          match_date - timedelta(days=6)  @ 16:00 UTC
    ecs_fc_schedule.py:529      match_date - timedelta(days=6)  @ 09:00 naive
    tasks_ecs_fc_scheduled.py   match_date - timedelta(days=6)  (re-derived again)

Two different hours for the same intent, and the 16:00 UTC one was commented
"8:00 AM PST" — correct only in winter. Pacific is UTC-7 from March to November,
so for most of a season the Pub League RSVP went out at 9am local, not 8am.

Applies to Pub League and ECS FC alike. Nothing here touches the MLS match
scheduler, which is a separate subsystem with its own mls_* settings.
"""

import logging

logger = logging.getLogger(__name__)

# Used when AdminConfig has no row yet (fresh install, or before the seed runs).
# Matches the behaviour the hardcoded constants had, so nothing moves until an
# admin actually changes it.
DEFAULT_POST_DAYS_BEFORE = 6
DEFAULT_POST_HOUR = 8  # 8am PACIFIC, not UTC


def rsvp_post_schedule():
    """(days_before, pacific_hour) for posting an RSVP request.

    Clamped, because these come from an admin form and a nonsense value would
    either schedule in the past or throw deep inside a Celery beat task where
    nobody sees it.
    """
    try:
        from app.models import AdminConfig
        days = int(AdminConfig.get_setting('rsvp_post_days_before',
                                           DEFAULT_POST_DAYS_BEFORE))
        hour = int(AdminConfig.get_setting('rsvp_post_hour', DEFAULT_POST_HOUR))
    except Exception:
        logger.exception("Could not read RSVP post schedule; using defaults")
        return DEFAULT_POST_DAYS_BEFORE, DEFAULT_POST_HOUR

    # 0 days = post on match day itself; 14 is a fortnight's notice, past which
    # the roster is usually not settled anyway.
    days = max(0, min(14, days))
    hour = max(0, min(23, hour))
    return days, hour
