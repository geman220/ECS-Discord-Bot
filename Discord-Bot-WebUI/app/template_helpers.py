"""
Template Helpers

This module provides helper functions that can be used in Jinja2 templates
for displaying schedule information, special weeks, and other UI elements.
"""

from flask import current_app
from app.helpers.schedule_display import (
    get_match_display_info, get_schedule_display_info, 
    format_match_card_html, get_week_summary_for_dashboard
)
from app.models import Match, Schedule, Team


def register_template_helpers(app):
    """
    Register template helper functions with the Flask app.
    
    Args:
        app: Flask application instance
    """
    
    @app.template_filter('match_display_info')
    def match_display_info_filter(match):
        """Get display information for a match."""
        return get_match_display_info(match)
    
    @app.template_filter('schedule_display_info')
    def schedule_display_info_filter(schedule):
        """Get display information for a schedule entry."""
        return get_schedule_display_info(schedule)
    
    @app.template_filter('match_card_html')
    def match_card_html_filter(match, team_perspective=None):
        """Format a match as HTML card."""
        return format_match_card_html(match, team_perspective)
    
    @app.template_filter('week_summary')
    def week_summary_filter(matches, week_number):
        """Get week summary for dashboard."""
        return get_week_summary_for_dashboard(week_number, matches)
    
    @app.template_filter('is_special_week')
    def is_special_week_filter(match):
        """Check if a match is part of a special week."""
        display_info = get_match_display_info(match)
        return display_info['type'] in ['playoff', 'fun', 'tst', 'bye', 'bonus', 'practice']
    
    @app.template_filter('is_playoff_week')
    def is_playoff_week_filter(match):
        """Check if a match is part of a playoff week."""
        display_info = get_match_display_info(match)
        return display_info['type'] == 'playoff'
    
    @app.template_filter('is_practice_match')
    def is_practice_match_filter(match):
        """Check if a match is a practice session."""
        display_info = get_match_display_info(match)
        return display_info['type'] == 'practice'
    
    @app.template_filter('opponent_name')
    def opponent_name_filter(match, team):
        """Get opponent name from team perspective."""
        if match.home_team_id == team.id:
            return match.away_team.name
        else:
            return match.home_team.name
    
    @app.template_filter('match_result_display')
    def match_result_display_filter(match, team):
        """Get match result display from team perspective."""
        if not match.home_team_score or not match.away_team_score:
            return "Not played"
        
        if match.home_team_id == team.id:
            team_score = match.home_team_score
            opponent_score = match.away_team_score
        else:
            team_score = match.away_team_score
            opponent_score = match.home_team_score
        
        if team_score > opponent_score:
            return f"W {team_score}-{opponent_score}"
        elif team_score < opponent_score:
            return f"L {team_score}-{opponent_score}"
        else:
            return f"T {team_score}-{opponent_score}"
    
    @app.template_global()
    def get_special_week_icon(week_type):
        """Get icon for special week types."""
        icons = {
            'playoff': 'ti-trophy',
            'fun': 'ti-star',
            'tst': 'ti-target',
            'bye': 'ti-calendar-off',
            'bonus': 'ti-gift',
            'practice': 'ti-run',
            'regular': 'ti-ball-football'
        }
        return icons.get(week_type, 'ti-calendar')
    
    @app.template_global()
    def get_special_week_color(week_type):
        """Get color class for special week types."""
        colors = {
            'playoff': 'danger',
            'fun': 'warning',
            'tst': 'info',
            'bye': 'secondary',
            'bonus': 'primary',
            'practice': 'success',
            'regular': 'secondary'
        }
        return colors.get(week_type, 'secondary')
    
    @app.template_global()
    def format_playoff_placeholder(playoff_round, teams_count):
        """Format playoff placeholder text."""
        if playoff_round == 1:
            return f"Playoffs Round 1 - {teams_count} teams, brackets TBD"
        elif playoff_round == 2:
            return f"Playoffs Round 2 - Final bracket TBD"
        else:
            return f"Playoffs Round {playoff_round} - Bracket TBD"
    
    @app.template_global()
    def should_show_playoff_setup(matches):
        """Check if playoff setup should be shown."""
        # Show playoff setup if we have playoff matches with placeholder teams
        for match in matches:
            display_info = get_match_display_info(match)
            if display_info['type'] == 'playoff':
                return True
        return False