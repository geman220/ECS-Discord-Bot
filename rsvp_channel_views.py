"""
Yes / No / Maybe buttons for the RSVP request posted to a team channel.

This is the CHANNEL post. The DM reminder has its own view in
rsvp_reminder_views.py; they are deliberately separate because a channel post is
public, is scoped to one team's roster, and is edited in place for the life of
the fixture, none of which is true of a DM.

Enabled per-post by the web app's `rsvp_use_buttons` setting. Messages already
in Discord keep their reactions and keep working — a posted message cannot be
converted — so the reaction handler in ECS_Discord_Bot.py must stay live
indefinitely, not just during a transition.

CUSTOM ID FORMAT
    rsvpc:{match_id}:{team_id}:{response}
    e.g. rsvpc:412:120:yes

`rsvpc` (channel), not `rsvp` (the DM prefix) — the DM handler pattern-matches on
`rsvp:` and would otherwise swallow these and look up the wrong thing.

The team_id is baked into the id at post time rather than resolved from the
message. The reaction path does a message_id -> (match, team) round-trip to the
web app on every single click; carrying it here removes that lookup from the hot
path, and a click can be authorised knowing exactly which roster to check.

SURVIVING RESTARTS
    Clicks are handled by `on_interaction` in ECS_Discord_Bot.py, which is a
    gateway event and fires for EVERY component interaction whether or not the
    view object still exists. So buttons keep working across bot restarts with
    no registration step, and this class only ever has to build the components.

    That is also why the buttons below carry no callbacks: adding one would make
    behaviour depend on the view being alive in memory, which after a restart it
    is not. `bot.add_view()` would not help either -- it matches on exact
    custom_id, and ours embed the match and team, so no fixed registration could
    cover them.

    The existing DM reminder view (rsvp_reminder_views.py) works the same way and
    has been in production for months.
"""

import logging

import discord

logger = logging.getLogger(__name__)

CUSTOM_ID_PREFIX = "rsvpc"

# (response value, button label, style)
RESPONSES = [
    ("yes", "Yes", discord.ButtonStyle.success),
    ("no", "No", discord.ButtonStyle.danger),
    ("maybe", "Maybe", discord.ButtonStyle.secondary),
]

CONFIRMATIONS = {
    "yes": "You're in ✅",
    "no": "Thanks for letting us know ❌",
    "maybe": "Marked as maybe ❓",
}


def build_custom_id(match_id, team_id, response):
    return f"{CUSTOM_ID_PREFIX}:{match_id}:{team_id}:{response}"


def parse_custom_id(custom_id):
    """(match_id, team_id, response) or None if this id is not ours.

    Fails closed on anything malformed rather than guessing — a wrong match_id
    would record somebody's availability against the wrong fixture.
    """
    if not custom_id or not custom_id.startswith(CUSTOM_ID_PREFIX + ":"):
        return None
    parts = custom_id.split(":")
    if len(parts) != 4:
        return None
    _, match_id, team_id, response = parts
    if response not in {r[0] for r in RESPONSES}:
        return None
    try:
        return int(match_id), int(team_id), response
    except (TypeError, ValueError):
        return None


class RSVPChannelView(discord.ui.View):
    """Persistent Yes/No/Maybe buttons for one team's copy of a match post."""

    def __init__(self, match_id, team_id):
        # timeout=None so Discord keeps the components enabled indefinitely; the
        # fixture may sit there for a week before kick-off.
        super().__init__(timeout=None)
        for value, label, style in RESPONSES:
            self.add_item(discord.ui.Button(
                label=label, style=style,
                custom_id=build_custom_id(match_id, team_id, value)))
