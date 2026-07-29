# app/utils/season_context.py

"""
Season / league context resolution for admin pages.

Background
----------
Both Pub League and ECS FC have their own ``is_current=True`` Season row
(``Season.league_type`` is 'Pub League' or 'ECS FC'). So the very common

    Season.query.filter_by(is_current=True).first()

returns an ARBITRARY current season — frequently the ECS FC one — which makes
Pub-League pages (standings, league table, schedule between our internal teams)
silently show empty/wrong data. The ``publeague`` blueprint resolves this
correctly in a ``before_request`` (g.current_pub_league_season), but that hook
does NOT run for ``admin_panel`` routes.

This module gives admin routes a single, league-scoped resolver. Pub-League is
an internal league (Match = home_team vs away_team) with rotating seasons and a
real Standings table, so its pages default to the current Pub League season and
allow picking PAST seasons for history via ?season_id=. ECS FC is a set of
disjoint teams playing EXTERNAL opponents (EcsFcMatch.opponent_name) with no
league table — it keeps its own team-centric section and is not toggled onto
Pub-League pages.
"""

PUB_LEAGUE = 'Pub League'
ECS_FC = 'ECS FC'


# ---------------------------------------------------------------------------
# Program-aware resolution
#
# ⚠️ 'Pub League' is a SEASON TYPE, not "the pub leagues".
#
# Every program declares its own `Season.league_type` so it can own an
# `is_current` row without disturbing anyone else's — Summer Sprint's seasons
# are 'PL Third'. So `filter_by(league_type='Pub League', is_current=True)` does
# NOT mean "the current pub-league-ish season"; it means "Premier and Classic's
# season, specifically", and it silently excludes every other program.
#
# That single line, copied ~26 times across the app, is why a Summer Sprint
# order was invisible on the orders page: not an error, not an empty state, just
# a row that fell outside a filter nobody thought of as a filter.
#
# The rule of thumb for choosing between these:
#   * `current_pub_league_season()`      — you genuinely mean Premier/Classic
#     (rollover, the Pub League lifecycle, a Premier-vs-Classic split).
#   * `current_program_seasons()` / `_ids()` — you mean "whatever seasons are
#     running right now", which is what almost every dashboard, roster lookup,
#     substitute query, draft gate and stats aggregate actually wants.
# ---------------------------------------------------------------------------

def pub_league_like_season_types():
    """Every `Season.league_type` whose programs use the Pub League machinery.

    Degrades to ['Pub League'] if the registry is unreachable, which is exactly
    the old hardcoded behaviour — a missing `program` table must never widen or
    narrow a query in a way the caller cannot see.
    """
    try:
        from app.services import program_registry
        return program_registry.pub_league_like_season_types() or [PUB_LEAGUE]
    except Exception:
        return [PUB_LEAGUE]


def current_program_seasons(session=None):
    """Every CURRENT season across all pub-league-like programs, newest id first.

    Returns a list precisely because there is more than one — a `.first()` here
    is the bug this function exists to remove.
    """
    from app.models import Season
    q = (session.query(Season) if session is not None else Season.query)
    return (q.filter(Season.league_type.in_(pub_league_like_season_types()),
                     Season.is_current.is_(True))
             .order_by(Season.id.desc()).all())


def current_program_season_ids(session=None):
    """Ids of `current_program_seasons()` — for `.in_(...)` scoping.

    Note an empty list is a legitimate answer (no season is current). Callers
    must treat that as "no seasons", NOT as "no filter": `col.in_([])` correctly
    matches nothing, but an `if ids:` guard that skips the filter entirely would
    silently widen the query to every season in history.
    """
    return [s.id for s in current_program_seasons(session)]


def current_season_for_program(program_key, session=None):
    """The current season of ONE program, resolved through the registry.

    Use when a page is genuinely about a single program and you know which.
    Returns None when the program is unknown, inactive, or has no current
    season — never another program's season, which is the failure mode that
    binds a paid order or a roster row to the wrong place.
    """
    from app.models import Season
    try:
        from app.services import program_registry
        pr = program_registry.by_key(program_key) or program_registry.by_membership_lane(program_key)
        if pr is None:
            pr = program_registry.by_league_name(program_key)
        if pr is None or not pr.season_league_type:
            return None
        season_type = pr.season_league_type
    except Exception:
        return None
    q = (session.query(Season) if session is not None else Season.query)
    return q.filter(Season.league_type == season_type,
                    Season.is_current.is_(True)).first()


def current_pub_league_season():
    """The current Pub League season (league_type-scoped), or None."""
    from app.models import Season
    return Season.query.filter_by(is_current=True, league_type=PUB_LEAGUE).first()


def pub_league_seasons():
    """All Pub League seasons, newest first — for the season-history dropdown."""
    from app.models import Season
    return Season.query.filter_by(league_type=PUB_LEAGUE).order_by(Season.id.desc()).all()


def resolve_pub_league_season(season_id=None):
    """Return the selected Pub League season.

    If ``season_id`` is given and is a valid Pub League season, return that
    (historical view); otherwise fall back to the current Pub League season.
    Never returns an ECS FC season.
    """
    from app.models import Season
    if season_id not in (None, '', 'current'):
        try:
            sid = int(season_id)
        except (TypeError, ValueError):
            sid = None
        if sid:
            s = Season.query.filter_by(id=sid, league_type=PUB_LEAGUE).first()
            if s:
                return s
    return current_pub_league_season()


def pub_league_season_context(season_id=None):
    """Convenience for a page + its selector.

    Returns ``(selected_season, seasons)`` where ``selected_season`` is the
    historical-or-current Pub League season and ``seasons`` is the full
    newest-first list for the dropdown. ``request.args.get('season_id')`` is the
    expected source for ``season_id``.
    """
    return resolve_pub_league_season(season_id), pub_league_seasons()
