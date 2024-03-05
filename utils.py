# utils.py

from dateutil import parser
import pytz
import json


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


async def find_customer_info_in_order(order, subgroups):
    def search_dict(d, customer_info=None):
        if isinstance(d, dict):
            for key, value in d.items():
                if value in subgroups:
                    customer_info = extract_customer_info(order)
                    return value, customer_info
                elif isinstance(value, (dict, list)):
                    result = search_dict(value, customer_info)
                    if result:
                        return result
        elif isinstance(d, list):
            for item in d:
                result = search_dict(item, customer_info)
                if result:
                    return result
        return None

    return search_dict(order)

def extract_customer_info(order_dict):
    first_name = order_dict.get('billing', {}).get('first_name', '')
    last_name = order_dict.get('billing', {}).get('last_name', '')
    email = order_dict.get('billing', {}).get('email', '')
    return {
        'first_name': first_name,
        'last_name': last_name,
        'email': email
    }