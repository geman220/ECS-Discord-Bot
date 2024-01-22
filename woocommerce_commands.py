# woocommerce_commands.py

import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import csv
import io
from common import server_id, has_required_wg_role
from match_utils import wc_url
from api_helpers import call_woocommerce_api

class WooCommerceCommands(commands.Cog, name="WooCommerce Commands"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='ticketlist', description="List all tickets for sale")
    @app_commands.guilds(discord.Object(id=server_id))
    async def list_tickets(self, interaction: discord.Interaction):
        if not await has_required_wg_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        home_tickets_category = "765197885"
        away_tickets_category = "765197886"

        home_tickets_url = wc_url.replace('orders/', f'products?category={home_tickets_category}')
        away_tickets_url = wc_url.replace('orders/', f'products?category={away_tickets_category}')

        home_tickets = await call_woocommerce_api(interaction, home_tickets_url)
        await asyncio.sleep(1)
        away_tickets = await call_woocommerce_api(interaction, away_tickets_url)

        message_content = "🏠 **Home Tickets:**\n"
        message_content += "\n".join([product["name"] for product in home_tickets]) if home_tickets else "No home tickets found."

        message_content += "\n\n🚗 **Away Tickets:**\n"
        message_content += "\n".join([product["name"] for product in away_tickets]) if away_tickets else "No away tickets found."

        await interaction.followup.send(message_content, ephemeral=True)

    @app_commands.command(name='getorderinfo', description="Retrieve order details for a specific product")
    @app_commands.describe(product_title='Title of the product')
    @app_commands.guilds(discord.Object(id=server_id))
    async def get_product_orders(self, interaction: discord.Interaction, product_title: str):
        if not await has_required_wg_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        product_url = wc_url.replace('orders/', f'products?search={product_title}')
        products = await call_woocommerce_api(interaction, product_url)
    
        if not products:
            await interaction.response.send_message("No products found or failed to fetch products.", ephemeral=True)
            return

        product = next((p for p in products if p['name'].lower() == product_title.lower()), None)

        if not product:
            await interaction.response.send_message("Product not found.", ephemeral=True)
            return

        orders_url = wc_url.replace('products?', f'orders?product={product["id"]}')
        orders = await call_woocommerce_api(interaction, orders_url)

        if not orders:
            await interaction.response.send_message("No orders found for this product.", ephemeral=True)
            return

        csv_output = io.StringIO()
        csv_writer = csv.writer(csv_output)
        header = ["Product Name", "Customer First Name", "Customer Last Name", "Customer Username", "Customer Email",
                  "Order Date Paid", "Order Line Item Quantity", "Order Line Item Price", "Order Number", "Order Status",
                  "Order Customer Note", "Product Variation Name"]
        csv_writer.writerow(header)

        for order in orders:
            for item in order.get('line_items', []):
                if item['product_id'] == product['id']:
                    row = [product['name'],
                           order['billing']['first_name'],
                           order['billing']['last_name'],
                           order['customer_user_agent'],
                           order['billing']['email'],
                           order.get('date_paid', 'N/A'),
                           item['quantity'],
                           item['price'],
                           order['number'],
                           order['status'],
                           order.get('customer_note', 'N/A'),
                           item['name']]
                    csv_writer.writerow(row)

        csv_output.seek(0)
        csv_file = discord.File(fp=csv_output, filename=f"{product_title}_orders.csv")

        await interaction.response.send_message(f"Orders for product '{product_title}':", file=csv_file, ephemeral=True)

        csv_output.close()