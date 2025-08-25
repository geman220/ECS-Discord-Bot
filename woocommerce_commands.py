# woocommerce_commands.py

import datetime
from http import server
import discord
from discord import app_commands
from discord.ext import commands
from collections import defaultdict
import urllib.parse
import asyncio
import csv
import io
import json
import datetime
import urllib
import difflib
from dateutil import parser
from common import (
    server_id, 
    has_required_wg_role, 
    has_admin_role,
)
from match_utils import wc_url
from utils import (
    find_customer_info_in_order, 
    extract_base_product_title, 
    extract_variation_detail,
)
from api_helpers import (
    call_woocommerce_api, 
    update_orders_from_api, 
    check_new_orders,
)
from database import (
    update_woo_orders,
    get_latest_order_id,
    get_order_extract,
    insert_order_extract,
    reset_woo_orders_db,
)
import logging
import tempfile
import os

debug = False

logger = logging.getLogger(__name__)

SUBGROUPS = [
    "253 Defiance",
    "Anchor 'n' Rose 48",
    "Armed Services Group",
    "Barra Fuerza Verde",
    "Bellingham Night Watch",
    "Dry Side Supporters",
    "European Sounders Federation",
    "Fog City Faithful",
    "Heartland Horde",
    "Pride of the Sound",
    "Seattle Sounders East",
    "Tropic Sound",
    "West Sound Armada",
]

async def get_product_by_name(product_name: str):
    """
    1) Perform a broad WooCommerce search for product_name.
    2) If any product is an exact name match, return it.
    3) Otherwise, do partial/fuzzy matching on product names
       and pick the 'best' match.
    """
    base_wc_url = wc_url.replace("/orders/", "/")
    encoded_name = urllib.parse.quote_plus(product_name)
    
    product_url = f"{base_wc_url}products?search={encoded_name}&per_page=50"

    products = await call_woocommerce_api(product_url)
    if not products or not isinstance(products, list):
        return None

    exact_matches = [
        p for p in products
        if p.get("name", "").strip().lower() == product_name.strip().lower()
    ]
    if exact_matches:
        return exact_matches[0]

    substring_matches = [
        p for p in products
        if product_name.lower() in p.get("name", "").lower()
    ]
    if len(substring_matches) == 1:
        return substring_matches[0]
    elif len(substring_matches) > 1:
        product_names = [p["name"] for p in substring_matches]
        best_guess = difflib.get_close_matches(product_name, product_names, n=1)
        if best_guess:
            for p in substring_matches:
                if p["name"] == best_guess[0]:
                    return p
        return substring_matches[0]

    product_names = [p["name"] for p in products]
    close = difflib.get_close_matches(product_name, product_names, n=1)
    if close:
        for p in products:
            if p["name"] == close[0]:
                return p

    return None

async def get_product_variations(product_id):
    base_wc_url = wc_url.replace("/orders/", "/")
    variations_url = f"{base_wc_url}products/{product_id}/variations"
    variations = await call_woocommerce_api(variations_url)
    return variations if isinstance(variations, list) else []

async def get_orders_for_product_ids(product_ids):
    if debug: print(f"[DEBUG] get_orders_for_product_ids called with: {product_ids}")
    
    if len(product_ids) == 1:
        all_orders = []
        for product_id in product_ids:
            orders = await get_single_product_orders_by_id(product_id)
            if debug: print(f"[DEBUG] Orders for single product_id {product_id}: {len(orders)} orders")
            all_orders.extend(orders)
    else:
        all_orders = await get_all_orders()
        if debug: print(f"[DEBUG] Total orders retrieved from get_all_orders: {len(all_orders)}")

    relevant_orders = []
    for order in all_orders:
        line_items = order.get("line_items", [])
        for item in line_items:
            product_in_order = item.get("product_id", None)
            if product_in_order in product_ids:
                append_line = True
                meta_data = item.get("meta_data", [])
                if debug: print(f"[DEBUG] Item meta_data: {meta_data}")
                for meta in meta_data:
                    if meta["key"] == "_reduced_stock": 
                        if meta["value"] == "0":
                            append_line = False
                if append_line:
                    relevant_orders.append(order)
                    if debug: print(f"[DEBUG] Appended order id: {order.get('id')}")
                break

    if debug: print(f"[DEBUG] Returning {len(relevant_orders)} relevant orders.")
    return relevant_orders

async def get_single_product_orders_by_id(product_id):
    base_wc_url = wc_url.replace("/orders/", "/")
    orders_url = f"{base_wc_url}orders"
    all_orders = []
    page = 1
    order_status = "processing"
    while True:
        current_url = f"{orders_url}?page={page}&per_page=100&status={order_status}&product={product_id}"
        page_orders = await call_woocommerce_api(current_url)

        if isinstance(page_orders, list):
            all_orders.extend(page_orders)
            if len(page_orders) < 100:
                if order_status == "processing":
                    order_status = "completed"
                    page = 1
                else:
                    break
            else:
                page += 1
        else:
            break

    return all_orders

async def get_all_orders():
    base_wc_url = wc_url.replace("/orders/", "/")
    orders_url = f"{base_wc_url}orders"
    all_orders = []
    page = 1
    order_status = "processing"
    while True:
        current_url = f"{orders_url}?page={page}&per_page=100&status={order_status}"
        page_orders = await call_woocommerce_api(current_url)

        if isinstance(page_orders, list):
            all_orders.extend(page_orders)
            if len(page_orders) < 100:
                if order_status == "processing":
                    order_status = "completed"
                    page = 1
                else:
                    break
            else:
                page += 1
        else:
            break

    return all_orders

async def generate_csv_from_orders(orders, product_ids):
    if debug: print(f"[DEBUG] Starting CSV generation for {len(orders)} orders and product_ids: {product_ids}")
    csv_output = io.StringIO()
    csv_writer = csv.writer(csv_output)

    headers = [
        "Product Name",
        "First Name",
        "Last Name",
        "Email",
        "Order Date",
        "Quantity",
        "Price",
        "Order #",
        "Status",
        "Note",
        "Variation",
        "Billing Address",
        "Alias",
        "Alias Description",
        "Alias 1 recipient",
        "Alias 1 type",
        "Alias 2 recipient",
        "Alias 2 type",
        "Email Sent"
    ]
    csv_writer.writerow(headers)

    rows = []
    previous_email = ""

    for order in orders:
        billing = order.get("billing", {})
        line_items = order.get("line_items", [])

        for item in line_items:
            product_in_order = item.get("product_id", None)
            if product_in_order in product_ids:
                # confirm in the line-item metadata the quantity reduced from stock
                # to account for line-item partial returns See order # 1005693
                item_quantity = ""
                item_meta_data = item.get("meta_data")
                if item_meta_data:
                    for meta in item_meta_data:
                        # in the get_orders_for_product_ids, we filter out orders where the item
                        # was completely returned/refunded. We only need to pay attention to the 
                        # _reduced_stock metadata item
                        if (meta["key"]=="_reduced_stock"):
                            item_quantity = meta["value"]
                else:
                    item_quantity = item.get("quantity")
                # Populate the row with initial values.
                row = [
                    item.get("name", ""),
                    billing.get("first_name", ""),
                    billing.get("last_name", ""),
                    billing.get("email", ""),
                    order.get("date_paid", ""),
                    item_quantity,
                    item.get("price", ""),
                    order.get("id", ""),
                    order.get("status", ""),
                    order.get("customer_note", ""),
                    item.get("variation_name", ""),
                    billing.get("address_1", "") + ", " + billing.get("city") + " " + billing.get("state"),
                    "",  # alias placeholder
                    "",  # alias description placeholder
                    "",  # alias 1 recipient placeholder
                    "",  # alias 1 type placeholder
                    "",  # alias 2 recipient placeholder
                    "",  # alias 2 type placeholder
                    ""   # Email Sent placeholder
                ]

                rows.append(row)
                if debug: print(f"[DEBUG] Processed order id {order.get('id')} into CSV row.")
                break

    if debug: print(f"[DEBUG] Sorting {len(rows)} rows.")
    rows.sort(key=lambda x: (x[3].lower(), int(x[7])))

    previous_email = ""  # Reset for alias logic.
    for row in rows:
        if row[3].lower() != previous_email:
            alias = f"ecstix-{row[7]}@weareecs.com"
            alias_description = f"{row[0]} entry for {row[1]} {row[2]}"
            alias_1_recipient = row[3]
            alias_2_recipient = "travel@weareecs.com"
            alias_type_member = "MEMBER"
            alias_type_owner = "OWNER"
        else:
            alias = ""
            alias_description = ""
            alias_1_recipient = ""
            alias_2_recipient = ""
            alias_type_member = ""
            alias_type_owner = ""

        row[12] = alias
        row[13] = alias_description
        row[14] = alias_1_recipient
        row[15] = alias_type_member
        row[16] = alias_2_recipient
        row[17] = alias_type_owner

        previous_email = row[3].lower()

    for row in rows:
        csv_writer.writerow(row)

    if debug: print(f"[DEBUG] CSV generation completed. Total rows written: {len(rows)}")
    return csv_output

async def generate_csv_for_product_variations(product_name):
    product = await get_product_by_name(product_name)
    
    if not product:
        raise Exception("Product not found")

    product_id = product.get("id")
    variations = await get_product_variations(product_id)

    all_orders = []
    for variation in variations:
        variation_id = variation.get("id")
        orders = await get_orders_for_product_ids(variation_id)
        
        if orders:
            all_orders.extend(orders)
    
    if not all_orders:
        raise Exception("No orders found for product variations")

    csv_output = await generate_csv_from_orders(all_orders, product_id)
    return csv_output

class WooCommerceCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ticketlist", description="List all tickets for sale")
    @app_commands.guilds(discord.Object(id=server_id))
    async def list_tickets(self, interaction: discord.Interaction):
        if not await has_required_wg_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        home_tickets_category = "765197885"
        away_tickets_category = "765197886"
        decoration = ""
        compare_date = datetime.datetime.now()
        current_year = datetime.datetime.now().year

        home_tickets = []
        home_tickets_url = wc_url.replace("orders/", f"products?category={home_tickets_category}&per_page=50&search={current_year}")
        home_tickets = await call_woocommerce_api(home_tickets_url)
        if home_tickets is not None:
            try:
                home_tickets.sort(
                    key=lambda x: parser.parse(x['name'], fuzzy=True)
                    if 'name' in x else datetime.datetime.min
                )
            except ValueError:
                # Skip sorting if any invalid date is encountered
                pass

        message_content = "🏠 **Home Tickets:** (sold, remaining)\n"
        if home_tickets:
            for product in home_tickets:
                try:
                    compare_date = parser.parse(product['name'], fuzzy=True)
                    offset = compare_date - datetime.datetime.now()

                    # Clamp offset to the allowed range
                    if not (datetime.timedelta(days=-1) < offset < datetime.timedelta(days=180)):
                        continue

                    decoration = "**" if offset <= datetime.timedelta(days=14) else ""
                    message_content += (
                        f"{decoration}{product['name']}{decoration} ({product['total_sales']}, {product['stock_quantity']})\n"
                    )
                except (ValueError, TypeError):
                    # Skip products with invalid dates
                    continue
        else:
            message_content += ("No home tickets found.\n")

        away_tickets = []
        away_tickets_url = wc_url.replace("orders/", f"products?category={away_tickets_category}&per_page=50&search={current_year}")
        away_tickets = await call_woocommerce_api(away_tickets_url)
        if away_tickets is not None:
            try:
                away_tickets.sort(
                    key=lambda x: parser.parse(x['name'], fuzzy=True)
                    if 'name' in x else datetime.datetime.min
                )
            except ValueError:
                # Skip sorting if any invalid date is encountered
                pass

        message_content += "\n🚗 **Away Tickets:** (sold, remaining)\n"
        if away_tickets:
            for product in away_tickets:
                try:
                    compare_date = parser.parse(product['name'], fuzzy=True)
                    offset = compare_date - datetime.datetime.now()

                    # Clamp offset to the allowed range; only show six months of tickets to avoid too many characters
                    if not (datetime.timedelta(days=-1) < offset < datetime.timedelta(days=180)):
                        continue

                    decoration = "**" if offset <= datetime.timedelta(days=14) else ""
                    message_content += (
                        f"{decoration}{product['name']}{decoration} ({product['total_sales']}, {product['stock_quantity']})\n"
                    )
                except (ValueError, TypeError):
                    # Skip products with invalid dates
                    continue
        else:
            message_content += ("No away tickets found.\n")

        await interaction.followup.send(message_content, ephemeral=True)
        
    @app_commands.command(
        name="getorderinfo", description="Retrieve order details for a specific product"
    )
    @app_commands.describe(product_title="Title of the product")
    @app_commands.guilds(discord.Object(id=server_id))
    async def get_product_orders(self, interaction: discord.Interaction, product_title: str):
        if debug: print(f"[DEBUG] Received command for product_title: {product_title}")

        if not await has_required_wg_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        await interaction.response.defer()
        if debug: print("[DEBUG] Deferred response sent.")

        product = await get_product_by_name(product_title)
        if not product:
            if debug: print(f"[DEBUG] Product not found: {product_title}")
            await interaction.followup.send("Product not found.", ephemeral=True)
            return
        if debug: print(f"[DEBUG] Found product: {product}")

        product_id = product["id"]
        variations = await get_product_variations(product_id)
        if debug: print(f"[DEBUG] Variations for product_id {product_id}: {variations}")

        product_ids = [product_id] + [variation["id"] for variation in variations]
        if debug: print(f"[DEBUG] Searching orders for product_ids: {product_ids}")

        relevant_orders = await get_orders_for_product_ids(product_ids)
        if debug: print(f"[DEBUG] Number of relevant orders found: {len(relevant_orders)}")

        if not relevant_orders:
            await interaction.followup.send("No orders found for this product or its variations.", ephemeral=True)
            return

        if debug: print("[DEBUG] Starting CSV generation...")
        csv_output = await generate_csv_from_orders(relevant_orders, product_ids)
        if debug: print("[DEBUG] CSV generation complete.")

        # Save StringIO content to a temporary file
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(csv_output.getvalue().encode())
            temp_file.flush()
            csv_filename = f"{product_title.replace('/', '_')}_orders.csv"
            csv_file = discord.File(fp=temp_file.name, filename=csv_filename)

        # Ensure temporary file is cleaned up after use
        import atexit
        atexit.register(lambda: os.remove(temp_file.name))

        await interaction.followup.send(
            f"Orders for product '{product_title}':", file=csv_file, ephemeral=True
        )
        if debug: print(f"[DEBUG] Followup message with CSV sent: {csv_filename}")

        csv_output.close()

    @app_commands.command(
        name="updateorders", description="Update local orders database from WooCommerce"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def update_orders(self, interaction: discord.Interaction):
        if not await has_required_wg_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        latest_order_id_in_db = get_latest_order_id()
        new_orders_count = 0
        page = 1
        done = False

        while not done:
            orders_url = wc_url.replace("orders/", f"orders?order=desc&page={page}")
            fetched_orders = await call_woocommerce_api(orders_url)

            if not fetched_orders:
                break

            for order in fetched_orders:
                order_id = str(order.get("id", ""))

                if order_id == latest_order_id_in_db:
                    done = True
                    break

                order_data = json.dumps(order)
                update_woo_orders(order_id, order_data)
                new_orders_count += 1

            page += 1
            await asyncio.sleep(1)

        message = f"Orders database updated. Added {new_orders_count} new orders."
        await interaction.followup.send(message, ephemeral=True)

    @app_commands.command(
        name="subgrouplist",
        description="Create a CSV list of members in each subgroup for a specified year"
    )
    @app_commands.describe(year="The year for which to generate the CSV list (e.g., 2024, 2025)")
    @app_commands.guilds(discord.Object(id=server_id))
    async def subgrouplist(self, interaction: discord.Interaction, year: int):
        try:
            if not await has_admin_role(interaction):
                await interaction.response.send_message(
                    "You do not have the necessary permissions.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True, thinking=True)

            now = datetime.datetime.now()
            current_year = now.year

            # Do not allow future years
            if year > current_year:
                await interaction.followup.send(
                    f"You cannot search for a future year ({year}).", ephemeral=True
                )
                return

            # Define the date range for the query.
            start_date = datetime.datetime(year, 1, 1, 0, 0, 0)
            if year < current_year:
                # For past years, use the full year.
                end_date = datetime.datetime(year, 12, 31, 23, 59, 59)
            else:
                # For the current year, use up to now.
                end_date = now

            start_of_time = start_date.strftime("%Y-%m-%dT%H:%M:%S")
            end_of_time = end_date.strftime("%Y-%m-%dT%H:%M:%S")

            page = 1
            per_page = 100
            member_info_by_subgroup = defaultdict(list)

            # Continue paging until no orders are returned.
            while True:
                orders_url = (
                    f"{wc_url}?order=desc&page={page}&per_page={per_page}"
                    f"&status=any&after={start_of_time}&before={end_of_time}"
                )
                logger.info(f"Fetching orders from page {page}.")
                fetched_orders = await call_woocommerce_api(orders_url)

                if not fetched_orders:
                    logger.info(f"No orders fetched from page {page}. Ending pagination.")
                    break

                # Process each order.
                for order in fetched_orders:
                    order_id = order.get("id", "Unknown")
                    # Pass the specified 'year' as membership_year to the customer info lookup.
                    subgroup_info = await find_customer_info_in_order(order, SUBGROUPS, membership_year=year)
                    if subgroup_info:
                        matched_subgroups, customer_info = subgroup_info

                        if not isinstance(matched_subgroups, list):
                            logger.error(f"'matched_subgroups' is not a list for Order ID {order_id}.")
                            continue

                        for subgroup in matched_subgroups:
                            if not isinstance(subgroup, str):
                                logger.error(f"Subgroup is not a string for Order ID {order_id}: {subgroup}")
                                continue
                            member_info_by_subgroup[subgroup].append(customer_info)

                # If fewer orders than requested are returned, we assume it's the last page.
                if len(fetched_orders) < per_page:
                    logger.info(f"Fetched {len(fetched_orders)} orders on page {page}. Assuming this is the last page.")
                    break

                page += 1
                # Respect API rate limits.
                await asyncio.sleep(1)

            # If no members were found, inform the user.
            if not member_info_by_subgroup:
                logger.info("No members found matching the criteria.")
                await interaction.followup.send(
                    "No members found in the specified subgroups within the given date range.",
                    ephemeral=True
                )
                return

            # Generate CSV output.
            csv_output = io.StringIO()
            csv_writer = csv.writer(csv_output)
            header = ["Subgroup", "First Name", "Last Name", "Email"]
            csv_writer.writerow(header)

            for subgroup, members in member_info_by_subgroup.items():
                for member in members:
                    csv_writer.writerow([
                        subgroup,
                        member.get("first_name", "").strip(),
                        member.get("last_name", "").strip(),
                        member.get("email", "").strip()
                    ])

            csv_output.seek(0)
            filename = f"subgroup_members_list_{year}.csv"
            csv_bytes = io.BytesIO(csv_output.getvalue().encode('utf-8'))
            csv_file = discord.File(fp=csv_bytes, filename=filename)

            # Send the CSV file as a follow-up message.
            await interaction.followup.send(
                content="Here is the list of subgroup members:",
                file=csv_file,
                ephemeral=True
            )
            csv_output.close()
            csv_bytes.close()

        except Exception as e:
            logger.error(f"An error occurred: {str(e)}")
            if interaction.response.is_done():
                try:
                    await interaction.followup.send(
                        f"An error occurred while generating the list: {str(e)}",
                        ephemeral=True
                    )
                except discord.HTTPException as followup_error:
                    logger.error(f"Failed to send followup message: {followup_error}")
            else:
                try:
                    await interaction.response.send_message(
                        f"An error occurred while generating the list: {str(e)}",
                        ephemeral=True
                    )
                except discord.HTTPException as response_error:
                    logger.error(f"Failed to send response message: {response_error}")

    @app_commands.command(
        name="refreshorders", description="Refresh Woo Commerce order cache"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def refreshorders(self, interaction: discord.Interaction):
        if not await has_required_wg_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)

        reset = reset_woo_orders_db() 
        message = f"Orders database reset. Please run updateorders now."
        await interaction.followup.send(message, ephemeral=True)
        
async def setup(bot):
    await bot.add_cog(WooCommerceCommands(bot))

