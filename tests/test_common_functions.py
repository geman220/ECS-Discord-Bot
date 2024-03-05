# test_common_functions.py

import pytest
from common import (
    is_admin_or_owner,
    dev_id,
    discord_admin_role,
    has_admin_role,
    format_stat_name,
    get_weather_forecast,
    create_event_if_necessary,
    check_existing_threads,
    generate_flight_search_url,
    parse_flight_data,
)
from utils import convert_to_pst
from datetime import datetime, timedelta, date
import discord
from unittest.mock import AsyncMock, MagicMock, Mock


@pytest.mark.asyncio
async def test_is_admin_or_owner_as_admin():
    mock_interaction = AsyncMock()
    mock_interaction.user.id = "123456789"
    admin_role = MagicMock(spec=discord.Role)
    admin_role.name = discord_admin_role
    mock_interaction.user.roles = [admin_role]

    result = await is_admin_or_owner(mock_interaction)
    assert result


@pytest.mark.asyncio
async def test_is_admin_or_owner_as_owner():
    mock_interaction = AsyncMock()
    mock_interaction.user.id = dev_id
    result = await is_admin_or_owner(mock_interaction)
    assert result


@pytest.mark.asyncio
async def test_is_admin_or_owner_as_non_admin():
    mock_interaction = AsyncMock()
    mock_interaction.user.id = "987654321"
    mock_interaction.user.roles = [MagicMock(name="Member")]
    result = await is_admin_or_owner(mock_interaction)
    assert not result


@pytest.mark.asyncio
async def test_has_admin_role_with_admin():
    mock_interaction = AsyncMock()
    admin_role = MagicMock(spec=discord.Role)
    admin_role.name = discord_admin_role
    mock_interaction.user.roles = [admin_role]

    result = await has_admin_role(mock_interaction)
    assert result


@pytest.mark.asyncio
async def test_has_admin_role_without_admin():
    mock_interaction = AsyncMock()
    mock_interaction.user.roles = [MagicMock(name="Member")]
    result = await has_admin_role(mock_interaction)
    assert not result


def test_format_stat_name():
    stat_names = ["gamesPlayed", "losses", "pointDifferential", "nonexistentStat"]
    expected_results = [
        "Games Played",
        "Losses",
        "Point Differential",
        "nonexistentStat",
    ]

    for stat, expected in zip(stat_names, expected_results):
        result = format_stat_name(stat)
        assert result == expected


@pytest.mark.asyncio
async def test_get_weather_forecast(monkeypatch):
    mock_weather_data = {
        "list": [
            {
                "dt": int(datetime(2024, 3, 1, 19, 0).timestamp()),
                "weather": [{"description": "sunny"}],
                "main": {"temp": 75},
            }
        ]
    }
    mock_fetch_openweather_data = AsyncMock(return_value=mock_weather_data)
    monkeypatch.setattr("common.fetch_openweather_data", mock_fetch_openweather_data)
    date_time_utc = "2024-03-01T19:00:00"
    latitude = 47.6062
    longitude = -122.3321

    result = await get_weather_forecast(date_time_utc, latitude, longitude)
    degree_sign = u"\N{DEGREE SIGN}"
    expected_result = f" sunny, Temperature: 75{degree_sign}F".encode('utf-8').decode('utf-8')
    assert result == expected_result


@pytest.mark.asyncio
async def test_create_event_for_home_game(monkeypatch):
    # Mock data for an empty list of scheduled events
    mock_fetch_scheduled_events = AsyncMock(return_value=[])

    # Mock for creating a scheduled event
    mock_create_scheduled_event = AsyncMock()

    # Applying the mocks to the respective Guild methods
    monkeypatch.setattr(
        "discord.Guild.fetch_scheduled_events", mock_fetch_scheduled_events
    )
    monkeypatch.setattr(
        "discord.Guild.create_scheduled_event", mock_create_scheduled_event
    )

    # Creating a mock Guild and Interaction object
    mock_guild = AsyncMock(spec=discord.Guild)
    mock_interaction = AsyncMock()
    mock_interaction.guild = mock_guild

    # Prepare match_info with is_home_game as True
    match_info = {
        "name": "Home Game Match",
        "date_time": "2024-03-01T19:00:00",
        "is_home_game": True,
        # Include other necessary fields
    }

    # Call the function with the mock data
    result = await create_event_if_necessary(mock_guild, match_info)

    # Check if the event creation message is returned
    assert "Event created:" in result

    # Assert that create_scheduled_event was called with expected arguments
    event_start_time_pst = convert_to_pst(match_info["date_time"]) - timedelta(hours=1)
    end_time = event_start_time_pst + timedelta(hours=2)
    mock_guild.create_scheduled_event.assert_called_once_with(
        name="March to the Match",
        start_time=event_start_time_pst,
        end_time=end_time,
        description=f"March to the Match for {match_info['name']}",
        location="117 S Washington St, Seattle, WA 98104",
        entity_type=discord.EntityType.external,
        privacy_level=discord.PrivacyLevel.guild_only,
    )


@pytest.mark.asyncio
async def test_check_existing_threads(monkeypatch):
    interaction = Mock()
    channel = MagicMock(spec=discord.ForumChannel)
    thread = Mock()
    thread.name = "test_thread"
    channel.threads = [thread]
    interaction.guild.channels = [channel]

    def mock_get_discord_utils_get(*args, **kwargs):
        if kwargs.get("name") == "test_channel":
            return channel
        return None

    monkeypatch.setattr("discord.utils.get", mock_get_discord_utils_get)

    result = await check_existing_threads(interaction, "test_thread", "test_channel")
    assert result


@pytest.mark.asyncio
async def test_generate_flight_search_url(monkeypatch):
    mock_flight_data = {
        "best_flights": [
            {
                "price": "350",
                "flights": [
                    {
                        "airline": "Test Airline",
                        "departure_airport": {"time": "10:00 AM"},
                        "arrival_airport": {"time": "12:00 PM"},
                    }
                ],
            }
        ],
        "search_metadata": {"google_flights_url": "https://www.google.com/flights"},
    }

    mock_get_airport_code_for_team = Mock(return_value="XYZ")
    mock_fetch_serpapi_flight_data = AsyncMock(return_value=mock_flight_data)
    monkeypatch.setattr(
        "common.get_airport_code_for_team", mock_get_airport_code_for_team
    )
    monkeypatch.setattr(
        "common.fetch_serpapi_flight_data", mock_fetch_serpapi_flight_data
    )

    result = await generate_flight_search_url(
        "SEA",
        "Team XYZ",
        date(2024, 3, 1),
        date(2024, 3, 2),
    )

    assert "https://www.google.com/flights" in result


def test_parse_flight_data():
    flight_data = {
        "best_flights": [
            {
                "price": "350",
                "flights": [
                    {
                        "airline": "Test Airline",
                        "departure_airport": {"time": "10:00 AM"},
                        "arrival_airport": {"time": "12:00 PM"},
                    }
                ],
            }
        ],
        "search_metadata": {"google_flights_url": "https://www.google.com/flights"},
    }

    result = parse_flight_data(flight_data)
    assert "Test Airline" in result
    assert "10:00 AM" in result
    assert "12:00 PM" in result
    assert "https://www.google.com/flights" in result
