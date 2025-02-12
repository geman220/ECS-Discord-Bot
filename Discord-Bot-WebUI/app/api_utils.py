from flask import current_app
from datetime import datetime
from dateutil import parser
import pytz
import logging
import aiohttp
import asyncio
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

def get_team_id() -> str:
    """
    Get the team ID from the application config.
    
    Returns:
        str: The configured team ID
    """
    team_id = current_app.config['TEAM_ID']
    logger.info(f"Team ID from config: {team_id}")
    return team_id

def convert_to_pst(utc_datetime: str) -> datetime:
    """
    Convert UTC datetime to PST timezone.
    
    Args:
        utc_datetime: UTC datetime string or datetime object
        
    Returns:
        datetime: PST timezone datetime
    """
    try:
        if not isinstance(utc_datetime, str):
            utc_datetime = str(utc_datetime)

        parsed_datetime = parser.parse(utc_datetime)

        # Ensure timezone is set
        if parsed_datetime.tzinfo is None or parsed_datetime.tzinfo.utcoffset(parsed_datetime) is None:
            parsed_datetime = parsed_datetime.replace(tzinfo=pytz.utc)

        pst_timezone = pytz.timezone("America/Los_Angeles")
        return parsed_datetime.astimezone(pst_timezone)
    except Exception as e:
        logger.error(f"Error converting datetime to PST: {e}")
        raise

def extract_links(event: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Extract various link types from an event.
    
    Args:
        event: Event data dictionary
        
    Returns:
        tuple: (summary_link, stats_link, commentary_link)
    """
    try:
        links = event.get('links', [])
        
        summary_link = next(
            (link["href"] for link in links if "summary" in link["rel"]),
            "Unavailable",
        )
        stats_link = next(
            (link["href"] for link in links if "stats" in link["rel"]),
            "Unavailable",
        )
        commentary_link = next(
            (link["href"] for link in links if "commentary" in link["rel"]),
            "Unavailable",
        )
        
        return summary_link, stats_link, commentary_link
    except Exception as e:
        logger.error(f"Error extracting links: {e}")
        return "Unavailable", "Unavailable", "Unavailable"

async def send_async_http_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict] = None,
    auth: Optional[Tuple] = None,
    data: Optional[Dict] = None,
    params: Optional[Dict] = None,
    timeout: int = 30
) -> Optional[Dict]:
    """
    Send asynchronous HTTP request.
    
    Args:
        url: Request URL
        method: HTTP method
        headers: Request headers
        auth: Authentication tuple
        data: Request data
        params: Query parameters
        timeout: Request timeout in seconds
        
    Returns:
        dict: Response data or None on failure
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, 
                url, 
                headers=headers, 
                auth=auth, 
                data=data, 
                params=params,
                timeout=timeout
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.error(f"Request failed with status code: {response.status}")
                return None
    except aiohttp.ClientError as e:
        logger.error(f"Client error in async request: {e}")
        return None
    except asyncio.TimeoutError:
        logger.error(f"Request timeout for URL: {url}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in async request: {e}")
        return None

async def fetch_espn_data(endpoint: Optional[str] = None, full_url: Optional[str] = None) -> Optional[Dict]:
    """
    Fetch data from ESPN API.
    
    Args:
        endpoint: API endpoint path
        full_url: Complete API URL
        
    Returns:
        dict: API response data or None on failure
    
    Raises:
        ValueError: If neither endpoint nor full_url is provided
    """
    if full_url:
        url = full_url
    elif endpoint:
        url = f"https://site.api.espn.com/apis/site/v2/{endpoint}"
    else:
        raise ValueError("Either 'endpoint' or 'full_url' must be provided")

    logger.info(f"[API UTILS] Fetching data from ESPN API: {url}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info("Successfully fetched data from ESPN API")
                    return data
                logger.error(f"Failed to fetch data from ESPN API. Status: {response.status}")
                return None
    except Exception as e:
        logger.error(f"[API UTILS] Error fetching data from ESPN API: {str(e)}", exc_info=True)
        return None

def async_to_sync(coroutine: Any) -> Any:
    """
    Convert async coroutine to sync function.
    
    Args:
        coroutine: Async coroutine to convert
        
    Returns:
        Any: Result of coroutine execution
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coroutine)

def extract_match_details(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract match details from event data and ensure the datetime is stored as UTC.
    """
    try:
        team_id = get_team_id()
        
        # Extract basic match info
        match_id = event.get("id")
        date_time_str = event.get("date")   # ESPN datetime string (naive but actually PST)
        name = event.get("name")
        venue = event.get("competitions", [{}])[0].get("venue", {}).get("fullName")
        
        # Parse ESPN's datetime string
        parsed_dt = parser.parse(date_time_str)
        
        # If the parsed datetime is naive, assume it is in PST and localize it
        if parsed_dt.tzinfo is None or parsed_dt.tzinfo.utcoffset(parsed_dt) is None:
            pst = pytz.timezone("America/Los_Angeles")
            parsed_dt = pst.localize(parsed_dt)
        
        # Convert to UTC for storage
        parsed_dt = parsed_dt.astimezone(pytz.UTC)
        
        # Extract competitors info
        competitors = event.get("competitions", [{}])[0].get("competitors", [])
        team_data = next((comp for comp in competitors if comp["team"]["id"] == team_id), None)
        
        if team_data:
            # Get opponent and home/away status
            opponent = next(
                (op["team"]["displayName"] for op in competitors if op["team"]["id"] != team_id),
                "Unknown"
            )
            is_home_game = team_data["homeAway"] == "home"
            team_logo = team_data["team"].get("logos", [{}])[0].get("href")
        else:
            opponent = "Unknown"
            # If we cannot find the Sounders data, guess "home" by known venues
            is_home_game = venue in ["Lumen Field", "Starfire Sports Stadium"]
            team_logo = "Unknown"
        
        # Extract match links
        summary_link, stats_link, commentary_link = extract_links(event)
        
        return {
            "match_id": match_id,
            "opponent": opponent,
            "date_time": parsed_dt,  # Stored as UTC
            "venue": venue,
            "name": name,
            "team_logo": team_logo,
            "is_home_game": is_home_game,
            "match_summary_link": summary_link,
            "match_stats_link": stats_link,
            "match_commentary_link": commentary_link,
        }
    except Exception as e:
        logger.error(f"Error extracting match details: {e}")
        raise