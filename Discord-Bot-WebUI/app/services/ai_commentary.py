# app/services/ai_commentary.py

"""
AI Commentary Service

Generates dynamic, authentic ECS supporter commentary for match events using OpenAI GPT.
Replaces static templates with dynamic, contextual responses that sound like real ECS members.
"""

import logging
import os
import asyncio
import aiohttp
import json
from typing import Dict, Any, Optional
from datetime import datetime

from app.models.ai_prompt_config import AIPromptConfig
from app.core.session_manager import managed_session

logger = logging.getLogger(__name__)

class AICommentaryService:
    """Service for generating AI-powered match commentary with ECS supporter personality."""
    
    def __init__(self):
        self.api_key = os.getenv('GPT_API')
        self.api_url = "https://api.openai.com/v1/chat/completions"
        self.model = "gpt-4o-mini"
        self.max_retries = 2
        self.timeout = 5  # seconds
        
        if not self.api_key:
            logger.warning("🤖 AI Commentary DISABLED: GPT_API key not found in environment variables")
        else:
            # Mask API key for security (show first 8 and last 4 chars)
            masked_key = f"{self.api_key[:8]}...{self.api_key[-4:]}" if len(self.api_key) > 12 else "***"
            logger.info(f"🤖 AI Commentary ENABLED: Using {self.model} with key {masked_key}, {self.max_retries} retries, {self.timeout}s timeout")
    
    async def generate_commentary(self, event_data: Dict[str, Any], match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate AI commentary for a match event.
        
        Args:
            event_data: Event details (type, player, team, etc.)
            match_context: Match context (teams, score, time, etc.)
            
        Returns:
            Generated commentary string or None if failed
        """
        if not self.api_key:
            logger.error("🤖 AI Commentary FAILED: No GPT API key configured - check GPT_API in .env")
            return None
            
        event_type = event_data.get('type', 'Unknown')
        team_name = event_data.get('team_name', 'Unknown')
        is_our_team = event_data.get('is_our_team', False)
        
        logger.info(f"🤖 AI Commentary REQUEST: {event_type} by {team_name} (our_team: {is_our_team})")
        
        try:
            prompt = self._create_prompt(event_data, match_context)
            start_time = datetime.now()
            
            for attempt in range(self.max_retries):
                try:
                    logger.debug(f"🤖 AI Commentary attempt {attempt + 1}/{self.max_retries}")
                    commentary = await self._call_openai_api(prompt)
                    if commentary:
                        elapsed = (datetime.now() - start_time).total_seconds()
                        logger.info(f"🤖 AI Commentary SUCCESS: Generated in {elapsed:.2f}s - '{commentary[:80]}{'...' if len(commentary) > 80 else ''}'")
                        return commentary
                    else:
                        logger.warning(f"🤖 AI Commentary attempt {attempt + 1} returned empty response")
                except asyncio.TimeoutError:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.warning(f"🤖 AI Commentary attempt {attempt + 1} TIMEOUT after {elapsed:.2f}s")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
                except aiohttp.ClientError as e:
                    logger.warning(f"🤖 AI Commentary attempt {attempt + 1} CLIENT ERROR: {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
                except Exception as e:
                    logger.warning(f"🤖 AI Commentary attempt {attempt + 1} UNEXPECTED ERROR: {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
            
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.error(f"🤖 AI Commentary FAILED: All {self.max_retries} attempts failed after {elapsed:.2f}s - falling back to static template")
            return None
            
        except Exception as e:
            logger.error(f"🤖 AI Commentary FATAL ERROR: {e}", exc_info=True)
            return None
    
    def _create_prompt(self, event_data: Dict[str, Any], match_context: Dict[str, Any]) -> str:
        """Create the prompt for AI commentary generation."""
        
        # Extract key information
        event_type = event_data.get('type', 'Event')
        player_name = event_data.get('player_name', 'Unknown')
        team_name = event_data.get('team_name', 'Unknown')
        is_our_team = event_data.get('is_our_team', False)
        event_time = event_data.get('time', 'Unknown')
        
        home_team = match_context.get('home_team', {}).get('displayName', 'Home')
        away_team = match_context.get('away_team', {}).get('displayName', 'Away')
        home_score = match_context.get('home_score', '0')
        away_score = match_context.get('away_score', '0')
        
        # Determine opponent and special rivalries
        opponent = away_team if home_team == "Seattle Sounders FC" else home_team
        is_portland = "portland" in opponent.lower() or "timber" in opponent.lower()
        is_vancouver = "vancouver" in opponent.lower() or "whitecap" in opponent.lower()
        
        # Build context-aware prompt
        prompt = f"""You are a passionate member of the Emerald City Supporters (ECS), Seattle Sounders FC's most dedicated fan group. You're commentating live on a match event in a Discord channel with other hardcore Sounders fans.

MATCH CONTEXT:
- Teams: {home_team} vs {away_team}
- Current Score: {home_score}-{away_score}
- Time: {event_time}
- Event: {event_type} by {player_name} ({team_name})

ECS SUPPORTER PERSONALITY:
- Authentic, passionate, and sometimes profane (swearing is fine)
- NEVER sound like AI or corporate - sound like a real supporter
- Use supporter culture language and chants
- Show proper disdain for rivals, especially Portland and Vancouver
- Celebrate our players, mock opponents (within reason)

RIVALRY CONTEXT:"""
        
        if is_portland:
            prompt += """
- This is PORTLAND FUCKING TIMBERS - our biggest rival! Use Portscum, Fuck off Rose City, bonfire references"""
        elif is_vancouver:
            prompt += """
- This is Vancouver Whitecaps - cascadia rival! Show proper disdain"""
        
        prompt += """

EVENT GUIDELINES:"""

        # Add event-specific guidance
        if event_type == "Goal":
            if is_our_team:
                prompt += """
- GOAL FOR SOUNDERS! Be absolutely ecstatic
- Reference "Can you hear [opponent] sing? We don't hear a fucking thing!" if appropriate
- Use celebration language like "GET IN!", "FUCKING YES!", "BOOM!"
- Mention the scorer with love"""
            else:
                prompt += """
- Opponent scored. Be disappointed but not defeated
- Show some resilience and support for the team
- Maybe acknowledge the goal but stay positive about comeback"""
        
        elif event_type in ["Yellow Card", "Red Card"]:
            if is_our_team:
                prompt += """
- Our player got carded. Be frustrated but supportive
- Maybe question the ref or call it soft
- Support the player, show it is not their fault"""
            else:
                prompt += """
- Opponent got carded! Be satisfied and a bit smug
- This is good for us - enjoy their indiscipline
- Reference how dirty/undisciplined they are"""
        
        elif event_type == "Substitution":
            if is_our_team:
                prompt += """
- Our tactical change. Support the decision and new player
- Believe it will help us get the result we need
- Show faith in the coaching"""
            else:
                prompt += """
- They are making changes. Maybe mock their desperation
- Or acknowledge if they are bringing on dangerous players
- Stay confident in our ability to handle it"""
        
        prompt += f"""

RESPONSE REQUIREMENTS:
- Maximum 200 characters (Discord-friendly)  
- 1-2 sentences max
- Sound like a real ECS member, not AI
- Use appropriate emotion for the event
- Include swearing if it fits naturally
- Reference specific rivalries when relevant
- NO corporate speak, NO generic nonsense
- NO hashtags (never use #SoundersPride, #ECS, etc.)
- NO em dashes - use regular dashes (-) or periods
- For hearts use blue and green hearts not other colors
- Avoid obvious AI phrases like "That's what you get", "Let's see if they", "Keep it up"
- Sound like someone actually at the stadium, not watching on TV
- Use natural supporter language, not manufactured excitement
- Avoid cringy corporate enthusiasm

Generate a raw, authentic ECS supporter reaction to this {event_type}:"""

        return prompt
    
    async def _call_openai_api(self, prompt: str) -> Optional[str]:
        """Make the actual API call to OpenAI."""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system", 
                    "content": "You are an authentic soccer supporter generating raw, genuine reactions. Never sound corporate or AI-like."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            "max_tokens": 80,
            "temperature": 0.9,  # High creativity for varied responses
            "top_p": 0.95,
            "frequency_penalty": 0.3,  # Reduce repetition
            "presence_penalty": 0.3
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as response:
                
                if response.status == 200:
                    result = await response.json()
                    commentary = result['choices'][0]['message']['content'].strip()
                    
                    # Clean up any quotes or extra formatting
                    commentary = commentary.strip('"\'')
                    
                    # Log usage stats if available
                    usage = result.get('usage', {})
                    if usage:
                        logger.debug(f"🤖 OpenAI Usage: {usage.get('prompt_tokens', 0)} prompt + {usage.get('completion_tokens', 0)} completion = {usage.get('total_tokens', 0)} total tokens")
                    
                    return commentary
                else:
                    error_text = await response.text()
                    if response.status == 401:
                        logger.error(f"🤖 OpenAI API AUTHENTICATION ERROR {response.status}: Invalid API key - check GPT_API in .env")
                    elif response.status == 429:
                        logger.error(f"🤖 OpenAI API RATE LIMIT ERROR {response.status}: Too many requests - consider reducing frequency")
                    elif response.status == 400:
                        logger.error(f"🤖 OpenAI API BAD REQUEST {response.status}: {error_text}")
                    elif response.status >= 500:
                        logger.error(f"🤖 OpenAI API SERVER ERROR {response.status}: OpenAI servers having issues - {error_text}")
                    else:
                        logger.error(f"🤖 OpenAI API ERROR {response.status}: {error_text}")
                    return None


# Global service instance
_ai_commentary_service = None

def get_ai_commentary_service() -> AICommentaryService:
    """Get the global AI commentary service instance."""
    global _ai_commentary_service
    if _ai_commentary_service is None:
        _ai_commentary_service = AICommentaryService()
    return _ai_commentary_service


async def generate_ai_commentary(event_data: Dict[str, Any], match_context: Dict[str, Any]) -> Optional[str]:
    """
    Convenience function to generate AI commentary.
    
    Args:
        event_data: Event details
        match_context: Match context
        
    Returns:
        Generated commentary or None
    """
    service = get_ai_commentary_service()
    return await service.generate_commentary(event_data, match_context)


class EnhancedAICommentaryService(AICommentaryService):
    """Enhanced AI Commentary Service with pre-match, half-time, and full-time messages."""
    
    def _get_prompt_config(self, prompt_type: str, competition: str = None) -> Optional[AIPromptConfig]:
        """
        Retrieve AI prompt configuration from database.
        
        Args:
            prompt_type: Type of prompt ('pre_match_hype', 'half_time_message', etc.)
            competition: Competition filter ('usa.1', 'mls', etc.)
            
        Returns:
            AIPromptConfig object or None if not found
        """
        try:
            with managed_session() as session:
                # Try to find exact match with competition filter
                if competition:
                    config = session.query(AIPromptConfig).filter(
                        AIPromptConfig.prompt_type == prompt_type,
                        AIPromptConfig.is_active == True,
                        AIPromptConfig.competition_filter.in_([competition.lower(), 'all'])
                    ).first()
                    
                    if config:
                        return config
                
                # Fall back to general config
                config = session.query(AIPromptConfig).filter(
                    AIPromptConfig.prompt_type == prompt_type,
                    AIPromptConfig.is_active == True
                ).first()
                
                return config
                
        except Exception as e:
            logger.error(f"Error retrieving prompt config for {prompt_type}: {e}")
            return None
    
    async def _call_openai_api_with_config(self, prompt: str, config: AIPromptConfig) -> Optional[str]:
        """Make OpenAI API call using database configuration."""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Use database configuration or fallback to defaults
        temperature = config.temperature if config and config.temperature is not None else 0.7
        max_tokens = config.max_tokens if config and config.max_tokens else 150
        system_prompt = config.system_prompt if config and config.system_prompt else "You are an authentic soccer supporter generating genuine reactions."
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system", 
                    "content": system_prompt
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.95,
            "frequency_penalty": 0.3,
            "presence_penalty": 0.3
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as response:
                
                if response.status == 200:
                    result = await response.json()
                    commentary = result['choices'][0]['message']['content'].strip()
                    commentary = commentary.strip('"\'')
                    return commentary
                else:
                    error_text = await response.text()
                    logger.error(f"🤖 OpenAI API ERROR {response.status}: {error_text}")
                    return None
    
    def _render_prompt_template(self, template: str, context: Dict[str, Any]) -> str:
        """
        Render prompt template with context variables.
        
        Args:
            template: Template string with {variable} placeholders
            context: Dictionary of context variables
            
        Returns:
            Rendered prompt string
        """
        try:
            return template.format(**context)
        except KeyError as e:
            logger.warning(f"Missing template variable {e}, using template as-is")
            return template
        except Exception as e:
            logger.error(f"Error rendering template: {e}")
            return template
    
    async def generate_pre_match_hype(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate pre-match hype message 5 minutes before kickoff.
        
        Args:
            match_context: Match details including teams, competition, importance
            
        Returns:
            Generated pre-match hype message or None
        """
        if not self.api_key:
            logger.error("🤖 Pre-match Hype FAILED: No GPT API key configured")
            return None
            
        try:
            # Get database configuration
            competition = match_context.get('competition', 'mls')
            config = self._get_prompt_config('pre_match_hype', competition)
            
            # Create prompt using database template or fallback
            if config and config.user_prompt_template:
                prompt = self._render_prompt_template(config.user_prompt_template, match_context)
            else:
                prompt = self._create_pre_match_prompt(match_context)
            
            logger.info(f"🤖 Generating pre-match hype message (temp: {config.temperature if config else 'default'})")
            
            for attempt in range(self.max_retries):
                try:
                    commentary = await self._call_openai_api_with_config(prompt, config)
                    if commentary:
                        logger.info(f"🤖 Pre-match Hype SUCCESS: '{commentary[:80]}{'...' if len(commentary) > 80 else ''}'")
                        return commentary
                except Exception as e:
                    logger.warning(f"🤖 Pre-match hype attempt {attempt + 1} failed: {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
            
            logger.error("🤖 Pre-match Hype FAILED: All attempts failed")
            return None
            
        except Exception as e:
            logger.error(f"🤖 Pre-match Hype FATAL ERROR: {e}", exc_info=True)
            return None
    
    async def generate_half_time_message(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate contextual half-time message with first half analysis.
        
        Args:
            match_context: Match details including score, events, performance
            
        Returns:
            Generated half-time message or None
        """
        if not self.api_key:
            logger.error("🤖 Half-time Message FAILED: No GPT API key configured")
            return None
            
        try:
            # Get database configuration
            competition = match_context.get('competition', 'mls')
            config = self._get_prompt_config('half_time_message', competition)
            
            # Create prompt using database template or fallback
            if config and config.user_prompt_template:
                prompt = self._render_prompt_template(config.user_prompt_template, match_context)
            else:
                prompt = self._create_half_time_prompt(match_context)
            
            logger.info(f"🤖 Generating half-time analysis message (temp: {config.temperature if config else 'default'})")
            
            for attempt in range(self.max_retries):
                try:
                    commentary = await self._call_openai_api_with_config(prompt, config)
                    if commentary:
                        logger.info(f"🤖 Half-time Message SUCCESS: '{commentary[:80]}{'...' if len(commentary) > 80 else ''}'")
                        return commentary
                except Exception as e:
                    logger.warning(f"🤖 Half-time message attempt {attempt + 1} failed: {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
            
            logger.error("🤖 Half-time Message FAILED: All attempts failed")
            return None
            
        except Exception as e:
            logger.error(f"🤖 Half-time Message FATAL ERROR: {e}", exc_info=True)
            return None
    
    async def generate_full_time_message(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate contextual full-time message with match summary.
        
        Args:
            match_context: Complete match details including final score and key events
            
        Returns:
            Generated full-time message or None
        """
        if not self.api_key:
            logger.error("🤖 Full-time Message FAILED: No GPT API key configured")
            return None
            
        try:
            # Get database configuration
            competition = match_context.get('competition', 'mls')
            config = self._get_prompt_config('full_time_message', competition)
            
            # Create prompt using database template or fallback
            if config and config.user_prompt_template:
                prompt = self._render_prompt_template(config.user_prompt_template, match_context)
            else:
                prompt = self._create_full_time_prompt(match_context)
            
            logger.info(f"🤖 Generating full-time summary message (temp: {config.temperature if config else 'default'})")
            
            for attempt in range(self.max_retries):
                try:
                    commentary = await self._call_openai_api_with_config(prompt, config)
                    if commentary:
                        logger.info(f"🤖 Full-time Message SUCCESS: '{commentary[:80]}{'...' if len(commentary) > 80 else ''}'")
                        return commentary
                except Exception as e:
                    logger.warning(f"🤖 Full-time message attempt {attempt + 1} failed: {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
            
            logger.error("🤖 Full-time Message FAILED: All attempts failed")
            return None
            
        except Exception as e:
            logger.error(f"🤖 Full-time Message FATAL ERROR: {e}", exc_info=True)
            return None
    
    async def generate_match_thread_context(self, match_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate contextual description for match thread creation.
        
        Args:
            match_context: Match details including teams, competition, importance
            
        Returns:
            Generated contextual description or None
        """
        if not self.api_key:
            logger.error("🤖 Thread Context FAILED: No GPT API key configured")
            return None
            
        try:
            # Get database configuration
            competition = match_context.get('competition', 'mls')
            config = self._get_prompt_config('match_thread_context', competition)
            
            # Create prompt using database template or fallback
            if config and config.user_prompt_template:
                prompt = self._render_prompt_template(config.user_prompt_template, match_context)
            else:
                prompt = self._create_thread_context_prompt(match_context)
            
            logger.info(f"🤖 Generating match thread context (temp: {config.temperature if config else 'default'})")
            
            for attempt in range(self.max_retries):
                try:
                    commentary = await self._call_openai_api_with_config(prompt, config)
                    if commentary:
                        logger.info(f"🤖 Thread Context SUCCESS: '{commentary[:80]}{'...' if len(commentary) > 80 else ''}'")
                        return commentary
                except Exception as e:
                    logger.warning(f"🤖 Thread context attempt {attempt + 1} failed: {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
            
            logger.error("🤖 Thread Context FAILED: All attempts failed")
            return None
            
        except Exception as e:
            logger.error(f"🤖 Thread Context FATAL ERROR: {e}", exc_info=True)
            return None
    
    def _create_pre_match_prompt(self, match_context: Dict[str, Any]) -> str:
        """Create prompt for pre-match hype message."""
        
        home_team = match_context.get('home_team', {}).get('displayName', 'Home')
        away_team = match_context.get('away_team', {}).get('displayName', 'Away') 
        opponent = away_team if home_team == "Seattle Sounders FC" else home_team
        competition = match_context.get('competition', 'MLS')
        venue = match_context.get('venue', 'Unknown Venue')
        
        # Determine match importance
        is_playoff = 'playoff' in competition.lower() or 'cup' in competition.lower()
        is_final = 'final' in competition.lower()
        is_portland = "portland" in opponent.lower() or "timber" in opponent.lower()
        is_vancouver = "vancouver" in opponent.lower() or "whitecap" in opponent.lower()
        
        prompt = f"""You are a passionate ECS member posting a pre-match hype message 5 minutes before kickoff. The team is about to take the field and energy is building!

MATCH DETAILS:
- Teams: {home_team} vs {away_team}
- Competition: {competition}
- Venue: {venue}
- It's GAME TIME in 5 minutes!"""

        if is_final:
            prompt += f"\n- THIS IS A FINAL! Massive match with silverware on the line!"
        elif is_playoff:
            prompt += f"\n- This is a playoff match - season on the line!"
            
        if is_portland:
            prompt += f"\n- Against our biggest rivals PORTLAND! Cascadia Cup implications!"
        elif is_vancouver:
            prompt += f"\n- Cascadia rivalry match against Vancouver!"

        prompt += f"""

TONE & STYLE:
- 5 minutes to kickoff energy - fans are pumped and ready!
- Authentic ECS supporter voice - passionate, not corporate
- Build excitement and rally the troops
- Reference the atmosphere, the supporters, the anticipation
- Use supporter culture language
- Swearing is fine if it fits naturally
- NO corporate speak or hashtags

RESPONSE REQUIREMENTS:
- Maximum 280 characters (Twitter-length for Discord)
- 1-3 sentences max
- Capture that pre-kickoff electricity
- Sound like you're in the stadium or pub getting hyped
- Make other supporters want to join the energy

Generate a raw, authentic pre-match hype message for this {competition} match:"""
        
        return prompt
    
    def _create_half_time_prompt(self, match_context: Dict[str, Any]) -> str:
        """Create prompt for half-time analysis message."""
        
        home_team = match_context.get('home_team', {}).get('displayName', 'Home')
        away_team = match_context.get('away_team', {}).get('displayName', 'Away')
        home_score = match_context.get('home_score', '0')
        away_score = match_context.get('away_score', '0')
        opponent = away_team if home_team == "Seattle Sounders FC" else home_team
        
        # Analyze the score situation
        sounders_score = int(home_score) if home_team == "Seattle Sounders FC" else int(away_score)
        opponent_score = int(away_score) if home_team == "Seattle Sounders FC" else int(home_score)
        
        if sounders_score > opponent_score:
            result_context = "We're ahead at the break!"
        elif sounders_score < opponent_score:
            result_context = "We're behind but not out of it!"
        else:
            result_context = "All square at halftime!"
            
        prompt = f"""You are an ECS member posting a half-time analysis as players head to the tunnel. Time to assess the first 45 minutes.

FIRST HALF RESULT:
- Score: {home_team} {home_score}-{away_score} {away_team}
- {result_context}
- Key events and performance in first half

TONE & STYLE:
- Half-time analysis voice - thoughtful but still passionate
- ECS supporter perspective - always backing the team
- Realistic assessment but optimistic about second half
- Reference tactical elements, player performances, momentum
- Show knowledge of the game while staying authentic
- Swearing is fine if it fits the moment

RESPONSE REQUIREMENTS:
- Maximum 280 characters
- 1-2 sentences max  
- Analyze first half performance
- Set expectations for second half
- Keep ECS energy even if result isn't perfect

Generate an authentic half-time analysis for this performance:"""
        
        return prompt
        
    def _create_full_time_prompt(self, match_context: Dict[str, Any]) -> str:
        """Create prompt for full-time summary message."""
        
        home_team = match_context.get('home_team', {}).get('displayName', 'Home')
        away_team = match_context.get('away_team', {}).get('displayName', 'Away')
        home_score = match_context.get('home_score', '0')
        away_score = match_context.get('away_score', '0')
        opponent = away_team if home_team == "Seattle Sounders FC" else home_team
        
        # Analyze final result
        sounders_score = int(home_score) if home_team == "Seattle Sounders FC" else int(away_score)
        opponent_score = int(away_score) if home_team == "Seattle Sounders FC" else int(home_score)
        
        if sounders_score > opponent_score:
            result_context = "Victory! 3 points in the bag!"
        elif sounders_score < opponent_score:
            result_context = "Defeat hurts but we keep fighting!"
        else:
            result_context = "A point earned, could be worse!"
            
        prompt = f"""You are an ECS member posting immediately after the final whistle. Time to sum up the match and result.

FINAL RESULT:
- Final Score: {home_team} {home_score}-{away_score} {away_team}  
- {result_context}
- 90+ minutes of football complete

TONE & STYLE:
- Full-time emotion - joy, disappointment, or mixed feelings
- ECS supporter voice - passionate about the result
- Acknowledge performance good or bad
- Always end with support for the team regardless of result
- Reference key moments or players if relevant
- Raw authentic emotion, not polished analysis

RESPONSE REQUIREMENTS:
- Maximum 280 characters
- 1-2 sentences max
- Capture the immediate post-match feeling  
- React to final result authentically
- Show ongoing support for Sounders

Generate a raw, authentic full-time reaction to this result:"""
        
        return prompt
        
    def _create_thread_context_prompt(self, match_context: Dict[str, Any]) -> str:
        """Create prompt for match thread contextual description."""
        
        home_team = match_context.get('home_team', {}).get('displayName', 'Home')
        away_team = match_context.get('away_team', {}).get('displayName', 'Away')
        competition = match_context.get('competition', 'MLS')
        venue = match_context.get('venue', 'Unknown Venue')
        opponent = away_team if home_team == "Seattle Sounders FC" else home_team
        
        # Determine match importance and storylines
        is_playoff = 'playoff' in competition.lower() or 'cup' in competition.lower()
        is_final = 'final' in competition.lower()
        is_portland = "portland" in opponent.lower() or "timber" in opponent.lower()
        is_vancouver = "vancouver" in opponent.lower() or "whitecap" in opponent.lower()
        is_home = home_team == "Seattle Sounders FC"
        
        prompt = f"""You are creating a contextual description for a new match thread. This should give fans context about why this match matters and what to watch for.

MATCH DETAILS:
- Teams: {home_team} vs {away_team}
- Competition: {competition}
- Venue: {venue}
- Location: {'Home at Lumen Field' if is_home else f'Away at {venue}'}"""

        if is_final:
            prompt += f"\n- FINAL MATCH - Trophy on the line!"
        elif is_playoff:
            prompt += f"\n- Playoff match - season defining moment!"
            
        if is_portland:
            prompt += f"\n- PORTLAND RIVALRY - Cascadia Cup implications!"
        elif is_vancouver:
            prompt += f"\n- Cascadia Derby against Vancouver!"

        prompt += f"""

TONE & STYLE:
- Informative but exciting - set the stage for discussion
- ECS supporter perspective but welcoming to all fans
- Highlight what makes this match significant
- Build anticipation and encourage predictions
- Professional but passionate - this is for match thread creation
- NO swearing in this context (thread welcome message)

RESPONSE REQUIREMENTS:  
- Maximum 200 characters (embed description)
- 1-2 sentences max
- Contextual information about match importance
- Encourage fan discussion and predictions
- Welcome tone for all supporters joining the thread

Generate a welcoming but informative match thread description:"""
        
        return prompt


# Enhanced global service instance
_enhanced_ai_service = None

def get_enhanced_ai_service() -> EnhancedAICommentaryService:
    """Get the enhanced AI commentary service instance."""
    global _enhanced_ai_service
    if _enhanced_ai_service is None:
        _enhanced_ai_service = EnhancedAICommentaryService()
    return _enhanced_ai_service