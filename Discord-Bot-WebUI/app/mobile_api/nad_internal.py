# app/mobile_api/nad_internal.py

"""
Internal NAD board endpoint (bot-fed).

The Discord bot's /nads command calls this to list Newly Acquired Drinkers or to
hand back a link to the web board. Same trust boundary as the other internal
endpoints: shared FLASK_TOKEN secret in the X-Bot-Token header, no per-user JWT.
Coach scoping isn't applied here (the command itself is role-gated in Discord),
so the bot sees the full board — same derivation as the mobile/web front-ends.
"""

import logging
import os

from flask import jsonify, request

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.services.nad_board_service import compute_nad_board

logger = logging.getLogger(__name__)


def _bot_token_ok() -> bool:
    expected = os.getenv('FLASK_TOKEN')
    token = request.headers.get('X-Bot-Token', '')
    return bool(expected) and bool(token) and token == expected


@mobile_api_v2.route('/internal/nads', methods=['GET'])
def internal_list_nads():
    """List NADs for the Discord /nads command.

    Auth: X-Bot-Token == FLASK_TOKEN.
    Query params: search (optional), limit (default 25, max 100).
    Returns: { success, total, season_name, board_url, nads: [...] }
    """
    if not _bot_token_ok():
        return jsonify({"msg": "unauthorized"}), 401

    search = (request.args.get('search') or '').strip()
    limit = min(request.args.get('limit', 25, type=int), 100)

    with managed_session() as session:
        result = compute_nad_board(session, search=search, limit=limit, viewer_user_id=None)

    base = (os.getenv('WEBUI_BASE_URL') or 'https://portal.ecsfc.com').rstrip('/')
    board_url = f"{base}/nad-board/"

    # Trim to the fields the bot renders in an embed.
    nads = [{
        'name': n['name'],
        'favorite_position': n['favorite_position'],
        'team_name': n['team_name'],
        'note_count': n['note_count'],
    } for n in result['nads']]

    return jsonify({
        'success': True,
        'total': len(nads),
        'season_name': result['season_name'],
        'board_url': board_url,
        'nads': nads,
    }), 200
