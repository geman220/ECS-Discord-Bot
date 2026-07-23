# app/services/substitute_availability_service.py

"""
Substitute Availability Service — the single API for the closed-loop sub pool.

`substitute_availability` is the canonical "who can sub this week" surface. It is
fed by TWO front doors, both of which funnel through this module so there is exactly
one place that writes availability:

  1. Discord availability poll votes  -> sync_availability_from_poll_vote()
  2. Admin reach-out responses (push / Discord DM / secure web link)
                                       -> record_reachout_response()

Everything else (the admin board panel, the assign flow, mobile) READS availability
through get_week_availability() / get_candidates_for_request().

Scope: Pub League only (Classic / Premier), matching the /subs Discord integration.
One row per (player_id, match_date, league_type); time-slot scoped, never tied to a
single team/request, so any available sub can be assigned to any matching OPEN request.
"""

import logging
from datetime import datetime, timedelta

from app.models import (
    SubstituteAvailability, SubstitutePool, SubstituteAssignment, SubstituteRequest,
    Player,
)
from app.models.matches import Match

logger = logging.getLogger(__name__)

# Canonical Pub League sub lanes. ECS FC is intentionally excluded (divergent backend).
PUB_LEAGUE_TYPES = ('Classic', 'Premier')

# Availability rows are segregated by SOURCE BUCKET so the two independent doors
# (Discord poll vs admin reach-out) never clobber each other's slots. Reads
# aggregate the (<=2) rows per player/date/league.
SOURCE_POLL = 'discord_poll'
SOURCE_REACHOUT = 'reachout'


def _bucket(source):
    """Collapse a detailed source ('reachout_push'/'reachout_dm'/'reachout_web'/
    'mobile'/'web') to its storage bucket. Poll stays 'discord_poll'."""
    return SOURCE_POLL if source == SOURCE_POLL else SOURCE_REACHOUT


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def upcoming_availability_date(today=None):
    """The Sunday the availability pool is keyed on (next Sunday, or today if Sunday)."""
    from app.utils.pacific_time import pacific_today
    today = today or pacific_today()
    return today + timedelta(days=(6 - today.weekday()) % 7)


# ---------------------------------------------------------------------------
# Write path 1: Discord poll votes
# ---------------------------------------------------------------------------

def sync_availability_from_poll_vote(session, poll, discord_user_id):
    """Recompute a player's availability rows for `poll.match_date` from their
    CURRENT active votes on `poll`. Called after every add/remove vote webhook, so
    it must be idempotent.

    The poll's `slot_map` maps str(answer_id) -> {league_type, slots, match_ids}.
    A multiselect voter may pick several buckets across leagues; we union the slots
    and match_ids per league_type and upsert one availability row per league.

    Unmapped Discord voters (no linked Player) are a no-op here — they still live in
    `discord_poll_votes` and surface in the reconcile view for manual linking.
    """
    from app.models.discord_polls import DiscordPollVote

    if not poll or not poll.match_date or not poll.slot_map:
        return

    player = session.query(Player).filter_by(discord_id=str(discord_user_id)).first()
    if not player:
        return  # unmapped voter — nothing to write to the pool

    # Current active votes for this player on this poll.
    active_votes = session.query(DiscordPollVote).filter(
        DiscordPollVote.poll_id == poll.id,
        DiscordPollVote.discord_user_id == str(discord_user_id),
        DiscordPollVote.removed_at.is_(None),
    ).all()

    # Union slots + match_ids per league_type from the buckets they voted for.
    by_league = {}  # league_type -> {'slots': set, 'match_ids': set}
    for v in active_votes:
        bucket = poll.slot_map.get(str(v.answer_id))
        if not bucket:
            continue
        league_type = bucket.get('league_type')
        if league_type not in PUB_LEAGUE_TYPES:
            continue
        agg = by_league.setdefault(league_type, {'slots': set(), 'match_ids': set()})
        agg['slots'].update(bucket.get('slots') or [])
        agg['match_ids'].update(bucket.get('match_ids') or [])

    # Upsert availability for each league the player now has active votes in.
    for league_type, agg in by_league.items():
        _upsert(
            session,
            player_id=player.id,
            match_date=poll.match_date,
            league_type=league_type,
            is_available=True,
            time_slots=sorted(agg['slots']),
            match_ids=sorted(agg['match_ids']),
            source='discord_poll',
            poll_id=poll.id,
            season_id=poll.season_id,
        )

    # Any POLL-sourced availability rows for this date/player that no longer have a
    # backing vote get cleared (is_available=False). We only touch poll-sourced rows so
    # a separate reach-out "yes" for the same league is never silently revoked here.
    stale = session.query(SubstituteAvailability).filter(
        SubstituteAvailability.player_id == player.id,
        SubstituteAvailability.match_date == poll.match_date,
        SubstituteAvailability.source == 'discord_poll',
        SubstituteAvailability.league_type.notin_(list(by_league.keys()) or ['__none__']),
    ).all()
    for row in stale:
        row.is_available = False
        row.time_slots = []
        row.match_ids = []
        row.updated_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# Write path 2: admin reach-out responses
# ---------------------------------------------------------------------------

def record_reachout_response(session, *, player_id, match_date, league_type,
                             is_available, time_slots=None, match_ids=None,
                             source='reachout_push', poll_id=None, season_id=None,
                             notes=None):
    """Upsert availability from an admin reach-out response.

    Works for both reach-out kinds — a general "can anyone sub at these times?" blast
    and a targeted "can you sub for this specific time?" ask. A 'yes' unions the offered
    slots into the pool; a 'no' marks the row unavailable (keeps a record so we don't
    re-pester). The team is never part of this record — availability is team-agnostic.
    """
    if league_type not in PUB_LEAGUE_TYPES:
        logger.warning("record_reachout_response: unsupported league_type %r", league_type)
        return None
    return _upsert(
        session,
        player_id=player_id,
        match_date=match_date,
        league_type=league_type,
        is_available=bool(is_available),
        time_slots=list(time_slots or []),
        match_ids=list(match_ids or []),
        source=source,
        poll_id=poll_id,
        season_id=season_id,
        notes=notes,
        merge_slots=True,
    )


# ---------------------------------------------------------------------------
# Shared upsert
# ---------------------------------------------------------------------------

def _upsert(session, *, player_id, match_date, league_type, is_available,
            time_slots, match_ids, source, poll_id=None, season_id=None,
            notes=None, merge_slots=False):
    """Insert or update the (player, date, league, SOURCE-BUCKET) availability row.

    Rows are keyed per source bucket, so the poll row and the reach-out row are
    independent and never overwrite each other.

    - Poll sync (merge_slots=False): OVERWRITE this bucket's slots with the
      fully-recomputed active-vote set (a removed vote must shrink the set).
    - Reach-out (merge_slots=True):
        * is_available True  -> UNION the offered slots (accumulate partial asks).
        * is_available False + slots -> SUBTRACT only those slots (a "no" to one
          slot must not wipe a prior "yes" to other slots); stays available if any
          slot remains.
        * is_available False + no slots -> blanket decline: clear + unavailable.
    """
    bucket = _bucket(source)
    row = session.query(SubstituteAvailability).filter_by(
        player_id=player_id, match_date=match_date, league_type=league_type,
        source=bucket,
    ).first()

    now = datetime.utcnow()
    slots_in = list(time_slots or [])
    mids_in = list(match_ids or [])

    if row is None:
        # New row. A partial "no" with no existing state = simply unavailable.
        new_slots = slots_in if is_available else []
        new_mids = mids_in if is_available else []
        row = SubstituteAvailability(
            player_id=player_id, match_date=match_date, league_type=league_type,
            season_id=season_id, is_available=bool(is_available),
            time_slots=new_slots, match_ids=new_mids,
            source=bucket, poll_id=poll_id, notes=notes, responded_at=now,
        )
        session.add(row)
        return row

    cur_slots = set(row.time_slots or [])
    cur_mids = set(row.match_ids or [])

    if not merge_slots:
        # Poll authoritative overwrite for this bucket.
        row.time_slots = sorted(set(slots_in))
        row.match_ids = sorted(set(mids_in))
        row.is_available = bool(is_available)
    elif is_available:
        row.time_slots = sorted(cur_slots | set(slots_in))
        row.match_ids = sorted(cur_mids | set(mids_in))
        row.is_available = True
    elif slots_in:
        # Partial decline: remove only the named slots.
        remaining = cur_slots - set(slots_in)
        row.time_slots = sorted(remaining)
        row.match_ids = sorted(cur_mids)  # keep match ids; slot set drives availability
        row.is_available = bool(remaining)
    else:
        # Blanket decline.
        row.time_slots = []
        row.match_ids = []
        row.is_available = False

    if poll_id is not None:
        row.poll_id = poll_id
    if season_id is not None:
        row.season_id = season_id
    if notes:
        row.notes = notes
    row.responded_at = now
    row.updated_at = now
    return row


# ---------------------------------------------------------------------------
# Player stats enrichment (shared by the availability panel AND the pool panel)
# ---------------------------------------------------------------------------

def player_sub_stats(session, player_id, season_id=None):
    """All-time + this-season substitute stats for one player.

    Returns dict: {subbed_this_season, matches_played, requests_received,
    requests_accepted, response_rate}. `response_rate` is the all-time pool
    acceptance rate (requests_accepted / requests_received), the same signal the
    board already surfaces.
    """
    pool = session.query(SubstitutePool).filter_by(player_id=player_id).first()
    matches_played = pool.matches_played if pool else 0
    requests_received = pool.requests_received if pool else 0
    requests_accepted = pool.requests_accepted if pool else 0
    response_rate = round(pool.acceptance_rate, 1) if pool else 0.0

    subbed_this_season = 0
    if season_id:
        subbed_this_season = (
            session.query(SubstituteAssignment)
            .join(SubstituteRequest, SubstituteAssignment.request_id == SubstituteRequest.id)
            .join(Match, SubstituteRequest.match_id == Match.id)
            .filter(
                SubstituteAssignment.player_id == player_id,
                Match.season_id == season_id,
            )
            .count()
        )

    return {
        'subbed_this_season': subbed_this_season,
        'matches_played': matches_played,
        'requests_received': requests_received,
        'requests_accepted': requests_accepted,
        'response_rate': response_rate,
    }


def player_sub_stats_bulk(session, player_ids, season_id=None):
    """Batched player_sub_stats for many players in a FIXED number of queries
    (one for the pool rows, one grouped count for this-season subs) instead of
    2 per player — protects the tight PgBouncer txn budget on hub renders.
    Returns {player_id: stats_dict}."""
    from sqlalchemy import func
    ids = list({int(p) for p in player_ids})
    if not ids:
        return {}
    pools = {
        p.player_id: p for p in
        session.query(SubstitutePool).filter(SubstitutePool.player_id.in_(ids)).all()
    }
    subbed = {}
    if season_id:
        try:
            rows = (
                session.query(SubstituteAssignment.player_id, func.count(SubstituteAssignment.id))
                .join(SubstituteRequest, SubstituteAssignment.request_id == SubstituteRequest.id)
                .join(Match, SubstituteRequest.match_id == Match.id)
                .filter(SubstituteAssignment.player_id.in_(ids), Match.season_id == season_id)
                .group_by(SubstituteAssignment.player_id)
                .all()
            )
            subbed = {pid: cnt for pid, cnt in rows}
        except Exception:
            logger.warning("player_sub_stats_bulk: season-subbed count failed; defaulting to 0",
                           exc_info=True)
            subbed = {}
    out = {}
    for pid in ids:
        pool = pools.get(pid)
        out[pid] = {
            'subbed_this_season': subbed.get(pid, 0),
            'matches_played': pool.matches_played if pool else 0,
            'requests_received': pool.requests_received if pool else 0,
            'requests_accepted': pool.requests_accepted if pool else 0,
            'response_rate': round(pool.acceptance_rate, 1) if pool else 0.0,
            'max_matches_per_week': (pool.max_matches_per_week if pool and pool.max_matches_per_week else None),
        }
    return out


_POS_SPLIT_RE = None


def _pos_tokens(value):
    """Normalize a positions value ('GK, DEF' / ['GK','MID'] / 'goalkeeper') to a
    lowercased token set for soft fit-matching. Never raises."""
    import re
    global _POS_SPLIT_RE
    if _POS_SPLIT_RE is None:
        _POS_SPLIT_RE = re.compile(r'[^a-z0-9]+')
    if not value:
        return set()
    if isinstance(value, (list, tuple, set)):
        text = ' '.join(str(v) for v in value)
    else:
        text = str(value)
    return {t for t in _POS_SPLIT_RE.split(text.lower()) if t}


def _aggregate(session, rows, season_id=None):
    """Merge the (<=2 per player) source-bucket rows into one enriched candidate
    dict per (player, league) — union of AVAILABLE slots/match_ids across poll +
    reach-out, with player image + stats.

    Handles rows of mixed availability (get_week_availability may pass declined
    rows too): `is_available` is True if ANY source says available; declined-only
    players surface with is_available=False and no slots (so the grid can show a
    real 'Declined' state instead of a false 'Available')."""
    grouped = {}
    for r in rows:
        key = (r.player_id, r.league_type)
        g = grouped.setdefault(key, {
            'slots': set(), 'match_ids': set(), 'sources': set(),
            'responded_at': None, 'notes': None, 'available': False,
        })
        # Only an available row contributes slots; a declined row has empty slots.
        if r.is_available:
            g['available'] = True
            g['slots'].update(r.time_slots or [])
            g['match_ids'].update(r.match_ids or [])
        g['sources'].add(r.source)
        if r.responded_at and (g['responded_at'] is None or r.responded_at > g['responded_at']):
            g['responded_at'] = r.responded_at
        if r.notes and not g['notes']:
            g['notes'] = r.notes

    # Batch player + stats lookups (avoid N+1 across candidates on hub renders).
    player_ids = {pid for (pid, _lt) in grouped.keys()}
    stats_map = player_sub_stats_bulk(session, player_ids, season_id)
    players = {}
    if player_ids:
        players = {p.id: p for p in
                   session.query(Player).filter(Player.id.in_(list(player_ids))).all()}

    out = []
    for (player_id, league_type), g in grouped.items():
        player = players.get(player_id)
        stats = stats_map.get(player_id, {})
        pos_tokens = set()
        if player:
            pos_tokens = _pos_tokens(getattr(player, 'favorite_position', None)) \
                | _pos_tokens(getattr(player, 'other_positions', None))
        out.append({
            'player_id': player_id,
            'name': player.name if player else f'Player {player_id}',
            'avatar_url': player.avatar_image_url if player else None,
            'league_type': league_type,
            'preferred_position': getattr(player, 'favorite_position', None) if player else None,
            'positions': sorted(pos_tokens),
            'time_slots': sorted(g['slots']),
            'match_ids': sorted(g['match_ids']),
            'sources': sorted(g['sources']),
            'is_available': g['available'],
            'responded_at': g['responded_at'].isoformat() if g['responded_at'] else None,
            'notes': g['notes'],
            **stats,
        })
    return out


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

def get_week_availability(session, match_date, league_type=None, season_id=None,
                          available_only=True):
    """Enriched available-subs list (one per player/league) for the admin pool panel.

    Ordered so the most useful subs surface first: fewest matches subbed this season
    (spreads the load / keeps balance), then highest response rate.
    """
    q = session.query(SubstituteAvailability).filter(
        SubstituteAvailability.match_date == match_date,
    )
    if available_only:
        q = q.filter(SubstituteAvailability.is_available.is_(True))
    if league_type and league_type in PUB_LEAGUE_TYPES:
        q = q.filter(SubstituteAvailability.league_type == league_type)
    else:
        q = q.filter(SubstituteAvailability.league_type.in_(list(PUB_LEAGUE_TYPES)))

    out = _aggregate(session, q.all(), season_id)
    out.sort(key=lambda d: (d['subbed_this_season'], -d['response_rate']))
    return out


def get_candidates_for_request(session, sub_request, season_id=None):
    """Available subs that match an OPEN SubstituteRequest, for the assign flow.

    A candidate matches when the request's match_id is in the sub's aggregated
    match_ids, OR the sub is available for the league/date via a general reach-out
    that carried no match_ids (so a "can anyone sub?" yes still surfaces). Returns
    enriched dicts with a `conflict` flag when the sub plays/coaches the team.
    """
    if not sub_request or sub_request.league_type not in PUB_LEAGUE_TYPES:
        return []

    match = session.query(Match).filter_by(id=sub_request.match_id).first()
    if not match:
        return []
    match_date = match.date

    rows = session.query(SubstituteAvailability).filter(
        SubstituteAvailability.match_date == match_date,
        SubstituteAvailability.league_type == sub_request.league_type,
        SubstituteAvailability.is_available.is_(True),
    ).all()

    # Conflict: player already rosters/coaches the requesting team.
    conflict_pids = set()
    if sub_request.team_id:
        from app.models import player_teams
        rows_pt = session.execute(
            player_teams.select().where(player_teams.c.team_id == sub_request.team_id)
        ).fetchall()
        conflict_pids = {r.player_id for r in rows_pt}

    needed_pos = _pos_tokens(getattr(sub_request, 'positions_needed', None))

    # Balance mode (Settings): 'soft' (default) = rank but never hide; 'hard' =
    # exclude off-position + at-weekly-cap subs from the list entirely.
    hard = False
    try:
        from app.models.admin_config import AdminConfig
        hard = str(AdminConfig.get_setting('sub_assignment_balance_mode', 'soft')).lower() == 'hard'
    except Exception:
        hard = False

    out = []
    for cand in _aggregate(session, rows, season_id):
        mids = cand.get('match_ids') or []
        # exact slot join, OR a general availability with no match_ids (fallback).
        if sub_request.match_id and mids and sub_request.match_id not in mids:
            continue
        cand['conflict'] = cand['player_id'] in conflict_pids
        #  - position_fit: does the sub play a needed position? (None if no need specified)
        #  - at_weekly_cap: already subbed >= their max this-week preference
        cand_pos = set(cand.get('positions') or [])
        cand['position_fit'] = bool(needed_pos & cand_pos) if needed_pos else None
        cap = cand.get('max_matches_per_week')
        cand['at_weekly_cap'] = bool(cap) and cand.get('subbed_this_season', 0) >= cap
        if hard and (cand['position_fit'] is False or cand['at_weekly_cap']):
            continue  # hard mode: filter out non-fits / over-cap subs
        out.append(cand)
    # Rank: conflict last, best position-fit first, then load-balance (fewest subs),
    # then most reliable. Nothing is hidden — this only orders the list.
    out.sort(key=lambda d: (
        d['conflict'],
        d.get('at_weekly_cap', False),
        d.get('position_fit') is False,   # fits (True/None) float above explicit non-fits
        d['subbed_this_season'],
        -d['response_rate'],
    ))
    return out
