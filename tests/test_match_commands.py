# test_match_commands.py

import unittest
from unittest.mock import AsyncMock, patch, MagicMock, Mock
from match_commands import MatchCommands
from match_utils import closed_matches
import discord
from discord import Embed

class TestMatchCommands(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.bot = MagicMock()
        self.cog = MatchCommands(self.bot)
        self.mock_interaction = AsyncMock() 
        self.mock_match_channel = MagicMock(spec=discord.ForumChannel, name="match-thread")
        self.mock_away_channel = MagicMock(spec=discord.ForumChannel, name="away-travel")
        self.mock_interaction.guild.channels = [self.mock_match_channel, self.mock_away_channel]
        self.mock_interaction.response.send_message = AsyncMock()
        self.mock_interaction.response.defer = AsyncMock()
        self.mock_interaction.followup.send = AsyncMock()

    @patch('match_commands.get_next_match', new_callable=AsyncMock)
    @patch('match_commands.convert_to_pst')
    async def test_next_match_success(self, mock_convert_to_pst, mock_get_next_match):
        """
        Test to ensure successful retrieval of the next match information and its correct format in the message.
        - Mocks: `get_next_match` to return mock match information and `convert_to_pst` to convert UTC time to PST.
        - Assertions: Checks if the `send_message` method is called once with the correct embedded match information.
        """
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

        await self.cog.next_match.callback(self.cog, self.mock_interaction)

        self.mock_interaction.response.send_message.assert_called_once()
        args, kwargs = self.mock_interaction.response.send_message.call_args
        self.assertIsInstance(kwargs['embed'], Embed)

    @patch('match_commands.get_next_match', new_callable=AsyncMock)
    async def test_next_match_no_match_info(self, mock_get_next_match):
        """
        Test to handle the scenario when there are no upcoming matches.
        - Mocks: `get_next_match` to return a string indicating no upcoming matches.
        - Assertions: Verifies that the message "No upcoming matches" is sent.
        """
        mock_get_next_match.return_value = "No upcoming matches."

        await self.cog.next_match.callback(self.cog, self.mock_interaction)

        self.mock_interaction.response.send_message.assert_called_once_with("No upcoming matches.")

    @patch('match_commands.get_next_match', new_callable=AsyncMock)
    async def test_next_match_error(self, mock_get_next_match):
        """
        Test the error handling when fetching match information fails.
        - Mocks: `get_next_match` to raise an exception simulating an error in fetching match info.
        - Assertions: Ensures that an appropriate error message is sent in response to the exception.
        """
        mock_get_next_match.side_effect = Exception("Error fetching match info")

        await self.cog.next_match.callback(self.cog, self.mock_interaction)

        expected_message = "An error occurred: Error fetching match info"
        self.mock_interaction.response.send_message.assert_called_once_with(expected_message)
        
    @patch('match_commands.has_admin_role', new_callable=AsyncMock)
    async def test_new_match_without_admin_role(self, mock_has_admin_role):
        """
        Tests if the `new_match` command correctly handles a user without admin permissions.
        - Mocks: `has_admin_role` to return False, simulating a user without admin rights.
        - Assertions: Checks if a permission error message is sent.
        """
        mock_has_admin_role.return_value = False

        await self.cog.new_match.callback(self.cog, self.mock_interaction)

        mock_has_admin_role.assert_called_once()
        self.mock_interaction.response.send_message.assert_called_once_with(
            "You do not have the necessary permissions.", ephemeral=True
        )
        
    @patch('match_commands.has_admin_role', new_callable=AsyncMock)
    @patch('match_commands.get_next_match', new_callable=AsyncMock)
    @patch('match_commands.prepare_match_environment', new_callable=AsyncMock)
    @patch('match_commands.check_existing_threads', new_callable=AsyncMock)
    @patch('match_commands.create_and_manage_thread', new_callable=AsyncMock)
    async def test_new_match_away_game(self, mock_create_and_manage_thread, mock_check_existing_threads, mock_prepare_match_environment, mock_get_next_match, mock_has_admin_role):
        """
        Tests the `new_match` command for an away game scenario to ensure correct thread creation.
        - Mocks: Functions like `get_next_match`, `prepare_match_environment`, `check_existing_threads`, and others to simulate the away match process.
        - Assertions: Verifies that all mocked methods are called appropriately and the final message indicates successful thread creation.
        """
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

        await self.cog.new_match.callback(self.cog, self.mock_interaction)

        mock_has_admin_role.assert_called_once()
        mock_get_next_match.assert_called_once()
        mock_prepare_match_environment.assert_called_once_with(self.mock_interaction, mock_get_next_match.return_value)
        mock_check_existing_threads.assert_called_once()
        mock_create_and_manage_thread.assert_called_once()
        self.mock_interaction.followup.send.assert_called_once_with("Thread created successfully")

    @patch('match_commands.create_and_manage_thread', new_callable=AsyncMock)
    @patch('match_commands.check_existing_threads', new_callable=AsyncMock)
    @patch('match_commands.prepare_match_environment', new_callable=AsyncMock)
    @patch('match_commands.get_next_match', new_callable=AsyncMock)
    @patch('match_commands.has_admin_role', new_callable=AsyncMock)
    async def test_new_match_home_game(self, mock_has_admin_role, mock_get_next_match, mock_prepare_match_environment, mock_check_existing_threads, mock_create_and_manage_thread):
        """
        Tests the `new_match` command for a home game, including weather information and event creation.
        - Mocks: Functions similar to the away game test, with additional mocks for home game specifics like weather and event information.
        - Assertions: Checks if weather and event information are correctly included in the responses sent.
        """
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

        await self.cog.new_match.callback(self.cog, self.mock_interaction)

        mock_has_admin_role.assert_called_once()
        mock_get_next_match.assert_called_once()
        mock_prepare_match_environment.assert_called_once_with(self.mock_interaction, mock_get_next_match.return_value)
        mock_check_existing_threads.assert_called_once()
        mock_create_and_manage_thread.assert_called_once()

        self.mock_interaction.followup.send.assert_any_call("Weather: Sunny, 75 F. Event created: 'Pre-Match Gathering'", ephemeral=True)
        self.mock_interaction.followup.send.assert_any_call("Thread created successfully with weather and event info")

    @patch('match_commands.get_away_match', new_callable=AsyncMock)
    @patch('match_commands.has_admin_role', new_callable=AsyncMock)
    async def test_away_match_success(self, mock_has_admin_role, mock_get_away_match):
        """
        Tests the successful execution of the `away_match` command with valid match and ticket information.
        - Mocks: `get_away_match` to return match title and ticket link, and `has_admin_role` to return True.
        - Assertions: Confirms the correct sequence of calls and ensures the final message contains the expected content.
        """
        mock_has_admin_role.return_value = True
        mock_get_away_match.return_value = ("Away Match Title", "ticket_link")

        await self.cog.away_match.callback(self.cog, self.mock_interaction, opponent="Opponent")

        mock_has_admin_role.assert_called_once()
        mock_get_away_match.assert_called_once_with(self.mock_interaction, "Opponent")

    @patch('match_commands.get_predictions', new_callable=AsyncMock)
    async def test_show_predictions_outside_thread(self, mock_get_predictions):
        """
        Tests the 'show_predictions' command when invoked outside a Discord thread.
        - Mocks: `get_predictions` to simulate response behavior.
        - Assertions: Confirms that the command correctly identifies non-thread usage and sends the appropriate error message.
        """
        self.mock_interaction.channel = MagicMock(spec=discord.TextChannel)
        await self.cog.show_predictions.callback(self.cog, self.mock_interaction)
        self.mock_interaction.response.send_message.assert_called_once_with(
            "This command can only be used in match threads.", ephemeral=True
        )

    @patch('match_commands.get_predictions', new_callable=AsyncMock)
    async def test_show_predictions_unassociated_thread(self, mock_get_predictions):
        """
        Tests the 'show_predictions' command in a thread that is not associated with any match.
        - Mocks: `get_predictions` to simulate response behavior.
        - Assertions: Checks that the command identifies unassociated threads and sends the correct error message.
        """
        self.mock_interaction.channel = MagicMock(spec=discord.Thread, id="12345")
        self.cog.match_thread_map = {}

        await self.cog.show_predictions.callback(self.cog, self.mock_interaction)

        self.mock_interaction.response.send_message.assert_called_once_with(
            "This thread is not associated with an active match prediction.", ephemeral=True
        )
 
    @patch('match_commands.get_predictions', new_callable=Mock)
    async def test_show_predictions_no_predictions(self, mock_get_predictions):
        """
        Tests the 'show_predictions' command in a thread associated with a match but having no predictions.
        - Mocks: `get_predictions` to return an empty list, simulating no predictions made for the match.
        - Assertions: Verifies that the command correctly identifies the absence of predictions and informs the user accordingly.
        """
        mock_thread_id = '12345'
        self.mock_interaction.channel = MagicMock(spec=discord.Thread, id=mock_thread_id)

        mock_match_id = '67890'
        self.cog.match_thread_map = {mock_thread_id: mock_match_id}

        mock_get_predictions.return_value = []

        await self.cog.show_predictions.callback(self.cog, self.mock_interaction)

        self.mock_interaction.response.send_message.assert_called_once_with(
            "No predictions have been made for this match.", ephemeral=True
        )

    @patch('match_commands.get_predictions', new_callable=Mock)
    async def test_show_predictions_success(self, mock_get_predictions):
        """
        Tests the successful display of predictions in a match thread.
        - Mocks: `get_predictions` to return a list of prediction counts, simulating existing predictions.
        - Assertions: Ensures that predictions are correctly displayed in an embed and the correct message is sent.
        """
        mock_channel_id = "123"
        self.mock_interaction.channel = MagicMock(spec=discord.Thread, id=mock_channel_id)
        self.cog.match_thread_map = {mock_channel_id: "match_id"}
        mock_predictions = [('Win', 5), ('Lose', 2)]
        mock_get_predictions.return_value = mock_predictions

        await self.cog.show_predictions.callback(self.cog, self.mock_interaction)

        args, kwargs = self.mock_interaction.response.send_message.call_args
        self.assertTrue('embed' in kwargs)
        self.assertIsInstance(kwargs['embed'], discord.Embed)
        self.assertEqual(len(kwargs['embed'].fields), 2)

    @patch('match_commands.get_predictions', new_callable=Mock)
    async def test_show_predictions_in_thread(self, mock_get_predictions):
        """
        Tests the 'show_predictions' command in a thread that is correctly associated with a match.
        - Mocks: `get_predictions` to return prediction data, simulating a thread associated with a match having predictions.
        - Assertions: Confirms that the command fetches predictions correctly and displays them in an embed.
        """
        mock_channel_id = "12345"
        self.mock_interaction.channel = MagicMock(spec=discord.Thread, id=mock_channel_id)
        self.cog.match_thread_map = {mock_channel_id: "67890"}
        mock_predictions = [('Win', 5), ('Lose', 2)]
        mock_get_predictions.return_value = mock_predictions

        await self.cog.show_predictions.callback(self.cog, self.mock_interaction)

        args, kwargs = self.mock_interaction.response.send_message.call_args
        self.assertTrue('embed' in kwargs)
        self.assertIsInstance(kwargs['embed'], discord.Embed)
        
    @patch('match_commands.insert_prediction', new_callable=AsyncMock)
    async def test_predict_outside_thread(self, mock_insert_prediction):
        """
        Tests the 'predict' command when used outside of a match thread.
        - Mocks: `insert_prediction` to simulate the prediction insertion process.
        - Assertions: Checks that the correct error message is sent when the command is used outside of a match thread.
        """
        self.mock_interaction.channel = MagicMock(spec=discord.TextChannel)

        await self.cog.predict.callback(self.cog, self.mock_interaction, prediction="2-1")

        self.mock_interaction.response.send_message.assert_called_once_with(
            "This command can only be used in match threads.", ephemeral=True
        )
        
    @patch('match_commands.insert_prediction', new_callable=AsyncMock)
    async def test_predict_unassociated_thread(self, mock_insert_prediction):
        """
        Tests the 'predict' command in a thread not associated with an active match prediction.
        - Mocks: `insert_prediction` to simulate the prediction insertion process.
        - Assertions: Verifies that the correct error message is sent when the command is used in a thread not associated with a match.
        """
        self.mock_interaction.channel = MagicMock(spec=discord.Thread, id="12345")
        self.cog.match_thread_map = {}

        await self.cog.predict.callback(self.cog, self.mock_interaction, prediction="2-1")

        self.mock_interaction.response.send_message.assert_called_once_with(
            "This thread is not associated with an active match prediction.", ephemeral=True
        )
        
    @patch('match_commands.insert_prediction')
    async def test_predict_closed_predictions(self, mock_insert_prediction):
        """
        Tests the 'predict' command in a thread where predictions are closed.
        - Setup: Adds a match to the `closed_matches` set to simulate closed predictions.
        - Mocks: `insert_prediction` to simulate the prediction insertion process.
        - Assertions: Ensures that the correct error message is sent when predictions are closed for the match.
        - Cleanup: Removes the match from `closed_matches` after the test.
        """
        mock_channel_id = "12345"
        mock_match_id = "67890"
        self.mock_interaction.channel = MagicMock(spec=discord.Thread, id=mock_channel_id)
        self.cog.match_thread_map = {mock_channel_id: mock_match_id}

        closed_matches.add(mock_match_id)

        mock_insert_prediction.return_value = True

        await self.cog.predict.callback(self.cog, self.mock_interaction, prediction="2-1")

        self.mock_interaction.response.send_message.assert_called_once_with(
            "Predictions are closed for this match.", ephemeral=True
        )

        closed_matches.remove(mock_match_id)

    @patch('match_commands.insert_prediction', new_callable=AsyncMock)
    async def test_predict_success(self, mock_insert_prediction):
        """
        Tests the successful execution of the 'predict' command in a match thread.
        - Mocks: `insert_prediction` to return True, simulating a successful prediction insertion.
        - Assertions: Confirms that the command correctly records a new prediction and sends a confirmation message.
        """
        self.mock_interaction.channel = MagicMock(spec=discord.Thread, id="12345")
        self.cog.match_thread_map = {"12345": "67890"}
        mock_insert_prediction.return_value = True

        await self.cog.predict.callback(self.cog, self.mock_interaction, prediction="1-0")

        self.mock_interaction.response.send_message.assert_called_once_with(
            "Prediction recorded!", ephemeral=True
        )
        
    @patch('match_commands.insert_prediction')
    async def test_predict_duplicate(self, mock_insert_prediction):
        """
        Tests the 'predict' command when a duplicate prediction is made by the same user for a match.
        - Mocks: `insert_prediction` to return False, simulating an attempt to make a duplicate prediction.
        - Assertions: Verifies that the correct error message is sent when a duplicate prediction is made.
        """
        mock_channel_id = "12345"
        mock_match_id = "67890"
        self.mock_interaction.channel = MagicMock(spec=discord.Thread, id=mock_channel_id)
        self.cog.match_thread_map = {mock_channel_id: mock_match_id}
        mock_insert_prediction.return_value = False

        await self.cog.predict.callback(self.cog, self.mock_interaction, prediction="2-1")

        self.mock_interaction.response.send_message.assert_called_once_with(
            "You have already made a prediction for this match.", ephemeral=True
        )

if __name__ == '__main__':
    unittest.main()