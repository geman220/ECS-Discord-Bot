# app/tasks/tasks_substitute_availability.py

"""
Weekly Sub Availability Poll (Automated Trigger)
================================================

Celery beat task that posts the automated weekly "can you sub?" availability
poll to #pl-subs — the scheduled trigger for the closed-loop substitute system.

Modeled on the Thursday RSVP DM reminder beat task. It reuses the single
poll-building path in ``app.mobile_api.substitutes.post_availability_poll`` (the
same function the admin ad-hoc endpoint calls), so there is exactly one way a
poll gets built and posted.

Schedule: Friday 2:00 PM PST (America/Los_Angeles).

Admin-adjustable via AdminConfig (key/value settings store):
    sub_availability_poll_enabled   (boolean, default True)
    sub_availability_poll_only_needed (boolean, default False)  BRIDGE flag
    sub_availability_poll_weekday   (integer, optional gate; crontab convention
                                     0=Sun..6=Sat; default unset = no gate)
    sub_availability_poll_hour      (integer, optional gate; Pacific hour 0-23;
                                     default unset = no gate)

The weekday/hour keys are OPTIONAL gates, not a dynamic schedule: the beat fires
Friday 14:00 Pacific, and if either key is set to a value that doesn't match the
Pacific moment the beat actually fires, the run is skipped. This gives basic
day/time adjustability (and a second off-switch) without a dynamic beat.
"""

import logging

from app.decorators import celery_task
from app.utils.pacific_time import pacific_now

logger = logging.getLogger(__name__)


@celery_task(max_retries=2, default_retry_delay=300)
def send_weekly_sub_availability_poll(self, session):
    """
    Post the automated weekly sub availability poll to #pl-subs.

    Reads enable flag + options from AdminConfig, then calls the shared
    ``post_availability_poll`` with the task's OWN session (never db.session —
    this runs outside any request context, and the poll function persists the
    DiscordPoll on the session it's handed; passing db.session here would write
    to a session nothing in this task commits, silently losing the poll row).
    """
    from app.models.admin_config import AdminConfig
    from app.mobile_api.substitutes import post_availability_poll

    try:
        # --- Enable flag ---
        enabled = AdminConfig.get_setting('sub_availability_poll_enabled', True)
        if not enabled:
            logger.info(
                "Weekly sub availability poll is disabled "
                "(sub_availability_poll_enabled=false); skipping."
            )
            return {'success': True, 'skipped': True, 'reason': 'disabled'}

        # --- Optional weekday/hour gate (see module docstring) ---
        now_pt = pacific_now()
        # Python weekday() convention: Mon=0 .. Sun=6 — MUST match the Settings UI /
        # schema (_substitute_settings.html: Monday=0..Friday=4). Using isoweekday()%7
        # (Sun=0..Fri=5) here silently disabled the poll after any Settings save,
        # because the saved value 4 (Friday in the UI) is Thursday in that convention.
        current_weekday = now_pt.weekday()
        current_hour = now_pt.hour

        want_weekday = AdminConfig.get_setting('sub_availability_poll_weekday', None)
        if want_weekday is not None and int(want_weekday) != current_weekday:
            logger.info(
                "Weekly sub availability poll gated by weekday override "
                "(want=%s, current=%s Pacific); skipping.",
                want_weekday, current_weekday
            )
            return {'success': True, 'skipped': True, 'reason': 'weekday_mismatch'}

        want_hour = AdminConfig.get_setting('sub_availability_poll_hour', None)
        if want_hour is not None and int(want_hour) != current_hour:
            logger.info(
                "Weekly sub availability poll gated by hour override "
                "(want=%s, current=%s Pacific); skipping.",
                want_hour, current_hour
            )
            return {'success': True, 'skipped': True, 'reason': 'hour_mismatch'}

        # --- Bridge flag: ask ALL slots (default) vs only slots needing subs ---
        only_needed = AdminConfig.get_setting('sub_availability_poll_only_needed', False)

        # --- Build and post the poll on the task's own session ---
        # target_date=None -> upcoming Sunday; user_id=None -> system run.
        payload, _status = post_availability_poll(
            session,
            target_date=None,
            user_id=None,
            channel_key='pl_subs',
            only_slots_needing_subs=bool(only_needed),
        )

        success = bool(payload.get('success'))
        reason = payload.get('reason')

        if success:
            logger.info(
                "Weekly sub availability poll posted for %s (only_needed=%s): %s",
                payload.get('match_date'), bool(only_needed),
                payload.get('discord_message_url') or 'posted'
            )
        elif reason == 'duplicate':
            logger.info(
                "Weekly sub availability poll already live for %s; not re-posting (%s).",
                payload.get('match_date'), payload.get('discord_message_url')
            )
        elif reason in ('no_matches', 'no_slots_needed'):
            logger.info(
                "Weekly sub availability poll: nothing to ask for %s (reason=%s, only_needed=%s).",
                payload.get('match_date'), reason, bool(only_needed)
            )
        else:
            # Non-success without a benign reason => a real posting failure
            # (bot unreachable, channel/roles misconfigured, etc.). Surface it
            # via retry so the closed loop doesn't silently miss a week.
            logger.error(
                "Weekly sub availability poll failed: %s",
                payload.get('msg') or reason or payload
            )
            raise RuntimeError(payload.get('msg') or f"poll failed: {reason or payload}")

        return {
            'success': success,
            'reason': reason,
            'only_needed': bool(only_needed),
            'match_date': payload.get('match_date'),
            'discord_message_url': payload.get('discord_message_url'),
        }

    except Exception as e:
        logger.error(f"Error in send_weekly_sub_availability_poll: {e}", exc_info=True)
        raise self.retry(exc=e)


@celery_task()
def send_weekly_sub_availability_poll_manual(self, session):
    """Manual trigger for the weekly sub availability poll (admin testing)."""
    result = send_weekly_sub_availability_poll.delay()
    return {'task_id': result.id, 'status': 'dispatched'}
