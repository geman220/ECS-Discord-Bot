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