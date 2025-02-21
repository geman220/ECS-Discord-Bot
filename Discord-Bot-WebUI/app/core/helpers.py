# app/core/helpers.py'

"""
Core Helper Utilities.

This module provides helper functions that are used across the application.
In particular, it includes a utility function to retrieve an MLSMatch instance
from the database using either its internal primary key (id) or its ESPN match_id.
This function enables flexible lookups so that either unique identifier can be used.

Example:
    from app.core.helpers import get_match
    match = get_match(session, identifier)
    # identifier can be either the internal id (e.g. 36) or the ESPN match_id (e.g. "72681")
"""

from sqlalchemy import or_
from app.models import MLSMatch

def get_match(session, identifier) -> MLSMatch:
    """
    Retrieve an MLSMatch using either the internal id (if identifier is numeric)
    or the ESPN match_id (always stored as a string).

    This helper function attempts to convert the provided identifier to an integer.
    If successful, it adds a filter to check if the internal primary key (id) matches.
    It also always checks whether the ESPN match_id (stored as a string) matches
    the string representation of the identifier. This dual filtering ensures that
    the function works regardless of which unique identifier is provided.

    :param session: The SQLAlchemy session object used for querying the database.
    :param identifier: A unique identifier for the match, which can be either the
                       internal primary key (integer) or the ESPN match_id (string).
    :return: An instance of MLSMatch if found; otherwise, None.
    """
    try:
        numeric_id = int(identifier)
    except (ValueError, TypeError):
        numeric_id = None

    filters = []
    if numeric_id is not None:
        filters.append(MLSMatch.id == numeric_id)
    # Always check match_id as a string.
    filters.append(MLSMatch.match_id == str(identifier))
    
    return session.query(MLSMatch).filter(or_(*filters)).first()
