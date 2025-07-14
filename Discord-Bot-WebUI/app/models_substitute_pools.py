# app/models_substitute_pools.py

"""
Backward compatibility module - models moved to app.models.substitutes
"""

# Import everything from the new location for backward compatibility
from app.models.substitutes import (
    SubstitutePool, SubstitutePoolHistory, SubstituteRequest,
    SubstituteResponse, SubstituteAssignment,
    get_eligible_players, get_active_substitutes, log_pool_action
)