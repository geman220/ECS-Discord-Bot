# utils.py

from datetime import datetime
import pytz
import json


def convert_to_pst(utc_datetime_str):
    utc_datetime = datetime.fromisoformat(utc_datetime_str.replace("Z", "+00:00"))
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
