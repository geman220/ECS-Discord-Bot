# app/services/enhanced_match_events.py

"""
Enhanced Match Events Service

Provides rich live match reporting with detailed events and intelligent hype system.
Supports:
- Match start/half-time/full-time messages
- Enhanced goal reporting with assists
- Substitution tracking
- Added time announcements  
- Card tracking with cumulative counts
- Possession and shot statistics
- Intelligent hype vs neutral reporting
"""

import logging
import random
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Team ID for Seattle Sounders (hype logic)
SEATTLE_SOUNDERS_ID = "9726"

class EnhancedMatchEvents:
    """Enhanced match event processor with intelligent hype system and personality."""
    
    def __init__(self):
        self.match_state = {
            'period': 0,
            'yellow_cards': {'home': 0, 'away': 0},
            'red_cards': {'home': 0, 'away': 0},
            'substitutions': {'home': 0, 'away': 0},
            'last_status': None,
            'goals_with_assists': [],
            'processed_events': set()  # Track processed event fingerprints
        }
        
        # Match-specific context tracking for AI awareness
        self.match_contexts = {}  # match_id -> context
        
        # Personality and quips collections
        self.goal_hype_messages = [
            "🎉 GOOOOOAAAALLLL! {scorer} finds the net at {minute}! That's what I'm talking about! ⚽🔥",
            "BOOM! {scorer} strikes gold at {minute}! Pure class! 🚀",
            "GET IN! {scorer} buries it at {minute}! The crowd goes wild! 💚",
            "YES! {scorer} scores a beauty at {minute}! Poetry in motion! ⚡",
            "WHAT A FINISH! {scorer} at {minute} - absolutely brilliant! 🌟",
            "MAGNIFICO! {scorer} slots it home at {minute}! That's why we love this game! ⚽",
            "SPECTACULAR! {scorer} delivers at {minute}! Goosebumps everywhere! 🎯"
        ]
        
        self.assist_celebrations = [
            " (assisted by the brilliant {assist}!)",
            " (beautiful setup by {assist}!)",
            " (thanks to {assist}'s vision!)",
            " (what a pass from {assist}!)",
            " ({assist} with the magic!)"
        ]
        
        self.opponent_goal_reactions = [
            "😠 They score... {scorer} at {minute}. Not ideal, but we're not done yet! 💪",
            "Ugh. {scorer} finds the net at {minute}. Time to show our character! 🔥",
            "Disappointing. {scorer} scores at {minute}. Let's hit back immediately! ⚡",
            "They celebrate now... {scorer} at {minute}. But this match isn't over! 💚"
        ]
        
        self.card_hype_messages = [
            "{emoji} {player} sees {card_type} at {minute}! They should be more careful! 😏",
            "{emoji} Booking for {player} at {minute}! That's what happens when you can't handle our pace! 🔥",
            "{emoji} {card_type} shown to {player} at {minute}! Getting under their skin! 😈",
            "{emoji} {player} gets cautioned at {minute}! They're feeling the pressure! ⚡",
            "{emoji} {card_type} for {player} at {minute}! Keep rattling them! 💪"
        ]
        
        self.card_neutral_messages = [
            "{emoji} {player} receives {card_type} at {minute}. Keep our discipline! 🤐",
            "{emoji} Booking for {player} at {minute}. Let's stay focused! ⚠️",
            "{emoji} {card_type} shown to {player} at {minute}. Play it smart! 🧠"
        ]
        
        self.substitution_messages = [
            "🔄 {player_in} comes on for {player_out} at {minute}. Fresh legs, fresh energy! 🏃‍♂️",
            "🔄 Tactical switch: {player_in} replaces {player_out} at {minute}. Let's see what they bring! ⚡",
            "🔄 {player_out} makes way for {player_in} at {minute}. Time to make an impact! 💪",
            "🔄 New blood: {player_in} on for {player_out} at {minute}. Show us what you've got! 🌟"
        ]
        
        self.match_start_messages = [
            "⚽ **KICKOFF!** The battle begins! Let's show them what we're made of! 🔥",
            "⚽ **AND WE'RE OFF!** 90 minutes of pure excitement ahead! 💚",
            "⚽ **THE MATCH IS UNDERWAY!** Time to make some magic happen! ⚡",
            "⚽ **GAME ON!** Let the beautiful game commence! 🌟"
        ]
        
        self.halftime_messages = [
            "⏸️ **HALFTIME** - {home_team} {home_score}-{away_score} {away_team}. Time for the tactical adjustments! 🧠",
            "⏸️ **BREAK TIME** - {home_team} {home_score}-{away_score} {away_team}. 45 more minutes to go! ⚡",
            "⏸️ **HALFTIME WHISTLE** - {home_team} {home_score}-{away_score} {away_team}. What will the second half bring? 🤔"
        ]
        
        self.victory_celebrations = [
            "🎉 **FULL TIME - VICTORY!** {final_score} - What a performance! The boys delivered! 💚",
            "🏆 **WE DID IT!** {final_score} - Absolutely brilliant! This is why we love this team! ⚽",
            "🔥 **CHAMPIONS!** {final_score} - That was pure class from start to finish! 🌟",
            "💪 **DOMINANT!** {final_score} - They couldn't handle our intensity! Get in! 🚀"
        ]
        
        self.defeat_messages = [
            "😔 **Full Time** - {final_score}. Not our day, but we'll be back stronger! 💪",
            "😞 **Disappointing result** - {final_score}. Time to regroup and learn! 🔄",
            "😤 **Frustrating** - {final_score}. We know we're better than this! ⚡"
        ]
        
        self.draw_messages = [
            "🤝 **Full Time** - {final_score}. A hard-fought point! Every point matters! ⚖️",
            "😐 **All Square** - {final_score}. Could've been better, but we take the point! 💙"
        ]
        
        # New event types
        self.added_time_messages = [
            "⏰ **{added_time} minutes of added time** - Every second counts now! ⚡",
            "⏱️ **{added_time} minutes of stoppage time** - Crunch time! 🔥",
            "🕐 **{added_time} additional minutes** - The drama continues! 💚",
            "⌛ **{added_time} minutes added** - Final push time! 💪"
        ]
        
        self.save_messages = [
            "🥅 **WHAT A SAVE!** Brilliant goalkeeping at {minute}! That's why we have the best! 🧤",
            "🛡️ **AMAZING SAVE!** Our keeper comes up huge at {minute}! Pure reflex! ⚡",
            "🔥 **SPECTACULAR SAVE!** What a stop at {minute}! That's championship quality! 🏆",
            "💚 **CLUTCH SAVE!** Our goalkeeper delivers when it matters at {minute}! Legend! 🙌",
            "⚡ **INCREDIBLE SAVE!** Lightning reflexes at {minute}! That's our wall! 🧱"
        ]
        
        self.var_review_messages = [
            "📐 **VAR REVIEW** - The officials are taking a closer look... 🤔",
            "🔍 **VAR CHECK** - Hold your breath, this could be big... ⏳",
            "📺 **VIDEO REVIEW** - The drama builds as VAR investigates... 👀",
            "⚖️ **VAR DECISION PENDING** - Tension in the air as they review... 😬"
        ]
        
        # Enhanced substitution context
        self.tactical_sub_messages = [
            "🔄 Tactical switch: {player_in} on for {player_out} at {minute}. Smart move! 🧠",
            "⚡ Strategic change: {player_in} replaces {player_out} at {minute}. Fresh approach! 🎯",
            "🎯 Game plan adjustment: {player_in} comes on for {player_out} at {minute}. 💡"
        ]
        
        self.late_sub_messages = [
            "🔄 Late change: {player_in} on for {player_out} at {minute}. Desperate times! ⏰",
            "⏱️ Last-minute switch: {player_in} replaces {player_out} at {minute}. All or nothing! 🎲",
            "🚨 Final roll of the dice: {player_in} comes on for {player_out} at {minute}! 🎰"
        ]
        
        self.impact_sub_messages = [
            "🔥 Game-changer incoming: {player_in} on for {player_out} at {minute}! 🌟",
            "⚡ Fresh legs, fresh hope: {player_in} replaces {player_out} at {minute}! 💪",
            "🎯 Difference-maker alert: {player_in} comes on for {player_out} at {minute}! 🚀"
        ]
    
    def reset_match_state(self):
        """Reset state for a new match."""
        self.match_state = {
            'period': 0,
            'yellow_cards': {'home': 0, 'away': 0},
            'red_cards': {'home': 0, 'away': 0},
            'substitutions': {'home': 0, 'away': 0},
            'last_status': None,
            'goals_with_assists': [],
            'processed_events': set()  # Track processed event fingerprints
        }
    
    def should_hype_event(self, event_type: str, event_team_id: str, event_data: Dict[str, Any]) -> bool:
        """
        Determine if an event should be hyped based on team and event type.
        
        HYPE EVENTS (for Seattle Sounders):
        - Our goals, assists, saves
        - Opponent yellow/red cards
        - Opponent missed penalties/own goals
        - Our clean sheets, comebacks
        
        NEUTRAL EVENTS:
        - Our cards, fouls
        - Routine substitutions
        - General match events
        """
        is_our_team = event_team_id == SEATTLE_SOUNDERS_ID
        
        # Events that are ALWAYS hyped when they favor us
        hype_events_for_us = [
            "Goal", "Assist", "Penalty Goal", "Save", "Block",
            "Clean Sheet", "Hat Trick", "Comeback"
        ]
        
        # Events that are hyped when they happen to opponents
        hype_events_against_them = [
            "Yellow Card", "Red Card", "Own Goal", "Penalty Miss",
            "Miss", "Offside", "Foul"
        ]
        
        # Special hype conditions
        if event_type in hype_events_for_us and is_our_team:
            return True
        elif event_type in hype_events_against_them and not is_our_team:
            return True
        elif event_type == "Goal" and not is_our_team:
            # Opponent goals are never hyped
            return False
        elif event_type in ["Yellow Card", "Red Card"] and is_our_team:
            # Our cards are reported neutrally
            return False
        elif event_type == "Save" and is_our_team:
            # Only hype our saves, not opponent saves
            return True
        elif event_type == "Save" and not is_our_team:
            # Don't report opponent saves at all
            return False
        
        return False
    
    def extract_goal_details(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Extract enhanced goal information including assists."""
        goal_details = {
            'scorer': None,
            'assist': None,
            'goal_type': 'Goal',
            'is_penalty': False,
            'is_own_goal': False,
            'minute': None
        }
        
        # Extract scorer
        athletes = event.get("athletesInvolved", [])
        if athletes:
            goal_details['scorer'] = {
                'name': athletes[0].get("displayName", "Unknown"),
                'short_name': athletes[0].get("shortName", "Unknown")
            }
        
        # Extract assist (usually second athlete)
        if len(athletes) > 1:
            goal_details['assist'] = {
                'name': athletes[1].get("displayName", "Unknown"),
                'short_name': athletes[1].get("shortName", "Unknown")
            }
        
        # Extract goal type from description
        description = event.get("text", "").lower()
        if "penalty" in description:
            goal_details['is_penalty'] = True
            goal_details['goal_type'] = "Penalty Goal"
        elif "own goal" in description:
            goal_details['is_own_goal'] = True
            goal_details['goal_type'] = "Own Goal"
        
        # Extract minute
        clock = event.get("clock", {})
        goal_details['minute'] = clock.get("displayValue", "Unknown")
        
        return goal_details
    
    def get_random_goal_message(self, goal_details: Dict[str, Any], is_hype: bool) -> str:
        """Generate a random goal message with personality."""
        scorer_name = goal_details.get('scorer', {}).get('short_name', 'Unknown')
        minute = goal_details.get('minute', 'Unknown')
        
        if is_hype:
            base_message = random.choice(self.goal_hype_messages)
            message = base_message.format(scorer=scorer_name, minute=minute)
            
            # Add assist celebration if available
            if goal_details.get('assist'):
                assist_name = goal_details['assist'].get('short_name', 'Unknown')
                assist_msg = random.choice(self.assist_celebrations)
                message += assist_msg.format(assist=assist_name)
            
            return message
        else:
            base_message = random.choice(self.opponent_goal_reactions)
            return base_message.format(scorer=scorer_name, minute=minute)
    
    def extract_card_details(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Extract card information with cumulative tracking."""
        card_details = {
            'player': None,
            'card_type': event.get("type", {}).get("text", "Card"),
            'minute': None,
            'reason': None,
            'team_totals': None
        }
        
        # Extract player
        athletes = event.get("athletesInvolved", [])
        if athletes:
            card_details['player'] = {
                'name': athletes[0].get("displayName", "Unknown"),
                'short_name': athletes[0].get("shortName", "Unknown")
            }
        
        # Extract minute
        clock = event.get("clock", {})
        card_details['minute'] = clock.get("displayValue", "Unknown")
        
        # Extract reason from description
        card_details['reason'] = event.get("text", "No details available")
        
        # Update cumulative counts
        event_team_id = str(event.get("team", {}).get("id", ""))
        if card_details['card_type'] == "Yellow Card":
            if event_team_id == SEATTLE_SOUNDERS_ID:
                self.match_state['yellow_cards']['home'] += 1
            else:
                self.match_state['yellow_cards']['away'] += 1
        elif card_details['card_type'] == "Red Card":
            if event_team_id == SEATTLE_SOUNDERS_ID:
                self.match_state['red_cards']['home'] += 1
            else:
                self.match_state['red_cards']['away'] += 1
        
        card_details['team_totals'] = {
            'home_yellows': self.match_state['yellow_cards']['home'],
            'home_reds': self.match_state['red_cards']['home'],
            'away_yellows': self.match_state['yellow_cards']['away'],
            'away_reds': self.match_state['red_cards']['away']
        }
        
        return card_details
    
    def get_random_card_message(self, card_details: Dict[str, Any], is_hype: bool) -> str:
        """Generate a random card message with personality."""
        player_name = card_details.get('player', {}).get('short_name', 'Unknown')
        card_type = card_details.get('card_type', 'Card')
        minute = card_details.get('minute', 'Unknown')
        emoji = "🟨" if card_type == "Yellow Card" else "🟥"
        
        if is_hype:
            base_message = random.choice(self.card_hype_messages)
        else:
            base_message = random.choice(self.card_neutral_messages)
        
        return base_message.format(
            emoji=emoji, player=player_name, card_type=card_type.lower(), minute=minute
        )
    
    def extract_substitution_details(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Extract substitution information."""
        sub_details = {
            'player_out': None,
            'player_in': None,
            'minute': None,
            'team_sub_count': None
        }
        
        # Extract players (typically 2 athletes for substitution)
        athletes = event.get("athletesInvolved", [])
        if len(athletes) >= 2:
            # First athlete is usually the one coming off
            sub_details['player_out'] = {
                'name': athletes[0].get("displayName", "Unknown"),
                'short_name': athletes[0].get("shortName", "Unknown")
            }
            # Second athlete is the one coming on
            sub_details['player_in'] = {
                'name': athletes[1].get("displayName", "Unknown"),
                'short_name': athletes[1].get("shortName", "Unknown")
            }
        
        # Extract minute
        clock = event.get("clock", {})
        sub_details['minute'] = clock.get("displayValue", "Unknown")
        
        # Update substitution count
        event_team_id = str(event.get("team", {}).get("id", ""))
        if event_team_id == SEATTLE_SOUNDERS_ID:
            self.match_state['substitutions']['home'] += 1
            sub_details['team_sub_count'] = self.match_state['substitutions']['home']
        else:
            self.match_state['substitutions']['away'] += 1
            sub_details['team_sub_count'] = self.match_state['substitutions']['away']
        
        return sub_details
    
    def extract_added_time_details(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Extract added time information."""
        added_time_details = {
            'added_time': None,
            'period': None,
            'minute': None
        }
        
        # Extract added time from description or clock
        description = event.get("text", "").lower()
        clock = event.get("clock", {})
        
        # Try to parse added time from various formats
        import re
        time_match = re.search(r'(\d+)\s*(?:minute|min)', description)
        if time_match:
            added_time_details['added_time'] = time_match.group(1)
        
        added_time_details['minute'] = clock.get("displayValue", "Unknown")
        
        return added_time_details
    
    def extract_save_details(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Extract save information."""
        save_details = {
            'goalkeeper': None,
            'minute': None,
            'save_type': 'Save'
        }
        
        # Extract goalkeeper
        athletes = event.get("athletesInvolved", [])
        if athletes:
            save_details['goalkeeper'] = {
                'name': athletes[0].get("displayName", "Unknown"),
                'short_name': athletes[0].get("shortName", "Unknown")
            }
        
        # Extract minute
        clock = event.get("clock", {})
        save_details['minute'] = clock.get("displayValue", "Unknown")
        
        return save_details
    
    def get_random_substitution_message(self, sub_details: Dict[str, Any], match_minute: str = None) -> str:
        """Generate a random substitution message with enhanced context."""
        player_in_name = sub_details.get('player_in', {}).get('short_name', 'Unknown')
        player_out_name = sub_details.get('player_out', {}).get('short_name', 'Unknown')
        minute = sub_details.get('minute', 'Unknown')
        
        # Determine substitution context
        try:
            minute_num = int(minute.replace("'", "").replace("+", ""))
        except:
            minute_num = 0
        
        # Choose message type based on timing
        if minute_num >= 80:  # Late substitution
            base_message = random.choice(self.late_sub_messages)
        elif minute_num >= 60:  # Impact substitution
            base_message = random.choice(self.impact_sub_messages)
        else:  # Tactical substitution
            base_message = random.choice(self.tactical_sub_messages)
        
        return base_message.format(
            player_in=player_in_name, player_out=player_out_name, minute=minute
        )
    
    def get_random_added_time_message(self, added_time_details: Dict[str, Any]) -> str:
        """Generate a random added time message with personality."""
        added_time = added_time_details.get('added_time', 'Unknown')
        
        base_message = random.choice(self.added_time_messages)
        return base_message.format(added_time=added_time)
    
    def get_random_save_message(self, save_details: Dict[str, Any]) -> str:
        """Generate a random save message with personality (only for our team)."""
        minute = save_details.get('minute', 'Unknown')
        
        base_message = random.choice(self.save_messages)
        return base_message.format(minute=minute)
    
    def get_random_var_message(self) -> str:
        """Generate a random VAR review message with suspense."""
        return random.choice(self.var_review_messages)
    
    async def _generate_ai_commentary(self, event: Dict[str, Any], enhanced_data: Dict[str, Any], 
                                    match_context: Dict[str, Any]) -> Optional[str]:
        """Generate AI commentary for an event."""
        try:
            from app.services.ai_commentary import generate_ai_commentary
            
            # Extract event details for AI
            event_data = {
                'type': enhanced_data.get('type', 'Event'),
                'player_name': self._extract_player_name(event),
                'team_name': enhanced_data.get('team_name', 'Unknown'),
                'is_our_team': enhanced_data.get('is_our_team', False),
                'time': enhanced_data.get('time', 'Unknown')
            }
            
            # Add event-specific details
            if 'goal_details' in enhanced_data:
                event_data['goal_details'] = enhanced_data['goal_details']
            if 'card_details' in enhanced_data:
                event_data['card_details'] = enhanced_data['card_details']
            if 'substitution_details' in enhanced_data:
                event_data['substitution_details'] = enhanced_data['substitution_details']
            
            return await generate_ai_commentary(event_data, match_context)
            
        except Exception as e:
            logger.error(f"Error generating AI commentary: {e}")
            return None
    
    def _extract_player_name(self, event: Dict[str, Any]) -> str:
        """Extract player name from event data."""
        athletes = event.get("athletesInvolved", [])
        if athletes:
            return athletes[0].get("displayName", "Unknown Player")
        return "Unknown Player"
    
    async def create_enhanced_event_data_async(self, match_id: str, event: Dict[str, Any], team_map: Dict[str, Any], 
                                             home_team: Dict[str, Any], away_team: Dict[str, Any],
                                             home_score: str, away_score: str) -> Dict[str, Any]:
        """
        Async version with AI commentary generation.
        """
        # Get the base enhanced data
        enhanced_data = self.create_enhanced_event_data(event, team_map, home_team, away_team, home_score, away_score)
        
        # Try to generate AI commentary
        match_context = {
            'home_team': home_team,
            'away_team': away_team,
            'home_score': home_score,
            'away_score': away_score
        }
        
        ai_commentary = await self._generate_ai_commentary(event, enhanced_data, match_context)
        if ai_commentary:
            enhanced_data["personality_message"] = ai_commentary
            enhanced_data["ai_generated"] = True
            logger.info(f"✅ AI COMMENTARY USED for {enhanced_data.get('type', 'event')}: '{ai_commentary[:60]}{'...' if len(ai_commentary) > 60 else ''}'")
        else:
            enhanced_data["ai_generated"] = False
            fallback_message = enhanced_data.get("personality_message", "No message")
            logger.warning(f"⚠️ FALLBACK TEMPLATE USED for {enhanced_data.get('type', 'event')}: '{fallback_message[:60]}{'...' if len(fallback_message) > 60 else ''}' - check AI logs above for failure reason")
        
        return enhanced_data
    
    def create_enhanced_event_data(self, event: Dict[str, Any], team_map: Dict[str, Any], 
                                  home_team: Dict[str, Any], away_team: Dict[str, Any],
                                  home_score: str, away_score: str) -> Dict[str, Any]:
        """Create enhanced event data with rich details."""
        event_type = event.get("type", {}).get("text", "Unknown Event")
        event_time = event.get("clock", {}).get("displayValue", "N/A")
        event_team_id = str(event.get("team", {}).get("id", ""))
        event_team = team_map.get(event_team_id, {})
        event_team_name = event_team.get("displayName", "Unknown Team")
        
        # Skip opponent saves entirely - we only care about our saves
        if event_type == "Save" and event_team_id != SEATTLE_SOUNDERS_ID:
            return None
        
        # Generate event fingerprint for deduplication
        from app.utils.match_events_utils import event_fingerprint
        fingerprint = event_fingerprint(event)
        
        # Check if we've already processed this event
        if fingerprint in self.match_state['processed_events']:
            logger.debug(f"Event already processed, skipping: {event_type} at {event_time} (fingerprint: {fingerprint})")
            return None
        
        # Mark event as processed
        self.match_state['processed_events'].add(fingerprint)
        logger.debug(f"Processing new event: {event_type} at {event_time} (fingerprint: {fingerprint})")
        
        # Base event data
        enhanced_data = {
            "type": event_type,
            "team": {
                'id': event_team_id,
                'displayName': event_team_name,
                'logo': event_team.get("logo", None)
            },
            "time": event_time,
            "description": event.get("text", "No description available."),
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "is_our_team": event_team_id == SEATTLE_SOUNDERS_ID
        }
        
        # Add enhanced details based on event type
        if event_type == "Goal":
            goal_details = self.extract_goal_details(event)
            enhanced_data["goal_details"] = goal_details
            # Add personality message
            is_hype = event_team_id == SEATTLE_SOUNDERS_ID
            enhanced_data["personality_message"] = self.get_random_goal_message(goal_details, is_hype)
        elif event_type in ["Yellow Card", "Red Card"]:
            card_details = self.extract_card_details(event)
            enhanced_data["card_details"] = card_details
            # Add personality message
            is_hype = event_team_id != SEATTLE_SOUNDERS_ID  # Cards are hyped when against opponents
            enhanced_data["personality_message"] = self.get_random_card_message(card_details, is_hype)
        elif event_type == "Substitution":
            sub_details = self.extract_substitution_details(event)
            enhanced_data["substitution_details"] = sub_details
            # Add personality message with enhanced context
            enhanced_data["personality_message"] = self.get_random_substitution_message(sub_details, event_time)
        elif event_type == "Save" and event_team_id == SEATTLE_SOUNDERS_ID:
            # Only process saves for our team
            save_details = self.extract_save_details(event)
            enhanced_data["save_details"] = save_details
            # Add personality message
            enhanced_data["personality_message"] = self.get_random_save_message(save_details)
        elif event_type in ["Added Time", "Stoppage Time"]:
            added_time_details = self.extract_added_time_details(event)
            enhanced_data["added_time_details"] = added_time_details
            # Add personality message
            enhanced_data["personality_message"] = self.get_random_added_time_message(added_time_details)
        elif event_type in ["VAR Review", "Video Review", "VAR Check"]:
            # VAR events don't need detailed extraction, just suspense
            enhanced_data["var_details"] = {"review_type": event_type}
            enhanced_data["personality_message"] = self.get_random_var_message()
        
        # Set special event flags
        enhanced_data["is_added_time"] = event_type in ["Added Time", "Stoppage Time"]
        enhanced_data["is_save"] = event_type == "Save" and event_team_id == SEATTLE_SOUNDERS_ID
        enhanced_data["is_var"] = event_type in ["VAR Review", "Video Review", "VAR Check"]
        enhanced_data["is_enhanced_sub"] = event_type == "Substitution"
        enhanced_data["event_fingerprint"] = fingerprint  # Store for logging/debugging
        
        return enhanced_data
    
    def create_status_change_data(self, status_type: str, home_team: Dict[str, Any], 
                                 away_team: Dict[str, Any], home_score: str, away_score: str,
                                 match_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create enhanced status change data."""
        competition = match_data.get("competitions", [{}])[0]
        status_info = competition.get("status", {})
        period = status_info.get("period", 0)
        clock = status_info.get("clock", {})
        
        status_data = {
            "status": status_type,
            "period": period,
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "clock": clock.get("displayValue", "N/A") if isinstance(clock, dict) else str(clock)
        }
        
        # Add special messages for different status changes with personality
        if status_type == "STATUS_IN_PROGRESS" and self.match_state['last_status'] != "STATUS_IN_PROGRESS":
            if period == 1:
                status_data["message_type"] = "match_start"
                status_data["special_message"] = random.choice(self.match_start_messages)
            elif period == 2:
                status_data["message_type"] = "second_half_start"
                status_data["special_message"] = "🔄 **Second half is underway!**"
        elif status_type == "STATUS_HALFTIME":
            status_data["message_type"] = "halftime"
            base_message = random.choice(self.halftime_messages)
            status_data["special_message"] = base_message.format(
                home_team=home_team['displayName'], 
                home_score=home_score, 
                away_score=away_score, 
                away_team=away_team['displayName']
            )
        elif status_type in ["STATUS_FULL_TIME", "STATUS_FINAL"]:
            status_data["message_type"] = "fulltime"
            # Add result analysis with personality
            final_score = f"{home_score}-{away_score}"
            
            if home_team.get("id") == SEATTLE_SOUNDERS_ID:
                our_score, their_score = int(home_score), int(away_score)
            else:
                our_score, their_score = int(away_score), int(home_score)
            
            if our_score > their_score:
                base_message = random.choice(self.victory_celebrations)
                status_data["special_message"] = base_message.format(final_score=final_score)
                status_data["result_type"] = "victory"
            elif our_score < their_score:
                base_message = random.choice(self.defeat_messages)
                status_data["special_message"] = base_message.format(final_score=final_score)
                status_data["result_type"] = "defeat"
            else:
                base_message = random.choice(self.draw_messages)
                status_data["special_message"] = base_message.format(final_score=final_score)
                status_data["result_type"] = "draw"
        
        self.match_state['last_status'] = status_type
        return status_data
    
    def should_report_event(self, event_type: str, event_team_id: str) -> bool:
        """Determine if an event should be reported at all."""
        # Skip opponent saves entirely
        if event_type == "Save" and event_team_id != SEATTLE_SOUNDERS_ID:
            return False
        
        return True
    
    def get_match_context(self, match_id: str) -> Dict[str, Any]:
        """Get or create match context for AI awareness."""
        if match_id not in self.match_contexts:
            self.match_contexts[match_id] = {
                'events_timeline': [],  # List of (timestamp, event_type, details)
                'goals_for': [],       # Our goals with timing
                'goals_against': [],   # Their goals with timing
                'cards_for': [],       # Our cards
                'cards_against': [],   # Their cards
                'match_narrative': [], # Key momentum shifts
                'score_progression': [], # (time, score) tuples
                'match_start_time': None,
                'is_sounders_home': None,
                'opponent_name': None
            }
        return self.match_contexts[match_id]
    
    def update_match_context(self, match_id: str, event_data: Dict[str, Any], 
                           home_team: Dict[str, Any], away_team: Dict[str, Any],
                           home_score: str, away_score: str) -> None:
        """Update match context with new event for AI awareness."""
        context = self.get_match_context(match_id)
        
        # Initialize match details if first time
        if context['is_sounders_home'] is None:
            context['is_sounders_home'] = home_team.get('id') == SEATTLE_SOUNDERS_ID
            context['opponent_name'] = away_team['displayName'] if context['is_sounders_home'] else home_team['displayName']
        
        # Current time and scores
        current_time = event_data.get('time', 'Unknown')
        current_score = f"{home_score}-{away_score}"
        is_our_team = event_data.get('is_our_team', False)
        event_type = event_data.get('type', 'Unknown')
        
        # Add to timeline
        event_entry = {
            'time': current_time,
            'type': event_type,
            'is_our_team': is_our_team,
            'player': event_data.get('player_name', ''),
            'details': event_data.get('details', ''),
            'timestamp': datetime.now()
        }
        context['events_timeline'].append(event_entry)
        
        # Track goals specifically
        if event_type == 'Goal':
            goal_info = {
                'time': current_time,
                'player': event_data.get('player_name', ''),
                'score_after': current_score,
                'timestamp': datetime.now()
            }
            if is_our_team:
                context['goals_for'].append(goal_info)
            else:
                context['goals_against'].append(goal_info)
        
        # Track cards
        elif event_type in ['Yellow Card', 'Red Card']:
            card_info = {
                'time': current_time,
                'type': event_type,
                'player': event_data.get('player_name', ''),
                'timestamp': datetime.now()
            }
            if is_our_team:
                context['cards_for'].append(card_info)
            else:
                context['cards_against'].append(card_info)
        
        # Track score progression
        if current_score not in [entry['score'] for entry in context['score_progression']]:
            context['score_progression'].append({
                'time': current_time,
                'score': current_score,
                'timestamp': datetime.now()
            })
        
        # Add narrative tracking for momentum shifts
        self._analyze_momentum_shift(context, event_data, current_score, is_our_team)
        
        # Limit context size to prevent memory bloat
        if len(context['events_timeline']) > 50:
            context['events_timeline'] = context['events_timeline'][-30:]
    
    def _analyze_momentum_shift(self, context: Dict[str, Any], event_data: Dict[str, Any], 
                               current_score: str, is_our_team: bool) -> None:
        """Analyze if this event represents a momentum shift for narrative context."""
        event_type = event_data.get('type', '')
        
        # Quick goals (within 5 minutes)
        if event_type == 'Goal' and len(context['events_timeline']) > 0:
            last_goal_time = None
            for event in reversed(context['events_timeline']):
                if event['type'] == 'Goal':
                    last_goal_time = event['timestamp']
                    break
            
            if last_goal_time:
                time_diff = (datetime.now() - last_goal_time).total_seconds() / 60
                if time_diff < 5:  # Goals within 5 minutes
                    context['match_narrative'].append({
                        'type': 'quick_goal_sequence',
                        'description': f'Goals scored within {time_diff:.1f} minutes',
                        'timestamp': datetime.now()
                    })
        
        # Red cards = game changers
        if event_type == 'Red Card':
            context['match_narrative'].append({
                'type': 'red_card_incident',
                'is_our_team': is_our_team,
                'description': f'Red card shown to {"us" if is_our_team else "them"}',
                'timestamp': datetime.now()
            })
        
        # Comeback tracking
        if event_type == 'Goal' and is_our_team:
            home_score, away_score = map(int, current_score.split('-'))
            if context['is_sounders_home']:
                our_score, their_score = home_score, away_score
            else:
                our_score, their_score = away_score, home_score
                
            # Check if this is a comeback goal
            if len(context['goals_against']) > len(context['goals_for']) - 1:
                context['match_narrative'].append({
                    'type': 'comeback_goal',
                    'description': f'Comeback goal to make it {our_score}-{their_score}',
                    'timestamp': datetime.now()
                })
    
    def build_ai_context(self, match_id: str, current_event: Dict[str, Any]) -> Dict[str, Any]:
        """Build rich context for AI commentary."""
        context = self.get_match_context(match_id)
        
        # Recent events (last 10 minutes or 5 events)
        recent_events = []
        current_time = datetime.now()
        for event in reversed(context['events_timeline'][-10:]):
            time_diff = (current_time - event['timestamp']).total_seconds() / 60
            if time_diff < 10:  # Last 10 minutes
                recent_events.append(event)
        
        # Goal timing analysis
        goals_timing = []
        for goal in context['goals_for']:
            goals_timing.append({
                'time': goal['time'],
                'player': goal['player'],
                'minutes_ago': (current_time - goal['timestamp']).total_seconds() / 60
            })
        
        # Build narrative context
        narrative_context = []
        for narrative in context['match_narrative'][-3:]:  # Last 3 narrative events
            narrative_context.append(narrative['description'])
        
        # Score situation analysis
        if context['score_progression']:
            latest_score = context['score_progression'][-1]['score']
            home_score, away_score = map(int, latest_score.split('-'))
            
            if context['is_sounders_home']:
                our_score, their_score = home_score, away_score
            else:
                our_score, their_score = away_score, home_score
            
            score_situation = {
                'leading': our_score > their_score,
                'tied': our_score == their_score,
                'behind': our_score < their_score,
                'goal_difference': our_score - their_score,
                'clean_sheet': their_score == 0,
                'our_goals': our_score,
                'their_goals': their_score
            }
        else:
            score_situation = {'leading': False, 'tied': True, 'behind': False, 'goal_difference': 0, 'clean_sheet': True, 'our_goals': 0, 'their_goals': 0}
        
        return {
            'recent_events': recent_events,
            'goals_timeline': goals_timing,
            'narrative_moments': narrative_context,
            'score_situation': score_situation,
            'opponent_name': context['opponent_name'],
            'is_home_game': context['is_sounders_home'],
            'match_events_count': len(context['events_timeline']),
            'total_goals_for': len(context['goals_for']),
            'total_goals_against': len(context['goals_against']),
            'total_cards_for': len(context['cards_for']),
            'total_cards_against': len(context['cards_against'])
        }


# Global instance
_enhanced_events = None

def get_enhanced_events_service() -> EnhancedMatchEvents:
    """Get the global enhanced events service."""
    global _enhanced_events
    if _enhanced_events is None:
        _enhanced_events = EnhancedMatchEvents()
    return _enhanced_events