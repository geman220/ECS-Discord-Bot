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


ALLOWED_ROLES = {'Global Admin', 'Pub League Admin', 'Pub League Coach'}

# At or below this many results we return rich per-player cards (photo + notes);
# above it, a compact list. Bounded so we never exceed Discord's 10-embeds limit.
DETAIL_MAX = 6


@mobile_api_v2.route('/internal/nads', methods=['GET'])
def internal_list_nads():
    """List NADs for the Discord /nads command.

    Auth: X-Bot-Token == FLASK_TOKEN (bot trust) PLUS the invoking Discord user
    must map to an app user holding an allowed role — so authorization uses the
    real app role model (a Global Admin in the app can run it even if their Discord
    roles differ). The board is then scoped to that viewer (admins see all; coaches
    see their division + the unassigned pool), same as web/mobile.

    Query params: discord_id (invoking user), search (optional), limit (default 25, max 100).
    Returns: { success, total, season_name, board_url, nads: [...] } or 403 if not allowed.
    """
    if not _bot_token_ok():
        return jsonify({"msg": "unauthorized"}), 401

    discord_id = (request.args.get('discord_id') or '').strip()
    search = (request.args.get('search') or '').strip()
    limit = min(request.args.get('limit', 25, type=int), 100)

    with managed_session() as session:
        from app.models import Player

        # Resolve the invoking Discord user to an app user and check their roles.
        viewer_user_id = None
        role_names = set()
        if discord_id:
            player = session.query(Player).filter_by(discord_id=discord_id).first()
            if player and player.user:
                viewer_user_id = player.user_id
                role_names = {r.name for r in player.user.roles}

        if not (role_names & ALLOWED_ROLES):
            return jsonify({
                'success': False,
                'authorized': False,
                'msg': 'not authorized',
            }), 403

        result = compute_nad_board(session, search=search, limit=limit, viewer_user_id=viewer_user_id)
        nads_raw = result['nads']

        base = (os.getenv('WEBUI_BASE_URL') or 'https://portal.ecsfc.com').rstrip('/')
        board_url = f"{base}/nad-board/"

        # A small result set (e.g. a name search) gets rich cards: photo, full info,
        # and the scouting notes with authors. A big list stays compact.
        detail = 0 < len(nads_raw) <= DETAIL_MAX

        def abs_url(rel):
            if not rel:
                return None
            return rel if rel.startswith('http') else f"{base}{rel}"

        def labels(value):
            if not value:
                return []
            s = str(value).strip()
            if s.startswith('{') and s.endswith('}'):
                s = s[1:-1]
            return [p.strip().strip('"') for p in s.split(',') if p.strip()]

        # Fetch notes (with authors) for the detailed set in one grouped query.
        notes_by_player = {}
        if detail:
            from sqlalchemy.orm import joinedload
            from app.models import User
            from app.models.players import PlayerAdminNote
            pids = [n['id'] for n in nads_raw]
            rows = (
                session.query(PlayerAdminNote)
                .filter(PlayerAdminNote.player_id.in_(pids))
                .options(joinedload(PlayerAdminNote.author).joinedload(User.player))
                .order_by(PlayerAdminNote.created_at.asc())
                .all()
            )
            for note in rows:
                d = note.to_dict(include_author=True)
                author = (d.get('author') or {})
                notes_by_player.setdefault(note.player_id, []).append({
                    'content': d.get('content'),
                    'author': author.get('name') or author.get('username') or 'Unknown',
                    'created_at': d.get('created_at'),
                })

        nads = []
        for n in nads_raw:
            item = {
                'name': n['name'],
                'favorite_position': n['favorite_position'],
                'team_name': n['team_name'],
                'note_count': n['note_count'],
            }
            if detail:
                item.update({
                    'pronouns': n['pronouns'],
                    'other_positions': labels(n['other_positions']),
                    'positions_not_to_play': labels(n['positions_not_to_play']),
                    'frequency_play_goal': n['frequency_play_goal'],
                    'jersey_size': n['jersey_size'],
                    'profile_picture_url': abs_url(n['profile_picture_url']),
                    'notes': notes_by_player.get(n['id'], []),
                })
            nads.append(item)

    return jsonify({
        'success': True,
        'total': len(nads),
        'detail': detail,
        'season_name': result['season_name'],
        'board_url': board_url,
        'nads': nads,
    }), 200
