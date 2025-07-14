# app/models.py

"""
Database Models Module

This module provides backward compatibility for existing imports while the actual
models have been refactored into separate modules within the models/ package.

All imports will continue to work exactly as before:
    from app.models import User, Player, Team, etc.

The models are now organized into logical groups:
- models/core.py: Core models (User, Role, Permission, League, Season)
- models/players.py: Player and team models
- models/matches.py: Match and scheduling models  
- models/stats.py: Statistics and analytics models
- models/communication.py: Notifications and messaging models
- models/store.py: Store and commerce models
- models/ecs_fc.py: ECS FC specific models
- models/substitutes.py: All substitute system models
- models/predictions.py: Draft prediction models
- models/external.py: External integration models
- models/league_features.py: League polls, drafts, and other features
"""

# Import everything from the models package to maintain backward compatibility
from app.models import *