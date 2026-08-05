# app/services/calendar/programs.py

"""
Program lens for the calendar.

Every calendar surface used to hardcode the three original divisions --
'Premier' | 'Classic' | 'ECS FC' -- and then treat that list as an ALLOW-LIST.
The portal calendar is the worst case: the API fetched a fourth program's
matches correctly, the client transformed them correctly, and then

    if (divisions.length > 0 && !divisions.includes(event.division)) return false;

dropped every one of them, because a Summer Sprint match carries
`division === 'Summer Sprint'` and that string is in nobody's list. The
fixtures were invisible at the DEFAULT checked state, with no filter to
un-check that would bring them back -- which is why it read as "missing data"
rather than "over-filtered".

This module is the one place that answers "which programs does the calendar
know about, and what does one look like", resolved through the program
registry so the answer follows the registry instead of the next person's
memory of how many leagues there were.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Only used when the registry is unreachable AND the league name is unknown to
# it. Deliberately NOT a division list -- it is a single fallback colour.
DEFAULT_COLOR = '#0288d1'


def program_for_league_name(name: Optional[str], session=None):
    """The registry program owning a `League.name`, or None.

    Never raises: a missing/unreadable `program` table must degrade to
    "unknown program", not to a 500 on the calendar.
    """
    if not name:
        return None
    try:
        from app.services import program_registry
        return program_registry.by_league_name(name, session)
    except Exception:
        logger.debug("program_registry unavailable resolving league %r", name, exc_info=True)
        return None


def program_label_for_league_name(name: Optional[str], session=None) -> Tuple[Optional[str], str, str]:
    """(program_key, display_label, color) for a `League.name`.

    `program_key` is the STABLE identifier clients must filter on; the label is
    a display string that changes on any rebrand. Falls back to the raw league
    name as the label so an unregistered league still renders something
    truthful rather than being relabelled as somebody else's division.
    """
    program = program_for_league_name(name, session)
    if program is not None:
        return program.key, (program.display_name or name or ''), (program.color or DEFAULT_COLOR)
    return None, (name or ''), DEFAULT_COLOR


def program_for_league_id(league_id: Optional[int], session=None):
    """The registry program owning a `League.id`, or None."""
    if not league_id:
        return None
    try:
        from app.models import League
        q = (session.query(League) if session is not None else League.query)
        league = q.filter(League.id == league_id).first()
    except Exception:
        logger.debug("Could not load league %r for program lookup", league_id, exc_info=True)
        return None
    return program_for_league_name(getattr(league, 'name', None), session)


def program_by_league_id_map(league_ids, session=None) -> Dict[int, Dict[str, Any]]:
    """{league_id: {key, label, color}} for the given league ids.

    One query for the whole page instead of a registry round-trip per event.
    League ids that resolve to no program are simply absent from the map --
    callers must render those as unlabelled, never as somebody else's program.
    """
    ids = [i for i in set(league_ids or []) if i]
    if not ids:
        return {}
    try:
        from app.models import League
        q = (session.query(League) if session is not None else League.query)
        rows = q.filter(League.id.in_(ids)).all()
    except Exception:
        logger.debug("Could not load leagues for program map", exc_info=True)
        return {}
    out: Dict[int, Dict[str, Any]] = {}
    for lg in rows:
        key, label, color = program_label_for_league_name(lg.name, session)
        if key:
            out[lg.id] = {'key': key, 'label': label, 'color': color}
    return out


def league_ids_for_program(program_key: str, session=None) -> List[int]:
    """Every `League.id` belonging to one program, across ALL seasons.

    Deliberately not restricted to the current season: an event scoped to last
    season's league still belongs to that program, and filtering it out would
    make the program's own filter hide the program's own events.

    Resolved by running each league name back through the registry rather than
    by matching `League.name` in SQL. That is deliberate: the badge on an event
    is produced by `program_for_league_name`, which is tolerant (exact ->
    case-insensitive -> substring). A SQL exact-match here would disagree with
    it, so a league that had drifted to e.g. "Premier Division" would render a
    Premier badge yet be excluded by the Premier filter. `league` is a small
    table and the registry is request-cached, so this costs one query.

    ⚠️ A DB failure here RAISES rather than returning []. That is deliberate
    and load-bearing for the public page cache: `[]` is a perfectly valid
    answer that renders "no events for this program", and returning it on a
    transient error produced a SUCCESSFUL empty render, which
    _dynamic_page_cache then stored for TTL_HTML (and as :stale for an hour)
    and served to everyone. One pool blip would bake an empty program page in
    site-wide — exactly the failure that wrapper's docstring promises it
    prevents. Callers run this inside their own degraded-render guard, so
    letting it propagate is what marks the render degraded and keeps it
    uncached.
    """
    if not program_key:
        return []
    try:
        from app.services import program_registry
        program = program_registry.by_key(program_key, session)
    except Exception:
        program = None
    if program is None:
        # Genuinely unknown program (not a DB error) — it owns no leagues.
        return []
    from app.models import League
    q = (session.query(League) if session is not None else League.query)
    rows = q.with_entities(League.id, League.name).all()
    return [lid for lid, lname in rows
            if getattr(program_for_league_name(lname, session), 'key', None) == program.key]


def _current_season_id_by_type(session=None) -> Dict[str, int]:
    """{Season.league_type: current season id} across EVERY program.

    Not `current_program_seasons()`: that helper is scoped to pub-league-like
    season types, and the calendar shows ECS FC too.
    """
    try:
        from app.models import Season
        q = (session.query(Season) if session is not None else Season.query)
        rows = q.filter(Season.is_current.is_(True)).order_by(Season.id.asc()).all()
        return {s.league_type: s.id for s in rows if s.league_type}
    except Exception:
        logger.debug("Could not resolve current seasons for calendar programs", exc_info=True)
        return {}


def calendar_programs(session=None, with_league_ids: bool = False) -> List[Dict[str, Any]]:
    """The programs the calendar filters by, in registry sort order.

    Each entry: {key, label, color, league_name, league_id}. `league_id` is the
    CURRENT season's league for that program and is only resolved when
    `with_league_ids` is set (it costs a query) -- the event-scope picker needs
    it; the filter checkboxes do not.

    An empty list is a legitimate answer (registry unreachable). Callers must
    treat that as "no program filter available" and show everything, never as
    "no programs exist" -- filtering against an empty allow-list is exactly the
    bug this module was written to remove.
    """
    try:
        from app.services import program_registry
        programs = program_registry.all_programs(session)
    except Exception:
        logger.debug("program_registry unavailable building calendar programs", exc_info=True)
        return []

    season_ids = _current_season_id_by_type(session) if with_league_ids else {}
    leagues_by_key: Dict[str, int] = {}
    if with_league_ids and season_ids:
        try:
            from app.models import League
            q = (session.query(League) if session is not None else League.query)
            rows = q.filter(League.season_id.in_(list(season_ids.values()))).all()
            by_name = {(lg.name or '').strip().lower(): lg for lg in rows}
            for p in programs:
                season_id = season_ids.get(p.season_league_type)
                if season_id is None:
                    continue
                lg = by_name.get((p.league_name or '').strip().lower())
                if lg is not None and lg.season_id == season_id:
                    leagues_by_key[p.key] = lg.id
        except Exception:
            logger.debug("Could not resolve current leagues for calendar programs", exc_info=True)

    return [{
        'key': p.key,
        'label': p.display_name or p.league_name or p.key,
        'color': p.color or DEFAULT_COLOR,
        'league_name': p.league_name,
        'league_id': leagues_by_key.get(p.key),
    } for p in programs]
