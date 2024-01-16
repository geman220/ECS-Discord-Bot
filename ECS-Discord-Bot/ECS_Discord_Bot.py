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
import traceback
from collections import defaultdict
import sqlite3

load_dotenv()

intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.messages = True
intents.guilds = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

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
BOT_VERSION = "1.1.0"
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

    # Check if user has already made a prediction for this match
    c.execute("SELECT * FROM predictions WHERE match_id=? AND user_id=?", (match_id, user_id))
    if c.fetchone():
        conn.close()
        return False

    # Insert new prediction
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
    # Ensure both datetimes are offset-aware and in the same timezone (UTC in this case)
    now_utc = datetime.now(pytz.utc)
    delay = (match_start_time - now_utc).total_seconds()

    if delay > 0:
        await asyncio.sleep(delay)

        # Send a message indicating that predictions are closed
        await thread.send("Predictions closed.")

        predictions = get_predictions(match_id)
        result_message = "Predictions for the match:\n" + "\n".join(f"{pred[0]}: {pred[1]} votes" for pred in predictions)
        await thread.send(result_message)

        # Mark the match as closed for predictions
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

async def get_weather_forecast(ctx, date_time_utc, latitude, longitude):
    match_date = datetime.fromisoformat(date_time_utc).date()

    if match_date > datetime.utcnow().date() + timedelta(days=5):
        return "No weather information available for dates more than 5 days ahead."

    url = f"http://api.openweathermap.org/data/2.5/forecast?lat={latitude}&lon={longitude}&appid={openweather_api}&units=metric"

    response = await send_async_http_request(ctx, url)
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

@bot.event
async def on_ready():
    # Check if the update_channel_id.txt file exists
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
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("Sorry, I can't find that command.")
    elif isinstance(error, commands.MissingRole):
        if ctx.command.name in ['clear_orders', 'new_season', 'new_match', 'version']:
            await ctx.send("You do not have the proper permission to use this command.")
        else:
            await ctx.send("You are not authorized to use this command.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Invalid argument. Please check your command and try again.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"This command is on cooldown. Please try again after {error.retry_after:.2f} seconds.")
    else:
        print(f"Unhandled command error: {error}")
        await ctx.send("An error occurred while processing the command.")

@bot.command(name='version')
async def bot_version(ctx):
    if str(ctx.author.id) == '129059682257076224' or any(role.name == 'ECS Presidents' for role in ctx.author.roles):
        user_id = '129059682257076224'
        await ctx.send(f"ECS Bot - developed by <@{user_id}> version {BOT_VERSION}")

@bot.command(name='update')
@commands.has_role("ECS Presidents")
async def update_bot(ctx):
    with open('/root/update_channel_id.txt', 'w') as f:
        f.write(str(ctx.channel.id))

    headers = {'Authorization': f'Bearer {flask_token}'}
    async with aiohttp.ClientSession() as session:
        async with session.post(flask_url, headers=headers) as response:
            if response.status == 200:
                await ctx.send("Bot is updating...")
            else:
                response_text = await response.text()
                await ctx.send(f"Update failed: {response_text}")

@bot.command(name='record')
async def team_record(ctx):
    match_info, record = await get_next_match(ctx, team_name)
    if record:
        record_info, team_logo_url = record
        embed = discord.Embed(title=f"{team_name} Record", color=0x00ff00)
        if team_logo_url:
            embed.set_thumbnail(url=team_logo_url)
        for stat, value in record_info.items():
            readable_stat = format_stat_name(stat)
            embed.add_field(name=readable_stat, value=str(value), inline=True)
        
        await ctx.send(embed=embed)
    else:
        await ctx.send("Error fetching record.")

@bot.command(name='predict')
async def predict(ctx, *, prediction: str):
    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send("This command can only be used in match threads.")
        return

    match_id = match_thread_map.get(str(ctx.channel.id))
    if not match_id:
        await ctx.send("This thread is not associated with an active match prediction.")
        return

    # Check if predictions are closed for this match
    if match_id in closed_matches:
        await ctx.send("Predictions are closed for this match.")
        return

    user_id = str(ctx.author.id)
    if insert_prediction(match_id, user_id, prediction):
        await ctx.message.add_reaction("👍")
    else:
        await ctx.send("You have already made a prediction for this match.")

@bot.command(name='predictions')
async def show_predictions(ctx):
    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send("This command can only be used in match threads.")
        return

    match_id = match_thread_map.get(str(ctx.channel.id))
    if not match_id:
        await ctx.send("This thread is not associated with an active match prediction.")
        return

    predictions = get_predictions(match_id)
    if not predictions:
        await ctx.send("No predictions have been made for this match.")
        return

    # Create an embed for displaying predictions
    embed = discord.Embed(title="Match Predictions", color=0x00ff00)
    # Correctly access the guild icon URL
    if ctx.guild.icon:
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url)
    else:
        embed.set_author(name=ctx.guild.name)

    embed.set_footer(text="Predictions are subject to change before match kickoff.")

    for prediction, count in predictions:
        embed.add_field(name=prediction, value=f"{count} prediction(s)", inline=True)

    await ctx.send(embed=embed)

@bot.command(name='verify')
async def verify_order(ctx):
    await ctx.message.delete()

    # Check if the command is used in the allowed channels
    #if ctx.channel.name not in ['lapsed-membership', 'lobby']:
     #   await ctx.send("This command can only be used in #lapsed-membership and #lobby.")
     #   return

    prompt_message = await ctx.send(f"{ctx.author.mention}, please enter your order ID number:")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        order_id_message = await bot.wait_for('message', check=check, timeout=60.0)
        await order_id_message.delete()

        order_id = order_id_message.content
        if order_id.startswith('#'):
            order_id = order_id[1:]

        if order_id in redeemed_orders:
            response = await ctx.send("This order has already been redeemed.")
            await asyncio.sleep(10)
            await response.delete()
            return

        full_url = f"{wc_url}{order_id}"
        response_data = await call_woocommerce_api(ctx, full_url)
        current_membership_role = load_current_role()

        if response_data:
            order_data = response_data
            order_status = order_data['status']
            order_date_str = order_data['date_created']
            membership_prefix = "ECS Membership 20"
            membership_found = any(membership_prefix in item['name'] for item in order_data.get('line_items', []))

            if not membership_found:
                await ctx.send("The order does not contain the required ECS Membership item.")
                return

            order_date = datetime.fromisoformat(order_date_str)
            current_year = datetime.now().year
            cutoff_date = datetime(current_year - 1, 12, 1)

            if order_date < cutoff_date:
                await ctx.send("This order is not valid for the current membership period.")
                return

            if order_status in ['processing', 'completed']:
                redeemed_orders[order_id] = str(ctx.author.id)
                save_redeemed_orders(redeemed_orders)
                role = discord.utils.get(ctx.guild.roles, name=current_membership_role)
        else:
            invalid_order_message = await ctx.send("Invalid order number.")
            await asyncio.sleep(10)
            await invalid_order_message.delete()
            return

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
        await prompt_message.delete()

@bot.command(name='clear')
@commands.has_role("ECS Presidents")
async def clear_orders(ctx):
    message = await ctx.send("Are you sure you want to clear the ECS membership redemption history?  If you want to start a new season please use !newseason instead.  Reply with 'yes' to confirm.")

    def check(m):
        return m.author == ctx.author and m.content.lower() == 'yes'

    try:
        await bot.wait_for('message', check=check, timeout=30.0)
    except asyncio.TimeoutError:
        await ctx.send("Clear command canceled.")
    else:
        redeemed_orders.clear()
        save_redeemed_orders(redeemed_orders)
        await ctx.send("Membership history cleared.  ECS Members can now !verify for the current season")

@bot.command(name='newseason')
@commands.has_role("ECS Presidents")
async def new_season(ctx):
    confirmation_msg = await ctx.send("Are you sure you want to start a new season? Reply with 'yes' to confirm.")
    def check_confirmation(m):
        return m.author == ctx.author and m.content.lower() == 'yes' and m.channel == ctx.channel

    try:
        await bot.wait_for('message', check=check_confirmation, timeout=30.0)
    except asyncio.TimeoutError:
        await ctx.send("New season command canceled.")
        return

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

    try:
        await bot.wait_for('message', check=check_confirmation, timeout=30.0)

        redeemed_orders.clear()
        save_redeemed_orders(redeemed_orders)
        await ctx.send(f"Order redemption history cleared. New season started with role {current_membership_role}.")
    except asyncio.TimeoutError:
        await ctx.send(f"Database not cleared. New season started with role {current_membership_role}.")


@bot.command(name='checkorder')
@commands.has_role("ECS Presidents")
async def check_order(ctx):
    await ctx.send(f"{ctx.author.mention}, please enter your order ID number:")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        order_id_message = await bot.wait_for('message', check=check, timeout=60.0)
        await order_id_message.delete()
        order_id = order_id_message.content

        if order_id.startswith('#'):
            order_id = order_id[1:]

        full_url = f"{wc_url}{order_id}"
        response_data = await call_woocommerce_api(ctx, full_url)
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

        await ctx.send(response_message)

    except asyncio.TimeoutError:
        await ctx.send(f"{ctx.author.mention}, no order ID provided. Command canceled.")

@bot.command(name='nextmatch')
async def next_match(ctx):
    match_info, team_record = await get_next_match(ctx, team_name)

    if isinstance(match_info, str):
        await ctx.send(match_info)
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

    await ctx.send(embed=embed)

@bot.command(name='newmatch')
@commands.has_role("ECS Presidents")
async def new_match(ctx):
    global match_thread_map 
    match_info, team_record = await get_next_match(ctx, team_name)

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
        weather_forecast = await get_weather_forecast(ctx, date_time_utc, venue_lat, venue_long)
        weather_forecast = f"\n\n**Weather**: {weather_forecast}"
        match_time_pst = convert_to_pst(date_time_utc)
        event_start_time_pst = match_time_pst - timedelta(hours=1)
        date_time_pst_formatted = match_time_pst.strftime('%m/%d/%Y %I:%M %p PST')
        event_start_str = event_start_time_pst.strftime('%m/%d/%Y %I:%M %p PST')

        existing_events = await ctx.guild.fetch_scheduled_events()
        event_exists = any(
            event.name == "March to the Match" and 
            event.start_time == event_start_time_pst for event in existing_events
        )

        if not event_exists:
            try:
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

    thread_name = f"Match Thread: {team_name} vs {opponent} - {date_time_pst_formatted}"

    channel = discord.utils.get(ctx.guild.channels, name='match-thread')
    if channel and isinstance(channel, discord.ForumChannel):
        existing_threads = channel.threads

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
        f"{weather_forecast}"
    )

    embed = discord.Embed(
        title=thread_name,
        description=starter_message,
        color=0x1a75ff
    )
    embed.set_image(url=match_info['team_logos'][0])

    channel = discord.utils.get(ctx.guild.channels, name='match-thread')
    if channel:
        if isinstance(channel, discord.ForumChannel):
            thread, initial_message = await channel.create_thread(name=thread_name, auto_archive_duration=60, embed=embed)
            match_thread_map[thread.id] = match_info['match_id']
            insert_match_thread(thread.id, match_info['match_id'])

            match_thread_map = load_match_threads()

            # Send a message in the thread for score prediction
            await thread.send(f"Predict the score! Use `!predict {team_name}-Score {opponent}-Score` `example: !predict 3-0` to participate.  Predictions end at kickoff!")

            # Schedule the poll closing as a background task
            match_start_time = convert_to_pst(date_time_utc)  # Convert match start time to PST
            asyncio.create_task(schedule_poll_closing(match_start_time, match_info['match_id'], thread))

            await ctx.send(f"Match thread created: [Click here to view the thread](https://discord.com/channels/{ctx.guild.id}/{channel.id}/{thread.id})")
        else:
            await ctx.send("Match thread channel not found.")

bot.run(bot_token)