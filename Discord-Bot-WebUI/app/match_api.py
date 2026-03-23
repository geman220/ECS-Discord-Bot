# app/match_api.py

"""
Match API Module

API endpoints for managing live reporting sessions.
All actual live event processing is handled by the RealtimeReportingService.
These routes only create/stop/query LiveReportingSession DB records.
"""

import logging
from datetime import datetime
import ipaddress

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required
from flask_wtf.csrf import CSRFProtect

from app.models import MLSMatch
from app.core.session_manager import managed_session
from app.core.helpers import get_match
from app.utils.live_reporting_helpers import create_live_reporting_session, stop_live_reporting_session

# Initialize CSRF protection for the blueprint
csrf = CSRFProtect()

TEAM_ID = '9726'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

match_api = Blueprint('match_api', __name__)
csrf.exempt(match_api)


@match_api.before_request
def limit_remote_addr():
    """
    Restrict API access to allowed hosts and mobile devices.
    """
    allowed_hosts = [
        '127.0.0.1:5000',
        'localhost:5000',
        'webui:5000',
        '192.168.1.112:5000',
        'portal.ecsfc.com',
        '10.0.2.2:5000',
        '192.168.1.0/24',
        '192.168.0.0/24',
    ]

    if request.host in allowed_hosts:
        return

    client_ip = request.host.split(':')[0]
    for allowed in allowed_hosts:
        if '/' in allowed:
            try:
                network = ipaddress.ip_network(allowed)
                if ipaddress.ip_address(client_ip) in network:
                    return
            except (ValueError, ipaddress.AddressValueError):
                continue

    api_key = request.headers.get('X-API-Key')
    if api_key and api_key == current_app.config.get('MOBILE_API_KEY', 'ecs-soccer-mobile-key'):
        return

    logger.warning(f"API access denied for host: {request.host}")
    return "Access Denied", 403


@match_api.route('/schedule_live_reporting', endpoint='schedule_live_reporting_route', methods=['POST'])
@login_required
def schedule_live_reporting_route():
    """
    Schedule live reporting for a match.

    Creates a LiveReportingSession in the DB. The RealtimeReportingService
    picks it up automatically when the match goes live.
    """
    data = request.json
    match_id = data.get('match_id')

    try:
        with managed_session() as session:
            match = get_match(session, match_id)
            if not match:
                logger.error(f"Match {match_id} not found")
                return jsonify({'error': 'Match not found'}), 404

            if match.live_reporting_scheduled:
                logger.warning(f"Live reporting already scheduled for match {match_id}")
                return jsonify({'error': 'Live reporting already scheduled'}), 400

            # Create session — RealtimeReportingService picks it up automatically
            result = create_live_reporting_session(
                session,
                str(match_id),
                str(match.discord_thread_id),
                match.competition or 'usa.1'
            )

            if result.get('success'):
                match.live_reporting_scheduled = True
                session.commit()

            logger.info(f"Live reporting scheduled for match {match_id}")
            return jsonify({'success': True, 'message': 'Live reporting scheduled'})
    except Exception as e:
        logger.error(f"Error scheduling live reporting for match {match_id}: {str(e)}")
        raise


@match_api.route('/start_live_reporting/<match_id>', endpoint='start_live_reporting_route', methods=['POST'])
@login_required
def start_live_reporting_route(match_id):
    """
    Start live reporting for a match immediately.

    Creates a LiveReportingSession in the DB. The RealtimeReportingService
    picks it up within 10-30 seconds.
    """
    try:
        with managed_session() as session:
            match = get_match(session, match_id)
            if not match:
                logger.error(f"Match {match_id} not found")
                return jsonify({'success': False, 'error': 'Match not found'}), 404

            if match.live_reporting_status == 'running':
                logger.warning(f"Live reporting already running for match {match_id}")
                return jsonify({'success': False, 'error': 'Live reporting already running'}), 400

            result = create_live_reporting_session(
                session,
                str(match_id),
                str(match.discord_thread_id),
                match.competition or 'usa.1'
            )

            if not result.get('success'):
                return jsonify({'success': False, 'error': result.get('message')}), 500

            match.live_reporting_status = 'running'
            match.live_reporting_started = True
            session.commit()

            logger.info(f"Live reporting started for match {match_id}")
            return jsonify({
                'success': True,
                'message': 'Live reporting started successfully',
                'session_id': result.get('session_id')
            })
    except Exception as e:
        logger.error(f"Error starting live reporting for match {match_id}: {str(e)}")
        raise


@match_api.route('/stop_live_reporting/<match_id>', endpoint='stop_live_reporting_route', methods=['POST'])
@login_required
def stop_live_reporting_route(match_id):
    """
    Stop live reporting for a match.

    Deactivates the LiveReportingSession. The RealtimeReportingService
    stops processing within 10-30 seconds.
    """
    try:
        with managed_session() as session:
            match = get_match(session, match_id)
            if not match:
                logger.error(f"Match {match_id} not found")
                return jsonify({'success': False, 'error': 'Match not found'}), 404

            if match.live_reporting_status != 'running':
                logger.warning(f"Live reporting is not running for match {match_id}")
                return jsonify({'success': False, 'error': 'Live reporting is not running for this match'}), 400

            stop_live_reporting_session(session, str(match_id))

            match.live_reporting_status = 'stopped'
            match.live_reporting_started = False
            match.live_reporting_task_id = None
            session.commit()

            logger.info(f"Live reporting stopped for match {match_id}")
            return jsonify({'success': True, 'message': 'Live reporting stopped successfully'})
    except Exception as e:
        logger.error(f"Error stopping live reporting for match {match_id}: {str(e)}")
        raise


@match_api.route('/get_match_status/<match_id>', endpoint='get_match_status', methods=['GET'])
def get_match_status(match_id):
    """Retrieve the current live reporting status of a match."""
    try:
        with managed_session() as session:
            match = get_match(session, match_id)
            if not match:
                logger.error(f"Match {match_id} not found")
                return jsonify({'error': 'Match not found'}), 404

            return jsonify({
                'match_id': match.match_id,
                'live_reporting_scheduled': match.live_reporting_scheduled,
                'live_reporting_started': match.live_reporting_started,
                'discord_thread_id': match.discord_thread_id
            })
    except Exception as e:
        logger.error(f"Error retrieving match status for match {match_id}: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@match_api.route('/match/<int:match_id>/channel', endpoint='get_match_channel', methods=['GET'])
def get_match_channel(match_id):
    """Retrieve the Discord channel ID associated with a match."""
    logger.info(f"Fetching channel ID for match {match_id}")
    try:
        with managed_session() as session:
            match = get_match(session, match_id)
            if not match:
                logger.warning(f"No match found with match_id {match_id}")
                return jsonify({'error': 'Match not found'}), 404
            if not match.discord_thread_id:
                logger.warning(f"No discord_thread_id found for match {match_id}")
                return jsonify({'error': 'No channel ID found for this match'}), 404
            return jsonify({'channel_id': match.discord_thread_id})
    except Exception as e:
        logger.error(f"Error fetching channel ID for match {match_id}: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500
