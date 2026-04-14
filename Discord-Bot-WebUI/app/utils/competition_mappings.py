"""
Shared competition / league mappings.

Single source of truth mapping the friendly names used in the admin UI
(and returned by ESPN for legacy matches) to ESPN league codes used when
building API URLs like `https://.../sports/soccer/{league_code}/scoreboard`.

All live-reporting, match-thread, and ESPN-polling code should import from
here rather than maintaining its own copy.
"""

from typing import Dict


# Display name -> ESPN league code.
#
# Historically `match.competition` was stored as either the display name
# (e.g. "Concacaf Champions Cup") or the ESPN code itself (e.g.
# "concacaf.champions"), depending on where/when the row was created.
# `resolve_league_code()` handles both cases — use it rather than reaching
# into this dict directly.
COMPETITION_MAPPINGS: Dict[str, str] = {
    "MLS": "usa.1",
    "US Open Cup": "usa.open",
    "FIFA Club World Cup": "fifa.cwc",
    "Concacaf": "concacaf.champions",
    "Concacaf Champions League": "concacaf.champions",
    "Concacaf Champions Cup": "concacaf.champions",
    "CONCACAF Champions League": "concacaf.champions",
    "CONCACAF Champions Cup": "concacaf.champions",
    "Leagues Cup": "usa.leagues_cup",
}

# ESPN league code -> display name (for UI rendering of stored codes).
INVERSE_COMPETITION_MAPPINGS: Dict[str, str] = {
    v: k for k, v in COMPETITION_MAPPINGS.items()
}


def resolve_league_code(competition: str, default: str = "usa.1") -> str:
    """
    Resolve any competition string to an ESPN league code.

    Accepts either a display name ("MLS", "Concacaf Champions Cup") or a
    bare ESPN code ("usa.1", "concacaf.champions") and returns the code
    suitable for ESPN API URL construction.

    Args:
        competition: The competition value from a Match/LiveReportingSession
            row, a form field, or a caller-provided string. Empty / None /
            whitespace-only values fall back to `default`.
        default: Fallback league code when `competition` is empty.

    Returns:
        ESPN league code string (e.g. "usa.1", "concacaf.champions").
    """
    if not competition:
        return default

    value = competition.strip()
    if not value:
        return default

    # Direct match on display name
    if value in COMPETITION_MAPPINGS:
        return COMPETITION_MAPPINGS[value]

    # Already an ESPN code (contains a dot like `usa.1`, `concacaf.champions`)
    if "." in value:
        return value

    # Unknown value — fall back to default rather than passing a bad URL segment
    return default
