# test_woocommerce_commands.py

import pytest
import csv
from woocommerce_commands import WooCommerceCommands
from unittest.mock import AsyncMock, MagicMock
from database import insert_order_extract, get_order_extract
import discord

@pytest.fixture
def woocommerce_commands_bot():
    return WooCommerceCommands(bot=MagicMock())


@pytest.fixture
def mock_database_functions(monkeypatch):
    mock_insert_order_extract = MagicMock()
    monkeypatch.setattr("woocommerce_commands.insert_order_extract", mock_insert_order_extract)

    mock_get_order_extract = MagicMock(return_value=[
        {
            "order_id": "12345",
            "product_name": "Away vs LAFC | 2024-02-24",
            "first_name": "John",
            "last_name": "Doe",
            "email_address": "johndoe@example.com",
            "order_date": "2024-01-21T23:03:50",
            "item_qty": 2,
            "item_price": "50.00",
            "order_status": "completed",
            "order_note": "",
            "product_variation": "0",
            "billing_address": "123 Main St, Seattle, WA, 98101, US",
            "alias": "ecstix-12345@weareecs.com",
            "alias_description": "Away vs LAFC | 2024-02-24 entry for John Doe",
            "alias_1_recipient": "johndoe@example.com",
            "alias_2_recipient": "travel@weareecs.com",
            "alias_type": "MEMBER"
        },
        {
            "order_id": "67890",
            "product_name": "Away vs LAFC | 2024-02-24",
            "first_name": "Alice",
            "last_name": "Smith",
            "email_address": "alicesmith@example.com",
            "order_date": "2024-01-22T10:15:30",
            "item_qty": 1,
            "item_price": "55.00",
            "order_status": "processing",
            "order_note": "Please deliver ASAP",
            "product_variation": "1",
            "billing_address": "456 Another St, Seattle, WA, 98102, US",
            "alias": "ecstix-67890@weareecs.com",
            "alias_description": "Away vs LAFC | 2024-02-24 entry for Alice Smith",
            "alias_1_recipient": "alicesmith@example.com",
            "alias_2_recipient": "travel@weareecs.com",
            "alias_type": "MEMBER"
        }
    ])
    monkeypatch.setattr("woocommerce_commands.get_order_extract", mock_get_order_extract)

    return {
        "insert_order_extract": mock_insert_order_extract,
        "get_order_extract": mock_get_order_extract
    }


@pytest.fixture
def mock_interaction():
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.response.send_message = AsyncMock()
    return interaction


@pytest.fixture
def mock_call_api(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr("woocommerce_commands.call_woocommerce_api", async_mock)
    return async_mock


@pytest.fixture
def mock_role_check(monkeypatch):
    async_mock = AsyncMock()
    monkeypatch.setattr("woocommerce_commands.has_required_wg_role", async_mock)
    return async_mock


@pytest.mark.asyncio
async def test_list_tickets_no_tickets_available(
    woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check
):
    mock_role_check.side_effect = lambda _: True
    mock_home_tickets = []
    mock_away_tickets = []
    mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

    await woocommerce_commands_bot.list_tickets.callback(
        woocommerce_commands_bot, mock_interaction
    )

    expected_message = "🏠 **Home Tickets:**\nNo home tickets found.\n\n🚗 **Away Tickets:**\nNo away tickets found."
    mock_interaction.followup.send.assert_called_once_with(
        expected_message, ephemeral=True
    )


@pytest.mark.asyncio
async def test_list_tickets_no_permission(
    woocommerce_commands_bot, mock_interaction, mock_role_check
):
    mock_role_check.side_effect = lambda _: False

    await woocommerce_commands_bot.list_tickets.callback(
        woocommerce_commands_bot, mock_interaction
    )
    mock_interaction.response.send_message.assert_called_once_with(
        "You do not have the necessary permissions.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_get_product_orders_no_products_found(
    woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check
):
    mock_role_check.side_effect = lambda _: True
    mock_call_api.return_value = AsyncMock(return_value=[])

    await woocommerce_commands_bot.get_product_orders.callback(
        woocommerce_commands_bot, mock_interaction, "Nonexistent Product"
    )

    mock_interaction.followup.send.assert_called_once_with(
        "Product not found.", ephemeral=True
    )