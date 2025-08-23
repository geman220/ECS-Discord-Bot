# app/test_live_reporting.py

"""
Test Live Reporting Module

This module provides test endpoints to trigger live reporting for any ESPN match.
Useful for debugging and testing without waiting for specific team matches.
"""

import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required
from app import csrf  # Import CSRF protection from main app
from app.decorators import role_required
from app.core.session_manager import managed_session
from app.models import MLSMatch
from app.tasks.tasks_live_reporting import start_live_reporting
from app.tasks.tasks_robust_live_reporting import start_robust_live_reporting, stop_robust_live_reporting
try:
    from app.tasks.tasks_live_reporting_v2 import start_live_reporting_v2, stop_live_reporting_v2, process_all_active_sessions_v2
    V2_AVAILABLE = True
except ImportError:
    V2_AVAILABLE = False
    start_live_reporting_v2 = None
    stop_live_reporting_v2 = None
    process_all_active_sessions_v2 = None
from app.models import LiveReportingSession
import asyncio

logger = logging.getLogger(__name__)

# Log V2 availability after logger is defined
if V2_AVAILABLE:
    logger.info("✅ Live Reporting V2 system is AVAILABLE and will be used for all operations")
else:
    logger.warning("⚠️  Live Reporting V2 system NOT AVAILABLE - falling back to Robust system")

test_live_reporting_bp = Blueprint('test_live_reporting', __name__, url_prefix='/test')


@test_live_reporting_bp.route('/live-reporting', methods=['GET', 'POST'])
@csrf.exempt
@login_required
@role_required(['Global Admin'])
def test_live_reporting():
    """
    Test page for triggering live reporting on any match.
    GET: Display the test form
    POST: Trigger live reporting for the specified match
    """
    if request.method == 'GET':
        return render_template('test_live_reporting.html')
    
    # POST request - trigger live reporting
    data = request.json if request.is_json else request.form
    
    match_id = data.get('match_id')
    competition = data.get('competition', 'usa.1')  # Default to MLS
    team_id = data.get('team_id', '9726')  # Default to Sounders
    thread_id = data.get('thread_id')  # Optional Discord thread ID
    
    if not match_id:
        return jsonify({'error': 'match_id is required'}), 400
    
    try:
        with managed_session() as session:
            # Check if match already exists
            match = session.query(MLSMatch).filter_by(match_id=match_id).first()
            
            if not match:
                # Create a test match entry
                match = MLSMatch(
                    match_id=match_id,
                    competition=competition,
                    opponent='Test Opponent',
                    date_time=datetime.utcnow() + timedelta(minutes=5),  # Set to 5 minutes from now
                    is_home_game=True,
                    venue='Test Venue',
                    discord_thread_id=thread_id,
                    thread_created=bool(thread_id),
                    live_reporting_scheduled=False,
                    live_reporting_started=False,
                    live_reporting_status='idle'
                )
                session.add(match)
                session.commit()
                logger.info(f"Created test match entry for {match_id}")
            else:
                # Update existing match with thread ID if provided
                if thread_id and not match.discord_thread_id:
                    match.discord_thread_id = thread_id
                    match.thread_created = True
                    session.commit()
                    logger.info(f"Updated match {match_id} with thread ID {thread_id}")
            
            # Trigger live reporting
            result = start_live_reporting.delay(str(match_id))
            
            return jsonify({
                'success': True,
                'message': f'Live reporting triggered for match {match_id}',
                'task_id': result.id,
                'match_data': {
                    'match_id': match.match_id,
                    'competition': match.competition,
                    'opponent': match.opponent,
                    'is_home_game': match.is_home_game,
                    'thread_id': match.discord_thread_id,
                    'status': match.live_reporting_status
                }
            })
            
    except Exception as e:
        logger.error(f"Error triggering test live reporting: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@test_live_reporting_bp.route('/start-robust-live-reporting/<match_id>', methods=['POST'])
@csrf.exempt
def start_robust_live_reporting_route(match_id):
    """Start robust live reporting for a test match. Auto-creates match record if needed."""
    try:
        # Safely get JSON data or use empty dict
        try:
            data = request.get_json() or {}
        except Exception:
            data = {}
        
        competition = data.get('competition', 'usa.1')
        thread_id = data.get('thread_id', None)
        
        with managed_session() as session:
            # Check if match exists
            match = session.query(MLSMatch).filter_by(match_id=str(match_id)).first()
            
            # Get thread ID from request or existing match
            if thread_id:
                final_thread_id = thread_id
            elif match and match.discord_thread_id:
                final_thread_id = match.discord_thread_id
            else:
                return jsonify({
                    'error': f'No Discord thread ID provided. Please provide thread_id in request.'
                }), 400
            
            # Use V2 live reporting system (enterprise-grade with async architecture)
            if V2_AVAILABLE:
                logger.info(f"🚀 Starting V2 live reporting for match {match_id} in thread {final_thread_id}")
                result = start_live_reporting_v2.delay(
                    str(match_id), 
                    str(final_thread_id), 
                    competition
                )
                reporting_type = "V2 Enterprise System"
            else:
                logger.warning(f"⚠️  V2 not available, falling back to Robust system for match {match_id} in thread {final_thread_id}")
                result = start_robust_live_reporting.delay(
                    str(match_id), 
                    str(final_thread_id), 
                    competition
                )
                reporting_type = "Robust (V2 fallback)"
            
            # Update match status if it exists
            if match:
                match.live_reporting_status = 'running'
                session.add(match)
                session.commit()
            
            return jsonify({
                'success': True,
                'message': f'{reporting_type} live reporting started for match {match_id}',
                'task_id': result.id,
                'match_data': {
                    'match_id': match_id,
                    'competition': competition,
                    'thread_id': final_thread_id,
                    'status': 'running'
                }
            })
            
    except Exception as e:
        logger.error(f"Error starting robust live reporting: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@test_live_reporting_bp.route('/stop-robust-live-reporting/<match_id>', methods=['POST'])
@csrf.exempt
def stop_robust_live_reporting_route(match_id):
    """Stop robust live reporting for a test match."""
    try:
        with managed_session() as session:
            # Find match in database
            match = session.query(MLSMatch).filter_by(match_id=str(match_id)).first()
            
            if not match:
                return jsonify({
                    'error': f'Match {match_id} not found in database.'
                }), 404
            
            # Stop V2 live reporting if available, otherwise use robust
            if V2_AVAILABLE:
                logger.info(f"🛑 Stopping V2 live reporting for match {match_id}")
                result = stop_live_reporting_v2.delay(str(match_id))
                reporting_type = "V2 Enterprise System"
            else:
                logger.warning(f"⚠️  V2 not available, using Robust system to stop match {match_id}")
                result = stop_robust_live_reporting.delay(str(match_id), "Manual stop via test interface")
                reporting_type = "Robust (V2 fallback)"
            
            # Update match status
            match.live_reporting_status = 'stopped'
            session.add(match)
            session.commit()
            
            return jsonify({
                'success': True,
                'message': f'{reporting_type} live reporting stopped for match {match_id}',
                'task_id': result.id
            })
            
    except Exception as e:
        logger.error(f"Error stopping robust live reporting: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@test_live_reporting_bp.route('/live-sessions', methods=['GET'])
@csrf.exempt
def get_live_sessions():
    """Get all active live reporting sessions."""
    try:
        with managed_session() as session:
            active_sessions = LiveReportingSession.get_active_sessions(session)
            
            sessions_data = []
            for session_obj in active_sessions:
                sessions_data.append(session_obj.to_dict())
            
            return jsonify({
                'success': True,
                'active_sessions': sessions_data,
                'count': len(sessions_data)
            })
            
    except Exception as e:
        logger.error(f"Error getting live sessions: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@test_live_reporting_bp.route('/fetch-espn/<match_id>', methods=['GET', 'POST'])
@csrf.exempt
@login_required
@role_required(['Global Admin'])
def test_fetch_espn(match_id):
    """
    Test fetching ESPN data for a specific match.
    GET: Fetch and display ESPN data
    POST: Fetch ESPN data and create match record in database
    """
    competition = request.args.get('competition', 'usa.1') if request.method == 'GET' else request.json.get('competition', 'usa.1')
    thread_id = request.json.get('thread_id') if request.method == 'POST' else None
    
    try:
        # Import the ESPN service
        from app.services.espn_service import get_espn_service
        from app.api_utils import async_to_sync
        
        espn_service = get_espn_service()
        
        # Fetch match data
        match_data = async_to_sync(espn_service.get_match_data(match_id, competition))
        
        if not match_data:
            return jsonify({'error': 'Failed to fetch match data from ESPN'}), 404
        
        # Extract key information
        competition_data = match_data.get('competitions', [{}])[0]
        status = competition_data.get('status', {})
        competitors = competition_data.get('competitors', [])
        venue = competition_data.get('venue', {})
        date_str = match_data.get('date', '')
        
        home_team = competitors[0] if len(competitors) > 0 else {}
        away_team = competitors[1] if len(competitors) > 1 else {}
        
        # Parse date
        match_date = None
        if date_str:
            try:
                match_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except:
                match_date = datetime.utcnow()
        
        result = {
            'success': True,
            'match_id': match_id,
            'competition': competition,
            'status': status.get('type', {}).get('name', 'Unknown'),
            'home_team': {
                'name': home_team.get('team', {}).get('displayName', 'Unknown'),
                'score': home_team.get('score', '0')
            },
            'away_team': {
                'name': away_team.get('team', {}).get('displayName', 'Unknown'),
                'score': away_team.get('score', '0')
            },
            'events': len(competition_data.get('details', [])),
            'raw_data': match_data  # Include full data for debugging
        }
        
        # If POST request, create match record
        if request.method == 'POST':
            with managed_session() as session:
                # Check if match already exists
                match = session.query(MLSMatch).filter_by(match_id=match_id).first()
                
                if not match:
                    # Create match record
                    match = MLSMatch(
                        match_id=match_id,
                        competition=competition,
                        opponent=f"{home_team.get('team', {}).get('displayName', 'Unknown')} vs {away_team.get('team', {}).get('displayName', 'Unknown')}",
                        date_time=match_date or datetime.utcnow(),
                        is_home_game=False,  # Not a Sounders match
                        venue=venue.get('fullName', 'Unknown Venue'),
                        discord_thread_id=thread_id,
                        thread_created=bool(thread_id),
                        live_reporting_scheduled=False,
                        live_reporting_started=False,
                        live_reporting_status='idle'
                    )
                    session.add(match)
                    session.commit()
                    result['message'] = f'Match record created for {match_id}'
                    result['match_created'] = True
                else:
                    # Update thread ID if provided
                    if thread_id and not match.discord_thread_id:
                        match.discord_thread_id = thread_id
                        match.thread_created = True
                        session.commit()
                        result['message'] = f'Match record updated with thread ID'
                    else:
                        result['message'] = f'Match record already exists for {match_id}'
                    result['match_created'] = False
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error fetching ESPN data: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@test_live_reporting_bp.route('/process-single-update/<match_id>', methods=['POST'])
@csrf.exempt
@login_required
@role_required(['Global Admin'])
def test_process_single_update(match_id):
    """
    Trigger a single update cycle for a match (useful for debugging).
    """
    data = request.json if request.is_json else request.form
    thread_id = data.get('thread_id')
    competition = data.get('competition', 'usa.1')
    
    if not thread_id:
        return jsonify({'error': 'thread_id is required'}), 400
    
    try:
        # Trigger a single update
        result = process_match_update.delay(
            match_id=str(match_id),
            thread_id=str(thread_id),
            competition=competition,
            last_status=None,
            last_score=None,
            last_event_keys=[],
            task_id=None
        )
        
        return jsonify({
            'success': True,
            'message': f'Single update triggered for match {match_id}',
            'task_id': result.id
        })
        
    except Exception as e:
        logger.error(f"Error triggering single update: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@test_live_reporting_bp.route('/stop/<match_id>', methods=['POST'])
@csrf.exempt
@login_required
@role_required(['Global Admin'])
def stop_live_reporting(match_id):
    """
    Stop live reporting for a match.
    """
    try:
        with managed_session() as session:
            match = session.query(MLSMatch).filter_by(match_id=match_id).first()
            
            if not match:
                return jsonify({'error': 'Match not found'}), 404
            
            # Update match status
            match.live_reporting_status = 'stopped'
            match.live_reporting_started = False
            match.live_reporting_task_id = None
            session.commit()
            
            return jsonify({
                'success': True,
                'message': f'Live reporting stopped for match {match_id}'
            })
            
    except Exception as e:
        logger.error(f"Error stopping live reporting: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@test_live_reporting_bp.route('/status/<match_id>', methods=['GET'])
@csrf.exempt
@login_required
@role_required(['Global Admin'])
def get_reporting_status(match_id):
    """
    Get the current status of live reporting for a match.
    """
    try:
        with managed_session() as session:
            match = session.query(MLSMatch).filter_by(match_id=match_id).first()
            
            if not match:
                return jsonify({'error': 'Match not found'}), 404
            
            return jsonify({
                'match_id': match.match_id,
                'competition': match.competition,
                'opponent': match.opponent,
                'is_home_game': match.is_home_game,
                'venue': match.venue,
                'date_time': match.date_time.isoformat() if match.date_time else None,
                'thread_id': match.discord_thread_id,
                'thread_created': match.thread_created,
                'live_reporting_status': match.live_reporting_status,
                'live_reporting_started': match.live_reporting_started,
                'live_reporting_scheduled': match.live_reporting_scheduled,
                'task_id': match.live_reporting_task_id,
                'current_score': 'Not available - check ESPN API directly',
                'last_update': 'Check task logs for live reporting activity'
            })
            
    except Exception as e:
        logger.error(f"Error getting status: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@test_live_reporting_bp.route('/v2/health', methods=['GET'])
@csrf.exempt
def v2_health_check():
    """V2 system health check endpoint."""
    try:
        if not V2_AVAILABLE:
            return jsonify({
                'success': False,
                'error': 'V2 system not available - missing dependencies',
                'overall': False,
                'components': {}
            }), 503
        
        logger.info("V2 health check requested")
        
        # Import V2 health check task
        from app.tasks.tasks_live_reporting_v2 import health_check_v2
        
        # Queue health check task
        task = health_check_v2.delay()
        result = task.get(timeout=30)
        
        logger.info(f"V2 health check completed: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"V2 health check error: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'overall': False,
            'components': {}
        }), 500


@test_live_reporting_bp.route('/v2/active-sessions', methods=['GET'])
@csrf.exempt
def v2_get_active_sessions():
    """Get active live reporting sessions using V2 architecture."""
    try:
        if not V2_AVAILABLE:
            return jsonify({
                'success': False,
                'error': 'V2 system not available',
                'count': 0,
                'active_sessions': []
            }), 503
            
        logger.info("Getting active sessions (V2) - using synchronous database access")
        
        # Use synchronous database access to avoid asyncio issues in Flask
        from app.models.live_reporting_session import LiveReportingSession
        from app.core.session_manager import managed_session
        
        with managed_session() as session:
            active_sessions = session.query(LiveReportingSession).filter_by(is_active=True).all()
            sessions_data = [
                {
                    'id': live_session.id,
                    'match_id': live_session.match_id,
                    'competition': live_session.competition,
                    'thread_id': live_session.thread_id,
                    'is_active': live_session.is_active,
                    'started_at': live_session.started_at.isoformat() if live_session.started_at else None,
                    'ended_at': live_session.ended_at.isoformat() if live_session.ended_at else None,
                    'last_update': live_session.last_update.isoformat() if live_session.last_update else None,
                    'last_status': live_session.last_status,
                    'last_score': live_session.last_score,
                    'update_count': live_session.update_count,
                    'error_count': live_session.error_count,
                    'last_error': live_session.last_error
                }
                for live_session in active_sessions
            ]
        
        return jsonify({
            'success': True,
            'count': len(sessions_data),
            'active_sessions': sessions_data
        })
        
    except Exception as e:
        logger.error(f"Error getting active sessions (V2): {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'count': 0,
            'active_sessions': []
        }), 500