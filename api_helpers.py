# api_helpers.py

import aiohttp
import json
from datetime import datetime, timedelta
from config import BOT_CONFIG
from database import get_latest_order_id, update_woo_orders, insert_order_extract, update_latest_order_id

wc_url = BOT_CONFIG["wc_url"]
wc_key = BOT_CONFIG["wc_key"]
wc_secret = BOT_CONFIG["wc_secret"]
openweather_api = BOT_CONFIG["openweather_api"]
serpapi_api = BOT_CONFIG["serpapi_api"]


async def send_async_http_request(
    interaction, url, method="GET", headers=None, auth=None, data=None, params=None
):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(
                method, url, headers=headers, auth=auth, data=data, params=params
            ) as response:
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


async def call_woocommerce_api(interaction, url):
    auth = aiohttp.BasicAuth(wc_key, wc_secret)
    return await send_async_http_request(interaction, url, auth=auth)


async def fetch_espn_data(interaction, endpoint):
    base_url = "https://site.api.espn.com/apis/site/v2/"
    full_url = base_url + endpoint
    return await send_async_http_request(interaction, full_url)


async def fetch_openweather_data(interaction, latitude, longitude, date):
    match_date = datetime.fromisoformat(date).date()

    if match_date > datetime.utcnow().date() + timedelta(days=5):
        return "No weather information available for dates more than 5 days ahead."

    url = f"http://api.openweathermap.org/data/2.5/forecast?lat={latitude}&lon={longitude}&appid={openweather_api}&units=metric"
    return await send_async_http_request(interaction, url)


async def fetch_serpapi_flight_data(
    interaction, departure_airport, arrival_airport, outbound_date, return_date
):
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
        "api_key": serpapi_api,
    }
    return await send_async_http_request(
        interaction, base_url, method="GET", params=params
    )


async def check_new_orders(interaction, product_id):
    latest_order_id_in_db = get_latest_order_id()

    orders_url = wc_url.replace("orders/", f"orders?order=desc&product={product_id}&per_page=1")
    latest_orders = await call_woocommerce_api(interaction, orders_url)

    if latest_orders and len(latest_orders) > 0:
        latest_order_id_from_api = str(latest_orders[0].get("id", ""))

        if latest_order_id_from_api != latest_order_id_in_db:
            return True
        else:
            return False
    else:
        return False


async def update_orders_from_api(interaction, product_id):
    new_orders_count = 0
    page = 1
    latest_order_updated = False

    while True:
        orders_url = wc_url.replace("orders/", f"orders?order=desc&product={product_id}&page={page}")
        fetched_orders = await call_woocommerce_api(interaction, orders_url)

        if not fetched_orders:
            break

        for index, order in enumerate(fetched_orders):
            billing_info = order.get("billing", {})
            order_id = str(order.get("id", ""))

            if index == 0 and not latest_order_updated:
                update_latest_order_id(order_id)
                latest_order_updated = True

            order_data = json.dumps(order)
            update_woo_orders(order_id, order_data)

            for item in order.get("line_items", []):
                if item["product_id"] == product_id:
                    billing_address = ", ".join(
                        [
                            billing_info.get(key, "N/A") 
                            for key in ["address_1", "address_2", "city", "state", "postcode", "country"]
                        ]
                    )

                    insert_order_extract(
                        order["number"],
                        item["name"],
                        billing_info.get("first_name", "N/A"),
                        billing_info.get("last_name", "N/A"),
                        billing_info.get("email", "N/A"),
                        order.get("date_paid", "N/A"),
                        str(item.get("quantity", 0)),
                        str(item.get("price", "N/A")),
                        order["status"],
                        order.get("customer_note", "N/A"),
                        item.get("variation_id", "N/A"),
                        billing_address
                    )

            new_orders_count += 1

        page += 1

    return new_orders_count