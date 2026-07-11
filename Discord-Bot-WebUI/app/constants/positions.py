# app/constants/positions.py

"""
Single source of truth for soccer positions.

Every consumer — web forms, the pub-league link-order step, the player profile,
the mobile API, request validators, and the Flutter app (via the /positions
endpoint) — must derive its position list, storage format, and normalization
from here so they can never drift apart again.

Public API:
    SOCCER_POSITIONS : ordered list of (slug, label) tuples. Slugs are the
                       canonical STORED form; labels are for display.
    POSITION_SLUGS   : set of valid slugs.
    POSITION_LABELS  : {slug: label}.
    normalize_position(value) : coerce any legacy value (label or slug, quoted
                       or not, any case) to a canonical slug.
    parse_positions(value)    : parse a stored column (Postgres array `{a,b}`
                       OR legacy comma string `a, b`) into a de-duped list of
                       canonical slugs (unknown values dropped).
    format_positions(values)  : render an iterable/list back to the canonical
                       `{slug,slug}` Postgres-array storage form (or None).
"""

# Canonical, display-ordered list: GK -> defense -> midfield -> attack.
SOCCER_POSITIONS = [
    ('goalkeeper', 'Goalkeeper'),
    ('defender', 'Defender'),
    ('center_back', 'Center Back'),
    ('left_back', 'Left Back'),
    ('right_back', 'Right Back'),
    ('full_back', 'Full Back'),
    ('wing_back', 'Wing Back'),
    ('midfielder', 'Midfielder'),
    ('defensive_midfielder', 'Defensive Midfielder'),
    ('central_midfielder', 'Central Midfielder'),
    ('left_midfielder', 'Left Midfielder'),
    ('right_midfielder', 'Right Midfielder'),
    ('attacking_midfielder', 'Attacking Midfielder'),
    ('winger', 'Winger'),
    ('left_winger', 'Left Winger'),
    ('right_winger', 'Right Winger'),
    ('forward', 'Forward'),
    ('center_forward', 'Center Forward'),
    ('striker', 'Striker'),
    ('support_striker', 'Support Striker'),
    ('no_preference', 'No Preference'),
]

POSITION_SLUGS = {slug for slug, _ in SOCCER_POSITIONS}
POSITION_LABELS = {slug: label for slug, label in SOCCER_POSITIONS}
_LABEL_TO_SLUG = {label.lower(): slug for slug, label in SOCCER_POSITIONS}


def normalize_position(value):
    """Coerce a raw position value to a canonical slug.

    Handles display labels ('Left Winger'), existing slugs ('left_winger'),
    Postgres array quoting ('"Left Winger"'), stray whitespace, and any case.
    Returns '' for empty input. The result is lowered/underscored even if it is
    not a known slug, so callers can decide whether to filter on POSITION_SLUGS.
    """
    if not value:
        return ''
    v = str(value).strip().strip('"').strip("'").replace('\\"', '"').strip()
    if not v:
        return ''
    low = v.lower()
    if low in _LABEL_TO_SLUG:
        return _LABEL_TO_SLUG[low]
    return low.replace(' ', '_')


def parse_positions(value):
    """Parse a stored positions column into a de-duped list of canonical slugs.

    Accepts both storage shapes seen in production:
        * Postgres array text : {Striker,"Left Winger"}
        * legacy comma string : Striker, Left Winger
    Values that don't map to a known slug are dropped.
    """
    if not value:
        return []
    s = str(value).strip()
    if s.startswith('{') and s.endswith('}'):
        s = s[1:-1]
    out, seen = [], set()
    for part in s.split(','):
        slug = normalize_position(part)
        if slug and slug in POSITION_SLUGS and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def label_for(value):
    """Return the display label for a single stored position.

    For API responses that must present human labels ('Left Winger') even though
    storage is canonical slugs ('left_winger'). Falls back to the raw value if
    it's not a known position, so nothing is ever blanked.
    """
    if not value:
        return value
    return POSITION_LABELS.get(normalize_position(value), value)


def to_label_array(value):
    """Convert a stored positions column to a '{Label,Label}' display string.

    For mobile read endpoints so the app keeps receiving human labels. Returns
    the original value untouched if nothing parses (avoids data loss), or None
    for empty input.
    """
    if not value:
        return None
    slugs = parse_positions(value)
    if not slugs:
        return value
    return '{' + ','.join(POSITION_LABELS[s] for s in slugs) + '}'


def format_positions(values):
    """Render positions to the canonical `{slug,slug}` Postgres-array storage form.

    Accepts a list of values or a raw stored string. Normalizes, drops unknowns,
    de-dupes, and returns None for an empty result (matches the nullable column).
    """
    if not values:
        return None
    if isinstance(values, str):
        values = parse_positions(values)
    slugs, seen = [], set()
    for v in values:
        slug = normalize_position(v)
        if slug and slug in POSITION_SLUGS and slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return ('{' + ','.join(slugs) + '}') if slugs else None
