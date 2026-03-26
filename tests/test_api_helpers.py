# tests/test_api_helpers.py

import pytest
import aiohttp
from unittest.mock import AsyncMock, patch, MagicMock
from urllib.parse import urlparse
from api_helpers import (
    send_async_http_request,
    call_woocommerce_api,
    fetch_espn_data,
    fetch_openweather_data,
    fetch_serpapi_flight_data,
    check_new_orders
)

# Mock BOT_CONFIG and dependent variables at the module level in api_helpers
@pytest.fixture(autouse=True)
def mock_api_helpers_config(monkeypatch):
    monkeypatch.setattr("api_helpers.wc_key", "dummy_key")
    monkeypatch.setattr("api_helpers.wc_secret", "dummy_secret")
    monkeypatch.setattr("api_helpers.wc_url", "https://example.com/wp-json/wc/v3/orders/")

@pytest.mark.asyncio
async def test_send_async_http_request_success(mock_aiohttp_session):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.status = 200
    mock_response.json.return_value = {"key": "value"}
    
    result = await send_async_http_request("https://api.example.com/test")
    
    assert result == {"key": "value"}
    mock_session.request.assert_called_once_with(
        "GET", "https://api.example.com/test", headers=None, auth=None, data=None, params=None
    )

@pytest.mark.asyncio
async def test_send_async_http_request_failure(mock_aiohttp_session):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.status = 404
    
    result = await send_async_http_request("https://api.example.com/notfound")
    
    assert result is None

@pytest.mark.asyncio
async def test_send_async_http_request_exception(monkeypatch):
    # Test client error (connection issue)
    mock_session = MagicMock()
    mock_session.request.side_effect = aiohttp.ClientError("Connection failed")
    mock_session.__aenter__.return_value = mock_session
    monkeypatch.setattr("aiohttp.ClientSession", MagicMock(return_value=mock_session))
    
    result = await send_async_http_request("https://api.example.com/error")
    assert result is None

@pytest.mark.asyncio
async def test_call_woocommerce_api(mock_aiohttp_session):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.json.return_value = [{"id": 1}]
    
    result = await call_woocommerce_api("https://store.com/products")
    
    assert result == [{"id": 1}]
    # Verify auth was used
    args, kwargs = mock_session.request.call_args
    assert isinstance(kwargs["auth"], aiohttp.BasicAuth)

@pytest.mark.asyncio
async def test_fetch_espn_data(mock_aiohttp_session):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.json.return_value = {"team": "Sounders"}
    
    result = await fetch_espn_data("sports/soccer/usa.1/teams/184")
    
    assert result == {"team": "Sounders"}
    assert mock_session.request.call_args[0][1].startswith("https://site.api.espn.com")

@pytest.mark.asyncio
async def test_check_new_orders_detected(mock_aiohttp_session, monkeypatch):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.json.return_value = [{"id": 12345}]
    
    # Mock database call
    monkeypatch.setattr("api_helpers.get_latest_order_id", MagicMock(return_value="12300"))
    
    result = await check_new_orders("765197886")
    
    assert result is True

@pytest.mark.asyncio
async def test_check_new_orders_not_detected(mock_aiohttp_session, monkeypatch):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.json.return_value = [{"id": 12345}]
    
    # Mock database call
    monkeypatch.setattr("api_helpers.get_latest_order_id", MagicMock(return_value="12345"))
    
    result = await check_new_orders("765197886")
    
    assert result is False

@pytest.mark.asyncio
async def test_fetch_openweather_data(mock_aiohttp_session):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.json.return_value = {"list": []}
    
    # Test date within 5 days
    from datetime import datetime, timedelta
    test_date = (datetime.utcnow() + timedelta(days=2)).isoformat()
    result = await fetch_openweather_data(47.6, -122.3, test_date)
    assert result == {"list": []}
    
    # Test date more than 5 days ahead
    far_date = (datetime.utcnow() + timedelta(days=10)).isoformat()
    result = await fetch_openweather_data(47.6, -122.3, far_date)
    assert "No weather information available" in result

@pytest.mark.asyncio
async def test_fetch_serpapi_flight_data(mock_aiohttp_session):
    mock_session, mock_response = mock_aiohttp_session
    mock_response.json.return_value = {"flights": []}
    
    from datetime import date
    result = await fetch_serpapi_flight_data("SEA", "PDX", date(2024, 5, 12), date(2024, 5, 14))
    assert result == {"flights": []}
    request_url = mock_session.request.call_args[0][1]
    parsed_url = urlparse(request_url)
    assert parsed_url.hostname and parsed_url.hostname.endswith("serpapi.com")
