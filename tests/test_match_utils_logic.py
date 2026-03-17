# tests/test_match_utils_logic.py

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from match_utils import (
    extract_date_from_title,
    get_away_match,
    get_team_record
)

@pytest.fixture(autouse=True)
def mock_match_utils_config(monkeypatch):
    monkeypatch.setattr("match_utils.wc_url", "https://example.com/wp-json/wc/v3/orders/")
    monkeypatch.setattr("match_utils.team_name", "Seattle Sounders FC")

def test_extract_date_from_title():
    # Valid date
    assert extract_date_from_title("Match 2024-05-12") == datetime(2024, 5, 12)
    # Different position
    assert extract_date_from_title("2024-12-31 Match Name") == datetime(2024, 12, 31)
    # Invalid date format
    assert extract_date_from_title("Match 12-05-2024") is None
    # No date
    assert extract_date_from_title("Just a match") is None

@pytest.mark.asyncio
async def test_get_away_match_success(wc_products_fixture, monkeypatch):
    # Update fixture to have a future date so it's not filtered out
    future_products = [
        {
            "name": "Away Match vs Portland Timbers - 2029-05-12",
            "permalink": "https://emeraldcitysupporters.com/product/away-portland-2029/"
        }
    ]
    mock_api = AsyncMock(return_value=future_products)
    monkeypatch.setattr("match_utils.call_woocommerce_api", mock_api)
    
    # Test getting match for Portland
    result = await get_away_match(opponent="Portland")
    assert result is not None
    title, link = result
    
    assert "Portland" in title
    assert link == "https://emeraldcitysupporters.com/product/away-portland-2029/"

@pytest.mark.asyncio
async def test_get_away_match_not_found(monkeypatch):
    mock_api = AsyncMock(return_value=[])
    monkeypatch.setattr("match_utils.call_woocommerce_api", mock_api)
    
    result = await get_away_match(opponent="Galaxy")
    assert result is None

@pytest.mark.asyncio
async def test_get_team_record_success(espn_record_fixture, monkeypatch):
    mock_api = AsyncMock(return_value=espn_record_fixture)
    monkeypatch.setattr("match_utils.fetch_espn_data", mock_api)
    
    record, logo = await get_team_record("184")
    
    assert record["wins"] == 12
    assert record["losses"] == 8
    assert logo == "https://a.espncdn.com/i/teamlogos/soccer/500/184.png"

def test_extract_links():
    from match_utils import extract_links
    event = {
        "links": [
            {"rel": ["summary", "desktop"], "href": "https://espn.com/summary"},
            {"rel": ["stats", "desktop"], "href": "https://espn.com/stats"},
            {"rel": ["commentary", "desktop"], "href": "https://espn.com/commentary"}
        ]
    }
    s, st, c = extract_links(event)
    assert s == "https://espn.com/summary"
    assert st == "https://espn.com/stats"
    assert c == "https://espn.com/commentary"

def test_generate_thread_name():
    from match_utils import generate_thread_name
    match_info = {
        "name": "Sounders vs Timbers",
        "date_time": datetime(2024, 5, 12, 19, 0)
    }
    # Expected: "Match Thread: Sounders vs Timbers - 05/12/2024 07:00 PM PST"
    name = generate_thread_name(match_info)
    assert "Match Thread: Sounders vs Timbers" in name
    assert "05/12/2024 07:00 PM PST" in name

def test_format_current_score():
    from match_utils import format_current_score
    match_data = {
        "competitions": [{
            "competitors": [
                {"team": {"displayName": "Sounders"}, "score": "2"},
                {"team": {"displayName": "Timbers"}, "score": "1"}
            ]
        }]
    }
    result = format_current_score(match_data)
    assert "Sounders 2 - 1 Timbers" in result

def test_get_competition_for_match(monkeypatch):
    from match_utils import get_competition_for_match
    
    # Mock database connection and cursor
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = ["usa.1"]
    
    monkeypatch.setattr("match_utils.get_db_connection", MagicMock(return_value=mock_conn))
    
    assert get_competition_for_match("123") == "usa.1"

@pytest.mark.asyncio
async def test_get_next_match_success(monkeypatch):
    from match_utils import get_next_match
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    # Mock data for one match
    mock_cursor.fetchone.return_value = (
        "123", "Portland", "2024-05-12T19:00:00", 1, "link1", "link2", "link3", "Lumen", 0
    )
    
    monkeypatch.setattr("match_utils.get_db_connection", MagicMock(return_value=mock_conn))
    
    match = await get_next_match("184")
    assert match["match_id"] == "123"
    assert match["opponent"] == "Portland"
    assert match["venue"] == "Lumen"

@pytest.mark.asyncio
async def test_prepare_match_environment_home(monkeypatch):
    from match_utils import prepare_match_environment
    
    match_info = {
        "is_home_game": True,
        "date_time": datetime(2024, 5, 12, 19, 0)
    }
    
    # Mock common functions
    monkeypatch.setattr("match_utils.get_weather_forecast", AsyncMock(return_value="Sunny"))
    monkeypatch.setattr("match_utils.create_event_if_necessary", AsyncMock(return_value="Event Created"))
    
    evt, weather = await prepare_match_environment(MagicMock(), match_info)
    assert evt == "Event Created"
    assert weather == "Sunny"

def test_update_live_updates_status(monkeypatch):
    from match_utils import update_live_updates_status
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    
    monkeypatch.setattr("match_utils.get_db_connection", MagicMock(return_value=mock_conn))
    
    update_live_updates_status("123", 1)
    mock_cursor.execute.assert_called_once()
    assert "UPDATE match_schedule" in mock_cursor.execute.call_args[0][0]

@pytest.mark.asyncio
async def test_schedule_poll_closing(monkeypatch):
    from match_utils import schedule_poll_closing
    
    mock_thread = AsyncMock()
    mock_cog = MagicMock()
    match_start = datetime(2024, 5, 12, 19, 0)
    
    # Mock dependencies
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    monkeypatch.setattr("match_utils.get_predictions", MagicMock(return_value=[("2-1", 5)]))
    monkeypatch.setattr("asyncio.create_task", MagicMock())
    
    await schedule_poll_closing(match_start, "123", mock_thread, mock_cog)
    
    assert mock_thread.send.call_count == 2
    mock_thread.send.assert_any_call("Predictions closed.")

def test_format_match_update():
    from match_utils import format_match_update
    match_data = {
        "competitions": [{
            "competitors": [
                {"id": "184", "team": {"displayName": "Sounders"}},
                {"id": "185", "team": {"displayName": "Timbers"}}
            ],
            "details": [
                {
                    "type": {"text": "Goal"},
                    "team": {"id": "184"},
                    "clock": {"displayValue": "45'"},
                    "athletesInvolved": [{"displayName": "Jordan Morris"}]
                },
                {
                    "type": {"text": "Yellow Card"},
                    "team": {"id": "185"},
                    "clock": {"displayValue": "60'"},
                    "athletesInvolved": [{"displayName": "Diego Chara"}]
                }
            ]
        }]
    }
    reported_events = set()
    embed = format_match_update(match_data, reported_events, "184")
    
    assert embed is not None
    assert len(embed.fields) == 2
    assert "SOUNDERS FC GOAL!" in embed.fields[0].value
    assert "Jordan Morris" in embed.fields[0].value
    assert "Yellow Card" in embed.fields[1].name
    assert "Diego Chara" in embed.fields[1].value
    
    # Test deduplication
    embed2 = format_match_update(match_data, reported_events, "184")
    assert embed2 is None

def test_extract_match_details():
    from match_utils import extract_match_details
    event = {
        "id": "123",
        "name": "Sounders vs Timbers",
        "date": "2024-05-12T19:00:00Z",
        "competitions": [{
            "venue": {"fullName": "Lumen Field"},
            "competitors": [
                {"homeAway": "home", "team": {"displayName": "Sounders", "id": "184"}},
                {"homeAway": "away", "team": {"displayName": "Timbers", "id": "185"}}
            ]
        }]
    }
    details = extract_match_details(event)
    assert details["match_id"] == "123"
    assert details["opponent"] == "Timbers"
    assert details["is_home_game"] is True
    assert details["venue"] == "Lumen Field"
