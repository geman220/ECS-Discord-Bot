# match_utils.py

import logging
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
    load_existing_dates,
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

logger = logging.getLogger(__name__)

wc_url = BOT_CONFIG["wc_url"]
team_name = BOT_CONFIG["team_name"]

closed_polls = set()
completed_matches = set()
closed_matches = set()

async def get_away_match(opponent=None):
    logger.info(f"Fetching away match for opponent: {opponent}")
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
            found_matches = [match for match in matches if opponent.lower() in match[1].lower()]
            if found_matches:
                logger.info(f"Found away match for opponent {opponent}: {found_matches[0]}")
                return found_matches[0][1], found_matches[0][2]
            else:
                return None

        if matches:
            closest_match = matches[0]
            logger.info(f"Found closest away match: {closest_match}")
            return closest_match[1], closest_match[2]

    logger.warning("No away matches found.")
    return None


def extract_date_from_title(title):
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", title)
    if match:
        date_str = match.group(0)
        try:
            match_date = datetime.strptime(date_str, "%Y-%m-%d")
            logger.info(f"Extracted date {match_date} from title {title}")
            return match_date
        except ValueError as e:
            logger.error(f"Error parsing date from title {title}: {e}")
            return None
    logger.warning(f"No date found in title {title}")
    return None


async def get_team_record(team_id):
    logger.info(f"Fetching team record for team ID: {team_id}")
    data = await fetch_espn_data(f"sports/soccer/usa.1/teams/{team_id}")
    if data and "team" in data:
        record_data = data["team"].get("record", {}).get("items", [])
        team_logo_url = data["team"].get("logos", [{}])[0].get("href") if data["team"].get("logos") else None
        if record_data:
            stats = record_data[0].get("stats", [])
            record_info = {stat["name"]: stat["value"] for stat in stats}
            logger.info(f"Fetched team record: {record_info}")
            return record_info, team_logo_url
    logger.warning("Team record not available.")
    return "Record not available", None


async def get_next_match(team_id, for_automation=False):
    logger.info(f"Fetching next match for team ID: {team_id} (for automation: {for_automation})")
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
            logger.info(f"Fetched next match info: {match_info}")
            return match_info

    logger.warning("No next match found.")
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

    match_details = {
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

    logger.info(f"Extracted match details: {match_details}")
    return match_details


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
    thread_name = f"Match Thread: {match_info['name']} - {date_time_pst_formatted}"
    logger.info(f"Generated thread name: {thread_name}")
    return thread_name


async def prepare_match_environment(guild: discord.Guild, match_info: dict) -> Tuple[str, str]:
    event_response = ""
    weather_forecast = ""

    if match_info.get("is_home_game"):
        weather_forecast = await get_weather_forecast(
            convert_to_pst(match_info["date_time"]), venue_lat, venue_long
        )
        event_response = await create_event_if_necessary(guild, match_info)
        logger.info(f"Prepared match environment: event_response={event_response}, weather_forecast={weather_forecast}")

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

    logger.info(f"Thread management response: {thread_response}")
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

            logger.info(f"Thread created in {channel.name}: {thread.id}")
            return f"Thread created in {channel.name}: [Click here to view the thread](https://discord.com/channels/{guild.id}/{channel.id}/{thread.id})"
        else:
            logger.error("Provided channel is not a forum channel.")
            return f"Provided channel is not a forum channel."
    except Exception as e:
        logger.error(f"Error creating thread: {e}")
        return f"Error occurred while creating thread: {e}"


async def schedule_poll_closing(match_start_time, match_id, thread, match_commands_cog):
    if not match_start_time.tzinfo:
        match_start_time = match_start_time.replace(tzinfo=tz.gettz('America/Los_Angeles'))

    match_start_time_utc = match_start_time.astimezone(tz.tzutc())
    now_utc = datetime.now(tz.tzutc())
    delay = (match_start_time_utc - now_utc).total_seconds()

    if delay > 0:
        await asyncio.sleep(delay)

    try:
        await thread.send("Predictions closed.")
        predictions = get_predictions(match_id)
        result_message = "Predictions for the match:\n" + "\n".join(
            f"{pred[0]}: {pred[1]} votes" for pred in predictions
        )
        await thread.send(result_message)
        logging.info(f"Predictions closed message sent for match {match_id}")

        closed_polls.add(match_id)
        asyncio.create_task(post_live_updates(match_id, thread, match_commands_cog))
    except Exception as e:
        logging.error(f"Error closing predictions for match {match_id}: {e}")


def update_live_updates_status(match_id, status):
    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE match_schedule SET live_updates_active = ? WHERE match_id = ?", (status, match_id))
        conn.commit()
    logger.info(f"Updated live updates status for match {match_id} to {status}")
        

async def post_live_updates(match_id, thread, match_commands_cog):
    reported_events = set()
    halftime_reported = False
    fulltime_reported = False

    while match_id not in completed_matches:
        try:
            update_live_updates_status(match_id, 1)
            match_data = await fetch_espn_data(f"sports/soccer/usa.1/scoreboard/{match_id}")
            if match_data:
                match_status = match_data["competitions"][0]["status"]["type"]["name"]

                if match_status == "STATUS_HALFTIME" and not halftime_reported:
                    halftime_message = "Halftime! " + format_current_score(match_data)
                    await thread.send(halftime_message)
                    halftime_reported = True
                    logging.info(f"Halftime update sent for match {match_id}")

                elif match_status == "STATUS_FULL_TIME":
                    if not fulltime_reported:
                        fulltime_message = "Full Time! " + format_current_score(match_data)
                        await thread.send(fulltime_message)
                        fulltime_reported = True
                        update_live_updates_status(match_id, 0)
                        completed_matches.add(match_id)
                        logging.info(f"Full time update sent for match {match_id}")
                        break

                else:
                    update_embed = format_match_update(match_data, reported_events, team_id)
                    if update_embed:
                        await thread.send(embed=update_embed)
                        logging.info(f"Live update sent for match {match_id}")

            await asyncio.sleep(10)
        except Exception as e:
            logging.error(f"Error posting live updates for match {match_id}: {e}")
            await asyncio.sleep(10)


def format_current_score(match_data):
    teams = match_data["competitions"][0]["competitors"]
    home_team = teams[0]["team"]["displayName"]
    away_team = teams[1]["team"]["displayName"]
    home_score = teams[0]["score"]
    away_score = teams[1]["score"]
    current_score = f"{home_team} {home_score} - {away_score} {away_team}"
    logger.info(f"Formatted current score: {current_score}")
    return current_score


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

        logger.info(f"Formatted match update: {embed.to_dict()}")
        return embed if embed.fields else None

    except KeyError as e:
        logger.error(f"Key error in format_match_update: {e}")
        return None


async def get_matches_for_calendar():
    match_dates = load_match_dates()
    existing_dates = load_existing_dates()
    new_dates = set(match_dates)
    existing_dates_set = set(existing_dates)

    dates_to_delete = existing_dates_set - new_dates
    dates_to_add = new_dates - existing_dates_set

    with get_db_connection(PREDICTIONS_DB_PATH) as conn:
        c = conn.cursor()
        for date in dates_to_delete:
            c.execute("DELETE FROM match_schedule WHERE date_time = ?", (date,))
            conn.commit()
            logger.info(f"Deleted matches for date: {date}")

    all_matches = []

    for date in dates_to_add:
        try:
            match_data = await fetch_espn_data(f"sports/soccer/usa.1/scoreboard?dates={date}")
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
                    logger.info(f"Inserted match schedule: {match_details}")
        except Exception as e:
            logger.error(f"Error processing date {date}: {e}")
            continue

    logger.info(f"Total matches for calendar: {len(all_matches)}")
    return all_matches

