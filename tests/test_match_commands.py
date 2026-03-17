# test_match_commands.py

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from match_commands import MatchCommands, fetch_match_by_thread, PredictionModal
from match_utils import closed_matches
from discord import Embed, TextChannel, Thread, ForumChannel
import discord

@pytest.fixture
def match_commands_bot():
    bot = AsyncMock()
    return MatchCommands(bot)


@pytest.fixture
def mock_interaction():
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = 123456789
    interaction.guild = MagicMock()
    interaction.guild.name = "Test Guild"
    interaction.guild.channels = [
        MagicMock(spec=ForumChannel, name="match-thread"),
        MagicMock(spec=ForumChannel, name="away-travel"),
    ]
    interaction.guild.icon = MagicMock()
    interaction.guild.icon.url = "http://example.com/icon.png"
    interaction.channel = MagicMock(spec=TextChannel)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.fixture
def mock_get_next_match(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr("match_commands.get_next_match", async_mock)
    return async_mock


@pytest.fixture
def mock_convert_to_pst(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("match_commands.convert_to_pst", mock)
    return mock


@pytest.fixture
def mock_fetch_match_by_thread(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr("match_commands.fetch_match_by_thread", async_mock)
    return async_mock


@pytest.fixture
def mock_has_admin_role(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr("match_commands.has_admin_role", async_mock)
    return async_mock


@pytest.mark.asyncio
async def test_fetch_match_by_thread_success():
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"match_id": "12345"}
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        result = await fetch_match_by_thread("thread_id")
        assert result == {"match_id": "12345"}


@pytest.mark.asyncio
async def test_fetch_match_by_thread_failure():
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        result = await fetch_match_by_thread("thread_id")
        assert result is None


@pytest.mark.asyncio
async def test_next_match_success(
    match_commands_bot, mock_interaction, mock_get_next_match, mock_convert_to_pst
):
    mock_match_info = {
        "name": "Match Name",
        "opponent": "Opponent Team",
        "date_time": "2024-03-01T19:00:00",
        "venue": "Stadium Name",
    }
    mock_get_next_match.return_value = mock_match_info
    mock_date_time_pst = MagicMock()
    mock_date_time_pst.strftime.return_value = "03/01/2024 07:00 PM PST"
    mock_convert_to_pst.return_value = mock_date_time_pst

    await match_commands_bot.next_match.callback(match_commands_bot, mock_interaction)

    mock_interaction.response.send_message.assert_called_once()
    args, kwargs = mock_interaction.response.send_message.call_args
    assert isinstance(kwargs["embed"], Embed)
    embed = kwargs["embed"]
    assert embed.title == "Next Match: Match Name"
    assert embed.fields[0].value == "Opponent Team"
    assert embed.fields[2].value == "Stadium Name"


@pytest.mark.asyncio
async def test_next_match_no_match_info(
    match_commands_bot, mock_interaction, mock_get_next_match
):
    mock_get_next_match.return_value = "No upcoming matches."

    await match_commands_bot.next_match.callback(match_commands_bot, mock_interaction)

    mock_interaction.response.send_message.assert_called_once_with(
        "No upcoming matches."
    )


@pytest.mark.asyncio
async def test_next_match_error(
    match_commands_bot, mock_interaction, mock_get_next_match
):
    mock_get_next_match.side_effect = Exception("Error fetching match info")

    await match_commands_bot.next_match.callback(match_commands_bot, mock_interaction)

    expected_message = "An error occurred while fetching the next match information."
    mock_interaction.response.send_message.assert_called_once_with(expected_message)


@pytest.mark.asyncio
async def test_show_predictions_outside_thread(
    match_commands_bot, mock_interaction, mock_fetch_match_by_thread
):
    mock_interaction.channel = MagicMock(spec=TextChannel)
    await match_commands_bot.show_predictions.callback(
        match_commands_bot, mock_interaction
    )
    mock_interaction.response.send_message.assert_called_once_with(
        "This command can only be used in match threads.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_show_predictions_unassociated_thread(
    match_commands_bot, mock_interaction, mock_fetch_match_by_thread
):
    mock_interaction.channel = MagicMock(spec=Thread, id=12345)
    mock_fetch_match_by_thread.return_value = None

    await match_commands_bot.show_predictions.callback(
        match_commands_bot, mock_interaction
    )

    mock_interaction.response.send_message.assert_called_once_with(
        "This thread is not associated with an active match prediction.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_show_predictions_no_predictions(
    match_commands_bot, mock_interaction, mock_fetch_match_by_thread
):
    mock_thread_id = 12345
    mock_interaction.channel = MagicMock(spec=Thread, id=mock_thread_id)

    mock_match_id = "67890"
    mock_fetch_match_by_thread.return_value = {"match_id": mock_match_id}

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = []
        mock_get.return_value.__aenter__.return_value = mock_resp

        await match_commands_bot.show_predictions.callback(
            match_commands_bot, mock_interaction
        )

    mock_interaction.response.send_message.assert_called_once_with(
        "No predictions have been made for this match.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_show_predictions_success(
    match_commands_bot, mock_interaction, mock_fetch_match_by_thread
):
    mock_channel_id = 123
    mock_interaction.channel = MagicMock(spec=Thread, id=mock_channel_id)
    mock_fetch_match_by_thread.return_value = {"match_id": "match_id"}
    
    mock_predictions = [
        {"discord_user_id": "1", "home_score": 1, "opponent_score": 0},
        {"discord_user_id": "2", "home_score": 2, "opponent_score": 1}
    ]

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = mock_predictions
        mock_get.return_value.__aenter__.return_value = mock_resp

        # Mock interaction.guild.get_member
        mock_interaction.guild.get_member.side_effect = lambda uid: MagicMock(display_name=f"User {uid}") if uid == "1" else None

        await match_commands_bot.show_predictions.callback(
            match_commands_bot, mock_interaction
        )

    args, kwargs = mock_interaction.response.send_message.call_args
    assert "embed" in kwargs
    embed = kwargs["embed"]
    assert len(embed.fields) == 2
    assert embed.fields[0].name == "User 1: 1 - 0"
    assert embed.fields[1].name == "User 2: 2 - 1"


@pytest.mark.asyncio
async def test_show_predictions_no_icon(
    match_commands_bot, mock_interaction, mock_fetch_match_by_thread
):
    mock_interaction.channel = MagicMock(spec=Thread, id=123)
    mock_interaction.guild.icon = None
    mock_fetch_match_by_thread.return_value = {"match_id": "match_id"}

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = [{"discord_user_id": "1", "home_score": 1, "opponent_score": 0}]
        mock_get.return_value.__aenter__.return_value = mock_resp

        await match_commands_bot.show_predictions.callback(
            match_commands_bot, mock_interaction
        )

    args, kwargs = mock_interaction.response.send_message.call_args
    assert "embed" in kwargs


@pytest.mark.asyncio
async def test_show_predictions_api_error(
    match_commands_bot, mock_interaction, mock_fetch_match_by_thread
):
    mock_interaction.channel = MagicMock(spec=Thread, id=123)
    mock_fetch_match_by_thread.return_value = {"match_id": "match_id"}

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_get.return_value.__aenter__.return_value = mock_resp

        await match_commands_bot.show_predictions.callback(
            match_commands_bot, mock_interaction
        )

    mock_interaction.response.send_message.assert_called_once_with(
        "Failed to fetch predictions.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_predict_outside_thread(
    match_commands_bot, mock_interaction, mock_fetch_match_by_thread
):
    mock_interaction.channel = MagicMock(spec=TextChannel)

    await match_commands_bot.predict.callback(
        match_commands_bot, mock_interaction
    )

    mock_interaction.response.send_message.assert_called_once_with(
        "This command can only be used in match threads.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_predict_unassociated_thread(
    match_commands_bot, mock_interaction, mock_fetch_match_by_thread
):
    mock_interaction.channel = MagicMock(spec=Thread, id=12345)
    mock_fetch_match_by_thread.return_value = None

    await match_commands_bot.predict.callback(
        match_commands_bot, mock_interaction
    )

    mock_interaction.response.send_message.assert_called_once_with(
        "This thread is not associated with an active match prediction.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_predict_success(
    match_commands_bot, mock_interaction, mock_fetch_match_by_thread
):
    mock_interaction.channel = MagicMock(spec=Thread, id=12345)
    mock_interaction.channel.name = "Sounders vs Timbers - 2024-01-01"
    mock_fetch_match_by_thread.return_value = {"match_id": "67890"}

    await match_commands_bot.predict.callback(
        match_commands_bot, mock_interaction
    )

    mock_interaction.response.send_modal.assert_called_once()
    modal = mock_interaction.response.send_modal.call_args[0][0]
    assert isinstance(modal, PredictionModal)
    assert modal.home_team == "Sounders"
    assert modal.opponent_team == "Timbers"


@pytest.mark.asyncio
async def test_predict_fallback_teams(
    match_commands_bot, mock_interaction, mock_fetch_match_by_thread
):
    mock_interaction.channel = MagicMock(spec=Thread, id=12345)
    mock_interaction.channel.name = "Malformed Title"
    mock_fetch_match_by_thread.return_value = {"match_id": "67890"}

    await match_commands_bot.predict.callback(
        match_commands_bot, mock_interaction
    )

    modal = mock_interaction.response.send_modal.call_args[0][0]
    assert modal.home_team == "Home"
    assert modal.opponent_team == "Opponent"


@pytest.mark.asyncio
async def test_prediction_modal_submit_success(mock_interaction):
    modal = PredictionModal(home_team="Home", opponent_team="Opponent", match_id="67890")
    modal.home_score = MagicMock()
    modal.home_score.value = "2"
    modal.opponent_score = MagicMock()
    modal.opponent_score.value = "1"
    
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"message": "Prediction recorded"}
        mock_post.return_value.__aenter__.return_value = mock_resp
        
        await modal.on_submit(mock_interaction)
        
    mock_interaction.response.send_message.assert_called_once_with(
        "Prediction recorded", ephemeral=True
    )


@pytest.mark.asyncio
async def test_prediction_modal_invalid_input(mock_interaction):
    modal = PredictionModal(home_team="Home", opponent_team="Opponent", match_id="67890")
    modal.home_score = MagicMock()
    modal.home_score.value = "abc"
    modal.opponent_score = MagicMock()
    modal.opponent_score.value = "1"
    
    await modal.on_submit(mock_interaction)
        
    mock_interaction.response.send_message.assert_called_once_with(
        "Please enter valid numeric scores.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_prediction_modal_closed_match(mock_interaction):
    # Mock match closure
    with patch("match_commands.closed_matches", ["67890"]):
        modal = PredictionModal(home_team="Home", opponent_team="Opponent", match_id="67890")
        modal.home_score = MagicMock()
        modal.home_score.value = "2"
        modal.opponent_score = MagicMock()
        modal.opponent_score.value = "1"
        await modal.on_submit(mock_interaction)
        
    mock_interaction.response.send_message.assert_called_once_with(
        "Predictions are closed for this match.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_prediction_modal_api_error(mock_interaction):
    modal = PredictionModal(home_team="Home", opponent_team="Opponent", match_id="67890")
    modal.home_score = MagicMock()
    modal.home_score.value = "2"
    modal.opponent_score = MagicMock()
    modal.opponent_score.value = "1"
    
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 400
        mock_resp.json.return_value = {"error": "Invalid user"}
        mock_post.return_value.__aenter__.return_value = mock_resp
        
        await modal.on_submit(mock_interaction)
        
    mock_interaction.response.send_message.assert_called_once_with(
        "Invalid user", ephemeral=True
    )
