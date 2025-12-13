# app/admin_panel/routes/match_operations/__init__.py

"""
Match Operations Routes Package

This package splits the monolithic match_operations.py into focused modules:
- core.py - Match operations hub and statistics
- scheduling.py - Match scheduling and auto-scheduling
- views.py - Match view pages (upcoming, results, live, reports)
- leagues.py - League management and standings
- seasons.py - Season management
- teams.py - Team management and rosters
- transfers.py - Player transfers
- ajax.py - AJAX utility routes
- substitutes.py - Substitute management
- verification.py - Match verification
- substitute_pools.py - Substitute pool management
"""


def register_match_operations_routes():
    """
    Register all match operations routes.

    This function imports all route modules, which registers them
    with the admin_panel_bp blueprint via decorators.
    """
    from app.admin_panel.routes.match_operations import (
        core,
        scheduling,
        views,
        leagues,
        seasons,
        teams,
        transfers,
        ajax,
        substitutes,
        verification,
        substitute_pools,
    )
