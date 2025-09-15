# api/routes/testing_routes.py

"""
Testing API Routes

Endpoints for testing the live reporting system with mock matches.
Provides realistic match simulation for development and QA.
"""

import logging
import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import random

from shared_states import get_bot_instance

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/testing", tags=["testing"])


class MockMatchConfig(BaseModel):
    thread_id: int
    home_team: str = "Arsenal"
    away_team: str = "Chelsea"
    competition: str = "Premier League"
    duration_minutes: int = 5  # Compressed match duration
    events_enabled: bool = True
    auto_status_updates: bool = True


class MockEventConfig(BaseModel):
    minute: int
    event_type: str  # 'goal', 'yellow_card', 'red_card', 'substitution'
    player: str
    team: str
    description: Optional[str] = None


# Global state for running mock matches
running_matches: Dict[int, bool] = {}


@router.post("/mock-match/start")
async def start_mock_match(config: MockMatchConfig, background_tasks: BackgroundTasks):
    """
    Start a realistic mock match simulation.

    Simulates a full match with realistic events and timing.
    Perfect for testing the live reporting system end-to-end.
    """
    if config.thread_id in running_matches:
        raise HTTPException(status_code=400, detail="Mock match already running for this thread")

    running_matches[config.thread_id] = True

    # Start the mock match in background
    background_tasks.add_task(simulate_match, config)

    logger.info(f"Started mock match: {config.home_team} vs {config.away_team} in thread {config.thread_id}")

    return {
        "success": True,
        "thread_id": config.thread_id,
        "message": f"Mock match started: {config.home_team} vs {config.away_team}",
        "duration_minutes": config.duration_minutes
    }


@router.post("/mock-match/stop/{thread_id}")
async def stop_mock_match(thread_id: int):
    """Stop a running mock match."""
    if thread_id not in running_matches:
        raise HTTPException(status_code=404, detail="No mock match running for this thread")

    running_matches[thread_id] = False
    del running_matches[thread_id]

    return {
        "success": True,
        "thread_id": thread_id,
        "message": "Mock match stopped"
    }


@router.get("/mock-match/status")
async def get_running_matches():
    """Get list of currently running mock matches."""
    return {
        "running_matches": list(running_matches.keys()),
        "count": len(running_matches)
    }


async def simulate_match(config: MockMatchConfig):
    """
    Simulate a realistic soccer match with events.

    Compresses a 90-minute match into the specified duration
    with realistic event distribution.
    """
    try:
        bot = get_bot_instance()
        if not bot or not bot.is_ready():
            logger.error("Bot not ready for mock match simulation")
            return

        thread = bot.get_channel(config.thread_id)
        if not thread:
            logger.error(f"Thread {config.thread_id} not found")
            return

        # Calculate timing
        match_duration_seconds = config.duration_minutes * 60
        minute_duration = match_duration_seconds / 90  # 90 minutes compressed

        home_score = 0
        away_score = 0

        logger.info(f"Starting mock match simulation: {config.home_team} vs {config.away_team}")

        # Send kickoff message
        if config.auto_status_updates:
            kickoff_embed = {
                "title": "🟢 KICK-OFF!",
                "description": f"**{config.home_team}** vs **{config.away_team}**\n\n*Match simulation started*",
                "color": 0x00ff00,
                "timestamp": datetime.utcnow().isoformat()
            }
            await send_mock_message(thread, embed=kickoff_embed)

        # Generate realistic events
        match_events = generate_realistic_events(config.home_team, config.away_team)

        # Simulate first half (0-45 minutes)
        for minute in range(1, 46):
            if config.thread_id not in running_matches:
                logger.info("Mock match stopped")
                return

            # Check for events at this minute
            minute_events = [e for e in match_events if e['minute'] == minute]

            for event in minute_events:
                if event['event_type'] == 'goal':
                    if event['team'] == config.home_team:
                        home_score += 1
                    else:
                        away_score += 1

                # Send event message
                event_message = format_event_message(event, home_score, away_score, config.home_team, config.away_team)
                await send_mock_message(thread, content=event_message)

                # Small delay between events
                await asyncio.sleep(2)

            # Wait for next minute
            await asyncio.sleep(minute_duration)

        # Halftime
        if config.auto_status_updates and config.thread_id in running_matches:
            halftime_embed = {
                "title": "⏸️ HALF-TIME",
                "description": f"**{config.home_team}** {home_score} - {away_score} **{config.away_team}**",
                "color": 0xffa500,
                "timestamp": datetime.utcnow().isoformat()
            }
            await send_mock_message(thread, embed=halftime_embed)
            await asyncio.sleep(10)  # Halftime break

        # Second half (46-90 minutes)
        for minute in range(46, 91):
            if config.thread_id not in running_matches:
                return

            minute_events = [e for e in match_events if e['minute'] == minute]

            for event in minute_events:
                if event['event_type'] == 'goal':
                    if event['team'] == config.home_team:
                        home_score += 1
                    else:
                        away_score += 1

                event_message = format_event_message(event, home_score, away_score, config.home_team, config.away_team)
                await send_mock_message(thread, content=event_message)
                await asyncio.sleep(2)

            await asyncio.sleep(minute_duration)

        # Full time
        if config.thread_id in running_matches:
            # Determine result
            if home_score > away_score:
                result = f"🏆 {config.home_team} wins!"
            elif away_score > home_score:
                result = f"🏆 {config.away_team} wins!"
            else:
                result = "🤝 It's a draw!"

            fulltime_embed = {
                "title": "🏁 FULL-TIME",
                "description": f"**{config.home_team}** {home_score} - {away_score} **{config.away_team}**\n\n{result}\n\n*Mock match simulation completed*",
                "color": 0xff0000,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {"text": "Thanks for following the simulation!"}
            }
            await send_mock_message(thread, embed=fulltime_embed)

        # Cleanup
        if config.thread_id in running_matches:
            del running_matches[config.thread_id]

        logger.info(f"Mock match completed: {config.home_team} {home_score}-{away_score} {config.away_team}")

    except Exception as e:
        logger.error(f"Error in mock match simulation: {e}")
        if config.thread_id in running_matches:
            del running_matches[config.thread_id]


def generate_realistic_events(home_team: str, away_team: str) -> List[Dict[str, Any]]:
    """Generate realistic match events with proper distribution."""
    events = []

    # Realistic player names
    home_players = ["Smith", "Johnson", "Williams", "Brown", "Jones"]
    away_players = ["Garcia", "Rodriguez", "Martinez", "Lopez", "Gonzalez"]

    # Goals (0-5 per match, most common 1-3)
    num_goals = random.choices([0, 1, 2, 3, 4, 5], weights=[5, 25, 35, 25, 8, 2])[0]
    for _ in range(num_goals):
        minute = random.randint(1, 90)
        team = random.choice([home_team, away_team])
        player = random.choice(home_players if team == home_team else away_players)

        events.append({
            'minute': minute,
            'event_type': 'goal',
            'team': team,
            'player': player,
            'description': f"Goal by {player}!"
        })

    # Yellow cards (1-4 per match)
    num_yellows = random.randint(1, 4)
    for _ in range(num_yellows):
        minute = random.randint(10, 85)
        team = random.choice([home_team, away_team])
        player = random.choice(home_players if team == home_team else away_players)

        events.append({
            'minute': minute,
            'event_type': 'yellow_card',
            'team': team,
            'player': player,
            'description': f"Yellow card for {player}"
        })

    # Red cards (0-1 per match, rare)
    if random.random() < 0.2:  # 20% chance
        minute = random.randint(30, 85)
        team = random.choice([home_team, away_team])
        player = random.choice(home_players if team == home_team else away_players)

        events.append({
            'minute': minute,
            'event_type': 'red_card',
            'team': team,
            'player': player,
            'description': f"Red card for {player}!"
        })

    # Substitutions (3-5 per team)
    for team, players in [(home_team, home_players), (away_team, away_players)]:
        num_subs = random.randint(3, 5)
        sub_minutes = sorted(random.sample(range(60, 85), num_subs))

        for i, minute in enumerate(sub_minutes):
            off_player = random.choice(players)
            on_player = f"Sub{i+1}"

            events.append({
                'minute': minute,
                'event_type': 'substitution',
                'team': team,
                'player': on_player,
                'description': f"{on_player} replaces {off_player}"
            })

    return sorted(events, key=lambda x: x['minute'])


def format_event_message(event: Dict[str, Any], home_score: int, away_score: int, home_team: str, away_team: str) -> str:
    """Format event into Discord message."""
    minute = event['minute']
    event_type = event['event_type']
    player = event['player']
    team = event['team']

    if event_type == 'goal':
        return f"⚽ **GOAL!** {minute}' - {player} ({team})\n\n**{home_team}** {home_score} - {away_score} **{away_team}**"
    elif event_type == 'yellow_card':
        return f"🟨 **Yellow Card** {minute}' - {player} ({team})"
    elif event_type == 'red_card':
        return f"🟥 **Red Card** {minute}' - {player} ({team})"
    elif event_type == 'substitution':
        return f"🔄 **Substitution** {minute}' - {team}\n{event['description']}"
    else:
        return f"📝 **{minute}'** - {event['description']}"


async def send_mock_message(thread, content: str = None, embed: Dict = None):
    """Send message to Discord thread."""
    try:
        if embed:
            discord_embed = discord.Embed.from_dict(embed)
            await thread.send(embed=discord_embed)
        else:
            await thread.send(content)
    except Exception as e:
        logger.error(f"Error sending mock message: {e}")


# Quick test endpoints
@router.post("/quick-test/goal/{thread_id}")
async def send_test_goal(thread_id: int):
    """Send a test goal event."""
    try:
        bot = get_bot_instance()
        thread = bot.get_channel(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        message = "⚽ **TEST GOAL!** 25' - Test Player (Test Team)\n\n**Team A** 1 - 0 **Team B**"
        await thread.send(message)

        return {"success": True, "message": "Test goal sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quick-test/status/{thread_id}")
async def send_test_status(thread_id: int):
    """Send a test status update."""
    try:
        bot = get_bot_instance()
        thread = bot.get_channel(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        embed = discord.Embed(
            title="🟢 TEST KICKOFF",
            description="**Test Team A** vs **Test Team B**\n\n*This is a test status update*",
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        await thread.send(embed=embed)

        return {"success": True, "message": "Test status sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))