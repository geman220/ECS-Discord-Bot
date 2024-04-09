# match_utils.py

from typing import Tuple
import asyncio
import discord
import re
import pytz
from datetime import datetime, timedelta
from dateutil import parser, tz
from config import BOT_CONFIG
from api_helpers import (
    call_woocommerce_api, 
    fetch_espn_data,
)
from utils import convert_to_pst
from database import (
    insert_match_thread, 
    get_predictions, 
    get_db_connection, 
    PREDICTIONS_DB_PATH, 
    insert_match_schedule,
)
from common import (
    load_match_dates,
    create_event_if_necessary,
    get_weather_forecast,
    venue_lat,
    venue_long,
    prepare_starter_message,
    team_id,
)

wc_url = BOT_CONFIG["wc_url"]
team_name = BOT_CONFIG["team_name"]

closed_polls = set()
completed_matches = set()
closed_matches = set()

async def get_away_match(opponent=None):
    product_url = wc_url.replace("orders/", "products?category=765197886")
    products = await call_woocommerce_api(product_url)

    if products:
        matches = []

        for product in products:
            title = product.get("name", "")
            match_date = extract_date_from_title(title)

            if match_date and match_date >= datetime.now():
                link = product.get("permalink")
                matches.append((match_date, title, link))

        matches.sort()

        if opponent:
            found_matches = [
                match for match in matches if opponent.lower() in match[1].lower()
            ]
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


async def get_team_record(team_id):
    data = await fetch_espn_data(f"sports/soccer/usa.1/teams/{team_id}")
    if data and "team" in data:
        record_data = data["team"].get("record", {}).get("items", [])
        team_logo_url = (
            data["team"]["logos"][0]["href"] if data["team"].get("logos") else None
        )
        if record_data:
            stats = record_data[0].get("stats", [])
            record_info = {stat["name"]: stat["value"] for stat in stats}
            return record_info, team_logo_url
    return "Record not available", None


async def get_next_match(team_id, for_automation=False):
    now = datetime.now(pytz.timezone("America/Los_Angeles"))
    end_time = now + timedelta(hours=24) if for_automation else None

    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        if for_automation:
            query = """
                SELECT match_id, opponent, date_time, is_home_game, match_summary_link, match_stats_link, match_commentary_link, venue
                FROM match_schedule 
                WHERE date_time > ? AND date_time <= ? AND thread_created = 0
                ORDER BY date_time ASC
                LIMIT 1
            """
            c.execute(query, (now, end_time))
        else:
            query = """
                SELECT match_id, opponent, date_time, is_home_game, match_summary_link, match_stats_link, match_commentary_link, venue, thread_created
                FROM match_schedule 
                WHERE date_time > ?
                ORDER BY date_time ASC
                LIMIT 1
            """
            c.execute(query, (now,))
        match_data = c.fetchone()

        if match_data:
            if for_automation:
                match_id, opponent, date_time, is_home_game, summary_link, stats_link, commentary_link, venue = match_data
            else:
                match_id, opponent, date_time, is_home_game, summary_link, stats_link, commentary_link, venue, thread_created = match_data

            if isinstance(date_time, str):
                date_time = datetime.fromisoformat(date_time)

            team_logo_url = f"https://a.espncdn.com/i/teamlogos/soccer/500/{team_id}.png"
            match_name = f"{team_name} vs {opponent}"
            match_info = {
                "match_id": match_id,
                "opponent": opponent,
                "date_time": date_time,
                "is_home_game": is_home_game,
                "venue": venue,
                "team_logo": team_logo_url,
                "name": match_name,
                "match_summary_link": summary_link,
                "match_stats_link": stats_link,
                "commentary_link": commentary_link
            }
            if not for_automation:
                match_info["thread_created"] = thread_created
            return match_info

    return None


def extract_match_details(event):
    match_id = event.get("id")
    date_time_utc = event.get("date")
    name = event.get("name")
    venue = event.get("competitions", [{}])[0].get("venue", {}).get("fullName")

    date_time_pst = convert_to_pst(date_time_utc)

    competitors = event.get("competitions", [{}])[0].get("competitors", [])
    team_data = next((comp for comp in competitors if comp["team"]["id"] == team_id), None)

    if team_data:
        opponent = next(
            op["team"]["displayName"]
            for op in competitors
            if op["team"]["id"] != team_id
        )
        is_home_game = team_data["homeAway"] == "home"
        team_logo = team_data["team"].get("logos", [{}])[0].get("href")
    else:
        opponent = "Unknown"
        is_home_game = False
        team_logo = "Unknown"

    summary_link, stats_link, commentary_link = extract_links(event)

    return {
        "match_id": match_id,
        "opponent": opponent,
        "date_time": date_time_pst,
        "venue": venue,
        "name": name,
        "team_logo": team_logo,
        "is_home_game": is_home_game,
        "match_summary_link": summary_link,
        "match_stats_link": stats_link,
        "match_commentary_link": commentary_link,
    }


def extract_links(event):
    summary_link = next(
        (link["href"] for link in event.get("links", []) if "summary" in link["rel"]),
        "Unavailable",
    )
    stats_link = next(
        (link["href"] for link in event.get("links", []) if "stats" in link["rel"]),
        "Unavailable",
    )
    commentary_link = next(
        (link["href"] for link in event.get("links", []) if "commentary" in link["rel"]),
        "Unavailable",
    )
    return summary_link, stats_link, commentary_link


def generate_thread_name(match_info):
    date_time_pst = match_info["date_time"]
    date_time_pst_formatted = date_time_pst.strftime("%m/%d/%Y %I:%M %p PST")
    return f"Match Thread: {match_info['name']} - {date_time_pst_formatted}"


async def prepare_match_environment(guild: discord.Guild, match_info: dict) -> Tuple[str, str]:
    event_response = ""
    weather_forecast = ""

    if match_info.get("is_home_game"):
        weather_forecast = await get_weather_forecast(
            convert_to_pst(match_info["date_time"]), venue_lat, venue_long
        )
        event_response = await create_event_if_necessary(guild, match_info)

    return event_response, weather_forecast


async def create_and_manage_thread(
    guild: discord.Guild, match_info: dict, cog, channel: discord.abc.GuildChannel, weather_forecast: str
):
    date_time_pst = match_info["date_time"]
    date_time_pst_formatted = date_time_pst.strftime("%m/%d/%Y %I:%M %p PST")
    thread_name = generate_thread_name(match_info)

    weather_info = weather_forecast if weather_forecast else ""

    starter_message, embed = prepare_starter_message(
        match_info,
        date_time_pst_formatted,
        match_info["team_logo"],
        weather_info,
        thread_name,
    )

    thread_response = await create_match_thread(
        guild, thread_name, embed, match_info, cog, channel
    )

    return thread_response


async def create_match_thread(
    guild: discord.Guild, thread_name, embed, match_info, match_commands_cog, channel: discord.abc.GuildChannel
):
    try:
        if isinstance(channel, discord.ForumChannel):
            thread, initial_message = await channel.create_thread(
                name=thread_name, auto_archive_duration=60, embed=embed
            )
            match_id = match_info["match_id"]
            thread_id = str(thread.id)

            match_commands_cog.update_thread_map(thread_id, match_id)
            insert_match_thread(thread_id, match_id)

            if channel.name == "match-thread":
                await thread.send(
                    f"Predict the score! Use `/predict {match_info['name']}-Score - {match_info['opponent']}-Score` to participate. Predictions end at kickoff!"
                )
                if isinstance(match_info["date_time"], datetime):
                    match_start_time = match_info["date_time"]
                else:
                    match_start_time = parser.parse(match_info["date_time"])
                asyncio.create_task(
                    schedule_poll_closing(match_start_time, match_info["match_id"], thread, match_commands_cog)
                )

            return f"Thread created in {channel.name}: [Click here to view the thread](https://discord.com/channels/{guild.id}/{channel.id}/{thread.id})"
        else:
            return f"Provided channel is not a forum channel."
    except Exception as e:
        print(f"Error creating thread: {e}")
        return f"Error occurred while creating thread: {e}"


async def schedule_poll_closing(match_start_time, match_id, thread, match_commands_cog):
    if not match_start_time.tzinfo:
        match_start_time = match_start_time.replace(tzinfo=tz.gettz('America/Los_Angeles'))

    match_start_time_utc = match_start_time.astimezone(tz.tzutc())

    now_utc = datetime.now(tz.tzutc())
    delay = (match_start_time_utc - now_utc).total_seconds()

    if delay > 0:
        await asyncio.sleep(delay)

    await thread.send("Predictions closed.")

    predictions = get_predictions(match_id)
    result_message = "Predictions for the match:\n" + "\n".join(
        f"{pred[0]}: {pred[1]} votes" for pred in predictions
    )
    await thread.send(result_message)

    closed_polls.add(match_id)
        
    asyncio.create_task(post_live_updates(match_id, thread, match_commands_cog))


def update_live_updates_status(match_id, status):
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE match_schedule SET live_updates_active = ? WHERE match_id = ?", (status, match_id))
        conn.commit()
        

async def post_live_updates(match_id, thread, match_commands_cog):
    reported_events = set()
    halftime_reported = False
    fulltime_reported = False

    while match_id not in completed_matches:
        update_live_updates_status(match_id, 1)
        match_data = await fetch_espn_data(f"sports/soccer/usa.1/scoreboard/{match_id}")
        if match_data:
            match_status = match_data["competitions"][0]["status"]["type"]["name"]

            if match_status == "STATUS_HALFTIME" and not halftime_reported:
                halftime_message = "Halftime! " + format_current_score(match_data)
                await thread.send(halftime_message)
                halftime_reported = True

            elif match_status == "STATUS_FULL_TIME":
                if not fulltime_reported:
                    fulltime_message = "Full Time! " + format_current_score(match_data)
                    await thread.send(fulltime_message)
                    fulltime_reported = True
                    update_live_updates_status(match_id, 0)
                    completed_matches.add(match_id)
                    break

            else:
                update_embed = format_match_update(match_data, reported_events, team_id)
                if update_embed:
                    await thread.send(embed=update_embed)
        
        await asyncio.sleep(10)


def format_current_score(match_data):
    teams = match_data["competitions"][0]["competitors"]
    home_team = teams[0]["team"]["displayName"]
    away_team = teams[1]["team"]["displayName"]
    home_score = teams[0]["score"]
    away_score = teams[1]["score"]
    return f"{home_team} {home_score} - {away_score} {away_team}"


def format_match_update(match_data, reported_events, team_id):
    try:
        embed = discord.Embed(title="Match Update", color=0x1D2951)
        teams = match_data["competitions"][0]["competitors"]

        for event in match_data["competitions"][0]["details"]:
            event_type = event.get("type", {}).get("text", "")
            event_team_id = event.get("team", {}).get("id", "")
            event_team_name = next((team["team"]["displayName"] for team in teams if team["id"] == event_team_id), None)
            event_time = event.get("clock", {}).get("displayValue", "")
            event_identifier = f"{event_type}-{event_time}-{event_team_id}"

            if event_identifier in reported_events:
                continue

            reported_events.add(event_identifier)
            
            soccer_ball_emoji = "\U000026BD"

            if "Goal" in event_type:
                goal_scorer = next((athlete["displayName"] for athlete in event.get("athletesInvolved", [])), "Unknown")
                goal_message = f"{goal_scorer} scored a goal at {event_time}"
                message_prefix = f"SOUNDERS FC GOAL! " if event_team_id == team_id else "Goal "
                final_message = message_prefix + goal_message
                embed.add_field(name=f"{soccer_ball_emoji} {event_type}", value=final_message, inline=False)

            elif "Penalty" in event_type:
                penalty_taker = next((athlete["displayName"] for athlete in event.get("athletesInvolved", [])), "Unknown")
                if "Scored" in event_type:
                    penalty_message = f"{penalty_taker} scored a penalty at {event_time}"
                    message_prefix = f"SOUNDERS FC GOAL! " if event_team_id == team_id else "Goal "
                else:
                    penalty_message = f"{penalty_taker} penalty {event_type.lower()} at {event_time}"
                    message_prefix = ""

                final_message = message_prefix + penalty_message
                embed.add_field(name=f"{soccer_ball_emoji} {event_type}", value=final_message, inline=False)

            elif event_type == "Yellow Card":
                yellow_card_emoji = "\U0001F7E8"
                player = next((athlete["displayName"] for athlete in event.get("athletesInvolved", [])), "Unknown")
                embed.add_field(name=f"{yellow_card_emoji} Yellow Card", value=f"{player} ({event_team_name}) at {event_time}", inline=False)

            elif event_type == "Red Card":
                red_card_emoji = "\U0001F7E5"
                player = next((athlete["displayName"] for athlete in event.get("athletesInvolved", [])), "Unknown")
                embed.add_field(name=f"{red_card_emoji} Red Card", value=f"{player} ({event_team_name}) at {event_time}", inline=False)

        return embed if embed.fields else None

    except KeyError as e:
        print(f"Key error in format_match_update: {e}")
        return None


async def get_matches_for_calendar():
    match_dates = load_match_dates()
    all_matches = []

    for date in match_dates:
        try:
            match_data = await fetch_espn_data(
                f"sports/soccer/usa.1/scoreboard?dates={date}"
            )

            if not match_data or 'events' not in match_data:
                continue

            for event in match_data['events']:
                if team_name in event.get("name", ""):
                    match_details = extract_match_details(event)
                    insert_match_schedule(
                        match_details['match_id'],
                        match_details['opponent'],
                        match_details['date_time'],
                        match_details['is_home_game'],
                        match_details['match_summary_link'],
                        match_details['match_stats_link'],
                        match_details['match_commentary_link'],
                        match_details['venue']
                    )
                    all_matches.append(match_details)
        except Exception as e:
            print(f"Error processing date {date}: {e}")
            continue

    return all_matches
