from flask import Blueprint, request, jsonify, url_for, g
from flask_login import login_required
from app.models import Player

# Create a new blueprint for search routes
search_bp = Blueprint('search', __name__)

@search_bp.route('/search/players', methods=['GET'])
@login_required
def search_players():
    term = request.args.get('term', '').strip()
    session = g.db_session
    players = session.query(Player).filter(Player.name.ilike(f'%{term}%')).all()
    results = [{
        'id': player.id,
        'name': player.name,
        'profile_picture_url': player.profile_picture_url or url_for('static', filename='img/default_player.png')
    } for player in players]
    return jsonify(results)