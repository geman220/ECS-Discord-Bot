# test_general_commands.py

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from general_commands import GeneralCommands
import warnings

warnings.filterwarnings("ignore", category=ResourceWarning)

class TestAwayTicketsCommand(unittest.IsolatedAsyncioTestCase):
    
    @patch('api_helpers.call_woocommerce_api')
    async def test_away_tickets_closest_upcoming_match(self, mock_call_api):
        """
        Test for retrieving the closest upcoming away match.
        - Mocks API response with two scheduled matches.
        - Asserts that send_message is called with details of the closest match.
        """
        mock_products_response = [
            {
                "name": "Away vs LAFC | 2024-02-24",
                "permalink": "https://example-website.com/product/away-vs-lafc-2024-02-24/"
            },
            {
                "name": "Away vs Philadelphia | 2024-03-09",
                "permalink": "https://example-website.com/product/away-vs-philadelphia-union-2024-03-09/"
            }
        ]

        mock_call_api.return_value = AsyncMock(return_value=mock_products_response)

        mock_interaction = MagicMock()
        mock_interaction.response.send_message = AsyncMock()

        cog = GeneralCommands(bot=MagicMock())
        await cog.away_tickets.callback(cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()

    @patch('api_helpers.call_woocommerce_api')
    async def test_away_tickets_with_existing_opponent(self, mock_call_api):
        """
        Test for retrieving an away match for a specific existing opponent.
        - Mocks API response with a match against the specified opponent.
        - Asserts that send_message is called with match details.
        """
        mock_call_api.return_value = AsyncMock(return_value=[
            {
                "name": "Match vs Miami",
                "permalink": "miami_match_ticket_link"
            }
        ])

        mock_interaction = MagicMock()
        mock_interaction.response.send_message = AsyncMock()

        cog = GeneralCommands(bot=MagicMock())
        await cog.away_tickets.callback(cog, mock_interaction, opponent="Miami")

        mock_interaction.response.send_message.assert_called_once()

    @patch('api_helpers.call_woocommerce_api')
    async def test_away_tickets_with_nonexistent_opponent(self, mock_call_api):
        """
        Test for handling a non-existent opponent in away match lookup.
        - Mocks API response with an empty list to simulate no matches found.
        - Asserts that send_message is called with a 'no matches found' message.
        """
        mock_call_api.return_value = AsyncMock(return_value=[])

        mock_interaction = MagicMock()
        mock_interaction.response.send_message = AsyncMock()

        cog = GeneralCommands(bot=MagicMock())
        await cog.away_tickets.callback(cog, mock_interaction, opponent="1231241354")

        error_message = "No upcoming away matches found."
        mock_interaction.response.send_message.assert_called_once_with(error_message)

if __name__ == '__main__':
    unittest.main()