# tests/test_rsvp_utils.py

import pytest
import discord
from unittest.mock import AsyncMock, MagicMock, patch

# Global session reset fixture
@pytest.fixture(autouse=True)
def reset_rsvp_session():
    import api.utils.rsvp_utils as rsvp_utils
    rsvp_utils.session = None
    yield
    rsvp_utils.session = None

from api.utils.rsvp_utils import (
    get_emoji_for_response,
    extract_channel_and_message_id,
    update_embed_for_message
)

def test_get_emoji_for_response():
    assert get_emoji_for_response('yes') == "👍"
    assert get_emoji_for_response('no') == "👎"
    assert get_emoji_for_response('maybe') == "🤷"
    assert get_emoji_for_response('unknown') is None

def test_extract_channel_and_message_id_valid():
    chan, msg = extract_channel_and_message_id("123-456")
    assert chan == "123"
    assert msg == "456"

def test_extract_channel_and_message_id_invalid():
    with pytest.raises(ValueError):
        extract_channel_and_message_id("invalid")

@pytest.mark.asyncio
async def test_update_embed_for_message_success(mock_aiohttp_session, monkeypatch):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.json.side_effect = None # Clear any previous side effects
    
    # Mock BOT configuration
    monkeypatch.setattr("api.utils.rsvp_utils.WEBUI_API_URL", "https://api.example.com")
    
    # Mock Discord objects
    mock_bot = MagicMock()
    mock_channel = AsyncMock()
    mock_message = AsyncMock()
    
    mock_bot.get_channel.return_value = mock_channel
    mock_channel.fetch_message.return_value = mock_message
    
    # Mock API responses (RSVP data and Match data)
    mock_rsvp_data = {
        "yes": [{"player_name": "Alice"}],
        "no": [],
        "maybe": [{"player_name": "Bob"}]
    }
    mock_match_data = {
        "home_team_id": 1,
        "home_team_name": "Sounders",
        "away_team_name": "Timbers",
        "match_date": "2024-05-12",
        "match_time": "19:00"
    }
    
    # Set up the mock response to return RSVP data then Match data
    mock_response.json.side_effect = [mock_rsvp_data, mock_match_data]
    mock_response.status = 200
    
    result = await update_embed_for_message("456", "123", 1, 1, mock_bot)
    
    assert result is True
    # Verify message was edited
    mock_message.edit.assert_called_once()
    # Check that embed was created correctly
    args, kwargs = mock_message.edit.call_args
    embed = kwargs["embed"]
    assert isinstance(embed, discord.Embed)
    assert embed.title == "Sounders vs Timbers"
    assert len(embed.fields) == 3
    assert "Alice" in embed.fields[0].value

@pytest.mark.asyncio
async def test_update_embed_for_message_channel_not_found(mock_bot_fixture):
    mock_bot = mock_bot_fixture
    mock_bot.get_channel.return_value = None
    mock_bot.fetch_channel.side_effect = discord.NotFound(MagicMock(), "Not Found")
    
    result = await update_embed_for_message("456", "123", 1, 1, mock_bot)
    assert result is False

def test_create_team_embed():
    from api.utils.rsvp_utils import create_team_embed
    from api.models.schemas import AvailabilityRequest
    
    match_req = AvailabilityRequest(
        match_id=1,
        home_team_id=1,
        home_team_name="Sounders",
        away_team_id=2,
        away_team_name="Timbers",
        home_channel_id=123,
        away_channel_id=456,
        match_date="2024-05-12",
        match_time="19:00"
    )
    rsvp_data = {
        "yes": [{"player_name": "Alice"}],
        "no": [],
        "maybe": []
    }
    
    embed = create_team_embed(match_req, rsvp_data, team_type='home')
    assert embed.title == "Sounders vs Timbers"
    assert "Alice" in embed.fields[0].value

@pytest.mark.asyncio
async def test_get_player_info_from_discord_success(mock_aiohttp_session, monkeypatch):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.status = 200
    mock_response.json.return_value = {"player_id": 10, "team_id": 5}
    monkeypatch.setattr("api.utils.rsvp_utils.WEBUI_API_URL", "https://api.example.com/api")
    
    from api.utils.rsvp_utils import get_player_info_from_discord
    p_id, t_id = await get_player_info_from_discord("discord123")
    assert p_id == 10
    assert t_id == 5

@pytest.mark.asyncio
async def test_retry_api_call_success(mock_aiohttp_session):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.status = 200
    mock_response.json.side_effect = None  # Reset side_effect from other tests
    mock_response.json.return_value = {"status": "ok"}
    
    from api.utils.rsvp_utils import retry_api_call
    result = await retry_api_call("https://api.example.com/retry")
    assert result == {"status": "ok"}

@pytest.mark.asyncio
async def test_fetch_match_data_success(mock_aiohttp_session, monkeypatch):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.status = 200
    mock_response.json.return_value = {"match_id": 1}
    monkeypatch.setattr("api.utils.rsvp_utils.WEBUI_API_URL", "https://api.example.com")
    
    from api.utils.rsvp_utils import fetch_match_data
    result = await fetch_match_data(1)
    assert result == {"match_id": 1}

@pytest.mark.asyncio
async def test_fetch_team_rsvp_data_success(mock_aiohttp_session, monkeypatch):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.status = 200
    mock_response.json.return_value = {"yes": []}
    monkeypatch.setattr("api.utils.rsvp_utils.WEBUI_API_URL", "https://api.example.com")
    
    from api.utils.rsvp_utils import fetch_team_rsvp_data
    result = await fetch_team_rsvp_data(1, 1)
    assert result == {"yes": []}

@pytest.mark.asyncio
async def test_update_embed_message_with_players():
    from api.utils.rsvp_utils import update_embed_message_with_players
    
    mock_message = AsyncMock()
    mock_embed = MagicMock()
    mock_message.embeds = [mock_embed]
    
    rsvp_data = {
        "yes": [{"player_name": "Alice"}],
        "no": [{"player_name": "Bob"}],
        "maybe": []
    }
    
    await update_embed_message_with_players(mock_message, rsvp_data)
    
    # Should call set_field_at three times (yes, no, maybe)
    assert mock_embed.set_field_at.call_count == 3
    mock_message.edit.assert_called_once()

@pytest.fixture
def mock_bot_fixture():
    return MagicMock()
