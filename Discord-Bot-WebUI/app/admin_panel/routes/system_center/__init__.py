# app/admin_panel/routes/system_center/__init__.py

"""
System Command Center routes package.

Importing the submodules triggers their @admin_panel_bp.route decorators so the
routes register. Kept as a package (like the other modular route areas) so later
phases can add per-tab modules without touching the registrar.
"""

from . import worklist  # noqa: F401  (import triggers route registration)
