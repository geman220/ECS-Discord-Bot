# match_utils.py

import asyncio
import discord
import re
import pytz
from datetime import datetime
from config import BOT_CONFIG
from api_helpers import call_woocommerce_api, fetch_espn_data
from utils import convert_to_pst
from database import insert_match_thread, get_predictions
from common import load_match_dates, create_event_if_necessary, get_weather_forecast, venue_lat, venue_long, prepare_starter_message

wc_url = BOT_CONFIG['wc_url']
team_name = BOT_CONFIG['team_name']

closed_matches = set()

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
            found_matches = [match for match in matches if opponent.lower() in match[1].lower()]
            if found_matches:
                return found_matches[0][1], found_matches[0][2]
            else:
                return None

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

def generate_thread_name(match_info):
    date_time_pst = convert_to_pst(match_info['date_time'])
    date_time_pst_formatted = date_time_pst.strftime('%m/%d/%Y %I:%M %p PST')
    return f"Match Thread: {match_info['name']} - {date_time_pst_formatted}"

async def prepare_match_environment(interaction: discord.Interaction, match_info: dict) -> str:
    if match_info.get('is_home_game'):
        weather_forecast = await get_weather_forecast(convert_to_pst(match_info['date_time']), venue_lat, venue_long)
        event_response = await create_event_if_necessary(interaction, match_info)
        if event_response:
            return event_response
        return weather_forecast
    return ""

async def create_and_manage_thread(interaction: discord.Interaction, match_info: dict, cog):
    date_time_pst = convert_to_pst(match_info['date_time'])
    date_time_pst_formatted = date_time_pst.strftime('%m/%d/%Y %I:%M %p PST')
    thread_name = generate_thread_name(match_info)

    weather_forecast = ""
    starter_message, embed = await prepare_starter_message(match_info, date_time_pst_formatted, match_info['team_logo'], weather_forecast, thread_name)

    channel_name = "match-thread"
    thread_response = await create_match_thread(interaction, thread_name, embed, match_info, cog, channel_name)

    return thread_response

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
