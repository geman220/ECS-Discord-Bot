# app/models_draft_predictions.py

"""
Backward compatibility module - models moved to app.models.predictions
"""

# Import everything from the new location for backward compatibility
from app.models.predictions import (
    DraftSeason, DraftPrediction, DraftPredictionSummary
)