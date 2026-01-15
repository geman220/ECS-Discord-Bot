# app/pub_league/__init__.py

"""
Pub League Order Linking Blueprint

This blueprint handles the Pub League order linking flow:
1. WooCommerce order verification
2. Discord login integration
3. Multi-pass assignment (self, search, claim links)
4. Profile conflict resolution
5. Player activation and role sync
6. Wallet pass generation

Routes:
- /pub-league/link-order - Main order linking wizard
- /pub-league/claim - Claim link processing
"""

from flask import Blueprint

pub_league_bp = Blueprint(
    'pub_league',
    __name__,
    url_prefix='/pub-league',
    template_folder='../templates/pub_league'
)

# Import routes to register them with the blueprint
from . import routes  # noqa: F401, E402
