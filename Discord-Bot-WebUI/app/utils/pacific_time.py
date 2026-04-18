"""
Pacific timezone helpers.

The whole league is local to Seattle (Pacific time). All match dates/times in
the database are stored as naive values that represent Pacific calendar
date/time. But Celery workers run in UTC containers, so Python's `date.today()`
and `datetime.now()` return UTC — which on the wrong side of midnight UTC
gives a different calendar date than Pacific.

Use these helpers anywhere you compare to a `Match.date`, decide "today" /
"tomorrow", or build a match-local `datetime` for duration math.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

PACIFIC_TZ = ZoneInfo('America/Los_Angeles')


def pacific_now() -> datetime:
    """Timezone-aware datetime in Pacific."""
    return datetime.now(PACIFIC_TZ)


def pacific_today() -> date:
    """Calendar date in Pacific — use in place of `date.today()`."""
    return pacific_now().date()


def pacific_datetime(d: date, t: time) -> datetime:
    """Combine a Pacific-intent date+time into an aware Pacific datetime."""
    return datetime.combine(d, t, tzinfo=PACIFIC_TZ)
