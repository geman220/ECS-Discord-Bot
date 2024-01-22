# interactions.py

from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from common import load_redeemed_orders, save_redeemed_orders, load_current_role, save_current_role, wc_url
from api_helpers import call_woocommerce_api


class VerifyModal(discord.ui.Modal):
    def __init__(self, bot, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot

    order_id = discord.ui.TextInput(label="Order ID", placeholder="Enter your order ID number here")

    async def on_submit(self, interaction: discord.Interaction):
        order_id = self.order_id.value.strip()
        if order_id.startswith('#'):
            order_id = order_id[1:]

        redeemed_orders = load_redeemed_orders()

        if order_id in redeemed_orders:
            await interaction.response.send_message("This order has already been redeemed.", ephemeral=True)
            return

        full_url = f"{wc_url}{order_id}"
        response_data = await call_woocommerce_api(interaction, full_url)

        if response_data:
            order_data = response_data
            order_status = order_data['status']
            order_date_str = order_data['date_created']
            membership_prefix = "ECS Membership 20"
            membership_found = any(membership_prefix in item['name'] for item in order_data.get('line_items', []))

            if not membership_found:
                await interaction.response.send_message("The order does not contain the required ECS Membership item.", ephemeral=True)
                return

            order_date = datetime.fromisoformat(order_date_str)
            current_year = datetime.now().year
            cutoff_date = datetime(current_year - 1, 12, 1)

            if order_date < cutoff_date:
                await interaction.response.send_message("This order is not valid for the current membership period.", ephemeral=True)
                return

            if order_status in ['processing', 'completed']:
                redeemed_orders[order_id] = str(interaction.user.id)
                save_redeemed_orders(redeemed_orders)
                current_membership_role = load_current_role()
                role = discord.utils.get(interaction.guild.roles, name=current_membership_role)

                if role:
                    await interaction.user.add_roles(role)
                    await interaction.response.send_message("Thank you for validating your ECS membership!", ephemeral=True)
                else:
                    await interaction.response.send_message(f"{current_membership_role} role not found.", ephemeral=True)
            else:
                await interaction.response.send_message("Invalid order number or order status not eligible.", ephemeral=True)
        else:
            await interaction.response.send_message("Invalid order number or unable to retrieve order details.", ephemeral=True)
            
class CheckOrderModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="Check Order")
        self.bot = bot
        self.add_item(discord.ui.TextInput(label="Order ID", placeholder="Enter the order ID number"))

    async def on_submit(self, interaction: discord.Interaction):
        order_id = self.children[0].value.strip()
        if order_id.startswith('#'):
            order_id = order_id[1:]

        full_url = f"{wc_url}{order_id}"
        response_data = await call_woocommerce_api(interaction, full_url)

        if response_data:
            order_status = response_data['status']
            order_date_str = response_data['date_created']
            order_date = datetime.fromisoformat(order_date_str)
            membership_prefix = "ECS Membership 20"
            membership_found = any(membership_prefix in item['name'] for item in response_data.get('line_items', []))

            current_year = datetime.now().year
            cutoff_date = datetime(current_year - 1, 12, 1)

            if order_date < cutoff_date:
                response_message = "Membership expired."
            elif not membership_found:
                response_message = "The order does not contain the required ECS Membership item."
            elif order_status in ['processing', 'completed']:
                response_message = "That membership is valid for the current season."
            else:
                response_message = "Invalid order number."
        else:
            response_message = "Order not found"

        await interaction.response.send_message(response_message, ephemeral=True)
        
class NewRoleModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="New ECS Membership Role")
        self.bot = bot
        self.save_current_role = save_current_role
        self.new_role_input = None

    new_role = discord.ui.TextInput(label="Enter the new ECS Membership role")

    async def on_submit(self, interaction: discord.Interaction):
        self.new_role_input = self.new_role.value.strip()
        self.bot.current_membership_role = self.new_role_input
        self.save_current_role(self.new_role_input)

        view = ConfirmResetView(self.bot, self.new_role_input)
        await interaction.response.send_message("Do you want to clear the redeemed orders database for the new season?", view=view, ephemeral=True)

class ConfirmResetView(discord.ui.View):
    def __init__(self, bot, role):
        super().__init__()
        self.bot = bot
        self.redeemed_orders = load_redeemed_orders()
        self.save_redeemed_orders = save_redeemed_orders
        self.role = role

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user and interaction.user.guild_permissions.administrator

    @discord.ui.button(label="Yes, reset", style=discord.ButtonStyle.green, custom_id="confirm_reset")
    async def confirm_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.redeemed_orders.clear()
        self.save_redeemed_orders(self.redeemed_orders)
        await interaction.response.defer()
        await interaction.followup.send(f"Order redemption history cleared. New season started with role {self.role}.", ephemeral=True)

    @discord.ui.button(label="No, keep data", style=discord.ButtonStyle.red, custom_id="cancel_reset")
    async def cancel_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.followup.send(f"Database not cleared. New season started with role {self.role}", ephemeral=True)
