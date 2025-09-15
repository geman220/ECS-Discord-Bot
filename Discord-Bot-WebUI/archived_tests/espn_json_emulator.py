# app/utils/espn_json_emulator.py

"""
ESPN API JSON Emulator

Provides 1:1 accurate ESPN API JSON responses for comprehensive testing.
Based on real ESPN API structure for soccer matches.
"""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


class ESPNJSONEmulator:
    """Emulates exact ESPN API JSON responses for realistic testing."""

    def __init__(self):
        self.match_states = {}
        self.base_timestamp = datetime.utcnow()

    def create_realistic_match(self, match_id: str, home_team: str, away_team: str) -> Dict[str, Any]:
        """Create a realistic ESPN match JSON structure."""

        # Event progression with realistic timing
        events_timeline = [
            {'minute': 1, 'type': 'kickoff', 'team': None},
            {'minute': 12, 'type': 'goal', 'team': 'home', 'player': 'Jordan Morris', 'description': 'Right footed shot from the center of the box'},
            {'minute': 23, 'type': 'yellow-card', 'team': 'away', 'player': 'Sergio Busquets', 'description': 'Tactical foul'},
            {'minute': 31, 'type': 'goal', 'team': 'away', 'player': 'Lionel Messi', 'description': 'Left footed shot from outside the box'},
            {'minute': 45, 'type': 'half-time', 'team': None},
            {'minute': 46, 'type': 'second-half', 'team': None},
            {'minute': 58, 'type': 'substitution', 'team': 'home', 'player_out': 'Albert Rusnák', 'player_in': 'Paul Rothrock'},
            {'minute': 67, 'type': 'goal', 'team': 'home', 'player': 'Raúl Ruidíaz', 'description': 'Header from close range'},
            {'minute': 73, 'type': 'yellow-card', 'team': 'home', 'player': 'João Paulo', 'description': 'Time wasting'},
            {'minute': 82, 'type': 'substitution', 'team': 'away', 'player_out': 'Luis Suárez', 'player_in': 'Leonardo Campana'},
            {'minute': 90, 'type': 'full-time', 'team': None}
        ]

        self.match_states[match_id] = {
            'timeline': events_timeline,
            'current_minute': 0,
            'home_team': home_team,
            'away_team': away_team,
            'started': False
        }

        return self.get_espn_json_at_minute(match_id, 0)

    def get_espn_json_at_minute(self, match_id: str, minute: int) -> Dict[str, Any]:
        """Get ESPN-formatted JSON at specific minute."""

        if match_id not in self.match_states:
            return self._create_error_response(match_id)

        state = self.match_states[match_id]
        state['current_minute'] = minute

        # Calculate scores and events up to current minute
        home_score = 0
        away_score = 0
        match_events = []

        for event in state['timeline']:
            if event['minute'] <= minute:
                if event['type'] == 'goal':
                    if event['team'] == 'home':
                        home_score += 1
                    else:
                        away_score += 1

                    match_events.append(self._create_goal_event(event, home_score + away_score))
                elif event['type'] in ['yellow-card', 'substitution']:
                    match_events.append(self._create_event(event))

        # Determine status
        if minute == 0:
            status_type = {'id': '1', 'name': 'STATUS_SCHEDULED', 'state': 'pre', 'completed': False, 'description': 'Scheduled', 'detail': 'Sun, September 15th at 4:30 PM PST', 'shortDetail': '9/15 - 4:30 PM PST'}
            period = 0
            clock = '0:00'
        elif minute < 45:
            status_type = {'id': '2', 'name': 'STATUS_IN_PROGRESS', 'state': 'in', 'completed': False, 'description': 'In Progress', 'detail': f'{minute}\'', 'shortDetail': f'{minute}\''}
            period = 1
            clock = f'{minute}:00'
        elif minute == 45:
            status_type = {'id': '3', 'name': 'STATUS_HALFTIME', 'state': 'in', 'completed': False, 'description': 'Halftime', 'detail': 'Halftime', 'shortDetail': 'Half'}
            period = 1
            clock = '45:00'
        elif minute < 90:
            status_type = {'id': '2', 'name': 'STATUS_IN_PROGRESS', 'state': 'in', 'completed': False, 'description': 'In Progress', 'detail': f'{minute}\'', 'shortDetail': f'{minute}\''}
            period = 2
            clock = f'{minute}:00'
        else:
            status_type = {'id': '4', 'name': 'STATUS_FINAL', 'state': 'post', 'completed': True, 'description': 'Final', 'detail': 'Final', 'shortDetail': 'Final'}
            period = 2
            clock = '90:00'

        # Build complete ESPN JSON structure
        espn_json = {
            'boxscore': {
                'teams': [
                    {
                        'team': {
                            'id': '3500',
                            'location': 'Seattle',
                            'name': 'Sounders FC',
                            'displayName': state['home_team'],
                            'shortDisplayName': 'SEA',
                            'abbreviation': 'SEA',
                            'color': '005F4F',
                            'alternateColor': 'C4D600',
                            'logo': 'https://a.espncdn.com/i/teamlogos/soccer/500/3500.png'
                        },
                        'homeAway': 'home',
                        'score': str(home_score),
                        'linescores': [{'value': home_score}],
                        'statistics': [],
                        'leaders': []
                    },
                    {
                        'team': {
                            'id': '28716',
                            'location': 'Inter Miami',
                            'name': 'CF',
                            'displayName': state['away_team'],
                            'shortDisplayName': 'MIA',
                            'abbreviation': 'MIA',
                            'color': 'F7B5CD',
                            'alternateColor': '231F20',
                            'logo': 'https://a.espncdn.com/i/teamlogos/soccer/500/28716.png'
                        },
                        'homeAway': 'away',
                        'score': str(away_score),
                        'linescores': [{'value': away_score}],
                        'statistics': [],
                        'leaders': []
                    }
                ],
                'players': []
            },
            'header': {
                'id': match_id,
                'uid': f's:1~l:22~e:{match_id}',
                'date': (self.base_timestamp + timedelta(days=1)).isoformat() + 'Z',
                'timeValid': True,
                'competitions': [
                    {
                        'id': match_id,
                        'uid': f's:1~l:22~e:{match_id}~c:{match_id}',
                        'date': (self.base_timestamp + timedelta(days=1)).isoformat() + 'Z',
                        'attendance': 69274 if minute > 0 else 0,
                        'type': {
                            'id': '1',
                            'abbreviation': 'STD'
                        },
                        'timeValid': True,
                        'neutralSite': False,
                        'conferenceCompetition': False,
                        'playByPlayAvailable': True,
                        'recent': minute > 0,
                        'venue': {
                            'id': '3995',
                            'fullName': 'Lumen Field',
                            'address': {
                                'city': 'Seattle',
                                'state': 'WA'
                            },
                            'capacity': 69274,
                            'indoor': False
                        },
                        'competitors': [
                            {
                                'id': '3500',
                                'uid': 's:1~l:22~t:3500',
                                'type': 'team',
                                'order': 0,
                                'homeAway': 'home',
                                'team': {
                                    'id': '3500',
                                    'location': 'Seattle',
                                    'name': 'Sounders FC',
                                    'displayName': state['home_team'],
                                    'shortDisplayName': 'SEA',
                                    'abbreviation': 'SEA'
                                },
                                'score': str(home_score),
                                'linescores': [{'value': home_score}],
                                'statistics': [],
                                'leaders': []
                            },
                            {
                                'id': '28716',
                                'uid': 's:1~l:22~t:28716',
                                'type': 'team',
                                'order': 1,
                                'homeAway': 'away',
                                'team': {
                                    'id': '28716',
                                    'location': 'Inter Miami',
                                    'name': 'CF',
                                    'displayName': state['away_team'],
                                    'shortDisplayName': 'MIA',
                                    'abbreviation': 'MIA'
                                },
                                'score': str(away_score),
                                'linescores': [{'value': away_score}],
                                'statistics': [],
                                'leaders': []
                            }
                        ],
                        'notes': [],
                        'status': {
                            'clock': clock,
                            'displayClock': clock,
                            'period': period,
                            'type': status_type
                        },
                        'broadcasts': [],
                        'leaders': []
                    }
                ],
                'links': [],
                'season': {
                    'year': 2025,
                    'type': 2,
                    'name': 'Regular Season'
                },
                'week': {
                    'number': 28
                }
            },
            'plays': match_events,
            'winprobability': [],
            'predictor': {},
            'gameInfo': {
                'venue': {
                    'id': '3995',
                    'fullName': 'Lumen Field',
                    'address': {
                        'city': 'Seattle',
                        'state': 'WA'
                    },
                    'capacity': 69274
                },
                'attendance': 69274 if minute > 0 else 0,
                'officials': [],
                'temperature': 72
            },
            'drives': {
                'previous': [],
                'current': {},
                'next': []
            }
        }

        return espn_json

    def _create_goal_event(self, event: Dict[str, Any], sequence: int) -> Dict[str, Any]:
        """Create ESPN-style goal event."""
        return {
            'id': f'4014156817862{sequence:03d}',
            'sequenceNumber': str(sequence),
            'type': {
                'id': '1',
                'text': 'Goal'
            },
            'text': f"Goal by {event['player']} ({event['description']})",
            'shortText': f"{event['player']} goal",
            'scoreValue': 1,
            'team': {
                'id': '3500' if event['team'] == 'home' else '28716'
            },
            'participants': [
                {
                    'athlete': {
                        'id': '123456',
                        'fullName': event['player'],
                        'displayName': event['player'],
                        'shortName': event['player'],
                        'jersey': '9' if 'Morris' in event['player'] else '10'
                    }
                }
            ],
            'clock': {
                'value': event['minute'] * 60,
                'displayValue': f"{event['minute']}:00"
            },
            'period': {
                'number': 1 if event['minute'] <= 45 else 2
            },
            'scoreAfter': {
                'homeScore': 1 if event['team'] == 'home' else 0,
                'awayScore': 1 if event['team'] == 'away' else 0
            },
            'modified': (datetime.utcnow() - timedelta(minutes=90-event['minute'])).isoformat() + 'Z'
        }

    def _create_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Create ESPN-style general event."""
        return {
            'id': f'4014156817862{event["minute"]:03d}',
            'sequenceNumber': str(event['minute']),
            'type': {
                'id': '23' if event['type'] == 'yellow-card' else '19',
                'text': 'Yellow Card' if event['type'] == 'yellow-card' else 'Substitution'
            },
            'text': f"{event['type'].replace('-', ' ').title()} - {event.get('player', 'Player')}",
            'shortText': f"{event.get('player', 'Player')} {event['type']}",
            'team': {
                'id': '3500' if event['team'] == 'home' else '28716'
            },
            'clock': {
                'value': event['minute'] * 60,
                'displayValue': f"{event['minute']}:00"
            },
            'period': {
                'number': 1 if event['minute'] <= 45 else 2
            }
        }

    def _create_error_response(self, match_id: str) -> Dict[str, Any]:
        """Create error response when match not found."""
        return {
            'error': True,
            'message': f'Match {match_id} not found',
            'statusCode': 404
        }


# Global emulator instance
espn_json_emulator = ESPNJSONEmulator()