# app/services/attendance_analytics.py

"""
Read side of the analytics spine: turns `player_season_participation` into the
rows, week-strips, follow-up lanes and season pulse the reports render.

Everything here reads the rollup, never recomputes from `availability` — except
`week_strips`, which needs per-match detail the rollup doesn't store and so does
one bounded per-season query. All scoping goes through `AnalyticsScope` so a
report can't accidentally filter on the wrong column.

Session discipline: every function takes an explicit session and uses it; no
`Model.query` (which would bind db.session and take a second pooled connection).
"""

import logging
from datetime import datetime

from sqlalchemy import text

from app.utils.analytics_scope import scope_participation_query

logger = logging.getLogger(__name__)


# Follow-up thresholds. Tuned to be actionable, not noisy — see each lane.
SLIPPING_DROP_PP = 15.0     # season turnout this many points below career = slipping
SLIPPING_MIN_SEASON = 3     # ...but only once they've played enough this season
SLIPPING_MIN_CAREER = 8     # ...and we know their career baseline
CHRONIC_MAX_PCT = 40.0      # career turnout at/below this...
CHRONIC_MIN_CAREER = 15     # ...over a real career sample = chronically low
NEVER_MIN_PLAYED = 3        # had at least this many chances and answered none


def _turnout(yes, played):
    """RSVP-yes rate over played matches, or None when nothing has been played."""
    if not played:
        return None
    return round(yes / played * 100, 1)


def build_attendance_rows(session, scope, min_played=0):
    """One row per participation record in scope, newest-team-name resolved.

    In a single-season scope this is one row per (player, league) membership. In an
    all-seasons scope a player appears once per season they played — callers that
    want a career roll-up use `career_turnout` instead.
    """
    from app.models import PlayerSeasonParticipation as PSP, Player, League, Team, Season

    # Player is selected as a query entity (fully loaded), so no joinedload and no
    # N+1 — avatar_image_url is a pure-Python property over a loaded column.
    q = (
        session.query(PSP, Player, League.name.label('league_name'),
                      Team.name.label('team_name'), Season.name.label('season_name'))
        .join(Player, Player.id == PSP.player_id)
        .join(League, League.id == PSP.league_id)
        .join(Season, Season.id == PSP.season_id)
        .outerjoin(Team, Team.id == PSP.team_id)
    )
    q = scope_participation_query(q, scope)
    if min_played:
        q = q.filter(PSP.matches_played >= min_played)

    rows = []
    for psp, player, league_name, team_name, season_name in q.all():
        rows.append({
            'player_id': player.id,
            'player': player.name,
            'avatar_url': player.avatar_image_url,
            'team': team_name or '—',
            'league': league_name,
            'season_name': season_name,
            'matches_scheduled': psp.matches_scheduled,
            'matches_played': psp.matches_played,
            'rsvp_yes': psp.rsvp_yes,
            'rsvp_no': psp.rsvp_no,
            'rsvp_maybe': psp.rsvp_maybe,
            'rsvp_none': psp.rsvp_none,
            'checked_in': psp.checked_in,
            'turnout_pct': psp.turnout_pct,
            'response_pct': psp.response_pct,
            'show_pct': psp.show_pct,
            'was_coach': psp.was_coach,
            'season_id': psp.season_id,
            'league_id': psp.league_id,
        })
    return rows


def career_turnout(session, player_ids, exclude_season_ids=None):
    """{player_id: {'turnout': float|None, 'played': int}} across a player's whole
    history, excluding import-baseline seasons.

    "Career" is lifetime and cross-league on purpose — it answers "who is this
    person overall", which is the baseline the slipping lane compares against.
    """
    if not player_ids:
        return {}
    excl = list(exclude_season_ids or [])
    rows = session.execute(text("""
        SELECT player_id,
               COALESCE(SUM(rsvp_yes), 0)       AS yes,
               COALESCE(SUM(matches_played), 0) AS played
          FROM player_season_participation
         WHERE player_id = ANY(:pids)
           AND (:has_excl = FALSE OR season_id <> ALL(:excl))
         GROUP BY player_id
    """), {
        'pids': list(player_ids),
        'excl': excl,
        'has_excl': bool(excl),
    }).mappings().all()

    out = {}
    for r in rows:
        out[r['player_id']] = {
            'turnout': _turnout(r['yes'], r['played']),
            'played': r['played'],
        }
    return out


def week_strips(session, scope, as_of=None):
    """{player_id: [{'date','resp'} ...]} in date order for the scoped season(s).

    resp is 'yes'|'no'|'maybe'|None (no reply). Only meaningful for a bounded
    season scope; callers skip it for all-time. Availability is deduped to one
    (latest) response per (match, player), same as the rollup.
    """
    if scope.season_ids is None:
        return {}
    as_of = as_of or datetime.utcnow().date()

    params = {'season_ids': list(scope.season_ids), 'as_of': as_of}
    league_clause = ""
    if scope.league_ids is not None:
        league_clause = "AND l.id = ANY(:league_ids)"
        params['league_ids'] = list(scope.league_ids)

    sql = text(f"""
        WITH pm AS (
            SELECT DISTINCT pts.player_id, m.id AS match_id, m.date AS d
              FROM player_team_season pts
              JOIN team   t ON t.id = pts.team_id
              JOIN league l ON l.id = t.league_id
              JOIN matches m ON (m.home_team_id = t.id OR m.away_team_id = t.id)
             WHERE l.season_id = ANY(:season_ids)
               {league_clause}
               AND m.week_type = 'REGULAR'
               AND m.home_team_id <> m.away_team_id
               AND m.date <= :as_of
        ),
        ded AS (
            -- Bounded to THIS scope's matches, not the whole availability table —
            -- this runs per page load and the DB budget is tight.
            SELECT DISTINCT ON (a.match_id, a.player_id) a.match_id, a.player_id, a.response
              FROM availability a
             WHERE a.match_id IN (SELECT match_id FROM pm)
             ORDER BY a.match_id, a.player_id, a.responded_at DESC NULLS LAST, a.id DESC
        )
        SELECT pm.player_id, pm.d, LOWER(ded.response) AS resp
          FROM pm
          LEFT JOIN ded ON ded.match_id = pm.match_id AND ded.player_id = pm.player_id
         ORDER BY pm.player_id, pm.d, pm.match_id
    """)

    strips = {}
    for r in session.execute(sql, params).mappings().all():
        resp = r['resp']
        if resp not in ('yes', 'no', 'maybe'):
            resp = None
        strips.setdefault(r['player_id'], []).append({'date': r['d'], 'resp': resp})
    return strips


def follow_up_lanes(session, scope):
    """Three actionable lists for the reports center, each a different problem.

    - slipping: turning out well below THEIR OWN career baseline (talk to them).
    - chronic:  low across their whole career (a drafting signal, not welfare).
    - never:    never answered an RSVP this season (contactability, not attendance).

    Returns {'slipping': [...], 'chronic': [...], 'never': [...]}, each row
    carrying enough to render a card and link to the player.

    Intended for a single-season scope (the reports center defaults to the current
    season). Rows are aggregated to ONE per player first, so a player rostered in
    both Premier and Classic — or, in an all-seasons scope, across seasons — is
    evaluated once and can never appear twice in a lane.
    """
    raw = build_attendance_rows(session, scope)
    if not raw:
        return {'slipping': [], 'chronic': [], 'never': []}

    agg = {}
    for r in raw:
        a = agg.get(r['player_id'])
        if a is None:
            a = {
                'player_id': r['player_id'], 'player': r['player'],
                'avatar_url': r['avatar_url'], 'team': r['team'], 'league': r['league'],
                'matches_played': 0, 'rsvp_yes': 0, 'rsvp_no': 0, 'rsvp_maybe': 0,
            }
            agg[r['player_id']] = a
        a['matches_played'] += r['matches_played']
        a['rsvp_yes'] += r['rsvp_yes']
        a['rsvp_no'] += r['rsvp_no']
        a['rsvp_maybe'] += r['rsvp_maybe']
        if a['team'] in (None, '—') and r['team'] not in (None, '—'):
            a['team'] = r['team']
    rows = list(agg.values())
    for r in rows:
        r['turnout_pct'] = _turnout(r['rsvp_yes'], r['matches_played'])

    career = career_turnout(session, list(agg.keys()),
                            exclude_season_ids=scope.baseline_season_ids)

    slipping, chronic, never = [], [], []
    for r in rows:
        c = career.get(r['player_id'], {})
        c_turn, c_played = c.get('turnout'), c.get('played', 0)
        answered = r['rsvp_yes'] + r['rsvp_no'] + r['rsvp_maybe']

        # never replied — had chances, answered none
        if r['matches_played'] >= NEVER_MIN_PLAYED and answered == 0:
            never.append({**r, 'career_turnout': c_turn})
            continue

        # slipping — meaningfully below their own baseline
        if (r['turnout_pct'] is not None and c_turn is not None
                and r['matches_played'] >= SLIPPING_MIN_SEASON
                and c_played >= SLIPPING_MIN_CAREER
                and (c_turn - r['turnout_pct']) >= SLIPPING_DROP_PP):
            slipping.append({**r, 'career_turnout': c_turn,
                             'drop': round(c_turn - r['turnout_pct'], 1)})
            continue

        # chronic — always low, over a real sample
        if c_turn is not None and c_played >= CHRONIC_MIN_CAREER and c_turn <= CHRONIC_MAX_PCT:
            chronic.append({**r, 'career_turnout': c_turn, 'career_played': c_played})

    slipping.sort(key=lambda r: -r['drop'])
    chronic.sort(key=lambda r: r['career_turnout'])
    never.sort(key=lambda r: (-r['matches_played'], r['player'].lower()))
    return {'slipping': slipping, 'chronic': chronic, 'never': never}


def season_pulse(session, scope):
    """Top-line season numbers for the reports center header.

    Turnout and response are weighted by matches (sum of yes / sum of played),
    NOT a mean of per-player rates — a mean lets a one-match player swing the
    league number as hard as a full-season one.
    """
    rows = build_attendance_rows(session, scope)
    players = len(rows)
    total_played = sum(r['matches_played'] for r in rows)
    total_yes = sum(r['rsvp_yes'] for r in rows)
    total_answered = sum(r['rsvp_yes'] + r['rsvp_no'] + r['rsvp_maybe'] for r in rows)
    total_checkin = sum(r['checked_in'] for r in rows)

    return {
        'players': players,
        'turnout_pct': _turnout(total_yes, total_played),
        'response_pct': _turnout(total_answered, total_played),
        'show_pct': _turnout(total_checkin, total_played) if total_checkin else None,
        'total_played': total_played,
    }
