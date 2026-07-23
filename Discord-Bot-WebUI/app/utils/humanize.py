# app/utils/humanize.py

"""
Identifier humanization — turn machine identifiers into readable display text.

Used by the System Command Center (and available anywhere) to render task names,
service keys, metric keys, etc. as human labels without hand-maintaining a lookup
table for every string. Acronym-aware so common initialisms stay uppercase.

To register as a Jinja filter, add to a context processor / app init:

    from app.utils.humanize import humanize_identifier
    app.jinja_env.filters['humanize'] = humanize_identifier

(There is no single obvious existing place that registers plain string filters in
`app/init/context_processors.py` — it registers context processors and template
globals, not `jinja_env.filters` — so this module only EXPOSES the function; wire
the filter wherever filters get registered if a `| humanize` filter is wanted.
The System Command Center service calls the function directly, so the filter is
optional.)

Examples (doctest-style):
    >>> humanize_identifier('send_rsvp_reminders')
    'Send RSVP Reminders'
    >>> humanize_identifier('process.discord.role_updates')
    'Process Discord Role Updates'
    >>> humanize_identifier('sync-mls-matches')
    'Sync MLS Matches'
    >>> humanize_identifier('cpu_usage')
    'CPU Usage'
    >>> humanize_identifier('')
    ''
    >>> humanize_identifier(None)
    ''
"""

import re

# Tokens kept fully UPPERCASE when they appear as a standalone word. Compared
# case-insensitively; the canonical uppercase form is emitted.
_ACRONYMS = {
    'RSVP', 'API', 'MLS', 'ECS', 'FC', 'DM', 'SMS', 'FCM', 'URL', 'IP', 'DB',
    'ID', 'AI', 'CSV', 'HTTP', 'HTTPS', 'UI', 'UX', 'OK', 'PG', 'SQL', 'TTL',
    'CPU', 'RAM', 'JSON',
}

# Any run of separators — underscore, dot, hyphen, or whitespace — splits tokens.
_SPLIT = re.compile(r'[_.\-\s]+')


def humanize_identifier(s):
    """Convert a snake/dotted/kebab identifier into Title Case display text,
    keeping known acronyms uppercase.

    None or empty (after stripping) returns ''. Non-string input is coerced to
    str first so a stray number/enum never raises.
    """
    if s is None:
        return ''
    text = str(s).strip()
    if not text:
        return ''

    words = []
    for token in _SPLIT.split(text):
        if not token:
            continue
        if token.upper() in _ACRONYMS:
            words.append(token.upper())
        else:
            # Title-case a single token (handles all-caps or mixed input) without
            # str.title() mangling internal letters oddly for our simple tokens.
            words.append(token[:1].upper() + token[1:].lower())
    return ' '.join(words)
