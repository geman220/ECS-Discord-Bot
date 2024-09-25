# utils.py

from dateutil import parser
import datetime
import pytz
import re
import json
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
    return {
        'first_name': first_name,
        'last_name': last_name,
        'email': email
    }

async def find_customer_info_in_order(order, subgroups):
    """
    Checks if the order contains:
    1. An ECS Membership for the current year.
    2. One or more Subgroup designations from the specified subgroups list.
    
    Returns:
        Tuple of (list_of_subgroups, customer_info) if criteria are met.
        None otherwise.
    """
    current_year = datetime.datetime.now().year
    ecs_membership_keyword = f"ECS Membership {current_year}"

    # Normalize ECS Membership keyword
    ecs_membership_keyword_norm = normalize_string(ecs_membership_keyword)

    # Flag to check for ECS Membership
    has_ecs_membership = False

    # Variable to store the subgroup designation(s)
    subgroup_designations = []

    # Normalize predefined subgroups
    normalized_subgroups = [normalize_string(s) for s in subgroups]

    # Check line_items for ECS Membership (case-insensitive, partial match)
    line_items = order.get('line_items', [])
    for item in line_items:
        product_name = item.get('name', '')
        product_name_norm = normalize_string(product_name)
        if ecs_membership_keyword_norm in product_name_norm:
            has_ecs_membership = True
            logger.debug(f"Order ID {order.get('id', 'Unknown')} has ECS Membership: {product_name}")
            break  # Found the required membership

    if not has_ecs_membership:
        logger.debug(f"Order ID {order.get('id', 'Unknown')} does not have ECS Membership for {current_year}.")
        return None  # Order doesn't contain the required ECS Membership

    # Extract subgroup designations from line items' meta_data
    for item in line_items:
        item_meta_data = item.get('meta_data', [])
        logger.debug(f"Order ID {order.get('id', 'Unknown')} - Processing Line Item ID: {item.get('id', 'Unknown')}")
        for meta in item_meta_data:
            key = normalize_string(meta.get('key', ''))
            value = meta.get('value', '')
            logger.debug(f"Order ID {order.get('id', 'Unknown')} - Line Item Meta Key: {meta.get('key', '')}, Meta Value: {value} (type: {type(value)})")
            if key == 'subgroup designation':
                designation = extract_designation(value)
                if designation:
                    subgroup_designations.append(designation)
                    logger.debug(f"Order ID {order.get('id', 'Unknown')} - Extracted Subgroup Designation: {designation} (type: {type(designation)})")

    if not subgroup_designations:
        logger.debug(f"Order ID {order.get('id', 'Unknown')} has no subgroup designation.")
        return None  # No subgroup designation found

    # Normalize subgroup designations for matching
    normalized_designations = [normalize_string(desig) for desig in subgroup_designations]

    # Find all matching subgroups
    matched_subgroups = set()
    for subgroup_norm, original_subgroup in zip(normalized_subgroups, subgroups):
        for desig_norm in normalized_designations:
            if subgroup_norm in desig_norm:
                matched_subgroups.add(original_subgroup)
                logger.debug(f"Order ID {order.get('id', 'Unknown')} matched subgroup: {original_subgroup}")

    if not matched_subgroups:
        for desig in subgroup_designations:
            logger.debug(f"Order ID {order.get('id', 'Unknown')} subgroup designation '{desig}' not in predefined list.")
        return None  # No subgroup designation matched

    # Extract customer information once
    customer_info = extract_customer_info(order)

    # Convert set to list before returning
    return list(matched_subgroups), customer_info

def extract_base_product_title(full_title: str) -> str:
    base_title = full_title.split(" - ")[0]
    return base_title

def extract_variation_detail(order: dict) -> str:
    variation_detail = order.get('product_variation', '')
    return variation_detail