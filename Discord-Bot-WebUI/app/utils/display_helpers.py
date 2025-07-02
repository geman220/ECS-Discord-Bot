"""
Display Helper Functions

This module provides utility functions for formatting data for display purposes
without modifying the underlying data models.
"""


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