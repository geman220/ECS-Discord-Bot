# app/utils/role_display.py

"""
Friendly, human-readable presentation for Flask role NAMES.

The stored role names are a mix of terse slugs (``pl-premier``, ``pl-waitlist``)
and Title-ish strings (``Premier Coach``). Admins shouldn't have to decode a
slug — the Access Control surface shows a clear label + a one-line "what it is"
so it's obvious what granting a role means.

``kind`` drives badge colour / grouping. ``discord_expected`` says whether this
role is one we intend to have a Discord counterpart (mirrors
``CANONICAL_DISCORD_ROLE_MAP`` in discord_role_sync_service) — used to explain
why an admin/app-only role reads as "App-only" rather than "unmapped / to-do".
"""

# name -> (label, what_it_is, kind)
# kind ∈ {admin, league, coach, sub, referee, other}
_ROLE_DISPLAY = {
    # ---- Admin / staff (app-only, powerful) ----
    'Global Admin':       ('Global Admin', 'Full control of the entire platform.', 'admin'),
    'Pub League Admin':   ('Pub League Admin', 'Runs Pub League operations end-to-end.', 'admin'),
    'ECS FC Admin':       ('ECS FC Admin', 'Runs ECS FC operations.', 'admin'),
    'Discord Admin':      ('Discord Admin', 'Manages the Discord integration & server.', 'admin'),
    'Pub League Manager': ('Pub League Manager', 'Day-to-day Pub League management, below admin.', 'admin'),

    # ---- League membership (players) ----
    'pl-premier':    ('Premier Player', 'Rostered in the Premier division this season.', 'league'),
    'pl-classic':    ('Classic Player', 'Rostered in the Classic division this season.', 'league'),
    'pl-ecs-fc':     ('ECS FC Player', 'Rostered in ECS FC this season.', 'league'),
    'pl-unverified': ('Unverified', 'New or not-yet-approved account, pre-placement.', 'league'),
    'pl-waitlist':   ('Waitlist', 'Waiting for a spot — app-only, no Discord role.', 'league'),

    # ---- Coaches ----
    'Premier Coach':    ('Premier Coach', 'Coaches a Premier team.', 'coach'),
    'Classic Coach':    ('Classic Coach', 'Coaches a Classic team.', 'coach'),
    'ECS FC Coach':     ('ECS FC Coach', 'Coaches an ECS FC team.', 'coach'),
    'Pub League Coach': ('Pub League Coach', 'General Pub League coach (self-service capable).', 'coach'),

    # ---- Substitutes ----
    'Premier Sub': ('Premier Sub', 'In the Premier substitute pool.', 'sub'),
    'Classic Sub': ('Classic Sub', 'In the Classic substitute pool.', 'sub'),
    'ECS FC Sub':  ('ECS FC Sub', 'In the ECS FC substitute pool.', 'sub'),

    # ---- Referees ----
    'Pub League Ref': ('Referee', 'Referees matches (maps to the Discord “Referee” role).', 'referee'),
}

# Roles we intend to keep mirrored to a Discord role (mirrors CANONICAL_DISCORD_ROLE_MAP).
# Anything not here is "app-only" by design and should not read as an unmapped to-do.
DISCORD_EXPECTED = frozenset({
    'pl-premier', 'pl-classic', 'pl-ecs-fc', 'pl-unverified',
    'Premier Coach', 'Classic Coach', 'ECS FC Coach',
    'Premier Sub', 'Classic Sub', 'ECS FC Sub', 'Pub League Ref',
})

_KIND_ORDER = {'admin': 0, 'coach': 1, 'league': 2, 'sub': 3, 'referee': 4, 'other': 5}


def _fallback_label(name):
    """Turn an unknown role slug into something readable.

    'pl-premier' -> 'Premier'; 'some_role' -> 'Some Role'.
    """
    base = name
    if base.lower().startswith('pl-'):
        base = base[3:]
    base = base.replace('-', ' ').replace('_', ' ').strip()
    # Title-case but leave already-capitalised tokens (acronyms) alone.
    words = [w if (w[:1].isupper() and w[1:2].islower() is False and len(w) > 1) else w.capitalize()
             for w in base.split()]
    return ' '.join(words) or name


def role_display(name):
    """Return {name, label, what, kind, discord_expected} for a role name."""
    entry = _ROLE_DISPLAY.get(name)
    if entry:
        label, what, kind = entry
    else:
        label, what, kind = _fallback_label(name), '', 'other'
    return {
        'name': name,
        'label': label,
        'what': what,
        'kind': kind,
        'discord_expected': name in DISCORD_EXPECTED,
    }


def role_sort_key(name):
    """Stable ordering: by kind (admin→other), then label."""
    d = role_display(name)
    return (_KIND_ORDER.get(d['kind'], 9), d['label'].lower())
