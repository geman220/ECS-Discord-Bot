# test_admin_commands.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from admin_commands import AdminCommands


@pytest.fixture
def admin_commands_bot():
    bot = MagicMock()
    return AdminCommands(bot)


@pytest.fixture
def mock_interaction():
    interaction = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_create_schedule_without_admin_role(
    admin_commands_bot, mock_interaction, mocker
):
    mocker.patch(
        "admin_commands.has_admin_role", new_callable=AsyncMock, return_value=False
    )
    await admin_commands_bot.create_schedule_command.callback(
        admin_commands_bot, mock_interaction
    )
    mock_interaction.response.send_message.assert_awaited_with(
        "You do not have the necessary permissions.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_new_season_without_admin_role(
    admin_commands_bot, mock_interaction, mocker
):
    mocker.patch(
        "admin_commands.has_admin_role", new_callable=AsyncMock, return_value=False
    )
    await admin_commands_bot.new_season.callback(admin_commands_bot, mock_interaction)
    mock_interaction.response.send_message.assert_awaited_with(
        "You do not have the necessary permissions.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_new_season_success(admin_commands_bot, mock_interaction, mocker):
    mocker.patch(
        "admin_commands.has_admin_role", new_callable=AsyncMock, return_value=True
    )
    await admin_commands_bot.new_season.callback(admin_commands_bot, mock_interaction)
    mock_interaction.response.send_modal.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_order_without_admin_role(
    admin_commands_bot, mock_interaction, mocker
):
    mocker.patch(
        "admin_commands.has_admin_role", new_callable=AsyncMock, return_value=False
    )
    await admin_commands_bot.check_order.callback(admin_commands_bot, mock_interaction)
    mock_interaction.response.send_message.assert_awaited_with(
        "You do not have the necessary permissions.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_check_order_success(admin_commands_bot, mock_interaction, mocker):
    mocker.patch(
        "admin_commands.has_admin_role", new_callable=AsyncMock, return_value=True
    )
    await admin_commands_bot.check_order.callback(admin_commands_bot, mock_interaction)
    mock_interaction.response.send_modal.assert_awaited_once()