# test_woocommerce_commands.py

import pytest
import csv
from woocommerce_commands import WooCommerceCommands
from unittest.mock import AsyncMock, MagicMock
import discord

# Fixture for WooCommerceCommands cog
@pytest.fixture
def woocommerce_commands_bot():
    return WooCommerceCommands(bot=MagicMock())

# Fixture for mock interaction
@pytest.fixture
def mock_interaction():
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.response.send_message = AsyncMock()
    return interaction

# Fixture for mocking API calls
@pytest.fixture
def mock_call_api(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr('woocommerce_commands.call_woocommerce_api', async_mock)
    return async_mock

# Fixture for mocking role check
@pytest.fixture
def mock_role_check(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr('woocommerce_commands.has_required_wg_role', async_mock)
    return async_mock

@pytest.mark.asyncio
async def test_list_tickets_success(woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check):
    mock_role_check.side_effect = lambda _: True
    mock_home_tickets = [
        {"id": 1, "name": "Generic Home Match 1", "permalink": "https://example-website.com/home1"},
        {"id": 2, "name": "Generic Home Match 2", "permalink": "https://example-website.com/home2"}
    ]
    mock_away_tickets = [
        {"id": 3, "name": "Generic Away Match 1", "permalink": "https://example-website.com/away1"}
    ]
    mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

    await woocommerce_commands_bot.list_tickets.callback(woocommerce_commands_bot, mock_interaction)

    expected_message = ("🏠 **Home Tickets:**\nGeneric Home Match 1\nGeneric Home Match 2\n\n"
                        "🚗 **Away Tickets:**\nGeneric Away Match 1")
    mock_interaction.followup.send.assert_called_once_with(expected_message, ephemeral=True)

@pytest.mark.asyncio
async def test_list_tickets_no_home_tickets(woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check):
    mock_role_check.side_effect = lambda _: True
    mock_home_tickets = []
    mock_away_tickets = [{"name": "Away Match 1"}, {"name": "Away Match 2"}]
    mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

    await woocommerce_commands_bot.list_tickets.callback(woocommerce_commands_bot, mock_interaction)

    expected_message = "🏠 **Home Tickets:**\nNo home tickets found.\n\n🚗 **Away Tickets:**\nAway Match 1\nAway Match 2"
    mock_interaction.followup.send.assert_called_once_with(expected_message, ephemeral=True)

@pytest.mark.asyncio
async def test_list_tickets_no_away_tickets(woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check):
    mock_role_check.side_effect = lambda _: True
    mock_home_tickets = [{"name": "Home Match 1"}, {"name": "Home Match 2"}]
    mock_away_tickets = []
    mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

    await woocommerce_commands_bot.list_tickets.callback(woocommerce_commands_bot, mock_interaction)

    expected_message = "🏠 **Home Tickets:**\nHome Match 1\nHome Match 2\n\n🚗 **Away Tickets:**\nNo away tickets found."
    mock_interaction.followup.send.assert_called_once_with(expected_message, ephemeral=True)

@pytest.mark.asyncio
async def test_list_tickets_no_tickets_available(woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check):
    mock_role_check.side_effect = lambda _: True
    mock_home_tickets = []
    mock_away_tickets = []
    mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

    await woocommerce_commands_bot.list_tickets.callback(woocommerce_commands_bot, mock_interaction)

    expected_message = "🏠 **Home Tickets:**\nNo home tickets found.\n\n🚗 **Away Tickets:**\nNo away tickets found."
    mock_interaction.followup.send.assert_called_once_with(expected_message, ephemeral=True)

@pytest.mark.asyncio
async def test_list_tickets_no_permission(woocommerce_commands_bot, mock_interaction, mock_role_check):
    mock_role_check.side_effect = lambda _: False

    await woocommerce_commands_bot.list_tickets.callback(woocommerce_commands_bot, mock_interaction)
    mock_interaction.response.send_message.assert_called_once_with(
        "You do not have the necessary permissions.", ephemeral=True)
     
@pytest.mark.asyncio
async def test_get_product_orders_success(woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check):
    mock_role_check.side_effect = lambda _: True
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

    await woocommerce_commands_bot.get_product_orders.callback(woocommerce_commands_bot, mock_interaction, product_title)

    # Assertions
    args, kwargs = mock_interaction.followup.send.call_args
    assert 'file' in kwargs
    file = kwargs['file']
    assert isinstance(file, discord.File)

    file.fp.seek(0)
    reader = csv.reader(file.fp)
    rows = list(reader)
    expected_header = ["Product Name", "Customer First Name", "Customer Last Name", "Customer Email",
                       "Order Date Paid", "Order Line Item Quantity", "Order Line Item Price", "Order Number", "Order Status",
                       "Order Customer Note", "Product Variation Name", "Billing Address", "Shipping Address"]
    assert rows[0] == expected_header
    assert rows[1][0] == product_title
    assert rows[1][1] == "John"

@pytest.mark.asyncio
async def test_get_product_orders_no_products_found(woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check):
    mock_role_check.side_effect = lambda _: True
    mock_call_api.return_value = AsyncMock(return_value=[])

    await woocommerce_commands_bot.get_product_orders.callback(woocommerce_commands_bot, mock_interaction, "Nonexistent Product")

    mock_interaction.followup.send.assert_called_once_with("Product not found.", ephemeral=True)

@pytest.mark.asyncio
async def test_get_product_orders_product_not_found(woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check):
    mock_role_check.side_effect = lambda _: True
    mock_products = [{"name": "Other Product", "id": 2}]
    mock_call_api.return_value = mock_products

    await woocommerce_commands_bot.get_product_orders.callback(woocommerce_commands_bot, mock_interaction, "Nonexistent Product")

    mock_interaction.followup.send.assert_called_once_with("Product not found.", ephemeral=True)

@pytest.mark.asyncio
async def test_get_product_orders_no_orders(woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check):
    mock_role_check.side_effect = lambda _: True
    mock_products = [{"name": "Existing Product", "id": 1}]
    mock_orders = []
    mock_call_api.side_effect = [mock_products, mock_orders]

    await woocommerce_commands_bot.get_product_orders.callback(woocommerce_commands_bot, mock_interaction, "Existing Product")

    mock_interaction.followup.send.assert_called_once_with("No orders found for this product.", ephemeral=True)

@pytest.mark.asyncio
async def test_get_product_orders_no_permission(woocommerce_commands_bot, mock_interaction, mock_role_check):
    mock_role_check.side_effect = lambda _: False

    await woocommerce_commands_bot.get_product_orders.callback(woocommerce_commands_bot, mock_interaction, "Any Product")

    mock_interaction.response.send_message.assert_called_once_with(
        "You do not have the necessary permissions.", ephemeral=True)