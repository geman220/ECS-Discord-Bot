# app/utils/analytics_scope.py

"""
The one season x league scope contract every analytics page reads.

Why this exists
---------------
Each report currently invents its own scoping, and most of them get it wrong in a
different way:

- `_build_attendance` filters on `Player.primary_league_id`, which rollover
  repoints for every player — so "Premier" means "whose pointer happens to land on
  a Premier row right now", not "played in Premier".
- Several reports have no season concept at all and present all-time numbers under
  a current-season heading.
- `Season.is_current` is TRUE for Pub League and ECS FC simultaneously, so the
  common `filter_by(is_current=True).first()` returns an arbitrary one.
- `League.season_id` is NOT NULL, meaning "Premier" is a DIFFERENT League row every
  season. Filtering by `League.name` therefore silently spans all seasons.

`AnalyticsScope` resolves both axes once, from the query string, and hands back
season ids and league ids. Reports join on ids, never on names.

Session discipline
------------------
Every function takes an explicit session. `app/utils/season_context.py` uses
`Season.query` (i.e. db.session), which inside a request is a SECOND session and
therefore a second pooled connection on a 22-connection budget. This module never
does that.
"""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

PUB_LEAGUE = 'Pub League'
ECS_FC = 'ECS FC'

# `league` query-param values that are not a literal League.name.
LEAGUE_ALL = 'all'
LEAGUE_PUB = 'pub'          # Premier + Classic
PUB_LEAGUE_NAMES = ('Premier', 'Classic')

# `season` query-param values that are not an id.
SEASON_CURRENT = 'current'
SEASON_ALL = 'all'


class AnalyticsScope:
    """Resolved season x league scope. Immutable once built.

    Attributes:
        season_ids: list of Season.id, or None meaning "every season".
        league_ids: list of League.id, or None meaning "every league".
        season_label / league_label: human strings for the UI chip.
        is_current: whether the season axis resolved to the live season.
        include_baseline: whether import-baseline seasons are included.
    """

    def __init__(self, season_ids, league_ids, season_label, league_label,
                 is_current, include_baseline, season_param, league_param,
                 seasons, baseline_season_ids):
        self.season_ids = season_ids
        self.league_ids = league_ids
        self.season_label = season_label
        self.league_label = league_label
        self.is_current = is_current
        self.include_baseline = include_baseline
        self.season_param = season_param
        self.league_param = league_param
        self.seasons = seasons                       # [{id, name, is_current, is_baseline}]
        self.baseline_season_ids = baseline_season_ids

    @property
    def chips(self):
        """Active-filter chips for the UI, in display order."""
        out = [f"Season: {self.season_label}", f"League: {self.league_label}"]
        if self.baseline_season_ids and not self.include_baseline:
            out.append("Excludes import baseline")
        return out

    def as_query_args(self, **overrides):
        """Current scope as url_for kwargs, with optional overrides.

        Lets a template swap one axis while preserving the other, which is what
        makes the scope bar links work.
        """
        args = {'season': self.season_param, 'league': self.league_param}
        if self.include_baseline:
            args['baseline'] = 1
        args.update(overrides)
        return {k: v for k, v in args.items() if v not in (None, '')}

    def __repr__(self):
        return (f'<AnalyticsScope season={self.season_label} league={self.league_label} '
                f'seasons={self.season_ids} leagues={self.league_ids}>')


def _load_seasons(session, league_type=PUB_LEAGUE):
    """All seasons of a league type, newest first, with baseline flags.

    Ordered by start_date DESC NULLS LAST then id DESC. Every season in production
    currently has a NULL start_date, so the id tiebreak is doing all the work —
    which happens to be chronological. The explicit NULLS LAST is what keeps a
    dated season sorting ahead of an undated one if that ever changes.
    """
    rows = session.execute(text("""
        SELECT id, name, is_current,
               COALESCE(is_analytics_baseline, FALSE) AS is_baseline
          FROM season
         WHERE league_type = :lt
         ORDER BY start_date DESC NULLS LAST, id DESC
    """), {'lt': league_type}).mappings().all()
    return [dict(r) for r in rows]


def _resolve_leagues(session, league_param, season_ids, league_type=PUB_LEAGUE):
    """Map the league param to concrete League.ids within the season scope.

    Returns (league_ids, label). `league_ids` is None for "every league".

    League rows are per-season, so this resolves NAMES to the ids belonging to the
    seasons in scope. That is the whole point: "Premier, 2025 Fall" is a different
    League.id from "Premier, 2026 Spring", and a report must use the right one.
    """
    param = (league_param or LEAGUE_ALL).strip()

    if param in (LEAGUE_ALL, ''):
        return None, 'All leagues'

    if param == LEAGUE_PUB:
        names = list(PUB_LEAGUE_NAMES)
        label = 'Pub League'
    else:
        names = [param]
        label = param

    sql = """
        SELECT l.id FROM league l
         WHERE l.name = ANY(:names)
    """
    params = {'names': names}
    if season_ids is not None:
        sql += " AND l.season_id = ANY(:season_ids)"
        params['season_ids'] = season_ids

    ids = session.execute(text(sql), params).scalars().all()
    if not ids:
        # Honest empty rather than silently widening to every league.
        logger.info(f"AnalyticsScope: no League rows for {names} in seasons {season_ids}")
    return list(ids), label


def resolve_scope(session, args=None, league_type=PUB_LEAGUE):
    """Build an AnalyticsScope from request args.

    Query params:
        season   'current' (default) | '<season_id>' | 'all'
        league   'all' (default) | 'pub' | 'Premier' | 'Classic' | 'ECS FC'
        baseline '1' to include import-baseline seasons in ranges

    An unknown or non-Pub-League season id falls back to current rather than
    erroring — a stale bookmark should show something sensible, not a 500.
    """
    from flask import request
    args = args if args is not None else request.args

    # ECS FC keeps its own season timeline (its own is_current season), so when the
    # league filter is ECS FC the season axis must resolve against ECS FC seasons —
    # otherwise the pills would show Pub League seasons that ECS FC data never uses.
    if (args.get('league') or '').strip() == ECS_FC:
        league_type = ECS_FC

    seasons = _load_seasons(session, league_type)
    baseline_ids = [s['id'] for s in seasons if s['is_baseline']]
    include_baseline = str(args.get('baseline', '')).strip() in ('1', 'true', 'yes')

    season_param = (args.get('season') or SEASON_CURRENT).strip()
    by_id = {s['id']: s for s in seasons}

    if season_param == SEASON_ALL:
        # None means "no season filter at all". Only correct when we genuinely want
        # every season — i.e. baselines are being included. Otherwise we must pass an
        # explicit id list so the baseline is actually excluded.
        if include_baseline:
            season_ids = None
        else:
            season_ids = [s['id'] for s in seasons if s['id'] not in baseline_ids]
        season_label, is_current = 'All seasons', False
    else:
        target = None
        if season_param != SEASON_CURRENT:
            try:
                candidate = int(season_param)
                if candidate in by_id:
                    target = by_id[candidate]
            except (TypeError, ValueError):
                target = None
        if target is None:
            # Highest id wins if is_current is somehow set on more than one row —
            # the same tiebreak every other read path in the app uses.
            currents = [s for s in seasons if s['is_current']]
            target = currents[0] if currents else (seasons[0] if seasons else None)

        if target is None:
            season_ids, season_label, is_current = [], 'No seasons', False
        else:
            season_ids = [target['id']]
            season_label = target['name']
            is_current = bool(target['is_current'])
            season_param = SEASON_CURRENT if is_current else str(target['id'])

    league_ids, league_label = _resolve_leagues(
        session, args.get('league'), season_ids, league_type)

    # NOT `season_ids or None` — an empty list means "no season matched" and must stay
    # empty. Collapsing it to None would mean "no filter", i.e. show EVERY season, which
    # is the exact opposite and would leak the excluded baseline back into the numbers.
    return AnalyticsScope(
        season_ids=season_ids,
        league_ids=league_ids,
        season_label=season_label,
        league_label=league_label,
        is_current=is_current,
        include_baseline=include_baseline,
        season_param=season_param,
        league_param=(args.get('league') or LEAGUE_ALL),
        seasons=seasons,
        baseline_season_ids=baseline_ids,
    )


def scope_participation_query(query, scope):
    """Apply a resolved scope to a PlayerSeasonParticipation query.

    The single place scoping is translated into filters, so a report can never
    accidentally scope on the wrong column.
    """
    from app.models import PlayerSeasonParticipation as PSP

    if scope.season_ids is not None:
        query = query.filter(PSP.season_id.in_(scope.season_ids))
    if scope.league_ids is not None:
        query = query.filter(PSP.league_id.in_(scope.league_ids))
    return query
