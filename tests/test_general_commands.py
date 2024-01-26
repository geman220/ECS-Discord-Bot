# test_general_commands.py

import pytest
from general_commands import GeneralCommands
import api_helpers
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def mock_interaction(monkeypatch):
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


@pytest.fixture
def general_commands_bot():
    return GeneralCommands(bot=MagicMock())


@pytest.mark.asyncio
async def test_away_tickets_closest_upcoming_match(
    monkeypatch, mock_interaction, general_commands_bot
):
    mock_products_response = [
        {
            "name": "Away vs LAFC | 2024-02-24",
            "permalink": "https://example-website.com/product/away-vs-lafc-2024-02-24/",
        },
        {
            "name": "Away vs Philadelphia | 2024-03-09",
            "permalink": "https://example-website.com/product/away-vs-philadelphia-union-2024-03-09/",
        },
    ]
    monkeypatch.setattr(
        api_helpers,
        "call_woocommerce_api",
        AsyncMock(return_value=mock_products_response),
    )

    await general_commands_bot.away_tickets.callback(
        general_commands_bot, mock_interaction
    )
    mock_interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_away_tickets_with_existing_opponent(
    monkeypatch, mock_interaction, general_commands_bot
):
    mock_call_api_return = [
        {"name": "Match vs Miami", "permalink": "miami_match_ticket_link"}
    ]
    monkeypatch.setattr(
        api_helpers,
        "call_woocommerce_api",
        AsyncMock(return_value=mock_call_api_return),
    )

    await general_commands_bot.away_tickets.callback(
        general_commands_bot, mock_interaction, opponent="Miami"
    )
    mock_interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_away_tickets_with_nonexistent_opponent(
    monkeypatch, mock_interaction, general_commands_bot
):
    monkeypatch.setattr(api_helpers, "call_woocommerce_api", AsyncMock(return_value=[]))

    await general_commands_bot.away_tickets.callback(
        general_commands_bot, mock_interaction, opponent="1231241354"
    )
    error_message = "No upcoming away matches found."
    mock_interaction.response.send_message.assert_called_once_with(error_message)