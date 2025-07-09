# embeds.py - Discord embed creation functions

import discord
import random
from typing import Union
from utils import get_correct_predictions
from api.models.schemas import AvailabilityRequest

# Constants
TEAM_ID = '9726'

def get_emoji_for_response(response):
    if response == 'yes':
        return "👍"
    elif response == 'no':
        return "👎"
    elif response == 'maybe':
        return "🤷"
    else:
        return None

def create_team_embed(match_request: AvailabilityRequest, rsvp_data, team_type='home'):
    team_name = match_request.home_team_name if team_type == 'home' else match_request.away_team_name
    opponent_name = match_request.away_team_name if team_type == 'home' else match_request.home_team_name
    match_date = match_request.match_date
    match_time = match_request.match_time
    
    embed = discord.Embed(title=f"{team_name} vs {opponent_name}",
                          description=f"Date: {match_date}\nTime: {match_time}",
                          color=0x00ff00)
    
    if rsvp_data:
        for status in ['yes', 'no', 'maybe']:
            players = rsvp_data.get(status, [])
            player_names = ', '.join([player['player_name'] for player in players])
            emoji = get_emoji_for_response(status)
            embed.add_field(name=f"{emoji} {status.capitalize()} ({len(players)})", 
                            value=player_names or "None", 
                            inline=False)
    
    return embed

def create_match_embed(update_type, update_data):
    focus_team_id = str(TEAM_ID)  # Our team ID

    if update_type == "score_update":
        return create_score_update_embed(update_data, focus_team_id)
    elif update_type in ["match_event", "hype_event"]:
        return create_match_event_embed(update_data, focus_team_id, is_hype=(update_type == "hype_event"))
    elif update_type == "halftime":
        return create_halftime_embed(update_data, focus_team_id)
    elif update_type == "fulltime":
        # Extract match_id from update_data (ensure update_data contains it)
        match_id = update_data.get("match_id")
        return create_fulltime_embed(match_id, update_data, focus_team_id)
    elif update_type == "match_started":
        # Create a special kickoff embed to avoid duplicate messages
        return create_match_started_embed(update_data, focus_team_id)
    elif update_type in ["status_scheduled", "pre_match_info"]:
        return create_pre_match_embed(update_data, focus_team_id)
    else:
        embed = discord.Embed(
            title="Match Update",
            description="An update has occurred."
        )
        return embed

def create_match_started_embed(update_data, focus_team_id):
    """
    Create an embed for match kickoff.
    """
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.title = f"🏟️ Kickoff! {home_team_name} vs {away_team_name}"
    embed.color = discord.Color.green()
    
    # Check if our team is playing
    if home_team_id == focus_team_id:
        embed.description = f"**{home_team_name}** 0 - 0 {away_team_name}"
        embed.set_thumbnail(url=home_team.get('logo'))
        embed.add_field(name="Let's Go!", value="The match has started! Let's go Sounders! 💚", inline=False)
    elif away_team_id == focus_team_id:
        embed.description = f"{home_team_name} 0 - 0 **{away_team_name}**"
        embed.set_thumbnail(url=away_team.get('logo'))
        embed.add_field(name="Let's Go!", value="The match has started! Let's go Sounders! 💚", inline=False)
    else:
        embed.description = f"{home_team_name} 0 - 0 {away_team_name}"
        embed.color = discord.Color.blue()
        embed.add_field(name="Kickoff", value="The match has started!", inline=False)

    embed.add_field(name="Time", value="Kickoff", inline=True)
    
    return embed

def create_match_update_embed(update_data, focus_team_id):
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    match_status = update_data.get('match_status', "Unknown")
    time = update_data.get('time', "N/A")
    home_score = update_data.get('home_score', "0")
    away_score = update_data.get('away_score', "0")

    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()

    # Determine if the focus team is the home or away team
    if home_team_id == focus_team_id:
        # Our team is the home team
        embed.title = f"🏟️ Match Update: {home_team_name} vs {away_team_name}"
        embed.description = f"**{home_team_name}** {home_score} - {away_score} {away_team_name}"
        embed.set_thumbnail(url=home_team.get('logo'))

        if int(home_score) > int(away_score):
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value="We're leading! Let's keep up the momentum! 💪", inline=False)
        elif int(home_score) < int(away_score):
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value="We're trailing. Time to rally! 🔥", inline=False)
        else:
            embed.color = discord.Color.gold()
            embed.add_field(name="Status", value="All tied up! Push for the lead! ⚽", inline=False)
    elif away_team_id == focus_team_id:
        # Our team is the away team
        embed.title = f"🏟️ Match Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        embed.set_thumbnail(url=away_team.get('logo'))

        if int(away_score) > int(home_score):
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value="We're ahead! Keep the pressure on! 💪", inline=False)
        elif int(away_score) < int(home_score):
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value="We're behind. Let's fight back! 🔥", inline=False)
        else:
            embed.color = discord.Color.gold()
            embed.add_field(name="Status", value="It's a draw! Let's take the lead! ⚽", inline=False)
    else:
        # Neither team is our focus team
        embed.title = f"Match Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"
        embed.color = discord.Color.blue()
        embed.add_field(name="Status", value=match_status, inline=False)

    #embed.add_field(name="Match Status", value=match_status, inline=True)
    embed.add_field(name="Time", value=time, inline=True)

    return embed

def create_match_event_embed(event_data, focus_team_id, is_hype=False):
    event_type = event_data.get('type', '')
    event_team = event_data.get('team', {})
    event_time = event_data.get('time', "N/A")
    athlete = event_data.get('player', {})
    home_team = event_data.get('home_team', {})
    away_team = event_data.get('away_team', {})
    home_score = event_data.get('home_score', "0")
    away_score = event_data.get('away_score', "0")

    event_team_id = str(event_team.get('id', ""))
    event_team_name = event_team.get('displayName', "Unknown Team")
    is_focus_team_event = event_team_id == focus_team_id

    # Prepare embed based on event type and favorability
    if event_type == "Goal":
        embed = create_goal_embed(event_team_name, athlete, is_focus_team_event, event_time, is_hype)
    elif event_type in ["Yellow Card", "Red Card"]:
        embed = create_card_embed(event_type, event_team_name, athlete, is_focus_team_event, event_time, is_hype)
    else:
        embed = discord.Embed(
            title=f"{event_type} - {event_team_name}",
            description=f"An event occurred for {event_team_name}."
        )
        embed.color = discord.Color.green() if is_hype else discord.Color.blue()
        embed.add_field(name="Time", value=event_time, inline=True)

    # Add current score to the embed
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    embed.add_field(name="Score", value=f"{home_team_name} {home_score} - {away_score} {away_team_name}", inline=False)

    # Add player image
    add_player_image(embed, athlete)

    return embed

def create_goal_embed(team_name, athlete, is_focus_team_event, event_time, is_hype):
    scorer_name = athlete.get('displayName', "Unknown Player")
    if is_focus_team_event:
        messages = [
            f"🎉 GOOOOOAAAALLLL! {scorer_name} scores for {team_name} at {event_time}! Keep it coming! ⚽🔥",
            f"Goal! {scorer_name} puts {team_name} in the lead at {event_time}! Amazing strike! 🚀",
            f"Fantastic! {scorer_name} nets one for {team_name} at {event_time}! Let's keep the momentum! 💪"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
            color=discord.Color.green()
        )
    else:
        messages = [
            f"😡 Goal for {team_name} by {scorer_name} at {event_time}. We must fight back! 💪",
            f"{scorer_name} scores for the opposition at {event_time}. Time to regroup! ⚡",
            f"They take the lead... {scorer_name} scores for {team_name} at {event_time}. Let's counterattack! 🔥"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
            color=discord.Color.red()
        )
    return embed

def create_card_embed(card_type, team_name, athlete, is_focus_team_event, event_time, is_hype):
    player_name = athlete.get('displayName', "Unknown Player")
    emoji = "🟨" if card_type == "Yellow Card" else "🟥"
    if is_hype:
        messages = [
            f"{emoji} {card_type} for {team_name}! {player_name} gets booked at {event_time}. Advantage us! 😈",
            f"{emoji} A booking for {team_name} at {event_time}! {player_name} should be more careful! 🔥"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
            color=discord.Color.green()
        )
    else:
        messages = [
            f"{emoji} {card_type} for {team_name}: {player_name} received it at {event_time}. Stay focused!",
            f"{emoji} {player_name} got a {card_type.lower()} at {event_time} for {team_name}. Let's tighten up our play!"
        ]
        embed = discord.Embed(
            title=random.choice(messages),
            color=discord.Color.red() if card_type == "Red Card" else discord.Color.gold()
        )
    return embed

def create_substitution_embed(team_name, athlete, is_focus_team_event, event_time):
    player_in = athlete.get('in', {}).get('displayName', "Unknown Player")
    player_out = athlete.get('out', {}).get('displayName', "Unknown Player")

    if is_focus_team_event:
        embed = discord.Embed(
            title=f"🔄 Substitution for {team_name}",
            description=f"{player_in} comes on for {player_out} at {event_time}. Fresh legs! 🏃‍♂️",
            color=discord.Color.blue()
        )
    else:
        embed = discord.Embed(
            title=f"🔄 Substitution for {team_name}",
            description=f"{team_name} brings on {player_in} for {player_out} at {event_time}. Stay focused!",
            color=discord.Color.light_grey()
        )

    return embed

def create_score_update_embed(update_data, focus_team_id):
    # Extract current and previous scores
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_score = int(update_data.get('home_score', "0"))
    away_score = int(update_data.get('away_score', "0"))
    previous_home_score = int(update_data.get('previous_home_score', home_score))
    previous_away_score = int(update_data.get('previous_away_score', away_score))
    time = update_data.get('time', "N/A")

    # Determine if a goal has been scored
    goal_scored = False
    if home_score > previous_home_score or away_score > previous_away_score:
        goal_scored = True
        # Prepare event data for the goal
        if home_score > previous_home_score:
            scoring_team = home_team
            scoring_team_id = str(home_team.get('id', ""))
            scoring_team_name = home_team.get('displayName', "Home Team")
        else:
            scoring_team = away_team
            scoring_team_id = str(away_team.get('id', ""))
            scoring_team_name = away_team.get('displayName', "Away Team")

        # Include player information if available
        goal_scorer = update_data.get('goal_scorer', {})
        event_data = {
            'type': 'Goal',
            'team': scoring_team,
            'player': goal_scorer,
            'time': time,
            'home_team': home_team,
            'away_team': away_team,
            'home_score': str(home_score),
            'away_score': str(away_score)
        }
        return create_match_event_embed(event_data, focus_team_id)

    # If no goal, create a generic score update embed
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.add_field(name="Time", value=time, inline=True)

    if home_team_id == focus_team_id:
        embed.title = f"⚽ Score Update: {home_team_name} vs {away_team_name}"
        embed.description = f"**{home_team_name}** {home_score} - {away_score} {away_team_name}"
        embed.set_thumbnail(url=home_team.get('logo'))
        # Randomized messages for our team scoring conditions
        if home_score > away_score:
            messages = [
                "We're in the lead! Keep pushing! 🔥",
                "On top of the game—let's maintain our momentum! 🚀",
                "Great job! We're ahead. Stay focused! 💪"
            ]
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        elif home_score < away_score:
            messages = [
                "We're behind, but it's not over! Let's rally! 💪",
                "Time to step it up—fight back! ⚡",
                "Challenging start, but we can turn it around! 🔥"
            ]
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        else:
            messages = [
                "It's all square! Time to take control! ⚖️",
                "Evenly matched—now's our chance to break through! 🌟",
                "The score is level. Let's create an opportunity! ⚽"
            ]
            embed.color = discord.Color.gold()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
    elif away_team_id == focus_team_id:
        embed.title = f"⚽ Score Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        embed.set_thumbnail(url=away_team.get('logo'))
        if away_score > home_score:
            messages = [
                "We're ahead! Keep the pressure on! 💪",
                "Fantastic! We're leading on the road! 🚀",
                "In the lead—stay sharp and maintain the edge! 🔥"
            ]
            embed.color = discord.Color.green()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        elif away_score < home_score:
            messages = [
                "We're behind, but there's still time! Let's fight back! 💪",
                "Challenging game—time to regroup and push harder! 🔥",
                "We're trailing; every minute counts! ⚡"
            ]
            embed.color = discord.Color.red()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
        else:
            messages = [
                "It's a draw! Let's take the initiative! ⚽",
                "Level game—now's our chance to break the deadlock! 🌟",
                "Tied up at the moment. We need to push for the win! ⚖️"
            ]
            embed.color = discord.Color.gold()
            embed.add_field(name="Status", value=random.choice(messages), inline=False)
    else:
        embed.title = f"Score Update: {home_team_name} vs {away_team_name}"
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"
        embed.color = discord.Color.blue()

    #embed.add_field(name="Match Status", value=update_data.get('match_status', "Unknown"), inline=True)
    return embed

def create_halftime_embed(update_data, focus_team_id):
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_score = update_data.get('home_score', "0")
    away_score = update_data.get('away_score', "0")

    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.title = "Half-Time"
    embed.color = discord.Color.orange()
    embed.set_footer(text="45 minutes played. Second half coming up!")

    if home_team_id == focus_team_id:
        embed.description = f"**{home_team_name}** {home_score} - {away_score} {away_team_name}"
        embed.add_field(name="Our Performance", value="Stay tuned for the second half!", inline=False)
        embed.set_thumbnail(url=home_team.get('logo'))
    elif away_team_id == focus_team_id:
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        embed.add_field(name="Our Performance", value="Stay tuned for the second half!", inline=False)
        embed.set_thumbnail(url=away_team.get('logo'))
    else:
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"

    return embed

def create_fulltime_embed(match_id, update_data, focus_team_id):
    """
    Create a full-time embed including the result and, if available, a list of users who predicted correctly.
    The match_id is used to fetch the prediction data from the Flask API.
    """
    # Fetch correct predictions from the Flask API
    correct_predictions = get_correct_predictions(match_id)

    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_score = update_data.get('home_score', "0")
    away_score = update_data.get('away_score', "0")
    
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))
    
    embed = discord.Embed()
    embed.title = "Full-Time"
    embed.set_footer(text="Match has ended.")
    
    if home_team_id == focus_team_id:
        embed.description = f"**{home_team_name}** {home_score} - {away_score} {away_team_name}"
        if int(home_score) > int(away_score):
            embed.color = discord.Color.green()
            embed.add_field(name="Result", value="Victory! 🎉", inline=False)
        elif int(home_score) < int(away_score):
            embed.color = discord.Color.red()
            embed.add_field(name="Result", value="Defeat. We'll come back stronger! 💪", inline=False)
        else:
            embed.color = discord.Color.gold()
            embed.add_field(name="Result", value="Draw. A hard-fought point! ⚖️", inline=False)
        embed.set_thumbnail(url=home_team.get('logo'))
    elif away_team_id == focus_team_id:
        embed.description = f"{home_team_name} {home_score} - {away_score} **{away_team_name}**"
        if int(away_score) > int(home_score):
            embed.color = discord.Color.green()
            embed.add_field(name="Result", value="Victory! 🎉", inline=False)
        elif int(away_score) < int(home_score):
            embed.color = discord.Color.red()
            embed.add_field(name="Result", value="Defeat. We'll come back stronger! 💪", inline=False)
        else:
            embed.color = discord.Color.gold()
            embed.add_field(name="Result", value="Draw. A hard-fought point! ⚖️", inline=False)
        embed.set_thumbnail(url=away_team.get('logo'))
    else:
        embed.description = f"{home_team_name} {home_score} - {away_score} {away_team_name}"
        embed.color = discord.Color.blue()
    
    # Add a field for correct predictions if any were found.
    if correct_predictions:
        # Format the Discord user IDs as mentions.
        mentions = ", ".join([f"<@{user_id}>" for user_id in correct_predictions])
        embed.add_field(name="Correct Predictions", value=mentions, inline=False)
    
    return embed

def create_pre_match_embed(update_data, focus_team_id):
    home_team = update_data.get('home_team', {})
    away_team = update_data.get('away_team', {})
    home_team_name = home_team.get('displayName', "Home Team")
    away_team_name = away_team.get('displayName', "Away Team")
    home_team_id = str(home_team.get('id', ""))
    away_team_id = str(away_team.get('id', ""))

    embed = discord.Embed()
    embed.title = f"🚨 Pre-Match Hype: {home_team_name} vs {away_team_name} 🚨"
    embed.color = discord.Color.blue()

    embed.add_field(name="🏟️ Venue", value=update_data.get('venue', "N/A"), inline=False)
    embed.add_field(name="🏠 Home Form", value=update_data.get('home_form', "N/A"), inline=True)
    embed.add_field(name="🛫 Away Form", value=update_data.get('away_form', "N/A"), inline=True)

    odds_info = (
        f"Home Win: {update_data.get('home_odds', 'N/A')}\n"
        f"Draw: {update_data.get('draw_odds', 'N/A')}\n"
        f"Away Win: {update_data.get('away_odds', 'N/A')}"
    )
    #embed.add_field(name="💰 Odds", value=odds_info, inline=False)

    # Randomize pre-match hype messages based on focus team
    if home_team_id == str(focus_team_id):
        messages = [
            f"🔥 It's matchday! {home_team_name} is set to dominate on home turf! 🏟️",
            f"Get ready! {home_team_name} is fired up for a big night at home! 💪",
            f"{home_team_name} is ready to rock the stadium—let's show them our power! 🚀"
        ]
        embed.description = random.choice(messages)
        embed.set_thumbnail(url=home_team.get('logo'))
        embed.add_field(name="Team Spirit", value="Our boys are pumped and ready to give it their all! 💪", inline=False)
    elif away_team_id == str(focus_team_id):
        messages = [
            f"🌟 It's time for {away_team_name} to shine on the road! Let's show them what we've got! 💪",
            f"{away_team_name} is ready for battle away from home—let's make it a statement! 🚀",
            f"On the road and on fire! {away_team_name} is set to take control! 🔥"
        ]
        embed.description = random.choice(messages)
        embed.set_thumbnail(url=away_team.get('logo'))
        embed.add_field(name="Away Day Magic", value="We're taking our A-game to their turf! Let's make our traveling fans proud! 🛫", inline=False)
    else:
        embed.description = "An exciting match is on the horizon! Who will come out on top?"

    return embed

def add_player_image(embed, athlete):
    if isinstance(athlete, dict) and 'id' in athlete:
        player_id = athlete['id']
        player_image_url = f"https://a.espncdn.com/combiner/i?img=/i/headshots/soccer/players/full/{player_id}.png"
        embed.set_thumbnail(url=player_image_url)