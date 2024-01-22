# Common.py

import asyncio
import discord
import re
import json
import pytz
from datetime import datetime, timedelta
from config import BOT_CONFIG
from api_helpers import call_woocommerce_api, fetch_espn_data
from utils import load_json_data, save_json_data, convert_to_pst, get_airport_code_for_team
from database import insert_match_thread, get_predictions, initialize_db, load_match_threads
from api_helpers import fetch_openweather_data, fetch_serpapi_flight_data

bot_token = BOT_CONFIG['bot_token']
wc_url = BOT_CONFIG['wc_url']
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

closed_matches = set()

try:
    initialize_db()
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

redeemed_orders = load_redeemed_orders()
team_airports = load_team_airports()
match_dates = load_match_dates()
team_schedule = load_team_schedule()

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

async def get_away_match(ctx, opponent=None):
    product_url = wc_url.replace('orders/', 'products?category=765197886')
    products = await call_woocommerce_api(ctx, product_url)

    if products:
        matches = []

        for product in products:
            title = product.get('name', '')
            match_date = extract_date_from_title(title)

            if match_date and match_date >= datetime.now():
                link = product.get('permalink')
                matches.append((match_date, title, link))

        matches.sort()

        if opponent:
            for match in matches:
                if opponent.lower() in match[1].lower():
                    return match[1], match[2]

        if matches:
            closest_match = matches[0]
            return closest_match[1], closest_match[2]

    return None

def extract_date_from_title(title):
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", title)
    if match:
        date_str = match.group(0)
        try:
            match_date = datetime.strptime(date_str, "%Y-%m-%d")
            return match_date
        except ValueError as e:
            return None
    return None

async def get_team_record(interaction, team_id):
    data = await fetch_espn_data(interaction, f"sports/soccer/usa.1/teams/{team_id}")
    if data and 'team' in data:
        record_data = data['team'].get('record', {}).get('items', [])
        team_logo_url = data['team']['logos'][0]['href'] if data['team'].get('logos') else None
        if record_data:
            stats = record_data[0].get('stats', [])
            record_info = {stat['name']: stat['value'] for stat in stats}
            return record_info, team_logo_url
    return "Record not available", None

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

async def get_next_match(interaction, team_id, opponent=None, home_away=None):
    schedule_endpoint = f"sports/soccer/usa.1/teams/{team_id}/schedule"
    schedule_data = await fetch_espn_data(interaction, schedule_endpoint)
    if schedule_data and schedule_data.get("events"):
        return "!!! Schedule endpoint now contains events data. You should tell Immortal to update the parsing logic. Using backup method for now."

    if opponent:
        match_title, _ = await get_away_match(interaction, opponent)
        match_date = extract_date_from_title(match_title)
        if match_date:
            formatted_date = match_date.strftime("%Y%m%d")
            scoreboard_endpoint = f"sports/soccer/usa.1/scoreboard?dates={formatted_date}"
            backup_data = await fetch_espn_data(interaction, scoreboard_endpoint)
            if backup_data:
                for event in backup_data.get("events", []):
                    if team_name in event.get("name", "") and opponent.lower() in event.get("name", "").lower():
                        return extract_match_details(event)

    team_endpoint = f"sports/soccer/usa.1/teams/{team_id}"
    data = await fetch_espn_data(interaction, team_endpoint)
    if not data or 'team' not in data:
        return "Data not found for the specified team."

    next_events = data['team'].get('nextEvent', [])
    for event in next_events:
        competitors = event.get("competitions", [{}])[0].get("competitors", [])
        for competitor in competitors:
            if competitor["team"]["id"] == team_id:
                match_opponent = next(op["team"]["displayName"] for op in competitors if op["team"]["id"] != team_id)
                is_home_game = competitor["homeAway"] == "home"
                if (not opponent or opponent.lower() == match_opponent.lower()) and (home_away is None or competitor["homeAway"] == home_away):
                    return extract_match_details(event, competitor)

    return "No relevant away matches found."

def extract_match_details(event, competitor=None):
    match_id = event.get("id")
    date_time_utc = event.get("date")
    name = event.get("name")
    venue = event.get("competitions", [{}])[0].get("venue", {}).get("fullName")
    
    if competitor:
        opponent = next(op["team"]["displayName"] for op in event.get("competitions", [{}])[0].get("competitors", []) if op["team"]["id"] != competitor["team"]["id"])
        team_logo = competitor["team"].get("logos", [{}])[0].get("href")
        is_home_game = competitor["homeAway"] == "home"
    else:
        sounders_data = next(comp for comp in event["competitions"][0]["competitors"] if comp["team"]["id"] == "9726")
        opponent = next(op["team"]["displayName"] for op in event["competitions"][0]["competitors"] if op["team"]["id"] != "9726")
        team_logo = sounders_data["team"].get("logo")
        is_home_game = sounders_data["homeAway"] == "home"

    summary_link = next((link["href"] for link in event.get("links", []) if "summary" in link["rel"]), "Unavailable")
    stats_link = next((link["href"] for link in event.get("links", []) if "stats" in link["rel"]), "Unavailable")
    commentary_link = next((link["href"] for link in event.get("links", []) if "commentary" in link["rel"]), "Unavailable")

    return {
        "match_id": match_id,
        "opponent": opponent,
        "date_time": date_time_utc,
        "venue": venue,
        "name": name,
        "team_logo": team_logo,
        "is_home_game": is_home_game,
        "match_summary_link": summary_link,
        "match_stats_link": stats_link,
        "match_commentary_link": commentary_link
    }

async def create_match_thread(interaction, thread_name, embed, match_info, match_commands_cog, channel_name):
    channel = discord.utils.get(interaction.guild.channels, name=channel_name)
    if channel and isinstance(channel, discord.ForumChannel):
        thread, initial_message = await channel.create_thread(name=thread_name, auto_archive_duration=60, embed=embed)
        match_id = match_info['match_id']
        thread_id = str(thread.id)

        match_commands_cog.update_thread_map(thread_id, match_id)
        insert_match_thread(thread_id, match_id)

        if channel_name == 'match-thread':
            await thread.send(f"Predict the score! Use `/predict {match_info['name']}-Score - {match_info['opponent']}-Score` to participate. Predictions end at kickoff!")
            match_start_time = convert_to_pst(match_info['date_time'])
            asyncio.create_task(schedule_poll_closing(match_start_time, match_info['match_id'], thread))

        return f"Thread created in {channel_name}: [Click here to view the thread](https://discord.com/channels/{interaction.guild_id}/{channel.id}/{thread.id})"
    else:
        return f"Channel '{channel_name}' not found."
    
async def schedule_poll_closing(match_start_time, match_id, thread):
    now_utc = datetime.now(pytz.utc)
    delay = (match_start_time - now_utc).total_seconds()

    if delay > 0:
        await asyncio.sleep(delay)

        await thread.send("Predictions closed.")

        predictions = get_predictions(match_id)
        result_message = "Predictions for the match:\n" + "\n".join(f"{pred[0]}: {pred[1]} votes" for pred in predictions)
        await thread.send(result_message)

        closed_matches.add(match_id)
        
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
        self.redeemed_orders = redeemed_orders
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
        
async def get_matches_for_calendar(ctx):
    match_dates = load_match_dates()
    all_matches = []

    for date in match_dates:
        match_data = await fetch_espn_data(f"sports/soccer/usa.1/scoreboard?dates={date}")

        if not match_data:
            continue

        for event in match_data.get("events", []):
            if team_name in event.get("name", ""):
                match_details = extract_match_details(event)
                all_matches.append(match_details)

    return all_matches

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