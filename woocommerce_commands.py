# woocommerce_commands.py

import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import csv
import io
import json
from common import server_id, has_required_wg_role, has_admin_role
from match_utils import wc_url
from api_helpers import call_woocommerce_api
from database import (
    update_woo_orders,
    get_latest_order_id,
    count_orders_for_multiple_subgroups,
    get_members_for_subgroup,
)
import urllib.parse

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

        home_tickets_url = wc_url.replace(
            "orders/", f"products?category={home_tickets_category}"
        )
        away_tickets_url = wc_url.replace(
            "orders/", f"products?category={away_tickets_category}"
        )

        home_tickets = await call_woocommerce_api(interaction, home_tickets_url)
        await asyncio.sleep(1)
        away_tickets = await call_woocommerce_api(interaction, away_tickets_url)

        message_content = "🏠 **Home Tickets:**\n"
        message_content += (
            "\n".join([product["name"] for product in home_tickets])
            if home_tickets
            else "No home tickets found."
        )

        message_content += "\n\n🚗 **Away Tickets:**\n"
        message_content += (
            "\n".join([product["name"] for product in away_tickets])
            if away_tickets
            else "No away tickets found."
        )

        await interaction.followup.send(message_content, ephemeral=True)

    @app_commands.command(
        name="getorderinfo", description="Retrieve order details for a specific product"
    )
    @app_commands.describe(product_title="Title of the product")
    @app_commands.guilds(discord.Object(id=server_id))
    async def get_product_orders(
        self, interaction: discord.Interaction, product_title: str
    ):
        if not await has_required_wg_role(interaction):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return

        await interaction.response.defer()

        encoded_product_title = urllib.parse.quote_plus(product_title)
        product_url = wc_url.replace(
            "orders/", f"products?search={encoded_product_title}"
        )
        products = await call_woocommerce_api(interaction, product_url)
        product = next(
            (p for p in products if p["name"].lower() == product_title.lower()), None
        )
        if not product:
            await interaction.followup.send("Product not found.", ephemeral=True)
            return

        product_id = product["id"]
        await asyncio.sleep(1)

        all_orders = []
        page = 1
        while True:
            all_orders_url = wc_url.replace("orders/", f"orders?product={product_id}&page={page}")
            orders_page = await call_woocommerce_api(interaction, all_orders_url)

            if not orders_page:
                break

            all_orders.extend(orders_page)

            page += 1
            await asyncio.sleep(1)

        filtered_orders = [
            order
            for order in all_orders
            if any(
                item["product_id"] == product_id
                for item in order.get("line_items", [])
            )
        ]

        if not filtered_orders:
            await interaction.followup.send(
                "No orders found for this product.", ephemeral=True
            )
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
            "Shipping Address",
            "Alias",
            "Alias Description",
            "Alias 1 email",
            "Alias 1 recipient",
            "Alias 1 type",
            "Alias 2 email",
            "Alias 2 recipient",
            "Alias 2 type",
        ]
        csv_writer.writerow(header)

        for order in filtered_orders:
            for item in order.get("line_items", []):
                if item["product_id"] == product_id:
                    billing_address = ", ".join(
                        [
                            order["billing"].get(key, "N/A")
                            for key in [
                                "address_1",
                                "address_2",
                                "city",
                                "state",
                                "postcode",
                                "country",
                            ]
                        ]
                    )
                    shipping_address = ", ".join(
                        [
                            order.get("shipping", {}).get(key, "N/A")
                            for key in [
                                "address_1",
                                "address_2",
                                "city",
                                "state",
                                "postcode",
                                "country",
                            ]
                        ]
                    )
                    alias = f"ecstix-{order['number']}@weareecs.com"
                    alias_description = f"{item['name']} entry for {order['billing'].get('first_name', 'N/A')} {order['billing'].get('last_name', 'N/A')}"
                    alias_type = "Member"
                    alias_1_recipient = order["billing"].get("email", "N/A")
                    alias_2_recipient = "travel@weareecs.com"
                    row = [
                        item["name"],
                        order["billing"].get("first_name", "N/A"),
                        order["billing"].get("last_name", "N/A"),
                        order["billing"].get("email", "N/A"),
                        order.get("date_paid", "N/A"),
                        str(item.get("quantity", 0)),
                        str(item.get("price", "N/A")),
                        order["number"],
                        order["status"],
                        order.get("customer_note", "N/A"),
                        item.get("variation_id", "N/A"),
                        billing_address,
                        shipping_address,
                        alias,
                        alias_description,
                        alias,
                        alias_1_recipient,
                        alias_type,
                        alias,
                        alias_2_recipient,
                        alias_type
                    ]
                    csv_writer.writerow(row)

        csv_output.seek(0)
        sanitized_name = product_title.replace("/", "_").replace("\\", "_")
        filename = f"{sanitized_name}_orders.csv"
        csv_file = discord.File(fp=csv_output, filename=filename)
        await interaction.followup.send(
            f"Orders for product '{product_title}':", file=csv_file, ephemeral=True
        )
        csv_output.close()

    @app_commands.command(
        name="updateorders", description="Update local orders database from WooCommerce"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def update_orders(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
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
            fetched_orders = await call_woocommerce_api(interaction, orders_url)

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
        name="subgroupcount", description="Count orders for each subgroup"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def subgroup_count(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
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
            fetched_orders = await call_woocommerce_api(interaction, orders_url)

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

        subgroup_counts = count_orders_for_multiple_subgroups(SUBGROUPS)
        message_content = "Subgroup Order Counts:\n"
        for subgroup, count in subgroup_counts.items():
            message_content += f"{subgroup}: {count}\n"

        await interaction.followup.send(message_content, ephemeral=True)

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

        while not done:
            orders_url = wc_url.replace("orders/", f"orders?order=desc&page={page}")
            fetched_orders = await call_woocommerce_api(interaction, orders_url)

            if not fetched_orders:
                break

            for order in fetched_orders:
                order_id = str(order.get("id", ""))

                if order_id == latest_order_id_in_db:
                    done = True
                    break

                order_data = json.dumps(order)
                update_woo_orders(order_id, order_data)

            page += 1
            await asyncio.sleep(1)

        csv_output = io.StringIO()
        csv_writer = csv.writer(csv_output)
        header = ["Subgroup", "First Name", "Last Name", "Email"]
        csv_writer.writerow(header)

        for subgroup in SUBGROUPS:
            member_list = get_members_for_subgroup(subgroup)
            for member in member_list:
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