import aiohttp
import asyncio
from flask import current_app
from datetime import datetime
from dateutil import parser
import pytz
import logging

# Get the logger for this module
logger = logging.getLogger(__name__)

def get_team_id():
    team_id = current_app.config['TEAM_ID']
    logger.info(f"Team ID from config: {team_id}")  # Logs the message
    return team_id

def convert_to_pst(utc_datetime):
    if not isinstance(utc_datetime, str):
        utc_datetime = str(utc_datetime)

    utc_datetime = parser.parse(utc_datetime)

    if utc_datetime.tzinfo is None or utc_datetime.tzinfo.utcoffset(utc_datetime) is None:
        utc_datetime = utc_datetime.replace(tzinfo=pytz.utc)

    pst_timezone = pytz.timezone("America/Los_Angeles")
    return utc_datetime.astimezone(pst_timezone)

def extract_links(event):
    summary_link = next(
        (link["href"] for link in event.get("links", []) if "summary" in link["rel"]),
        "Unavailable",
    )
    stats_link = next(
        (link["href"] for link in event.get("links", []) if "stats" in link["rel"]),
        "Unavailable",
    )
    commentary_link = next(
        (link["href"] for link in event.get("links", []) if "commentary" in link["rel"]),
        "Unavailable",
    )
    return summary_link, stats_link, commentary_link

async def send_async_http_request(url, method="GET", headers=None, auth=None, data=None, params=None):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(method, url, headers=headers, auth=auth, data=data, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    print(f"Request failed with status code: {response.status}")
                    return None
        except aiohttp.ClientError as e:
            print(f"Client error occurred: {e}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return None

async def fetch_espn_data(endpoint=None, full_url=None):
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
                    logger.info(f"Successfully fetched data from ESPN API")
                    return data
                else:
                    logger.error(f"Failed to fetch data from ESPN API. Status: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"[API UTILS] Error fetching data from ESPN API: {str(e)}", exc_info=True)
        return None

def async_to_sync(coroutine):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coroutine)

def extract_match_details(event):
    # Fetch the team ID from the app config
    team_id = get_team_id()

    match_id = event.get("id")
    date_time_utc = event.get("date")
    name = event.get("name")
    venue = event.get("competitions", [{}])[0].get("venue", {}).get("fullName")

    # Convert UTC to PST for uniformity in your database
    date_time_pst = convert_to_pst(date_time_utc)
    
    # Extract competitors
    competitors = event.get("competitions", [{}])[0].get("competitors", [])
    team_data = next((comp for comp in competitors if comp["team"]["id"] == team_id), None)

    if team_data:
        # Identify the opponent
        opponent = next(
            (op["team"]["displayName"] for op in competitors if op["team"]["id"] != team_id),
            "Unknown"
        )

        # Determine if it's a home game
        is_home_game = team_data["homeAway"] == "home"

        # Get the team logo
        team_logo = team_data["team"].get("logos", [{}])[0].get("href")
    else:
        opponent = "Unknown"
        is_home_game = False
        team_logo = "Unknown"

    # Check the venue to determine if it's a home game
    if venue in ["Lumen Field", "Starfire Sports Stadium"]:
        is_home_game = True
    else:
        is_home_game = False

    # Extract match links using the existing extract_links function
    summary_link, stats_link, commentary_link = extract_links(event)

    match_details = {
        "match_id": match_id,
        "opponent": opponent,
        "date_time": date_time_pst,
        "venue": venue,
        "name": name,
        "team_logo": team_logo,
        "is_home_game": is_home_game,
        "match_summary_link": summary_link,
        "match_stats_link": stats_link,
        "match_commentary_link": commentary_link,
    }

    return match_details