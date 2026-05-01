"""
Canonical mapping for special-week display names.

FUN / TST / BYE / BONUS weeks are stored as placeholder match rows where
home_team_id == away_team_id, so a naive "{home_team.name} vs {away_team.name}"
render shows the placeholder team name twice. Mobile clients (Flutter) and
SMS/Discord paths instead show the human-readable label below.

Keep the wording in sync with: auto_schedule_generator placeholder labels
(`"BYE Week!"`, `"Fun Week!"`, `"The Soccer Tournament!"`, `"Bonus Week!"`).
"""

from typing import Optional

WEEK_TYPE_DISPLAY_NAMES = {
    'FUN': 'Fun Week!',
    'TST': 'The Soccer Tournament!',
    'BYE': 'BYE Week!',
    'BONUS': 'Bonus Week!',
}

# Fallback for matches that pre-date the week_type column and only have a
# placeholder team named "FUN WEEK" / "BYE" / "TST" / "BONUS".
TEAM_NAME_HINTS = {
    'FUN': 'Fun Week!',
    'TST': 'The Soccer Tournament!',
    'BYE': 'BYE Week!',
    'BONUS': 'Bonus Week!',
}


def get_special_week_display_name(match) -> Optional[str]:
    """
    Return the display string for a special-week match, or None for a regular match.

    A match is "special" when home_team_id == away_team_id (the auto-scheduler
    creates a single self-vs-self row per team for FUN/TST/BYE/BONUS weeks).
    Regular team-vs-team matches return None — callers should render
    "{home_team.name} vs {away_team.name}" themselves.
    """
    if not match or match.home_team_id != match.away_team_id:
        return None

    week_type = (getattr(match, 'week_type', None) or '').upper()
    if week_type in WEEK_TYPE_DISPLAY_NAMES:
        return WEEK_TYPE_DISPLAY_NAMES[week_type]

    home_team_name = (getattr(getattr(match, 'home_team', None), 'name', '') or '').upper()
    for hint, label in TEAM_NAME_HINTS.items():
        if hint in home_team_name:
            return label

    return 'Special Week!'
