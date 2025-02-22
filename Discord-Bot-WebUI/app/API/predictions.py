# app/API/predictions.py

"""
Predictions API Module

This module provides a standalone set of API endpoints for handling match predictions
and for looking up match details by Discord thread ID. It exposes three endpoints:

  1. GET /match/by_thread/<discord_thread_id>
      Looks up the match details from the mls_matches table using the provided Discord thread ID.
      Returns match details (e.g. match_id, opponent, date_time, etc.) in JSON format.
  
  2. POST /predictions
     Accepts a JSON payload with the following fields:
          match_id (string): The unique match identifier.
          discord_user_id (string): The Discord user ID making the prediction.
          home_score (integer): The predicted score for the home team.
          opponent_score (integer): The predicted score for the opponent.
     Creates a new prediction record in the database and returns a confirmation JSON response.
  
  3. GET /predictions/<match_id>
     Retrieves all prediction records for a given match in a structured JSON array.

These endpoints are designed specifically for JSON API usage (for example, by a Discord bot)
and are exempt from CSRF protection using a before-request handler. This API module is meant to
be integrated into a larger Flask application where CSRF protection remains enabled for all other
endpoints.
"""

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify, current_app
from app.core.session_manager import managed_session
from app.models import MLSMatch, Prediction

logger = logging.getLogger(__name__)

predictions_api = Blueprint('predictions_api', __name__)

@predictions_api.route('/match/by_thread/<discord_thread_id>', methods=['GET'])
def get_match_by_thread(discord_thread_id):
    """
    Look up and return the match details for a given Discord thread ID.

    Expects a Discord thread ID as a URL parameter.
    Returns a JSON object with match details if found, or a 404 error if not.

    Example response (200):
    {
      "match_id": "726810",
      "opponent": "Charlotte FC",
      "date_time": "2025-02-22T19:30:00-08:00",
      "is_home_game": true,
      "summary_link": "https://www.espn.com/soccer/match/_/gameId/726810/charlotte-fc-seattle-sounders-fc",
      "stats_link": "https://www.espn.com/soccer/matchstats/_/gameId/726810",
      "commentary_link": "Unavailable",
      "venue": "Lumen Field",
      "competition": "usa.1",
      "thread_creation_time": "2025-02-20T19:30:00-08:00",
      "thread_created": true,
      "discord_thread_id": "1342584949340897342",
      "live_reporting_scheduled": true,
      "live_reporting_started": false,
      "live_reporting_status": "not_started",
      "live_reporting_task_id": null
    }
    """
    with managed_session() as session:
        match = session.query(MLSMatch).filter_by(discord_thread_id=discord_thread_id).first()
        if not match:
            return jsonify({'error': 'Match not found for given Discord thread ID'}), 404

        match_data = {
            'match_id': match.match_id,
            'opponent': match.opponent,
            'date_time': match.date_time.isoformat(),
            'is_home_game': match.is_home_game,
            'summary_link': match.summary_link,
            'stats_link': match.stats_link,
            'commentary_link': match.commentary_link,
            'venue': match.venue,
            'competition': match.competition,
            'thread_creation_time': match.thread_creation_time.isoformat() if match.thread_creation_time else None,
            'thread_created': match.thread_created,
            'discord_thread_id': match.discord_thread_id,
            'live_reporting_scheduled': match.live_reporting_scheduled,
            'live_reporting_started': match.live_reporting_started,
            'live_reporting_status': match.live_reporting_status,
            'live_reporting_task_id': match.live_reporting_task_id
        }
        return jsonify(match_data), 200


@predictions_api.route('/predictions', methods=['POST'])
def create_prediction():
    """
    Create or update a prediction if predictions are still open.
    Predictions will be closed if the match is within 5 minutes of kickoff
    or if live reporting has started.
    """
    data = request.json
    logger.info(f"Received POST /predictions with data: {data}")

    match_id = data.get("match_id")
    discord_user_id = data.get("discord_user_id")
    
    try:
        home_score = int(data.get("home_score"))
        opponent_score = int(data.get("opponent_score"))
    except (TypeError, ValueError):
        logger.error("Scores must be numeric")
        return jsonify({'error': 'Scores must be numeric'}), 400

    try:
        with managed_session() as session:
            # Query the match record to enforce prediction cutoff.
            match_record = session.query(MLSMatch).filter_by(match_id=match_id).first()
            if match_record:
                # Use an offset-aware datetime
                now = datetime.now(timezone.utc)
                # Check if live reporting has started or if we're within 5 minutes of kickoff.
                if (match_record.live_reporting_started or
                    match_record.live_reporting_status == 'running' or
                    now >= match_record.date_time - timedelta(minutes=5)):
                    return jsonify({'error': 'Predictions are closed for this match.'}), 400

            # Check if a prediction from this user for this match already exists.
            existing = session.query(Prediction).filter_by(
                match_id=match_id,
                discord_user_id=discord_user_id
            ).first()

            if existing:
                # Update the existing prediction.
                existing.home_score = home_score
                existing.opponent_score = opponent_score
                session.commit()
                logger.info(f"Prediction updated for match {match_id} by user {discord_user_id}")
                return jsonify({'success': True, 'message': 'Prediction updated'}), 200
            else:
                # Create a new prediction.
                prediction = Prediction(
                    match_id=match_id,
                    discord_user_id=discord_user_id,
                    home_score=home_score,
                    opponent_score=opponent_score
                )
                session.add(prediction)
                session.commit()
                logger.info(f"Prediction recorded for match {match_id} by user {discord_user_id}")
                return jsonify({'success': True, 'message': 'Prediction recorded'}), 200

    except Exception as e:
        current_app.logger.error(f"Error processing prediction: {str(e)}")
        return jsonify({'error': 'Failed to record prediction'}), 500

@predictions_api.route('/predictions/<match_id>', methods=['GET'])
def get_predictions(match_id):
    """
    Retrieve all predictions for a given match.

    URL Parameter:
      - match_id (string): The unique identifier for the match.

    Returns a JSON array of prediction objects. Each object includes:
      - id (integer): The prediction record ID.
      - match_id (string): The match identifier.
      - discord_user_id (string): The Discord user ID who made the prediction.
      - home_score (integer): The predicted home team score.
      - opponent_score (integer): The predicted opponent score.
      - is_correct (boolean or null): Whether the prediction was correct (null if not evaluated yet).
      - season_correct_count (integer): The running tally of correct predictions in the season.
      - created_at (string): Timestamp in ISO format of when the prediction was created.

    Example response:
    [
        {
            "id": 1,
            "match_id": "726810",
            "discord_user_id": "1234567890",
            "home_score": 3,
            "opponent_score": 1,
            "is_correct": null,
            "season_correct_count": 0,
            "created_at": "2025-02-21T20:38:10.915168"
        },
        ...
    ]
    """
    logger.info(f"Received GET /predictions/{match_id}")
    try:
        with managed_session() as session:
            predictions = session.query(Prediction).filter_by(match_id=match_id).all()
            results = []
            for pred in predictions:
                results.append({
                    'id': pred.id,
                    'match_id': pred.match_id,
                    'discord_user_id': pred.discord_user_id,
                    'home_score': pred.home_score,
                    'opponent_score': pred.opponent_score,
                    'is_correct': pred.is_correct,
                    'season_correct_count': pred.season_correct_count,
                    'created_at': pred.created_at.isoformat()
                })
            logger.info(f"Returning {len(results)} predictions for match {match_id}")
            return jsonify(results), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching predictions: {str(e)}")
        return jsonify({'error': 'Failed to fetch predictions'}), 500

@predictions_api.route('/predictions/<match_id>/correct', methods=['GET'])
def get_correct_predictions(match_id):
    """
    Retrieve a list of Discord user IDs for users whose predictions were correct for the given match.
    """
    try:
        with managed_session() as session:
            predictions = session.query(Prediction).filter_by(match_id=match_id, is_correct=True).all()
            correct_users = [p.discord_user_id for p in predictions]
        return jsonify({'correct_predictions': correct_users}), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching correct predictions: {str(e)}")
        return jsonify({'error': 'Failed to fetch correct predictions'}), 500