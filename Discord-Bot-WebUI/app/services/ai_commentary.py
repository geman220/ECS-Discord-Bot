# app/services/ai_commentary.py

"""
AI Commentary Service

Generates dynamic, authentic ECS supporter commentary for match events using Anthropic Claude.
Replaces static templates with dynamic, contextual responses that sound like real ECS members.
"""

import logging
import os
import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime

import anthropic

from app.models.ai_prompt_config import AIPromptConfig
from app.core.session_manager import managed_session
from app.utils.commentary_validator import (
    validate_and_record, async_generate_with_validation,
    CommentaryType
)

logger = logging.getLogger(__name__)

class AICommentaryService:
    """Service for generating AI-powered match commentary with ECS supporter personality."""
    
    def __init__(self):
        self.api_key = os.getenv('CLAUDE_API') or os.getenv('ANTHROPIC_API_KEY')
        self.model = os.getenv('ANTHROPIC_MODEL', 'claude-haiku-4-5')
        self.max_retries = 2
        self.timeout = 10  # seconds

        if not self.api_key:
            logger.warning("🤖 AI Commentary DISABLED: CLAUDE_API key not found in environment variables")
        else:
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
            logger.error("🤖 AI Commentary FAILED: No CLAUDE_API key configured - check CLAUDE_API in .env")
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
                        # Validate against tone rules before accepting
                        result = validate_and_record(
                            commentary,
                            CommentaryType.MATCH_EVENT,
                            match_id=None  # No match_id at this layer
                        )
                        if result.is_valid:
                            elapsed = (datetime.now() - start_time).total_seconds()
                            logger.info(f"🤖 AI Commentary SUCCESS: Generated in {elapsed:.2f}s - '{result.text[:80]}{'...' if len(result.text) > 80 else ''}'")
                            return result.text
                        else:
                            logger.warning(f"🤖 AI Commentary attempt {attempt + 1} rejected: {result.rejection_reason}")
                            # Don't sleep, try again immediately with a fresh generation
                            continue
                    else:
                        logger.warning(f"🤖 AI Commentary attempt {attempt + 1} returned empty response")
                except asyncio.TimeoutError:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.warning(f"🤖 AI Commentary attempt {attempt + 1} TIMEOUT after {elapsed:.2f}s")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
                except anthropic.APIConnectionError as e:
                    logger.warning(f"🤖 AI Commentary attempt {attempt + 1} CONNECTION ERROR: {e}")
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

        event_type = event_data.get('type', 'Event')
        player_name = event_data.get('player_name', 'Unknown')
        team_name = event_data.get('team_name', 'Unknown')
        is_our_team = event_data.get('is_our_team', False)
        event_time = event_data.get('time', '')
        event_text = event_data.get('text', '')

        home_team = match_context.get('home_team', {}).get('displayName', 'Home')
        away_team = match_context.get('away_team', {}).get('displayName', 'Away')
        home_score = match_context.get('home_score', '0')
        away_score = match_context.get('away_score', '0')
        score = f"{home_score}-{away_score}"

        opponent = away_team if home_team == "Seattle Sounders FC" else home_team
        is_portland = "portland" in opponent.lower() or "timber" in opponent.lower()
        is_vancouver = "vancouver" in opponent.lower() or "whitecap" in opponent.lower()

        # Build rivalry context line
        rivalry = ""
        if is_portland:
            rivalry = "This is Portland. Be hostile."
        elif is_vancouver:
            rivalry = "This is Vancouver. Show dislike."

        # Determine team context for the example tone
        if is_our_team:
            tone = "Sounders event - be supportive"
        else:
            tone = "Opponent event - be dismissive or disappointed"

        prompt = f"""Rewrite this match event as a short casual reaction. Use the specific details from the ESPN text. One sentence, two max. Under 200 characters.

Match: {home_team} vs {away_team} | Score: {score} | Minute: {event_time}
{rivalry}
Tone: {tone}

ESPN event: "{event_text if event_text else f'{event_type} - {player_name} ({team_name})'}"

Write only the reaction, nothing else."""

        return prompt
    
    async def _call_openai_api(self, prompt: str) -> Optional[str]:
        """Make the actual API call to Claude. (Name preserved for backward compat.)"""
        try:
            client = anthropic.AsyncAnthropic(api_key=self.api_key, timeout=self.timeout)
            response = await client.messages.create(
                model=self.model,
                max_tokens=60,
                temperature=0.4,
                system="You are an authentic soccer supporter generating raw, genuine reactions. Never sound corporate or AI-like.",
                messages=[{"role": "user", "content": prompt}],
            )
            commentary = next(
                (b.text for b in response.content if b.type == "text"),
                "",
            ).strip().strip('"\'')

            usage = response.usage
            logger.debug(
                f"🤖 Claude Usage: {usage.input_tokens} in + {usage.output_tokens} out"
            )
            return commentary or None
        except anthropic.AuthenticationError:
            logger.error("🤖 Claude API AUTH ERROR: Invalid CLAUDE_API key")
            return None
        except anthropic.RateLimitError as e:
            logger.error(f"🤖 Claude API RATE LIMIT: {e}")
            return None
        except anthropic.APIStatusError as e:
            logger.error(f"🤖 Claude API ERROR {e.status_code}: {e.message}")
            return None
        except Exception as e:
            logger.error(f"🤖 Claude call failed: {type(e).__name__}: {e}")
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
    
    def _get_prompt_config(self, prompt_type: str, competition: str = None) -> Optional[Dict[str, Any]]:
        """
        Retrieve AI prompt configuration from database, returned as a plain dict
        so attributes are safe to access after the SQLAlchemy session closes.
        """
        try:
            with managed_session() as session:
                config = None
                if competition:
                    config = session.query(AIPromptConfig).filter(
                        AIPromptConfig.prompt_type == prompt_type,
                        AIPromptConfig.is_active == True,
                        AIPromptConfig.competition_filter.in_([competition.lower(), 'all'])
                    ).first()

                if not config:
                    config = session.query(AIPromptConfig).filter(
                        AIPromptConfig.prompt_type == prompt_type,
                        AIPromptConfig.is_active == True
                    ).first()

                if not config:
                    return None

                system_prompt = config.system_prompt or ''
                user_prompt_template = config.user_prompt_template
                temperature = config.temperature
                max_tokens = config.max_tokens
                resolved_prompt_type = config.prompt_type

                if config.active_template_id and config.active_template:
                    template_data = config.active_template.template_data or {}
                    suffix = template_data.get('system_prompt_suffix')
                    if suffix:
                        system_prompt = (system_prompt + '\n' + suffix) if system_prompt else suffix

                return {
                    'system_prompt': system_prompt,
                    'user_prompt_template': user_prompt_template,
                    'temperature': temperature,
                    'max_tokens': max_tokens,
                    'prompt_type': resolved_prompt_type,
                }

        except Exception as e:
            logger.error(f"Error retrieving prompt config for {prompt_type}: {e}")
            return None
    
    async def _call_openai_api_with_config(self, prompt: str, config: Optional[Dict[str, Any]]) -> Optional[str]:
        """Make Claude API call using database configuration. (Name preserved for backward compat.)"""
        cfg = config or {}
        temperature = cfg.get('temperature') if cfg.get('temperature') is not None else 0.4
        max_tokens = cfg.get('max_tokens') or 60
        system_prompt = (
            cfg.get('system_prompt')
            or "You write short, casual match reactions. Never use em dashes. One or two sentences max."
        )

        try:
            client = anthropic.AsyncAnthropic(api_key=self.api_key, timeout=self.timeout)
            response = await client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            commentary = next(
                (b.text for b in response.content if b.type == "text"),
                "",
            ).strip().strip('"\'')
            from app.utils.commentary_validator import _clean_text
            return _clean_text(commentary) if commentary else None
        except anthropic.AuthenticationError:
            logger.error("🤖 Claude API AUTH ERROR: Invalid CLAUDE_API key")
            return None
        except anthropic.RateLimitError as e:
            logger.error(f"🤖 Claude API RATE LIMIT: {e}")
            return None
        except anthropic.APIStatusError as e:
            logger.error(f"🤖 Claude API ERROR {e.status_code}: {e.message}")
            return None
        except Exception as e:
            logger.error(f"🤖 Claude call failed: {type(e).__name__}: {e}")
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
            logger.error("🤖 Pre-match Hype FAILED: No CLAUDE_API key configured")
            return None
            
        try:
            # Get database configuration
            competition = match_context.get('competition', 'mls')
            config = self._get_prompt_config('pre_match_hype', competition)
            
            # Create prompt using database template or fallback
            if config and config.get('user_prompt_template'):
                prompt = self._render_prompt_template(config['user_prompt_template'], match_context)
            else:
                prompt = self._create_pre_match_prompt(match_context)
            
            logger.info(f"🤖 Generating pre-match hype message (temp: {config.get('temperature') if config else 'default'})")
            
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
            logger.error("🤖 Half-time Message FAILED: No CLAUDE_API key configured")
            return None
            
        try:
            # Get database configuration
            competition = match_context.get('competition', 'mls')
            config = self._get_prompt_config('half_time_message', competition)
            
            # Create prompt using database template or fallback
            if config and config.get('user_prompt_template'):
                prompt = self._render_prompt_template(config['user_prompt_template'], match_context)
            else:
                prompt = self._create_half_time_prompt(match_context)
            
            logger.info(f"🤖 Generating half-time analysis message (temp: {config.get('temperature') if config else 'default'})")
            
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
            logger.error("🤖 Full-time Message FAILED: No CLAUDE_API key configured")
            return None
            
        try:
            # Get database configuration
            competition = match_context.get('competition', 'mls')
            config = self._get_prompt_config('full_time_message', competition)
            
            # Create prompt using database template or fallback
            if config and config.get('user_prompt_template'):
                prompt = self._render_prompt_template(config['user_prompt_template'], match_context)
            else:
                prompt = self._create_full_time_prompt(match_context)
            
            logger.info(f"🤖 Generating full-time summary message (temp: {config.get('temperature') if config else 'default'})")
            
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
            logger.error("🤖 Thread Context FAILED: No CLAUDE_API key configured")
            return None
            
        try:
            # Get database configuration
            competition = match_context.get('competition', 'mls')
            config = self._get_prompt_config('match_thread_context', competition)
            
            # Create prompt using database template or fallback
            if config and config.get('user_prompt_template'):
                prompt = self._render_prompt_template(config['user_prompt_template'], match_context)
            else:
                prompt = self._create_thread_context_prompt(match_context)
            
            logger.info(f"🤖 Generating match thread context (temp: {config.get('temperature') if config else 'default'})")
            
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

        home_team_raw = match_context.get('home_team', 'Home')
        home_team = home_team_raw.get('displayName', 'Home') if isinstance(home_team_raw, dict) else home_team_raw
        away_team_raw = match_context.get('away_team', 'Away')
        away_team = away_team_raw.get('displayName', 'Away') if isinstance(away_team_raw, dict) else away_team_raw
        opponent = away_team if home_team == "Seattle Sounders FC" else home_team
        competition = match_context.get('competition', 'MLS')
        venue = match_context.get('venue', 'Unknown Venue')

        is_portland = "portland" in opponent.lower() or "timber" in opponent.lower()
        is_vancouver = "vancouver" in opponent.lower() or "whitecap" in opponent.lower()
        is_home = home_team == "Seattle Sounders FC"

        rivalry = ""
        if is_portland:
            rivalry = "Rivalry match vs Portland. Be hostile."
        elif is_vancouver:
            rivalry = "Cascadia match vs Vancouver. Show dislike."

        prompt = f"""Write a short pre-kickoff message for a Sounders Discord channel. 5 minutes to kick. One or two sentences. Under 280 characters. No em dashes.

Match: {home_team} vs {away_team} at {venue}
Competition: {competition}
{"Home match." if is_home else "Away match."}
{rivalry}

Examples:
"Sounders and Houston, 5 minutes out. Three points and nothing less."
"Almost time. {venue}, let's have it."
"Portland away in 5. Fuck the Timbers. Come on Seattle."
"About to kick off against Vancouver. Time to handle business."
"Playoff time. This is what the whole season was for."

Write only the message."""

        return prompt
    
    def _create_half_time_prompt(self, match_context: Dict[str, Any]) -> str:
        """Create prompt for half-time analysis message."""

        home_team = match_context.get('home_team', {}).get('displayName', 'Home')
        away_team = match_context.get('away_team', {}).get('displayName', 'Away')
        home_score = match_context.get('home_score', '0')
        away_score = match_context.get('away_score', '0')
        stats = match_context.get('stats', '')

        score = f"{home_score}-{away_score}"

        stats_line = f"\nMatch stats: {stats}" if stats else ""

        prompt = f"""Rewrite this halftime data as a short reaction for a Sounders Discord channel. Reference the stats if provided. One or two sentences. Under 280 characters. No em dashes.

Halftime score: {home_team} {score} {away_team}{stats_line}

Examples:
"Halftime. 1-0 up. 62% possession and 7 shots to their 2. Controlled."
"Halftime, still 0-0. Not much in it. 3 shots each. Second half needs more."
"Down 2-0 at the half. They've had 65% of the ball. Need a big response."
"2-1 up at the break. 8 shots but only 3 on target. Should be more."
"1-1 at halftime. Decent spell toward the end, keep pushing."

Write only the reaction."""

        return prompt

    def _create_full_time_prompt(self, match_context: Dict[str, Any]) -> str:
        """Create prompt for full-time summary message."""

        home_team = match_context.get('home_team', {}).get('displayName', 'Home')
        away_team = match_context.get('away_team', {}).get('displayName', 'Away')
        home_score = match_context.get('home_score', '0')
        away_score = match_context.get('away_score', '0')
        stats = match_context.get('stats', '')

        score = f"{home_score}-{away_score}"

        stats_line = f"\nMatch stats: {stats}" if stats else ""

        prompt = f"""Rewrite this full-time data as a short reaction for a Sounders Discord channel. Reference the stats if provided. One or two sentences. Under 280 characters. No em dashes.

Final score: {home_team} {score} {away_team}{stats_line}

Examples:
"Full time. 2-0. 58% possession, 12 shots. Clean sheet and 3 points."
"Full time. 1-2. They had 15 shots to our 6. Deserved it honestly."
"1-1 at the final whistle. 52% possession but couldn't find a winner."
"3-1. 9 shots on target. Comfortable in the end."
"0-0. 4 shots on target between both teams. Grim."
"Full time. 2-1. Outshot them 14-5. 3 points is 3 points."

Write only the reaction."""

        return prompt
        
    def _create_thread_context_prompt(self, match_context: Dict[str, Any]) -> str:
        """Create prompt for match thread contextual description."""

        home_team_raw = match_context.get('home_team', 'Home')
        home_team = home_team_raw.get('displayName', 'Home') if isinstance(home_team_raw, dict) else home_team_raw
        away_team_raw = match_context.get('away_team', 'Away')
        away_team = away_team_raw.get('displayName', 'Away') if isinstance(away_team_raw, dict) else away_team_raw
        competition = match_context.get('competition', 'MLS')
        venue = match_context.get('venue', 'Unknown Venue')
        is_home = match_context.get('is_home_game', home_team == "Seattle Sounders FC")
        opponent = match_context.get('opponent', away_team if home_team == "Seattle Sounders FC" else home_team)
        espn_info = match_context.get('espn_info', '')

        is_portland = "portland" in opponent.lower() or "timber" in opponent.lower()
        is_vancouver = "vancouver" in opponent.lower() or "whitecap" in opponent.lower()

        rivalry = ""
        if is_portland:
            rivalry = "Rivalry match vs Portland."
        elif is_vancouver:
            rivalry = "Cascadia match vs Vancouver."

        # Detect cup/knockout competitions
        is_cup = any(kw in competition.lower() for kw in ['cup', 'champions', 'concacaf', 'open', 'playoff'])

        if espn_info:
            prompt = f"""Rewrite this ESPN match info as a short one-liner for a Sounders supporters Discord thread. Under 200 characters. No em dashes. Use the real stats. No welcomes, no predictions, no hype.

ESPN info: "{espn_info}"
Competition: {competition}
{"Home match." if is_home else "Away match."} {rivalry}

Examples of ESPN info -> one-liner:
"Seattle Sounders FC (12W-5D-3L, 4th Western). Portland Timbers (10W-7D-5L, 2nd Western). Last meeting: SEA 2 - 1 POR" -> "Portland at home. Beat them 2-1 last time. Sitting 4th, need to close the gap."
"Seattle Sounders FC (8W-3D-2L, 3rd Western). Houston Dynamo FC (5W-6D-4L, 9th Western)" -> "Houston at home. They're 9th for a reason. Three points."
"Inter Miami CF (14W-2D-1L, 1st Eastern). Seattle Sounders FC (9W-4D-5L, 5th Western). Last meeting: MIA 3 - 0 SEA" -> "Miami away. They hammered us 3-0 last time. Top of the East for a reason."
"Seattle Sounders FC (10W-4D-3L, 3rd Western). Vancouver Whitecaps FC (7W-5D-6L, 7th Western)" -> "Vancouver at home. Cascadia. Love winning up there."
"Seattle Sounders FC (11W-3D-4L). Los Angeles Galaxy (12W-2D-5L). Last meeting: SEA 1 - 1 LAG" -> "LA Galaxy at home. LFG."
"Club America. Seattle Sounders FC" -> "CONCACAF quarterfinal leg 1. Club America at home. Huge night."

Write only the one-liner."""
        else:
            prompt = f"""Write a one-line match thread description for a Sounders supporters Discord. Under 200 characters. No em dashes. State what the match is and one reason it matters. No welcomes, no predictions, no hype.

Match: {home_team} vs {away_team} at {venue}
Competition: {competition}
{"Home match." if is_home else "Away match."}
{rivalry}

Examples:
"Portland at home tonight. Three points would put some distance in the table."
"Seattle at San Jose. Road trips are never easy."
"Cascadia Cup on the line in Vancouver. Love winning up there."
"Midweek match against Houston. Need the points either way."
"LA Galaxy at home. LFG."
"CONCACAF Champions Cup quarterfinal. Leg 1 at home. Big one."
"US Open Cup round of 16. Take care of business."

Write only the description."""

        return prompt


# Enhanced global service instance
_enhanced_ai_service = None

def get_enhanced_ai_service() -> EnhancedAICommentaryService:
    """Get the enhanced AI commentary service instance."""
    global _enhanced_ai_service
    if _enhanced_ai_service is None:
        _enhanced_ai_service = EnhancedAICommentaryService()
    return _enhanced_ai_service