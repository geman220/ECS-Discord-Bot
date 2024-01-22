# api_helpers.py

import aiohttp
from datetime import datetime, timedelta
from config import BOT_CONFIG

wc_key = BOT_CONFIG['wc_key']
wc_secret = BOT_CONFIG['wc_secret']
openweather_api = BOT_CONFIG['openweather_api']
serpapi_api = BOT_CONFIG['serpapi_api']

async def send_async_http_request(interaction, url, method='GET', headers=None, auth=None, data=None):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(method, url, headers=headers, auth=auth, data=data) as response:
                if response.status == 200:
                    return await response.json()
        except aiohttp.ClientError as e:
            # You might want to send a message to the user or log the error
            print(f"Client error occurred: {e}")  # Logging the error
            return None
        except Exception as e:
            # You might want to send a message to the user or log the error
            print(f"An unexpected error occurred: {e}")  # Logging the error
            return None
        
async def call_woocommerce_api(interaction, url):
    auth = aiohttp.BasicAuth(wc_key, wc_secret)
    return await send_async_http_request(interaction, url, auth=auth)

async def fetch_espn_data(interaction, endpoint):
    base_url = "https://site.api.espn.com/apis/site/v2/"
    full_url = base_url + endpoint
    return await send_async_http_request(interaction, full_url)

async def fetch_weather_data(latitude, longitude, date_time_utc):
    match_date = datetime.fromisoformat(date_time_utc).date()

    if match_date > datetime.utcnow().date() + timedelta(days=5):
        return None, "No weather information available for dates more than 5 days ahead."

    url = f"http://api.openweathermap.org/data/2.5/forecast?lat={latitude}&lon={longitude}&appid={openweather_api}&units=metric"
    data = await send_async_http_request(url)
    if data:
        for forecast in data.get('list', []):
            forecast_date = datetime.fromtimestamp(forecast['dt']).date()
            if forecast_date == match_date:
                return forecast, None
        return None, "Weather forecast not available for the selected date."
    else:
        return None, "Unable to fetch weather information."

async def fetch_flight_data(departure_airport, arrival_airport, outbound_date, return_date):
    base_url = "https://serpapi.com/search"
    params = {
        "engine": "google_flights",
        "departure_id": departure_airport,
        "arrival_id": arrival_airport,
        "gl": "us",
        "hl": "en",
        "currency": "USD",
        "type": "1",
        "outbound_date": outbound_date.strftime("%Y-%m-%d"),
        "return_date": return_date.strftime("%Y-%m-%d"),
        "api_key": serpapi_api
    }

    try:
        data = await send_async_http_request(base_url, params=params)
        return data, None
    except Exception as e:
        return None, str(e)