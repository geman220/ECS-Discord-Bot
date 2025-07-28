# interactions.py

from datetime import datetime
import discord
from common import (
    load_redeemed_orders,
    save_redeemed_orders,
    load_current_role,
    save_current_role,
)
from match_utils import wc_url
from api_helpers import call_woocommerce_api


class VerifyModal(discord.ui.Modal):
    def __init__(self, bot, default_order=None):
        # Call the parent initializer with only the expected parameters.
        super().__init__(title="Verify Membership")
        self.bot = bot
        self.order_input = discord.ui.TextInput(
            label="Order ID",
            placeholder="Enter your order ID number here",
            default=default_order if default_order else ""
        )
        self.add_item(self.order_input)

    async def on_submit(self, interaction: discord.Interaction):
        # (Your existing on_submit logic remains unchanged)
        raw_order_id = self.order_input.value.strip()
        if not raw_order_id:
            return await interaction.response.send_message(
                "You must enter an Order ID.", ephemeral=True
            )
        if raw_order_id.startswith("#"):
            raw_order_id = raw_order_id[1:].strip()
        if not raw_order_id.isdigit():
            return await interaction.response.send_message(
                "Invalid Order ID. Please enter a numeric Order ID (e.g. 123456 or #123456).",
                ephemeral=True
            )
        order_id = raw_order_id

        # Check if the order has already been redeemed
        redeemed_orders = load_redeemed_orders()
        if order_id in redeemed_orders:
            return await interaction.response.send_message(
                "This order has already been redeemed.", ephemeral=True
            )

        # Call the WooCommerce API to retrieve order details
        full_url = f"{wc_url}{order_id}"
        response_data = await call_woocommerce_api(full_url)
        if not response_data:
            return await interaction.response.send_message(
                "Invalid order number or unable to retrieve order details.",
                ephemeral=True
            )

        order_data = response_data
        order_status = order_data.get("status")
        order_date_str = order_data.get("date_created")
        membership_prefix = "ECS Membership 20"

        # Check if this is a pub league order first
        pub_league_found = any(
            "ECS Pub League" in item.get("name", "")
            for item in order_data.get("line_items", [])
        )
        if pub_league_found:
            return await interaction.response.send_message(
                "This appears to be a **Pub League** order, not an ECS membership order.\n\n"
                "For Pub League registration, please log into the **Player Portal** at "
                "https://portal.ecsfc.com with your same Discord account.\n\n"
                "The `/verify` command is only for **ECS Membership** verification.",
                ephemeral=True
            )

        # Verify that the order contains the required membership item
        membership_found = any(
            membership_prefix in item.get("name", "")
            for item in order_data.get("line_items", [])
        )
        if not membership_found:
            return await interaction.response.send_message(
                "The order does not contain the required ECS Membership item.",
                ephemeral=True
            )

        # Convert the order date string to a datetime object safely
        try:
            order_date = datetime.fromisoformat(order_date_str)
        except Exception:
            return await interaction.response.send_message(
                "Received an invalid order date format from the API.",
                ephemeral=True
            )

        # Ensure the order is valid for the current membership period
        current_year = datetime.now().year
        cutoff_date = datetime(current_year - 1, 12, 1)
        if order_date < cutoff_date:
            return await interaction.response.send_message(
                "This order is not valid for the current membership period.",
                ephemeral=True
            )

        # Verify that the order status qualifies for redemption
        if order_status not in ["processing", "completed"]:
            return await interaction.response.send_message(
                "Invalid order number or order status not eligible.",
                ephemeral=True
            )

        # Mark the order as redeemed and assign the membership role
        redeemed_orders[order_id] = str(interaction.user.id)
        save_redeemed_orders(redeemed_orders)
        current_membership_role = load_current_role()
        role = discord.utils.get(interaction.guild.roles, name=current_membership_role)

        if role:
            try:
                await interaction.user.add_roles(role)
            except Exception as e:
                return await interaction.response.send_message(
                    f"Error assigning role: {str(e)}", ephemeral=True
                )
            return await interaction.response.send_message(
                "Thank you for validating your ECS membership!", ephemeral=True
            )
        else:
            return await interaction.response.send_message(
                f"Role '{current_membership_role}' not found.", ephemeral=True
            )

class CheckOrderModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="Check Order")
        self.bot = bot
        self.add_item(
            discord.ui.TextInput(
                label="Order ID", placeholder="Enter the order ID number"
            )
        )

    async def on_submit(self, interaction: discord.Interaction):
        order_id = self.children[0].value.strip()
        if order_id.startswith("#"):
            order_id = order_id[1:]

        full_url = f"{wc_url}{order_id}"
        response_data = await call_woocommerce_api(full_url)

        if response_data:
            order_status = response_data["status"]
            order_date_str = response_data["date_created"]
            order_date = datetime.fromisoformat(order_date_str)
            membership_prefix = "ECS Membership 20"
            membership_found = any(
                membership_prefix in item["name"]
                for item in response_data.get("line_items", [])
            )

            current_year = datetime.now().year
            cutoff_date = datetime(current_year - 1, 12, 1)

            if order_date < cutoff_date:
                response_message = "Membership expired."
            elif not membership_found:
                response_message = (
                    "The order does not contain the required ECS Membership item."
                )
            elif order_status in ["processing", "completed"]:
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
        await interaction.response.send_message(
            "Do you want to clear the redeemed orders database for the new season?",
            view=view,
            ephemeral=True,
        )


class ConfirmResetView(discord.ui.View):
    def __init__(self, bot, role):
        super().__init__()
        self.bot = bot
        self.redeemed_orders = load_redeemed_orders()
        self.save_redeemed_orders = save_redeemed_orders
        self.role = role

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user and interaction.user.guild_permissions.administrator

    @discord.ui.button(
        label="Yes, reset", style=discord.ButtonStyle.green, custom_id="confirm_reset"
    )
    async def confirm_reset(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.redeemed_orders.clear()
        self.save_redeemed_orders(self.redeemed_orders)
        await interaction.response.defer()
        await interaction.followup.send(
            f"Order redemption history cleared. New season started with role {self.role}.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="No, keep data", style=discord.ButtonStyle.red, custom_id="cancel_reset"
    )
    async def cancel_reset(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        await interaction.followup.send(
            f"Database not cleared. New season started with role {self.role}",
            ephemeral=True,
        )