# test_woocommerce_commands.py

import csv
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call
from woocommerce_commands import WooCommerceCommands
import discord

class TestWooCommerceCommands(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = MagicMock()
        self.cog = WooCommerceCommands(self.bot)
        self.mock_interaction = MagicMock()
        self.mock_interaction.response.defer = AsyncMock()
        self.mock_interaction.followup.send = AsyncMock()
        self.mock_interaction.response.send_message = AsyncMock()

    async def mock_required_role(self, interaction):
        return True

    async def mock_no_required_role(self, interaction):
        return False

    @patch('woocommerce_commands.call_woocommerce_api')
    @patch('woocommerce_commands.has_required_wg_role')
    async def test_list_tickets_success(self, mock_role_check, mock_call_api):
        """
        Test to ensure successful listing of both home and away tickets.
        - Mocks API calls to return home and away ticket lists.
        - Verifies the correct message format is sent with home and away ticket names.
        """
        mock_role_check.side_effect = self.mock_required_role
        mock_home_tickets = [
            {"id": 1, "name": "Generic Home Match 1", "permalink": "https://example.com/home1"},
            {"id": 2, "name": "Generic Home Match 2", "permalink": "https://example.com/home2"}
        ]
        mock_away_tickets = [
            {"id": 3, "name": "Generic Away Match 1", "permalink": "https://example.com/away1"}
        ]
        mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

        await self.cog.list_tickets.callback(self.cog, self.mock_interaction)

        expected_message = ("🏠 **Home Tickets:**\nGeneric Home Match 1\nGeneric Home Match 2\n\n"
                            "🚗 **Away Tickets:**\nGeneric Away Match 1")
        home_tickets_url = 'https://weareecs.com/wp-json/wc/v3/products?category=765197885'
        away_tickets_url = 'https://weareecs.com/wp-json/wc/v3/products?category=765197886'
        mock_call_api.assert_has_calls([
            call(self.mock_interaction, home_tickets_url),
            call(self.mock_interaction, away_tickets_url)
        ])
        self.mock_interaction.followup.send.assert_called_once_with(expected_message, ephemeral=True)

    @patch('woocommerce_commands.call_woocommerce_api')
    @patch('woocommerce_commands.has_required_wg_role')
    async def test_list_tickets_no_home_tickets(self, mock_role_check, mock_call_api):
        """
        Test to handle the scenario when no home tickets are available.
        - Mocks API call for home tickets to return an empty list.
        - Verifies that the message correctly indicates no home tickets available.
        """
        mock_role_check.side_effect = self.mock_required_role
        mock_home_tickets = []
        mock_away_tickets = [{"name": "Away Match 1"}, {"name": "Away Match 2"}]
        mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

        self.mock_interaction.response.defer = AsyncMock()

        await self.cog.list_tickets.callback(self.cog, self.mock_interaction)

        expected_message = "🏠 **Home Tickets:**\nNo home tickets found.\n\n🚗 **Away Tickets:**\nAway Match 1\nAway Match 2"
        self.mock_interaction.followup.send.assert_called_once_with(expected_message, ephemeral=True)

    @patch('woocommerce_commands.call_woocommerce_api')
    @patch('woocommerce_commands.has_required_wg_role')
    async def test_list_tickets_no_away_tickets(self, mock_role_check, mock_call_api):
        """
        Test to handle the scenario when no away tickets are available.
        - Mocks API call for away tickets to return an empty list.
        - Verifies that the message correctly indicates no away tickets available.
        """
        mock_role_check.side_effect = self.mock_required_role
        mock_home_tickets = [{"name": "Home Match 1"}, {"name": "Home Match 2"}]
        mock_away_tickets = [] 
        mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

        self.mock_interaction.response.defer = AsyncMock()

        await self.cog.list_tickets.callback(self.cog, self.mock_interaction)

        expected_message = "🏠 **Home Tickets:**\nHome Match 1\nHome Match 2\n\n🚗 **Away Tickets:**\nNo away tickets found."
        self.mock_interaction.followup.send.assert_called_once_with(expected_message, ephemeral=True)

    @patch('woocommerce_commands.call_woocommerce_api')
    @patch('woocommerce_commands.has_required_wg_role')
    async def test_list_tickets_no_tickets_available(self, mock_role_check, mock_call_api):
        """
        Test to handle the scenario when both home and away tickets are unavailable.
        - Mocks API calls for both home and away tickets to return empty lists.
        - Verifies that the message correctly indicates no tickets available for both categories.
        """
        mock_role_check.side_effect = self.mock_required_role
        mock_home_tickets = [] 
        mock_away_tickets = [] 
        mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

        self.mock_interaction.response.defer = AsyncMock()

        await self.cog.list_tickets.callback(self.cog, self.mock_interaction)

        expected_message = "🏠 **Home Tickets:**\nNo home tickets found.\n\n🚗 **Away Tickets:**\nNo away tickets found."
        self.mock_interaction.followup.send.assert_called_once_with(expected_message, ephemeral=True)

    @patch('woocommerce_commands.has_required_wg_role')
    async def test_list_tickets_no_permission(self, mock_role_check):
        """
        Test to verify proper handling of insufficient permissions.
        - Mocks the role check to return a negative result, simulating a user without required permissions.
        - Verifies that the correct permission error message is sent.
        """
        mock_role_check.side_effect = self.mock_no_required_role
        await self.cog.list_tickets.callback(self.cog, self.mock_interaction)
        self.mock_interaction.response.send_message.assert_called_once_with(
            "You do not have the necessary permissions.", ephemeral=True)
        
class TestGetProductOrdersCommand(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.bot = MagicMock()
        self.cog = WooCommerceCommands(self.bot)
        self.mock_interaction = MagicMock()
        self.mock_interaction.response.defer = AsyncMock()
        self.mock_interaction.response.send_message = AsyncMock()
        self.mock_interaction.followup.send = AsyncMock()

    async def mock_required_role(self, interaction):
        return True

    async def mock_no_required_role(self, interaction):
        return False

    @patch('woocommerce_commands.call_woocommerce_api')
    @patch('woocommerce_commands.has_required_wg_role')
    async def test_get_product_orders_success(self, mock_role_check, mock_call_api):
        """
        Test to ensure successful retrieval of product orders.
        - Simulates API calls to retrieve product and orders.
        - Validates CSV file generation and content.
        """
        mock_role_check.side_effect = self.mock_required_role
        product_title = "Away vs LAFC | 2024-02-24"
        product_id = 996603

        mock_product_response = [{"name": product_title, "id": product_id}]
        mock_orders_response = [
            {
                "id": 12345,
                "billing": {
                    "first_name": "John",
                    "last_name": "Doe",
                    "email": "johndoe@example.com",
                    "address_1": "123 Main St",
                    "address_2": "",
                    "city": "Seattle",
                    "state": "WA",
                    "postcode": "98101",
                    "country": "US"
                },
                "line_items": [
                    {
                        "name": product_title,
                        "product_id": product_id,
                        "quantity": 2,
                        "price": "50.00",
                        "variation_id": "0"
                    }
                ],
                "date_paid": "2024-01-21T23:03:50",
                "number": "12345",
                "status": "completed",
                "customer_note": ""
            },
        ]

        mock_call_api.side_effect = [mock_product_response, mock_orders_response]

        await self.cog.get_product_orders.callback(self.cog, self.mock_interaction, product_title)

        args, kwargs = self.mock_interaction.followup.send.call_args
        self.assertTrue('file' in kwargs)
        file = kwargs['file']
        self.assertIsInstance(file, discord.File)

        file.fp.seek(0)
        reader = csv.reader(file.fp)
        rows = list(reader)
        expected_header = ["Product Name", "Customer First Name", "Customer Last Name", "Customer Email",
                           "Order Date Paid", "Order Line Item Quantity", "Order Line Item Price", "Order Number", "Order Status",
                           "Order Customer Note", "Product Variation Name", "Billing Address", "Shipping Address"]
        self.assertEqual(rows[0], expected_header)
        self.assertEqual(rows[1][0], product_title) 
        self.assertEqual(rows[1][1], "John")

    @patch('woocommerce_commands.call_woocommerce_api')
    @patch('woocommerce_commands.has_required_wg_role')
    async def test_get_product_orders_no_products_found(self, mock_role_check, mock_call_api):
        """
        Test to handle the scenario when no products are found.
        - Mocks API call for products to return an empty list.
        - Verifies that the correct message is sent indicating no products found.
        """
        mock_role_check.side_effect = self.mock_required_role
        mock_call_api.return_value = AsyncMock(return_value=[])

        await self.cog.get_product_orders.callback(self.cog, self.mock_interaction, "Nonexistent Product")

        self.mock_interaction.followup.send.assert_called_once_with("Product not found.", ephemeral=True)

    @patch('woocommerce_commands.call_woocommerce_api')
    @patch('woocommerce_commands.has_required_wg_role')
    async def test_get_product_orders_product_not_found(self, mock_role_check, mock_call_api):
        """
        Test to handle the scenario when the specified product is not found.
        - Mocks API call for products to return a list without the specified product.
        - Verifies that the correct message is sent indicating the product is not found.
        """
        mock_role_check.side_effect = self.mock_required_role
        mock_products = [{"name": "Other Product", "id": 2}]
        mock_call_api.return_value = mock_products

        await self.cog.get_product_orders.callback(self.cog, self.mock_interaction, "Nonexistent Product")

        self.mock_interaction.followup.send.assert_called_once_with("Product not found.", ephemeral=True)

    @patch('woocommerce_commands.call_woocommerce_api')
    @patch('woocommerce_commands.has_required_wg_role')
    async def test_get_product_orders_no_orders(self, mock_role_check, mock_call_api):
        """
        Test to handle the scenario when no orders are found for the specified product.
        - Mocks API call for products and orders, with orders returning an empty list.
        - Verifies that the correct message is sent indicating no orders found for the product.
        """
        mock_role_check.side_effect = self.mock_required_role
        mock_products = [{"name": "Existing Product", "id": 1}] 
        mock_orders = [] 
        mock_call_api.side_effect = [mock_products, mock_orders]

        await self.cog.get_product_orders.callback(self.cog, self.mock_interaction, "Existing Product")

        self.mock_interaction.followup.send.assert_called_once_with("No orders found for this product.", ephemeral=True)

    @patch('woocommerce_commands.has_required_wg_role')
    async def test_get_product_orders_no_permission(self, mock_role_check):
        """
        Test to verify proper handling of insufficient permissions.
        - Mocks the role check to return a negative result, simulating a user without required permissions.
        - Verifies that the correct permission error message is sent.
        """
        mock_role_check.side_effect = self.mock_no_required_role

        await self.cog.get_product_orders.callback(self.cog, self.mock_interaction, "Any Product")

        self.mock_interaction.response.send_message.assert_called_once_with(
            "You do not have the necessary permissions.", ephemeral=True)

if __name__ == '__main__':
    unittest.main()