# app/services/league_membership_sync.py

"""
LeagueMembership dual-write (Phase 0).

`resync_player_memberships(session, player_id)` recomputes a single player's
CURRENT-season membership rows from the live source tables (player_teams roster,
substitute_pools / ecs_fc_sub_pool, the pl-* / pl-waitlist roles) and upserts them into
`league_membership`. Every existing write path calls it once, right after its own writes,
so the spine stays fresh as events happen.

⚠️ Event-driven writes ALONE leave the spine structurally incomplete: a player nobody has
edited since the season began has no row at all. Two bulk entry points close that gap, and
both reuse `_do_resync` / the same status rules rather than reimplementing them:
  * `backfill_all_memberships(session)` — sweep every player. Run after a rollover and
    whenever the drift check reports missing rows. Exposed as `flask backfill-league-membership`.
  * `seed_subs_for_season(session, to_season_id, lanes)` — mirror the sub pools into a new
    season's rows at rollover.
Until a backfill has run and the drift check is clean, treat the spine as a display
read-model only, never as an authority for who gets contacted / paid / rostered.

Why a full per-player resync instead of eight bespoke transitions:
  * Idempotent + self-healing — a missed call is corrected by the next event.
  * One code path to review, not eight.
  * Behavior-neutral — the whole thing runs inside a SAVEPOINT (begin_nested),
    so a bug here can never roll back or break the real approval / draft / pick.

Scope: only rows for the CURRENT Pub League + ECS FC seasons are touched. Historical
membership rows (from the backfill) are never modified. ECS FC is pinned in_season
and exempt from the Pub League lifecycle; that does not affect this sync.

Design: ~/.claude/plans/registration-lifecycle-overhaul.md  (Phase 0, §13.4)
"""

import logging
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import (
    LeagueMembership, Season, Team, League, Player, User,
    SubstitutePool, EcsFcSubPool, player_teams,
)

logger = logging.getLogger(__name__)

# league membership Flask roles that mean "approved into this league" (no team required)
_LEAGUE_ROLE_TO_TYPE = {
    'pl-classic': 'classic',
    'pl-premier': 'premier',
    'pl-ecs-fc': 'ecs_fc',
}

# terminal status per role, used to retire a current-season row whose source fact is gone
_TERMINAL = {
    'player': 'inactive',
    'coach': 'inactive',
    'sub': 'retired',
    'waitlist': 'removed',
}

_UPSERT_FIELDS = ('team_id', 'source', 'paid_at', 'activated_at', 'rested_at',
                  'last_engaged_at', 'needs_reconfirm', 'notes')


def _norm_league_type(value):
    """Map any league-ish string ('Classic', 'sub-premier', 'ECS FC', 'ecs-fc') to the canonical lane."""
    if not value:
        return None
    v = str(value).lower()
    if 'classic' in v:
        return 'classic'
    if 'premier' in v:
        return 'premier'
    if 'ecs' in v:
        return 'ecs_fc'
    return None


def _current_season_ids(session):
    """Return {'pub_league': id_or_None, 'ecs_fc': id_or_None} for the current seasons.

    Ordered by id asc so the highest id wins per league_type (last iteration) — matching
    the sub-dispatch read's `order_by(Season.id.desc()).first()`, so read and write agree
    on which season if a duplicate is_current ever exists.
    """
    rows = (session.query(Season.id, Season.league_type)
            .filter(Season.is_current.is_(True))
            .order_by(Season.id.asc()).all())
    out = {'pub_league': None, 'ecs_fc': None}
    for sid, ltype in rows:
        if ltype == 'ECS FC':
            out['ecs_fc'] = sid
        elif ltype == 'Pub League':
            out['pub_league'] = sid
    return out


def _season_for_lane(current, league_type):
    """Which current-season id a lane belongs to (classic/premier -> Pub League, ecs_fc -> ECS FC)."""
    return current['ecs_fc'] if league_type == 'ecs_fc' else current['pub_league']


def _build_desired(session, player, current):
    """Compute the desired current-season membership rows for one player.

    Returns {(season_id, league_type, role): {status, **fields}}.
    """
    desired = {}
    pid = player.id

    # --- 1. Roster (player_teams) -> player/rostered (+ coach/active) ---------
    roster = (
        session.query(player_teams.c.team_id, player_teams.c.is_coach, League.name, League.season_id)
        .join(Team, Team.id == player_teams.c.team_id)
        .join(League, League.id == Team.league_id)
        .filter(player_teams.c.player_id == pid)
        .all()
    )
    rostered_lanes = set()
    for team_id, is_coach, lname, lseason in roster:
        lt = _norm_league_type(lname)
        if not lt or not lseason:
            continue
        rostered_lanes.add((lseason, lt))
        desired[(lseason, lt, 'player')] = {'status': 'rostered', 'team_id': team_id}
        if is_coach:
            desired[(lseason, lt, 'coach')] = {'status': 'active', 'team_id': team_id}

    # --- 2. Approved into a league but not on a team -> player/unrostered -----
    user = player.user if player.user_id else None
    role_names = {r.name for r in user.roles} if user else set()
    if user and user.is_approved:
        for role_name, lt in _LEAGUE_ROLE_TO_TYPE.items():
            if role_name not in role_names:
                continue
            sid = _season_for_lane(current, lt)
            if sid and (sid, lt, 'player') not in desired:
                desired[(sid, lt, 'player')] = {'status': 'unrostered', 'team_id': None}

    # --- 3. Substitute pools -> sub/{active,resting,pending} ------------------
    for sp in session.query(SubstitutePool).filter(SubstitutePool.player_id == pid).all():
        lt = _norm_league_type(sp.league_type)
        sid = _season_for_lane(current, lt) if lt else None
        if not sid:
            continue
        if sp.is_active and sp.approved_at is not None:
            status = 'active'
        elif sp.approved_at is not None:
            status = 'resting'
        else:
            status = 'pending'
        desired[(sid, lt, 'sub')] = {
            'status': status,
            'activated_at': sp.approved_at,
            'last_engaged_at': sp.last_active_at,
        }

    for ep in session.query(EcsFcSubPool).filter(EcsFcSubPool.player_id == pid).all():
        sid = current['ecs_fc']
        if sid and (sid, 'ecs_fc', 'sub') not in desired:
            desired[(sid, 'ecs_fc', 'sub')] = {
                'status': 'active' if ep.is_active else 'resting',
                'last_engaged_at': ep.last_active_at,
            }

    # --- 4. Waitlist (pl-waitlist role + waitlist_league lane) -> waitlist/waiting
    if user and 'pl-waitlist' in role_names:
        lt = _norm_league_type(getattr(user, 'waitlist_league', None))
        sid = _season_for_lane(current, lt) if lt else None
        if sid and (sid, lt, 'waitlist') not in desired:
            desired[(sid, lt, 'waitlist')] = {'status': 'waiting'}

    return desired


def _upsert(session, player_id, season_id, league_type, role, values):
    now = datetime.utcnow()
    insert_vals = {
        'player_id': player_id, 'season_id': season_id, 'league_type': league_type,
        'role': role, 'status': values['status'], 'created_at': now, 'updated_at': now,
    }
    set_vals = {'status': values['status'], 'updated_at': now}
    for f in _UPSERT_FIELDS:
        if f in values:
            insert_vals[f] = values[f]
            set_vals[f] = values[f]
    if 'source' not in insert_vals:
        insert_vals['source'] = 'admin'
    stmt = pg_insert(LeagueMembership.__table__).values(**insert_vals).on_conflict_do_update(
        index_elements=['player_id', 'season_id', 'league_type', 'role'],
        set_=set_vals,
    )
    session.execute(stmt)


def _do_resync(session, player):
    current = _current_season_ids(session)
    current_ids = [sid for sid in (current['pub_league'], current['ecs_fc']) if sid]
    if not current_ids:
        return

    desired = _build_desired(session, player, current)
    desired_keys = set(desired.keys())

    # retire current-season rows whose source fact disappeared
    existing = (
        session.query(LeagueMembership)
        .filter(LeagueMembership.player_id == player.id,
                LeagueMembership.season_id.in_(current_ids))
        .all()
    )
    for row in existing:
        key = (row.season_id, row.league_type, row.role)
        if key not in desired_keys:
            terminal = _TERMINAL.get(row.role)
            if terminal and row.status != terminal:
                row.status = terminal
                row.updated_at = datetime.utcnow()

    for (sid, lt, role), values in desired.items():
        _upsert(session, player.id, sid, lt, role, values)


def seed_subs_for_season(session, to_season_id, lanes=None):
    """Season rollover: create the new season's sub rows by MIRRORING the sub pools.

    Sub pool membership is NOT season-scoped — `substitute_pools` / `ecs_fc_sub_pool`
    carry across the boundary untouched, and the pool row's own state is the authority
    for availability (active vs resting). league_membership IS season-scoped, so the new
    season starts with no sub rows at all; this reflects the pools into it.

    Replaces the old `carry_forward_subs`, which copied last season's rows in as
    `resting` + needs_reconfirm=True to force a per-season re-opt-in. That contradicted
    the pool-is-authority model two ways: it made the spine disagree with the pool row it
    is supposed to mirror, and the disagreement didn't even hold — `_upsert` recomputes
    status from the pool and never reads needs_reconfirm, so any later write to that
    player silently flipped `resting` back to `active`. Resting is now driven only by the
    pool row (admin rests them / they stop responding / they opt out), never by the
    calendar.

    `lanes` optionally restricts to a subset of ('classic', 'premier', 'ecs_fc') — the Pub
    League rollover passes its two lanes so it can't touch ECS FC rows, and vice versa.
    Idempotent: re-running updates status in place. Returns the number of rows written.
    """
    if not to_season_id:
        return 0
    now = datetime.utcnow()
    seeded = 0

    def _write(player_id, lane, status, activated_at=None, last_engaged_at=None):
        nonlocal seeded
        if lanes and lane not in lanes:
            return
        stmt = pg_insert(LeagueMembership.__table__).values(
            player_id=player_id, season_id=to_season_id, league_type=lane,
            role='sub', status=status, source='backfill', needs_reconfirm=False,
            activated_at=activated_at, last_engaged_at=last_engaged_at,
            created_at=now, updated_at=now,
        ).on_conflict_do_update(
            index_elements=['player_id', 'season_id', 'league_type', 'role'],
            set_={'status': status, 'updated_at': now},
        )
        session.execute(stmt)
        seeded += 1

    for sp in session.query(SubstitutePool).all():
        lane = _norm_league_type(sp.league_type)
        if not lane:
            continue
        if sp.is_active and sp.approved_at is not None:
            status = 'active'
        elif sp.approved_at is not None:
            status = 'resting'
        else:
            status = 'pending'
        _write(sp.player_id, lane, status,
               activated_at=sp.approved_at, last_engaged_at=sp.last_active_at)

    # EcsFcSubPool has no approval concept — is_active is the only gate.
    for ep in session.query(EcsFcSubPool).all():
        _write(ep.player_id, 'ecs_fc', 'active' if ep.is_active else 'resting',
               last_engaged_at=getattr(ep, 'last_active_at', None))

    logger.info("seed_subs_for_season: %s sub row(s) mirrored from the pools into season %s "
                "(lanes=%s)", seeded, to_season_id, lanes or 'all')
    return seeded


def backfill_all_memberships(session, batch_size=200, dry_run=False, progress=None):
    """Recompute current-season league_membership rows for EVERY player.

    WHY THIS EXISTS: the spine is otherwise written only by per-player
    `resync_player_memberships` calls hanging off write paths (approvals, pool edits,
    draft, bulk ops). A player nobody has edited since the season began therefore has NO
    row at all — not a stale row, no row. That made the spine structurally incomplete and
    unusable as an authority for anything operational. This sweep closes that gap; run it
    after any season rollover and any time the drift check reports missing rows.

    Uses `_do_resync` — the SAME function the per-player dual-write uses — rather than a
    parallel SQL reimplementation, so there is exactly one definition of desired state and
    nothing to drift against.

    Commits every `batch_size` players. That is deliberate: transaction HOLD TIME is the
    scarce resource against PgBouncer (small pool, 1 vCPU), and one transaction spanning
    thousands of players would pin a server-side connection for the whole run. Each batch
    is independently committed, so an interrupted run leaves consistent partial progress
    and is safe to simply re-run (the whole operation is idempotent).

    Returns {'players': int, 'batches': int, 'errors': int}. `progress` is an optional
    callable(done, total) for CLI output.
    """
    current = _current_season_ids(session)
    if not any(current.values()):
        logger.warning("backfill_all_memberships: no current season for either program; nothing to do")
        return {'players': 0, 'batches': 0, 'errors': 0}

    player_ids = [pid for (pid,) in session.query(Player.id).order_by(Player.id).all()]
    total = len(player_ids)
    stats = {'players': 0, 'batches': 0, 'errors': 0}

    for start in range(0, total, batch_size):
        chunk = player_ids[start:start + batch_size]
        # One query per batch, not one per player.
        players = session.query(Player).filter(Player.id.in_(chunk)).all()
        for player in players:
            try:
                # SAVEPOINT per player: one bad row rolls back only itself, so the rest
                # of the batch still commits and the sweep never loses good work.
                with session.begin_nested():
                    _do_resync(session, player)
                stats['players'] += 1
            except Exception:
                stats['errors'] += 1
                logger.exception("backfill_all_memberships: resync failed for player_id=%s", player.id)
        if dry_run:
            session.rollback()
        else:
            session.commit()
        stats['batches'] += 1
        if progress:
            progress(min(start + batch_size, total), total)

    logger.info("backfill_all_memberships: %s player(s) across %s batch(es), %s error(s)%s",
                stats['players'], stats['batches'], stats['errors'],
                ' [DRY RUN, rolled back]' if dry_run else '')
    return stats


def resync_player_memberships(session, player_id):
    """Best-effort dual-write: recompute one player's current-season league_membership rows.

    Call AFTER the caller's own writes, using the caller's session. Never raises —
    a failure is logged and isolated to a SAVEPOINT so the surrounding operation is
    unaffected. Phase 0 only; harmless once reads cut over.
    """
    if not player_id:
        return
    try:
        # materialize the caller's pending writes so the resync reads current state,
        # then isolate the resync itself in a savepoint.
        session.flush()
        player = session.query(Player).get(player_id)
        if player is None:
            return
        with session.begin_nested():
            _do_resync(session, player)
    except Exception:
        logger.exception("[dual-write] league_membership resync failed (non-fatal) for player_id=%s", player_id)
