import requests
import logging
import re
from woocommerce import API
from flask import current_app
import uuid

logger = logging.getLogger(__name__)

def fetch_orders_from_woocommerce(current_season_name):
    wcapi = API(
        url=current_app.config['WOO_API_URL'],
        consumer_key=current_app.config['WOO_CONSUMER_KEY'],
        consumer_secret=current_app.config['WOO_CONSUMER_SECRET'],
        version="wc/v3"
    )

    orders = []
    page = 1
    season_string = f"{current_season_name} ECS Pub League"
    logger.info(f"Looking for orders matching: {season_string} or 'ECS FC'")

    while True:
        try:
            params = {
                'status': 'completed',
                'page': page,
                'per_page': 100
            }

            logger.info(f"Making request to WooCommerce API: {wcapi.url}orders with params: {params}")
            response = wcapi.get("orders", params=params)
            response.raise_for_status()

            fetched_orders = response.json()
            if not fetched_orders:
                logger.info(f"No more orders found at page {page}. Stopping.")
                break

            # Filter orders based on product name containing "ECS Pub League", "ECS FC", or season-specific strings
            for order in fetched_orders:
                order_id = order['id']
                for item in order['line_items']:
                    product_name = item['name']
                    if ("ECS Pub League" in product_name or "ECS FC" in product_name) or \
                       (season_string in product_name and ("Classic Division" in product_name or "Premier Division" in product_name)):
                        orders.append({
                            'order_id': order_id,
                            'product_name': product_name,
                            'billing': order['billing'],
                            'quantity': item.get('quantity', 1)  # Extract quantity
                        })

            page += 1

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching data from WooCommerce: {e}", exc_info=True)
            break

    logger.info(f"Total orders fetched: {len(orders)}")
    return orders

def fetch_order_by_id(order_id):
    wcapi = API(
        url=current_app.config['WOO_API_URL'],
        consumer_key=current_app.config['WOO_CONSUMER_KEY'],
        consumer_secret=current_app.config['WOO_CONSUMER_SECRET'],
        version="wc/v3"
    )

    try:
        logger.info(f"Fetching WooCommerce order with ID: {order_id}")
        response = wcapi.get(f"orders/{order_id}")
        response.raise_for_status()

        order = response.json()

        # Filter based on the product name containing "ECS Pub League", "ECS FC", or other relevant criteria
        for item in order.get('line_items', []):
            product_name = item['name']
            if ("ECS Pub League" in product_name or "ECS FC" in product_name):
                logger.info(f"Order ID {order_id} matches the criteria.")
                return {
                    'order_id': order_id,
                    'product_name': product_name,
                    'billing': order['billing'],
                    'quantity': item.get('quantity', 1)
                }

        logger.warning(f"Order ID {order_id} does not match the criteria.")
        return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching order from WooCommerce: {e}", exc_info=True)
        return None