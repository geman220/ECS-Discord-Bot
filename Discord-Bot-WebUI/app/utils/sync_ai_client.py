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

logger = logging.getLogger(__name__)


class SyncAIClient:
    """Synchronous client for AI commentary service."""
    
    def __init__(self):
        self.service = get_enhanced_ai_service()
        self.timeout = 10  # seconds
    
    def generate_pre_match_hype(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate pre-match hype message synchronously.
        
        Args:
            match_context: Match details for hype generation
            
        Returns:
            Generated hype message or None
        """
        try:
            return self._run_sync(
                self.service.generate_pre_match_hype(match_context)
            )
        except Exception as e:
            logger.error(f"Error generating pre-match hype: {e}")
            return None
    
    def generate_half_time_message(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate half-time analysis message synchronously.
        
        Args:
            match_context: Match details for half-time analysis
            
        Returns:
            Generated half-time message or None
        """
        try:
            return self._run_sync(
                self.service.generate_half_time_message(match_context)
            )
        except Exception as e:
            logger.error(f"Error generating half-time message: {e}")
            return None
    
    def generate_full_time_message(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate full-time summary message synchronously.
        
        Args:
            match_context: Complete match details for summary
            
        Returns:
            Generated full-time message or None
        """
        try:
            return self._run_sync(
                self.service.generate_full_time_message(match_context)
            )
        except Exception as e:
            logger.error(f"Error generating full-time message: {e}")
            return None
    
    def generate_match_thread_context(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate match thread contextual description synchronously.
        
        Args:
            match_context: Match details for context generation
            
        Returns:
            Generated thread context or None
        """
        try:
            return self._run_sync(
                self.service.generate_match_thread_context(match_context)
            )
        except Exception as e:
            logger.error(f"Error generating thread context: {e}")
            return None
    
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

        Args:
            event_context: Event details including type, team, player, score, etc.
            match_history: Previous events in this match for context

        Returns:
            Generated commentary or None
        """
        try:
            return self._generate_dynamic_commentary(event_context, match_history)
        except Exception as e:
            logger.error(f"Error generating dynamic event commentary: {e}")
            # Fallback to simple message
            return self._generate_simple_fallback(event_context)

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

                # Priority 2: Check for event-specific prompts
                if not prompt_config:
                    event_specific_configs = {
                        'goal': 'sounders_goal' if is_sounders_event else 'opponent_goal',
                        'yellow_card': 'card' if is_sounders_event else 'opponent_card',
                        'red_card': 'sounders_red_card' if is_sounders_event else 'opponent_red_card',
                        'substitution': 'substitution'
                    }

                    if event_type in event_specific_configs:
                        specific_type = event_specific_configs[event_type]
                        specific_config = query.filter(
                            AIPromptConfig.prompt_type == specific_type
                        ).first()
                        if specific_config:
                            prompt_config = specific_config

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

                user_prompt = prompt_config.get('user_prompt_template').format(**template_vars)
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

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=prompt_config.get('max_tokens') or 50,
                temperature=prompt_config.get('temperature') or 0.8
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
        """Simple fallback when AI generation fails."""
        try:
            event_type = event_context.get('event_type', 'event')
            player = event_context.get('player', 'Player')
            minute = event_context.get('minute', 0)
            scoring_team = event_context.get('scoring_team', '')

            # Basic team detection for fallback
            is_sounders = 'Seattle' in scoring_team or 'Sounders' in scoring_team

            if event_type == 'goal':
                if is_sounders:
                    return f"⚽ SOUNDERS GOAL! {player} scores in minute {minute}!"
                else:
                    return f"😤 {player} scores. Time for the Sounders to respond!"
            elif event_type == 'yellow_card':
                return f"🟨 Yellow card shown in minute {minute}"
            elif event_type == 'substitution':
                return f"🔄 Substitution in minute {minute}"
            else:
                return f"📋 Match event in minute {minute}"

        except Exception as e:
            logger.error(f"Error in fallback commentary: {e}")
            return "📋 Match event occurred"

    def _generate_neutral_commentary(self, event_context: Dict[str, Any]) -> Optional[str]:
        """Generate neutral commentary when no Sounders involvement."""
        event_type = event_context.get('event_type', 'event')
        player = event_context.get('player', 'Player')
        minute = event_context.get('minute', 0)

        if event_type == 'goal':
            return f"⚽ {player} scores in minute {minute}"
        elif event_type == 'yellow_card':
            return f"🟨 {player} receives yellow card"
        else:
            return f"📋 {event_type.replace('_', ' ').title()}"

    def _generate_goal_commentary(self, context: Dict[str, Any]) -> Optional[str]:
        """Generate contextual goal commentary."""
        try:
            home_team = context.get('home_team', {}).get('displayName', 'Home Team')
            away_team = context.get('away_team', {}).get('displayName', 'Away Team')
            scoring_team = context.get('scoring_team', '')
            player = context.get('player', 'Unknown Player')
            minute = context.get('minute', 0)
            home_score = context.get('home_score', 0)
            away_score = context.get('away_score', 0)

            # Determine if this is good or bad for Sounders (Sounders is ALWAYS our team regardless of home/away)
            is_sounders_goal = 'Seattle' in scoring_team or 'Sounders' in scoring_team

            if is_sounders_goal:
                # HYPED UP commentary for Sounders goals - always celebrate our team!
                commentaries = [
                    f"🚀 GOAL! {player} finds the back of the net for the Sounders! What a finish in the {minute}th minute!",
                    f"⚽ SOUNDERS SCORE! {player} delivers when it matters most! ECS erupts wherever we are!",
                    f"🎯 Clinical finish from {player}! The Sounders faithful are going wild! RAVE GREEN MAGIC in minute {minute}!",
                    f"🔥 {player} strikes! Another brilliant goal for our boys! This is why we love this team!",
                    f"💚 SOUNDERS GOAL! {player} absolutely buries it! The energy is electric wherever Sounders play!",
                    f"⚡ {player} with the goods! That's what happens when you wear the Rave Green with pride!",
                    f"🎉 GET IN! {player} scores for the Sounders! This team never stops fighting!",
                    f"🌟 {player} lights it up! Sounders showing their class in the {minute}th minute!"
                ]
            else:
                # Downplayed, resilient commentary for opponent goals - don't celebrate them
                commentaries = [
                    f"😤 {scoring_team} finds the net through {player}. Not worried - we've seen the Sounders bounce back from tougher spots.",
                    f"⚠️ {player} scores for {scoring_team}. Time for our boys to show what they're made of. Still plenty of match left.",
                    f"🛡️ {scoring_team} gets one, but this Sounders team has character. We've come back from worse than this.",
                    f"💪 {player} scores for {scoring_team}, but we've seen this Sounders squad fight back from worse positions.",
                    f"😮‍💨 {scoring_team} capitalizes, but the Sounders faithful know this team doesn't quit. Let's go boys!",
                    f"📝 {player} puts one away for {scoring_team}. The Sounders have answered back before, they'll do it again.",
                    f"🔄 {scoring_team} scores through {player}. Time for the Sounders to dig deep and show their quality."
                ]

            # Select based on minute for variety
            return commentaries[minute % len(commentaries)]

        except Exception as e:
            logger.error(f"Error generating goal commentary: {e}")
            return f"⚽ GOAL! {context.get('player', 'Unknown')} scores in minute {context.get('minute', 0)}!"

    def _generate_card_commentary(self, context: Dict[str, Any], card_type: str) -> Optional[str]:
        """Generate card event commentary."""
        try:
            player = context.get('player', 'Unknown Player')
            team = context.get('team', 'Unknown Team')
            minute = context.get('minute', 0)

            is_sounders_card = 'Seattle' in team or 'Sounders' in team

            if card_type == 'yellow':
                if is_sounders_card:
                    # Defensive commentary for Sounders yellows
                    commentaries = [
                        f"🟨 {player} picks up a yellow in the {minute}th minute. Just gotta stay smart now.",
                        f"⚠️ Yellow card for {player}. No worries - our boys know how to manage the game.",
                        f"🟨 Caution for {player} in minute {minute}. Part of the game, keep the intensity up!",
                        f"📋 {player} gets booked. The Sounders can handle playing with discipline."
                    ]
                    return commentaries[minute % len(commentaries)]
                else:
                    # Matter-of-fact for opponent yellows
                    commentaries = [
                        f"🟨 {player} from {team} picks up a yellow card in the {minute}th minute.",
                        f"⚠️ Caution shown to {player} from {team}. They need to be careful now.",
                        f"🟨 {team}'s {player} gets booked in minute {minute}. Good to see the ref keeping control.",
                        f"📋 Yellow card for {player} from {team}. That's what happens when you get too aggressive."
                    ]
                    return commentaries[minute % len(commentaries)]
            else:
                # Red cards
                if is_sounders_card:
                    return f"🟥 Tough break - {player} gets sent off in the {minute}th minute. The boys will need to dig deep now."
                else:
                    return f"🟥 RED CARD! {player} from {team} is sent off in the {minute}th minute! Huge advantage for the Sounders!"

        except Exception as e:
            logger.error(f"Error generating card commentary: {e}")
            return f"📋 Card shown in minute {context.get('minute', 0)}"

    def _generate_substitution_commentary(self, context: Dict[str, Any]) -> Optional[str]:
        """Generate substitution commentary."""
        try:
            team = context.get('team', 'Unknown Team')
            minute = context.get('minute', 0)

            if 'Seattle' in team or 'Sounders' in team:
                # Positive commentary for Sounders subs
                commentaries = [
                    f"🔄 Tactical change for the Sounders in the {minute}th minute. Fresh legs to make an impact!",
                    f"⚡ Smart move by the coaching staff! New energy coming on for the Sounders in minute {minute}!",
                    f"🔥 The Sounders depth showing! Fresh legs ready to make a difference!",
                    f"💚 Substitution for our boys - always looking to improve and push forward!"
                ]
                return commentaries[minute % len(commentaries)]
            else:
                # Neutral/downplayed commentary for opponent subs
                commentaries = [
                    f"🔄 {team} makes a substitution in minute {minute}. They're trying to change things up.",
                    f"📝 {team} bringing on fresh legs. The Sounders will be ready for whatever they throw at us.",
                    f"🔄 Tactical change for {team}. Our boys have been dealing with their threats well so far.",
                    f"⚖️ {team} switches things up in minute {minute}. Time for the Sounders to adapt and respond."
                ]
                return commentaries[minute % len(commentaries)]

        except Exception as e:
            logger.error(f"Error generating substitution commentary: {e}")
            return f"🔄 Substitution in minute {context.get('minute', 0)}"

    def _generate_general_commentary(self, context: Dict[str, Any]) -> Optional[str]:
        """Generate general event commentary."""
        try:
            minute = context.get('minute', 0)
            event_type = context.get('event_type', 'event')
            return f"📋 {event_type.replace('_', ' ').title()} in minute {minute}"
        except Exception as e:
            logger.error(f"Error generating general commentary: {e}")
            return "📋 Match event occurred"
    
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
        
        # Check for eventlet environment
        try:
            import eventlet
            if eventlet.patcher.is_monkey_patched('thread'):
                import eventlet.tpool
                return eventlet.tpool.execute(run_in_new_loop)
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