# tests/conftest.py

import pytest
import json
import os
import warnings
from unittest.mock import AsyncMock, patch, MagicMock

def pytest_configure(config):
    # Suppress urllib3 NotOpenSSLWarning which occurs on macOS with Python 3.9
    config.addinivalue_line("filterwarnings", "ignore::urllib3.exceptions.NotOpenSSLWarning")
    # Also suppress the specific post_live_updates warning if it persists
    config.addinivalue_line("filterwarnings", "ignore:coroutine 'post_live_updates' was never awaited:RuntimeWarning")

# Set dummy environment variables before any other imports
os.environ["SERVER_ID"] = "123456789"
os.environ["BOT_TOKEN"] = "dummy_token"
os.environ["ADMIN_ROLE"] = "Admin"
os.environ["DEV_ID"] = "987654321"
os.environ["TEAM_ID"] = "184"
os.environ["URL"] = "https://example.com/wp-json/wc/v3/orders/"
os.environ["MATCH_CHANNEL_ID"] = "111222333"
os.environ["LEAGUE_ANNOUNCEMENTS_CHANNEL_ID"] = "444555666"
os.environ["WC_KEY"] = "dummy_wc_key"
os.environ["WC_SECRET"] = "dummy_wc_secret"

@pytest.fixture
def espn_record_fixture():
    with open("tests/fixtures/espn_record.json", "r") as f:
        return json.load(f)

@pytest.fixture
def wc_products_fixture():
    with open("tests/fixtures/wc_products.json", "r") as f:
        return json.load(f)

@pytest.fixture
def mock_aiohttp_session(monkeypatch):
    """
    Fixture to mock aiohttp.ClientSession for async HTTP requests
    """
    mock_session = MagicMock()
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.__aenter__.return_value = mock_response
    
    # raise_for_status is synchronous in aiohttp, so it should be a regular Mock/MagicMock
    # to avoid "coroutine never awaited" warnings when using AsyncMock.
    mock_response.raise_for_status = MagicMock()
    
    # Set default JSON return value
    mock_response.json.return_value = {"status": "ok"}
    
    mock_session.request.return_value = mock_response
    mock_session.get.return_value = mock_response
    mock_session.__aenter__.return_value = mock_session
    
    # Helper to patch specific modules
    def _patch_module(module_path):
        monkeypatch.setattr(f"{module_path}.aiohttp.ClientSession", MagicMock(return_value=mock_session))
    
    # Default patch for api_helpers
    _patch_module("api_helpers")
    
    # If rsvp_utils is imported, patch it too
    try:
        import api.utils.rsvp_utils
        _patch_module("api.utils.rsvp_utils")
    except ImportError:
        pass
    
    return mock_session, mock_response
