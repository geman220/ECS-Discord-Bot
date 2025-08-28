# app/routes/ai_enhancement_routes.py

"""
AI Enhancement Routes

API endpoints for AI-powered live reporting enhancements including
pre-match hype, contextual messages, and thread descriptions.
"""

import logging
from flask import Blueprint, request, jsonify
from app.utils.sync_ai_client import get_sync_ai_client

logger = logging.getLogger(__name__)

# Create blueprint
ai_enhancement_bp = Blueprint('ai_enhancement', __name__)


@ai_enhancement_bp.route('/api/ai/generate_thread_context', methods=['POST'])
def generate_thread_context():
    """
    Generate AI-powered contextual description for match thread creation.
    
    Expected payload:
    {
        "home_team": {"displayName": "Team Name"},
        "away_team": {"displayName": "Team Name"},
        "competition": "MLS|Leagues Cup|etc",
        "venue": "Stadium Name"
    }
    
    Returns:
        {"context": "Generated contextual description"}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Validate required fields
        required_fields = ['home_team', 'away_team']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields: home_team, away_team'}), 400
        
        # Get AI client and generate context
        ai_client = get_sync_ai_client()
        context = ai_client.generate_match_thread_context(data)
        
        if context:
            logger.info(f"Generated AI thread context for {data.get('home_team', {}).get('displayName')} vs {data.get('away_team', {}).get('displayName')}")
            return jsonify({'context': context})
        else:
            logger.warning("AI thread context generation failed - returning fallback")
            return jsonify({'context': None})
            
    except Exception as e:
        logger.error(f"Error in thread context generation: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@ai_enhancement_bp.route('/api/ai/generate_pre_match_hype', methods=['POST'])
def generate_pre_match_hype():
    """
    Generate AI-powered pre-match hype message.
    
    Expected payload:
    {
        "home_team": {"displayName": "Team Name"},
        "away_team": {"displayName": "Team Name"},
        "competition": "MLS|Leagues Cup|etc",
        "venue": "Stadium Name",
        "kickoff_time": "ISO timestamp"
    }
    
    Returns:
        {"hype_message": "Generated pre-match hype"}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Get AI client and generate hype
        ai_client = get_sync_ai_client()
        hype_message = ai_client.generate_pre_match_hype(data)
        
        if hype_message:
            logger.info(f"Generated pre-match hype for {data.get('home_team', {}).get('displayName')} vs {data.get('away_team', {}).get('displayName')}")
            return jsonify({'hype_message': hype_message})
        else:
            logger.warning("Pre-match hype generation failed")
            return jsonify({'hype_message': None})
            
    except Exception as e:
        logger.error(f"Error in pre-match hype generation: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@ai_enhancement_bp.route('/api/ai/generate_half_time_message', methods=['POST'])
def generate_half_time_message():
    """
    Generate AI-powered half-time analysis message.
    
    Expected payload:
    {
        "home_team": {"displayName": "Team Name"},
        "away_team": {"displayName": "Team Name"},
        "home_score": "0",
        "away_score": "1",
        "competition": "MLS"
    }
    
    Returns:
        {"half_time_message": "Generated half-time analysis"}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Get AI client and generate message
        ai_client = get_sync_ai_client()
        message = ai_client.generate_half_time_message(data)
        
        if message:
            logger.info(f"Generated half-time message for {data.get('home_score', '0')}-{data.get('away_score', '0')} match")
            return jsonify({'half_time_message': message})
        else:
            logger.warning("Half-time message generation failed")
            return jsonify({'half_time_message': None})
            
    except Exception as e:
        logger.error(f"Error in half-time message generation: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@ai_enhancement_bp.route('/api/ai/generate_full_time_message', methods=['POST'])  
def generate_full_time_message():
    """
    Generate AI-powered full-time summary message.
    
    Expected payload:
    {
        "home_team": {"displayName": "Team Name"},
        "away_team": {"displayName": "Team Name"}, 
        "home_score": "2",
        "away_score": "1",
        "competition": "MLS"
    }
    
    Returns:
        {"full_time_message": "Generated full-time summary"}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Get AI client and generate message
        ai_client = get_sync_ai_client()
        message = ai_client.generate_full_time_message(data)
        
        if message:
            logger.info(f"Generated full-time message for {data.get('home_score', '0')}-{data.get('away_score', '0')} final")
            return jsonify({'full_time_message': message})
        else:
            logger.warning("Full-time message generation failed")
            return jsonify({'full_time_message': None})
            
    except Exception as e:
        logger.error(f"Error in full-time message generation: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@ai_enhancement_bp.route('/api/ai/health', methods=['GET'])
def ai_health_check():
    """Health check for AI enhancement services."""
    try:
        ai_client = get_sync_ai_client()
        return jsonify({
            'status': 'healthy',
            'ai_service_configured': ai_client.service.api_key is not None
        })
    except Exception as e:
        logger.error(f"AI health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500