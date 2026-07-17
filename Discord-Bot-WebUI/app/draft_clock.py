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
  linear -> slot index = idx
  snake  -> even rounds reverse: idx = n-1-idx
"""

import logging
from datetime import datetime, timedelta

from app.core import db, socketio
from app.models import DraftSession, DraftPickSlot, Team

logger = logging.getLogger(__name__)


def get_session(session, season_id, league_id):
    """Return the DraftSession for this (season, league), or None."""
    if not season_id or not league_id:
        return None
    return session.query(DraftSession).filter_by(
        season_id=season_id, league_id=league_id
    ).first()


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


def advance(session, ds):
    """Advance the clock by one pick. Caller commits. Returns updated state dict."""
    team_ids = ordered_team_ids(session, ds)
    set_clock_to(ds, (ds.current_overall_pick or 0) + 1, team_ids)
    return build_state(session, ds, team_ids=team_ids)


def step_back(session, ds):
    """Move the clock BACK one pick (admin correction, the inverse of skip/advance).

    Caller commits. Returns updated state dict. Never goes before pick #1. If the draft
    had completed, this re-activates it and lands on the final pick. Note: this only moves
    the clock — it does not un-draft a player (use the roster Remove control for that)."""
    team_ids = ordered_team_ids(session, ds)
    total = total_picks(ds, team_ids)
    if ds.status == 'complete':
        target = total or 1
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


def alert_team_coaches(session, ds, escalation):
    """Hyper-alert the on-the-clock team's coach(es) via Discord DM. Returns count DM'd.

    `escalation` (int, 1-based) drives the urgency of the message copy. Best-effort:
    never raises (a failed alert must not stall the draft)."""
    import os
    import requests
    coaches = get_team_coaches(session, ds.current_team_id)
    team = session.query(Team).filter(Team.id == ds.current_team_id).first()
    team_name = team.name if team else 'your team'
    if escalation <= 1:
        msg = (f"You're on the clock in the {team_name} draft. Make your pick when you get a sec — "
               f"the board's waiting on you.")
    elif escalation == 2:
        msg = (f"Still your pick in the {team_name} draft — clock's run out. Jump in and grab someone.")
    else:
        msg = (f"Heads up — the {team_name} draft is held up on your pick (reminder #{escalation}). "
               f"Please make a selection so we can keep moving.")
    bot_api_url = os.getenv('BOT_API_URL', 'http://discord-bot:5001')
    sent = 0
    for c in coaches:
        if not c.get('discord_id'):
            continue
        try:
            requests.post(f"{bot_api_url}/send_discord_dm",
                          json={'discord_id': c['discord_id'], 'message': msg}, timeout=5)
            sent += 1
        except Exception as e:
            logger.warning(f"draft coach alert DM failed for {c['discord_id']}: {e}")
    return sent


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
