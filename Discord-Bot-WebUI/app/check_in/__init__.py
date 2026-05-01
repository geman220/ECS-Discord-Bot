# app/check_in/__init__.py

"""Match check-in business logic."""

from .constants import MATCH_CHECKIN_WINDOW_HOURS, NEXT_MATCH_WINDOW_DAYS
from .service import (
    perform_check_in,
    get_match,
    get_match_kickoff,
    is_within_checkin_window,
    get_match_roster_yes,
    is_coach_of_match,
    resolve_member_token,
    build_match_label,
)

__all__ = [
    'MATCH_CHECKIN_WINDOW_HOURS',
    'NEXT_MATCH_WINDOW_DAYS',
    'perform_check_in',
    'get_match',
    'get_match_kickoff',
    'is_within_checkin_window',
    'get_match_roster_yes',
    'is_coach_of_match',
    'resolve_member_token',
    'build_match_label',
]
