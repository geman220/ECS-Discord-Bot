# test_common_functions.py

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from common import is_admin_or_owner, dev_id, discord_admin_role, has_admin_role, format_stat_name, get_weather_forecast, create_event_if_necessary, check_existing_threads, generate_flight_search_url, parse_flight_data
import datetime
import discord

class TestCommonFunctions(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.dev_id = dev_id

    def test_is_admin_or_owner_as_admin(self):
        """
        Test the 'is_admin_or_owner' function with a user having the admin role.
        - Mocks: A user with an admin role.
        - Assertions: Checks if the function returns True, indicating the user is recognized as an admin.
        """
        mock_interaction = AsyncMock()
        mock_interaction.user.id = '123456789'

        admin_role = MagicMock(spec=discord.Role)
        admin_role.name = discord_admin_role
        mock_interaction.user.roles = [admin_role]

        result = asyncio.run(is_admin_or_owner(mock_interaction))
        self.assertTrue(result)

    def test_is_admin_or_owner_as_owner(self):
        """
        Test the 'is_admin_or_owner' function with the owner of the server.
        - Mocks: The server owner user.
        - Assertions: Ensures the function correctly identifies the server owner and returns True.
        """
        mock_interaction = AsyncMock()
        mock_interaction.user.id = self.dev_id
        result = asyncio.run(is_admin_or_owner(mock_interaction))
        self.assertTrue(result)

    def test_is_admin_or_owner_as_non_admin(self):
        """
        Test the 'is_admin_or_owner' function with a non-admin user.
        - Mocks: A user without admin privileges.
        - Assertions: Verifies that the function returns False for a non-admin user.
        """
        mock_interaction = AsyncMock()
        mock_interaction.user.id = '987654321'
        mock_interaction.user.roles = [MagicMock(name='Member')]
        result = asyncio.run(is_admin_or_owner(mock_interaction))
        self.assertFalse(result)
        
    def test_has_admin_role_with_admin(self):
        """
        Test the 'has_admin_role' function with a user having the admin role.
        - Mocks: A user with an admin role as per the server's configuration.
        - Assertions: Checks that the function accurately identifies an admin user and returns True.
        """
        mock_interaction = AsyncMock()
        admin_role = MagicMock(spec=discord.Role)
        admin_role.name = discord_admin_role
        mock_interaction.user.roles = [admin_role]

        result = asyncio.run(has_admin_role(mock_interaction))
        self.assertTrue(result)

    def test_has_admin_role_without_admin(self):
        """
        Test the 'has_admin_role' function with a user lacking the admin role.
        - Mocks: A regular user without admin privileges.
        - Assertions: Ensures that the function correctly identifies a non-admin user and returns False.
        """
        mock_interaction = AsyncMock()
        mock_interaction.user.roles = [MagicMock(name='Member')]
        result = asyncio.run(has_admin_role(mock_interaction))
        self.assertFalse(result)
        
    def test_format_stat_name(self):
        """
        Test the functionality of the 'format_stat_name' function.
        - Scenario: Converts internal stat names to more readable formats and handles unknown stat names.
        - Assertions: Ensures that each stat name is correctly formatted or returned as is if not found in the mappings.
        """
        stat_names = ["gamesPlayed", "losses", "pointDifferential", "nonexistentStat"]
        expected_results = ["Games Played", "Losses", "Point Differential", "nonexistentStat"]
    
        for stat, expected in zip(stat_names, expected_results):
            result = format_stat_name(stat)
            self.assertEqual(result, expected)
            
    @patch('common.fetch_openweather_data', new_callable=AsyncMock)
    async def test_get_weather_forecast(self, mock_fetch_openweather_data):
        """
        Test the 'get_weather_forecast' function for accurate weather data retrieval.
        - Mocks: `fetch_openweather_data` to return predefined weather data for a specific date and time.
        - Scenario: Simulates fetching weather data for a specific date and asserts the function's ability to parse and return a formatted weather forecast.
        - Assertions: Confirms the function returns the correct weather description and temperature.
        """
        mock_weather_data = {
            'list': [
                {
                    'dt': int(datetime.datetime(2024, 3, 1, 19, 0).timestamp()),
                    'weather': [{'description': 'sunny'}],
                    'main': {'temp': 75}
                }
            ]
        }
        mock_fetch_openweather_data.return_value = mock_weather_data
        interaction = AsyncMock()
        date_time_utc = '2024-03-01T19:00:00'
        latitude = 47.6062
        longitude = -122.3321

        result = await get_weather_forecast(interaction, date_time_utc, latitude, longitude)
        expected_result = 'Weather: sunny, Temperature: 75 F'

        self.assertEqual(result, expected_result)
        
    @patch('common.fetch_openweather_data', new_callable=AsyncMock)
    @patch('discord.Guild.create_scheduled_event', new_callable=AsyncMock)
    @patch('discord.Guild.fetch_scheduled_events', new_callable=AsyncMock)
    async def test_create_event_if_necessary(self, mock_fetch_scheduled_events, mock_create_scheduled_event, mock_fetch_openweather_data):
        """
        Test the 'create_event_if_necessary' function for event creation in Discord.
        - Mocks: `fetch_scheduled_events` to return no existing events and `create_scheduled_event` to simulate the creation of a new event.
        - Scenario: Tests whether a new event is created when no existing events are found for the specified match.
        - Assertions: Verifies that the function calls 'create_scheduled_event' and returns a message confirming the creation of the event.
        """
        mock_fetch_scheduled_events.return_value = []

        mock_guild = AsyncMock(spec=discord.Guild)
        mock_interaction = AsyncMock()
        mock_interaction.guild = mock_guild

        match_info = {'name': 'Match Name', 'date_time': '2024-03-01T19:00:00'}

        result = await create_event_if_necessary(mock_interaction, match_info)

        self.assertIn("Event created:", result)
        mock_guild.create_scheduled_event.assert_called_once()
 
    @patch('discord.utils.get')
    async def test_thread_exists(self, mock_get):
        """
        Test the 'check_existing_threads' function to identify existing threads in a forum channel.
        - Setup: Creates mock objects for interaction, channel, and thread. The test simulates a scenario where a thread named "test_thread" exists in a forum channel named "test_channel".
        - Mocks: `discord.utils.get` to return the mocked channel when looking for "test_channel" in the guild's channels.
        - Scenario: Verifies if the function correctly identifies the presence of "test_thread" in "test_channel".
        - Assertions: Asserts that the function returns True, indicating the thread's existence in the specified channel.
        """
        interaction = Mock()
        channel = MagicMock(spec=discord.ForumChannel)
        thread = Mock()
        thread.name = "test_thread"
        channel.threads = [thread]
        interaction.guild.channels = [channel]

        mock_get.return_value = channel

        result = await check_existing_threads(interaction, "test_thread", "test_channel")

        self.assertTrue(result)
        
    @patch('common.fetch_serpapi_flight_data', new_callable=AsyncMock)
    @patch('common.get_airport_code_for_team')
    async def test_generate_flight_search_url(self, mock_get_airport_code_for_team, mock_fetch_serpapi_flight_data):
        """
        Test the 'generate_flight_search_url' function for generating a URL for flight searches.
        - Mocks: `fetch_serpapi_flight_data` to return mock flight data and `get_airport_code_for_team` to return a mock airport code.
        - Scenario: Simulates generating a flight search URL for a specified team and travel dates.
        - Assertions: Verifies that the function returns a string containing the Google Flights URL, confirming successful URL generation.
        """
        mock_get_airport_code_for_team.return_value = "XYZ"

        mock_flight_data = {
            "search_metadata": {
                "google_flights_url": "https://www.google.com/flights"
            },
            "best_flights": [
                {
                    "price": "350",
                    "flights": [
                        {
                            "airline": "Test Airline",
                            "departure_airport": {"time": "2024-03-01T10:00:00"},
                            "arrival_airport": {"time": "2024-03-01T12:00:00"}
                        }
                    ]
                }
            ]
        }
        mock_fetch_serpapi_flight_data.return_value = mock_flight_data

        interaction = AsyncMock()

        result = await generate_flight_search_url(interaction, "SEA", "Team XYZ", "2024-03-01", "2024-03-02")

        self.assertIn("https://www.google.com/flights", result)
        
    def test_parse_flight_data(self):
        """
        Test the 'parse_flight_data' function for processing flight API response data.
        - Scenario: Provides mock flight data mimicking the response from a flight API, including price, airline, and times.
        - Assertions: Checks if the function correctly parses and formats the flight data, including the airline, departure and arrival times, and a link to Google Flights.
        """
        flight_data = {
            "best_flights": [
                {
                    "price": "350",
                    "flights": [
                        {
                            "airline": "Test Airline",
                            "departure_airport": {"time": "10:00 AM"},
                            "arrival_airport": {"time": "12:00 PM"}
                        }
                    ]
                }
            ],
            "search_metadata": {"google_flights_url": "https://www.google.com/flights"}
        }

        result = parse_flight_data(flight_data)

        self.assertIn("Test Airline", result)
        self.assertIn("10:00 AM", result)
        self.assertIn("12:00 PM", result)
        self.assertIn("https://www.google.com/flights", result)

if __name__ == '__main__':
    unittest.main()
