﻿# test_woocommerce_commands.py

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
async def test_list_tickets_success(
    woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check
):
    mock_role_check.side_effect = lambda _: True
    mock_home_tickets = [
        {
            "id": 1,
            "name": "Generic Home Match 1",
            "permalink": "https://example-website.com/home1",
        },
        {
            "id": 2,
            "name": "Generic Home Match 2",
            "permalink": "https://example-website.com/home2",
        },
    ]
    mock_away_tickets = [
        {
            "id": 3,
            "name": "Generic Away Match 1",
            "permalink": "https://example-website.com/away1",
        }
    ]
    mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

    await woocommerce_commands_bot.list_tickets.callback(
        woocommerce_commands_bot, mock_interaction
    )

    expected_message = (
        "🏠 **Home Tickets:**\nGeneric Home Match 1\nGeneric Home Match 2\n\n"
        "🚗 **Away Tickets:**\nGeneric Away Match 1"
    )
    mock_interaction.followup.send.assert_called_once_with(
        expected_message, ephemeral=True
    )


@pytest.mark.asyncio
async def test_list_tickets_no_home_tickets(
    woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check
):
    mock_role_check.side_effect = lambda _: True
    mock_home_tickets = []
    mock_away_tickets = [{"name": "Away Match 1"}, {"name": "Away Match 2"}]
    mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

    await woocommerce_commands_bot.list_tickets.callback(
        woocommerce_commands_bot, mock_interaction
    )

    expected_message = "🏠 **Home Tickets:**\nNo home tickets found.\n\n🚗 **Away Tickets:**\nAway Match 1\nAway Match 2"
    mock_interaction.followup.send.assert_called_once_with(
        expected_message, ephemeral=True
    )


@pytest.mark.asyncio
async def test_list_tickets_no_away_tickets(
    woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check
):
    mock_role_check.side_effect = lambda _: True
    mock_home_tickets = [{"name": "Home Match 1"}, {"name": "Home Match 2"}]
    mock_away_tickets = []
    mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

    await woocommerce_commands_bot.list_tickets.callback(
        woocommerce_commands_bot, mock_interaction
    )

    expected_message = "🏠 **Home Tickets:**\nHome Match 1\nHome Match 2\n\n🚗 **Away Tickets:**\nNo away tickets found."
    mock_interaction.followup.send.assert_called_once_with(
        expected_message, ephemeral=True
    )


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
async def test_get_product_orders_success(
    woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check, mock_database_functions
):
    mock_role_check.side_effect = lambda _: True
    product_title = "Away vs LAFC | 2024-02-24"
    product_id = 996603

    mock_product_response = [{"name": product_title, "id": product_id}]
    order_number = "12345"
    alias_email = f"ecstix-{order_number}@weareecs.com"
    expected_alias_description = f"{product_title} entry for John Doe"
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
                "country": "US",
            },
            "shipping": {
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
                    "variation_id": "0",
                }
            ],
            "date_paid": "2024-01-21T23:03:50",
            "number": order_number,
            "status": "completed",
            "customer_note": "",
            "alias": alias_email,
            "alias_description": expected_alias_description,
            "alias_1_email": alias_email,
            "alias_1_recipient": "Alias1Recipient",
            "alias_1_type": "Member",
            "alias_2_email": alias_email,
            "alias_2_recipient": "travel@weareecs.com",
            "alias_2_type": "Member",
        },
    ]

    mock_call_api.side_effect = [
        mock_product_response,  
        mock_orders_response,   
        []                      
    ]

    await woocommerce_commands_bot.get_product_orders.callback(
        woocommerce_commands_bot, mock_interaction, product_title
    )

    args, kwargs = mock_interaction.followup.send.call_args
    assert "file" in kwargs
    file = kwargs["file"]
    assert isinstance(file, discord.File)

    file.fp.seek(0)
    reader = csv.reader(file.fp)
    rows = list(reader)

    expected_header = [
        "Product Name",
        "Customer First Name",
        "Customer Last Name",
        "Customer Email",
        "Order Date Paid",
        "Order Line Item Quantity",
        "Order Line Item Price",
        "Order Number",
        "Order Status",
        "Order Customer Note",
        "Product Variation Name",
        "Billing Address",
        "Alias",
        "Alias Email",
        "Alias Description",
        "Alias 1 email",
        "Alias 1 recipient",
        "Alias 1 type",
        "Alias 2 email",
        "Alias 2 recipient",
        "Alias 2 type",
    ]
    assert rows[0] == expected_header
    if len(rows) > 1:
        assert rows[1][0] == "Away vs LAFC | 2024-02-24"
        assert rows[1][1] == "John"
        assert rows[1][2] == "Doe"
        assert rows[1][3] == "johndoe@example.com"
        assert rows[1][4] == "2024-01-21T23:03:50"
        assert rows[1][5] == "2"
        assert rows[1][6] == "50.00"
        assert rows[1][7] == "12345"
        assert rows[1][8] == "completed"
        assert rows[1][9] == ""
        assert rows[1][10] == "0"
        assert rows[1][11] == "123 Main St, Seattle, WA, 98101, US"
        assert rows[1][12] == "ecstix-12345@weareecs.com"
        assert rows[1][13] == alias_email
        assert rows[1][14] == expected_alias_description
        assert rows[1][15] == alias_email
        assert rows[1][16] == "johndoe@example.com"
        assert rows[1][17] == "MEMBER"
        assert rows[1][18] == alias_email
        assert rows[1][19] == "travel@weareecs.com"
        assert rows[1][20] == "MEMBER"


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


@pytest.mark.asyncio
async def test_get_product_orders_product_not_found(
    woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check
):
    mock_role_check.side_effect = lambda _: True
    mock_products = [{"name": "Other Product", "id": 2}]
    mock_call_api.return_value = mock_products

    await woocommerce_commands_bot.get_product_orders.callback(
        woocommerce_commands_bot, mock_interaction, "Nonexistent Product"
    )

    mock_interaction.followup.send.assert_called_once_with(
        "Product not found.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_get_product_orders_no_orders(
    woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check
):
    mock_role_check.side_effect = lambda _: True
    mock_products = [{"name": "Existing Product", "id": 1}]
    mock_orders = []
    mock_call_api.side_effect = [mock_products, mock_orders]

    await woocommerce_commands_bot.get_product_orders.callback(
        woocommerce_commands_bot, mock_interaction, "Existing Product"
    )

    mock_interaction.followup.send.assert_called_once_with(
        "No orders found for this product.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_get_product_orders_no_permission(
    woocommerce_commands_bot, mock_interaction, mock_role_check
):
    mock_role_check.side_effect = lambda _: False

    await woocommerce_commands_bot.get_product_orders.callback(
        woocommerce_commands_bot, mock_interaction, "Any Product"
    )

    mock_interaction.response.send_message.assert_called_once_with(
        "You do not have the necessary permissions.", ephemeral=True
    )