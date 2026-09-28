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
import re
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
    extract_subgroup_designation_from_line_item,
    find_customer_info_in_order, 
    extract_base_product_title, 
    extract_variation_detail,
    find_membership_in_order,
    find_membership_item_in_order,
    find_membership_plan_for_year,
    find_subgroup_in_order,
    normalize_string,
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

# init_subgroups
# This function pulls the subgroup items from the API and creates a list of the name and item ID
# Returns list of name and item id for the standalone subgroup products.
# refactor from the hardcoded initialization of subgroup list
async def init_subgroups():
    base_wc_url = wc_url.replace("/orders/", "/")
    category_url = f"{base_wc_url}products/categories?per_page=100"
    categories = await call_woocommerce_api(category_url)
    if not categories:
        logger.error("Could not fetch WooCommerce product categories.")
        return []

    subgroup_category_id = None
    for category in categories:
        if category.get("name", "").lower() == "subgroup":
            subgroup_category_id = category
            break
    
    if subgroup_category_id is None:
        logger.error("Subgroup category not found in WooCommerce.")
        return []
    
    product_url = f"{base_wc_url}products?category={subgroup_category_id['id']}&per_page=100"
    products = await call_woocommerce_api(product_url)
    if not products:
        return []

    subgroup_list = []
    for product in products:
        subgroup_list.append({
            "name": product.get("name", ""),
            "name_normalized": normalize_string(product.get("name", "")),
            "id": product.get("id", "")
        })
    return subgroup_list


async def get_customers_by_ids(customer_url, customer_ids, batch_size=100):
    customer_ids = [str(customer_id) for customer_id in customer_ids if str(customer_id) not in ("", "Unknown")]
    customers = {}

    for start in range(0, len(customer_ids), batch_size):
        batch = customer_ids[start:start + batch_size]
        response = await call_woocommerce_api(
            customer_url,
            params={"include": ",".join(batch), "per_page": len(batch)},
        )
        for customer in response or []:
            customers[str(customer.get("id", ""))] = customer

        if start + batch_size < len(customer_ids):
            await asyncio.sleep(1)

    return customers


async def find_member_id_from_customer_product(customer_id, product_name):
    """
    Checks if the customer has a membership associated with the specified product_name.

    Returns:
        member_id if criteria are met.
        None otherwise.
    """
    wc_base_url = wc_url.replace("/orders/", "/memberships/members/")
    api_url = f"{wc_base_url}?customer={customer_id}"
    
    memberships = await call_woocommerce_api(api_url)
    if memberships:
        for membership in memberships:
            if membership.get('plan_name', '').strip().lower() == product_name.strip().lower():
                logger.debug(f"Found member ID {membership.get('id', 'Unknown')} for customer ID {customer_id} and product name {product_name}.")
                return membership.get('id', None)

    logger.debug(f"No membership found for customer ID {customer_id} and product name {product_name}.")
    return None


async def update_customer_profile_field(member_id, field_name, field_value):
    """
    Updates a customer profile field in WooCommerce using the API.

    Args:
        member_id: The ID of the member to update.
        field_name: The name of the profile field to update.
        field_value: The value to set for the profile field.
    
    Returns:
        True if the update was successful, False otherwise.
    """
    try:
        # Construct the API endpoint URL for updating the customer profile field
        wc_base_url = wc_url.replace("/orders/", "/memberships/members/")
        api_url = f"{wc_base_url}{member_id}"
        
        # Prepare the payload for the API request
        payload = {
            "profile_fields": [
                {
                    "slug": field_name,
                    "value": field_value
                }
            ]
        }
        
        # Make the API request to update the customer profile field
        response = await call_woocommerce_api(api_url, method="PUT", data=json.dumps(payload))
        
        # The API returns the updated membership object on success, not a success flag
        if response and response.get("id"):
            logger.info(f"Successfully updated profile field '{field_name}' for member ID {member_id}.")
            return True
        else:
            logger.error(f"Failed to update profile field '{field_name}' for member ID {member_id}. Response: {response}")
            return False
    except Exception as e:
        logger.exception(f"Exception occurred while updating profile field '{field_name}' for member ID {member_id}: {str(e)}")
        return False


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
        if not await has_required_wg_role(
            interaction, ["WG: Travel", "WG: Home Tickets"]
        ):
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
        iteration = 1
        message_content = ""
        category_id = None

        while iteration <= 2:
            if iteration == 1:
                category_id = home_tickets_category
                message_content = "🏠 **Home Tickets:** (sold, remaining)\n"
            elif iteration == 2:
                category_id = away_tickets_category
                message_content += "\n🚗 **Away Tickets:** (sold, remaining)\n"

            tickets = []
            tickets_url = wc_url.replace("orders/", f"products?category={category_id}&per_page=50&search={current_year}")
            tickets = await call_woocommerce_api(tickets_url)

            if tickets is not None:
                try:
                    tickets.sort(
                        key=lambda x: parser.parse(x['name'], fuzzy=True)
                        if 'name' in x else datetime.datetime.min
                    )
                except ValueError:
                    # Skip sorting if any invalid date is encountered
                    pass

            if tickets:
                for product in tickets:
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
                message_content += ("No tickets found.\n")

            iteration += 1

        await interaction.followup.send(message_content[:2000], ephemeral=True)
        
    @app_commands.command(
        name="getorderinfo", description="Retrieve order details for a specific product"
    )
    @app_commands.describe(product_title="Title of the product")
    @app_commands.guilds(discord.Object(id=server_id))
    async def get_product_orders(self, interaction: discord.Interaction, product_title: str):
        if debug: print(f"[DEBUG] Received command for product_title: {product_title}")

        if not await has_required_wg_role(
            interaction, ["WG: Travel", "WG: Home Tickets"]
        ):
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
        if not await has_required_wg_role(
            interaction, ["WG: Travel", "WG: Home Tickets"]
        ):
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
    @app_commands.describe(
        year="The year for which to generate the CSV list (e.g., 2024, 2025)"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def subgrouplist(self, interaction: discord.Interaction, year: int):
        try:
            if not await has_required_wg_role(
                interaction, ["ECS Leadership"] 
            ):
                await interaction.response.send_message(
                    "You do not have the necessary permissions.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True, thinking=True)

            base_wc_url = wc_url.replace("/orders/", "/memberships/")
            plans_url = f"{base_wc_url}plans?per_page=100"
            plans = await call_woocommerce_api(plans_url)
            plan_id = await find_membership_plan_for_year(plans, year)
            
            if not plan_id:
                await interaction.followup.send(
                    f"A membership plan for the year {year} could not be found.", ephemeral=True
                )
                return

            page = 1
            per_page = 100
            member_info_by_subgroup = defaultdict(list)
            #subgroup_list = await init_subgroups()

            # Continue paging until no orders are returned.
            while True:
                # changing to use the membership REST API - https://godaddy-wordpress.github.io/woocommerce-memberships-rest-api-docs/#the-user-membership

                membership_url = f"{base_wc_url}members?plan={plan_id}&page={page}&per_page={per_page}"
                fetched_memberships = await call_woocommerce_api(membership_url)

                if not fetched_memberships:
                    logger.info(f"No memberships fetched from page {page}. Ending pagination.")
                    break

                # Process each membership.
                for membership in fetched_memberships:
                    subgroup_designation = ""
                    customer_id = str(membership.get("customer_id", "Unknown"))
                    profile_fields = membership.get("profile_fields", {})
                    for field in profile_fields:
                        if field.get("name") == "ECS Subgroup":
                            subgroup_designation = field.get("value", "").strip()
                            break

                    if subgroup_designation != "":
                        logger.info(f"On page {page} found subgroup {subgroup_designation} for customer {customer_id}.")
                        member_info_by_subgroup[subgroup_designation].append({
                            "customer_id": customer_id,
                            "first_name": "N/A",
                            "last_name": "N/A",
                            "email": "N/A"
                        })

                # If fewer memberships than requested are returned, we assume it's the last page.
                if len(fetched_memberships) < per_page:
                    logger.info(f"Fetched {len(fetched_memberships)} memberships on page {page}. Assuming this is the last page.")
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

            base_wc_url = wc_url.replace("/orders/", "/customers")

            # Collect all unique customer IDs across all subgroups
            all_customer_ids = set()
            for subgroup, member_list in member_info_by_subgroup.items():
                for member_dict in member_list:
                    all_customer_ids.add(member_dict["customer_id"])
            
            logger.info(f"Collected all unique customer IDs: {len(all_customer_ids)} customers to query for details.")

            customer_details = await get_customers_by_ids(base_wc_url, all_customer_ids)
            for member_list in member_info_by_subgroup.values():
                for member_dict in member_list:
                    customer = customer_details.get(member_dict["customer_id"])
                    if customer:
                        member_dict["first_name"] = customer.get("first_name", "N/A")
                        member_dict["last_name"] = customer.get("last_name", "N/A")
                        member_dict["email"] = customer.get("email", "N/A")

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

    #
    # reviewmemberships
    # examine purchases for the prior seven days and identify any membership purchases not attached to a customer
    # record bearing the appropriate membership.
    #
    @app_commands.command(
        name="reviewmemberships",
        description="Create a list of membership purchases requiring manual review for missing membership records"
    )
    @app_commands.describe(
        days="Number of days to go back (default = 7)"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def reviewmemberships(self, interaction: discord.Interaction, days: int = 7):
        try:
            if not await has_required_wg_role(
                interaction, ["ECS Leadership", "mod"]
            ):
                await interaction.response.send_message(
                    "You do not have the necessary permissions.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True, thinking=True)

            start = datetime.datetime.now()-datetime.timedelta(days=days)

            start_of_time = start.strftime("%Y-%m-%dT%H:%M:%S")

            page = 1
            per_page = 100
            membership_purchases = defaultdict(list)

            # Continue paging until no orders are returned.
            while True:
                orders_url = (
                    f"{wc_url}?order=desc&page={page}&per_page={per_page}"
                    f"&status=any&after={start_of_time}"
                )
                logger.info(f"Fetching orders from page {page}.")
                fetched_orders = await call_woocommerce_api(orders_url)

                if not fetched_orders:
                    logger.info(f"No orders fetched from page {page}. Ending pagination.")
                    break

                # Process each order.
                for order in fetched_orders:
                    order_id = order.get("id", "Unknown")
                    # find_membership_in_order will return a value if the order contains a membership product but the customer does not have a corresponding membership record.
                    customer_info = await find_membership_in_order(order)
                    if customer_info:
                        membership_purchases[order_id].append((order.get("status", ""), customer_info))

                # If fewer orders than requested are returned, we assume it's the last page.
                if len(fetched_orders) < per_page:
                    logger.info(f"Fetched {len(fetched_orders)} orders on page {page}. Assuming this is the last page.")
                    break

                page += 1
                # Respect API rate limits.
                await asyncio.sleep(1)

            # If no members were found, inform the user.
            if not membership_purchases:
                logger.info("No membersship purchases found matching the criteria.")
                message_content = f"No membership purchases found missing a membership record in the past {days} days."
            else:
                message_content = "**Membership reconciliation:**\n"
                for product in membership_purchases.items():
                    order_url = (
                        f"https://weareecs.com/wp-admin/admin.php?page=wc-orders&action=edit&id={product[0]}"
                    )
                    message_content += (
                        f"Order number **{product[0]}** status (**{product[1][0][0]}**) {order_url}\n"
                    )

            await interaction.followup.send(message_content[:2000], ephemeral=True)

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


    #
    # reviewsubgroups
    # examine purchases for the prior seven days and identify any membership purchases with a disconnected
    # subgroup purchase (i.e., subgroup purchase not attached to a customer record bearing the appropriate subgroup).
    #
    @app_commands.command(
        name="reviewsubgroups",
        description="Create a list of membership purchases requiring manual review for missing subgroup records"
    )
    @app_commands.describe(
        days="Number of days to go back (default = 7)"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def reviewsubgroups(self, interaction: discord.Interaction, days: int = 7):
        try:
            if not await has_required_wg_role(
                interaction, ["ECS Leadership", "mod"]
            ):
                await interaction.response.send_message(
                    "You do not have the necessary permissions.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True, thinking=True)

            start = datetime.datetime.now()-datetime.timedelta(days=days)

            start_of_time = start.strftime("%Y-%m-%dT%H:%M:%S")

            page = 1
            per_page = 100
            subgroup_updates = []
            subgroups = await init_subgroups()

            # Continue paging until no orders are returned.
            while True:
                orders_url = (
                    f"{wc_url}?order=desc&page={page}&per_page={per_page}"
                    f"&status=any&after={start_of_time}"
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
                    result = await find_subgroup_in_order(order, subgroups)
                    if result:
                        customer_id, order_id, product_id, line_item_id, subgroup_designation = result
                        subgroup_updates.append([customer_id, order_id, product_id, line_item_id, subgroup_designation])

                # If fewer orders than requested are returned, we assume it's the last page.
                if len(fetched_orders) < per_page:
                    logger.info(f"Fetched {len(fetched_orders)} orders on page {page}. Assuming this is the last page.")
                    break

                page += 1
                # Respect API rate limits.
                await asyncio.sleep(1)

            # If no eligible purchases were found, inform the user.
            if not subgroup_updates:
                logger.info("No subgroup item purchases found matching the criteria.")
                message_content = f"No subgroup item purchases found in the past {days} days."
            else:
                message_content = "**Subgroup reconciliation:**\n"
                for customer_id, order_id, product_id, line_item_id, subgroup_designation in subgroup_updates:
                    message_content += (
                        f"Line item **{line_item_id}**: customer {customer_id}, order {order_id}, "
                        f"product {product_id}, subgroup {subgroup_designation}\n"
                    )

            await interaction.followup.send(message_content[:2000], ephemeral=True)

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
        if not await has_required_wg_role(
            interaction, ["WG: Travel", "WG: Home Tickets"]
        ):
            await interaction.response.send_message(
                "You do not have the necessary permissions.", ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)

        reset = reset_woo_orders_db() 
        message = f"Orders database reset. Please run updateorders now."
        await interaction.followup.send(message, ephemeral=True)


    @app_commands.command(
        name="proliferate",
        description="Push subgroup information to customer-membership records based on order history"
    )
    @app_commands.describe(
        days="Number of days to go back (default = 7)"
    )
    @app_commands.guilds(discord.Object(id=server_id))
    async def proliferate(self, interaction: discord.Interaction, days: int = 7):
        try:
            if not await has_required_wg_role(
                interaction, ["ECS Leadership", "mod"]
            ):
                await interaction.response.send_message(
                    "You do not have the necessary permissions.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True, thinking=True)

            start = datetime.datetime.now()-datetime.timedelta(days=days)
            start_of_time = start.strftime("%Y-%m-%dT%H:%M:%S")

            page = 1
            per_page = 100

            base_wc_url = wc_url
            processed_any_orders = False

            while True:
                orders_url = f"{base_wc_url}?order=desc&page={page}&per_page={per_page}&after={start_of_time}"
                orders = await call_woocommerce_api(orders_url)

                if not orders:
                    logger.info("No orders fetched. Ending process.")
                    if not processed_any_orders:
                        await interaction.followup.send(
                            "No orders found to process for subgroup proliferation.",
                            ephemeral=True,
                        )
                        return
                    break

                processed_any_orders = True
                for order in orders:
                    membership_product_name = await find_membership_item_in_order(order)
                    if not membership_product_name:
                        continue

                    year_match = re.search(r"\d{4}", membership_product_name)
                    if not year_match:
                        continue
                    year = year_match.group()

                    for line_item in order.get("line_items", []):
                        if line_item.get("name", "") not in (f"ECS Member {year}", f"ECS Membership {year}"):
                            continue

                        subgroup_designation = await extract_subgroup_designation_from_line_item(line_item)
                        if not subgroup_designation:
                            continue

                        customer_id = order.get("customer_id", "Unknown")
                        product_name = line_item.get("name", "")
                        member_id = await find_member_id_from_customer_product(customer_id, product_name)
                        if not member_id:
                            logger.warning(
                                f"No membership record found for customer {customer_id} and product {product_name}."
                            )
                            continue

                        update_success = await update_customer_profile_field(
                            member_id, "ecs-subgroup", subgroup_designation
                        )
                        if update_success:
                            logger.info(
                                f"Updated member {member_id} with subgroup {subgroup_designation}."
                            )
                        else:
                            logger.error(
                                f"Failed to update member {member_id} with subgroup {subgroup_designation}."
                            )

                if len(orders) < per_page:
                    logger.info(f"Fetched {len(orders)} orders on page {page}. Assuming it's the last page.")
                    break

                page += 1
                await asyncio.sleep(1)

            await interaction.followup.send(
                "Subgroup proliferation completed.",
                ephemeral=True,
            )
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

        
async def setup(bot):
    await bot.add_cog(WooCommerceCommands(bot))
