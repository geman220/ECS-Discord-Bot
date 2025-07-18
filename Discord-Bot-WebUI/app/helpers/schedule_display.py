"""
Schedule Display Helpers

This module provides helper functions for displaying schedule information
throughout the system, including special handling for playoffs, practice sessions,
and special weeks (Fun, TST, Bonus).
"""

from datetime import date
from typing import Dict, List, Optional, Tuple
from app.models import Match, Schedule, ScheduleTemplate, Team


def get_match_display_info(match: Match) -> Dict:
    """
    Get display information for a match, handling special weeks, playoffs, and practice sessions.
    
    Args:
        match: Match object
        
    Returns:
        Dictionary with display information
    """
    # First check if this is a playoff game using the new fields
    if hasattr(match, 'is_playoff_game') and match.is_playoff_game:
        return _get_playoff_match_display(match, None)
    
    # Check if this is a special week using the new fields
    if hasattr(match, 'week_type') and match.week_type and match.week_type.upper() != 'REGULAR':
        week_type = match.week_type.upper()
        if week_type == 'FUN':
            return _get_fun_week_display(match, None)
        elif week_type == 'TST':
            return _get_tst_week_display(match, None)
        elif week_type == 'BYE':
            return _get_bye_week_display(match, None)
        elif week_type == 'BONUS':
            return _get_bonus_week_display(match, None)
        elif week_type == 'PLAYOFF':
            return _get_playoff_match_display(match, None)
        elif week_type == 'PRACTICE':
            return _get_practice_match_display(match, None)
    
    # Also check for special weeks based on home_team_id == away_team_id (the current format)
    if match.home_team_id == match.away_team_id:
        # This is a special week represented as a "self-match"
        if hasattr(match, 'week_type') and match.week_type:
            week_type = match.week_type.upper()
            if week_type == 'FUN':
                return _get_fun_week_display(match, None)
            elif week_type == 'TST':
                return _get_tst_week_display(match, None)
            elif week_type == 'BYE':
                return _get_bye_week_display(match, None)
            elif week_type == 'BONUS':
                return _get_bonus_week_display(match, None)
            elif week_type == 'PLAYOFF':
                return _get_playoff_match_display(match, None)
        else:
            # Legacy fallback - determine type from schedule
            schedule = match.schedule
            if schedule:
                week_type = _get_week_type_from_schedule(schedule)
                if week_type == 'PLAYOFF':
                    return _get_playoff_match_display(match, schedule)
                elif week_type == 'FUN':
                    return _get_fun_week_display(match, schedule)
                elif week_type == 'TST':
                    return _get_tst_week_display(match, schedule)
                elif week_type == 'BYE':
                    return _get_bye_week_display(match, schedule)
                elif week_type == 'BONUS':
                    return _get_bonus_week_display(match, schedule)
    
    # Get the schedule to determine week type (fallback for older format)
    schedule = match.schedule
    if not schedule:
        return _get_regular_match_display(match)
    
    # Check if this is a special week
    week_type = _get_week_type_from_schedule(schedule)
    
    if week_type == 'PLAYOFF':
        return _get_playoff_match_display(match, schedule)
    elif week_type == 'FUN':
        return _get_fun_week_display(match, schedule)
    elif week_type == 'TST':
        return _get_tst_week_display(match, schedule)
    elif week_type == 'BYE':
        return _get_bye_week_display(match, schedule)
    elif week_type == 'BONUS':
        return _get_bonus_week_display(match, schedule)
    elif week_type == 'PRACTICE':
        return _get_practice_match_display(match, schedule)
    else:
        return _get_regular_match_display(match)


def get_schedule_display_info(schedule: Schedule) -> Dict:
    """
    Get display information for a schedule entry.
    
    Args:
        schedule: Schedule object
        
    Returns:
        Dictionary with display information
    """
    week_type = _get_week_type_from_schedule(schedule)
    
    if week_type == 'PLAYOFF':
        return {
            'type': 'playoff',
            'title': 'Playoffs',
            'subtitle': 'Teams TBD',
            'show_opponent': False,
            'show_time': True,
            'show_location': False,
            'css_class': 'playoff-week',
            'icon': 'ti-trophy'
        }
    elif week_type == 'FUN':
        return {
            'type': 'fun',
            'title': 'Fun Week',
            'subtitle': 'Special activities and events',
            'show_opponent': False,
            'show_time': True,
            'show_location': True,
            'css_class': 'fun-week',
            'icon': 'ti-star'
        }
    elif week_type == 'TST':
        return {
            'type': 'tst',
            'title': 'The Soccer Tournament',
            'subtitle': 'Tournament matches and events',
            'show_opponent': False,
            'show_time': True,
            'show_location': True,
            'css_class': 'tst-week',
            'icon': 'ti-target'
        }
    elif week_type == 'BYE':
        return {
            'type': 'bye',
            'title': 'BYE Week',
            'subtitle': 'No games scheduled',
            'show_opponent': False,
            'show_time': False,
            'show_location': False,
            'css_class': 'bye-week',
            'icon': 'ti-calendar-off'
        }
    elif week_type == 'BONUS':
        return {
            'type': 'bonus',
            'title': 'Bonus Week',
            'subtitle': 'Additional activities',
            'show_opponent': False,
            'show_time': True,
            'show_location': True,
            'css_class': 'bonus-week',
            'icon': 'ti-gift'
        }
    elif week_type == 'PRACTICE':
        return {
            'type': 'practice',
            'title': 'Practice Session',
            'subtitle': 'Game 1 is practice',
            'show_opponent': True,
            'show_time': True,
            'show_location': True,
            'css_class': 'practice-week',
            'icon': 'ti-run'
        }
    else:
        return {
            'type': 'regular',
            'title': 'Regular Match',
            'subtitle': '',
            'show_opponent': True,
            'show_time': True,
            'show_location': True,
            'css_class': 'regular-week',
            'icon': 'ti-ball-football'
        }


def format_match_card_html(match: Match, team_perspective: Optional[Team] = None) -> str:
    """
    Format a match as HTML for display in team dashboards and calendars.
    
    Args:
        match: Match object
        team_perspective: Team viewing the match (for opponent display)
        
    Returns:
        HTML string for the match card
    """
    display_info = get_match_display_info(match)
    
    if display_info['type'] == 'playoff':
        return f"""
        <div class="match-card {display_info['css_class']}">
            <div class="match-header">
                <i class="{display_info['icon']} me-2"></i>
                <strong>{display_info['title']}</strong>
            </div>
            <div class="match-content">
                <div class="match-subtitle">{display_info['subtitle']}</div>
                <div class="match-date">{match.date.strftime('%B %d, %Y')}</div>
                <div class="match-time">{match.time.strftime('%I:%M %p')}</div>
                <div class="match-note">Bracket will be determined after regular season</div>
            </div>
        </div>
        """
    
    elif display_info['type'] in ['fun', 'tst', 'bye', 'bonus']:
        content_parts = [
            f'<div class="match-subtitle">{display_info["subtitle"]}</div>',
            f'<div class="match-date">{match.date.strftime("%B %d, %Y")}</div>'
        ]
        
        # Only add time and location for non-BYE weeks
        if display_info['type'] != 'bye':
            content_parts.extend([
                f'<div class="match-time">{match.time.strftime("%I:%M %p")}</div>',
                f'<div class="match-location">{match.location}</div>'
            ])
        
        return f"""
        <div class="match-card {display_info['css_class']}">
            <div class="match-header">
                <i class="{display_info['icon']} me-2"></i>
                <strong>{display_info['title']}</strong>
            </div>
            <div class="match-content">
                {''.join(content_parts)}
            </div>
        </div>
        """
    
    elif display_info['type'] == 'practice':
        opponent = _get_opponent_name(match, team_perspective)
        return f"""
        <div class="match-card {display_info['css_class']}">
            <div class="match-header">
                <i class="{display_info['icon']} me-2"></i>
                <strong>{display_info['title']}</strong>
            </div>
            <div class="match-content">
                <div class="match-opponent">vs {opponent}</div>
                <div class="match-date">{match.date.strftime('%B %d, %Y')}</div>
                <div class="match-time">{match.time.strftime('%I:%M %p')}</div>
                <div class="match-location">{match.location}</div>
                <div class="match-note text-warning">Practice Session</div>
            </div>
        </div>
        """
    
    else:  # Regular match
        opponent = _get_opponent_name(match, team_perspective)
        return f"""
        <div class="match-card {display_info['css_class']}">
            <div class="match-header">
                <i class="{display_info['icon']} me-2"></i>
                <strong>vs {opponent}</strong>
            </div>
            <div class="match-content">
                <div class="match-date">{match.date.strftime('%B %d, %Y')}</div>
                <div class="match-time">{match.time.strftime('%I:%M %p')}</div>
                <div class="match-location">{match.location}</div>
            </div>
        </div>
        """


def get_week_summary_for_dashboard(week_number: int, matches: List[Match]) -> Dict:
    """
    Get a summary of a week for dashboard display.
    
    Args:
        week_number: Week number
        matches: List of matches for the week
        
    Returns:
        Dictionary with week summary information
    """
    if not matches:
        return {'type': 'empty', 'title': f'Week {week_number}', 'matches': []}
    
    # Check if this is a special week
    first_match = matches[0]
    display_info = get_match_display_info(first_match)
    
    if display_info['type'] == 'playoff':
        return {
            'type': 'playoff',
            'title': f'Week {week_number}: Playoffs',
            'subtitle': 'Playoff brackets TBD',
            'css_class': 'playoff-week',
            'matches': matches
        }
    elif display_info['type'] == 'fun':
        return {
            'type': 'fun',
            'title': f'Week {week_number}: Fun Week',
            'subtitle': 'Special activities',
            'css_class': 'fun-week',
            'matches': matches
        }
    elif display_info['type'] == 'tst':
        return {
            'type': 'tst',
            'title': f'Week {week_number}: The Soccer Tournament',
            'subtitle': 'Tournament matches and events',
            'css_class': 'tst-week',
            'matches': matches
        }
    elif display_info['type'] == 'bye':
        return {
            'type': 'bye',
            'title': f'Week {week_number}: BYE Week',
            'subtitle': 'No games scheduled',
            'css_class': 'bye-week',
            'matches': matches
        }
    elif display_info['type'] == 'bonus':
        return {
            'type': 'bonus',
            'title': f'Week {week_number}: Bonus Week',
            'subtitle': 'Additional activities',
            'css_class': 'bonus-week',
            'matches': matches
        }
    elif display_info['type'] == 'practice':
        return {
            'type': 'practice',
            'title': f'Week {week_number}: Regular + Practice',
            'subtitle': 'Game 1 is practice session',
            'css_class': 'practice-week',
            'matches': matches
        }
    else:
        return {
            'type': 'regular',
            'title': f'Week {week_number}: Regular Season',
            'subtitle': '',
            'css_class': 'regular-week',
            'matches': matches
        }


# Helper functions

def _get_week_type_from_schedule(schedule: Schedule) -> str:
    """Determine week type from schedule."""
    # Check for special weeks in multiple ways for backward compatibility
    
    # Method 1: Check for new "self-match" format where team plays against itself
    if hasattr(schedule, 'team_id') and hasattr(schedule, 'opponent') and schedule.team_id == schedule.opponent:
        # This is a special week represented as a self-match
        # Check the associated match for week_type
        if hasattr(schedule, 'match') and schedule.match:
            match = schedule.match
            if hasattr(match, 'week_type'):
                return match.week_type.upper()
    
    # Method 2: Check for matches where home_team_id == away_team_id (from ScheduleTemplate)
    if hasattr(schedule, 'match') and schedule.match:
        match = schedule.match
        if match.home_team_id == match.away_team_id:
            # Special week - determine type from week_type field if available
            if hasattr(match, 'week_type'):
                return match.week_type.upper()
    
    # Method 3: Legacy check based on opponent team name
    if schedule.opponent_team and schedule.opponent_team.name in ['FUN WEEK', 'TST', 'BYE']:
        return schedule.opponent_team.name.replace(' WEEK', '').replace(' ', '')
    
    # Method 4: Check if opponent ID matches team ID (both point to same team)
    if hasattr(schedule, 'team_id') and hasattr(schedule, 'opponent') and schedule.team_id == schedule.opponent:
        # Try to get the team name to determine type
        try:
            from app.models import Team
            team = Team.query.get(schedule.team_id)
            if team and team.name in ['FUN WEEK', 'TST', 'BYE']:
                return team.name.replace(' WEEK', '').replace(' ', '')
        except:
            pass
            
    return 'REGULAR'


def _get_opponent_name(match: Match, team_perspective: Optional[Team] = None) -> str:
    """Get opponent name from team perspective."""
    if not team_perspective:
        return f"{match.home_team.name} vs {match.away_team.name}"
    
    if match.home_team_id == team_perspective.id:
        return match.away_team.name
    else:
        return match.home_team.name


def _get_regular_match_display(match: Match) -> Dict:
    """Get display info for regular match."""
    return {
        'type': 'regular',
        'title': 'Regular Match',
        'show_opponent': True,
        'show_time': True,
        'show_location': True,
        'css_class': 'regular-week',
        'icon': 'ti-ball-football'
    }


def _get_playoff_match_display(match: Match, schedule: Schedule) -> Dict:
    """Get display info for playoff match."""
    playoff_round = getattr(match, 'playoff_round', 1)
    return {
        'type': 'playoff',
        'title': f'Playoffs Round {playoff_round}',
        'subtitle': 'TBD',
        'show_opponent': True,  # Show TBD as opponent
        'show_time': True,
        'show_location': True,
        'css_class': 'playoff-week',
        'icon': 'ti-trophy'
    }


def _get_fun_week_display(match: Match, schedule: Schedule) -> Dict:
    """Get display info for fun week."""
    return {
        'type': 'fun',
        'title': 'Fun Week',
        'subtitle': 'Special activities and events',
        'show_opponent': False,
        'show_time': True,
        'show_location': True,
        'css_class': 'fun-week',
        'icon': 'ti-star'
    }


def _get_tst_week_display(match: Match, schedule: Schedule) -> Dict:
    """Get display info for TST week."""
    return {
        'type': 'tst',
        'title': 'The Soccer Tournament',
        'subtitle': 'Tournament matches and events',
        'show_opponent': False,
        'show_time': True,
        'show_location': True,
        'css_class': 'tst-week',
        'icon': 'ti-target'
    }


def _get_bye_week_display(match: Match, schedule: Schedule) -> Dict:
    """Get display info for BYE week."""
    return {
        'type': 'bye',
        'title': 'BYE Week',
        'subtitle': 'No games scheduled',
        'show_opponent': False,
        'show_time': False,
        'show_location': False,
        'css_class': 'bye-week',
        'icon': 'ti-calendar-off'
    }


def _get_bonus_week_display(match: Match, schedule: Schedule) -> Dict:
    """Get display info for bonus week."""
    return {
        'type': 'bonus',
        'title': 'Bonus Week',
        'subtitle': 'Additional activities',
        'show_opponent': False,
        'show_time': True,
        'show_location': True,
        'css_class': 'bonus-week',
        'icon': 'ti-gift'
    }


def _get_practice_match_display(match: Match, schedule: Schedule) -> Dict:
    """Get display info for practice match."""
    return {
        'type': 'practice',
        'title': 'Practice Session',
        'subtitle': 'Game 1 is practice',
        'show_opponent': True,
        'show_time': True,
        'show_location': True,
        'css_class': 'practice-week',
        'icon': 'ti-run'
    }