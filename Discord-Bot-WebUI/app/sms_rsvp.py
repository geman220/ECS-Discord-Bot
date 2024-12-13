from flask import Blueprint, jsonify, request, render_template, abort, url_for, g
from flask_wtf import FlaskForm
from app.models import Player, Match, Availability, Token
from app.sms_helpers import send_sms
from datetime import datetime, timedelta
import secrets
import logging

logger = logging.getLogger(__name__)

sms_rsvp_bp = Blueprint('sms_rsvp', __name__)

def update_rsvp(match_id, player_id, response, discord_id=None):
    if response not in ['yes', 'no', 'maybe']:
        return False

    session = g.db_session
    try:
        availability = session.query(Availability).filter_by(match_id=match_id, player_id=player_id).first()
        if availability:
            availability.response = response
            availability.responded_at = datetime.utcnow()
        else:
            availability = Availability(
                match_id=match_id,
                player_id=player_id,
                response=response,
                discord_id=discord_id,
                responded_at=datetime.utcnow()
            )
            session.add(availability)
        return True
    except Exception as e:
        logger.error(f"Error updating RSVP for player {player_id}: {e}", exc_info=True)
        return False

def get_next_matches(team_id, limit=2):
    session = g.db_session
    return session.query(Match).filter(
        (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
        Match.date >= datetime.utcnow()
    ).order_by(Match.date, Match.time).limit(limit).all()

def generate_token():
    return secrets.token_urlsafe(24)

@sms_rsvp_bp.route('/generate_link/<phone_number>', methods=['POST'])
def generate_rsvp_link(phone_number):
    session = g.db_session
    try:
        player = session.query(Player).filter_by(phone=phone_number).first()
        if not player:
            return jsonify({'error': 'Player not found'}), 404

        token = generate_token()
        new_token = Token(player_id=player.id, token=token)
        session.add(new_token)

        rsvp_link = url_for('sms_rsvp.rsvp_page', token=token, _external=True)
        return jsonify({'rsvp_link': rsvp_link})
    except Exception as e:
        logger.error(f"Error generating RSVP link for phone number {phone_number}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to generate RSVP link'}), 500

@sms_rsvp_bp.route('/rsvp/<token>', methods=['GET', 'POST'])
def rsvp_page(token):
    session = g.db_session
    try:
        token_obj = session.query(Token).filter_by(token=token).first()
        if not token_obj or not token_obj.is_valid:
            abort(404)  # Token not found or invalid

        player = session.query(Player).get(token_obj.player_id)
        if not player:
            abort(404)  # Player not found

        matches = get_next_matches(player.team_id, limit=2)

        # Fetch existing RSVP data
        match_ids = [m.id for m in matches]
        existing_rsvps = {
            a.match_id: a.response
            for a in session.query(Availability).filter(
                Availability.player_id == player.id,
                Availability.match_id.in_(match_ids)
            ).all()
        }

        if request.method == 'POST':
            for match in matches:
                response = request.form.get(f'response-{match.id}')
                update_rsvp(match.id, player.id, response, player.discord_id)

            # Invalidate the token after successful RSVP
            token_obj.invalidate()

            return render_template('rsvp_success.html')

        form = FlaskForm()  # This creates a form with just the CSRF token
        return render_template('sms_rsvp_form.html', form=form, player=player, matches=matches, existing_rsvps=existing_rsvps)
    except Exception as e:
        logger.error(f"Error processing RSVP for token {token}: {e}", exc_info=True)
        abort(500)

@sms_rsvp_bp.route('/dev_test_send_rsvp_requests', methods=['GET'])
def dev_test_send_rsvp_requests():
    session = g.db_session
    try:
        opted_in_players = session.query(Player).filter_by(sms_consent_given=True).all()
        results = []
        
        for player in opted_in_players:
            upcoming_matches = get_next_matches(player.team_id, limit=2)

            match_ids = [m.id for m in upcoming_matches]
            existing_rsvps = session.query(Availability).filter(
                Availability.player_id == player.id,
                Availability.match_id.in_(match_ids)
            ).all()

            if len(existing_rsvps) == 2:
                logger.info(f"Player {player.id} has already RSVP'd to both upcoming matches. Skipping SMS.")
                results.append({
                    'player_id': player.id,
                    'phone': player.phone,
                    'success': False,
                    'message': 'Already RSVP\'d to both matches'
                })
                continue

            # Generate RSVP token
            token = secrets.token_urlsafe(24)
            expiration = datetime.utcnow() + timedelta(hours=24)
            new_token = Token(player_id=player.id, token=token, expires_at=expiration)
            session.add(new_token)

            rsvp_link = f"https://ecsfc.com/rsvp/{token}"
            message = f"Please RSVP for your upcoming matches: {rsvp_link}"
            success = send_sms(player.phone, message)

            results.append({
                'player_id': player.id,
                'phone': player.phone,
                'success': success,
                'rsvp_link': rsvp_link,
                'message': 'SMS sent' if success else 'Failed to send SMS'
            })

        return jsonify({'message': 'Test RSVP requests processed', 'results': results})
    except Exception as e:
        logger.error(f"Error sending RSVP requests: {e}", exc_info=True)
        return jsonify({'error': 'Failed to process RSVP requests'}), 500
