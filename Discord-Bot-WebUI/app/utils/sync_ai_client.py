# app/utils/sync_ai_client.py

"""
Synchronous AI Client for Enhanced Commentary

Provides synchronous wrappers around the AI commentary service to work
with the V2 synchronous live reporting architecture.
"""

import logging
import asyncio
import concurrent.futures
from typing import Dict, Any, Optional, List
from app.services.ai_commentary import get_enhanced_ai_service
from app.models.ai_prompt_config import AIPromptConfig
from app.utils.task_session_manager import task_session
from app.utils.commentary_validator import (
    validate_and_record, generate_with_validation,
    CommentaryType, get_tracker
)

logger = logging.getLogger(__name__)


class SyncAIClient:
    """Synchronous client for AI commentary service."""
    
    def __init__(self):
        self.service = get_enhanced_ai_service()
        self.timeout = 10  # seconds
    
    def generate_pre_match_hype(self, match_context: Dict[str, Any]) -> Optional[str]:
        """Generate pre-match hype message with validation."""
        def _generate():
            return self._run_sync(self.service.generate_pre_match_hype(match_context))

        result = generate_with_validation(
            generate_fn=_generate,
            fallback_fn=lambda: None,
            commentary_type=CommentaryType.PRE_MATCH,
            max_attempts=2,
            strict=True
        )
        return result or None

    def generate_half_time_message(self, match_context: Dict[str, Any]) -> Optional[str]:
        """Generate half-time message with validation."""
        def _generate():
            return self._run_sync(self.service.generate_half_time_message(match_context))

        result = generate_with_validation(
            generate_fn=_generate,
            fallback_fn=lambda: None,
            commentary_type=CommentaryType.HALFTIME,
            max_attempts=2,
            strict=True
        )
        return result or None

    def generate_full_time_message(self, match_context: Dict[str, Any]) -> Optional[str]:
        """Generate full-time message with validation."""
        def _generate():
            return self._run_sync(self.service.generate_full_time_message(match_context))

        result = generate_with_validation(
            generate_fn=_generate,
            fallback_fn=lambda: None,
            commentary_type=CommentaryType.FULLTIME,
            max_attempts=2,
            strict=True
        )
        return result or None

    def generate_match_thread_context(self, match_context: Dict[str, Any]) -> Optional[str]:
        """Generate match thread context with strict validation for thread descriptions."""
        def _generate():
            return self._run_sync(self.service.generate_match_thread_context(match_context))

        result = generate_with_validation(
            generate_fn=_generate,
            fallback_fn=lambda: None,
            commentary_type=CommentaryType.THREAD_CONTEXT,
            max_attempts=2,
            strict=True  # Enforce AI-ism detection for thread descriptions
        )
        return result or None
    
    def generate_commentary(self, event_data: Dict[str, Any], match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate regular event commentary synchronously.

        Args:
            event_data: Event details
            match_context: Match context

        Returns:
            Generated commentary or None
        """
        try:
            return self._run_sync(
                self.service.generate_commentary(event_data, match_context)
            )
        except Exception as e:
            logger.error(f"Error generating event commentary: {e}")
            return None

    def generate_match_event_commentary(self, event_context: Dict[str, Any], match_history: Optional[List[Dict]] = None) -> Optional[str]:
        """
        Generate dynamic, contextually-aware live event commentary using ChatGPT API.
        Validates output against tone rules and anti-repetition before returning.

        Args:
            event_context: Event details including type, team, player, score, etc.
            match_history: Previous events in this match for context

        Returns:
            Validated commentary or fallback
        """
        # Extract match_id for anti-repetition tracking
        match_id = str(event_context.get('match_id', ''))

        return generate_with_validation(
            generate_fn=lambda: self._generate_dynamic_commentary(event_context, match_history),
            fallback_fn=lambda: self._generate_simple_fallback(event_context),
            commentary_type=CommentaryType.MATCH_EVENT,
            match_id=match_id if match_id else None,
            max_attempts=2,
            strict=True
        )

    def _get_prompt_config(self, event_type: str, event_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get appropriate prompt configuration from database based on event type and context."""
        try:
            # Try to use Flask app context if available
            try:
                from flask import current_app
                # If we have Flask context, proceed normally
                _ = current_app.name
            except (ImportError, RuntimeError):
                # No Flask context available, return None to use fallback
                logger.debug("No Flask app context for database prompt config, using defaults")
                return None

            with task_session() as session:
                # Determine team involvement for filtering
                # Handle both string and dict formats
                home_team_data = event_context.get('home_team', '')
                away_team_data = event_context.get('away_team', '')

                if isinstance(home_team_data, dict):
                    home_team = home_team_data.get('displayName', '')
                else:
                    home_team = str(home_team_data)

                if isinstance(away_team_data, dict):
                    away_team = away_team_data.get('displayName', '')
                else:
                    away_team = str(away_team_data)
                is_sounders_match = 'Seattle' in home_team or 'Sounders' in home_team or 'Seattle' in away_team or 'Sounders' in away_team

                # Check if this is a rivalry match
                rivalry_teams = []
                if 'Portland' in home_team or 'Portland' in away_team or 'Timbers' in home_team or 'Timbers' in away_team:
                    rivalry_teams.append('portland')
                if 'Vancouver' in home_team or 'Vancouver' in away_team or 'Whitecaps' in home_team or 'Whitecaps' in away_team:
                    rivalry_teams.append('vancouver')

                # Determine if this event is for Sounders or opponent
                is_sounders_event = False
                scoring_team = event_context.get('scoring_team', '')
                team = event_context.get('team', '')
                if event_type == 'goal':
                    is_sounders_event = 'Seattle' in scoring_team or 'Sounders' in scoring_team
                elif event_type in ['yellow_card', 'red_card', 'substitution']:
                    is_sounders_event = 'Seattle' in team or 'Sounders' in team

                # Build query for appropriate prompt
                query = session.query(AIPromptConfig).filter(
                    AIPromptConfig.is_active == True
                )

                prompt_config = None

                # Priority 1: Check for rivalry-specific prompts
                if rivalry_teams and event_type == 'goal':
                    rivalry_config = query.filter(
                        AIPromptConfig.prompt_type == 'rivalry'
                    ).first()
                    if rivalry_config:
                        prompt_config = rivalry_config

                # Priority 2: Check for event-specific prompts with fallback chain
                # Try team-specific type first, then base type, then match_commentary
                if not prompt_config:
                    event_specific_configs = {
                        'goal': 'sounders_goal' if is_sounders_event else 'opponent_goal',
                        'yellow_card': 'card' if is_sounders_event else 'opponent_card',
                        'red_card': 'sounders_red_card' if is_sounders_event else 'opponent_red_card',
                        'substitution': 'substitution' if is_sounders_event else 'opponent_substitution'
                    }

                    # Base type fallbacks when team-specific config is inactive/missing
                    base_type_fallbacks = {
                        'sounders_goal': 'goal',
                        'opponent_goal': 'goal',
                        'opponent_card': 'card',
                        'opponent_yellow_card': 'card',
                        'yellow_card': 'card',
                        'opponent_red_card': 'card',
                        'sounders_red_card': 'card',
                        'opponent_substitution': 'substitution',
                        'sounders_penalty_miss': 'match_commentary',
                        'opponent_penalty_miss': 'match_commentary',
                    }

                    if event_type in event_specific_configs:
                        specific_type = event_specific_configs[event_type]
                        base_type = base_type_fallbacks.get(specific_type)

                        # Try team-specific first, then base type
                        for try_type in [specific_type, base_type]:
                            if try_type and not prompt_config:
                                config = query.filter(
                                    AIPromptConfig.prompt_type == try_type
                                ).first()
                                if config:
                                    prompt_config = config

                # Priority 3: Fall back to general match commentary
                if not prompt_config:
                    general_config = query.filter(
                        AIPromptConfig.prompt_type == 'match_commentary'
                    ).first()
                    prompt_config = general_config

                # Extract data while session is active to avoid detached instance errors
                if prompt_config:
                    return {
                        'system_prompt': prompt_config.system_prompt,
                        'user_prompt_template': prompt_config.user_prompt_template,
                        'max_tokens': prompt_config.max_tokens,
                        'temperature': prompt_config.temperature,
                        'prompt_type': prompt_config.prompt_type
                    }

                return None

        except Exception as e:
            logger.error(f"Error retrieving prompt config for {event_type}: {e}")
            return None

    def _generate_dynamic_commentary(self, event_context: Dict[str, Any], match_history: Optional[List[Dict]] = None) -> Optional[str]:
        """Generate dynamic commentary using ChatGPT API with database-configured prompts."""
        try:
            import openai
            import os

            # Get OpenAI API key - check multiple possible env var names
            api_key = os.getenv('OPENAI_API_KEY') or os.getenv('GPT_API') or os.getenv('GPT_API_KEY')
            if not api_key:
                logger.warning("🤖 AI Commentary DISABLED: GPT_API key not found in environment variables")
                return self._generate_simple_fallback(event_context)

            # Get appropriate prompt configuration from database
            event_type = event_context.get('event_type', 'unknown')
            prompt_config = self._get_prompt_config(event_type, event_context)

            if not prompt_config:
                logger.warning(f"No prompt configuration found for {event_type}, using fallback")
                return self._generate_simple_fallback(event_context)

            # Extract event details - handle both string and dict formats
            event_type = event_context.get('event_type', 'unknown')

            # Handle home_team format
            home_team_data = event_context.get('home_team', 'Home Team')
            if isinstance(home_team_data, dict):
                home_team = home_team_data.get('displayName', 'Home Team')
            else:
                home_team = str(home_team_data)

            # Handle away_team format
            away_team_data = event_context.get('away_team', 'Away Team')
            if isinstance(away_team_data, dict):
                away_team = away_team_data.get('displayName', 'Away Team')
            else:
                away_team = str(away_team_data)
            scoring_team = event_context.get('scoring_team', '')
            player = event_context.get('player', 'Unknown Player')
            minute = event_context.get('minute', 0)
            home_score = event_context.get('home_score', 0)
            away_score = event_context.get('away_score', 0)

            # Determine if Sounders is involved and which team they are
            sounders_is_home = 'Seattle' in home_team or 'Sounders' in home_team
            sounders_is_away = 'Seattle' in away_team or 'Sounders' in away_team

            if sounders_is_home:
                sounders_team = home_team
                opponent_team = away_team
                sounders_score = home_score
                opponent_score = away_score
            elif sounders_is_away:
                sounders_team = away_team
                opponent_team = home_team
                sounders_score = away_score
                opponent_score = home_score
            else:
                # No Sounders in this match - neutral commentary
                return self._generate_neutral_commentary(event_context)

            # Determine if this event favors Sounders
            is_sounders_event = False
            if event_type == 'goal':
                is_sounders_event = 'Seattle' in scoring_team or 'Sounders' in scoring_team
            elif event_type in ['yellow_card', 'red_card', 'substitution']:
                event_team = event_context.get('team', '')
                is_sounders_event = 'Seattle' in event_team or 'Sounders' in event_team

            # Build comprehensive match context using new context builder
            match_context = self._build_match_context_string(event_context, match_history)
            history_context = ""  # Already included in match_context

            # Use database-configured prompt system instead of hardcoded prompts
            system_prompt = prompt_config.get('system_prompt') or "You are a passionate Seattle Sounders supporter providing biased live commentary. Always favor the Sounders and downplay opponents."

            # Build user prompt from template if available
            if prompt_config.get('user_prompt_template'):
                # Format score string
                score_string = f"{sounders_team if sounders_is_home or sounders_is_away else 'Seattle Sounders'} {sounders_score if sounders_is_home or sounders_is_away else home_score} - {opponent_score if sounders_is_home or sounders_is_away else away_score} {opponent_team if sounders_is_home or sounders_is_away else 'opponent'}"

                # Build event description for templates
                event_desc = event_context.get('description', f"{event_type.replace('_', ' ').title()} by {player} in minute {minute}")

                # Build template variables dictionary
                template_vars = {
                    # Standard variables
                    'player': player,
                    'minute': minute,
                    'event_type': event_type,
                    'sounders_team': sounders_team if sounders_is_home or sounders_is_away else "Seattle Sounders",
                    'opponent_team': opponent_team if sounders_is_home or sounders_is_away else "opponent",
                    'home_team': home_team,
                    'away_team': away_team,
                    'scoring_team': scoring_team,
                    'match_context': match_context,
                    # Additional common variables that might be in templates
                    'team': event_context.get('team', opponent_team if sounders_is_home or sounders_is_away else "opponent"),
                    'description': event_context.get('description', f"{event_type} event in minute {minute}"),
                    'event_description': event_desc,
                    # Score variables from event context
                    'home_score': event_context.get('home_score', home_score),
                    'away_score': event_context.get('away_score', away_score),
                    'history_context': history_context,
                    'is_sounders_event': is_sounders_event,
                    'sounders_score': sounders_score if sounders_is_home or sounders_is_away else 0,
                    'opponent_score': opponent_score if sounders_is_home or sounders_is_away else 0,
                    # Database template variables
                    'athlete_name': player,
                    'clock': f"{minute}'",
                    'score': score_string,
                    # Event-specific variables
                    'team_name': event_context.get('team', ''),
                    'events': event_context.get('description', ''),
                }

                # Add goal-specific context
                if event_type == 'goal':
                    # Determine match situation after this goal
                    if is_sounders_event:
                        new_sounders = sounders_score + 1 if sounders_is_home or sounders_is_away else 1
                        new_opponent = opponent_score if sounders_is_home or sounders_is_away else home_score
                    else:
                        new_sounders = sounders_score if sounders_is_home or sounders_is_away else away_score
                        new_opponent = opponent_score + 1 if sounders_is_home or sounders_is_away else home_score + 1

                    if new_sounders > new_opponent:
                        match_situation = "leading" if is_sounders_event else "behind"
                    elif new_sounders < new_opponent:
                        match_situation = "behind" if is_sounders_event else "leading"
                    else:
                        match_situation = "tied"

                    template_vars['match_situation'] = match_situation

                # Add substitution-specific variables
                elif event_type == 'substitution':
                    template_vars.update({
                        'player_on': event_context.get('player_on', event_context.get('player', '')),
                        'player_off': event_context.get('player_off', ''),
                        'player_in': event_context.get('player_on', event_context.get('player', '')),
                        'player_out': event_context.get('player_off', '')
                    })

                # Add card-specific variables
                elif event_type in ['yellow_card', 'red_card']:
                    template_vars.update({
                        'reason': event_context.get('reason', 'Foul'),
                        'card_type': event_type.replace('_', ' ').title()
                    })

                # Add halftime/fulltime specific variables with match context
                elif event_type in ['halftime', 'half_time', 'fulltime', 'full_time']:
                    # Determine match situation for context
                    sounders_score = sounders_score if sounders_is_home or sounders_is_away else away_score
                    opponent_score = opponent_score if sounders_is_home or sounders_is_away else home_score

                    if sounders_score > opponent_score:
                        match_situation = "leading"
                    elif sounders_score < opponent_score:
                        match_situation = "behind"
                    else:
                        match_situation = "tied"

                    template_vars.update({
                        'home_score': home_score,
                        'away_score': away_score,
                        'sounders_score': sounders_score,
                        'opponent_score': opponent_score,
                        'match_situation': match_situation,
                        'competition': event_context.get('competition', 'MLS')
                    })

                # Use format_map with a defaultdict to avoid KeyError on unknown template vars
                from collections import defaultdict
                safe_vars = defaultdict(lambda: '', template_vars)
                user_prompt = prompt_config.get('user_prompt_template').format_map(safe_vars)
            else:
                # Fallback to simple prompt construction
                if event_type == 'goal':
                    if is_sounders_event:
                        user_prompt = f"SOUNDERS GOAL: {player} scored in minute {minute}! Write exciting 1-2 sentence commentary."
                    else:
                        user_prompt = f"Opponent goal: {player} scored for {opponent_team} in minute {minute}. Write disappointed but resilient commentary."
                elif event_type in ['yellow_card', 'red_card']:
                    if is_sounders_event:
                        user_prompt = f"Sounders {event_type.replace('_', ' ')}: {player} in minute {minute}. Write defensive commentary."
                    else:
                        user_prompt = f"Opponent {event_type.replace('_', ' ')}: {player} in minute {minute}. Write neutral commentary."
                elif event_type == 'substitution':
                    if is_sounders_event:
                        user_prompt = f"Sounders substitution in minute {minute}. Write positive commentary about fresh legs."
                    else:
                        user_prompt = f"Opponent substitution in minute {minute}. Write confident commentary."
                else:
                    user_prompt = f"{event_type} in minute {minute}. Write brief Sounders-biased commentary."

# Debug logging removed for production

            # Call OpenAI API with database-configured parameters
            client = openai.OpenAI(api_key=api_key)

            model = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=prompt_config.get('max_tokens') or 60,
                temperature=prompt_config.get('temperature') or 0.4
            )

            commentary = response.choices[0].message.content.strip()

            # Post-processing: Remove any hashtags that slipped through
            import re
            # Remove hashtags (# followed by word characters)
            commentary = re.sub(r'#\w+', '', commentary)
            # Clean up extra spaces
            commentary = re.sub(r'\s+', ' ', commentary).strip()

            # Clean up and validate - respect Discord embed limits
            # Discord embed description limit is 4096 characters
            if len(commentary) > 4000:
                commentary = commentary[:3997] + "..."

            logger.info(f"Generated dynamic commentary for {event_type}: {commentary}")
            return commentary

        except Exception as e:
            logger.error(f"Error generating dynamic commentary: {e}")
            return self._generate_simple_fallback(event_context)

    def _build_match_context_string(self, event_context: Dict[str, Any], match_history: Optional[List[Dict]] = None) -> str:
        """Build context string from current match state and history."""
        try:
            context_parts = []

            # Current score context
            home_score = event_context.get('home_score', 0)
            away_score = event_context.get('away_score', 0)
            home_team = event_context.get('home_team', 'Home')
            away_team = event_context.get('away_team', 'Away')

            # Handle cases where team names might be nested in objects
            if isinstance(home_team, dict):
                home_team = home_team.get('displayName', 'Home')
            if isinstance(away_team, dict):
                away_team = away_team.get('displayName', 'Away')

            context_parts.append(f"Current Score: {home_team} {home_score} - {away_score} {away_team}")

            # Match history context
            if match_history:
                recent_events = []
                yellow_cards = {}  # Track yellow cards per player

                for event in match_history[-5:]:  # Last 5 events
                    event_type = event.get('event_type', '')
                    minute = event.get('minute', 0)
                    player = event.get('player', '')
                    team = event.get('team', '')

                    if event_type == 'goal':
                        recent_events.append(f"Goal by {player} ({team}) in {minute}'")
                    elif event_type == 'yellow_card':
                        # Track yellow cards for second yellow detection
                        if player not in yellow_cards:
                            yellow_cards[player] = 0
                        yellow_cards[player] += 1

                        if yellow_cards[player] == 2:
                            recent_events.append(f"SECOND yellow for {player} ({team}) in {minute}' - RED CARD!")
                        else:
                            recent_events.append(f"Yellow card for {player} ({team}) in {minute}'")
                    elif event_type == 'substitution':
                        player_out = event.get('player_out', player)
                        player_in = event.get('player_in', 'substitute')
                        recent_events.append(f"Sub: {player_out} off, {player_in} on ({team}) in {minute}'")

                if recent_events:
                    context_parts.append(f"Recent Events: {'; '.join(recent_events)}")

            return "\nMATCH CONTEXT:\n" + "\n".join(context_parts) + "\n"

        except Exception as e:
            logger.error(f"Error building match context: {e}")
            return "\nMATCH CONTEXT: Live match in progress\n"

    def _generate_simple_fallback(self, event_context: Dict[str, Any]) -> Optional[str]:
        """Simple fallback when AI generation fails. Matches human supporter tone."""
        try:
            event_type = event_context.get('event_type', 'event')
            player = event_context.get('player', 'Player')
            minute = event_context.get('minute', 0)
            scoring_team = event_context.get('scoring_team', '')

            is_sounders = 'Seattle' in scoring_team or 'Sounders' in scoring_team

            if event_type == 'goal':
                if is_sounders:
                    return f"{player} scores. {minute}'. Yes."
                else:
                    return f"{player} scores for {scoring_team}. {minute}'. Need to respond."
            elif event_type == 'yellow_card':
                return f"Yellow card for {player}. {minute}'."
            elif event_type == 'red_card':
                return f"Red card. {player} off. {minute}'."
            elif event_type == 'substitution':
                player_on = event_context.get('player_on', player)
                player_off = event_context.get('player_off', '')
                if player_off:
                    return f"{player_on} on for {player_off}. {minute}'."
                return f"Sub: {player}. {minute}'."
            else:
                return f"{event_type.replace('_', ' ').title()}. {minute}'."

        except Exception as e:
            logger.error(f"Error in fallback commentary: {e}")
            return None

    def _generate_neutral_commentary(self, event_context: Dict[str, Any]) -> Optional[str]:
        """Generate neutral commentary when no Sounders involvement."""
        event_type = event_context.get('event_type', 'event')
        player = event_context.get('player', 'Player')
        minute = event_context.get('minute', 0)

        if event_type == 'goal':
            return f"{player} scores. {minute}'."
        elif event_type == 'yellow_card':
            return f"Yellow for {player}. {minute}'."
        else:
            return f"{event_type.replace('_', ' ').title()}. {minute}'."

    def _generate_goal_commentary(self, context: Dict[str, Any]) -> Optional[str]:
        """Generate goal commentary - terse, human, Sounders-biased."""
        try:
            scoring_team = context.get('scoring_team', '')
            player = context.get('player', 'Unknown')
            minute = context.get('minute', 0)

            is_sounders_goal = 'Seattle' in scoring_team or 'Sounders' in scoring_team

            if is_sounders_goal:
                commentaries = [
                    f"{player} scores. {minute}'. Get in.",
                    f"{player} puts it away. {minute}'. Yes.",
                    f"{player} finishes it. {minute}'.",
                    f"Goal. {player}. {minute}'. Lovely stuff.",
                    f"{player} with the goal. {minute}'. That'll do.",
                ]
            else:
                commentaries = [
                    f"{player} scores for {scoring_team}. {minute}'. Need to respond.",
                    f"{scoring_team} score through {player}. {minute}'. Sort it out.",
                    f"{player} puts one in. {minute}'. Sloppy from us.",
                    f"{scoring_team} goal. {player}. {minute}'. Come on.",
                    f"{player} scores. {minute}'. Got to be better than that.",
                ]

            return commentaries[minute % len(commentaries)]

        except Exception as e:
            logger.error(f"Error generating goal commentary: {e}")
            return f"{context.get('player', 'Goal')} scores. {context.get('minute', '')}'."

    def _generate_card_commentary(self, context: Dict[str, Any], card_type: str) -> Optional[str]:
        """Generate card commentary - terse, factual."""
        try:
            player = context.get('player', 'Unknown')
            team = context.get('team', 'Unknown')
            minute = context.get('minute', 0)

            is_sounders_card = 'Seattle' in team or 'Sounders' in team

            if card_type == 'yellow':
                if is_sounders_card:
                    commentaries = [
                        f"Yellow for {player}. {minute}'. Didn't need to do that.",
                        f"{player} booked. {minute}'. Stay smart.",
                        f"Yellow card. {player}. {minute}'.",
                    ]
                else:
                    commentaries = [
                        f"Yellow for {player}. {minute}'. Been getting away with it.",
                        f"{player} finally gets booked. {minute}'.",
                        f"Card for {player} from {team}. {minute}'.",
                    ]
                return commentaries[minute % len(commentaries)]
            else:
                if is_sounders_card:
                    return f"Red card. {player} off. {minute}'. Rough."
                else:
                    return f"Red card. {player} off. {minute}'. Couldn't happen to a nicer guy."

        except Exception as e:
            logger.error(f"Error generating card commentary: {e}")
            return f"Card for {context.get('player', 'player')}. {context.get('minute', '')}'."

    def _generate_substitution_commentary(self, context: Dict[str, Any]) -> Optional[str]:
        """Generate sub commentary - brief and factual."""
        try:
            team = context.get('team', 'Unknown')
            minute = context.get('minute', 0)

            if 'Seattle' in team or 'Sounders' in team:
                commentaries = [
                    f"Sounders sub. {minute}'.",
                    f"Change for Seattle. {minute}'.",
                    f"Sounders make a switch. {minute}'.",
                ]
            else:
                commentaries = [
                    f"{team} sub. {minute}'.",
                    f"Change for {team}. {minute}'.",
                    f"{team} make a switch. {minute}'.",
                ]
            return commentaries[minute % len(commentaries)]

        except Exception as e:
            logger.error(f"Error generating substitution commentary: {e}")
            team = context.get('team', 'Unknown')
            return f"{team} sub. {context.get('minute', 0)}'."

    def _generate_general_commentary(self, context: Dict[str, Any]) -> Optional[str]:
        """Generate general event commentary."""
        try:
            minute = context.get('minute', 0)
            event_type = context.get('event_type', 'event')
            return f"{event_type.replace('_', ' ').title()}. {minute}'."
        except Exception as e:
            logger.error(f"Error generating general commentary: {e}")
            return None
    
    def _run_sync(self, coroutine) -> Any:
        """
        Run an async coroutine synchronously with proper event loop handling.
        
        Args:
            coroutine: The async coroutine to run
            
        Returns:
            Result of the coroutine execution
        """
        def run_in_new_loop():
            """Run the coroutine in a new event loop."""
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(coroutine)
            finally:
                new_loop.close()
        
        # Check for gevent environment
        try:
            from gevent import monkey
            if monkey.is_module_patched('threading'):
                from gevent.threadpool import ThreadPool
                pool = ThreadPool(1)
                return pool.spawn(run_in_new_loop).get()
        except ImportError:
            pass
        
        try:
            # Check if there's already a running event loop
            asyncio.get_running_loop()
            # If we get here, use a thread pool
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_in_new_loop)
                return future.result(timeout=self.timeout)
        except RuntimeError:
            # No running event loop - run directly
            return run_in_new_loop()


# Global client instance
_sync_ai_client = None

def get_sync_ai_client() -> SyncAIClient:
    """Get the global synchronous AI client instance."""
    global _sync_ai_client
    if _sync_ai_client is None:
        _sync_ai_client = SyncAIClient()
    return _sync_ai_client