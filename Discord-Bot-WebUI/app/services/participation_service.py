# app/services/participation_service.py

"""
Builds and refreshes the per-(player, season, league) participation rollup.

Design notes
------------
Everything here is SET-BASED: one INSERT ... SELECT per season, not a Python loop
over players. The previous attendance recompute issued ~11 queries per player and
took minutes for ~250 players; this does a whole season in a handful of
statements. That matters because the database is behind PgBouncer with a small
connection budget — transaction HOLD TIME is the scarce resource, not CPU.

Season attribution
------------------
Season comes from ``team -> league -> league.season_id``, never from
``Schedule.season_id``. Historical schedules have null/orphaned ``season_id``
(documented in app/models/stats.py), so joining through Schedule silently drops
older seasons. Because Pub League teams are recreated every season, ``team_id``
already encodes exactly one (team, season) pair, which makes the team join
sufficient and correct.

What counts as a match
----------------------
- ``week_type = 'REGULAR'`` — excludes FUN/TST/BYE/PLAYOFF/PRACTICE/BONUS.
- ``home_team_id <> away_team_id`` — special weeks are stored as self-match
  placeholder rows, and production has 9 of them mislabelled as REGULAR, so the
  week_type filter alone is not enough.
- ``date <= today`` for ``matches_played`` — the honest denominator.

Playoffs are deliberately excluded: they are a separate competition in which
every team participates, so folding them into season turnout would mix two
different things. If playoff participation is wanted it belongs in its own
columns, not blended into these.
"""

import logging
from datetime import datetime

from sqlalchemy import text

logger = logging.getLogger(__name__)


# One statement builds every row for a season. Written as raw SQL rather than ORM
# because it is a bulk upsert over three source tables and the ORM equivalent
# would either N+1 or be unreadable.
_REFRESH_SQL = text("""
WITH roster AS (
    -- Every (player, season, league) that was rostered, with their team(s).
    SELECT pts.player_id,
           l.season_id,
           l.id                              AS league_id,
           MIN(pts.team_id)                  AS any_team_id,
           COUNT(DISTINCT pts.team_id)       AS team_count,
           BOOL_OR(COALESCE(pts.is_coach, FALSE)) AS was_coach,
           ARRAY_AGG(DISTINCT pts.team_id)   AS team_ids
      FROM player_team_season pts
      JOIN team   t ON t.id = pts.team_id
      JOIN league l ON l.id = t.league_id
     WHERE l.season_id = :season_id
     GROUP BY pts.player_id, l.season_id, l.id
),
fixtures AS (
    -- Every real fixture belonging to each roster row's team(s).
    SELECT r.player_id,
           r.season_id,
           r.league_id,
           m.id        AS match_id,
           m.date      AS match_date,
           (m.date <= :as_of) AS is_played
      FROM roster r
      JOIN matches m
        ON (m.home_team_id = ANY(r.team_ids) OR m.away_team_id = ANY(r.team_ids))
     WHERE m.week_type = 'REGULAR'
       AND m.home_team_id <> m.away_team_id
),
agg AS (
    SELECT f.player_id,
           f.season_id,
           f.league_id,
           COUNT(DISTINCT f.match_id)                                    AS matches_scheduled,
           COUNT(DISTINCT f.match_id) FILTER (WHERE f.is_played)          AS matches_played,
           COUNT(DISTINCT f.match_id) FILTER (
               WHERE f.is_played AND LOWER(a.response) = 'yes')           AS rsvp_yes,
           COUNT(DISTINCT f.match_id) FILTER (
               WHERE f.is_played AND LOWER(a.response) = 'no')            AS rsvp_no,
           COUNT(DISTINCT f.match_id) FILTER (
               WHERE f.is_played AND LOWER(a.response) = 'maybe')         AS rsvp_maybe,
           COUNT(DISTINCT f.match_id) FILTER (
               WHERE f.is_played AND (a.response IS NULL
                     OR LOWER(a.response) NOT IN ('yes','no','maybe')))  AS rsvp_none,
           -- Gated on is_played so the numerator shares the denominator's date
           -- predicate — otherwise an early/clock-skewed check-in on a
           -- not-yet-played fixture could push show_pct above 100%.
           COUNT(DISTINCT f.match_id) FILTER (
               WHERE f.is_played AND att.player_id IS NOT NULL)          AS checked_in,
           MIN(f.match_date)                                             AS first_match_date,
           MAX(f.match_date)                                             AS last_match_date,
           MAX(f.match_date) FILTER (
               WHERE f.is_played AND LOWER(a.response) = 'yes')           AS last_played_date
      FROM fixtures f
      -- Dedup availability to ONE response per (match, player), latest wins.
      -- There is NO unique constraint on availability(match_id, player_id), and
      -- RSVPs arrive from Discord / web / SMS / mobile, so a race can leave two
      -- rows. Joining them raw would let a player's 'yes' AND 'no' for one match
      -- both count, so the rsvp buckets would sum to MORE than matches_played and
      -- the turnout denominator would no longer match the parts.
      LEFT JOIN (
          SELECT DISTINCT ON (match_id, player_id)
                 match_id, player_id, response
            FROM availability
           ORDER BY match_id, player_id, responded_at DESC NULLS LAST, id DESC
      ) a ON a.match_id = f.match_id AND a.player_id = f.player_id
      LEFT JOIN match_attendance att
             ON att.match_id = f.match_id
            AND att.player_id = f.player_id
            AND att.league_type = 'pub_league'
     GROUP BY f.player_id, f.season_id, f.league_id
)
INSERT INTO player_season_participation (
    player_id, season_id, league_id, team_id, team_count,
    matches_scheduled, matches_played,
    rsvp_yes, rsvp_no, rsvp_maybe, rsvp_none, checked_in,
    was_coach, first_match_date, last_match_date, last_played_date, last_computed_at
)
SELECT r.player_id, r.season_id, r.league_id,
       CASE WHEN r.team_count = 1 THEN r.any_team_id ELSE NULL END,
       r.team_count,
       COALESCE(agg.matches_scheduled, 0),
       COALESCE(agg.matches_played, 0),
       COALESCE(agg.rsvp_yes, 0),
       COALESCE(agg.rsvp_no, 0),
       COALESCE(agg.rsvp_maybe, 0),
       COALESCE(agg.rsvp_none, 0),
       COALESCE(agg.checked_in, 0),
       r.was_coach,
       agg.first_match_date, agg.last_match_date, agg.last_played_date,
       now()
  FROM roster r
  LEFT JOIN agg
         ON agg.player_id = r.player_id
        AND agg.season_id = r.season_id
        AND agg.league_id = r.league_id
ON CONFLICT (player_id, season_id, league_id) DO UPDATE SET
    team_id           = EXCLUDED.team_id,
    team_count        = EXCLUDED.team_count,
    matches_scheduled = EXCLUDED.matches_scheduled,
    matches_played    = EXCLUDED.matches_played,
    rsvp_yes          = EXCLUDED.rsvp_yes,
    rsvp_no           = EXCLUDED.rsvp_no,
    rsvp_maybe        = EXCLUDED.rsvp_maybe,
    rsvp_none         = EXCLUDED.rsvp_none,
    checked_in        = EXCLUDED.checked_in,
    was_coach         = EXCLUDED.was_coach,
    first_match_date  = EXCLUDED.first_match_date,
    last_match_date   = EXCLUDED.last_match_date,
    last_played_date  = EXCLUDED.last_played_date,
    last_computed_at  = EXCLUDED.last_computed_at
""")


# Rows whose roster assignment disappeared (undrafted, moved, roster row deleted)
# must not linger — otherwise a player shows up in a league they were removed from.
_PRUNE_SQL = text("""
DELETE FROM player_season_participation psp
 WHERE psp.season_id = :season_id
   AND NOT EXISTS (
        SELECT 1
          FROM player_team_season pts
          JOIN team   t ON t.id = pts.team_id
          JOIN league l ON l.id = t.league_id
         WHERE pts.player_id = psp.player_id
           AND l.season_id   = psp.season_id
           AND l.id          = psp.league_id
   )
""")


# ---------------------------------------------------------------------
# ECS FC variant. ECS FC teams play EXTERNAL opponents, so fixtures live in
# ecs_fc_matches (no week_type, no self-match), RSVPs in ecs_fc_availability
# (UPPERCASE responses), and check-ins in match_attendance with league_type
# 'ecs_fc'. ECS FC cares about its OWN turnout — who shows up for the team —
# not who they play, so the same rollup shape applies with these sources.
# ---------------------------------------------------------------------
_REFRESH_ECS_FC_SQL = text("""
WITH roster AS (
    SELECT pts.player_id,
           l.season_id,
           l.id                              AS league_id,
           MIN(pts.team_id)                  AS any_team_id,
           COUNT(DISTINCT pts.team_id)       AS team_count,
           BOOL_OR(COALESCE(pts.is_coach, FALSE)) AS was_coach,
           ARRAY_AGG(DISTINCT pts.team_id)   AS team_ids
      FROM player_team_season pts
      JOIN team   t ON t.id = pts.team_id
      JOIN league l ON l.id = t.league_id
     WHERE l.season_id = :season_id
     GROUP BY pts.player_id, l.season_id, l.id
),
fixtures AS (
    SELECT r.player_id, r.season_id, r.league_id,
           m.id         AS match_id,
           m.match_date AS match_date,
           (m.match_date <= :as_of) AS is_played
      FROM roster r
      JOIN ecs_fc_matches m ON m.team_id = ANY(r.team_ids)
     WHERE COALESCE(m.status, '') <> 'CANCELLED'
),
ded AS (
    SELECT DISTINCT ON (a.ecs_fc_match_id, a.player_id) a.ecs_fc_match_id, a.player_id, a.response
      FROM ecs_fc_availability a
     WHERE a.ecs_fc_match_id IN (SELECT match_id FROM fixtures)
     ORDER BY a.ecs_fc_match_id, a.player_id, a.responded_at DESC NULLS LAST, a.id DESC
),
agg AS (
    SELECT f.player_id, f.season_id, f.league_id,
           COUNT(DISTINCT f.match_id)                                   AS matches_scheduled,
           COUNT(DISTINCT f.match_id) FILTER (WHERE f.is_played)        AS matches_played,
           COUNT(DISTINCT f.match_id) FILTER (
               WHERE f.is_played AND UPPER(ded.response) = 'YES')       AS rsvp_yes,
           COUNT(DISTINCT f.match_id) FILTER (
               WHERE f.is_played AND UPPER(ded.response) = 'NO')        AS rsvp_no,
           COUNT(DISTINCT f.match_id) FILTER (
               WHERE f.is_played AND UPPER(ded.response) = 'MAYBE')     AS rsvp_maybe,
           COUNT(DISTINCT f.match_id) FILTER (
               WHERE f.is_played AND (ded.response IS NULL
                     OR UPPER(ded.response) NOT IN ('YES','NO','MAYBE'))) AS rsvp_none,
           COUNT(DISTINCT f.match_id) FILTER (
               WHERE f.is_played AND att.player_id IS NOT NULL)         AS checked_in,
           MIN(f.match_date)                                            AS first_match_date,
           MAX(f.match_date)                                            AS last_match_date,
           MAX(f.match_date) FILTER (
               WHERE f.is_played AND UPPER(ded.response) = 'YES')       AS last_played_date
      FROM fixtures f
      LEFT JOIN ded ON ded.ecs_fc_match_id = f.match_id AND ded.player_id = f.player_id
      LEFT JOIN match_attendance att
             ON att.match_id = f.match_id
            AND att.player_id = f.player_id
            AND att.league_type = 'ecs_fc'
     GROUP BY f.player_id, f.season_id, f.league_id
)
INSERT INTO player_season_participation (
    player_id, season_id, league_id, team_id, team_count,
    matches_scheduled, matches_played,
    rsvp_yes, rsvp_no, rsvp_maybe, rsvp_none, checked_in,
    was_coach, first_match_date, last_match_date, last_played_date, last_computed_at
)
SELECT r.player_id, r.season_id, r.league_id,
       CASE WHEN r.team_count = 1 THEN r.any_team_id ELSE NULL END,
       r.team_count,
       COALESCE(agg.matches_scheduled, 0), COALESCE(agg.matches_played, 0),
       COALESCE(agg.rsvp_yes, 0), COALESCE(agg.rsvp_no, 0),
       COALESCE(agg.rsvp_maybe, 0), COALESCE(agg.rsvp_none, 0),
       COALESCE(agg.checked_in, 0),
       r.was_coach, agg.first_match_date, agg.last_match_date, agg.last_played_date, now()
  FROM roster r
  LEFT JOIN agg ON agg.player_id = r.player_id
               AND agg.season_id = r.season_id
               AND agg.league_id = r.league_id
ON CONFLICT (player_id, season_id, league_id) DO UPDATE SET
    team_id           = EXCLUDED.team_id,
    team_count        = EXCLUDED.team_count,
    matches_scheduled = EXCLUDED.matches_scheduled,
    matches_played    = EXCLUDED.matches_played,
    rsvp_yes          = EXCLUDED.rsvp_yes,
    rsvp_no           = EXCLUDED.rsvp_no,
    rsvp_maybe        = EXCLUDED.rsvp_maybe,
    rsvp_none         = EXCLUDED.rsvp_none,
    checked_in        = EXCLUDED.checked_in,
    was_coach         = EXCLUDED.was_coach,
    first_match_date  = EXCLUDED.first_match_date,
    last_match_date   = EXCLUDED.last_match_date,
    last_played_date  = EXCLUDED.last_played_date,
    last_computed_at  = EXCLUDED.last_computed_at
""")


def refresh_season_participation(session, season_id, as_of=None, league_type='Pub League'):
    """Rebuild the participation rollup for one season. Returns a small summary.

    Idempotent — safe to run repeatedly. ``as_of`` (a date) exists so a backfill of
    a completed season can be computed as of its end rather than today; it defaults
    to today, which is what the nightly refresh wants. ``league_type`` selects the
    fixture/RSVP source: Pub League (matches/availability) or ECS FC
    (ecs_fc_matches/ecs_fc_availability).
    """
    as_of = as_of or datetime.utcnow().date()

    sql = _REFRESH_ECS_FC_SQL if league_type == 'ECS FC' else _REFRESH_SQL
    session.execute(sql, {'season_id': season_id, 'as_of': as_of})
    pruned = session.execute(_PRUNE_SQL, {'season_id': season_id}).rowcount

    summary = session.execute(text("""
        SELECT COUNT(*)                    AS rows,
               COALESCE(SUM(matches_played), 0) AS played,
               COALESCE(SUM(rsvp_yes), 0)       AS yes,
               COALESCE(SUM(checked_in), 0)     AS checked_in
          FROM player_season_participation
         WHERE season_id = :season_id
    """), {'season_id': season_id}).mappings().first()

    result = {
        'season_id': season_id,
        'league_type': league_type,
        'rows': summary['rows'],
        'matches_played': summary['played'],
        'rsvp_yes': summary['yes'],
        'checked_in': summary['checked_in'],
        'pruned': pruned,
        'as_of': as_of.isoformat(),
    }
    logger.info(f"Participation refresh: {result}")
    return result


def refresh_all_seasons(session, league_type=None):
    """Backfill every season, oldest first. ``league_type`` None = both Pub League
    and ECS FC (the post-migration backfill); pass one to restrict.

    Each season is computed as of its own end_date where one exists, so a completed
    season's ``matches_played`` reflects the season, not today.
    """
    league_types = [league_type] if league_type else ['Pub League', 'ECS FC']
    results = []
    for lt in league_types:
        rows = session.execute(text("""
            SELECT id, name, end_date
              FROM season
             WHERE league_type = :lt
             ORDER BY start_date NULLS LAST, id
        """), {'lt': lt}).mappings().all()
        for row in rows:
            results.append(refresh_season_participation(
                session, row['id'], as_of=row['end_date'], league_type=lt))
    return results


def current_season_ids(session, league_type='Pub League'):
    """Current season id(s) for a league type.

    Returns a list because `Season.is_current` has no uniqueness constraint and
    the codebase already assumes duplicates are possible. Callers that need one
    id should take the highest — that is what every other read path does.
    """
    rows = session.execute(text("""
        SELECT id FROM season
         WHERE is_current IS TRUE AND league_type = :lt
         ORDER BY id DESC
    """), {'lt': league_type}).scalars().all()
    return list(rows)
