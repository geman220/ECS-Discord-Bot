# app/utils/rsvp_copy.py

"""
Admin-editable wording for the RSVP request posted to a team channel.

Until now every one of these strings was an f-string inside the BOT process
(api/routes/match_routes.py, api/utils/rsvp_utils.py, ecs_fc_bot_api.py), so
changing "React with 👍" required a code change and a bot redeploy.

The webapp now renders the copy and passes it to the bot, which falls back to
its own baked-in strings for any field it does not receive. That means a webapp
deploy landing before the bot redeploy still posts correct RSVPs — it just
ignores edits until the bot catches up.

TOKENS are filled per MATCH, not per person (a channel post has no single
recipient). Unknown tokens are left visible rather than raising: a typo should
ship as `{oponent}` in one message, not take the whole week's RSVPs down.

Two programs, separate copy: Pub League posts to two team channels per fixture
and never names an opponent the way ECS FC does, and ECS FC carries shirt
colours and a home/away flag that Pub League has no concept of.
"""

import logging
import re

logger = logging.getLogger(__name__)

SETTING_KEY = 'rsvp_message_copy'

# The strings the bot currently hardcodes, reproduced exactly. Seeding these as
# the default means turning the feature on changes nothing until someone edits.
DEFAULTS = {
    'pub': {
        'content': ('⚽ **{team}** - Are you available for the match on {date} '
                    'at {time}? {instructions}'),
        'title': '{team} vs {opponent}',
        'description': 'Date: {date}\nTime: {time}',
        'footer': '',
    },
    'ecs_fc': {
        'content': ('⚽ **{team}** - Are you available for the match against '
                    '**{opponent}**? {instructions}'),
        'title': '⚽ {team} vs {opponent}',
        'description': '',
        'footer': '{instructions}',
    },
    # Special weeks (FUN / TST / BONUS) replace the fixture line entirely.
    'special': {
        'content': ('⚽ **{team}** - {display_name} on {date} at {time}! '
                    'Are you available? {instructions}'),
        'title': '{team} — {display_name}',
        'description': 'Date: {date}\nTime: {time}',
        'footer': '',
    },
    # BYE weeks take no RSVP at all — no buttons, no reactions.
    'bye': {
        'content': ('⚽ **{team}** - {display_name} on {date}. '
                    'No match scheduled this week.'),
        'title': '{team} — {display_name}',
        'description': 'No match this week.\n\n**Date:** {date}',
        'footer': 'Enjoy your week off!',
    },
}

# {instructions} is filled by the engine, not the admin — it has to match how
# people actually respond, and that flips when buttons are switched on. Letting
# an admin hardcode "React with 👍" would leave the message lying the moment the
# response method changed.
INSTRUCTIONS_REACTIONS = {
    'pub': 'React with 👍 for Yes, 👎 for No, or 🤷 for Maybe.',
    'ecs_fc': 'React with ✅ for Yes, ❌ for No, or ❓ for Maybe',
}
INSTRUCTIONS_BUTTONS = {
    'pub': 'Tap a button below to RSVP.',
    'ecs_fc': 'Tap a button below to RSVP.',
}

# What an admin may type. Shown in the editor and used by the preview.
TOKENS = {
    'team': 'The team the message is posted for',
    'opponent': 'Who they are playing',
    'date': 'Match date',
    'time': 'Kick-off time',
    'location': 'Pitch / venue',
    'display_name': 'Special-week name, e.g. "Fun Week!" (special and bye only)',
    'instructions': 'How to respond — filled in automatically, and changes when '
                    'you switch between reactions and buttons',
}

FIELDS = ('content', 'title', 'description', 'footer')
PROGRAMS = tuple(DEFAULTS)


def get_copy(program=None):
    """Admin-edited copy merged over DEFAULTS. Whole map if program is None."""
    stored = {}
    try:
        from app.models import AdminConfig
        stored = AdminConfig.get_setting(SETTING_KEY, None) or {}
        if not isinstance(stored, dict):
            logger.warning("%s is not a dict; ignoring", SETTING_KEY)
            stored = {}
    except Exception:
        logger.exception("Could not read %s; using defaults", SETTING_KEY)

    merged = {}
    for prog, defaults in DEFAULTS.items():
        block = dict(defaults)
        for field, value in (stored.get(prog) or {}).items():
            # A blank string is a legitimate choice (no footer). Only a MISSING
            # key falls back to the default.
            if field in FIELDS and isinstance(value, str):
                block[field] = value
        merged[prog] = block
    return merged[program] if program else merged


def instructions_for(program, use_buttons):
    table = INSTRUCTIONS_BUTTONS if use_buttons else INSTRUCTIONS_REACTIONS
    return table.get(program, table['pub'])


def render(template, values):
    """Fill {tokens}, leaving unknown ones visible."""
    return re.sub(r'\{(\w+)\}',
                  lambda m: str(values.get(m.group(1), m.group(0))),
                  template or '')


def render_fields(block, program, values, use_buttons=False):
    """Pure render of one already-fetched copy block. No I/O.

    Use this inside loops. `values` carries the match facts; {instructions} is
    injected here rather than being an admin field, so it can never drift from
    the actual response method.
    """
    vals = dict(values)
    vals.setdefault('instructions', instructions_for(program, use_buttons))
    return {field: render(block.get(field, ''), vals) for field in FIELDS}


def render_block(program, values, use_buttons=False):
    """Convenience single-shot render — fetches the copy, then renders.

    Fetching goes through AdminConfig, which in a Celery task has no
    request-scoped cache and therefore hits Redis every call. Fine for one
    message; call get_copy() once and use render_fields() when looping over a
    batch, or a Redis blip turns into one connection-retry storm per match.
    """
    return render_fields(get_copy(program), program, values, use_buttons)
