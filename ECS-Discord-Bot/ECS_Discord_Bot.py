import discord
from discord.ext import commands
from discord.ext.commands import has_role
import json
import aiohttp
import aiocron
import asyncio
import os
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import pytz

# Load environment variables from .env file
load_dotenv()

# Define intents
intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.messages = True   # For receiving messages
intents.guilds = True
intents.message_content = True  # For reading message content

# Bot setup with intents
bot = commands.Bot(command_prefix='!', intents=intents)

# Use environment variables for credentials
wc_key = os.getenv('WC_KEY')
wc_secret = os.getenv('WC_SECRET')
bot_token = os.getenv('BOT_TOKEN')
wc_url = os.getenv('URL')
team_name = os.getenv('TEAM_NAME')
openweather_api = os.getenv('OPENWEATHER_API_KEY')
venue_long = os.getenv('VENUE_LONG')
venue_lat = os.getenv('VENUE_LAT')

# Function to convert UTC time to PST
def convert_to_pst(utc_datetime_str):
    utc_datetime = datetime.fromisoformat(utc_datetime_str.replace('Z', '+00:00'))
    utc_datetime = utc_datetime.replace(tzinfo=pytz.utc)
    pst_timezone = pytz.timezone('America/Los_Angeles')
    return utc_datetime.astimezone(pst_timezone)  # Returns a datetime object in PST

async def get_next_match(team_name):
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                upcoming_matches = []
                now = datetime.now(tz=pytz.utc)  # Current time in UTC

                for event in data.get('events', []):
                    match_id = event['id']  # Extract match ID
                    for competition in event.get('competitions', []):
                        match_time_utc = datetime.fromisoformat(competition['date'].replace('Z', '+00:00'))
                        if match_time_utc > now:
                            competitors = competition.get('competitors', [])
                            for team in competitors:
                                display_name = team.get('team', {}).get('displayName')
                                if display_name == team_name:
                                    # Determine if the match is a home game
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
                                        'is_home_game': is_home_game  # Add 'is_home_game' to match_info
                                    }
                                    upcoming_matches.append((match_time_utc, match_info))

                if upcoming_matches:
                    next_match_info = sorted(upcoming_matches, key=lambda x: x[0])[0][1]
                    # Extract links for match summary and statistics
                    event = next(e for e in data['events'] if e['id'] == next_match_info['match_id'])
                    next_match_info['match_summary_link'] = next(link['href'] for link in event['links'] if link['rel'] == ["summary","desktop","event"])
                    next_match_info['match_stats_link'] = next(link['href'] for link in event['links'] if link['rel'] == ["stats","desktop","event"])
                    return next_match_info

                return "No upcoming matches found for {}.".format(team_name)
            else:
                return "Error fetching data from ESPN API."

def load_current_role():
    try:
        with open('current_role.json', 'r') as file:
            data = json.load(file)
            return data['current_role']
    except (FileNotFoundError, json.JSONDecodeError):
        return "ECS Membership 202x"  # Default role name

def save_current_role(role_name):
    with open('current_role.json', 'w') as file:
        json.dump({'current_role': role_name}, file)

async def call_woocommerce_api(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, auth=aiohttp.BasicAuth(wc_key, wc_secret)) as response:
            if response.status == 200:
                return await response.json()
            else:
                return None

# Function to load redeemed orders from file
def load_redeemed_orders():
    try:
        with open('redeemed_orders.json', 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Function to save redeemed orders to file
def save_redeemed_orders(redeemed_orders):
    with open('redeemed_orders.json', 'w') as file:
        json.dump(redeemed_orders, file)

# Initialize redeemed orders from file
redeemed_orders = load_redeemed_orders()

async def get_weather_forecast(date_time_utc, latitude, longitude):
    # Convert the match UTC date to a datetime object
    match_date = datetime.fromisoformat(date_time_utc).date()

    # Check if the match date is within the next 5 days
    if match_date > datetime.utcnow().date() + timedelta(days=5):
        return "No weather information available for dates more than 5 days ahead."

    # OpenWeatherMap API URL and Key
    url = f"http://api.openweathermap.org/data/2.5/forecast?lat={venue_lat}&lon={venue_long}&appid={openweather_api}&units=metric"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()

                # Loop through the list of forecasts
                for forecast in data.get('list', []):
                    # Convert forecast date to datetime object for comparison
                    forecast_date = datetime.fromtimestamp(forecast['dt']).date()

                    # Check if the forecast date matches the match date
                    if forecast_date == match_date:
                        # Extract weather details
                        weather = forecast['weather'][0]['description']
                        temp = forecast['main']['temp']
                        return f"Weather: {weather}, Temperature: {temp} F"

                # If no matching date is found in the forecasts
                return "Weather forecast not available for the selected date."
            else:
                # Handle errors (e.g., invalid API key, no response from server)
                return "Unable to fetch weather information."

    # Default message if unable to connect to the API
    return "Weather forecast service is currently unavailable."

# Bot event handlers
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        # Check which command was invoked
        if ctx.command.name in ['clear_orders', 'new_season', 'new_match']:
            await ctx.send("You do not have the proper authority to use this command.")
        else:
            # Handle other commands or provide a generic message
            await ctx.send("You are not authorized to use this command.")
    else:
        # Handle other types of errors here
        await ctx.send("An error occurred while processing the command.")

# Verify command
@bot.command(name='verify')
async def verify_order(ctx):
    await ctx.message.delete()

    # Check if the command is used in the allowed channels
    if ctx.channel.name not in ['lapsed-membership', 'lobby']:
        await ctx.send("This command can only be used in #lapsed-membership and #lobby.")
        return

    # Send the initial prompt and store the message object
    prompt_message = await ctx.send(f"{ctx.author.mention}, please enter your order ID number:")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        order_id_message = await bot.wait_for('message', check=check, timeout=60.0)
        await order_id_message.delete()  # Delete the message containing the order ID

        order_id = order_id_message.content
        if order_id.startswith('#'):
            order_id = order_id[1:]

        if order_id in redeemed_orders:
            response = await ctx.send("This order has already been redeemed.")
            await asyncio.sleep(10)
            await response.delete()
            return

        # Call WooCommerce API to check order validity
        response_data = await call_woocommerce_api(f"{wc_url}{order_id}")

        # Load the current membership role
        current_membership_role = load_current_role()

        if response_data:
            order_data = response_data
            order_status = order_data['status']
            order_date_str = order_data['date_created']  # Get the date the order was created
            membership_prefix = "ECS Membership 20"
            membership_found = any(membership_prefix in item['name'] for item in order_data.get('line_items', []))

            if not membership_found:
                await ctx.send("The order does not contain the required ECS Membership item.")
                return


            # Parse the order date
            order_date = datetime.fromisoformat(order_date_str)

            # Calculate the cutoff date (December 1st of the previous year)
            current_year = datetime.now().year
            cutoff_date = datetime(current_year - 1, 12, 1)

            # Check if order is after the cutoff date
            if order_date < cutoff_date:
                await ctx.send("This order is not valid for the current membership period.")
                return

            # Check if order is valid and not yet redeemed
            if order_status in ['processing', 'completed']:
                # Redeem the order and mark it as redeemed
                redeemed_orders[order_id] = str(ctx.author.id)
                save_redeemed_orders(redeemed_orders)
                role = discord.utils.get(ctx.guild.roles, name=current_membership_role)
        if role:
            await ctx.author.add_roles(role)
            response = await ctx.send("Thank you for validating your ECS membership!")
        else:
            response = await ctx.send(f"{current_membership_role} role not found.")

        await asyncio.sleep(10)
        await response.delete()

    except asyncio.TimeoutError:
        timeout_message = await ctx.send(f"{ctx.author.mention}, no order ID provided. Command canceled.")
        await asyncio.sleep(10)
        await timeout_message.delete()
    finally:
        await prompt_message.delete()  # Delete the initial prompt message

# Clear command
@bot.command(name='clear')
@commands.has_role("ECS Presidents")
async def clear_orders(ctx):
    # Send confirmation message
    message = await ctx.send("Are you sure you want to clear the ECS membership redemption history?  If you want to start a new season please use !newseason instead.  Reply with 'yes' to confirm.")

    # Check for the confirmation response
    def check(m):
        return m.author == ctx.author and m.content.lower() == 'yes'

    try:
        # Wait for a response for a certain amount of time (e.g., 30 seconds)
        await bot.wait_for('message', check=check, timeout=30.0)
    except asyncio.TimeoutError:
        await ctx.send("Clear command canceled.")
    else:
        # If confirmed, clear the redeemed orders
        redeemed_orders.clear()
        save_redeemed_orders(redeemed_orders)
        await ctx.send("Membership history cleared.  ECS Members can now !verify for the current season")

@bot.command(name='newseason')
@commands.has_role("ECS Presidents")
async def new_season(ctx):
    # Confirm starting a new season
    confirmation_msg = await ctx.send("Are you sure you want to start a new season? Reply with 'yes' to confirm.")
    def check_confirmation(m):
        return m.author == ctx.author and m.content.lower() == 'yes' and m.channel == ctx.channel

    try:
        await bot.wait_for('message', check=check_confirmation, timeout=30.0)
    except asyncio.TimeoutError:
        await ctx.send("New season command canceled.")
        return

    # Ask for the new ECS Membership role
    role_msg = await ctx.send("What is the new ECS Membership role?")
    def check_role(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        role_message = await bot.wait_for('message', check=check_role, timeout=60.0)
        new_role = role_message.content
        global current_membership_role
        current_membership_role = new_role

        save_current_role(current_membership_role)

    except asyncio.TimeoutError:
        await ctx.send("New season command canceled. No new role provided.")
        return

    await ctx.send(f"!verify will now assign the role {current_membership_role}. Do you want to clear the database? Reply with 'yes' to confirm.")

    # Confirm clearing the database
    try:
        await bot.wait_for('message', check=check_confirmation, timeout=30.0)

        # Clear the redeemed orders
        redeemed_orders.clear()
        save_redeemed_orders(redeemed_orders)
        await ctx.send(f"Order redemption history cleared. New season started with role {current_membership_role}.")
    except asyncio.TimeoutError:
        await ctx.send(f"Database not cleared. New season started with role {current_membership_role}.")

# Command to check order
@bot.command(name='checkorder')
@commands.has_role("ECS Presidents")
async def check_order(ctx):
    # Ask the user for the order ID
    await ctx.send(f"{ctx.author.mention}, please enter your order ID number:")

    # Check for the order ID response
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        order_id_message = await bot.wait_for('message', check=check, timeout=60.0)
        await order_id_message.delete()
        order_id = order_id_message.content

        if order_id.startswith('#'):
            order_id = order_id[1:]

        response_data = await call_woocommerce_api(f"{wc_url}{order_id}")
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
            response_message = "Order not found or access denied."

        await ctx.send(response_message)

    except asyncio.TimeoutError:
        await ctx.send(f"{ctx.author.mention}, no order ID provided. Command canceled.")

@bot.command(name='nextmatch')
async def next_match(ctx):
    match_info = await get_next_match(team_name)

    if isinstance(match_info, str):
        await ctx.send(match_info)
    else:
        opponent = match_info['opponent']
        date_time_utc = match_info['date_time']
        venue = match_info['venue']
        team_logo = match_info['team_logos'][0]  # Assuming the first logo is your team's logo

        # Convert UTC date/time to PST
        date_time_pst = convert_to_pst(date_time_utc)

        embed = discord.Embed(title="Next Match Details", color=0x1a75ff)
        embed.add_field(name="Opponent", value=opponent, inline=True)
        embed.add_field(name="Date and Time (PST)", value=date_time_pst, inline=True)
        embed.add_field(name="Venue", value=venue, inline=True)
        embed.set_image(url=team_logo)  # Set only the team logo as an image

        await ctx.send(embed=embed)

# Command to create a new match thread
@bot.command(name='newmatch')
@commands.has_role("ECS Presidents")
async def new_match(ctx):
    match_info = await get_next_match(team_name)

    if isinstance(match_info, str):
        await ctx.send(match_info)
        return

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

        # Convert the match time from UTC to PST (as a datetime object)
        match_time_pst = convert_to_pst(date_time_utc)
        event_start_time_pst = match_time_pst - timedelta(hours=1)

        # Format times for display
        date_time_pst_formatted = match_time_pst.strftime('%m/%d/%Y %I:%M %p PST')
        event_start_str = event_start_time_pst.strftime('%m/%d/%Y %I:%M %p PST')

        # Check if event already exists
        existing_events = await ctx.guild.fetch_scheduled_events()
        event_exists = any(
            event.name == "March to the Match" and 
            event.start_time == event_start_time_pst for event in existing_events
        )

        if not event_exists:
            try:
                # Create a scheduled event
                event = await ctx.guild.create_scheduled_event(
                    name="March to the Match",
                    start_time=event_start_time_pst,
                    end_time=event_start_time_pst + timedelta(hours=2),
                    description=f"March to the Match for {team_name} vs {opponent}",
                    location="117 S Washington St, Seattle, WA 98104",
                    entity_type=discord.EntityType.external,
                    privacy_level=discord.PrivacyLevel.guild_only
                )
                await ctx.send(f"Event created: 'March to the Match' starting at {event_start_str}.")
            except Exception as e:
                await ctx.send(f"Failed to create event: {e}")
        else:
            await ctx.send("An event for this match has already been scheduled.")

    # Use the formatted PST time for the thread name and message
    thread_name = f"Match Thread: {team_name} vs {opponent} - {date_time_pst_formatted}"

    channel = discord.utils.get(ctx.guild.channels, name='match-thread')
    if channel and isinstance(channel, discord.ForumChannel):
        # Fetch existing threads
        existing_threads = channel.threads
        
        # Check if a thread for this match already exists
        for thread in existing_threads:
            if thread.name == thread_name:
                await ctx.send("Next match thread already created.")
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
        f"{weather_forecast}"  # Include weather information here
    )

    # Creating the embed message
    embed = discord.Embed(
        title=thread_name,
        description=starter_message,
        color=0x1a75ff  # You can change the color as per your preference
    )
    # Set the team logo as a large image in the embed
    embed.set_image(url=match_info['team_logos'][0])  # Assuming the first logo is your team's logo

    channel = discord.utils.get(ctx.guild.channels, name='match-thread')
    if channel:
        if isinstance(channel, discord.ForumChannel):
            thread, initial_message = await channel.create_thread(name=thread_name, auto_archive_duration=60, embed=embed)
            await ctx.send(f"Match thread created: [Click here to view the thread](https://discord.com/channels/{ctx.guild.id}/{channel.id}/{thread.id})")
        else:
            await ctx.send("The channel is not a forum. Please use a forum channel.")
    else:
        await ctx.send("Match thread channel not found.")

# Run the bot
bot.run(bot_token)