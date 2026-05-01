# app/wallet_pass/routes/serve.py

"""
Public Apple Wallet pass serving — no headers required.

Apple Wallet / Safari can't send `Authorization: Bearer` or `X-API-Key`,
so this blueprint lives outside `/api/v1/` (which requires the mobile API
key middleware) and outside any JWT-protected blueprint. Security boundary
is the entropy of `WalletPass.download_token` (256 bits, urlsafe).

The Flutter app embeds these URLs in `passUrl` / `appleWallet.downloadUrl`
fields of `GET /api/v1/membership/wallet/pass`. When the user taps "Add to
Wallet", Safari opens the URL directly — no app headers in flight.
"""

import logging

from flask import Blueprint, make_response

from app.core.session_manager import managed_session
from app.models import Player
from app.models.wallet import WalletPass
from app.wallet_pass.services.pass_service import pass_service

logger = logging.getLogger(__name__)

# Mounted at root — full path is /wallet/pass/by-token/<token>.
apple_wallet_serve_bp = Blueprint('apple_wallet_serve', __name__, url_prefix='/wallet')


@apple_wallet_serve_bp.route('/pass/by-token/<token>', methods=['GET'])
def serve_pass_by_token(token: str):
    """Serve a .pkpass authenticated by per-pass download token.

    Works for both pub_league passes (player-linked) and ECS membership
    passes (WooCommerce orders, no portal user link). Apple Wallet caches
    the URL embedded at install time; this endpoint must remain stable.
    """
    try:
        with managed_session() as session_db:
            wallet_pass = session_db.query(WalletPass).filter_by(
                download_token=token,
                status='active'
            ).first()
            if not wallet_pass:
                return "Pass not found", 404

            # For player-linked passes (pub_league), block download once the
            # player is no longer current. ECS membership passes (no
            # player_id) skip this check — they're tied to the membership
            # year, not active player status.
            if wallet_pass.player_id:
                player = session_db.query(Player).get(wallet_pass.player_id)
                if not player or not player.is_current_player:
                    return "Pass expired", 410

            pass_file = pass_service.generate_apple_pass(wallet_pass)
            filename = f'{wallet_pass.member_name.replace(" ", "_")}_ecsfc_membership.pkpass'

            response = make_response(pass_file.getvalue())
            response.headers['Content-Type'] = 'application/vnd.apple.pkpass'
            response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response

    except Exception as e:
        logger.error(f"Error serving wallet pass by token: {e}", exc_info=True)
        return "Internal server error", 500
