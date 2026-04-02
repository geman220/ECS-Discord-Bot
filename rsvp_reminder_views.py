# rsvp_reminder_views.py

"""
Discord UI Views for RSVP Reminder DMs.

Provides interactive buttons (Yes/No/Maybe/Snooze) sent in reminder DMs.
Uses timeout=None for persistence across bot restarts.
Button interactions are handled by on_interaction in ECS_Discord_Bot.py.
"""

import discord


# Custom ID format: rsvp:{match_type}:{match_id}:{response}
# Examples: rsvp:pub:123:yes, rsvp:ecs_fc:42:no, rsvp:snooze:open


class RSVPReminderView(discord.ui.View):
    """
    Persistent view with RSVP buttons for reminder DMs.

    Each match gets one row of Yes/No/Maybe buttons.
    A final row has a Snooze button.
    Discord allows max 5 ActionRows, so up to 4 matches + snooze.
    """

    def __init__(self, matches):
        super().__init__(timeout=None)

        # Add one row of buttons per match (max 4 to leave room for snooze)
        for idx, match in enumerate(matches[:4]):
            match_type = match['match_type']
            match_id = match['match_id']
            opponent = match.get('opponent_name', 'Opponent')

            # Truncate label if too long (Discord button labels max 80 chars)
            label_prefix = opponent[:20] if len(opponent) > 20 else opponent

            self.add_item(discord.ui.Button(
                style=discord.ButtonStyle.success,
                label=f"Yes - {label_prefix}",
                custom_id=f"rsvp:{match_type}:{match_id}:yes",
                row=idx
            ))
            self.add_item(discord.ui.Button(
                style=discord.ButtonStyle.danger,
                label=f"No - {label_prefix}",
                custom_id=f"rsvp:{match_type}:{match_id}:no",
                row=idx
            ))
            self.add_item(discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                label=f"Maybe - {label_prefix}",
                custom_id=f"rsvp:{match_type}:{match_id}:maybe",
                row=idx
            ))

        # Snooze button on last row
        snooze_row = min(len(matches), 4)
        self.add_item(discord.ui.Button(
            style=discord.ButtonStyle.primary,
            label="Snooze Reminders",
            custom_id="rsvp:snooze:open",
            emoji="\U0001f634",  # Sleeping face
            row=snooze_row
        ))


class SnoozeSelectView(discord.ui.View):
    """View with a dropdown to select snooze duration."""

    def __init__(self):
        super().__init__(timeout=60)

        self.add_item(discord.ui.Select(
            custom_id="rsvp:snooze:select",
            placeholder="How long to pause reminders?",
            options=[
                discord.SelectOption(label="1 week", value="1", description="Pause for 1 week"),
                discord.SelectOption(label="2 weeks", value="2", description="Pause for 2 weeks"),
                discord.SelectOption(label="4 weeks", value="4", description="Pause for 4 weeks"),
                discord.SelectOption(label="Rest of season", value="0", description="Pause until end of current season"),
            ]
        ))


def build_rsvp_reminder_embed(matches):
    """
    Build the Discord embed for an RSVP reminder DM.

    Args:
        matches: List of match info dicts with keys:
            match_type, match_id, team_name, opponent_name,
            match_date, match_time, location
    """
    embed = discord.Embed(
        title="\u26bd RSVP Reminder",
        description="You haven't RSVP'd for the following match(es). Use the buttons below to respond!",
        color=0xff9800  # Orange
    )

    for match in matches:
        team_name = match.get('team_name', 'Your Team')
        opponent = match.get('opponent_name', 'TBD')
        match_date = match.get('match_date', 'TBD')
        match_time = match.get('match_time', 'TBD')
        location = match.get('location', 'TBD')

        field_value = (
            f"**{team_name}** vs **{opponent}**\n"
            f"\U0001f4c5 {match_date} at {match_time}\n"
            f"\U0001f4cd {location}"
        )

        match_label = "Pub League" if match.get('match_type') == 'pub' else "ECS FC"
        embed.add_field(
            name=f"{match_label} Match",
            value=field_value,
            inline=False
        )

    embed.set_footer(text="Click a button to RSVP, or Snooze to pause reminders")
    return embed
