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

async def get_orders_for_product(product_id: int):
    orders_url = wc_url.replace("orders/", f"orders?product={product_id}")
    orders = await call_woocommerce_api(orders_url)
    return orders if orders else []


class WooCommerceCommands(commands.Cog, name="WooCommerce Commands"):
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

        all_home_tickets = []
        page = 1
        while True:
            home_tickets_url = wc_url.replace("orders/", f"products?category={home_tickets_category}&page={page}")
            home_tickets_page = await call_woocommerce_api(interaction, home_tickets_url)

            if not home_tickets_page:
                break

            all_home_tickets.extend(home_tickets_page)

            page += 1
            await asyncio.sleep(1)

        message_content = "🏠 **Home Tickets:**\n"
        message_content += (
            "\n".join([product["name"] for product in all_home_tickets])
            if all_home_tickets
            else "No home tickets found."
        )

        all_away_tickets = []
        page = 1
        while True:
            away_tickets_url = wc_url.replace("orders/", f"products?category={away_tickets_category}&page={page}")
            away_tickets_page = await call_woocommerce_api(interaction, away_tickets_url)

            if not away_tickets_page:
                break

            all_away_tickets.extend(away_tickets_page)

            page += 1
            await asyncio.sleep(1)

        message_content += "\n\n🚗 **Away Tickets:**\n"
        message_content += (
            "\n".join([product["name"] for product in all_away_tickets])
            if all_away_tickets
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
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.defer()
        

        base_product_title = extract_base_product_title(product_title)
        encoded_product_title = urllib.parse.quote_plus(base_product_title)
        product_url = wc_url.replace("orders/", f"products?search={encoded_product_title}")
        products = await call_woocommerce_api(product_url)
#   if the product has variations, pull the variation array instead of the parent product
        if not products["variations"]:
            matching_products = [p for p in products if p["name"].lower().startswith(base_product_title.lower())]
        else:
            matching_products = products["variations"]

        all_orders = []
        for product in matching_products:
            product_orders = await get_orders_for_product(product["id"])
            all_orders.extend(product_orders)
        if not product:
            await interaction.followup.send("Product not found.", ephemeral=True)
            return

        product_id = product["id"]
        await asyncio.sleep(1)

        if await check_new_orders(product_id):
            await asyncio.sleep(1)
            await update_orders_from_api(product_id)

        order_extract_data = get_order_extract(product_title)

        if not order_extract_data:
            await interaction.followup.send("No orders found for this product.", ephemeral=True)
            return

        csv_output = io.StringIO()
        csv_writer = csv.writer(csv_output)
        header = [
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
        csv_writer.writerow(header)

        previous_email = ""
        for order in order_extract_data:
            alias = ""
            alias_description = ""
            alias_1_recipient = ""
            alias_2_recipient = ""
            alias_type = ""

            if order["email_address"] != previous_email:
                alias = f"ecstix-{order['order_id']}@weareecs.com"
                alias_description = f"{order['product_name']} entry for {order['first_name']} {order['last_name']}"
                alias_1_recipient = order["email_address"]
                alias_2_recipient = "travel@weareecs.com"
                alias_type = "MEMBER"

            row = [
                order["product_name"],
                order["first_name"],
                order["last_name"],
                order["email_address"],
                order["order_date"],
                order["item_qty"],
                order["item_price"],
                order["order_id"],
                order["order_status"],
                order["order_note"],
                order["product_variation"],
                order["billing_address"],
                alias,
                alias,
                alias_description,
                alias,
                alias_1_recipient,
                alias_type,
                alias,
                alias_2_recipient,
                alias_type
            ]
            variation_detail = extract_variation_detail(order)
            row.append(variation_detail)
            csv_writer.writerow(row)
            previous_email = order["email_address"]

        csv_output.seek(0)
        if csv_output.getvalue():
            sanitized_name = product_title.replace("/", "_").replace("\\", "_")
            filename = f"{sanitized_name}_orders.csv"
            csv_file = discord.File(fp=csv_output, filename=filename)
            await interaction.followup.send(
                f"Orders for product '{product_title}':", file=csv_file, ephemeral=True
            )
        else:
            await interaction.followup.send(
                "No orders found for this product.", ephemeral=True
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
