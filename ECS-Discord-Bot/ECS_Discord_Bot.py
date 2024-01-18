import csv
import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import has_role
import io
import json
import aiohttp
import aiocron
import asyncio
import os
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import pytz
import traceback
from collections import defaultdict
import re
import sqlite3

load_dotenv()

intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.messages = True
intents.guilds = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

wc_key = os.getenv('WC_KEY')
wc_secret = os.getenv('WC_SECRET')
bot_token = os.getenv('BOT_TOKEN')
wc_url = os.getenv('URL')
team_name = os.getenv('TEAM_NAME')
openweather_api = os.getenv('OPENWEATHER_API_KEY')
venue_long = os.getenv('VENUE_LONG')
venue_lat = os.getenv('VENUE_LAT')
flask_url = os.getenv('FLASK_URL')
flask_token = os.getenv('FLASK_TOKEN')
discord_admin_role = os.getenv('ADMIN_ROLE')
dev_id = os.getenv('DEV_ID')
server_id = os.getenv('SERVER_ID')
BOT_VERSION = "1.3.0"
closed_matches = set()

def initialize_db():
    conn = sqlite3.connect('predictions.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS predictions
                 (match_id TEXT, user_id TEXT, prediction TEXT, timestamp DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS match_threads
                 (thread_id TEXT, match_id TEXT)''')
    conn.commit()
    conn.close()

initialize_db()

def insert_match_thread(thread_id, match_id):
    conn = sqlite3.connect('predictions.db')
    c = conn.cursor()
    c.execute("INSERT INTO match_threads VALUES (?, ?)", (thread_id, match_id))
    conn.commit()
    conn.close()

def insert_prediction(match_id, user_id, prediction):
    conn = sqlite3.connect('predictions.db')
    c = conn.cursor()

    c.execute("SELECT * FROM predictions WHERE match_id=? AND user_id=?", (match_id, user_id))
    if c.fetchone():
        conn.close()
        return False

    c.execute("INSERT INTO predictions VALUES (?, ?, ?, CURRENT_TIMESTAMP)", (match_id, user_id, prediction))
    conn.commit()
    conn.close()
    return True

def get_predictions(match_id):
    conn = sqlite3.connect('predictions.db')
    c = conn.cursor()
    c.execute("SELECT prediction, COUNT(*) FROM predictions WHERE match_id=? GROUP BY prediction", (match_id,))
    results = c.fetchall()
    conn.close()
    return results

def load_match_threads():
    conn = sqlite3.connect('predictions.db')
    c = conn.cursor()
    c.execute("SELECT * FROM match_threads")
    threads = c.fetchall()
    conn.close()
    return {thread_id: match_id for thread_id, match_id in threads}

match_thread_map = load_match_threads()

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

redeemed_orders = load_redeemed_orders()

async def get_next_match(ctx, team_name):
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard"
    data = await send_async_http_request(ctx, url)

    team_id = None
    if data:
        for event in data.get('events', []):
            for competition in event.get('competitions', []):
                competitors = competition.get('competitors', [])
                for team in competitors:
                    if team.get('team', {}).get('displayName') == team_name:
                        team_id = team.get('team', {}).get('id')
                        break
                if team_id:
                    break

    if not team_id:
        return "Team ID not found."

    record = await get_team_record(ctx, team_id)
    upcoming_matches = []
    now = datetime.now(tz=pytz.utc)

    for event in data.get('events', []):
        match_id = event['id']
        for competition in event.get('competitions', []):
            match_time_utc = datetime.fromisoformat(competition['date'].replace('Z', '+00:00'))
            if match_time_utc > now:
                competitors = competition.get('competitors', [])
                for team in competitors:
                    display_name = team.get('team', {}).get('displayName')
                    if display_name == team_name:
                        is_home_game = team['homeAway'] == 'home'
                        opponent_details = next((t for t in competitors if t.get('team', {}).get('displayName') != team_name), None)

                        match_info = {
                            'match_id': match_id,
                            'opponent': opponent_details['team']['displayName'] if opponent_details else "Unknown",
                            'date_time': competition.get('date'),
                            'venue': competition.get('venue', {}).get('fullName'),
                            'team_logos': [t['team']['logo'] for t in competitors if 'team' in t],
                            'team_form': team['form'] if team else "N/A",
                            'opponent_form': opponent_details['form'] if opponent_details else "N/A",
                            'team_stats_link': team['team']['links'][1]['href'] if team else "",
                            'opponent_stats_link': opponent_details['team']['links'][1]['href'] if opponent_details else "",
                            'is_home_game': is_home_game
                        }
                        upcoming_matches.append((match_time_utc, match_info))

            if upcoming_matches:
                next_match_info = sorted(upcoming_matches, key=lambda x: x[0])[0][1]
                event = next(e for e in data['events'] if e['id'] == next_match_info['match_id'])
                next_match_info['match_summary_link'] = next(link['href'] for link in event['links'] if link['rel'] == ["summary","desktop","event"])
                next_match_info['match_stats_link'] = next(link['href'] for link in event['links'] if link['rel'] == ["stats","desktop","event"])
                return next_match_info, record

            return "No upcoming matches found for {}.".format(team_name)
        else:
            return "Error fetching data from ESPN API."

async def get_team_record(ctx, team_id):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/teams/{team_id}"
    data = await send_async_http_request(ctx, url)
    if data and 'team' in data:
        record_data = data['team'].get('record', {}).get('items', [])
        team_logo_url = data['team']['logos'][0]['href']  # Assuming the first logo is the one you want
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

async def get_closest_away_match(ctx):
    product_url = wc_url.replace('orders/', 'products?category=765197886')
    products = await call_woocommerce_api(ctx, product_url)
    
    if products:
        upcoming_matches = []

        for product in products:
            title = product.get('name', '')
            match_date = extract_date_from_title(title)

            if match_date and match_date >= datetime.now():
                link = product.get('permalink')
                upcoming_matches.append((match_date, title, link))

        upcoming_matches.sort()

        if upcoming_matches:
            closest_match = upcoming_matches[0]
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

async def is_admin_or_owner(interaction: discord.Interaction):
    return str(interaction.user.id) == dev_id or any(role.name == discord_admin_role for role in interaction.user.roles)

async def has_admin_role(interaction: discord.Interaction):
    return any(role.name == discord_admin_role for role in interaction.user.roles)

@bot.event
async def on_ready():
    await bot.wait_until_ready()

    await bot.add_cog(MatchCommands(bot))
    await bot.add_cog(AdminCommands(bot))
    await bot.add_cog(GeneralCommands(bot))
    await bot.add_cog(WooCommerceCommands(bot))
    await bot.tree.sync(guild=discord.Object(id=server_id))

    # Other on_ready logic
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
        order_id = self.children[0].value.strip()  # Retrieve the entered order ID
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

        view = ConfirmResetView(self.bot, self.new_role_input)  # Pass the role to the view
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

        await interaction.response.send_message(f"ECS Bot - developed by <@{dev_id}> version {BOT_VERSION}")

    @app_commands.command(name='checkorder', description="Check an ECS membership order")
    @app_commands.guilds(discord.Object(id=server_id))  # Replace with your server ID
    async def check_order(self, interaction: discord.Interaction):
        # Admin role check
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        # Show the modal to the user
        await interaction.response.send_modal(CheckOrderModal(self.bot))

    @app_commands.command(name='newseason', description="Start a new season with a new ECS membership role")
    @app_commands.guilds(discord.Object(id=server_id))  # Replace with your server ID
    async def new_season(self, interaction: discord.Interaction):
        # Admin role check
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        # Send the modal for new ECS role
        modal = NewRoleModal(self.bot)
        await interaction.response.send_modal(modal)

class MatchCommands(commands.Cog, name="Match Commands"):
    def __init__(self, bot):
        self.bot = bot
        self.match_thread_map = match_thread_map

    @app_commands.command(name='nextmatch', description="List the next scheduled match information")
    @app_commands.guilds(discord.Object(id=server_id))
    async def next_match(self, interaction: discord.Interaction):
        match_info, team_record = await get_next_match(interaction, team_name)

        if isinstance(match_info, str):
            await interaction.response.send_message(match_info)
            return

        opponent = match_info['opponent']
        date_time_utc = match_info['date_time']
        venue = match_info['venue']
        team_logo = match_info['team_logos'][0]
    
        date_time_pst_obj = convert_to_pst(date_time_utc)
        date_time_pst_formatted = date_time_pst_obj.strftime('%m/%d/%Y %I:%M %p PST')

        embed = discord.Embed(title="Next Match Details", color=0x1a75ff)
        embed.add_field(name="Opponent", value=opponent, inline=True)
        embed.add_field(name="Date and Time (PST)", value=date_time_pst_formatted, inline=True)
        embed.add_field(name="Venue", value=venue, inline=True)
        embed.set_image(url=team_logo)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='newmatch', description="Create a new match thread")
    @app_commands.guilds(discord.Object(id=server_id))  # Replace with your server ID
    async def new_match(self, interaction: discord.Interaction):
        # Admin role check
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        # Deferring the response for long processing
        await interaction.response.defer()

        try:
            match_info, team_record = await get_next_match(interaction, team_name)
            if isinstance(match_info, str):
                await interaction.followup.send(match_info, ephemeral=True)
                return
        except Exception as e:
            await interaction.followup.send(f"Failed to process the command: {e}", ephemeral=True)

        opponent = match_info.get('opponent', 'Unknown Opponent')
        date_time_utc = match_info.get('date_time', 'Unknown Date/Time')
        venue = match_info.get('venue', 'Unknown Venue')
        team_form = match_info.get('team_form', 'N/A')
        opponent_form = match_info.get('opponent_form', 'N/A')
        team_stats_link = match_info.get('team_stats_link', '')
        opponent_stats_link = match_info.get('opponent_stats_link', '')
        match_summary_link = match_info.get('match_summary_link', '#')
        match_stats_link = match_info.get('match_stats_link', '#')

        weather_forecast = ""
        if match_info['is_home_game']:
            weather_forecast = await get_weather_forecast(date_time_utc, venue_lat, venue_long)
            weather_forecast = f"\n\n**Weather**: {weather_forecast}"
            match_time_pst = convert_to_pst(date_time_utc)
            event_start_time_pst = match_time_pst - timedelta(hours=1)
            date_time_pst_formatted = match_time_pst.strftime('%m/%d/%Y %I:%M %p PST')
            event_start_str = event_start_time_pst.strftime('%m/%d/%Y %I:%M %p PST')

            existing_events = await interaction.guild.fetch_scheduled_events()
            event_exists = any(
                event.name == "March to the Match" and 
                event.start_time == event_start_time_pst for event in existing_events
            )

            if not event_exists:
                try:
                    event = await interaction.guild.create_scheduled_event(
                        name="March to the Match",
                        start_time=event_start_time_pst,
                        end_time=event_start_time_pst + timedelta(hours=2),
                        description=f"March to the Match for {team_name} vs {opponent}",
                        location="117 S Washington St, Seattle, WA 98104",
                        entity_type=discord.EntityType.external,
                        privacy_level=discord.PrivacyLevel.guild_only
                    )
                    await interaction.followup.send(f"Event created: 'March to the Match' starting at {event_start_str}.")
                except Exception as e:
                    await interaction.followup.send(f"Failed to create event: {e}")
            else:
                await interaction.followup.send("An event for this match has already been scheduled.")

        thread_name = f"Match Thread: {team_name} vs {opponent} - {date_time_pst_formatted}"

        channel = discord.utils.get(interaction.guild.channels, name='match-thread')
        if channel and isinstance(channel, discord.ForumChannel):
            existing_threads = channel.threads

            for thread in existing_threads:
                if thread.name == thread_name:
                    await interaction.followup.send("A thread for this match has already created.")
                    return

        starter_message = (
            f"**Upcoming Match: {team_name} vs {opponent}**\n"
            f"Date and Time: {date_time_pst_formatted}\n"
            f"Venue: {venue}\n"
            f"**Season History**\n"
            f"{team_name}: {team_form} [Team Stats]({team_stats_link})\n"
            f"{opponent}: {opponent_form} [Opponent Stats]({opponent_stats_link})\n"
            f"**Match Details**\n"
            f"More Info: [Match Summary](<{match_summary_link}>), [Statistics](<{match_stats_link}>)\n"
            f"**Broadcast**: AppleTV"
            f"{weather_forecast}"
        )

        embed = discord.Embed(
            title=thread_name,
            description=starter_message,
            color=0x1a75ff
        )
        embed.set_image(url=match_info['team_logos'][0])

        channel = discord.utils.get(interaction.guild.channels, name='match-thread')
        if channel:
            if isinstance(channel, discord.ForumChannel):
                thread, initial_message = await channel.create_thread(name=thread_name, auto_archive_duration=60, embed=embed)
                self.match_thread_map[thread.id] = match_info['match_id']
                insert_match_thread(thread.id, match_info['match_id'])

                self.match_thread_map = load_match_threads()

                await thread.send(f"Predict the score! Use `/predict {team_name}-Score - {opponent}-Score` to participate.  Predictions end at kickoff!")

                match_start_time = convert_to_pst(date_time_utc)
                asyncio.create_task(schedule_poll_closing(match_start_time, match_info['match_id'], thread))

                await interaction.followup.send(f"Match thread created: [Click here to view the thread](https://discord.com/channels/{interaction.guild_id}/{channel.id}/{thread.id})")
            else:
                await interaction.followup.send("Match thread channel not found.", ephemeral=True)

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

    @app_commands.command(name='record', description="Lists the Sounders season stats")
    @app_commands.guilds(discord.Object(id=server_id))
    async def team_record(self, interaction: discord.Interaction):
        match_info, record = await get_next_match(interaction, team_name)
        if record:
            record_info, team_logo_url = record
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
    async def away_tickets(self, interaction: discord.Interaction):
        closest_match = await get_closest_away_match(interaction)
        if closest_match:
            match_name, match_link = closest_match
            await interaction.response.send_message(f"Next away match: {match_name}\nTickets: {match_link}")
        else:
            await interaction.response.send_message("No upcoming away matches found.")

class WooCommerceCommands(commands.Cog, name="WooCommerce Commands"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='getorderinfo', description="Retrieve order details for a specific product")
    @app_commands.describe(product_title='Title of the product')
    @app_commands.guilds(discord.Object(id=server_id))  # Replace with your server ID
    async def get_product_orders(self, interaction: discord.Interaction, product_title: str):
        if not await has_admin_role(interaction):
            await interaction.response.send_message("You do not have the necessary permissions.", ephemeral=True)
            return

        # Modify the base URL to query the products endpoint
        product_url = wc_url.replace('orders/', f'products?search={product_title}')

        # Query WooCommerce for the product
        products = await call_woocommerce_api(interaction, product_url)
    
        if not products:
            await interaction.response.send_message("No products found or failed to fetch products.", ephemeral=True)
            return

        product = next((p for p in products if p['name'].lower() == product_title.lower()), None)

        if not product:
            await interaction.response.send_message("Product not found.", ephemeral=True)
            return

        # Modify the base URL to query orders for the specific product
        orders_url = wc_url.replace('products?', f'orders?product={product["id"]}')

        # Query WooCommerce for the orders
        orders = await call_woocommerce_api(interaction, orders_url)

        if not orders:
            await interaction.response.send_message("No orders found for this product.", ephemeral=True)
            return

        # Extract data and generate CSV
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
                           item['name']]  # Assuming this is the variation name
                    csv_writer.writerow(row)

        csv_output.seek(0)
        csv_file = discord.File(fp=csv_output, filename=f"{product_title}_orders.csv")

        # Send CSV File
        await interaction.response.send_message(f"Orders for product '{product_title}':", file=csv_file, ephemeral=True)

        csv_output.close()

@bot.tree.command(name='verify', description="Verify your ECS membership", guild=discord.Object(id=server_id))
async def verify_order(interaction: discord.Interaction):
    modal = VerifyModal(title="Verify Membership", bot=bot)
    await interaction.response.send_modal(modal)

bot.run(bot_token)