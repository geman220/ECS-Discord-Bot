"""
RSVP Filtering Utilities

This module provides standardized filtering for "active" RSVPs to dramatically reduce
memory usage. RSVPs are only considered "active" for 6-7 days after they're sent
(Monday for next Sunday), after which they become historical data.

Key Insight: RSVPs follow a predictable lifecycle:
- Day 0 (Monday): RSVP sent for match on Day 6 (Sunday)  
- Days 1-6: Players respond, Discord sync needed
- Day 7+: Match completed, RSVP becomes historical data
"""

from datetime import datetime, timedelta, date
from typing import Any, Optional
from sqlalchemy.orm import Query
from sqlalchemy import and_

# Configuration
ACTIVE_RSVP_DAYS = 7  # RSVPs are "active" for 7 days
DISCORD_CARE_DAYS = 8  # Discord bot cares about RSVPs for 8 days (slight buffer)


def get_active_rsvp_date_threshold() -> date:
    """
    Get the date threshold for "active" RSVPs.
    
    RSVPs for matches on or after this date are considered active.
    RSVPs for matches before this date are historical.
    
    Returns:
        date: The cutoff date for active RSVPs
    """
    return datetime.utcnow().date() - timedelta(days=ACTIVE_RSVP_DAYS)


def get_discord_care_date_threshold() -> date:
    """
    Get the date threshold for Discord bot caring about RSVPs.
    
    Uses a slightly longer window than active RSVPs to account for
    late responses and edge cases.
    
    Returns:
        date: The cutoff date for Discord RSVP processing
    """
    return datetime.utcnow().date() - timedelta(days=DISCORD_CARE_DAYS)


def filter_active_rsvps(query: Query, match_model: Any, availability_model: Any) -> Query:
    """
    Add filtering to only include RSVPs for recent/upcoming matches.
    
    This reduces memory usage by ~90% by excluding historical RSVPs that
    no longer need active processing.
    
    Args:
        query: SQLAlchemy query to filter
        match_model: The Match model class (usually app.models.Match)
        availability_model: The Availability model class
        
    Returns:
        Query: Filtered query that only includes active RSVPs
        
    Example:
        query = session.query(Availability)
        query = filter_active_rsvps(query, Match, Availability)
        active_rsvps = query.all()  # Only recent RSVPs
    """
    threshold = get_active_rsvp_date_threshold()
    
    # Join with Match table if not already joined
    if not _has_match_join(query):
        query = query.join(match_model, match_model.id == availability_model.match_id)
    
    # Filter by match date
    return query.filter(match_model.date >= threshold)


def filter_discord_relevant_rsvps(query: Query, match_model: Any, availability_model: Any) -> Query:
    """
    Add filtering for RSVPs that Discord bot should care about.
    
    Uses a slightly longer window than active RSVPs to handle edge cases.
    
    Args:
        query: SQLAlchemy query to filter
        match_model: The Match model class
        availability_model: The Availability model class
        
    Returns:
        Query: Filtered query for Discord-relevant RSVPs
    """
    threshold = get_discord_care_date_threshold()
    
    if not _has_match_join(query):
        query = query.join(match_model, match_model.id == availability_model.match_id)
    
    return query.filter(match_model.date >= threshold)


def is_match_active_for_rsvp(match_date: date) -> bool:
    """
    Check if a specific match date is within the active RSVP window.
    
    Args:
        match_date: The date of the match to check
        
    Returns:
        bool: True if RSVPs for this match are still active
    """
    return match_date >= get_active_rsvp_date_threshold()


def is_match_relevant_for_discord(match_date: date) -> bool:
    """
    Check if Discord bot should care about RSVPs for this match.
    
    Args:
        match_date: The date of the match to check
        
    Returns:
        bool: True if Discord should process RSVPs for this match
    """
    return match_date >= get_discord_care_date_threshold()


def should_sync_rsvp_to_discord(match_date: date, availability_responded_at: Optional[datetime] = None) -> bool:
    """
    Determine if an RSVP should be synced to Discord.
    
    Args:
        match_date: Date of the match
        availability_responded_at: When the availability was last updated (optional)
        
    Returns:
        bool: True if this RSVP should be synced to Discord
    """
    # Primary filter: match must be recent enough
    if not is_match_relevant_for_discord(match_date):
        return False
    
    # Optional: additional filtering based on response time
    # (could add logic here if needed)
    
    return True


def add_active_rsvp_conditions(conditions: list, match_model: Any) -> list:
    """
    Add active RSVP filtering conditions to an existing list of conditions.
    
    Useful for complex queries where you're building conditions dynamically.
    
    Args:
        conditions: List of existing SQLAlchemy conditions
        match_model: The Match model class
        
    Returns:
        list: Updated conditions list with active RSVP filtering
    """
    threshold = get_active_rsvp_date_threshold()
    conditions.append(match_model.date >= threshold)
    return conditions


def _has_match_join(query: Query) -> bool:
    """
    Check if a query already has a join with the Match table.
    
    This is a simple heuristic - in practice, you might want more sophisticated
    join detection depending on your use case.
    
    Args:
        query: SQLAlchemy query to check
        
    Returns:
        bool: True if query likely already has match join
    """
    # Simple check - look for 'matches' or 'match' in the query string
    query_str = str(query).lower()
    return 'join matches' in query_str or 'join match' in query_str


class ActiveRSVPFilter:
    """
    Context manager for applying active RSVP filtering to multiple queries.
    
    Usage:
        with ActiveRSVPFilter(Match, Availability) as filter:
            query1 = filter.apply(session.query(Availability))
            query2 = filter.apply(session.query(Availability).filter_by(response='yes'))
    """
    
    def __init__(self, match_model: Any, availability_model: Any, use_discord_threshold: bool = False):
        self.match_model = match_model
        self.availability_model = availability_model
        self.use_discord_threshold = use_discord_threshold
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
        
    def apply(self, query: Query) -> Query:
        """Apply the appropriate filtering to a query"""
        if self.use_discord_threshold:
            return filter_discord_relevant_rsvps(query, self.match_model, self.availability_model)
        else:
            return filter_active_rsvps(query, self.match_model, self.availability_model)


# Convenience functions for common models
def filter_availability_active(query: Query) -> Query:
    """
    Convenience function to filter Availability queries for active RSVPs.
    
    Assumes standard model imports are available.
    """
    from app.models import Match, Availability
    return filter_active_rsvps(query, Match, Availability)


def filter_availability_discord_relevant(query: Query) -> Query:
    """
    Convenience function to filter Availability queries for Discord-relevant RSVPs.
    """
    from app.models import Match, Availability
    return filter_discord_relevant_rsvps(query, Match, Availability)


# Performance statistics
def get_rsvp_filtering_stats(session) -> dict:
    """
    Get statistics on how much filtering reduces dataset size.
    
    Useful for monitoring the effectiveness of RSVP filtering.
    """
    from app.models import Match, Availability
    
    # Total RSVPs
    total_rsvps = session.query(Availability).count()
    
    # Active RSVPs
    active_query = session.query(Availability)
    active_query = filter_active_rsvps(active_query, Match, Availability)
    active_rsvps = active_query.count()
    
    # Discord-relevant RSVPs  
    discord_query = session.query(Availability)
    discord_query = filter_discord_relevant_rsvps(discord_query, Match, Availability)
    discord_rsvps = discord_query.count()
    
    return {
        'total_rsvps': total_rsvps,
        'active_rsvps': active_rsvps,
        'discord_relevant_rsvps': discord_rsvps,
        'active_percentage': (active_rsvps / total_rsvps * 100) if total_rsvps > 0 else 0,
        'discord_percentage': (discord_rsvps / total_rsvps * 100) if total_rsvps > 0 else 0,
        'memory_savings_estimate': f"{100 - (active_rsvps / total_rsvps * 100):.1f}%" if total_rsvps > 0 else "0%",
        'active_threshold': get_active_rsvp_date_threshold(),
        'discord_threshold': get_discord_care_date_threshold()
    }