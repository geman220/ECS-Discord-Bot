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

PERSISTENCE
    timeout=None plus a static custom_id makes this a persistent view, but
    discord.py only re-attaches handlers for views registered via
    `bot.add_view(...)` on startup. Without that, every button posted before the
    last bot restart silently stops responding. See register_persistent_views().
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

    def __init__(self, match_id=None, team_id=None):
        super().__init__(timeout=None)
        # match_id/team_id are None when discord.py rebuilds the view on startup
        # for persistence — the ids are already baked into each child's
        # custom_id, so nothing needs to be re-derived here.
        if match_id is None or team_id is None:
            for value, label, style in RESPONSES:
                # A placeholder id that parse_custom_id rejects. The real
                # dispatch happens in on_interaction from the message's own
                # custom_id, so these are never actually clicked.
                self.add_item(discord.ui.Button(
                    label=label, style=style,
                    custom_id=build_custom_id(0, 0, value)))
            return

        for value, label, style in RESPONSES:
            self.add_item(discord.ui.Button(
                label=label, style=style,
                custom_id=build_custom_id(match_id, team_id, value)))


def register_persistent_views(bot):
    """Re-attach button handling after a restart.

    Without this every RSVP post from before the restart becomes inert: the
    buttons still render, clicking does nothing, and there is no error anywhere
    — the failure is completely silent, which is the worst kind for something
    match-day critical.

    Call once from on_ready.
    """
    try:
        bot.add_view(RSVPChannelView())
        logger.info("Registered persistent RSVP channel button view")
    except Exception:
        logger.exception("Could not register persistent RSVP channel view")
