# utils.py

from dateutil import parser
import requests
import os
import datetime
import pytz
import re
import json
import logging
from api_helpers import call_woocommerce_api, wc_url

logger = logging.getLogger(__name__)

API_BASE_URL = os.getenv("WEBUI_API_URL")

def convert_to_pst(utc_datetime):
    if not isinstance(utc_datetime, str):
        utc_datetime = str(utc_datetime)

    utc_datetime = parser.parse(utc_datetime)

    if utc_datetime.tzinfo is None or utc_datetime.tzinfo.utcoffset(utc_datetime) is None:
        utc_datetime = utc_datetime.replace(tzinfo=pytz.utc)

    pst_timezone = pytz.timezone("America/Los_Angeles")
    return utc_datetime.astimezone(pst_timezone)


def read_json_file(file_path, default_value):
    try:
        with open(file_path, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_value


def write_json_file(file_path, data):
    with open(file_path, "w") as file:
        json.dump(data, file)


def get_airport_code_for_team(team_name, team_airports):
    for airport_code, teams in team_airports.items():
        if team_name in teams:
            return airport_code
    return None


def load_json_data(file_name, default_value):
    return read_json_file(file_name, default_value)


def save_json_data(file_name, data):
    write_json_file(file_name, data)


def extract_designation(value):
    """
    Recursively extracts string values from nested dictionaries or lists.
    
    Args:
        value: The value to extract from (can be dict, list, or str).
    
    Returns:
        A concatenated string of all extracted string values.
    """
    if isinstance(value, str):
        return value.strip()
    elif isinstance(value, dict):
        extracted = []
        for v in value.values():
            extracted_designation = extract_designation(v)
            if extracted_designation:
                extracted.append(extracted_designation)
        return ' '.join(extracted).strip()
    elif isinstance(value, list):
        extracted = [extract_designation(item) for item in value]
        return ' '.join(filter(None, extracted)).strip()
    else:
        # For other data types, convert to string
        return str(value).strip()


def normalize_string(s):
    """
    Normalizes a string by converting it to lowercase, stripping leading/trailing spaces,
    and replacing multiple spaces with a single space.
    """
    if not isinstance(s, str):
        return ''
    s = s.lower().strip()
    s = re.sub(r'\s+', ' ', s)
    return s

def extract_customer_info(order_dict):
    first_name = order_dict.get('billing', {}).get('first_name', '')
    last_name = order_dict.get('billing', {}).get('last_name', '')
    email = order_dict.get('billing', {}).get('email', '')
    customer_id = order_dict.get('customer_id', '')
    return {
        'first_name': first_name,
        'last_name': last_name,
        'email': email,
        'customer_id': customer_id
    }

async def find_customer_info_in_order(order, subgroups, membership_year=None):
    """
    Checks if the order contains:
    1. An ECS Membership for the specified membership_year (defaults to current year if not provided).
    2. One or more Subgroup designations from the specified subgroups list.

    Returns:
        Tuple of (list_of_subgroups, customer_info) if criteria are met.
        None otherwise.
    """

    if not await find_membership_item_in_order(order, membership_year):
        return None

    subgroup_designations = []

    for item in order.get('line_items', []):
        designation = await extract_subgroup_designation_from_line_item(item)
        if designation:
            subgroup_designations.append(designation)

    if not subgroup_designations:
        logger.debug(f"Order ID {order.get('id', 'Unknown')} has no subgroup designation.")
        return None

    normalized_designations = [normalize_string(desig) for desig in subgroup_designations]

    matched_subgroups = {
        subgroup
        for subgroup in subgroups
        if any(normalize_string(subgroup) in designation for designation in normalized_designations)
    }

    if not matched_subgroups:
        for desig in subgroup_designations:
            logger.debug(f"Order ID {order.get('id', 'Unknown')} subgroup designation '{desig}' not in predefined list.")
        return None

    customer_info = extract_customer_info(order)
    return list(matched_subgroups), customer_info


async def find_membership_plan_for_year(plans, year):
    membership_year_str = str(year)
    pattern = re.compile(rf"ecs member(?:ship)?(?:\s+\w+)*\s+{membership_year_str}\b")

    for plan in plans:
        plan_name = plan.get('name', '')
        plan_name_norm = normalize_string(plan_name)
        if pattern.search(plan_name_norm):
            logger.debug(f"Found membership plan for year {year}: {plan_name} (ID: {plan.get('id', 'Unknown')})")
            return plan.get('id', None)

    logger.debug(f"No membership plan found for year {year}.")
    return None


async def extract_subgroup_designation_from_line_item(line_item):
    """
    Checks if the line_item contains:
    1. A metadata key of 'subgroup designation' and extracts the subgroup designation value.

    Returns:
        Subgroup designation string if criteria are met.
        None otherwise.
    """

    item_meta_data = line_item.get('meta_data', [])
    for meta in item_meta_data:
        key = normalize_string(meta.get('key', ''))
        value = meta.get('value', '')
        logger.debug(f"Processing Line Item ID: {line_item.get('id', 'Unknown')} - Meta Key: {meta.get('key', '')}, Meta Value: {value} (type: {type(value)})")
        if key == 'subgroup designation':
            designation = extract_designation(value)
            if designation:
                logger.debug(f"Extracted Subgroup Designation: {designation} (type: {type(designation)})")
                return designation

    logger.debug(f"Line Item ID {line_item.get('id', 'Unknown')} has no subgroup designation.")
    return None


async def find_membership_item_in_order(order, membership_year=None):
    """
    Checks if the order contains:
    1. An ECS Membership for the specified membership_year (defaults to current year if not provided).

    Returns:
        product_name if criteria are met.
        None otherwise.
    """
    if membership_year is None:
        pattern = re.compile(r"ecs member(?:ship)?(?:\s+\w+)*\s+\d{4}\b")
    else:
        membership_year_str = str(membership_year)
        pattern = re.compile(rf"ecs member(?:ship)?(?:\s+\w+)*\s+{membership_year_str}\b")

    line_items = order.get('line_items', [])
    for item in line_items:
        product_name = item.get('name', '')
        product_name_norm = normalize_string(product_name)
        if pattern.search(product_name_norm):
            logger.debug(f"Order ID {order.get('id', 'Unknown')} has ECS Membership: {product_name} at line item ID: {item.get('id', 'Unknown')}")
            return product_name

    if membership_year is None:
        logger.debug(f"Order ID {order.get('id', 'Unknown')} does not have an ECS Membership item.")
    else:
        logger.debug(f"Order ID {order.get('id', 'Unknown')} does not have ECS Membership for {membership_year}.")
    return None


async def find_subgroup_item_in_order(order, subgroups):
    """
    Checks if the order contains:
    1. A subgroup designation from the specified subgroups list as a standalone item

    Returns:
        line_item_id, subgroup designation if criteria are met.
        None otherwise.
    """

    line_items = order.get('line_items', [])
    for item in line_items:
        product_name = item.get('name', '')
        product_name_norm = normalize_string(product_name)

        for subgroup in subgroups:
            subgroup_name_norm = normalize_string(subgroup["name"])
            if subgroup_name_norm == product_name_norm:
                logger.debug(f"Order ID {order.get('id', 'Unknown')} has subgroup designation in product name: {item.get('name', '')} at line item ID: {item.get('id', 'Unknown')}")
                return item.get('id', 'Unknown'), extract_designation(item.get('name', ''))
                # Found a matching subgroup designation

    return None


async def find_membership_in_order(order, membership_year=None):
    """
    Checks if the order contains:
    1. An ECS Membership for the specified membership_year (defaults to current year if not provided).

    Returns:
        Tuple of (customer_info) if the membership item is not associated to a membership grant.
        None otherwise.
    """

    if not await find_membership_item_in_order(order, membership_year):
        return None

    for order_meta in order.get('meta_data', []):
        key = normalize_string(order_meta.get('key', ''))
        if key == "_wc_memberships_access_granted":
            logger.debug(f"Order ID {order.get('id', 'Unknown')} has membership access granted meta key.")
            return None

    customer_info = extract_customer_info(order)
    return customer_info


async def find_subgroup_in_order(order, subgroups):
    """
    Checks if the order contains:
    1. A subgroup designation from the specified subgroups list as a standalone item

    Returns:
        Tuple of (customer_id, order_id, subgroup_product_id, subgroup_line_item_id, subgroup designation).
        None otherwise.
    """
    result = await find_subgroup_item_in_order(order, subgroups)
    if not result:
        return None
    
    # a disconnected subgoup item found; now look for a membership item in the order to confirm it's a valid subgroup purchase
    membership_product_name = await find_membership_item_in_order(order)
    if not membership_product_name:
        logger.debug(f"Order ID {order.get('id', 'Unknown')} has subgroup designation but no membership item.")
        return None

    subgroup_line_item_id, subgroup_designation = result
    subgroup_line_item = next(
        item for item in order.get('line_items', [])
        if item.get('id') == subgroup_line_item_id
    )
    customer_id = order.get('customer_id', 'Unknown')
    year_match = re.search(r"\d{4}", membership_product_name)
    if customer_id not in ("", "Unknown", None, 0, "0") and year_match:
        memberships_url = f"{wc_url.replace('/orders/', '/memberships/members/')}?customer={customer_id}"
        memberships = await call_woocommerce_api(memberships_url)
        if memberships:
            membership_year = year_match.group()
            plan_names = {
                normalize_string(f"ECS Member {membership_year}"),
                normalize_string(f"ECS Membership {membership_year}"),
            }
            matching_membership = next(
                (
                    membership for membership in memberships
                    if normalize_string(membership.get("plan_name", "")) in plan_names
                ),
                None,
            )
            if matching_membership:
                existing_subgroup = next(
                    (
                        extract_designation(field.get("value", ""))
                        for field in matching_membership.get("profile_fields", [])
                        if field.get("slug") == "ecs-subgroup"
                        or normalize_string(field.get("name", "")) == "ecs subgroup"
                    ),
                    "",
                )
                if normalize_string(existing_subgroup) == normalize_string(subgroup_designation):
                    logger.debug(
                        f"Order ID {order.get('id', 'Unknown')} member already has subgroup '{existing_subgroup}'."
                    )
                    return None
    return (
        customer_id,
        order.get('id', 'Unknown'),
        subgroup_line_item.get('product_id', 'Unknown'),
        subgroup_line_item_id,
        subgroup_designation,
    )


def extract_base_product_title(full_title: str) -> str:
    base_title = full_title.split(" - ")[0]
    return base_title

def extract_variation_detail(order: dict) -> str:
    variation_detail = order.get('product_variation', '')
    return variation_detail

def get_correct_predictions(match_id):
    """
    Fetch predictions for a given match from the Flask API and return a list of Discord user IDs 
    whose predictions were correct.
    """
    try:
        api_url = f"{API_BASE_URL}/predictions/{match_id}/correct"
        logger.info(f"Fetching correct predictions from: {api_url}")
        
        response = requests.get(api_url)
        if response.status_code == 200:
            data = response.json()
            correct_predictions = data.get('correct_predictions', [])
            logger.info(f"Found {len(correct_predictions)} correct predictions for match {match_id}")
            return correct_predictions
        else:
            logger.error(f"Error fetching correct predictions: Status {response.status_code}, Response: {response.text}")
            return []
    except Exception as e:
        logger.exception(f"Exception fetching correct predictions for match {match_id}: {str(e)}")
        return []