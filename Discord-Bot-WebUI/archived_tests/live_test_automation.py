# app/utils/live_test_automation.py

"""
Live Reporting Test Automation

Executes complete 1:1 live reporting simulation with real Discord updates.
"""

import asyncio
import logging
import time
import json
from typing import Dict, Any, List
from app.utils.espn_json_emulator import espn_json_emulator
from app.utils.espn_api_client import ESPNAPIClient
from app.utils.discord_request_handler import send_to_discord_bot
from app.utils.sync_ai_client import get_sync_ai_client

logger = logging.getLogger(__name__)


class LiveReportingTestAutomation:
    """Complete automation for testing live reporting end-to-end."""

    def __init__(self):
        self.espn_client = ESPNAPIClient()
        self.ai_client = get_sync_ai_client()

    def execute_full_simulation(self, match_data: Dict[str, Any], speed_multiplier: int = 5) -> Dict[str, Any]:
        """
        Execute complete live match simulation with Discord updates.

        Args:
            match_data: Match details including thread_id, teams, etc.
            speed_multiplier: Speed up factor (5 = 5x faster than real time)

        Returns:
            Simulation results with all events and Discord responses
        """
        try:
            match_id = str(match_data['match_id'])
            espn_match_id = match_data['espn_match_id']
            discord_thread_id = match_data['discord_thread_id']
            home_team = match_data['home_team']
            away_team = match_data['away_team']

            logger.info(f"🚀 Starting full live reporting simulation for {home_team} vs {away_team}")

            # Step 1: Create ESPN JSON simulation
            espn_json_emulator.create_realistic_match(espn_match_id, home_team, away_team)

            # Step 2: Send pre-match message
            self._send_pre_match_message(discord_thread_id, home_team, away_team)

            # Step 3: Execute timed simulation
            simulation_results = []
            match_history = []  # Track events for AI context
            timeline = espn_json_emulator.match_states[espn_match_id]['timeline']

            for event in timeline:
                minute = event['minute']

                # Get ESPN JSON at this minute
                espn_data = espn_json_emulator.get_espn_json_at_minute(espn_match_id, minute)

                # Process significant events
                if event['type'] in ['goal', 'yellow-card', 'substitution', 'half-time', 'full-time']:
                    result = self._process_match_event(
                        event, espn_data, discord_thread_id, home_team, away_team, match_history
                    )
                    simulation_results.append(result)

                    # Add to match history for context
                    match_history.append({
                        'event_type': event['type'].replace('-', '_'),
                        'minute': minute,
                        'player': event.get('player', ''),
                        'team': event.get('team', ''),
                        'player_out': event.get('player_out'),
                        'player_in': event.get('player_in'),
                        'description': event.get('description', '')
                    })

                    # Show progress
                    print(f"⏱️  Minute {minute}: {event['type']} - {result.get('status', 'processed')}")

                # Wait between events (scaled by speed multiplier)
                time.sleep(1.0 / speed_multiplier)

            # Step 4: Send final summary
            final_score = self._get_final_score(espn_data)
            self._send_full_time_summary(discord_thread_id, home_team, away_team, final_score)

            logger.info(f"✅ Live reporting simulation completed with {len(simulation_results)} events")

            return {
                'success': True,
                'match_id': match_id,
                'espn_match_id': espn_match_id,
                'discord_thread_id': discord_thread_id,
                'events_processed': len(simulation_results),
                'simulation_results': simulation_results,
                'final_score': final_score
            }

        except Exception as e:
            logger.error(f"Live reporting simulation failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _send_pre_match_message(self, thread_id: str, home_team: str, away_team: str):
        """Send pre-match hype message to Discord."""
        try:
            ai_data = {
                'home_team': {'displayName': home_team},
                'away_team': {'displayName': away_team},
                'competition': 'MLS',
                'venue': 'Lumen Field'
            }

            hype_message = self.ai_client.generate_pre_match_hype(ai_data)

            discord_data = {
                'thread_id': thread_id,
                'message_type': 'pre_match',
                'content': hype_message or f"🔥 {away_team} vs {home_team} - Let's go Sounders! 💚💙",
                'embed_data': {
                    'title': f'{away_team} vs {home_team}',
                    'description': 'Live match reporting starting soon...',
                    'color': 0x005F4F,
                    'fields': [
                        {'name': 'Venue', 'value': 'Lumen Field', 'inline': True},
                        {'name': 'Competition', 'value': 'MLS', 'inline': True}
                    ]
                }
            }

            response = send_to_discord_bot('/api/live-reporting/event', {
                'thread_id': int(thread_id),
                'event_type': 'pre_match',
                'content': hype_message or f"🔥 {away_team} vs {home_team} - Let's go Sounders! 💚💙"
            })
            logger.info(f"Pre-match message sent to Discord: {response}")

        except Exception as e:
            logger.error(f"Failed to send pre-match message: {e}")

    def _process_match_event(self, event: Dict[str, Any], espn_data: Dict[str, Any],
                           thread_id: str, home_team: str, away_team: str, match_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Process individual match event and send to Discord."""
        try:
            event_type = event['type']
            minute = event['minute']

            # Extract current scores from ESPN data
            competition = espn_data['header']['competitions'][0]
            competitors = competition['competitors']
            home_score = competitors[0]['score'] if competitors[0]['homeAway'] == 'home' else competitors[1]['score']
            away_score = competitors[1]['score'] if competitors[1]['homeAway'] == 'away' else competitors[0]['score']

            # Generate AI commentary with match history context
            ai_commentary = None
            if event_type in ['goal', 'yellow-card', 'substitution']:
                ai_data = {
                    'home_team': {'displayName': home_team},
                    'away_team': {'displayName': away_team},
                    'event_type': event_type.replace('-', '_'),
                    'scoring_team': home_team if event.get('team') == 'home' else away_team,
                    'team': home_team if event.get('team') == 'home' else away_team,
                    'player': event.get('player', 'Unknown Player'),
                    'minute': minute,
                    'home_score': int(home_score),
                    'away_score': int(away_score)
                }
                ai_commentary = self.ai_client.generate_match_event_commentary(ai_data, match_history)

            # Create Discord message
            discord_data = {
                'thread_id': thread_id,
                'message_type': event_type,
                'minute': minute,
                'espn_data': espn_data,
                'event_data': event,
                'ai_commentary': ai_commentary,
                'score_line': f"{home_team} {home_score} - {away_score} {away_team}"
            }

            # Send to Discord using correct endpoint
            if event_type == 'goal':
                discord_response = send_to_discord_bot('/api/live-reporting/event', {
                    'thread_id': int(thread_id),
                    'event_type': 'goal',
                    'content': f"⚽ GOAL! {event.get('player', 'Unknown')} scores! {ai_commentary}",
                    'match_data': espn_data
                })
            elif event_type == 'half-time':
                discord_response = send_to_discord_bot('/api/live-reporting/status', {
                    'thread_id': int(thread_id),
                    'content': f"⏸️ HALF TIME: {home_team} {home_score} - {away_score} {away_team}",
                    'event_type': 'half_time'
                })
            elif event_type == 'full-time':
                discord_response = send_to_discord_bot('/api/live-reporting/final', {
                    'thread_id': int(thread_id),
                    'content': f"🏁 FULL TIME: {home_team} {home_score} - {away_score} {away_team}"
                })
            else:
                discord_response = send_to_discord_bot('/api/live-reporting/event', {
                    'thread_id': int(thread_id),
                    'event_type': event_type,
                    'content': f"📋 {event_type.replace('_', ' ').title()} - {event.get('player', 'Match event')}",
                    'match_data': espn_data
                })

            return {
                'event_type': event_type,
                'minute': minute,
                'player': event.get('player'),
                'team': event.get('team'),
                'home_score': home_score,
                'away_score': away_score,
                'ai_commentary': ai_commentary,
                'discord_response': discord_response,
                'status': 'success' if discord_response else 'discord_failed'
            }

        except Exception as e:
            logger.error(f"Failed to process event {event}: {e}")
            return {
                'event_type': event.get('type', 'unknown'),
                'minute': event.get('minute', 0),
                'status': 'failed',
                'error': str(e)
            }

    def _get_final_score(self, espn_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract final score from ESPN data."""
        try:
            competition = espn_data['header']['competitions'][0]
            competitors = competition['competitors']

            home_team = competitors[0] if competitors[0]['homeAway'] == 'home' else competitors[1]
            away_team = competitors[1] if competitors[1]['homeAway'] == 'away' else competitors[0]

            return {
                'home_team': home_team['team']['displayName'],
                'away_team': away_team['team']['displayName'],
                'home_score': int(home_team['score']),
                'away_score': int(away_team['score']),
                'result': 'win' if int(home_team['score']) > int(away_team['score']) else 'loss' if int(home_team['score']) < int(away_team['score']) else 'draw'
            }
        except Exception as e:
            logger.error(f"Failed to get final score: {e}")
            return {'home_score': 0, 'away_score': 0, 'result': 'unknown'}

    def _send_full_time_summary(self, thread_id: str, home_team: str, away_team: str, final_score: Dict[str, Any]):
        """Send full-time summary message."""
        try:
            ai_data = {
                'home_team': {'displayName': home_team},
                'away_team': {'displayName': away_team},
                'home_score': str(final_score['home_score']),
                'away_score': str(final_score['away_score']),
                'competition': 'MLS'
            }

            summary_message = self.ai_client.generate_full_time_message(ai_data)

            discord_data = {
                'thread_id': thread_id,
                'message_type': 'full_time',
                'content': summary_message or f"🏁 FULL TIME: {home_team} {final_score['home_score']} - {final_score['away_score']} {away_team}",
                'embed_data': {
                    'title': '🏁 FULL TIME',
                    'description': f"{home_team} {final_score['home_score']} - {final_score['away_score']} {away_team}",
                    'color': 0x005F4F if final_score['result'] == 'win' else 0xFF0000 if final_score['result'] == 'loss' else 0xFFFF00,
                    'fields': [
                        {'name': 'Result', 'value': final_score['result'].upper(), 'inline': True},
                        {'name': 'Venue', 'value': 'Lumen Field', 'inline': True}
                    ]
                }
            }

            response = send_to_discord_bot('/api/live-reporting/final', {
                'thread_id': int(thread_id),
                'content': summary_message or f"🏁 FULL TIME: {home_team} {final_score['home_score']} - {final_score['away_score']} {away_team}"
            })
            logger.info(f"Full-time summary sent to Discord: {response}")

        except Exception as e:
            logger.error(f"Failed to send full-time summary: {e}")


# Global automation instance
live_test_automation = LiveReportingTestAutomation()