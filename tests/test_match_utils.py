# test_match_utils.py

import asyncio
import pytest
import pytz
from datetime import datetime, timedelta
import discord
from match_utils import (
    extract_date_from_title,
    get_away_match,
    get_next_match,
    generate_thread_name,
    get_team_record,
    schedule_poll_closing,
    create_match_thread,
    prepare_match_environment,
    create_and_manage_thread,
    schedule_poll_closing,
)
from unittest.mock import AsyncMock, patch, MagicMock


def test_extract_date_from_title_valid():
    title = "Match 2024-03-15"
    expected_date = datetime(2024, 3, 15)
    assert extract_date_from_title(title) == expected_date


def test_extract_date_from_title_no_date():
    title = "Match Information"
    assert extract_date_from_title(title) is None


def test_extract_date_from_title_invalid_format():
    title = "Match 2024/03/15"
    assert extract_date_from_title(title) is None


@pytest.mark.asyncio
@patch("match_utils.call_woocommerce_api")
async def test_get_away_match_no_products(mock_call_woocommerce_api):
    mock_call_woocommerce_api.return_value = []
    result = await get_away_match(None)
    assert result is None


@pytest.mark.asyncio
@patch("match_utils.fetch_espn_data")
async def test_get_team_record_success(mock_fetch_espn_data):
    mock_fetch_espn_data.return_value = {
        "team": {
            "record": {
                "items": [
                    {
                        "stats": [
                            {"name": "wins", "value": "10"},
                            {"name": "losses", "value": "2"},
                        ]
                    }
                ]
            },
            "logos": [{"href": "https://example.com/logo.png"}],
        }
    }
    expected_record = {"wins": "10", "losses": "2"}, "https://example.com/logo.png"
    record, logo = await get_team_record("123")
    assert record == expected_record[0]
    assert logo == expected_record[1]


@pytest.mark.asyncio
@patch("match_utils.fetch_espn_data")
async def test_get_team_record_no_data(mock_fetch_espn_data):
    mock_fetch_espn_data.return_value = {}
    result = await get_team_record("123")
    assert result == ("Record not available", None)