# test_match_commands.py

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from match_commands import MatchCommands
from match_utils import closed_matches
from discord import Embed, TextChannel, Thread, ForumChannel

# Fixtures and Mocks
@pytest.fixture
def match_commands_bot():
    bot = MagicMock()
    return MatchCommands(bot)

@pytest.fixture
def mock_interaction():
    interaction = AsyncMock()
    interaction.guild.channels = [
        MagicMock(spec=ForumChannel, name="match-thread"),
        MagicMock(spec=ForumChannel, name="away-travel")
    ]
    interaction.channel = MagicMock(spec=TextChannel)
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
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
def mock_insert_prediction(monkeypatch):
    mock = Mock()
    monkeypatch.setattr("match_commands.insert_prediction", mock)
    return mock

@pytest.fixture
def mock_get_predictions(monkeypatch):
    mock = Mock()
    monkeypatch.setattr("match_commands.get_predictions", mock)
    return mock

@pytest.fixture
def mock_has_admin_role(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr("match_commands.has_admin_role", async_mock)
    return async_mock

@pytest.fixture
def mock_prepare_match_environment(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr("match_commands.prepare_match_environment", async_mock)
    return async_mock

@pytest.fixture
def mock_get_away_match(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr("match_commands.get_away_match", async_mock)
    return async_mock

@pytest.fixture
def mock_check_existing_threads(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr("match_commands.check_existing_threads", async_mock)
    return async_mock

@pytest.fixture
def mock_create_and_manage_thread(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr("match_commands.create_and_manage_thread", async_mock)
    return async_mock

@pytest.mark.asyncio
async def test_next_match_success(match_commands_bot, mock_interaction, mock_get_next_match, mock_convert_to_pst):
    mock_match_info = {
        'name': 'Match Name',
        'opponent': 'Opponent Team',
        'date_time': '2024-03-01T19:00:00',
        'venue': 'Stadium Name'
    }
    mock_get_next_match.return_value = mock_match_info
    mock_date_time_pst = MagicMock()
    mock_date_time_pst.strftime.return_value = '03/01/2024 07:00 PM PST'
    mock_convert_to_pst.return_value = mock_date_time_pst

    await match_commands_bot.next_match.callback(match_commands_bot, mock_interaction)

    mock_interaction.response.send_message.assert_called_once()
    args, kwargs = mock_interaction.response.send_message.call_args
    assert isinstance(kwargs['embed'], Embed)

@pytest.mark.asyncio
async def test_next_match_no_match_info(match_commands_bot, mock_interaction, mock_get_next_match):
    mock_get_next_match.return_value = "No upcoming matches."

    await match_commands_bot.next_match.callback(match_commands_bot, mock_interaction)

    mock_interaction.response.send_message.assert_called_once_with("No upcoming matches.")

@pytest.mark.asyncio
async def test_next_match_error(match_commands_bot, mock_interaction, mock_get_next_match):
    mock_get_next_match.side_effect = Exception("Error fetching match info")

    await match_commands_bot.next_match.callback(match_commands_bot, mock_interaction)

    expected_message = "An error occurred: Error fetching match info"
    mock_interaction.response.send_message.assert_called_once_with(expected_message)
        
@pytest.mark.asyncio
async def test_new_match_without_admin_role(match_commands_bot, mock_interaction, mock_has_admin_role):
    mock_has_admin_role.return_value = False

    await match_commands_bot.new_match.callback(match_commands_bot, mock_interaction)

    mock_has_admin_role.assert_called_once()
    mock_interaction.response.send_message.assert_called_once_with(
        "You do not have the necessary permissions.", ephemeral=True
    )

@pytest.mark.asyncio
async def test_new_match_away_game(match_commands_bot, mock_interaction, mock_has_admin_role, mock_get_next_match, mock_prepare_match_environment, mock_check_existing_threads, mock_create_and_manage_thread):
    mock_has_admin_role.return_value = True
    mock_get_next_match.return_value = {
        'name': 'Away Match',
        'date_time': '2024-02-24T21:30Z',
        'is_home_game': False,
        'team_logo': 'team_logo_url',
        'match_id': '692606'
    }
    mock_prepare_match_environment.return_value = None
    mock_check_existing_threads.return_value = False
    mock_create_and_manage_thread.return_value = "Thread created successfully"

    await match_commands_bot.new_match.callback(match_commands_bot, mock_interaction)

    mock_has_admin_role.assert_called_once()
    mock_get_next_match.assert_called_once()
    mock_prepare_match_environment.assert_called_once_with(mock_interaction, mock_get_next_match.return_value)
    mock_check_existing_threads.assert_called_once()
    mock_create_and_manage_thread.assert_called_once()
    mock_interaction.followup.send.assert_called_once_with("Thread created successfully")

@pytest.mark.asyncio
async def test_new_match_home_game(match_commands_bot, mock_interaction, mock_has_admin_role, mock_get_next_match, mock_prepare_match_environment, mock_check_existing_threads, mock_create_and_manage_thread):
    mock_has_admin_role.return_value = True
    mock_get_next_match.return_value = {
        'name': 'Home Match',
        'date_time': '2024-03-01T19:00:00',
        'is_home_game': True,
        'team_logo': 'team_logo_url',
        'match_id': '12345'
    }

    combined_response = "Weather: Sunny, 75 F. Event created: 'Pre-Match Gathering'"
    mock_prepare_match_environment.return_value = combined_response

    mock_check_existing_threads.return_value = False
    mock_create_and_manage_thread.return_value = "Thread created successfully with weather and event info"

    await match_commands_bot.new_match.callback(match_commands_bot, mock_interaction)

    mock_has_admin_role.assert_called_once()
    mock_get_next_match.assert_called_once()
    mock_prepare_match_environment.assert_called_once_with(mock_interaction, mock_get_next_match.return_value)
    mock_check_existing_threads.assert_called_once()
    mock_create_and_manage_thread.assert_called_once()

    mock_interaction.followup.send.assert_any_call("Weather: Sunny, 75 F. Event created: 'Pre-Match Gathering'", ephemeral=True)
    mock_interaction.followup.send.assert_any_call("Thread created successfully with weather and event info")

@pytest.mark.asyncio
async def test_away_match_success(match_commands_bot, mock_interaction, mock_has_admin_role, mock_get_away_match):
    mock_has_admin_role.return_value = True
    mock_get_away_match.return_value = ("Away Match Title", "ticket_link")

    await match_commands_bot.away_match.callback(match_commands_bot, mock_interaction, opponent="Opponent")

    mock_has_admin_role.assert_called_once()
    mock_get_away_match.assert_called_once_with(mock_interaction, "Opponent")

@pytest.mark.asyncio
async def test_show_predictions_outside_thread(match_commands_bot, mock_interaction, mock_get_predictions):
    mock_interaction.channel = MagicMock(spec=TextChannel)
    await match_commands_bot.show_predictions.callback(match_commands_bot, mock_interaction)
    mock_interaction.response.send_message.assert_called_once_with(
        "This command can only be used in match threads.", ephemeral=True
    )

@pytest.mark.asyncio
async def test_show_predictions_unassociated_thread(match_commands_bot, mock_interaction, mock_get_predictions):
    mock_interaction.channel = MagicMock(spec=Thread, id="12345")
    match_commands_bot.match_thread_map = {}

    await match_commands_bot.show_predictions.callback(match_commands_bot, mock_interaction)

    mock_interaction.response.send_message.assert_called_once_with(
        "This thread is not associated with an active match prediction.", ephemeral=True
    )

@pytest.mark.asyncio
async def test_show_predictions_no_predictions(match_commands_bot, mock_interaction, mock_get_predictions):
    mock_thread_id = '12345'
    mock_interaction.channel = MagicMock(spec=Thread, id=mock_thread_id)

    mock_match_id = '67890'
    match_commands_bot.match_thread_map = {mock_thread_id: mock_match_id}

    mock_get_predictions.return_value = []

    await match_commands_bot.show_predictions.callback(match_commands_bot, mock_interaction)

    mock_interaction.response.send_message.assert_called_once_with(
        "No predictions have been made for this match.", ephemeral=True
    )

@pytest.mark.asyncio
async def test_show_predictions_success(match_commands_bot, mock_interaction, mock_get_predictions):
    mock_channel_id = "123"
    mock_interaction.channel = MagicMock(spec=Thread, id=mock_channel_id)
    match_commands_bot.match_thread_map = {mock_channel_id: "match_id"}
    mock_predictions = [('Win', 5), ('Lose', 2)]
    mock_get_predictions.return_value = mock_predictions

    await match_commands_bot.show_predictions.callback(match_commands_bot, mock_interaction)

    # Assertions for embed
    args, kwargs = mock_interaction.response.send_message.call_args
    assert 'embed' in kwargs
    assert isinstance(kwargs['embed'], Embed)
    assert len(kwargs['embed'].fields) == 2

@pytest.mark.asyncio
async def test_show_predictions_in_thread(match_commands_bot, mock_interaction, mock_get_predictions):
    mock_channel_id = "12345"
    mock_interaction.channel = MagicMock(spec=Thread, id=mock_channel_id)
    match_commands_bot.match_thread_map = {mock_channel_id: "67890"}
    mock_predictions = [('Win', 5), ('Lose', 2)]
    mock_get_predictions.return_value = mock_predictions

    await match_commands_bot.show_predictions.callback(match_commands_bot, mock_interaction)

    # Assertions for embed
    args, kwargs = mock_interaction.response.send_message.call_args
    assert 'embed' in kwargs
    assert isinstance(kwargs['embed'], Embed)

@pytest.mark.asyncio
async def test_predict_outside_thread(match_commands_bot, mock_interaction, mock_insert_prediction):
    mock_interaction.channel = MagicMock(spec=TextChannel)

    await match_commands_bot.predict.callback(match_commands_bot, mock_interaction, prediction="2-1")

    mock_interaction.response.send_message.assert_called_once_with(
        "This command can only be used in match threads.", ephemeral=True
    )

@pytest.mark.asyncio
async def test_predict_unassociated_thread(match_commands_bot, mock_interaction, mock_insert_prediction):
    mock_interaction.channel = MagicMock(spec=Thread, id="12345")
    match_commands_bot.match_thread_map = {}

    await match_commands_bot.predict.callback(match_commands_bot, mock_interaction, prediction="2-1")

    mock_interaction.response.send_message.assert_called_once_with(
        "This thread is not associated with an active match prediction.", ephemeral=True
    )

@pytest.mark.asyncio
async def test_predict_closed_predictions(match_commands_bot, mock_interaction, mock_insert_prediction):
    mock_channel_id = "12345"
    mock_match_id = "67890"
    mock_interaction.channel = MagicMock(spec=Thread, id=mock_channel_id)
    match_commands_bot.match_thread_map = {mock_channel_id: mock_match_id}

    closed_matches.add(mock_match_id)

    mock_insert_prediction.return_value = True

    await match_commands_bot.predict.callback(match_commands_bot, mock_interaction, prediction="2-1")

    mock_interaction.response.send_message.assert_called_once_with(
        "Predictions are closed for this match.", ephemeral=True
    )

    closed_matches.remove(mock_match_id)

@pytest.mark.asyncio
async def test_predict_success(match_commands_bot, mock_interaction, mock_insert_prediction):
    mock_interaction.channel = MagicMock(spec=Thread, id="12345")
    match_commands_bot.match_thread_map = {"12345": "67890"}
    mock_insert_prediction.return_value = True

    await match_commands_bot.predict.callback(match_commands_bot, mock_interaction, prediction="1-0")

    mock_interaction.response.send_message.assert_called_once_with(
        "Prediction recorded!", ephemeral=True
    )

@pytest.mark.asyncio
async def test_predict_command_already_predicted(
    match_commands_bot, mock_interaction
):
    mock_db = {}

    mock_interaction.channel = MagicMock(spec=Thread, id='12345678')
    mock_interaction.user.id = '87654321'

    async def mock_insert_prediction(match_id, user_id, prediction):
        if user_id in mock_db:
            return False
        else:
            mock_db[user_id] = prediction
            return True

    match_commands_bot.insert_prediction = mock_insert_prediction

    match_commands_bot.match_thread_map = {'12345678': 'match1'}

    match_commands_bot.closed_matches = set()

    await match_commands_bot.predict.callback(match_commands_bot, mock_interaction, prediction="3-0")

    await match_commands_bot.predict.callback(match_commands_bot, mock_interaction, prediction="2-1")

    mock_interaction.response.send_message.assert_awaited_with(
        "You have already made a prediction for this match.",
        ephemeral=True
    )
