"""
Display Helper Functions

This module provides utility functions for formatting data for display purposes
without modifying the underlying data models.
"""

from datetime import datetime
import pytz


def format_position_name(position):
    """
    Convert underscore-separated position names to proper title case for display.
    
    Args:
        position (str): Position name with underscores (e.g., 'central_midfielder')
        
    Returns:
        str: Formatted position name (e.g., 'Central Midfielder')
        
    Examples:
        >>> format_position_name('central_midfielder')
        'Central Midfielder'
        >>> format_position_name('goalkeeper')
        'Goalkeeper'
        >>> format_position_name('left_back')
        'Left Back'
    """
    if not position:
        return position
    
    return position.replace('_', ' ').title()


def format_field_name(field_name):
    """
    Convert underscore-separated field names to proper title case for display.
    This is a more general version that can be used for any field name.
    
    Args:
        field_name (str): Field name with underscores
        
    Returns:
        str: Formatted field name
        
    Examples:
        >>> format_field_name('favorite_position')
        'Favorite Position'
        >>> format_field_name('jersey_size')
        'Jersey Size'
    """
    if not field_name:
        return field_name
    
    return field_name.replace('_', ' ').title()


def convert_utc_to_pacific(utc_dt):
    """
    Convert a UTC datetime to Pacific Time (PST/PDT).
    
    Args:
        utc_dt (datetime): UTC datetime object (can be naive or timezone-aware)
        
    Returns:
        datetime: Timezone-aware datetime in Pacific Time
        
    Examples:
        >>> utc_time = datetime(2025, 7, 12, 18, 40)  # 6:40 PM UTC
        >>> pacific_time = convert_utc_to_pacific(utc_time)
        >>> print(pacific_time.strftime('%B %d, %Y at %I:%M %p %Z'))
        'July 12, 2025 at 11:40 AM PDT'
    """
    if not utc_dt:
        return None
    
    # Define timezones
    utc_tz = pytz.UTC
    pacific_tz = pytz.timezone('America/Los_Angeles')
    
    # If datetime is naive, assume it's UTC
    if utc_dt.tzinfo is None:
        utc_dt = utc_tz.localize(utc_dt)
    
    # Convert to Pacific Time
    pacific_dt = utc_dt.astimezone(pacific_tz)
    
    return pacific_dt


def format_datetime_pacific(utc_dt, format_string='%B %d, %Y at %I:%M %p %Z'):
    """
    Format a UTC datetime as Pacific Time with timezone abbreviation.
    
    Args:
        utc_dt (datetime): UTC datetime object
        format_string (str): strftime format string
        
    Returns:
        str: Formatted datetime string in Pacific Time
        
    Examples:
        >>> utc_time = datetime(2025, 7, 12, 18, 40)
        >>> formatted = format_datetime_pacific(utc_time)
        >>> print(formatted)
        'July 12, 2025 at 11:40 AM PDT'
    """
    if not utc_dt:
        return None
    
    pacific_dt = convert_utc_to_pacific(utc_dt)
    return pacific_dt.strftime(format_string)


def format_datetime_pacific_short(utc_dt):
    """
    Format a UTC datetime as Pacific Time in short format.
    
    Args:
        utc_dt (datetime): UTC datetime object
        
    Returns:
        str: Short formatted datetime string (e.g., "7/12/25 11:40 AM PST")
    """
    return format_datetime_pacific(utc_dt, '%m/%d/%y %I:%M %p %Z')