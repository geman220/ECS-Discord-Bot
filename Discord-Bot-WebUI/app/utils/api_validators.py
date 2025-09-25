# app/utils/api_validators.py

"""
API Validation Utilities

This module provides comprehensive validation functions for API endpoints
including request data validation, parameter checking, and error formatting.
"""

import re
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Union, Tuple

def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> Optional[str]:
    """
    Validate that all required fields are present in the data.

    Args:
        data (dict): Data to validate
        required_fields (list): List of required field names

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    missing_fields = [field for field in required_fields if field not in data or data[field] is None]

    if missing_fields:
        return f"Missing required fields: {', '.join(missing_fields)}"

    return None


def validate_field_types(data: Dict[str, Any], field_types: Dict[str, type]) -> Optional[str]:
    """
    Validate that fields have the correct types.

    Args:
        data (dict): Data to validate
        field_types (dict): Dictionary mapping field names to expected types

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    for field, expected_type in field_types.items():
        if field in data and data[field] is not None:
            if not isinstance(data[field], expected_type):
                return f"Field '{field}' must be of type {expected_type.__name__}, got {type(data[field]).__name__}"

    return None


def validate_string_length(data: Dict[str, Any], field: str, min_length: int = 0, max_length: int = None) -> Optional[str]:
    """
    Validate string field length.

    Args:
        data (dict): Data to validate
        field (str): Field name
        min_length (int): Minimum length (default: 0)
        max_length (int): Maximum length (optional)

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    if field not in data or data[field] is None:
        return None

    value = data[field]
    if not isinstance(value, str):
        return f"Field '{field}' must be a string"

    if len(value) < min_length:
        return f"Field '{field}' must be at least {min_length} characters long"

    if max_length is not None and len(value) > max_length:
        return f"Field '{field}' must be no more than {max_length} characters long"

    return None


def validate_integer_range(data: Dict[str, Any], field: str, min_value: int = None, max_value: int = None) -> Optional[str]:
    """
    Validate integer field range.

    Args:
        data (dict): Data to validate
        field (str): Field name
        min_value (int): Minimum value (optional)
        max_value (int): Maximum value (optional)

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    if field not in data or data[field] is None:
        return None

    value = data[field]
    if not isinstance(value, int):
        return f"Field '{field}' must be an integer"

    if min_value is not None and value < min_value:
        return f"Field '{field}' must be at least {min_value}"

    if max_value is not None and value > max_value:
        return f"Field '{field}' must be no more than {max_value}"

    return None


def validate_choice_field(data: Dict[str, Any], field: str, valid_choices: List[str]) -> Optional[str]:
    """
    Validate that a field contains one of the valid choices.

    Args:
        data (dict): Data to validate
        field (str): Field name
        valid_choices (list): List of valid choices

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    if field not in data or data[field] is None:
        return None

    value = data[field]
    if value not in valid_choices:
        return f"Field '{field}' must be one of: {', '.join(valid_choices)}"

    return None


def validate_email(email: str) -> bool:
    """
    Validate email format.

    Args:
        email (str): Email to validate

    Returns:
        bool: True if valid, False otherwise
    """
    if not email or not isinstance(email, str):
        return False

    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def validate_date_string(date_string: str) -> bool:
    """
    Validate date string in ISO format (YYYY-MM-DD).

    Args:
        date_string (str): Date string to validate

    Returns:
        bool: True if valid, False otherwise
    """
    try:
        datetime.strptime(date_string, '%Y-%m-%d')
        return True
    except (ValueError, TypeError):
        return False


def validate_time_string(time_string: str) -> bool:
    """
    Validate time string in HH:MM format.

    Args:
        time_string (str): Time string to validate

    Returns:
        bool: True if valid, False otherwise
    """
    try:
        datetime.strptime(time_string, '%H:%M')
        return True
    except (ValueError, TypeError):
        return False


def validate_datetime_string(datetime_string: str) -> bool:
    """
    Validate datetime string in ISO format.

    Args:
        datetime_string (str): Datetime string to validate

    Returns:
        bool: True if valid, False otherwise
    """
    try:
        datetime.fromisoformat(datetime_string.replace('Z', '+00:00'))
        return True
    except (ValueError, TypeError):
        return False


def validate_pagination_params(limit: int, offset: int, max_limit: int = 100) -> Optional[str]:
    """
    Validate pagination parameters.

    Args:
        limit (int): Limit value
        offset (int): Offset value
        max_limit (int): Maximum allowed limit

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    if not isinstance(limit, int) or limit < 1:
        return "Limit must be a positive integer"

    if limit > max_limit:
        return f"Limit must be no more than {max_limit}"

    if not isinstance(offset, int) or offset < 0:
        return "Offset must be a non-negative integer"

    return None


def validate_notification_preferences(preferences: Dict[str, Any]) -> Optional[str]:
    """
    Validate notification preferences structure.

    Args:
        preferences (dict): Notification preferences

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    if not isinstance(preferences, dict):
        return "Notification preferences must be an object"

    valid_keys = {'sms', 'email', 'discord'}
    for key in preferences:
        if key not in valid_keys:
            return f"Invalid notification preference key: {key}. Valid keys: {', '.join(valid_keys)}"

        if not isinstance(preferences[key], bool):
            return f"Notification preference '{key}' must be a boolean"

    return None


def validate_substitute_request_data(data: Dict[str, Any]) -> Optional[str]:
    """
    Comprehensive validation for substitute request data.

    Args:
        data (dict): Request data to validate

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    # Required fields
    required_fields = ['match_id', 'team_id', 'league_type']
    error = validate_required_fields(data, required_fields)
    if error:
        return error

    # Field types
    field_types = {
        'match_id': int,
        'team_id': int,
        'league_type': str,
        'substitutes_needed': int,
        'positions_needed': str,
        'gender_preference': str,
        'notes': str
    }
    error = validate_field_types(data, field_types)
    if error:
        return error

    # League type validation
    valid_league_types = ['ECS FC', 'Classic', 'Premier']
    error = validate_choice_field(data, 'league_type', valid_league_types)
    if error:
        return error

    # Substitutes needed validation
    error = validate_integer_range(data, 'substitutes_needed', min_value=1, max_value=10)
    if error:
        return error

    # Gender preference validation
    if 'gender_preference' in data and data['gender_preference']:
        valid_genders = ['male', 'female', 'any', 'non-binary']
        error = validate_choice_field(data, 'gender_preference', valid_genders)
        if error:
            return error

    # String length validations
    error = validate_string_length(data, 'positions_needed', max_length=255)
    if error:
        return error

    error = validate_string_length(data, 'notes', max_length=1000)
    if error:
        return error

    return None


def validate_substitute_response_data(data: Dict[str, Any]) -> Optional[str]:
    """
    Validate substitute response data.

    Args:
        data (dict): Response data to validate

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    # Required fields
    required_fields = ['is_available', 'league_type']
    error = validate_required_fields(data, required_fields)
    if error:
        return error

    # Field types
    field_types = {
        'is_available': bool,
        'league_type': str,
        'response_text': str
    }
    error = validate_field_types(data, field_types)
    if error:
        return error

    # League type validation
    valid_league_types = ['ECS FC', 'Classic', 'Premier']
    error = validate_choice_field(data, 'league_type', valid_league_types)
    if error:
        return error

    # Response text length
    error = validate_string_length(data, 'response_text', max_length=500)
    if error:
        return error

    return None


def validate_substitute_assignment_data(data: Dict[str, Any]) -> Optional[str]:
    """
    Validate substitute assignment data.

    Args:
        data (dict): Assignment data to validate

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    # Required fields
    required_fields = ['player_id', 'league_type']
    error = validate_required_fields(data, required_fields)
    if error:
        return error

    # Field types
    field_types = {
        'player_id': int,
        'league_type': str,
        'position_assigned': str,
        'notes': str
    }
    error = validate_field_types(data, field_types)
    if error:
        return error

    # League type validation
    valid_league_types = ['ECS FC', 'Classic', 'Premier']
    error = validate_choice_field(data, 'league_type', valid_league_types)
    if error:
        return error

    # String length validations
    error = validate_string_length(data, 'position_assigned', max_length=100)
    if error:
        return error

    error = validate_string_length(data, 'notes', max_length=500)
    if error:
        return error

    return None


def validate_pool_join_data(data: Dict[str, Any]) -> Optional[str]:
    """
    Validate substitute pool join data.

    Args:
        data (dict): Pool join data to validate

    Returns:
        str or None: Error message if validation fails, None if valid
    """
    # Field types
    field_types = {
        'preferred_positions': list,
        'max_matches_per_week': int,
        'notes': str,
        'notification_preferences': dict
    }
    error = validate_field_types(data, field_types)
    if error:
        return error

    # Max matches per week validation
    error = validate_integer_range(data, 'max_matches_per_week', min_value=1, max_value=10)
    if error:
        return error

    # Notes length validation
    error = validate_string_length(data, 'notes', max_length=500)
    if error:
        return error

    # Notification preferences validation
    if 'notification_preferences' in data and data['notification_preferences']:
        error = validate_notification_preferences(data['notification_preferences'])
        if error:
            return error

    # Preferred positions validation
    if 'preferred_positions' in data and data['preferred_positions']:
        if not isinstance(data['preferred_positions'], list):
            return "Preferred positions must be a list"

        valid_positions = [
            'Goalkeeper', 'Defender', 'Midfielder', 'Forward',
            'Center Back', 'Left Back', 'Right Back',
            'Defensive Midfielder', 'Central Midfielder', 'Attacking Midfielder',
            'Left Winger', 'Right Winger', 'Striker'
        ]

        for position in data['preferred_positions']:
            if not isinstance(position, str):
                return "All positions must be strings"
            if position not in valid_positions:
                return f"Invalid position: {position}. Valid positions: {', '.join(valid_positions)}"

    return None


def format_validation_error(error_message: str, field: str = None) -> Dict[str, Any]:
    """
    Format validation error for API response.

    Args:
        error_message (str): Error message
        field (str): Field that caused the error (optional)

    Returns:
        dict: Formatted error response
    """
    response = {
        'error': 'Validation failed',
        'message': error_message,
        'code': 'VALIDATION_ERROR'
    }

    if field:
        response['field'] = field

    return response


def sanitize_input_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize input data by trimming strings and removing empty values.

    Args:
        data (dict): Data to sanitize

    Returns:
        dict: Sanitized data
    """
    sanitized = {}

    for key, value in data.items():
        if isinstance(value, str):
            # Trim whitespace
            value = value.strip()
            # Convert empty strings to None
            if value == '':
                value = None
        elif isinstance(value, dict):
            # Recursively sanitize nested dictionaries
            value = sanitize_input_data(value)
        elif isinstance(value, list):
            # Sanitize list items
            value = [
                item.strip() if isinstance(item, str) else item
                for item in value
                if item is not None and (not isinstance(item, str) or item.strip())
            ]

        # Only include non-None values
        if value is not None:
            sanitized[key] = value

    return sanitized