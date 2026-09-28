# test_woocommerce_commands.py

import asyncio
import csv
import io
import pytest
from woocommerce_commands import (
    WooCommerceCommands,
    find_member_id_from_customer_product,
    generate_csv_from_orders,
    get_product_by_name,
    get_product_variations,
    get_customers_by_ids,
    init_subgroups,
    update_customer_profile_field,
)
from unittest.mock import AsyncMock, MagicMock
from database import insert_order_extract, get_order_extract
from membership_testing3 import _parse_args, process_order, run_reconciliation, update_ecs_subgroup
from help_commands import CustomHelpCommand
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
    mock_role_check.side_effect = lambda *_: True
    mock_home_tickets = []
    mock_away_tickets = []
    mock_call_api.side_effect = [mock_home_tickets, mock_away_tickets]

    await woocommerce_commands_bot.list_tickets.callback(
        woocommerce_commands_bot, mock_interaction
    )

    expected_message = "🏠 **Home Tickets:** (sold, remaining)\nNo tickets found.\n\n🚗 **Away Tickets:** (sold, remaining)\nNo tickets found.\n"
    mock_interaction.followup.send.assert_called_once_with(
        expected_message, ephemeral=True
    )


@pytest.mark.asyncio
async def test_list_tickets_no_permission(
    woocommerce_commands_bot, mock_interaction, mock_role_check
):
    mock_role_check.side_effect = lambda *_: False

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
    mock_role_check.side_effect = lambda *_: True
    mock_call_api.return_value = AsyncMock(return_value=[])

    await woocommerce_commands_bot.get_product_orders.callback(
        woocommerce_commands_bot, mock_interaction, "Nonexistent Product"
    )

    mock_interaction.followup.send.assert_called_once_with(
        "Product not found.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_proliferate_completes_after_processing_a_short_page(
    woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check
):
    mock_role_check.return_value = True
    mock_call_api.return_value = [{"id": 123, "line_items": []}]

    await woocommerce_commands_bot.proliferate.callback(
        woocommerce_commands_bot, mock_interaction, 7
    )

    mock_interaction.followup.send.assert_called_once_with(
        "Subgroup proliferation completed.", ephemeral=True
    )


def test_init_subgroups_returns_normalized_subgroup_list(monkeypatch):
    responses = [
        [{"id": 11, "name": "Subgroup"}],
        [{"id": 22, "name": "West Sound"}, {"id": 23, "name": "Armed Forces"}],
    ]

    async def fake_call_woocommerce_api(url):
        return responses.pop(0)

    monkeypatch.setattr("woocommerce_commands.call_woocommerce_api", fake_call_woocommerce_api)

    result = asyncio.run(init_subgroups())

    assert result == [
        {"name": "West Sound", "name_normalized": "west sound", "id": 22},
        {"name": "Armed Forces", "name_normalized": "armed forces", "id": 23},
    ]


def test_get_customers_by_ids_uses_include_params_and_normalizes_ids(monkeypatch):
    calls = []

    async def fake_call_woocommerce_api(url, params=None):
        calls.append((url, params))
        return [{"id": 42, "first_name": "Jane"}]

    monkeypatch.setattr("woocommerce_commands.call_woocommerce_api", fake_call_woocommerce_api)

    result = asyncio.run(get_customers_by_ids("https://example.test/customers", {42}))

    assert calls == [(
        "https://example.test/customers",
        {"include": "42", "per_page": 1},
    )]
    assert result == {"42": {"id": 42, "first_name": "Jane"}}


def test_membership_reconciliation_defaults_to_dry_run():
    assert _parse_args([]).dry_run is True
    assert _parse_args(["--apply"]).dry_run is False
    assert run_reconciliation.__kwdefaults__["dry_run"] is True


def test_reconciliation_recognizes_membership_plan_name_variant(monkeypatch):
    async def existing_memberships(_customer_id):
        return [{"id": 99, "plan_name": "ECS Membership 2026", "profile_fields": []}]

    monkeypatch.setattr(
        "membership_testing3.get_membership_records_for_customer",
        existing_memberships,
    )
    stats = {"orders_with_membership": 0}
    order = {
        "id": 1,
        "status": "processing",
        "customer_id": 7,
        "line_items": [{"name": "ECS Membership 2026"}],
    }

    asyncio.run(process_order(
        order,
        [],
        year_filter=None,
        dry_run=True,
        stats=stats,
    ))

    assert stats == {"orders_with_membership": 1}


def test_find_member_id_from_customer_product_returns_matching_membership(monkeypatch):
    async def fake_call_woocommerce_api(url):
        return [{"id": 99, "plan_name": "ECS Membership"}]

    monkeypatch.setattr("woocommerce_commands.call_woocommerce_api", fake_call_woocommerce_api)

    result = asyncio.run(find_member_id_from_customer_product(42, "ECS Membership"))

    assert result == 99


def test_update_ecs_subgroup_returns_false_when_verification_mismatches(monkeypatch):
    async def fake_call_woocommerce_api(url, method=None, data=None):
        return {"id": 77, "profile_fields": [{"slug": "ecs-subgroup", "value": "Other"}]}

    monkeypatch.setattr("membership_testing3.call_woocommerce_api", fake_call_woocommerce_api)

    result = asyncio.run(update_ecs_subgroup(77, "West Sound"))

    assert result is False


def test_update_customer_profile_field_returns_true_when_api_succeeds(monkeypatch):
    captured = {}

    async def fake_call_woocommerce_api(url, method=None, data=None):
        captured["url"] = url
        captured["method"] = method
        captured["data"] = data
        return {"id": 77}

    monkeypatch.setattr("woocommerce_commands.call_woocommerce_api", fake_call_woocommerce_api)

    result = asyncio.run(update_customer_profile_field(77, "first_name", "Jane"))

    assert result is True
    assert captured["url"].endswith("/memberships/members/77")
    assert captured["method"] == "PUT"
    assert "first_name" in captured["data"]


def test_get_product_by_name_returns_exact_match(monkeypatch):
    async def fake_call_woocommerce_api(url):
        return [{"id": 5, "name": "ECS Membership 2024"}, {"id": 6, "name": "Other Product"}]

    monkeypatch.setattr("woocommerce_commands.call_woocommerce_api", fake_call_woocommerce_api)

    result = asyncio.run(get_product_by_name("ECS Membership 2024"))

    assert result["id"] == 5


def test_get_product_variations_returns_variations(monkeypatch):
    async def fake_call_woocommerce_api(url):
        return [{"id": 100}, {"id": 101}]

    monkeypatch.setattr("woocommerce_commands.call_woocommerce_api", fake_call_woocommerce_api)

    result = asyncio.run(get_product_variations(42))

    assert result == [{"id": 100}, {"id": 101}]


def test_generate_csv_from_orders_writes_expected_aliases():
    orders = [
        {
            "id": 111,
            "status": "completed",
            "date_paid": "2024-01-01",
            "customer_note": "",
            "billing": {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "jane@example.com",
                "address_1": "123 Main St",
                "city": "Seattle",
                "state": "WA",
            },
            "line_items": [
                {
                    "product_id": 7,
                    "name": "ECS Membership 2024",
                    "price": "10.00",
                    "quantity": 1,
                    "variation_name": "",
                    "meta_data": [{"key": "_reduced_stock", "value": "1"}],
                }
            ],
        }
    ]

    csv_output = asyncio.run(generate_csv_from_orders(orders, [7]))
    rows = list(csv.reader(io.StringIO(csv_output.getvalue())))

    assert rows[1][0] == "ECS Membership 2024"
    assert rows[1][12] == "ecstix-111@weareecs.com"
    assert rows[1][13] == "ECS Membership 2024 entry for Jane Doe"


@pytest.mark.asyncio
async def test_proliferate_uses_matched_membership_product_name(
    woocommerce_commands_bot, mock_interaction, mock_call_api, mock_role_check, monkeypatch
):
    mock_role_check.return_value = True
    mock_call_api.side_effect = [[{
        "id": 123,
        "customer_id": 77,
        "line_items": [{
            "name": "ECS Membership 2026",
            "meta_data": [{"key": "Subgroup Designation", "value": "West Sound"}],
        }],
    }]]
    lookup = AsyncMock(return_value=99)
    monkeypatch.setattr("woocommerce_commands.find_member_id_from_customer_product", lookup)
    monkeypatch.setattr("woocommerce_commands.update_customer_profile_field", AsyncMock(return_value=True))

    await woocommerce_commands_bot.proliferate.callback(
        woocommerce_commands_bot, mock_interaction, 7
    )

    lookup.assert_awaited_once_with(77, "ECS Membership 2026")


@pytest.mark.asyncio
async def test_process_order_skips_non_eligible_status(monkeypatch):
    create_membership = AsyncMock()
    monkeypatch.setattr("membership_testing3.create_membership_record", create_membership)
    monkeypatch.setattr("membership_testing3.get_membership_records_for_customer", AsyncMock(return_value=[]))

    stats = {
        "orders_examined": 0,
        "orders_with_membership": 0,
        "memberships_create_attempted": 0,
        "memberships_create_succeeded": 0,
        "memberships_create_failed": 0,
        "memberships_skipped_guest": 0,
        "subgroup_already_set": 0,
        "subgroup_updates_attempted": 0,
        "subgroup_updates_succeeded": 0,
        "subgroup_updates_failed": 0,
    }
    order = {
        "id": 1,
        "status": "cancelled",
        "customer_id": 7,
        "line_items": [{"name": "ECS Membership 2026"}],
    }

    await process_order(order, [], year_filter=2026, dry_run=False, stats=stats)

    create_membership.assert_not_called()
    assert stats["orders_with_membership"] == 0


@pytest.mark.asyncio
async def test_process_order_passes_year_filter_to_membership_lookup(monkeypatch):
    captured = {}

    async def fake_find_membership_item_in_order(order, membership_year=None):
        captured["membership_year"] = membership_year
        return "ECS Membership 2025"

    monkeypatch.setattr("membership_testing3.find_membership_item_in_order", fake_find_membership_item_in_order)
    monkeypatch.setattr(
        "membership_testing3.get_membership_records_for_customer",
        AsyncMock(return_value=[{"id": 99, "plan_name": "ECS Membership 2025", "profile_fields": []}]),
    )

    stats = {
        "orders_examined": 0,
        "orders_with_membership": 0,
        "memberships_create_attempted": 0,
        "memberships_create_succeeded": 0,
        "memberships_create_failed": 0,
        "memberships_skipped_guest": 0,
        "subgroup_already_set": 0,
        "subgroup_updates_attempted": 0,
        "subgroup_updates_succeeded": 0,
        "subgroup_updates_failed": 0,
    }
    order = {
        "id": 1,
        "status": "processing",
        "customer_id": 7,
        "line_items": [{"name": "ECS Membership 2025"}],
    }

    await process_order(order, [], year_filter=2025, dry_run=True, stats=stats)

    assert captured["membership_year"] == 2025
    assert stats["orders_with_membership"] == 1


@pytest.mark.asyncio
async def test_custom_help_requires_leadership_for_subgrouplist(monkeypatch):
    help_command = CustomHelpCommand()
    help_command.context = MagicMock()
    leadership_check = AsyncMock(return_value=True)
    monkeypatch.setattr("help_commands.has_required_wg_role", leadership_check)

    command = MagicMock(name="subgrouplist")
    command.name = "subgrouplist"

    result = await help_command.can_run(command)

    assert result is True
    leadership_check.assert_awaited_once_with(help_command.context, ["ECS Leadership"])