# match_reminder_views.py

"""
Discord UI view for match reminder DMs.

One button: "Don't remind me anymore". Persistent (timeout=None) so it
survives bot restarts. Button interactions are handled by on_interaction
in ECS_Discord_Bot.py via the `match_reminder:optout` custom_id prefix.
"""

import discord


class MatchReminderView(discord.ui.View):
    """Persistent view with a single opt-out button for match reminder DMs."""

    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="Don't remind me anymore",
            custom_id="match_reminder:optout",
        ))
