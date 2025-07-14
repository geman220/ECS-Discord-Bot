# app/models_ecs_subs.py

"""
Backward compatibility module - models moved to app.models.substitutes
"""

# Import everything from the new location for backward compatibility
from app.models.substitutes import (
    EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment, EcsFcSubPool
)