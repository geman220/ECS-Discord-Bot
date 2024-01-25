# Common.py

import discord
import json
from datetime import datetime, timedelta
from config import BOT_CONFIG
from utils import load_json_data, save_json_data, convert_to_pst, get_airport_code_for_team
from database import initialize_db, load_match_threads, initialize_woo_orders_db
from api_helpers import fetch_openweather_data, fetch_serpapi_flight_data

bot_token = BOT_CONFIG['bot_token']
team_name = BOT_CONFIG['team_name']
team_id = BOT_CONFIG['team_id']
venue_long = BOT_CONFIG['venue_long']
venue_lat = BOT_CONFIG['venue_lat']
flask_url = BOT_CONFIG['flask_url']
flask_token = BOT_CONFIG['flask_token']
discord_admin_role = BOT_CONFIG['discord_admin_role']
dev_id = BOT_CONFIG['dev_id']
server_id = BOT_CONFIG['server_id']
serpapi_api = BOT_CONFIG['serpapi_api']
wp_username = BOT_CONFIG['wp_username']
wp_app_password = BOT_CONFIG['wp_app_password']
bot_version = BOT_CONFIG['bot_version']

try:
    initialize_db()
    initialize_woo_orders_db()
    match_thread_map = load_match_threads()
except Exception as e:
    print(f"Error during initialization: {e}")

def load_current_role():
    role_data = load_json_data('current_role.json', default_value={"current_role": "ECS Membership 202x"})
    return role_data['current_role']

def save_current_role(role_name):
    save_json_data('current_role.json', {'current_role': role_name})

def load_redeemed_orders():
    return load_json_data('redeemed_orders.json', default_value={})

def save_redeemed_orders(redeemed_orders):
    save_json_data('redeemed_orders.json', redeemed_orders)

def load_team_airports():
    return load_json_data('team_airports.json', default_value={})

def load_match_dates():
    return load_json_data('match_dates.json', default_value=[])

def load_team_schedule():
    return load_json_data('team_schedule.json', default_value=[])

team_airports = load_team_airports()

async def is_admin_or_owner(interaction: discord.Interaction):
    return str(interaction.user.id) == dev_id or any(role.name == discord_admin_role for role in interaction.user.roles)

async def has_admin_role(interaction: discord.Interaction):
    return any(role.name == discord_admin_role for role in interaction.user.roles)

async def has_required_wg_role(interaction: discord.Interaction):
    required_roles = ["WG: Travel", "WG: Home Tickets", discord_admin_role]
    return any(role.name in required_roles for role in interaction.user.roles)

def format_stat_name(stat_name):
    name_mappings = {
        "gamesPlayed": "Games Played",
        "losses": "Losses",
        "pointDifferential": "Point Differential",
        "points": "Points",
        "pointsAgainst": "Points Against",
        "pointsFor": "Points For",
        "streak": "Streak",
        "ties": "Ties",
        "wins": "Wins",
        "awayGamesPlayed": "Away Games Played",
        "awayLosses": "Away Losses",
        "awayPointsAgainst": "Away Points Against",
        "awayPointsFor": "Away Points For",
        "awayTies": "Away Ties",
        "awayWins": "Away Wins",
        "deductions": "Deductions",
        "homeGamesPlayed": "Home Games Played",
        "homeLosses": "Home Losses",
        "homePointsAgainst": "Home Points Against",
        "homePointsFor": "Home Points For",
        "homeTies": "Home Ties",
        "homeWins": "Home Wins",
        "ppg": "Points Per Game",
        "rank": "Rank",
        "rankChange": "Rank Change"
    }
    return name_mappings.get(stat_name, stat_name)
  
async def get_weather_forecast(interaction, date_time_utc, latitude, longitude):
    weather_data = await fetch_openweather_data(interaction, latitude, longitude, date_time_utc)
    
    if weather_data:
        for forecast in weather_data.get('list', []):
            forecast_date = datetime.fromtimestamp(forecast['dt']).date()

            if forecast_date == datetime.fromisoformat(date_time_utc).date():
                weather = forecast['weather'][0]['description']
                temp = forecast['main']['temp']
                return f"Weather: {weather}, Temperature: {temp} F"

        return "Weather forecast not available for the selected date."
    else:
        return "Unable to fetch weather information."
    
async def create_event_if_necessary(interaction, match_info):
    event_start_time_pst = convert_to_pst(match_info['date_time']) - timedelta(hours=1)
    existing_events = await interaction.guild.fetch_scheduled_events()
    event_exists = any(
        event.name == "March to the Match" and 
        event.start_time == event_start_time_pst for event in existing_events
    )

    if event_exists:
        return "An event for this match has already been scheduled."

    try:
        await interaction.guild.create_scheduled_event(
            name="March to the Match",
            start_time=event_start_time_pst,
            end_time=event_start_time_pst + timedelta(hours=2),
            description=f"March to the Match for {match_info['name']}",
            location="117 S Washington St, Seattle, WA 98104",
            entity_type=discord.EntityType.external,
            privacy_level=discord.PrivacyLevel.guild_only
        )
        event_start_str = event_start_time_pst.strftime('%m/%d/%Y %I:%M %p PST')
        return f"Event created: 'March to the Match' starting at {event_start_str}."
    except Exception as e:
        return f"Failed to create event: {e}"
    
async def check_existing_threads(interaction, thread_name, channel_name):
    channel = discord.utils.get(interaction.guild.channels, name=channel_name)
    if channel and isinstance(channel, discord.ForumChannel):
        existing_threads = channel.threads
        for thread in existing_threads:
            if thread.name == thread_name:
                return True
    return False

async def generate_flight_search_url(interaction, departure_airport, team_name, outbound_date, return_date):
    arrival_airport = get_airport_code_for_team(team_name, team_airports)
    if not arrival_airport:
        return "Airport for the team not found."

    json_response = await fetch_serpapi_flight_data(interaction, departure_airport, arrival_airport, outbound_date, return_date)
    if not json_response:
        return "Failed to fetch flight data."

    return parse_flight_data(json_response)

def parse_flight_data(json_response):
    if not json_response.get("best_flights"):
        return "No flight information available."

    best_flight = json_response["best_flights"][0]
    flight_info = best_flight["flights"][0]

    price = best_flight.get("price", "N/A")
    airline = flight_info.get("airline", "N/A")
    departure_time = flight_info["departure_airport"].get("time", "N/A")
    arrival_time = flight_info["arrival_airport"].get("time", "N/A")
    current_date = datetime.now().strftime("%m/%d/%y")

    message = (
        f"**Best Flight Price**: ${price} (as of {current_date})\n"
        f"**Airline**: {airline}\n"
        f"**Departure Time**: {departure_time}\n"
        f"**Arrival Time**: {arrival_time}\n"
        f"More details and options: [Google Flights]({json_response['search_metadata']['google_flights_url']})"
    )
    return message

async def prepare_starter_message(match_info, date_time_pst_formatted, team_logo, weather_forecast, thread_name):
    starter_message = (
        f"**Upcoming Match: {match_info['name']}**\n"
        f"Date and Time: {date_time_pst_formatted}\n"
        f"Venue: {match_info['venue']}\n"
        f"**Match Details**\n"
        f"More Info: [Match Summary](<{match_info['match_summary_link']}), [Statistics](<{match_info['match_stats_link']}>)\n"
        f"**Broadcast**: AppleTV\n"
    )

    embed = discord.Embed(title=thread_name, description=starter_message, color=0x1a75ff)
    embed.set_image(url=match_info['team_logo'])
    return starter_message, embed

async def prepare_starter_message_away(interaction, match_info, date_time_pst_formatted, thread_name, ticket_link):
    match_date = datetime.strptime(date_time_pst_formatted, '%m/%d/%Y %I:%M %p PST').date()
    outbound_date = match_date - timedelta(days=1)
    return_date = match_date + timedelta(days=1)

    flight_response = await generate_flight_search_url(interaction, "SEA", match_info['opponent'], outbound_date, return_date)
    if isinstance(flight_response, str):
        try:
            flight_response = json.loads(flight_response)
            flight_message = parse_flight_data(flight_response)
        except json.JSONDecodeError:
            flight_message = flight_response
    else:
        flight_message = parse_flight_data(flight_response)

    starter_message = (
        f"**Away Match: {match_info['name']}**\n"
        f"Date and Time: {date_time_pst_formatted}\n"
        f"Venue: {match_info['venue']}\n\n"
        f"Let's discuss travel plans, accommodations, and local attractions for this away match!\n\n"
        f"**Flight Information**\n"
        f"{flight_message}\n\n"
        f"**Get Your Tickets**: [Buy Tickets Here]({ticket_link})"
    )

    embed = discord.Embed(title=thread_name, description=starter_message, color=0x1a75ff)
    embed.set_image(url=match_info['team_logo'])
    return starter_message, embed