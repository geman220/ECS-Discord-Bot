import csv
import discord
from discord import app_commands
from discord.ext import commands
import io
import json
import aiohttp
import asyncio
import os
from datetime import datetime, timedelta
import pytz
import re
from database import initialize_db, insert_match_thread, get_predictions, load_match_threads, insert_prediction
from config import BOT_CONFIG

intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.messages = True
intents.guilds = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

wc_key = BOT_CONFIG['wc_key']
wc_secret = BOT_CONFIG['wc_secret']
bot_token = BOT_CONFIG['bot_token']
wc_url = BOT_CONFIG['wc_url']
team_name = BOT_CONFIG['team_name']
team_id = BOT_CONFIG['team_id']
openweather_api = BOT_CONFIG['openweather_api']
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

def convert_to_pst(utc_datetime_str):
    utc_datetime = datetime.fromisoformat(utc_datetime_str.replace('Z', '+00:00'))
    utc_datetime = utc_datetime.replace(tzinfo=pytz.utc)
    pst_timezone = pytz.timezone('America/Los_Angeles')
    return utc_datetime.astimezone(pst_timezone)

async def send_async_http_request(ctx, url, method='GET', headers=None, auth=None, data=None):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(method, url, headers=headers, auth=auth, data=data) as response:
                if response.status == 200:
                    return await response.json()
        except aiohttp.ClientError as e:
            await ctx.send(f"Client error occurred: {e}")
            return None
        except Exception as e:
            await ctx.send(f"An unexpected error occurred: {e}")
            return None

def read_json_file(file_path, default_value):
    try:
        with open(file_path, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_value

def write_json_file(file_path, data):
    with open(file_path, 'w') as file:
        json.dump(data, file)

async def call_woocommerce_api(ctx, url):
    auth = aiohttp.BasicAuth(wc_key, wc_secret)
    return await send_async_http_request(ctx, url, auth=auth)

def load_current_role():
    role_data = read_json_file('current_role.json', default_value={"current_role": "ECS Membership 202x"})
    return role_data['current_role']

def save_current_role(role_name):
    write_json_file('current_role.json', {'current_role': role_name})

def load_redeemed_orders():
    return read_json_file('redeemed_orders.json', default_value={})

def save_redeemed_orders(redeemed_orders):
    write_json_file('redeemed_orders.json', redeemed_orders)

def load_team_airports():
    return read_json_file('team_airports.json', default_value={})

def load_match_dates():
    return read_json_file('match_dates.json', default_value=[])

def load_team_schedule():
    return read_json_file('team_schedule.json', default_value=[])

def get_airport_code_for_team(team_name, team_airports):
    for airport_code, teams in team_airports.items():
        if team_name in teams:
            return airport_code
    return None

redeemed_orders = load_redeemed_orders()
team_airports = load_team_airports()
match_dates = load_match_dates()
team_schedule = load_team_schedule()

async def get_matches_for_calendar(ctx):
    match_dates = load_match_dates()
    all_matches = []

    for date in match_dates:
        api_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard?dates={date}"
        match_data = await send_async_http_request(ctx, api_url)

        if not match_data:
            continue

        for event in match_data.get("events", []):
            if team_name in event.get("name", ""):
                match_details = extract_match_details(event)
                all_matches.append(match_details)

    return all_matches

async def get_next_match(ctx, team_id, opponent=None, home_away=None):
    schedule_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/teams/{team_id}/schedule"
    schedule_data = await send_async_http_request(ctx, schedule_url)
    if schedule_data and schedule_data.get("events"):
        return "!!! Schedule endpoint now contains events data. You should tell Immortal to update the parsing logic.  Using backup method for now."

    if opponent:
        match_title, _ = await get_away_match(ctx, opponent)
        match_date = extract_date_from_title(match_title)
        if match_date:
            formatted_date = match_date.strftime("%Y%m%d")
            backup_data = await send_async_http_request(ctx, f"https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard?dates={formatted_date}")
            if backup_data:
                for event in backup_data.get("events", []):
                    if team_name in event.get("name", "") and opponent.lower() in event.get("name", "").lower():
                        return extract_match_details(event)

    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/teams/{team_id}"
    data = await send_async_http_request(ctx, url)

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

async def get_team_record(ctx, team_id):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/teams/{team_id}"
    data = await send_async_http_request(ctx, url)
    if data and 'team' in data:
        record_data = data['team'].get('record', {}).get('items', [])
        team_logo_url = data['team']['logos'][0]['href']
        if record_data:
            stats = record_data[0].get('stats', [])
            record_info = {stat['name']: stat['value'] for stat in stats}
            return record_info, team_logo_url
    return "Record not available", None

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

async def get_weather_forecast(date_time_utc, latitude, longitude):
    match_date = datetime.fromisoformat(date_time_utc).date()

    if match_date > datetime.utcnow().date() + timedelta(days=5):
        return "No weather information available for dates more than 5 days ahead."

    url = f"http://api.openweathermap.org/data/2.5/forecast?lat={latitude}&lon={longitude}&appid={openweather_api}&units=metric"

    response = await send_async_http_request(url)
    if response and response.status == 200:
        data = await response.json()

        for forecast in data.get('list', []):
            forecast_date = datetime.fromtimestamp(forecast['dt']).date()

            if forecast_date == match_date:
                weather = forecast['weather'][0]['description']
                temp = forecast['main']['temp']
                return f"Weather: {weather}, Temperature: {temp} F"

        return "Weather forecast not available for the selected date."
    else:
        return "Unable to fetch weather information."

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

async def generate_flight_search_url(departure_airport, team_name, outbound_date, return_date):
    arrival_airport = get_airport_code_for_team(team_name, team_airports)
    if not arrival_airport:
        return "Airport for the team not found."

    base_url = "https://serpapi.com/search"
    params = {
        "engine": "google_flights",
        "departure_id": departure_airport,
        "arrival_id": arrival_airport,
        "gl": "us",
        "hl": "en",
        "currency": "USD",
        "type": "1",
        "outbound_date": outbound_date.strftime("%Y-%m-%d"),
        "return_date": return_date.strftime("%Y-%m-%d"),
        "api_key": serpapi_api
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(base_url, params=params) as response:
            if response.status == 200:
                return await response.text()
            else:
                return f"Failed to fetch data: {response.status}"

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

async def prepare_starter_message_away(match_info, date_time_pst_formatted, thread_name, ticket_link):
    match_date = datetime.strptime(date_time_pst_formatted, '%m/%d/%Y %I:%M %p PST').date()
    outbound_date = match_date - timedelta(days=1)
    return_date = match_date + timedelta(days=1)

    flight_response = await generate_flight_search_url("SEA", match_info['opponent'], outbound_date, return_date)
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

async def is_admin_or_owner(interaction: discord.Interaction):
    return str(interaction.user.id) == dev_id or any(role.name == discord_admin_role for role in interaction.user.roles)

async def has_admin_role(interaction: discord.Interaction):
    return any(role.name == discord_admin_role for role in interaction.user.roles)

async def has_required_wg_role(interaction: discord.Interaction):
    required_roles = ["WG: Travel", "WG: Home Tickets", discord_admin_role]
    return any(role.name in required_roles for role in interaction.user.roles)

@bot.event
async def on_ready():
    await bot.wait_until_ready()

    await bot.add_cog(MatchCommands(bot))
    await bot.add_cog(AdminCommands(bot))
    await bot.add_cog(GeneralCommands(bot))
    await bot.add_cog(WooCommerceCommands(bot))
    await bot.tree.sync(guild=discord.Object(id=server_id))

    if os.path.exists('/root/update_channel_id.txt'):
        with open('/root/update_channel_id.txt', 'r') as f:
            channel_id = int(f.read())
        channel = bot.get_channel(channel_id)
        if channel:
            await channel.send("Update complete. Bot restarted successfully.")
        os.remove('/root/update_channel_id.txt')

    print(f'Logged in as {bot.user}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    await bot.process_commands(message)

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"This command is on cooldown. Please try again after {error.retry_after:.2f} seconds.", ephemeral=True)
    else:
        print(f"Unhandled interaction command error: {error}")
        await interaction.response.send_message("An error occurred while processing the command.", ephemeral=True)

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

class AdminCommands(commands.Cog, name="Admin Commands"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='update', description="Update the bot from the GitHub repository")
    @app_commands.guilds(discord.Object(id=server_id))
    async def update_bot(self, interaction: discord.Interaction):
        """Update the bot from GitHub repository"""
        if not await is_admin_or_owner(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        with open('/root/update_channel_id.txt', 'w') as f:
            f.write(str(interaction.channel.id))

        headers = {'Authorization': f'Bearer {flask_token}'}
        async with aiohttp.ClientSession() as session:
            async with session.post(flask_url, headers=headers) as response:
                if response.status == 200:
                    await interaction.response.send_message("Bot is updating...", ephemeral=True)
                else:
                    response_text = await response.text()
                    await interaction.response.send_message(f"Update failed: {response_text}", ephemeral=True)

    @app_commands.command(name='version', description="Get the current bot version")
    @app_commands.guilds(discord.Object(id=server_id))
    async def version(self, interaction: discord.Interaction):
        if not await is_admin_or_owner(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.send_message(f"ECS Bot - developed by <@{dev_id}> version {bot_version}")

    @app_commands.command(name='checkorder', description="Check an ECS membership order")
    @app_commands.guilds(discord.Object(id=server_id))
    async def check_order(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.send_modal(CheckOrderModal(self.bot))

    @app_commands.command(name='newseason', description="Start a new season with a new ECS membership role")
    @app_commands.guilds(discord.Object(id=server_id))
    async def new_season(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        modal = NewRoleModal(self.bot)
        await interaction.response.send_modal(modal)
        
    @app_commands.command(name='createschedule', description="Create the team schedule file")
    @app_commands.guilds(discord.Object(id=server_id))
    async def create_schedule_command(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return
    
        await interaction.response.defer()
        ctx = interaction

        try:
            matches = await get_matches_for_calendar(ctx)
            if not matches:
                await interaction.followup.send("No match data found.")
                return

            with open('team_schedule.json', 'w') as f:
                json.dump(matches, f, indent=4)
            await interaction.followup.send("Team schedule created successfully.")
        except Exception as e:
            await interaction.followup.send(f"Failed to create schedule: {e}")

    @app_commands.command(name='updatecalendar', description="Update the event calendar with team schedule")
    @app_commands.guilds(discord.Object(id=server_id))
    async def update_calendar_command(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.defer()

        team_schedule = load_team_schedule()
        api_url = 'https://weareecs.com/wp-json/tribe/events/v1/events'
        auth = aiohttp.BasicAuth(login=wp_username, password=wp_app_password)

        async with aiohttp.ClientSession() as session:
            for match in team_schedule:
                pst_start_time = self.convert_to_pst(match['date_time'])
                pst_end_time = pst_start_time + timedelta(hours=3)

                event_data = {
                    "title": match['name'],
                    "description": f"{match['name']} at {match['venue']}. More details [here]({match['match_summary_link']}).",
                    "start_date": pst_start_time.strftime('%Y-%m-%dT%H:%M:%S'),
                    "end_date": pst_end_time.strftime('%Y-%m-%dT%H:%M:%S'),
                    "image": match['team_logo'],
                    "website": match['match_summary_link'],
                    "timezone": "America/Los_Angeles",
                }

                async with session.post(api_url, json=event_data, auth=auth) as response:
                    if response.status == 201:
                        print(f"Event created successfully for match: {match['name']}")
                    else:
                        print(f"Failed to create event for match: {match['name']}. Status code: {response.status}")
                    await asyncio.sleep(1)

        await interaction.followup.send("Event calendar updated successfully.")

class MatchCommands(commands.Cog, name="Match Commands"):
    def __init__(self, bot):
        self.bot = bot
        self.match_thread_map = match_thread_map
        self.team_id = team_id

    def update_thread_map(self, thread_id, match_id):
        self.match_thread_map[thread_id] = match_id

    @app_commands.command(name='nextmatch', description="List the next scheduled match information")
    @app_commands.guilds(discord.Object(id=server_id))
    async def next_match(self, interaction: discord.Interaction):
        match_info = await get_next_match(interaction, team_id)

        if isinstance(match_info, str):
            await interaction.response.send_message(match_info)
            return

        date_time_pst_obj = convert_to_pst(match_info['date_time'])
        date_time_pst_formatted = date_time_pst_obj.strftime('%m/%d/%Y %I:%M %p PST')

        embed = discord.Embed(title=f"Next Match: {match_info['name']}", color=0x1a75ff)
        embed.add_field(name="Opponent", value=match_info['opponent'], inline=True)
        embed.add_field(name="Date and Time (PST)", value=date_time_pst_formatted, inline=True)
        embed.add_field(name="Venue", value=match_info['venue'], inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='newmatch', description="Create a new match thread")
    @app_commands.guilds(discord.Object(id=server_id))
    async def new_match(self, interaction: discord.Interaction):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            match_info = await get_next_match(interaction, self.team_id)
            if isinstance(match_info, str):
                await interaction.followup.send(match_info, ephemeral=True)
                return
        except Exception as e:
            await interaction.followup.send(f"Failed to process the command: {e}", ephemeral=True)

        date_time_pst = convert_to_pst(match_info['date_time'])
        date_time_pst_formatted = date_time_pst.strftime('%m/%d/%Y %I:%M %p PST')
        thread_name = f"Match Thread: {match_info['name']} - {date_time_pst_formatted}"
    
        weather_forecast = ""
        if match_info['is_home_game']:
            weather_forecast = await get_weather_forecast(date_time_pst, venue_lat, venue_long)
            event_response = await create_event_if_necessary(interaction, match_info, date_time_pst)
            if event_response:
                await interaction.followup.send(event_response)
                return

        if await check_existing_threads(interaction, thread_name, "match-thread"):
            await interaction.followup.send("A thread for this match has already been created.")
            return

        starter_message, embed = await prepare_starter_message(match_info, date_time_pst_formatted, match_info['team_logo'], weather_forecast, thread_name)
        thread_response = await create_match_thread(interaction, thread_name, embed, match_info, self, "match-thread")
        await interaction.followup.send(thread_response)

    @app_commands.command(name='awaymatch', description="Create a new away match thread, create ticket item in store first!")
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.describe(opponent='The name of the opponent team (optional)')
    async def away_match(self, interaction: discord.Interaction, opponent: str = None):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        await interaction.response.defer()

        match_ticket_info = await get_away_match(interaction, opponent)
        if not match_ticket_info:
            await interaction.followup.send("No relevant away match or ticket info found.", ephemeral=True)
            return

        match_name, match_link = match_ticket_info

        try:
            match_info = await get_next_match(interaction, self.team_id, opponent)
            if isinstance(match_info, str):
                await interaction.followup.send(match_info, ephemeral=True)
                return

            match_id = match_info['match_id']
            match_name = match_info['name']
            match_venue = match_info['venue']
            match_opponent = match_info['opponent']
            match_date_time_utc = match_info['date_time']

            date_time_pst = convert_to_pst(match_date_time_utc)
            date_time_pst_formatted = date_time_pst.strftime('%m/%d/%Y %I:%M %p PST')
            thread_name = f"Away Travel: {match_name} - {date_time_pst_formatted}"

            if await check_existing_threads(interaction, thread_name, "away-travel"):
                await interaction.followup.send("A thread for this away match has already been created.")
                return

            starter_message, embed = await prepare_starter_message_away(match_info, date_time_pst_formatted, thread_name, match_link)
            thread_response = await create_match_thread(interaction, thread_name, embed, match_info, self, channel_name='away-travel')
        
            await interaction.followup.send(thread_response)
        except Exception as e:
            await interaction.followup.send(f"Failed to process the command: {e}", ephemeral=True)

    @app_commands.command(name='predictions', description='List predictions for the current match thread')
    @app_commands.guilds(discord.Object(id=server_id))
    async def show_predictions(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This command can only be used in match threads.", ephemeral=True)
            return

        match_id = self.match_thread_map.get(str(interaction.channel.id))
        if not match_id:
            await interaction.response.send_message("This thread is not associated with an active match prediction.", ephemeral=True)
            return

        predictions = get_predictions(match_id)
        if not predictions:
            await interaction.response.send_message("No predictions have been made for this match.", ephemeral=True)
            return

        embed = discord.Embed(title="Match Predictions", color=0x00ff00)
        if interaction.guild.icon:
            embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
        else:
            embed.set_author(name=interaction.guild.name)

        embed.set_footer(text="Predictions are subject to change before match kickoff.")

        for prediction, count in predictions:
            embed.add_field(name=prediction, value=f"{count} prediction(s)", inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='predict', description='Predict the score of the match')
    @app_commands.describe(prediction='Your prediction (e.g., 3-0)')
    @app_commands.guilds(discord.Object(id=server_id))
    async def predict(self, interaction: discord.Interaction, prediction: str):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This command can only be used in match threads.", ephemeral=True)
            return

        match_id = self.match_thread_map.get(str(interaction.channel.id))
        if not match_id:
            await interaction.response.send_message("This thread is not associated with an active match prediction.", ephemeral=True)
            return

        if match_id in closed_matches:
            await interaction.response.send_message("Predictions are closed for this match.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        if insert_prediction(match_id, user_id, prediction):
            await interaction.response.send_message("Prediction recorded!", ephemeral=True)
        else:
            await interaction.response.send_message("You have already made a prediction for this match.", ephemeral=True)

class GeneralCommands(commands.Cog, name="General Commands"):
    def __init__(self, bot):
        self.bot = bot
        self.team_id = team_id

    @app_commands.command(name='record', description="Lists the Sounders season stats")
    @app_commands.guilds(discord.Object(id=server_id))
    async def team_record(self, interaction: discord.Interaction):
        record_info, team_logo_url = await get_team_record(interaction, self.team_id)
        if record_info != "Record not available":
            embed = discord.Embed(title=f"{team_name} Record", color=0x00ff00)
            if team_logo_url:
                embed.set_thumbnail(url=team_logo_url)
            for stat, value in record_info.items():
                readable_stat = format_stat_name(stat)
                embed.add_field(name=readable_stat, value=str(value), inline=True)
    
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("Error fetching record.")

    @app_commands.command(name='awaytickets', description="Get a link to the latest away tickets")
    @app_commands.guilds(discord.Object(id=server_id))
    @app_commands.describe(opponent='The name of the opponent team (optional)')
    async def away_tickets(self, interaction: discord.Interaction, opponent: str = None):
        closest_match = await get_away_match(interaction, opponent)
        if closest_match:
            match_name, match_link = closest_match
            await interaction.response.send_message(f"Away match: {match_name}\nTickets: {match_link}")
        else:
            await interaction.response.send_message("No upcoming away matches found.")

class WooCommerceCommands(commands.Cog, name="WooCommerce Commands"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='ticketlist', description="List all tickets for sale")
    @app_commands.guilds(discord.Object(id=server_id))
    async def list_tickets(self, interaction: discord.Interaction):
        if not await has_required_wg_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

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

        await interaction.response.send_message(message_content, ephemeral=True)

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

@bot.tree.command(name='verify', description="Verify your ECS membership", guild=discord.Object(id=server_id))
async def verify_order(interaction: discord.Interaction):
    modal = VerifyModal(title="Verify Membership", bot=bot)
    await interaction.response.send_modal(modal)

bot.run(bot_token)