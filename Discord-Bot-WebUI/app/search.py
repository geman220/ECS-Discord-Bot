# app/search.py

"""
Search Module

This module defines the search blueprint and endpoints used for performing
search operations within the application, such as searching for players by name.
"""

from flask import Blueprint, request, jsonify, url_for, g
from flask_login import login_required
from app.core.limiter import limiter
from app.models import Player

# Create a new blueprint for search routes with a URL prefix.
search_bp = Blueprint('search', __name__, url_prefix='/search')


@search_bp.route('/players', methods=['GET'])
@login_required
# Own bucket: typeahead fires per keystroke, and without an explicit limit it
# drains the shared per-IP default bucket that a whole venue NAT sits behind.
@limiter.limit("120 per minute")
def search_players():
    """
    Search for players by name.

    Query Parameters:
        term (str): The search term used to filter player names.

    Returns:
        A JSON response containing a list of players that match the search term.
        Each player object includes the player's id, name, and avatar URL
        (served under the profile_picture_url key the autocomplete expects).
    """
    term = request.args.get('term', '').strip()
    if len(term) < 2:
        return jsonify([])

    # Treat LIKE metacharacters as literals — otherwise "%%" matches everyone
    like_term = term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

    session = g.db_session
    players = (
        session.query(Player)
        .filter(Player.name.ilike(f'%{like_term}%'))
        .order_by(Player.is_current_player.desc().nullslast(), Player.name)
        .limit(10)
        .all()
    )

    results = [{
        'id': player.id,
        'name': player.name,
        'profile_picture_url': player.avatar_image_url or url_for('static', filename='img/default_player.png')
    } for player in players]

    response = jsonify(results)
    # Authenticated, per-user payload — never let an intermediary cache it
    response.headers['Cache-Control'] = 'no-store, private'
    return response