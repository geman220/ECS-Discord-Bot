# test_match_utils.py

import asyncio
import pytest
import pytz
from datetime import datetime, timedelta
import discord
from match_utils import (
    extract_date_from_title,
    get_away_match,
    get_next_match,
    generate_thread_name,
    get_team_record,
    schedule_poll_closing,
    create_match_thread,
    prepare_match_environment,
    create_and_manage_thread,
    schedule_poll_closing,
)
from unittest.mock import AsyncMock, patch, MagicMock


def test_extract_date_from_title_valid():
    title = "Match 2024-03-15"
    expected_date = datetime(2024, 3, 15)
    assert extract_date_from_title(title) == expected_date


def test_extract_date_from_title_no_date():
    title = "Match Information"
    assert extract_date_from_title(title) is None


def test_extract_date_from_title_invalid_format():
    title = "Match 2024/03/15"
    assert extract_date_from_title(title) is None


@pytest.mark.asyncio
@patch("match_utils.call_woocommerce_api")
async def test_get_away_match_no_products(mock_call_woocommerce_api):
    mock_call_woocommerce_api.return_value = []
    result = await get_away_match(None)
    assert result is None


@pytest.mark.asyncio
@patch("match_utils.call_woocommerce_api")
async def test_get_away_match_with_products(mock_call_woocommerce_api):
    mock_call_woocommerce_api.return_value = [
        {"name": "Away Match 2024-05-20", "permalink": "http://example.com/ticket1"},
        {"name": "Away Match 2024-05-25", "permalink": "http://example.com/ticket2"},
    ]
    expected_result = ("Away Match 2024-05-20", "http://example.com/ticket1")
    result = await get_away_match(None)
    assert result == expected_result


@pytest.mark.asyncio
@patch("match_utils.call_woocommerce_api")
async def test_get_away_match_with_opponent(mock_call_woocommerce_api):
    mock_call_woocommerce_api.return_value = [
        {
            "name": "Away Match against TeamX 2024-05-20",
            "permalink": "http://example.com/ticket1",
        },
        {
            "name": "Away Match against TeamY 2024-05-25",
            "permalink": "http://example.com/ticket2",
        },
    ]
    expected_result = (
        "Away Match against TeamX 2024-05-20",
        "http://example.com/ticket1",
    )
    result = await get_away_match(opponent="TeamX")
    assert result == expected_result


@pytest.mark.asyncio
@patch("match_utils.fetch_espn_data")
async def test_get_team_record_success(mock_fetch_espn_data):
    mock_fetch_espn_data.return_value = {
        "team": {
            "record": {
                "items": [
                    {
                        "stats": [
                            {"name": "wins", "value": "10"},
                            {"name": "losses", "value": "2"},
                        ]
                    }
                ]
            },
            "logos": [{"href": "https://example.com/logo.png"}],
        }
    }
    expected_record = {"wins": "10", "losses": "2"}, "https://example.com/logo.png"
    record, logo = await get_team_record("123")
    assert record == expected_record[0]
    assert logo == expected_record[1]


@pytest.mark.asyncio
@patch("match_utils.fetch_espn_data")
async def test_get_team_record_no_data(mock_fetch_espn_data):
    mock_fetch_espn_data.return_value = {}
    result = await get_team_record("123")
    assert result == ("Record not available", None)

@pytest.mark.asyncio
@patch("match_utils.fetch_espn_data")
async def test_get_next_match_primary_method(mock_fetch_espn_data):
    mock_schedule_data = {
        "events": [
            {
                "name": "Mock Event",
            }
        ]
    }

    mock_fetch_espn_data.return_value = mock_schedule_data

    expected_result = "!!! Schedule endpoint now contains events data. You should tell Immortal to update the parsing logic. Using backup method for now."

    result = await get_next_match(None, "team_id")
    assert result == expected_result


@pytest.mark.asyncio
@patch("match_utils.get_weather_forecast")
@patch("match_utils.create_event_if_necessary")
async def test_prepare_match_environment_home_game(mock_create_event, mock_get_weather):
    mock_get_weather.return_value = "Weather: Sunny, 75 F"
    mock_create_event.return_value = "Event created: 'Pre-Match Gathering'"
    match_info = {"is_home_game": True, "date_time": "2024-03-01T19:00:00Z"}
    result = await prepare_match_environment(None, match_info)
    assert result == "Event created: 'Pre-Match Gathering'"


@pytest.mark.asyncio
@patch("match_utils.get_weather_forecast")
@patch("match_utils.create_event_if_necessary")
async def test_prepare_match_environment_away_game(mock_create_event, mock_get_weather):
    match_info = {"is_home_game": False}
    result = await prepare_match_environment(None, match_info)
    assert result == ""


@pytest.mark.asyncio
@patch("match_utils.prepare_match_environment")
@patch("match_utils.create_match_thread")
async def test_create_and_manage_thread(
    mock_create_match_thread, mock_prepare_match_environment
):
    mock_prepare_match_environment.return_value = "Environment prepared"
    mock_create_match_thread.return_value = "Thread created"
    match_info = {
        "name": "Match Name",
        "date_time": "2024-03-01T19:00:00Z",
        "team_logo": "logo_url",
        "venue": "Stadium Name",
        "match_summary_link": "Unavailable",
        "match_stats_link": "Unavailable",
        "match_commentary_link": "Unavailable",
    }
    cog = MagicMock()
    result = await create_and_manage_thread(None, match_info, cog)
    assert result == "Thread created"


@pytest.mark.asyncio
@patch("discord.utils.get")
async def test_create_match_thread(mock_discord_get):
    mock_channel = MagicMock(spec=discord.ForumChannel)
    mock_thread = AsyncMock()
    mock_initial_message = AsyncMock()
    mock_interaction = AsyncMock()
    mock_interaction.guild.channels = [mock_channel]

    mock_channel.create_thread = AsyncMock(
        return_value=(mock_thread, mock_initial_message)
    )

    mock_discord_get.return_value = mock_channel

    match_info = {
        "match_id": "12345",
        "name": "Match Name",
        "opponent": "Opponent Team",
        "date_time": "2024-03-01T19:00:00Z",
    }

    mock_embed = MagicMock()
    mock_embed.title = f"Match Thread: {match_info['name']} vs {match_info['opponent']}"
    mock_embed.description = f"Match on {match_info['date_time']}"

    cog = MagicMock()

    result = await create_match_thread(
        mock_interaction, "Thread Name", mock_embed, match_info, cog, "match-thread"
    )

    mock_channel.create_thread.assert_awaited_once_with(
        name="Thread Name", auto_archive_duration=60, embed=mock_embed
    )
    mock_thread.send.assert_awaited_once_with(
        f"Predict the score! Use `/predict {match_info['name']}-Score - {match_info['opponent']}-Score` to participate. Predictions end at kickoff!"
    )


@pytest.mark.asyncio
@patch("match_utils.get_predictions")
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_schedule_poll_closing(mock_sleep, mock_get_predictions):
    match_start_time = datetime.now(pytz.utc) + timedelta(seconds=1)
    mock_thread = AsyncMock()
    mock_get_predictions.return_value = [("Win", 5), ("Lose", 2)]

    await schedule_poll_closing(match_start_time, "12345", mock_thread)

    await asyncio.sleep(2)

    assert mock_thread.send.await_args_list[0][0][0] == "Predictions closed."

    result_message = "Predictions for the match:\nWin: 5 votes\nLose: 2 votes"
    assert mock_thread.send.await_args_list[1][0][0] == result_message

    assert mock_thread.send.await_count == 2
