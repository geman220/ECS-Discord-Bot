from app import csrf
from flask import Blueprint, request, jsonify, g, current_app
from app.models import User, Player, Match
from app.sms_helpers import (
    send_welcome_message,
    send_sms,
    verify_sms_confirmation,
    send_confirmation_sms,
    generate_confirmation_code
)
from datetime import datetime
import random
import string
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

    player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404

    user = session_db.query(User).filter_by(id=player.user_id).first()
    if not user:
        return jsonify({"error": "Associated user not found"}), 404

    notifications = {
        "discord": user.discord_notifications,
        "email": user.email_notifications,
        "sms": user.sms_notifications
    }
    sms_enrolled = bool(player.phone and user.sms_confirmation_code is None)
    phone_verified = bool(player.phone and player.is_phone_verified)
    return jsonify({
        "notifications": notifications,
        "sms_enrolled": sms_enrolled,
        "phone_verified": phone_verified
    }), 200

@user_bp.route('/update_notifications', methods=['POST'])
def update_notifications():
    session_db = g.db_session
    data = request.json
    discord_id = data.get("discord_id")
    notifications = data.get("notifications")

    if not discord_id or notifications is None:
        return jsonify({"error": "Missing required fields"}), 400

    player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404

    user = session_db.query(User).filter_by(id=player.user_id).first()
    if not user:
        return jsonify({"error": "Associated user not found"}), 404

    # Save previous SMS state to detect change.
    previous_sms = user.sms_notifications

    user.discord_notifications = notifications.get("discord", False)
    user.email_notifications = notifications.get("email", False)
    user.sms_notifications = notifications.get("sms", False)

    if not notifications.get("sms", False) and previous_sms:
        player.is_phone_verified = False
        player.sms_opt_out_timestamp = datetime.utcnow()
    session_db.commit()

    if notifications.get("sms", False) and not previous_sms:
        success, sid = send_sms(player.phone, "SMS notifications enabled for ECS FC. Reply END to unsubscribe.")
        if not success:
            logger.error(f"Failed to send SMS confirmation for user {user.id}: {sid}")
    elif not notifications.get("sms", False) and previous_sms:
        success, sid = send_sms(player.phone, "SMS notifications disabled for ECS FC. Reply START to re-subscribe.")
        if not success:
            logger.error(f"Failed to send SMS disable confirmation for user {user.id}: {sid}")

    return jsonify({"message": "Notification preferences updated successfully"}), 200

@user_bp.route('/sms_enroll', methods=['POST'])
def sms_enroll():
    session_db = g.db_session
    data = request.json
    discord_id = data.get("discord_id")
    phone = data.get("phone")
    if not discord_id or not phone:
        return jsonify({"error": "Missing required fields"}), 400

    player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404

    user = session_db.query(User).filter_by(id=player.user_id).first()
    if not user:
        return jsonify({"error": "Associated user not found"}), 404

    player.phone = phone
    success, msg_info = send_confirmation_sms(user)
    if success:
        session_db.commit()
        return jsonify({"message": "SMS enrollment initiated. Please check your phone for a confirmation code."}), 200
    else:
        return jsonify({"error": msg_info}), 400

@user_bp.route('/sms_confirm', methods=['POST'])
def sms_confirm():
    session_db = g.db_session
    data = request.json
    discord_id = data.get("discord_id")
    code = data.get("code")
    if not discord_id or not code:
        return jsonify({"error": "Missing required fields"}), 400

    player = session_db.query(Player).filter_by(discord_id=str(discord_id)).first()
    if not player:
        return jsonify({"error": "Player not found"}), 404

    user = session_db.query(User).filter_by(id=player.user_id).first()
    if not user:
        return jsonify({"error": "Associated user not found"}), 404

    if verify_sms_confirmation(user, code):
        player.is_phone_verified = True
        session_db.commit()
        return jsonify({"message": "SMS enrollment confirmed and notifications enabled."}), 200
    else:
        return jsonify({"error": "Invalid confirmation code."}), 400