# test_admin_commands.py

import unittest
import discord
from unittest.mock import AsyncMock, patch, MagicMock
from admin_commands import AdminCommands

class TestAdminCommands(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.bot = MagicMock()
        self.cog = AdminCommands(self.bot)
        self.mock_interaction = AsyncMock()

    @patch('admin_commands.has_admin_role', new_callable=AsyncMock)
    async def test_create_schedule_without_admin_role(self, mock_has_admin_role):
        """
        Test to ensure the 'createschedule' command checks for admin permissions and responds correctly if not present.
        - Mocks: Functionality to simulate a user without admin permissions.
        - Assertions: Verifies that the appropriate permission error message is sent to the user.
        """
        mock_has_admin_role.return_value = False
        await self.cog.create_schedule_command.callback(self.cog, self.mock_interaction)
        self.mock_interaction.response.send_message.assert_called_once_with(
            "You do not have the necessary permissions.", ephemeral=True
        )

    @patch('admin_commands.get_matches_for_calendar', new_callable=AsyncMock)
    @patch('admin_commands.has_admin_role', new_callable=AsyncMock)
    async def test_create_schedule_success(self, mock_has_admin_role, mock_get_matches_for_calendar):
        """
        Test the successful execution of the 'createschedule' command, resulting in the creation of the team schedule file.
        - Mocks: `has_admin_role` to return True and `get_matches_for_calendar` to return mock match data.
        - Assertions: Confirms that the team schedule file is created successfully and the appropriate success message is sent.
        """
        mock_has_admin_role.return_value = True
        mock_get_matches_for_calendar.return_value = [{'match1': 'details'}, {'match2': 'details'}]
        await self.cog.create_schedule_command.callback(self.cog, self.mock_interaction)
        self.mock_interaction.followup.send.assert_called_once_with("Team schedule created successfully.")

    @patch('admin_commands.get_matches_for_calendar', new_callable=AsyncMock)
    @patch('admin_commands.has_admin_role', new_callable=AsyncMock)
    async def test_create_schedule_no_match_data(self, mock_has_admin_role, mock_get_matches_for_calendar):
        """
        Test the 'createschedule' command when no match data is available.
        - Mocks: `has_admin_role` to return True and `get_matches_for_calendar` to return None, simulating no match data found.
        - Assertions: Checks that the command correctly identifies the absence of match data and informs the user accordingly.
        """
        mock_has_admin_role.return_value = True
        mock_get_matches_for_calendar.return_value = None
        await self.cog.create_schedule_command.callback(self.cog, self.mock_interaction)
        self.mock_interaction.followup.send.assert_called_once_with("No match data found.")

    @patch('admin_commands.get_matches_for_calendar', new_callable=AsyncMock)
    @patch('admin_commands.has_admin_role', new_callable=AsyncMock)
    async def test_create_schedule_exception(self, mock_has_admin_role, mock_get_matches_for_calendar):
        """
        Test the error handling of the 'createschedule' command when an exception occurs during execution.
        - Mocks: `has_admin_role` to return True and `get_matches_for_calendar` to raise an exception, simulating an error during schedule creation.
        - Assertions: Verifies that the command correctly handles the exception and sends an error message to the user.
        """
        mock_has_admin_role.return_value = True
        mock_get_matches_for_calendar.side_effect = Exception("Test Exception")
        await self.cog.create_schedule_command.callback(self.cog, self.mock_interaction)
        self.mock_interaction.followup.send.assert_called_with("Failed to create schedule: Test Exception")
        
    @patch('admin_commands.has_admin_role', new_callable=AsyncMock)
    async def test_new_season_without_admin_role(self, mock_has_admin_role):
        """
        Test the 'newseason' command when executed by a user without admin permissions.
        - Mocks: `has_admin_role` to return False, simulating a user without admin rights.
        - Assertions: Checks if a permission error message is sent, indicating the user cannot execute this command.
        """
        mock_has_admin_role.return_value = False

        await self.cog.new_season.callback(self.cog, self.mock_interaction)

        self.mock_interaction.response.send_message.assert_called_once_with(
            "You do not have the necessary permissions.", ephemeral=True
        )

    @patch('admin_commands.has_admin_role', new_callable=AsyncMock)
    async def test_new_season_success(self, mock_has_admin_role):
        """
        Test the successful execution of the 'newseason' command by an admin user.
        - Mocks: `has_admin_role` to return True, indicating the user has admin permissions.
        - Assertions: Confirms that the command successfully opens a modal for creating a new season.
        """
        mock_has_admin_role.return_value = True

        await self.cog.new_season.callback(self.cog, self.mock_interaction)

        self.mock_interaction.response.send_modal.assert_called_once()
        
    @patch('admin_commands.has_admin_role', new_callable=AsyncMock)
    async def test_check_order_without_admin_role(self, mock_has_admin_role):
        """
        Test the 'checkorder' command when executed by a user without admin permissions.
        - Mocks: `has_admin_role` to return False, simulating a user without the necessary permissions.
        - Assertions: Verifies that the command correctly identifies unauthorized users and sends a corresponding error message.
        """
        mock_has_admin_role.return_value = False

        await self.cog.check_order.callback(self.cog, self.mock_interaction)

        self.mock_interaction.response.send_message.assert_called_once_with(
            "You do not have the necessary permissions.", ephemeral=True
        )

    @patch('admin_commands.has_admin_role', new_callable=AsyncMock)
    async def test_check_order_success(self, mock_has_admin_role):
        """
        Test the successful execution of the 'checkorder' command by an admin user.
        - Mocks: `has_admin_role` to return True, signifying that the user has the necessary admin permissions.
        - Assertions: Ensures that the command opens the appropriate modal for checking an ECS membership order.
        """
        mock_has_admin_role.return_value = True

        await self.cog.check_order.callback(self.cog, self.mock_interaction)

        self.mock_interaction.response.send_modal.assert_called_once()

        
if __name__ == '__main__':
    unittest.main()