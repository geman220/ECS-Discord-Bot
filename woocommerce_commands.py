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

logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG to capture all levels of logs
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_debug.log"),  # Log to a file
        logging.StreamHandler()  # Also log to console
    ]
)

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

async def get_product_by_name(product_name):
    base_wc_url = wc_url.replace("/orders/", "/")
    encoded_name = urllib.parse.quote_plus(product_name)
    product_url = f"{base_wc_url}products?search={encoded_name}"
    products = await call_woocommerce_api(product_url)
    return products[0] if products and isinstance(products, list) else None

async def get_product_variations(product_id):
    base_wc_url = wc_url.replace("/orders/", "/")
    variations_url = f"{base_wc_url}products/{product_id}/variations"
    variations = await call_woocommerce_api(variations_url)
    return variations if isinstance(variations, list) else []

async def get_orders_for_product_ids(product_ids):
    if len(product_ids)==1:
        for product_id in product_ids:
            all_orders = await get_single_product_orders_by_id(product_id)
    else:
        all_orders = await get_all_orders()
    relevant_orders = []

    for order in all_orders:
        line_items = order.get("line_items", [])
        for item in line_items:
            product_in_order = item.get("product_id", None)
            if product_in_order in product_ids:
                append_line = True
                meta_data = item.get("meta_data")
                for meta in meta_data:
                    if meta.get("key")=="_restock_refunded_items": 
                        append_line = False
                if append_line: 
                    relevant_orders.append(order)
                break

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
    csv_output = io.StringIO()
    csv_writer = csv.writer(csv_output)

    headers = [
        "Product Name",
        "Customer First Name",
        "Customer Last Name",
        "Customer Email",
        "Order Date Paid",
        "Order Line Item Quantity",
        "Order Line Item Price",
        "Order Number",
        "Order Status",
        "Order Customer Note",
        "Product Variation Name",
        "Billing Address",
        "Alias",
        "Alias Email",
        "Alias Description",
        "Alias 1 email",
        "Alias 1 recipient",
        "Alias 1 type",
        "Alias 2 email",
        "Alias 2 recipient",
        "Alias 2 type",
        "Product Variation Detail",
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
                alias = ""
                alias_description = ""
                alias_1_recipient = ""
                alias_2_recipient = ""
                alias_type = ""

                alias = ""
                alias_description = ""
                alias_1_recipient = ""
                alias_2_recipient = ""
                alias_type = ""

                item_price = item.get("price", "")

                row = [
                    item.get("name", ""),
                    billing.get("first_name", ""),
                    billing.get("last_name", ""),
                    billing.get("email", ""),
                    order.get("date_paid", ""),
                    item.get("quantity", ""),
                    item_price,
                    order.get("id", ""),
                    order.get("status", ""),
                    order.get("customer_note", ""),
                    item.get("variation_name", ""),
                    billing.get("address_1", ""),
                    alias,
                    alias,
                    alias_description,
                    alias,
                    alias_1_recipient,
                    alias_type,
                    alias,
                    alias_2_recipient,
                    alias_type,
                ]

                variation_detail = extract_variation_detail(order)
                row.append(variation_detail)

                rows.append(row)
                previous_email = billing.get("email", "")
                break

    rows.sort(key=lambda x: (x[3].lower(), int(x[7])))

    previous_email = "" #reset the email loop
    for row in rows:
        if row[3] != previous_email:
            alias = f"ecstix-{row[7]}@weareecs.com"
            alias_description = f"{row[0]} entry for {row[1]} {row[2]}"
            alias_1_recipient = row[3]
            alias_2_recipient = "travel@weareecs.com"
            alias_type = "MEMBER"
        else:
            alias = ""
            alias_description = ""
            alias_1_recipient = ""
            alias_2_recipient = ""
            alias_type = ""

        row[12] = alias
        row[13] = alias
        row[14] = alias_description
        row[15] = alias
        row[16] = alias_1_recipient
        row[17] = alias_type
        row[18] = alias
        row[19] = alias_2_recipient
        row[20] = alias_type

        previous_email = row[3]

    for row in rows:
        csv_writer.writerow(row)

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

    csv_output = await generate_csv_from_orders(all_orders)
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
        current_year = datetime.datetime.now().year

        home_tickets = []
        home_tickets_url = wc_url.replace("orders/", f"products?category={home_tickets_category}&per_page=50&search={current_year}")
        home_tickets = await call_woocommerce_api(home_tickets_url)

        message_content = "🏠 **Home Tickets:**\n"
        message_content += (
            "\n".join(f"{product['name']} ({product['stock_quantity']})" for product in home_tickets) 
            if home_tickets
            else "No home tickets found."
        )

        away_tickets = []
        away_tickets_url = wc_url.replace("orders/", f"products?category={away_tickets_category}&per_page=50&search={current_year}")
        away_tickets = await call_woocommerce_api(away_tickets_url)

        message_content += "\n\n🚗 **Away Tickets:**\n"
        message_content += (
            "\n".join(f"{product['name']} ({product['stock_quantity']})" for product in away_tickets)
            if away_tickets
            else "No away tickets found."
        )

        await interaction.followup.send(message_content, ephemeral=True)
        
    @app_commands.command(
        name="getorderinfo", description="Retrieve order details for a specific product"
    )
    @app_commands.describe(product_title="Title of the product")
    @app_commands.guilds(discord.Object(id=server_id))
    async def get_product_orders(self, interaction: discord.Interaction, product_title: str):
        if not await has_required_wg_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return
        
        await interaction.response.defer()

        product = await get_product_by_name(product_title)
        if not product:
            await interaction.followup.send("Product not found.", ephemeral=True)
            return

        product_id = product["id"]
        variations = await get_product_variations(product_id)

        product_ids = [product_id] + [variation["id"] for variation in variations]

        relevant_orders = await get_orders_for_product_ids(product_ids)

        if not relevant_orders:
            await interaction.followup.send("No orders found for this product or its variations.", ephemeral=True)
            return

        csv_output = await generate_csv_from_orders(relevant_orders, product_ids)

        csv_output.seek(0)
        csv_filename = f"{product_title.replace('/', '_')}_orders.csv"
        csv_file = discord.File(fp=csv_output, filename=csv_filename)

        await interaction.followup.send(
            f"Orders for product '{product_title}':", file=csv_file, ephemeral=True
        )

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
        name="subgrouplist", description="Create a CSV list of members in each subgroup"
    )
    @app_commands.guilds(discord.Object(id=server_id))  # Replace SERVER_ID with your actual server ID
    async def subgrouplist(self, interaction: discord.Interaction):
        try:
            # Check permissions
            if not await has_admin_role(interaction):
                await interaction.response.send_message(
                    "You do not have the necessary permissions.", ephemeral=True
                )
                return

            # Defer the response to give the bot time to process
            await interaction.response.defer(ephemeral=True, thinking=True)

            # Set a wide date range to fetch all orders
            # Alternatively, set a date range that covers the current year
            start_of_time = f"{datetime.datetime.now().year - 1}-01-01T00:00:00"  # Start from last year
            today = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            page = 1
            per_page = 100  # Maximum per WooCommerce API
            done = False
            member_info_by_subgroup = defaultdict(list)

            while not done:
                # Construct the orders URL with pagination and date filters
                orders_url = wc_url.replace(
                    "orders/",
                    f"orders?order=desc&page={page}&per_page={per_page}"
                    f"&status=any&after={start_of_time}&before={today}"
                )

                logger.info(f"Fetching orders from page {page}.")

                # Fetch orders from WooCommerce
                fetched_orders = await call_woocommerce_api(orders_url)

                if not fetched_orders:
                    # If the API call failed or no orders returned, stop fetching
                    logger.info(f"No orders fetched from page {page}. Ending pagination.")
                    done = True
                    break

                if len(fetched_orders) < per_page:
                    # Last page of results
                    logger.info(f"Fetched {len(fetched_orders)} orders from page {page}. Assuming last page.")
                    done = True

                # Process each order
                for order in fetched_orders:
                    order_id = order.get('id', 'Unknown')
                    logger.debug(f"Processing Order ID: {order_id}")
                    # Fetch customer info based on subgroup
                    subgroup_info = await find_customer_info_in_order(order, SUBGROUPS)
                    if subgroup_info:
                        matched_subgroups, customer_info = subgroup_info
                        
                        # Verify that 'matched_subgroups' is a list
                        if not isinstance(matched_subgroups, list):
                            logger.error(f"'matched_subgroups' is not a list for Order ID {order_id}.")
                            continue  # Skip this order

                        # Verify that each 'subgroup' is a string
                        for subgroup in matched_subgroups:
                            if not isinstance(subgroup, str):
                                logger.error(f"Subgroup is not a string for Order ID {order_id}: {subgroup}")
                                continue  # Skip this subgroup
                            
                            member_info_by_subgroup[subgroup].append(customer_info)
                            logger.debug(f"Added customer from Order ID {order_id} to subgroup '{subgroup}'.")

                # Move to the next page
                page += 1

                # Sleep to respect API rate limits
                await asyncio.sleep(1)

            # Check if any members were found
            if not member_info_by_subgroup:
                logger.info("No members found matching the criteria.")
                await interaction.followup.send(
                    "No members found in the specified subgroups within the given date range.",
                    ephemeral=True
                )
                return

            # Create CSV
            csv_output = io.StringIO()
            csv_writer = csv.writer(csv_output)
            header = ["Subgroup", "First Name", "Last Name", "Email"]
            csv_writer.writerow(header)

            for subgroup, members in member_info_by_subgroup.items():
                for member in members:
                    # Ensure that the member's data is correctly formatted
                    csv_writer.writerow([
                        subgroup,
                        member.get("first_name", "").strip(),
                        member.get("last_name", "").strip(),
                        member.get("email", "").strip()
                    ])
                    logger.debug(f"Written to CSV: {subgroup}, {member.get('first_name', '')}, {member.get('last_name', '')}, {member.get('email', '')}")

            # Prepare CSV for sending
            csv_output.seek(0)
            filename = "subgroup_members_list.csv"
            csv_file = discord.File(fp=csv_output, filename=filename)

            # Send the CSV file as a follow-up message
            await interaction.followup.send(
                content="Here is the list of subgroup members:",
                file=csv_file,
                ephemeral=True
            )

            logger.info(f"Successfully sent CSV file '{filename}' to user {interaction.user}.")

            # Close the StringIO object
            csv_output.close()

        except Exception as e:
            # Log the error
            logger.error(f"An error occurred: {str(e)}")
            # Check if the interaction has already been acknowledged
            if interaction.response.is_done():
                # If already acknowledged (deferred), use followup
                try:
                    await interaction.followup.send(
                        f"An error occurred while generating the list: {str(e)}",
                        ephemeral=True
                    )
                except discord.HTTPException as followup_error:
                    logger.error(f"Failed to send followup message: {followup_error}")
            else:
                # If not acknowledged, send a response
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