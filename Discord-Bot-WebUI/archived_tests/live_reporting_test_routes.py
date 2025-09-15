# app/routes/live_reporting_test_routes.py

"""
Live Reporting Test Routes

Comprehensive testing endpoints for live match reporting system including:
- ESPN API emulation with realistic match progressions
- AI contextual testing for various match events
- Automated test workflows with immediate results
"""

import logging
import asyncio
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app
from app.utils.sync_ai_client import get_sync_ai_client
from app.services.realtime_reporting_service import RealtimeReportingService
from app.utils.espn_api_client import ESPNAPIClient
from app.utils.discord_request_handler import send_to_discord_bot
import json
import time
import threading

logger = logging.getLogger(__name__)

# Create blueprint
live_test_bp = Blueprint('live_test', __name__)


class ESPNEmulator:
    """ESPN API emulator for realistic match testing."""

    def __init__(self):
        self.match_states = {}
        self.event_templates = {
            'goal_home': {
                'type': 'goal',
                'team': 'home',
                'player_names': ['Jordan Morris', 'Raúl Ruidíaz', 'Albert Rusnák', 'Cristian Roldan'],
                'ai_context': 'positive'
            },
            'goal_away': {
                'type': 'goal',
                'team': 'away',
                'player_names': ['Lionel Messi', 'Luis Suárez', 'Jordi Alba', 'Sergio Busquets'],
                'ai_context': 'negative'
            },
            'yellow_card': {
                'type': 'yellow_card',
                'player_names': ['João Paulo', 'Jackson Ragen', 'Obed Vargas'],
                'ai_context': 'caution'
            },
            'substitution': {
                'type': 'substitution',
                'player_names': ['Paul Rothrock', 'Reed Baker-Whiting', 'Danny Leyva'],
                'ai_context': 'tactical'
            }
        }

    def create_match_progression(self, match_id: str, home_team: str, away_team: str):
        """Create a realistic match progression with timed events."""
        progression = [
            {'minute': 1, 'event': 'kickoff', 'description': 'Match begins'},
            {'minute': 12, 'event': 'goal_home', 'description': f'{home_team} takes the lead!'},
            {'minute': 23, 'event': 'yellow_card', 'team': 'away', 'description': 'Tactical foul'},
            {'minute': 31, 'event': 'goal_away', 'description': f'{away_team} equalizes!'},
            {'minute': 45, 'event': 'half_time', 'description': 'Half-time break'},
            {'minute': 46, 'event': 'second_half', 'description': 'Second half begins'},
            {'minute': 58, 'event': 'substitution', 'team': 'home', 'description': 'Fresh legs brought on'},
            {'minute': 67, 'event': 'goal_home', 'description': f'{home_team} retakes the lead!'},
            {'minute': 73, 'event': 'yellow_card', 'team': 'home', 'description': 'Time-wasting caution'},
            {'minute': 82, 'event': 'substitution', 'team': 'away', 'description': 'Attacking change'},
            {'minute': 90, 'event': 'full_time', 'description': 'Match ends'}
        ]

        self.match_states[match_id] = {
            'progression': progression,
            'current_minute': 0,
            'home_team': home_team,
            'away_team': away_team,
            'home_score': 0,
            'away_score': 0,
            'status': 'scheduled'
        }

        return progression

    def get_match_data(self, match_id: str, target_minute: int = None):
        """Get ESPN-formatted match data at specific minute."""
        if match_id not in self.match_states:
            return None

        state = self.match_states[match_id]
        if target_minute:
            state['current_minute'] = target_minute

        # Calculate scores up to current minute
        home_score = 0
        away_score = 0
        events = []

        for event in state['progression']:
            if event['minute'] <= state['current_minute']:
                if event['event'] == 'goal_home':
                    home_score += 1
                    events.append({
                        'type': 'goal',
                        'minute': event['minute'],
                        'team': state['home_team'],
                        'player': self.event_templates['goal_home']['player_names'][home_score % 4],
                        'description': event['description']
                    })
                elif event['event'] == 'goal_away':
                    away_score += 1
                    events.append({
                        'type': 'goal',
                        'minute': event['minute'],
                        'team': state['away_team'],
                        'player': self.event_templates['goal_away']['player_names'][away_score % 4],
                        'description': event['description']
                    })
                elif event['event'] in ['yellow_card', 'substitution']:
                    events.append({
                        'type': event['event'],
                        'minute': event['minute'],
                        'team': state[f"{event.get('team', 'home')}_team"],
                        'description': event['description']
                    })

        # Determine match status
        if state['current_minute'] == 0:
            status = 'scheduled'
        elif state['current_minute'] < 45:
            status = 'in_progress_1st'
        elif state['current_minute'] == 45:
            status = 'halftime'
        elif state['current_minute'] < 90:
            status = 'in_progress_2nd'
        else:
            status = 'final'

        return {
            'match_id': match_id,
            'status': status,
            'home_team': state['home_team'],
            'away_team': state['away_team'],
            'home_score': home_score,
            'away_score': away_score,
            'minute': str(state['current_minute']),
            'events': events,
            'period': 1 if state['current_minute'] <= 45 else 2,
            'clock': f"{state['current_minute']:02d}:00",
            'emulated': True,
            'cached_at': time.time()
        }


# Global emulator instance
espn_emulator = ESPNEmulator()


@live_test_bp.route('/api/test/create-match-simulation', methods=['POST'])
def create_match_simulation():
    """
    Create a realistic match simulation with predefined events.

    Expected payload:
    {
        "match_id": 85,
        "espn_match_id": "727247",
        "discord_thread_id": "1417208764964016168",
        "home_team": "Seattle Sounders FC",
        "away_team": "Inter Miami CF"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        required_fields = ['match_id', 'espn_match_id', 'discord_thread_id', 'home_team', 'away_team']
        if not all(field in data for field in required_fields):
            return jsonify({'error': f'Missing required fields: {required_fields}'}), 400

        espn_match_id = data['espn_match_id']
        home_team = data['home_team']
        away_team = data['away_team']

        # Create match progression
        progression = espn_emulator.create_match_progression(espn_match_id, home_team, away_team)

        logger.info(f"Created match simulation for {home_team} vs {away_team} (ESPN ID: {espn_match_id})")

        return jsonify({
            'success': True,
            'message': 'Match simulation created successfully',
            'espn_match_id': espn_match_id,
            'progression': progression,
            'total_events': len(progression)
        })

    except Exception as e:
        logger.error(f"Error creating match simulation: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@live_test_bp.route('/api/test/simulate-match-minute', methods=['POST'])
def simulate_match_minute():
    """
    Simulate match at specific minute and test AI responses.

    Expected payload:
    {
        "espn_match_id": "727247",
        "minute": 23,
        "test_ai": true
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        espn_match_id = data.get('espn_match_id')
        minute = data.get('minute', 1)
        test_ai = data.get('test_ai', False)

        if not espn_match_id:
            return jsonify({'error': 'espn_match_id is required'}), 400

        # Get match data at specific minute
        match_data = espn_emulator.get_match_data(espn_match_id, minute)
        if not match_data:
            return jsonify({'error': 'Match simulation not found. Create simulation first.'}), 404

        result = {
            'success': True,
            'minute': minute,
            'match_data': match_data,
            'events_at_minute': []
        }

        # Find events at this specific minute
        current_events = [e for e in match_data['events'] if e['minute'] == minute]
        result['events_at_minute'] = current_events

        # Test AI responses if requested
        if test_ai and current_events:
            ai_client = get_sync_ai_client()
            ai_responses = []

            for event in current_events:
                try:
                    if event['type'] == 'goal':
                        # Test AI goal commentary
                        ai_data = {
                            'home_team': {'displayName': match_data['home_team']},
                            'away_team': {'displayName': match_data['away_team']},
                            'event_type': 'goal',
                            'scoring_team': event['team'],
                            'player': event['player'],
                            'minute': event['minute'],
                            'home_score': match_data['home_score'],
                            'away_score': match_data['away_score']
                        }

                        ai_response = ai_client.generate_match_event_commentary(ai_data)
                        ai_responses.append({
                            'event_type': 'goal',
                            'context': 'positive' if event['team'] == match_data['home_team'] else 'negative',
                            'ai_commentary': ai_response
                        })

                except Exception as e:
                    logger.error(f"AI test error for event {event}: {e}")
                    ai_responses.append({
                        'event_type': event['type'],
                        'error': str(e)
                    })

            result['ai_responses'] = ai_responses

        logger.info(f"Simulated minute {minute} for match {espn_match_id}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error simulating match minute: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@live_test_bp.route('/api/test/run-full-match-simulation', methods=['POST'])
def run_full_match_simulation():
    """
    Run complete match simulation with live reporting to Discord.

    Expected payload:
    {
        "match_id": 85,
        "espn_match_id": "727247",
        "discord_thread_id": "1417208764964016168",
        "speed_multiplier": 10,
        "test_ai": true
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        match_id = data.get('match_id')
        espn_match_id = data.get('espn_match_id')
        discord_thread_id = data.get('discord_thread_id')
        speed_multiplier = data.get('speed_multiplier', 10)  # 10x speed by default
        test_ai = data.get('test_ai', False)

        required_fields = ['match_id', 'espn_match_id', 'discord_thread_id']
        missing_fields = [f for f in required_fields if not data.get(f)]
        if missing_fields:
            return jsonify({'error': f'Missing required fields: {missing_fields}'}), 400

        # Check if simulation exists
        if espn_match_id not in espn_emulator.match_states:
            return jsonify({'error': 'Match simulation not found. Create simulation first.'}), 404

        # Start asynchronous simulation
        def run_simulation():
            """Run the simulation in background thread."""
            try:
                state = espn_emulator.match_states[espn_match_id]
                progression = state['progression']

                for event in progression:
                    minute = event['minute']

                    # Get match data at this minute
                    match_data = espn_emulator.get_match_data(espn_match_id, minute)

                    # Send to Discord if significant event
                    if event['event'] in ['goal_home', 'goal_away', 'half_time', 'full_time']:
                        discord_data = {
                            'thread_id': discord_thread_id,
                            'match_data': match_data,
                            'event': event,
                            'minute': minute
                        }

                        # Send to Discord bot
                        discord_response = send_to_discord_bot('/api/live_match_update', discord_data)
                        logger.info(f"Sent {event['event']} to Discord: {discord_response}")

                        # Test AI if requested
                        if test_ai and event['event'].startswith('goal'):
                            ai_client = get_sync_ai_client()
                            try:
                                ai_data = {
                                    'home_team': {'displayName': match_data['home_team']},
                                    'away_team': {'displayName': match_data['away_team']},
                                    'event_type': 'goal',
                                    'minute': minute,
                                    'home_score': match_data['home_score'],
                                    'away_score': match_data['away_score']
                                }
                                ai_response = ai_client.generate_match_event_commentary(ai_data)
                                logger.info(f"AI Commentary for minute {minute}: {ai_response}")
                            except Exception as e:
                                logger.error(f"AI test failed at minute {minute}: {e}")

                    # Wait based on speed multiplier
                    time.sleep(1.0 / speed_multiplier)

                logger.info(f"Full match simulation completed for {espn_match_id}")

            except Exception as e:
                logger.error(f"Simulation thread error: {e}", exc_info=True)

        # Start simulation in background
        simulation_thread = threading.Thread(target=run_simulation)
        simulation_thread.daemon = True
        simulation_thread.start()

        return jsonify({
            'success': True,
            'message': 'Full match simulation started',
            'espn_match_id': espn_match_id,
            'discord_thread_id': discord_thread_id,
            'speed_multiplier': speed_multiplier,
            'estimated_duration_seconds': 90 / speed_multiplier
        })

    except Exception as e:
        logger.error(f"Error starting full match simulation: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@live_test_bp.route('/api/test/quick-goal-test', methods=['POST'])
def quick_goal_test():
    """
    Quick test for goal events with AI commentary.

    Expected payload:
    {
        "discord_thread_id": "1417208764964016168",
        "scoring_team": "home|away",
        "player_name": "Jordan Morris"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        discord_thread_id = data.get('discord_thread_id')
        scoring_team = data.get('scoring_team', 'home')
        player_name = data.get('player_name', 'Jordan Morris')

        if not discord_thread_id:
            return jsonify({'error': 'discord_thread_id is required'}), 400

        # Create test goal event
        goal_event = {
            'type': 'goal',
            'team': 'Seattle Sounders FC' if scoring_team == 'home' else 'Inter Miami CF',
            'player': player_name,
            'minute': 23,
            'home_score': 1 if scoring_team == 'home' else 0,
            'away_score': 1 if scoring_team == 'away' else 0
        }

        # Test AI commentary
        ai_client = get_sync_ai_client()
        ai_data = {
            'home_team': {'displayName': 'Seattle Sounders FC'},
            'away_team': {'displayName': 'Inter Miami CF'},
            'event_type': 'goal',
            'scoring_team': goal_event['team'],
            'player': player_name,
            'minute': 23,
            'home_score': goal_event['home_score'],
            'away_score': goal_event['away_score']
        }

        ai_commentary = ai_client.generate_match_event_commentary(ai_data)

        # Send to Discord
        discord_data = {
            'thread_id': discord_thread_id,
            'event': goal_event,
            'ai_commentary': ai_commentary
        }

        discord_response = send_to_discord_bot('/api/live_goal_update', discord_data)

        return jsonify({
            'success': True,
            'goal_event': goal_event,
            'ai_commentary': ai_commentary,
            'discord_response': discord_response,
            'context': 'positive' if scoring_team == 'home' else 'negative'
        })

    except Exception as e:
        logger.error(f"Error in quick goal test: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@live_test_bp.route('/api/test/execute-full-simulation', methods=['POST'])
def execute_full_simulation():
    """
    Execute complete 1:1 live reporting simulation with Discord updates.

    Expected payload:
    {
        "match_id": 85,
        "espn_match_id": "727247",
        "discord_thread_id": "1417208764964016168",
        "home_team": "Seattle Sounders FC",
        "away_team": "Inter Miami CF",
        "speed_multiplier": 5
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        # Import and execute automation
        from app.utils.live_test_automation import live_test_automation

        # Execute simulation
        result = live_test_automation.execute_full_simulation(
            match_data=data,
            speed_multiplier=data.get('speed_multiplier', 5)
        )

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error executing full simulation: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@live_test_bp.route('/api/test/status', methods=['GET'])
def test_status():
    """Get status of all active test simulations."""
    try:
        return jsonify({
            'success': True,
            'active_simulations': list(espn_emulator.match_states.keys()),
            'emulator_ready': True,
            'ai_client_ready': get_sync_ai_client() is not None,
            'discord_bot_connected': True  # TODO: Add actual health check
        })
    except Exception as e:
        logger.error(f"Error getting test status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500