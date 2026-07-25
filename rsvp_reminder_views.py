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


# Fallback copy. The web app normally supplies all three from the
# 'rsvp_dm_reminder' automation rule, so these are what goes out only when it
# sends nothing -- an older web app, or a field an admin left blank. Keep them in
# step with DEFAULT_OPTIONS in the web app's tasks_rsvp_dm_reminders.py.
DEFAULT_REMINDER_TITLE = "\u26bd RSVP Reminder"
DEFAULT_REMINDER_DESCRIPTION = (
    "You haven't RSVP'd for the following match(es). Use the buttons below to respond!"
)
DEFAULT_REMINDER_FOOTER = "Click a button to RSVP, or Snooze to pause reminders"


def build_rsvp_reminder_embed(matches, title=None, description=None, footer=None):
    """
    Build the Discord embed for an RSVP reminder DM.

    Args:
        matches: List of match info dicts with keys:
            match_type, match_id, team_name, opponent_name,
            match_date, match_time, location
        title/description/footer: admin-authored copy from the web app's
            automation rule. Blank or missing falls back to the defaults above.
            The footer is the one field allowed to end up genuinely empty --
            an admin who clears it wants no footer line, not the default back.
    """
    embed = discord.Embed(
        title=(title or "").strip() or DEFAULT_REMINDER_TITLE,
        description=(description or "").strip() or DEFAULT_REMINDER_DESCRIPTION,
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

    # `footer is None` means "the caller said nothing" -> default. An empty
    # string means "the admin deliberately cleared it" -> no footer at all.
    footer_text = DEFAULT_REMINDER_FOOTER if footer is None else footer.strip()
    if footer_text:
        embed.set_footer(text=footer_text)
    return embed
