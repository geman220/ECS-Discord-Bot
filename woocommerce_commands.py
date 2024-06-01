# woocommerce_commands.py

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
    all_orders = await get_all_orders()
    relevant_orders = []

    for order in all_orders:
        line_items = order.get("line_items", [])
        for item in line_items:
            product_in_order = item.get("product_id", None)
            if product_in_order in product_ids:
                relevant_orders.append(order)
                break

    return relevant_orders

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

                if billing.get("email", "") != previous_email:
                    order_id = order.get("id", "")
                    alias = f"ecstix-{order_id}@weareecs.com"
                    alias_description = f"{item['name']} entry for {billing['first_name']} {billing['last_name']}"
                    alias_1_recipient = billing.get("email", "")
                    alias_2_recipient = "travel@weareecs.com"
                    alias_type = "MEMBER"

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
    @app_commands.guilds(discord.Object(id=server_id))
    async def subgrouplist(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        latest_order_id_in_db = get_latest_order_id()
        page = 1
        done = False
        member_info_by_subgroup = defaultdict(list)

        while not done:
            orders_url = wc_url.replace("orders/", f"orders?order=desc&page={page}&per_page=100")
            fetched_orders = await call_woocommerce_api(orders_url)

            if not fetched_orders or len(fetched_orders) < 100:
                done = True

            for order in fetched_orders:
                order_id = str(order.get("id", ""))

                if order_id == latest_order_id_in_db:
                    done = True
                    break

                subgroup_info = await find_customer_info_in_order(order, SUBGROUPS)
                if subgroup_info:
                    subgroup, customer_info = subgroup_info
                    member_info_by_subgroup[subgroup].append(customer_info)

                order_data = json.dumps(order)
                update_woo_orders(order_id, order_data)

            page += 1
            await asyncio.sleep(1)

        csv_output = io.StringIO()
        csv_writer = csv.writer(csv_output)
        header = ["Subgroup", "First Name", "Last Name", "Email"]
        csv_writer.writerow(header)

        for subgroup, members in member_info_by_subgroup.items():
            for member in members:
                csv_writer.writerow(
                    [
                        subgroup,
                        member["first_name"],
                        member["last_name"],
                        member["email"],
                    ]
                )

        csv_output.seek(0)
        filename = "subgroup_members_list.csv"
        csv_file = discord.File(fp=csv_output, filename=filename)
        await interaction.followup.send(
            "Subgroup members list:", file=csv_file, ephemeral=True
        )
        csv_output.close()

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