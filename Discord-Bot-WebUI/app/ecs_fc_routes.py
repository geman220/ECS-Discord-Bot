"""
ECS FC Routes Module

This module provides web routes for ECS FC match management, including
match details, RSVP management, sub request system, and integration with the admin system.
"""

import logging
import os
from datetime import datetime
from flask import Blueprint, request, render_template, redirect, url_for, flash, abort, jsonify, g
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.core import db
from app.models import Team, League, Player, User, MatchLineup
from app.models_ecs import EcsFcMatch, EcsFcAvailability
from app.models.ecs_fc import EcsFcPlayerEvent
from app.models.substitutes import (
    EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment, EcsFcSubPool
)
from app.models.matches import TemporarySubAssignment
from app.ecs_fc_schedule import EcsFcScheduleManager, is_user_ecs_fc_coach
from app.decorators import role_required

logger = logging.getLogger(__name__)

# Create blueprint
ecs_fc_routes = Blueprint('ecs_fc', __name__, url_prefix='/ecs-fc')


def check_ecs_fc_access(match_id: int) -> bool:
    """Check if current user has access to ECS FC match."""
    # Global/Pub League admins have access
    if (current_user.has_role('Global Admin') or 
        current_user.has_role('Pub League Admin')):
        return True
    
    # Check if user is ECS FC coach
    if current_user.has_role('ECS FC Coach'):
        match = EcsFcMatch.query.get(match_id)
        if match:
            coached_teams = is_user_ecs_fc_coach(current_user.id)
            return match.team_id in coached_teams
    
    return False


@ecs_fc_routes.route('/matches/<int:match_id>')
@login_required
def match_details(match_id: int):
    """Display ECS FC match details with RSVP information."""
    try:
        # Get the match with related data
        match = EcsFcMatch.query.options(
            joinedload(EcsFcMatch.team).joinedload(Team.players),
            joinedload(EcsFcMatch.availabilities).joinedload(EcsFcAvailability.player)
        ).get_or_404(match_id)
        
        # Check access permissions
        can_manage = check_ecs_fc_access(match_id)
        
        # If user doesn't have management access, check if they're a player on the team
        if not can_manage:
            if current_user.player and current_user.player in match.team.players:
                # Player can view their own team's matches
                pass
            else:
                abort(403)
        
        # Get RSVP summary
        rsvp_summary = match.get_rsvp_summary()
        
        # Build RSVP responses dictionary for easier template access
        rsvp_responses = {}
        for availability in match.availabilities:
            rsvp_responses[availability.player_id] = availability
        
        return render_template(
            'ecs_fc_match_details_flowbite.html',
            match=match,
            rsvp_summary=rsvp_summary,
            rsvp_responses=rsvp_responses,
            can_manage=can_manage
        )
        
    except Exception as e:
        logger.error(f"Error displaying ECS FC match {match_id}: {str(e)}")
        flash('Error loading match details', 'error')
        return redirect(url_for('main.index'))


@ecs_fc_routes.route('/rsvp/<int:match_id>')
@login_required
def rsvp_form(match_id: int):
    """Display RSVP form for ECS FC match."""
    try:
        # Get the match
        match = EcsFcMatch.query.options(
            joinedload(EcsFcMatch.team).joinedload(Team.players)
        ).get_or_404(match_id)
        
        # Check if user is a player on the team
        if not current_user.player or current_user.player not in match.team.players:
            abort(403)
        
        # Get existing RSVP if any
        existing_rsvp = EcsFcAvailability.query.filter_by(
            ecs_fc_match_id=match_id,
            player_id=current_user.player.id
        ).first()
        
        return render_template(
            'ecs_fc_rsvp_form_flowbite.html',
            match=match,
            existing_rsvp=existing_rsvp
        )
        
    except Exception as e:
        logger.error(f"Error displaying ECS FC RSVP form for match {match_id}: {str(e)}")
        flash('Error loading RSVP form', 'error')
        return redirect(url_for('main.index'))


@ecs_fc_routes.route('/rsvp/<int:match_id>', methods=['POST'])
@login_required
def submit_rsvp(match_id: int):
    """Submit RSVP response for ECS FC match."""
    try:
        # Get the match
        match = EcsFcMatch.query.options(
            joinedload(EcsFcMatch.team).joinedload(Team.players)
        ).get_or_404(match_id)
        
        # Check if user is a player on the team
        if not current_user.player or current_user.player not in match.team.players:
            abort(403)
        
        # Get form data
        response = request.form.get('response')
        notes = request.form.get('notes', '').strip()
        
        if response not in ['yes', 'no', 'maybe']:
            flash('Invalid response', 'error')
            return redirect(url_for('ecs_fc.rsvp_form', match_id=match_id))
        
        # Submit RSVP using the schedule manager
        success, message = EcsFcScheduleManager.submit_rsvp(
            match_id=match_id,
            player_id=current_user.player.id,
            response=response,
            user_id=current_user.id,
            discord_id=getattr(current_user, 'discord_id', None),
            notes=notes if notes else None
        )
        
        if success:
            flash('RSVP submitted successfully', 'success')
            return redirect(url_for('ecs_fc.match_details', match_id=match_id))
        else:
            flash(f'Error submitting RSVP: {message}', 'error')
            return redirect(url_for('ecs_fc.rsvp_form', match_id=match_id))
        
    except Exception as e:
        logger.error(f"Error submitting ECS FC RSVP for match {match_id}: {str(e)}")
        flash('Error submitting RSVP', 'error')
        return redirect(url_for('ecs_fc.rsvp_form', match_id=match_id))


# Error handlers
@ecs_fc_routes.errorhandler(403)
def forbidden(error):
    """Handle 403 errors."""
    flash('You do not have permission to access this resource', 'error')
    return redirect(url_for('main.index'))


@ecs_fc_routes.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    flash('The requested ECS FC match was not found', 'error')
    return redirect(url_for('main.index'))


@ecs_fc_routes.route('/report/<int:match_id>', methods=['GET'])
@login_required
def report_match_get(match_id: int):
    """
    Get ECS FC match data for reporting modal.
    Returns JSON data for the match report form.
    """
    session = g.db_session

    try:
        # Get the match with related data
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team).joinedload(Team.players),
            joinedload(EcsFcMatch.events).joinedload(EcsFcPlayerEvent.player)
        ).get(match_id)

        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        # Check access permissions
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        # Build player choices for the team
        team_players = {}
        if match.team and match.team.players:
            for player in match.team.players:
                team_players[str(player.id)] = player.name

        # Get existing events grouped by type
        goals = []
        assists = []
        yellow_cards = []
        red_cards = []
        own_goals = []

        for event in match.events:
            event_data = {
                'id': event.id,
                'player_id': str(event.player_id) if event.player_id else None,
                'player_name': event.player.name if event.player else 'Unknown',
                'minute': event.minute
            }

            if event.event_type == 'goal':
                goals.append(event_data)
            elif event.event_type == 'assist':
                assists.append(event_data)
            elif event.event_type == 'yellow_card':
                yellow_cards.append(event_data)
            elif event.event_type == 'red_card':
                red_cards.append(event_data)
            elif event.event_type == 'own_goal':
                event_data['team_id'] = str(event.team_id) if event.team_id else None
                own_goals.append(event_data)

        # Return match data
        response_data = {
            'success': True,
            'match_id': f'ecs_{match_id}',
            'is_ecs_fc': True,
            'home_team_name': match.team.name if match.team else 'Unknown',
            'away_team_name': match.opponent_name or 'Unknown',
            'home_team_score': match.home_score or 0,
            'away_team_score': match.away_score or 0,
            'notes': match.notes or '',
            'reported': match.status == 'COMPLETED',
            'match_date': match.match_date.strftime('%Y-%m-%d') if match.match_date else None,
            'match_time': match.match_time.strftime('%H:%M') if match.match_time else None,
            'location': match.location,
            'player_choices': {
                match.team.name if match.team else 'Team': team_players
            },
            'goals': goals,
            'assists': assists,
            'yellow_cards': yellow_cards,
            'red_cards': red_cards,
            'own_goals': own_goals,
            'version': 1  # For optimistic locking compatibility
        }

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error fetching ECS FC match data for reporting {match_id}: {str(e)}")
        return jsonify({'success': False, 'message': 'Error loading match data'}), 500


@ecs_fc_routes.route('/report/<int:match_id>', methods=['POST'])
@login_required
def report_match_post(match_id: int):
    """
    Submit ECS FC match report.
    Accepts JSON data with score and events.
    """
    session = g.db_session

    try:
        # Get the match
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team),
            joinedload(EcsFcMatch.events)
        ).get(match_id)

        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        # Check access permissions
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        # Get JSON data
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400

        # Update match score
        home_score = data.get('home_team_score')
        away_score = data.get('away_team_score')
        notes = data.get('notes', '')

        if home_score is not None:
            match.home_score = int(home_score)
        if away_score is not None:
            match.away_score = int(away_score)
        if notes:
            match.notes = notes

        # Mark as completed
        match.status = 'COMPLETED'
        match.updated_at = datetime.utcnow()

        # Process event additions
        user_id = current_user.id

        # Add goals
        for goal in data.get('goals_to_add', []):
            player_id = goal.get('player_id')
            if player_id:
                event = EcsFcPlayerEvent(
                    player_id=int(player_id),
                    ecs_fc_match_id=match_id,
                    event_type='goal',
                    minute=goal.get('minute'),
                    created_by=user_id
                )
                session.add(event)

        # Add assists
        for assist in data.get('assists_to_add', []):
            player_id = assist.get('player_id')
            if player_id:
                event = EcsFcPlayerEvent(
                    player_id=int(player_id),
                    ecs_fc_match_id=match_id,
                    event_type='assist',
                    minute=assist.get('minute'),
                    created_by=user_id
                )
                session.add(event)

        # Add yellow cards
        for card in data.get('yellow_cards_to_add', []):
            player_id = card.get('player_id')
            if player_id:
                event = EcsFcPlayerEvent(
                    player_id=int(player_id),
                    ecs_fc_match_id=match_id,
                    event_type='yellow_card',
                    minute=card.get('minute'),
                    created_by=user_id
                )
                session.add(event)

        # Add red cards
        for card in data.get('red_cards_to_add', []):
            player_id = card.get('player_id')
            if player_id:
                event = EcsFcPlayerEvent(
                    player_id=int(player_id),
                    ecs_fc_match_id=match_id,
                    event_type='red_card',
                    minute=card.get('minute'),
                    created_by=user_id
                )
                session.add(event)

        # Add own goals
        for own_goal in data.get('own_goals_to_add', []):
            team_id = own_goal.get('team_id')
            if team_id:
                event = EcsFcPlayerEvent(
                    team_id=int(team_id),
                    ecs_fc_match_id=match_id,
                    event_type='own_goal',
                    minute=own_goal.get('minute'),
                    created_by=user_id
                )
                session.add(event)

        # Process event removals
        events_to_remove = (
            data.get('goals_to_remove', []) +
            data.get('assists_to_remove', []) +
            data.get('yellow_cards_to_remove', []) +
            data.get('red_cards_to_remove', []) +
            data.get('own_goals_to_remove', [])
        )

        for event_id in events_to_remove:
            if event_id:
                event = session.query(EcsFcPlayerEvent).get(int(event_id))
                if event and event.ecs_fc_match_id == match_id:
                    session.delete(event)

        session.commit()

        logger.info(f"ECS FC match {match_id} reported successfully by user {user_id}")

        return jsonify({
            'success': True,
            'message': 'Match report submitted successfully',
            'home_team_verified': True,
            'away_team_verified': True
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error submitting ECS FC match report {match_id}: {str(e)}")
        return jsonify({'success': False, 'message': f'Error submitting report: {str(e)}'}), 500


# ============================================================================
# Sub Request System Routes
# ============================================================================

@ecs_fc_routes.route('/matches/<int:match_id>/sub-pool-info', methods=['GET'])
@login_required
def get_sub_pool_info(match_id: int):
    """
    Get information about the ECS FC sub pool for filtering.
    Returns counts by gender and position for the preview UI.
    """
    session = g.db_session

    try:
        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        # Check permissions
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        # Get all active sub pool members
        pool_members = session.query(EcsFcSubPool).options(
            joinedload(EcsFcSubPool.player).joinedload(Player.user)
        ).filter(EcsFcSubPool.is_active == True).all()

        # Count by gender (based on pronouns)
        gender_counts = {'male': 0, 'female': 0, 'other': 0}
        position_counts = {'GK': 0, 'DEF': 0, 'MID': 0, 'FWD': 0}

        players_list = []
        for pool_entry in pool_members:
            player = pool_entry.player
            if not player or not player.user or not player.user.is_approved:
                continue

            # Determine gender from pronouns
            pronouns = (player.pronouns or '').lower()
            if 'he' in pronouns:
                gender_counts['male'] += 1
                gender = 'male'
            elif 'she' in pronouns:
                gender_counts['female'] += 1
                gender = 'female'
            else:
                gender_counts['other'] += 1
                gender = 'other'

            # Count positions
            positions = (pool_entry.preferred_positions or '').upper().split(',')
            for pos in positions:
                pos = pos.strip()
                if pos in position_counts:
                    position_counts[pos] += 1

            players_list.append({
                'id': player.id,
                'name': player.name,
                'profile_picture_url': player.profile_picture_url,
                'gender': gender,
                'positions': [p.strip() for p in positions if p.strip()]
            })

        return jsonify({
            'success': True,
            'total_count': len(players_list),
            'gender_counts': gender_counts,
            'position_counts': position_counts,
            'players': players_list
        })

    except Exception as e:
        logger.error(f"Error fetching sub pool info: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@ecs_fc_routes.route('/matches/<int:match_id>/sub-request', methods=['POST'])
@login_required
def create_sub_request(match_id: int):
    """
    Create a sub request and send notifications to eligible subs.
    Coaches can filter by gender, position, or select specific people.
    """
    session = g.db_session

    try:
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team)
        ).get(match_id)

        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        # Check permissions (must be coach of this team)
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400

        # Get filter parameters
        recipient_type = data.get('recipient_type', 'all')  # all, gender, position, specific
        gender_filter = data.get('gender')  # male, female
        position_filters = data.get('positions', [])  # ['GK', 'DEF', ...]
        specific_player_ids = data.get('player_ids', [])
        channels = data.get('channels', ['email', 'discord'])  # sms, email, push, discord
        custom_message = data.get('message', '')
        subs_needed = data.get('subs_needed', 1)

        # Create the sub request record
        sub_request = EcsFcSubRequest(
            match_id=match_id,
            team_id=match.team_id,
            requested_by=current_user.id,
            positions_needed=','.join(position_filters) if position_filters else None,
            notes=custom_message,
            substitutes_needed=subs_needed,
            status='OPEN'
        )
        session.add(sub_request)
        session.flush()

        # Get eligible subs based on filters
        pool_members = session.query(EcsFcSubPool).options(
            joinedload(EcsFcSubPool.player).joinedload(Player.user)
        ).filter(EcsFcSubPool.is_active == True).all()

        eligible_players = []
        for pool_entry in pool_members:
            player = pool_entry.player
            if not player or not player.user or not player.user.is_approved:
                continue

            # Apply filters
            if recipient_type == 'specific':
                if player.id not in specific_player_ids:
                    continue
            elif recipient_type == 'gender' and gender_filter:
                pronouns = (player.pronouns or '').lower()
                if gender_filter == 'male' and 'he' not in pronouns:
                    continue
                if gender_filter == 'female' and 'she' not in pronouns:
                    continue
            elif recipient_type == 'position' and position_filters:
                player_positions = (pool_entry.preferred_positions or '').upper().split(',')
                player_positions = [p.strip() for p in player_positions]
                if not any(p in position_filters for p in player_positions):
                    continue

            eligible_players.append((player, pool_entry))

        if not eligible_players:
            session.rollback()
            return jsonify({
                'success': False,
                'message': 'No eligible subs found matching criteria'
            }), 400

        # Create response records and send notifications
        notifications_sent = 0
        base_url = os.getenv('BASE_URL', 'https://portal.ecsfc.com')

        for player, pool_entry in eligible_players:
            # Create response record
            response = EcsFcSubResponse(
                request_id=sub_request.id,
                player_id=player.id,
                is_available=None,
                notification_sent_at=datetime.utcnow(),
                notification_methods=','.join(channels)
            )
            response.generate_token()
            session.add(response)
            session.flush()

            # Build RSVP URL
            rsvp_url = f"{base_url}/ecs-fc/sub-response/{response.rsvp_token}"

            # Send notifications via enabled channels
            send_result = _send_sub_request_notification(
                player=player,
                pool_entry=pool_entry,
                match=match,
                custom_message=custom_message,
                channels=channels,
                rsvp_url=rsvp_url,
                rsvp_token=response.rsvp_token,
                request_id=sub_request.id
            )

            if send_result:
                notifications_sent += 1
                pool_entry.requests_received = (pool_entry.requests_received or 0) + 1
                pool_entry.last_active_at = datetime.utcnow()

        session.commit()

        logger.info(f"ECS FC sub request {sub_request.id} created by user {current_user.id}, "
                   f"{notifications_sent}/{len(eligible_players)} notifications sent")

        return jsonify({
            'success': True,
            'message': f'Sub request sent to {notifications_sent} subs',
            'request_id': sub_request.id,
            'eligible_count': len(eligible_players),
            'notifications_sent': notifications_sent
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error creating sub request for match {match_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def _send_sub_request_notification(player, pool_entry, match, custom_message, channels, rsvp_url, rsvp_token=None, request_id=None):
    """
    Send sub request notification via enabled channels.
    Returns True if at least one channel succeeded.

    Args:
        player: Player model instance
        pool_entry: EcsFcSubPool entry
        match: EcsFcMatch instance
        custom_message: Custom message from coach
        channels: List of channels to use
        rsvp_url: Web URL for response
        rsvp_token: RSVP token for deep linking (optional)
        request_id: EcsFcSubRequest ID for mobile API (optional)
    """
    sent = False

    # Build message
    match_date = match.match_date.strftime('%A, %B %d') if match.match_date else 'TBD'
    match_time = match.match_time.strftime('%I:%M %p') if match.match_time else 'TBD'

    message = f"""Hi {player.name},

{custom_message}

Match Details:
• Team: {match.team.name}
• Opponent: {match.opponent_name}
• Date: {match_date}
• Time: {match_time}
• Location: {match.location or 'TBD'}

Click here to respond: {rsvp_url}"""

    # Email - send if coach selected email AND player has email
    if 'email' in channels:
        logger.info(f"Attempting email for player {player.id}: user={player.user is not None}, email={player.user.email if player.user else 'no user'}")
        if player.user and player.user.email:
            try:
                from app.email import send_email
                html_body = _build_sub_request_email(player, match, custom_message, rsvp_url)
                result = send_email(
                    player.user.email,
                    f"Sub Request: {match.team.name} vs {match.opponent_name}",
                    html_body
                )
                logger.info(f"Email send result for {player.user.email}: {result}")
                if result:
                    sent = True
                    logger.info(f"Email sent successfully to {player.user.email}")
                else:
                    logger.warning(f"Email send returned False/None for {player.user.email}")
            except Exception as e:
                logger.error(f"Failed to send email to {player.user.email}: {e}", exc_info=True)
        else:
            logger.warning(f"Skipping email for player {player.id}: no user or no email")

    # SMS - ONLY send if player has EXPLICITLY opted in (verified phone AND consent)
    if 'sms' in channels:
        phone = getattr(player, 'phone', None)
        is_verified = getattr(player, 'is_phone_verified', False)
        has_consent = getattr(player, 'sms_consent_given', False)

        if phone and is_verified and has_consent:
            try:
                from app.sms_helpers import send_sms
                first_name = player.name.split()[0] if player.name else "Hi"
                sms_msg = f"{first_name}, sub needed: {match.team.name} vs {match.opponent_name}, {match_date} {match_time}. "
                sms_msg += f"{rsvp_url} "
                sms_msg += f"STOP to opt out"
                success, _ = send_sms(phone, sms_msg[:320])
                if success:
                    sent = True
                    logger.debug(f"SMS sent to player {player.id}")
            except Exception as e:
                logger.error(f"Failed to send SMS: {e}")
        else:
            logger.debug(f"Skipping SMS for player {player.id}: phone={bool(phone)}, verified={is_verified}, consent={has_consent}")

    # Discord DM - send if coach selected discord AND player has discord connected
    if 'discord' in channels:
        logger.info(f"Attempting Discord DM for player {player.id}: discord_id={player.discord_id}")
        if player.discord_id:
            try:
                import requests
                bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
                discord_msg = f"**🙋 Sub Request: {match.team.name}**\n\n"
                if custom_message:
                    discord_msg += f"{custom_message}\n\n"
                discord_msg += f"**Match Details:**\n"
                discord_msg += f"• Opponent: {match.opponent_name}\n"
                discord_msg += f"• Date: {match_date}\n"
                discord_msg += f"• Time: {match_time}\n"
                discord_msg += f"• Location: {match.location or 'TBD'}\n\n"
                discord_msg += f"🔗 [Click here to respond]({rsvp_url})\n\n"
                discord_msg += f"⚠️ *Multiple subs may respond. You'll receive a confirmation if selected - do not show up without confirmation.*"

                response = requests.post(
                    f"{bot_api_url}/send_discord_dm",
                    json={'discord_id': player.discord_id, 'message': discord_msg},
                    timeout=10
                )
                logger.info(f"Discord DM response for {player.discord_id}: status={response.status_code}")
                if response.status_code == 200:
                    sent = True
                    logger.info(f"Discord DM sent successfully to {player.discord_id}")
                else:
                    logger.warning(f"Discord DM failed for {player.discord_id}: {response.text}")
            except Exception as e:
                logger.error(f"Failed to send Discord DM: {e}", exc_info=True)
        else:
            logger.warning(f"Skipping Discord for player {player.id}: no discord_id")

    # Push notification - send if coach selected push AND player has push enabled
    if 'push' in channels:
        if player.user and hasattr(player.user, 'push_notifications') and player.user.push_notifications:
            if hasattr(player.user, 'fcm_tokens') and player.user.fcm_tokens:
                try:
                    from app.services.notification_orchestrator import (
                        orchestrator, NotificationType, NotificationPayload
                    )

                    # Build deep link for mobile app
                    deep_link = f"ecs-fc-scheme://sub-response/{rsvp_token}" if rsvp_token else None

                    push_data = {
                        'type': 'sub_request',
                        'token': rsvp_token,
                        'league_type': 'ecs_fc',
                        'deep_link': deep_link,
                        'web_url': rsvp_url,
                        'match_id': str(match.id)
                    }
                    # Add request_id for mobile API access
                    if request_id:
                        push_data['request_id'] = str(request_id)

                    payload = NotificationPayload(
                        notification_type=NotificationType.SUB_REQUEST,
                        title=f"Sub Request: {match.team.name}",
                        message=f"{match.team.name} vs {match.opponent_name} - {match_date}",
                        user_ids=[player.user.id],
                        data=push_data,
                        force_push=True,
                        force_in_app=False,
                        force_email=False,
                        force_sms=False,
                        force_discord=False
                    )

                    result = orchestrator.send(payload)
                    if result.get('push', {}).get('success'):
                        sent = True
                        logger.info(f"Push notification sent to user {player.user.id}")
                except Exception as e:
                    logger.error(f"Failed to send push notification: {e}", exc_info=True)
            else:
                logger.debug(f"Skipping push for player {player.id}: no FCM tokens")
        else:
            logger.debug(f"Skipping push for player {player.id}: push not enabled")

    logger.info(f"Notification result for player {player.id}: sent={sent}")
    return sent


def _build_sub_request_email(player, match, custom_message, rsvp_url):
    """Build HTML email for sub request."""
    match_date = match.match_date.strftime('%A, %B %d, %Y') if match.match_date else 'TBD'
    match_time = match.match_time.strftime('%I:%M %p') if match.match_time else 'TBD'

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #1a472a 0%, #2d5a3c 100%); color: white; padding: 20px; border-radius: 10px 10px 0 0;">
                <h1 style="margin: 0; font-size: 24px;">🙋 Sub Request</h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">{match.team.name} needs you!</p>
            </div>
            <div style="background: #f8f9fa; padding: 25px; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; margin-top: 0;">Hi {player.name},</p>
                <p>{custom_message}</p>

                <div style="background: white; border-radius: 8px; padding: 20px; margin: 20px 0; border-left: 4px solid #1a472a;">
                    <h3 style="margin: 0 0 15px 0; color: #1a472a;">Match Details</h3>
                    <p style="margin: 5px 0;"><strong>Team:</strong> {match.team.name}</p>
                    <p style="margin: 5px 0;"><strong>Opponent:</strong> {match.opponent_name}</p>
                    <p style="margin: 5px 0;"><strong>Date:</strong> {match_date}</p>
                    <p style="margin: 5px 0;"><strong>Time:</strong> {match_time}</p>
                    <p style="margin: 5px 0;"><strong>Location:</strong> {match.location or 'TBD'}</p>
                </div>

                <div style="text-align: center; margin: 30px 0;">
                    <a href="{rsvp_url}" style="display: inline-block; padding: 15px 40px; background-color: #1a472a; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
                        Respond Now
                    </a>
                </div>

                <div style="background: #fef3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 15px; margin: 20px 0;">
                    <p style="margin: 0; color: #856404; font-size: 14px;">
                        <strong>⚠️ Important:</strong> Multiple subs may respond to this request. You will receive a separate confirmation message if you are selected. <strong>Please do not show up unless you receive confirmation.</strong>
                    </p>
                </div>

                <p style="color: #666; font-size: 14px; text-align: center;">
                    This link expires in 48 hours.
                </p>
            </div>
            <p style="color: #999; font-size: 12px; text-align: center; margin-top: 20px;">
                ECS Soccer League • <a href="https://weareecs.com" style="color: #1a472a;">weareecs.com</a>
            </p>
        </div>
    </body>
    </html>
    """


# ============================================================================
# Sub Response Routes
# ============================================================================

@ecs_fc_routes.route('/sub-response/<token>')
@login_required
def sub_response_page(token: str):
    """
    Display the sub response page for the given token.
    Login required to verify the user matches the token recipient.
    """
    session = g.db_session

    try:
        # Find the response by token
        response = session.query(EcsFcSubResponse).options(
            joinedload(EcsFcSubResponse.request).joinedload(EcsFcSubRequest.match).joinedload(EcsFcMatch.team),
            joinedload(EcsFcSubResponse.player)
        ).filter(EcsFcSubResponse.rsvp_token == token).first()

        if not response:
            return render_template('ecs_fc_sub_response_flowbite.html',
                                 error='Invalid or expired token',
                                 token_valid=False)

        # Verify the logged-in user matches the token recipient
        user_player = session.query(Player).filter_by(user_id=current_user.id).first()
        if not user_player or user_player.id != response.player_id:
            return render_template('ecs_fc_sub_response_flowbite.html',
                                 error='This link was sent to a different user. Please sign in with the correct account.',
                                 token_valid=False)

        # Check if token is valid
        if not response.is_token_valid():
            already_responded = response.token_used_at is not None
            return render_template('ecs_fc_sub_response_flowbite.html',
                                 error='Token expired' if not already_responded else None,
                                 token_valid=False,
                                 already_responded=already_responded,
                                 previous_response=response.is_available,
                                 response=response)

        # Get match details
        sub_request = response.request
        match = sub_request.match

        return render_template('ecs_fc_sub_response_flowbite.html',
                             token_valid=True,
                             token=token,
                             response=response,
                             match=match,
                             team=match.team,
                             player=response.player,
                             coach_note=sub_request.notes)

    except Exception as e:
        logger.error(f"Error loading sub response page for token {token}: {e}")
        return render_template('ecs_fc_sub_response_flowbite.html',
                             error='An error occurred',
                             token_valid=False)


@ecs_fc_routes.route('/sub-response/<token>', methods=['POST'])
@login_required
def submit_sub_response(token: str):
    """
    Submit a sub response (accept or decline).
    Login required to verify the user matches the token recipient.
    """
    session = g.db_session

    try:
        response = session.query(EcsFcSubResponse).options(
            joinedload(EcsFcSubResponse.request).joinedload(EcsFcSubRequest.match),
            joinedload(EcsFcSubResponse.player)
        ).filter(EcsFcSubResponse.rsvp_token == token).first()

        if not response:
            flash('Invalid or expired token', 'error')
            return redirect(url_for('ecs_fc.sub_response_page', token=token))

        # Verify the logged-in user matches the token recipient
        user_player = session.query(Player).filter_by(user_id=current_user.id).first()
        if not user_player or user_player.id != response.player_id:
            flash('This link was sent to a different user', 'error')
            return redirect(url_for('ecs_fc.sub_response_page', token=token))

        if not response.is_token_valid():
            flash('This link has expired', 'error')
            return redirect(url_for('ecs_fc.sub_response_page', token=token))

        # Get response from form
        is_available = request.form.get('response') == 'accept'
        response_text = request.form.get('notes', '').strip()

        # Update response
        response.is_available = is_available
        response.responded_at = datetime.utcnow()
        response.response_method = 'web'
        response.response_text = response_text
        response.mark_token_used()

        # Update pool entry stats
        pool_entry = session.query(EcsFcSubPool).filter_by(
            player_id=response.player_id
        ).first()
        if pool_entry and is_available:
            pool_entry.requests_accepted = (pool_entry.requests_accepted or 0) + 1

        session.commit()

        flash('Response submitted successfully!', 'success')
        return redirect(url_for('ecs_fc.sub_response_page', token=token))

    except Exception as e:
        session.rollback()
        logger.error(f"Error submitting sub response for token {token}: {e}")
        flash('An error occurred. Please try again.', 'error')
        return redirect(url_for('ecs_fc.sub_response_page', token=token))


# ============================================================================
# Coach Assignment Routes
# ============================================================================

@ecs_fc_routes.route('/matches/<int:match_id>/sub-responses', methods=['GET'])
@login_required
def get_sub_responses(match_id: int):
    """
    Get all sub responses for a match (for coaches).
    """
    session = g.db_session

    try:
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        # Get all requests for this match
        requests = session.query(EcsFcSubRequest).options(
            joinedload(EcsFcSubRequest.responses).joinedload(EcsFcSubResponse.player)
        ).filter(EcsFcSubRequest.match_id == match_id).all()

        # Build response data
        accepted = []
        declined = []
        pending = []
        assigned = []

        for sub_req in requests:
            # Check for existing assignments
            assignments = session.query(EcsFcSubAssignment).filter(
                EcsFcSubAssignment.request_id == sub_req.id
            ).all()
            assigned_player_ids = [a.player_id for a in assignments]

            for resp in sub_req.responses:
                player = resp.player
                player_data = {
                    'id': player.id,
                    'name': player.name,
                    'profile_picture_url': player.profile_picture_url,
                    'positions': [],
                    'responded_at': resp.responded_at.isoformat() if resp.responded_at else None,
                    'response_text': resp.response_text,
                    'request_id': sub_req.id
                }

                # Get positions from pool entry
                pool_entry = session.query(EcsFcSubPool).filter_by(
                    player_id=player.id
                ).first()
                if pool_entry and pool_entry.preferred_positions:
                    player_data['positions'] = [p.strip() for p in pool_entry.preferred_positions.split(',')]

                if player.id in assigned_player_ids:
                    assigned.append(player_data)
                elif resp.is_available is True:
                    accepted.append(player_data)
                elif resp.is_available is False:
                    declined.append(player_data)
                else:
                    player_data['notification_sent_at'] = resp.notification_sent_at.isoformat() if resp.notification_sent_at else None
                    pending.append(player_data)

        # Calculate totals across all requests
        total_needed = sum(r.substitutes_needed or 1 for r in requests)
        total_assigned = len(assigned)

        return jsonify({
            'success': True,
            'accepted': accepted,
            'declined': declined,
            'pending': pending,
            'assigned': assigned,
            'substitutes_needed': total_needed,
            'substitutes_assigned': total_assigned,
            'all_slots_filled': total_assigned >= total_needed
        })

    except Exception as e:
        logger.error(f"Error fetching sub responses for match {match_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@ecs_fc_routes.route('/matches/<int:match_id>/assign-sub', methods=['POST'])
@login_required
def assign_sub(match_id: int):
    """
    Assign a sub to the match.
    Creates EcsFcSubAssignment and TemporarySubAssignment records.
    """
    session = g.db_session

    try:
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        data = request.get_json()
        player_id = data.get('player_id')
        request_id = data.get('request_id')
        position = data.get('position')
        notes = data.get('notes', '')

        if not player_id or not request_id:
            return jsonify({'success': False, 'message': 'Missing player_id or request_id'}), 400

        # Verify the response exists and player accepted
        response = session.query(EcsFcSubResponse).filter_by(
            request_id=request_id,
            player_id=player_id
        ).first()

        if not response:
            return jsonify({'success': False, 'message': 'No response found for this player'}), 404

        if response.is_available is not True:
            return jsonify({'success': False, 'message': 'Player has not accepted the request'}), 400

        # Check if already assigned
        existing = session.query(EcsFcSubAssignment).filter_by(
            request_id=request_id,
            player_id=player_id
        ).first()
        if existing:
            return jsonify({'success': False, 'message': 'Player already assigned'}), 400

        # Get the sub request
        sub_request = session.query(EcsFcSubRequest).get(request_id)

        # Create EcsFcSubAssignment
        assignment = EcsFcSubAssignment(
            request_id=request_id,
            player_id=player_id,
            assigned_by=current_user.id,
            position_assigned=position,
            notes=notes,
            outreach_methods=response.notification_methods
        )
        session.add(assignment)

        # Create TemporarySubAssignment (makes sub appear on team for this match)
        # Note: For ECS FC matches, we create a special temp assignment
        # We don't have a regular Match object, so we use a convention
        temp_assignment = TemporarySubAssignment(
            match_id=-match_id,  # Negative ID convention for ECS FC matches
            player_id=player_id,
            team_id=match.team_id,
            assigned_by=current_user.id,
            notes=f"ECS FC sub for match {match_id}"
        )
        session.add(temp_assignment)

        # Send confirmation notification
        player = session.query(Player).options(
            joinedload(Player.user)
        ).get(player_id)

        _send_assignment_confirmation(player, match, assignment, response.notification_methods)

        assignment.notification_sent = True
        assignment.notification_sent_at = datetime.utcnow()

        session.commit()

        logger.info(f"Sub {player_id} assigned to ECS FC match {match_id} by user {current_user.id}")

        return jsonify({
            'success': True,
            'message': f'{player.name} has been assigned and notified',
            'assignment_id': assignment.id
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error assigning sub to match {match_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@ecs_fc_routes.route('/matches/<int:match_id>/unassign-sub/<int:player_id>', methods=['POST'])
@login_required
def unassign_sub(match_id: int, player_id: int):
    """
    Remove a sub assignment from a match.
    """
    session = g.db_session

    try:
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        # Find and delete the assignment
        assignment = session.query(EcsFcSubAssignment).join(
            EcsFcSubRequest
        ).filter(
            EcsFcSubRequest.match_id == match_id,
            EcsFcSubAssignment.player_id == player_id
        ).first()

        if not assignment:
            return jsonify({'success': False, 'message': 'Assignment not found'}), 404

        # Delete TemporarySubAssignment
        temp_assignment = session.query(TemporarySubAssignment).filter_by(
            match_id=-match_id,
            player_id=player_id
        ).first()
        if temp_assignment:
            session.delete(temp_assignment)

        session.delete(assignment)
        session.commit()

        logger.info(f"Sub {player_id} unassigned from ECS FC match {match_id}")

        return jsonify({
            'success': True,
            'message': 'Sub has been removed from the match'
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error unassigning sub from match {match_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def _send_assignment_confirmation(player, match, assignment, channels_str):
    """Send confirmation notification to assigned sub."""
    # Normalize channels to lowercase for comparison
    channels = [c.strip().lower() for c in (channels_str or '').split(',')]
    match_date = match.match_date.strftime('%A, %B %d') if match.match_date else 'TBD'
    match_time = match.match_time.strftime('%I:%M %p') if match.match_time else 'TBD'

    # Email
    if 'email' in channels and player.user and player.user.email:
        try:
            from app.email import send_email
            html_body = f"""
            <html>
            <body style="font-family: -apple-system, sans-serif; line-height: 1.6;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <div style="background: #1a472a; color: white; padding: 20px; border-radius: 10px 10px 0 0;">
                        <h1 style="margin: 0;">✅ You're Confirmed!</h1>
                    </div>
                    <div style="background: #f8f9fa; padding: 25px; border-radius: 0 0 10px 10px;">
                        <p>Hi {player.name},</p>
                        <p>You've been confirmed as a substitute for <strong>{match.team.name}</strong>.</p>
                        <div style="background: white; padding: 15px; border-radius: 8px; margin: 15px 0;">
                            <p><strong>Opponent:</strong> {match.opponent_name}</p>
                            <p><strong>Date:</strong> {match_date}</p>
                            <p><strong>Time:</strong> {match_time}</p>
                            <p><strong>Location:</strong> {match.location or 'TBD'}</p>
                            {f'<p><strong>Position:</strong> {assignment.position_assigned}</p>' if assignment.position_assigned else ''}
                        </div>
                        <p><strong>Please arrive 15 minutes before kickoff.</strong> Thanks for stepping up!</p>
                    </div>
                </div>
            </body>
            </html>
            """
            send_email(player.user.email, f"CONFIRMED: You're subbing for {match.team.name}", html_body)
        except Exception as e:
            logger.error(f"Failed to send confirmation email: {e}")

    # SMS - Important! This confirms they should actually show up
    # Only send if player has verified phone AND consent
    if 'sms' in channels:
        phone = getattr(player, 'phone', None)
        is_verified = getattr(player, 'is_phone_verified', False)
        has_consent = getattr(player, 'sms_consent_given', False)

        if phone and is_verified and has_consent:
            try:
                from app.sms_helpers import send_sms
                first_name = player.name.split()[0] if player.name else "Hey"
                sms_msg = f"{first_name}, confirmed! {match.team.name} vs {match.opponent_name}, "
                sms_msg += f"{match_date} {match_time}. "
                sms_msg += f"{match.location or 'TBD'}. Arrive 15min early."
                success, _ = send_sms(phone, sms_msg[:320])
                if success:
                    logger.debug(f"Confirmation SMS sent to player {player.id}")
            except Exception as e:
                logger.error(f"Failed to send confirmation SMS: {e}")

    # Discord
    if 'discord' in channels and player.discord_id:
        try:
            import requests
            bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
            discord_msg = f"✅ **You're Confirmed!**\n\n"
            discord_msg += f"You've been confirmed as a substitute for **{match.team.name}**.\n\n"
            discord_msg += f"**Match Details:**\n"
            discord_msg += f"• Opponent: {match.opponent_name}\n"
            discord_msg += f"• Date: {match_date}\n"
            discord_msg += f"• Time: {match_time}\n"
            discord_msg += f"• Location: {match.location or 'TBD'}\n"
            if assignment.position_assigned:
                discord_msg += f"• Position: {assignment.position_assigned}\n"
            discord_msg += f"\n**Please arrive 15 minutes before kickoff.** Thanks for stepping up!"

            requests.post(
                f"{bot_api_url}/send_discord_dm",
                json={'discord_id': player.discord_id, 'message': discord_msg},
                timeout=10
            )
        except Exception as e:
            logger.error(f"Failed to send confirmation Discord DM: {e}")


# ============================================================================
# ECS FC Lineup Picker Routes
# ============================================================================

@ecs_fc_routes.route('/matches/<int:match_id>/lineup')
@login_required
def lineup_picker(match_id: int):
    """
    Display the lineup picker for an ECS FC match.
    """
    session = g.db_session

    try:
        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team).joinedload(Team.players),
            joinedload(EcsFcMatch.availabilities).joinedload(EcsFcAvailability.player)
        ).get_or_404(match_id)

        # Check permissions
        can_manage = check_ecs_fc_access(match_id)
        if not can_manage:
            abort(403)

        team = match.team

        # Build RSVP map
        rsvp_map = {}
        for avail in match.availabilities:
            rsvp_map[avail.player_id] = avail.response

        # Build roster with RSVP status
        roster = []
        for player in team.players:
            rsvp_status = rsvp_map.get(player.id, 'unavailable')
            rsvp_color = {
                'yes': 'green',
                'maybe': 'yellow',
                'no': 'red'
            }.get(rsvp_status, 'gray')

            roster.append({
                'player_id': player.id,
                'name': player.name,
                'profile_picture_url': player.profile_picture_url or '/static/img/default_player.png',
                'favorite_position': player.favorite_position,
                'other_positions': player.other_positions,
                'rsvp_status': rsvp_status,
                'rsvp_color': rsvp_color,
                'is_sub': False,
                'stats': {
                    'goals': 0,
                    'assists': 0
                }
            })

        # Add assigned subs to roster
        temp_assignments = session.query(TemporarySubAssignment).options(
            joinedload(TemporarySubAssignment.player)
        ).filter(
            TemporarySubAssignment.match_id == -match_id,
            TemporarySubAssignment.is_active == True
        ).all()

        for temp in temp_assignments:
            roster.append({
                'player_id': temp.player.id,
                'name': temp.player.name,
                'profile_picture_url': temp.player.profile_picture_url or '/static/img/default_player.png',
                'favorite_position': temp.player.favorite_position,
                'other_positions': temp.player.other_positions,
                'rsvp_status': 'yes',  # Assigned subs are confirmed
                'rsvp_color': 'green',
                'is_sub': True,
                'stats': {
                    'goals': 0,
                    'assists': 0
                }
            })

        # Get existing lineup
        lineup = session.query(MatchLineup).filter_by(
            match_id=-match_id,  # Negative ID for ECS FC
            team_id=team.id
        ).first()

        lineup_data = {
            'positions': lineup.positions if lineup else [],
            'notes': lineup.notes if lineup else '',
            'version': lineup.version if lineup else 1
        }

        return render_template(
            'ecs_fc_lineup_flowbite.html',
            match=match,
            team=team,
            roster=roster,
            lineup=lineup_data,
            is_coach=can_manage
        )

    except Exception as e:
        logger.error(f"Error loading ECS FC lineup picker for match {match_id}: {e}")
        flash('Error loading lineup picker', 'error')
        return redirect(url_for('ecs_fc.match_details', match_id=match_id))


@ecs_fc_routes.route('/matches/<int:match_id>/lineup-data', methods=['GET'])
@login_required
def get_lineup_data(match_id: int):
    """
    Get lineup data for an ECS FC match (web authenticated).
    """
    session = g.db_session

    try:
        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        # Get lineup using negative match_id convention
        lineup = session.query(MatchLineup).filter_by(
            match_id=-match_id,
            team_id=match.team_id
        ).first()

        return jsonify({
            'success': True,
            'lineup': {
                'id': lineup.id if lineup else None,
                'positions': lineup.positions if lineup else [],
                'notes': lineup.notes if lineup else '',
                'version': lineup.version if lineup else 1
            }
        })

    except Exception as e:
        logger.error(f"Error fetching lineup for match {match_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@ecs_fc_routes.route('/matches/<int:match_id>/lineup-data', methods=['PUT'])
@login_required
def save_lineup_data(match_id: int):
    """
    Save lineup data for an ECS FC match (web authenticated).
    """
    session = g.db_session

    try:
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        data = request.get_json()
        positions = data.get('positions', [])
        notes = data.get('notes')
        version = data.get('version')

        # Get or create lineup
        lineup = session.query(MatchLineup).filter_by(
            match_id=-match_id,
            team_id=match.team_id
        ).first()

        # Optimistic locking
        if lineup and version is not None and lineup.version != version:
            return jsonify({
                'success': False,
                'message': 'Lineup was modified by another coach. Please refresh.',
                'current_version': lineup.version,
                'conflict': True
            }), 409

        if not lineup:
            lineup = MatchLineup(
                match_id=-match_id,
                team_id=match.team_id,
                positions=positions,
                notes=notes,
                created_by=current_user.id
            )
            session.add(lineup)
        else:
            lineup.positions = positions
            if notes is not None:
                lineup.notes = notes
            lineup.last_updated_by = current_user.id
            lineup.increment_version()

        session.commit()

        return jsonify({
            'success': True,
            'version': lineup.version,
            'positions': lineup.positions
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error saving lineup for match {match_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@ecs_fc_routes.route('/matches/<int:match_id>/lineup-position', methods=['PATCH'])
@login_required
def update_lineup_position(match_id: int):
    """
    Update a single player's position in the lineup.
    """
    session = g.db_session

    try:
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        data = request.get_json()
        player_id = data.get('player_id')
        position = data.get('position', 'bench')

        if not player_id:
            return jsonify({'success': False, 'message': 'Missing player_id'}), 400

        # Get or create lineup
        lineup = session.query(MatchLineup).filter_by(
            match_id=-match_id,
            team_id=match.team_id
        ).first()

        if not lineup:
            lineup = MatchLineup(
                match_id=-match_id,
                team_id=match.team_id,
                positions=[],
                created_by=current_user.id
            )
            session.add(lineup)
            session.flush()

        # Update the position
        lineup.add_player(player_id, position)
        lineup.last_updated_by = current_user.id
        lineup.increment_version()

        session.commit()

        return jsonify({
            'success': True,
            'version': lineup.version,
            'player_id': player_id,
            'position': position
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error updating position for match {match_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@ecs_fc_routes.route('/matches/<int:match_id>/lineup-position/<int:player_id>', methods=['DELETE'])
@login_required
def remove_from_lineup(match_id: int, player_id: int):
    """
    Remove a player from the lineup.
    """
    session = g.db_session

    try:
        if not check_ecs_fc_access(match_id):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        match = session.query(EcsFcMatch).get(match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        # Get lineup
        lineup = session.query(MatchLineup).filter_by(
            match_id=-match_id,
            team_id=match.team_id
        ).first()

        if not lineup:
            return jsonify({'success': False, 'message': 'No lineup exists'}), 404

        # Remove the player
        lineup.remove_player(player_id)
        lineup.last_updated_by = current_user.id
        lineup.increment_version()

        session.commit()

        return jsonify({
            'success': True,
            'version': lineup.version
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error removing player from lineup for match {match_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500