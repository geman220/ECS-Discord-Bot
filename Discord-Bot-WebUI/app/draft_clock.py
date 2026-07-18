# app/draft_clock.py

"""
Draft "On the Clock" engine.

Turn-based draft layered ADDITIVELY on top of the existing free-form draft
(app/sockets/draft.py). When a DraftSession row exists and is 'active' for a
(season, league):
  - picks may be locked to the team currently on the clock, and
  - the clock advances (snake or linear) after each successful pick.

When no DraftSession exists, callers should treat the draft as free-form (the
historical behaviour) — every helper here is a no-op / returns None in that case.

Pick-order math (1-based overall_pick):
  n = number of teams, round = (overall_pick-1)//n + 1, idx = (overall_pick-1)%n
  linear   -> slot index = idx
  snake    -> even rounds reverse: idx = n-1-idx
  rotating -> snake, but the anchor rotates one seat every TWO rounds. Rounds pair
              up (1&2, 3&4, ...); within a pair it snakes (forward then reversed),
              and each successive pair rotates the base order left by one, so the
              team that opened rounds 1-2 opens later and later. For base seats
              [E,F,G,H,I,J,K,L]:
                R1 E F G H I J K L    R2 L K J I H G F E
                R3 F G H I J K L E    R4 E L K J I H G F
                R5 G H I J K L E F    R6 F E L K J I H G  ...
              (This is the "reverse each round, shift the start every 2 rounds"
              scheme some pub-league drafts use for maximal seat fairness.)
"""

import logging
from datetime import datetime, timedelta

from app.core import db, socketio
from app.models import DraftSession, DraftPickSlot, Team

logger = logging.getLogger(__name__)


def get_session(session, season_id, league_id, for_update=False):
    """Return the DraftSession for this (season, league), or None.

    for_update=True issues SELECT ... FOR UPDATE so the caller holds a row lock on
    the draft session for the rest of its transaction. This is the concurrency
    primitive that makes a pick atomic: two picks racing for the same on-the-clock
    team serialize on this lock, so only the first writes + advances and the second
    sees the clock already moved (see check_turn). Works across web and mobile
    because both hit the same DB row."""
    if not season_id or not league_id:
        return None
    q = session.query(DraftSession).filter_by(
        season_id=season_id, league_id=league_id
    )
    if for_update:
        q = q.with_for_update()
    return q.first()


def check_turn(ds, team_id, is_admin, expected_pick=None):
    """Authoritative on-the-clock turn check. MUST be called while holding the
    FOR UPDATE lock on `ds` (get_session(..., for_update=True)) so the claim is
    atomic against concurrent picks — that is what prevents a double-draft.

    Returns (ok: bool, code: str):
      'ok'          -> allowed: on the clock, admin override, or free-form/paused
      'out_of_turn' -> lock_to_clock on, a different team is on the clock, not admin
      'stale'       -> expected_pick given but the board already moved on, not admin

    No enforcement when there is no active session (free-form) or the draft is
    paused/complete — that preserves the legacy any-player-any-team behaviour."""
    if ds is None or ds.status != 'active':
        return True, 'ok'
    if (ds.lock_to_clock and ds.current_team_id and ds.current_team_id != team_id
            and not is_admin):
        return False, 'out_of_turn'
    if (expected_pick is not None and not is_admin
            and ds.current_overall_pick is not None
            and int(expected_pick) != ds.current_overall_pick):
        return False, 'stale'
    return True, 'ok'


def ordered_team_ids(session, ds):
    """Round-1 team order as a list of team ids."""
    rows = session.query(DraftPickSlot).filter_by(
        draft_session_id=ds.id
    ).order_by(DraftPickSlot.slot).all()
    return [r.team_id for r in rows]


def total_picks(ds, team_ids):
    return len(team_ids) * (ds.rounds or 0)


def team_on_clock(team_ids, fmt, overall_pick):
    """Return (team_id, round_no, pick_in_round) for a 1-based overall pick."""
    n = len(team_ids)
    if n == 0 or overall_pick is None or overall_pick < 1:
        return None, None, None
    rnd = (overall_pick - 1) // n + 1
    idx = (overall_pick - 1) % n
    if fmt == 'rotating':
        # Snake within each 2-round pair, then rotate the anchor left by one per pair.
        shift = (rnd - 1) // 2            # pairs 1&2 -> 0, 3&4 -> 1, 5&6 -> 2, ...
        if rnd % 2 == 0:                  # second round of the pair reverses
            idx = n - 1 - idx
        slot = (idx + shift) % n
        return team_ids[slot], rnd, slot + 1
    if fmt == 'snake' and rnd % 2 == 0:
        idx = n - 1 - idx
    return team_ids[idx], rnd, idx + 1


def up_next_team_ids(team_ids, fmt, overall_pick, count=3):
    out = []
    for k in range(1, count + 1):
        tid, _, _ = team_on_clock(team_ids, fmt, (overall_pick or 0) + k)
        if tid is None:
            break
        out.append(tid)
    return out


def set_clock_to(ds, overall_pick, team_ids):
    """Mutate ds to put `overall_pick` on the clock. Caller commits.

    Returns True if the draft is now complete (clock cleared), else False.
    """
    if overall_pick > total_picks(ds, team_ids):
        ds.status = 'complete'
        ds.current_overall_pick = overall_pick
        ds.current_round = None
        ds.current_team_id = None
        ds.pick_deadline = None
        ds.completed_at = datetime.utcnow()
        return True
    tid, rnd, _ = team_on_clock(team_ids, ds.format, overall_pick)
    ds.current_overall_pick = overall_pick
    ds.current_round = rnd
    ds.current_team_id = tid
    ds.alerts_sent = 0  # fresh pick -> reset escalation counter
    ds.pick_deadline = (
        datetime.utcnow() + timedelta(seconds=ds.seconds_per_pick)
    ) if ds.seconds_per_pick else None
    return False


def get_team_coaches(session, team_id):
    """Coaches of a team (contextual awareness for alerts): [{player_id, name, discord_id}]."""
    if not team_id:
        return []
    from app.models.players import player_teams
    from app.models import Player
    rows = session.query(Player).join(
        player_teams, player_teams.c.player_id == Player.id
    ).filter(
        player_teams.c.team_id == team_id,
        player_teams.c.is_coach == True  # noqa: E712
    ).all()
    return [{'player_id': p.id, 'name': p.name, 'discord_id': p.discord_id} for p in rows]


def advance(session, ds, with_state=True):
    """Advance the clock by one pick. Caller commits. Returns updated state dict.

    with_state=False mutates the clock columns but skips building the emit payload,
    so a caller holding a FOR UPDATE lock can advance and release the lock, then
    build_state() afterwards OUTSIDE the lock (build_state issues ~5 read queries
    that don't need to run under the lock). Returns None when with_state=False."""
    team_ids = ordered_team_ids(session, ds)
    set_clock_to(ds, (ds.current_overall_pick or 0) + 1, team_ids)
    return build_state(session, ds, team_ids=team_ids) if with_state else None


def step_back(session, ds):
    """Move the clock BACK one pick (admin correction, the inverse of skip/advance).

    Caller commits. Returns updated state dict. Never goes before pick #1. If the draft
    had completed, this re-activates it and lands on the final pick. Note: this only moves
    the clock — it does not un-draft a player (use the roster Remove control for that)."""
    team_ids = ordered_team_ids(session, ds)
    total = total_picks(ds, team_ids)
    if ds.status == 'complete':
        # Completed normally => current_overall_pick ran to total+1, land on the last real pick.
        # Ended early by an admin at pick N => current_overall_pick == N, resume there.
        cur = ds.current_overall_pick or (total + 1)
        target = min(cur, total) if total else 1
        ds.completed_at = None
    else:
        target = (ds.current_overall_pick or 1) - 1
    if target < 1:
        target = 1
    set_clock_to(ds, target, team_ids)
    ds.status = 'active'  # regaining the clock after a back-step
    return build_state(session, ds, team_ids=team_ids)


def complete(session, ds):
    """End the draft immediately (admin 'stop'). Caller commits. Returns state dict."""
    ds.status = 'complete'
    ds.current_team_id = None
    ds.current_round = None
    ds.pick_deadline = None
    ds.pause_remaining_seconds = None
    ds.completed_at = datetime.utcnow()
    return build_state(session, ds)


def _abbrev(name):
    if not name:
        return '?'
    parts = [p for p in name.replace('.', ' ').split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def build_state(session, ds, team_ids=None):
    """Serialise the live clock for the on-the-clock bar / state endpoint / socket emit."""
    if team_ids is None:
        team_ids = ordered_team_ids(session, ds)
    total = total_picks(ds, team_ids)

    def team_brief(tid, with_coaches=False):
        if not tid:
            return None
        t = session.query(Team).filter(Team.id == tid).first()
        if not t:
            return None
        b = {'id': t.id, 'name': t.name, 'abbrev': _abbrev(t.name)}
        if with_coaches:
            coaches = get_team_coaches(session, tid)
            b['coaches'] = [{'name': c['name']} for c in coaches]  # names only in the state payload
        return b

    overdue = bool(ds.status == 'active' and ds.pick_deadline and ds.pick_deadline < datetime.utcnow())

    return {
        'session_id': ds.id,
        'status': ds.status,
        'format': ds.format,
        'seconds_per_pick': ds.seconds_per_pick,
        'lock_to_clock': ds.lock_to_clock,
        'timeout_action': ds.timeout_action,
        'rounds': ds.rounds,
        'min_new_players': getattr(ds, 'min_new_players', 0) or 0,
        'min_admins': getattr(ds, 'min_admins', 0) or 0,
        'overall_pick': ds.current_overall_pick,
        'total_picks': total,
        'round': ds.current_round,
        'current_team': team_brief(ds.current_team_id, with_coaches=True),
        'pick_deadline': ds.pick_deadline.isoformat() + 'Z' if ds.pick_deadline else None,
        'overdue': overdue,
        'alerts_sent': ds.alerts_sent or 0,
        'up_next': [team_brief(tid) for tid in up_next_team_ids(team_ids, ds.format, ds.current_overall_pick or 0)],
        'progress_pct': round(100.0 * ((ds.current_overall_pick or 1) - 1) / total, 1) if total else 0,
    }


def _alert_message(team_name, escalation):
    """Escalation copy for the on-the-clock coach DM (human tone, no AI vibe)."""
    if escalation <= 1:
        return (f"You're on the clock in the {team_name} draft. Make your pick when you get a sec — "
                f"the board's waiting on you.")
    if escalation == 2:
        return (f"Still your pick in the {team_name} draft — clock's run out. Jump in and grab someone.")
    return (f"Heads up — the {team_name} draft is held up on your pick (reminder #{escalation}). "
            f"Please make a selection so we can keep moving.")


def resolve_coach_alert(session, ds, escalation):
    """READ-ONLY: gather the on-the-clock coaches' discord_ids + the escalation
    message. Call this INSIDE the DB transaction, commit, THEN hand the result to
    dispatch_coach_dms() OUTSIDE the transaction. Splitting it this way is what
    keeps the bot HTTP call from holding a pgbouncer slot open (the 1-vCPU DB has
    a tiny transaction budget — never do HTTP inside an open txn). Returns
    (discord_ids: list[str], message: str)."""
    coaches = get_team_coaches(session, ds.current_team_id)
    team = session.query(Team).filter(Team.id == ds.current_team_id).first()
    team_name = team.name if team else 'your team'
    discord_ids = [c['discord_id'] for c in coaches if c.get('discord_id')]
    return discord_ids, _alert_message(team_name, escalation)


def dispatch_coach_dms(discord_ids, message):
    """Send the coach alert DMs. Pure HTTP — NO DB session, so it is safe to call
    after the transaction has committed. Best-effort: never raises. Returns count
    sent. Tuple timeout is (connect, read) so a black-holing bot can't exceed it."""
    import os
    import requests
    bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
    sent = 0
    for did in discord_ids:
        try:
            requests.post(f"{bot_api_url}/send_discord_dm",
                          json={'discord_id': did, 'message': message}, timeout=(3, 5))
            sent += 1
        except Exception as e:
            logger.warning(f"draft coach alert DM failed for {did}: {e}")
    return sent


def alert_team_coaches(session, ds, escalation):
    """Back-compat convenience: resolve targets + dispatch in one call. Prefer the
    resolve_coach_alert()/dispatch_coach_dms() split in transactional contexts so
    the HTTP runs strictly after commit."""
    discord_ids, message = resolve_coach_alert(session, ds, escalation)
    return dispatch_coach_dms(discord_ids, message)


def queue_on_clock_push(ds):
    """Enqueue the 'you're on the clock' push for the team `ds` now points at.

    Best-effort, fire-and-forget; call after any real clock transition (a pick
    advancing the clock, a skip, the draft starting). No-op unless the draft is
    active with a team on the clock. The Celery task resolves the team's coaches
    and pushes to all of them, so the HTTP send never touches the pick txn."""
    try:
        if not ds or ds.status != 'active' or not ds.current_team_id:
            return
        from app.tasks.tasks_push_notifications import send_on_the_clock_push
        send_on_the_clock_push.delay(
            team_id=ds.current_team_id,
            round_no=ds.current_round,
            overall_pick=ds.current_overall_pick,
            seconds_per_pick=ds.seconds_per_pick or None,
        )
    except Exception as e:  # never let a push enqueue break the draft
        logger.warning(f"queue_on_clock_push failed: {e}")


def emit_clock(league_name, state):
    """Broadcast the clock state to the draft room(s). The board joins
    `draft_<getLeagueName()>`, whose casing may differ from League.name — emit to
    both the exact and lower-cased room so route/task updates always land."""
    if not league_name:
        return
    rooms = {f'draft_{league_name}', f'draft_{str(league_name).lower()}'}
    for room in rooms:
        try:
            socketio.emit('draft_clock_update', state, room=room)
        except Exception as e:  # never let an emit failure break a pick
            logger.warning(f"draft_clock_update emit failed ({room}): {e}")
