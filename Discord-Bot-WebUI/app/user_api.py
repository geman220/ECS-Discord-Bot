from app import csrf
from flask import Blueprint, request, jsonify, g
from app.models import Player, User
import logging

logger = logging.getLogger(__name__)
user_bp = Blueprint('user_api', __name__)
csrf.exempt(user_bp)

@user_bp.route('/get_notifications', methods=['GET'])
def get_notifications():
    discord_id = request.args.get("discord_id")
    if not discord_id:
        return jsonify({"error": "Missing discord_id parameter"}), 400

    session_db = g.db_session

    # Look up the player by discord_id
    player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404

    # Look up the associated user using player.user_id
    user = session_db.query(User).filter_by(id=player.user_id).first()
    if not user:
        return jsonify({"error": "Associated user not found"}), 404

    notifications = {
        "discord": user.discord_notifications,
        "email": user.email_notifications,
        "sms": user.sms_notifications
    }
    return jsonify({"notifications": notifications}), 200

@user_bp.route('/update_notifications', methods=['POST'])
def update_notifications():
    session_db = g.db_session
    data = request.json
    discord_id = data.get("discord_id")
    notifications = data.get("notifications")

    if not discord_id or notifications is None:
        return jsonify({"error": "Missing required fields"}), 400

    # Look up the player by discord_id
    player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404

    # Look up the associated user via player.user_id
    user = session_db.query(User).filter_by(id=player.user_id).first()
    if not user:
        return jsonify({"error": "Associated user not found"}), 404

    # Update the user's notification settings.
    user.discord_notifications = notifications.get("discord", False)
    user.email_notifications = notifications.get("email", False)
    user.sms_notifications = notifications.get("sms", False)

    session_db.commit()
    return jsonify({"message": "Notification preferences updated successfully"}), 200