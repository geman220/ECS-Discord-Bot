# app/admin_panel/routes/surveys/__init__.py

"""
Survey & Poll admin routes package.

Importing this package registers all survey route modules with admin_panel_bp
(routes self-register via @admin_panel_bp.route decorators on import).
"""

from . import builder      # noqa: F401  list / builder / CRUD / lifecycle
from . import results       # noqa: F401  results dashboard / analytics / export
from . import distribute    # noqa: F401  channel distribution (web/discord/email/push)
