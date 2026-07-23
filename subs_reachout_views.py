# subs_reachout_views.py

"""
Discord UI Views for Substitute reach-out DMs.

When an admin sends a TARGETED substitute reach-out from the Flask app, the
bot DMs the candidate an interactive "Can you sub? Yes/No" prompt. The team is
NEVER revealed in the DM — this is intentional: the candidate only decides
availability, and staff place them afterward.

Uses timeout=None for persistence across bot restarts. Button interactions are
handled by on_interaction in ECS_Discord_Bot.py, which dispatches on the frozen
custom_id prefix defined in subs_commands.py (SUBS_CID_PREFIX = "subs:v1:").

Custom ID grammar (frozen): subs:v1:reachout:<reachout_recipient_id>:<yes|no>
Examples: subs:v1:reachout:812:yes, subs:v1:reachout:812:no
"""

import discord


class SubsReachoutView(discord.ui.View):
    """
    Persistent view with Yes/No buttons for a substitute reach-out DM.

    Args:
        reachout_recipient_id: The Flask SubstituteReachoutRecipient row id that
            this DM corresponds to. It is embedded in the button custom_ids so
            the click can be written back to the correct recipient record.
    """

    def __init__(self, reachout_recipient_id):
        super().__init__(timeout=None)

        self.add_item(discord.ui.Button(
            style=discord.ButtonStyle.success,
            label="Yes, I can sub",
            custom_id=f"subs:v1:reachout:{reachout_recipient_id}:yes",
            emoji="✅",  # White check mark
        ))
        self.add_item(discord.ui.Button(
            style=discord.ButtonStyle.danger,
            label="No, I can't",
            custom_id=f"subs:v1:reachout:{reachout_recipient_id}:no",
            emoji="❌",  # Cross mark
        ))


def build_subs_reachout_embed(message):
    """
    Build the Discord embed for a substitute reach-out DM.

    The team is intentionally NOT included — availability only.

    Args:
        message: The reach-out body text supplied by Flask.
    """
    embed = discord.Embed(
        title="⚽ Sub Needed",
        description=message or "We're looking for a substitute. Can you play?",
        color=0xff9800,  # Orange
    )
    embed.set_footer(text="Tap Yes or No below to let us know your availability")
    return embed
