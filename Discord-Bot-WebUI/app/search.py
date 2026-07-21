# app/search.py

"""
Search Module

This module defines the search blueprint and endpoints used for performing
search operations within the application, such as searching for players by name.
"""

from flask import Blueprint, request, jsonify, url_for, g
from flask_login import login_required
from app.models import Player

# Create a new blueprint for search routes with a URL prefix.
search_bp = Blueprint('search', __name__, url_prefix='/search')


@search_bp.route('/players', methods=['GET'])
@login_required
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

    session = g.db_session
    players = (
        session.query(Player)
        .filter(Player.name.ilike(f'%{term}%'))
        .order_by(Player.is_current_player.desc().nullslast(), Player.name)
        .limit(10)
        .all()
    )

    results = [{
        'id': player.id,
        'name': player.name,
        'profile_picture_url': player.avatar_image_url or url_for('static', filename='img/default_player.png')
    } for player in players]

    return jsonify(results)