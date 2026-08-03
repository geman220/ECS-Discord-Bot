# app/services/match_schedule_service.py

"""
Match Schedule Service — reschedule a fixture, or call it off.

Two writes that the admin panel half-had:

* ``update_schedule`` — a PARTIAL edit of date / time / location / notes. The
  panel's ``update-match-time`` only ever moved date+time, and only on the one
  Schedule row the Match points at.
* ``set_schedule_status`` — postpone or cancel. The panel's "Postpone match"
  button was a JS stub that popped an alert and wrote nothing, so a rained-off
  fixture stayed on every member's schedule looking perfectly normal.

⚠️ MIRROR PAIR. A Pub League fixture is TWO ``Schedule`` rows (one per team's
perspective, ``team_id``/``opponent`` swapped) and normally ONE ``Match``. Moving
a match without moving both Schedule rows leaves the away team's schedule page
showing the old kickoff — which is exactly the failure that gets someone driving
to an empty pitch. Everything here resolves the pair. Some legacy fixtures also
carry a second Match on the mirror Schedule; that is handled too.

⚠️ ``sql_match_postponement.sql`` must have run — see Match.schedule_status.

Returns ``(payload, http_status)``; the caller only jsonifies.
"""

import logging
from datetime import datetime

from app.core import db

logger = logging.getLogger(__name__)


def _ok(message, **extra):
    payload = {'success': True, 'message': message}
    payload.update(extra)
    return payload, 200


def _err(message, status=400, **extra):
    payload = {'success': False, 'message': message}
    payload.update(extra)
    return payload, status


def _parse_date(value):
    """'YYYY-MM-DD' -> date. Raises ValueError with a usable message."""
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValueError(f"date must be YYYY-MM-DD, got {value!r}")


def _parse_time(value):
    """'HH:MM:SS' (or 'HH:MM') -> time.

    The mobile client always sends ``HH:MM:SS`` — the format every other match
    payload uses — but the web panel posts ``HH:MM``, so both are accepted
    rather than making one caller wrong.
    """
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(value, fmt).time()
        except (TypeError, ValueError):
            continue
    raise ValueError(f"time must be HH:MM:SS, got {value!r}")


def _schedule_pair(session, match):
    """Every Schedule row for this fixture — the match's own and its mirror.

    The mirror is found by the ORIGINAL (team_id, opponent, week) triple with
    the teams swapped, which is how the pair was created (see `flask` seeding in
    app/cli.py and ScheduleManager.update_match).
    """
    from app.models import Schedule

    if not match.schedule_id:
        return []
    own = session.query(Schedule).get(match.schedule_id)
    if own is None:
        return []
    rows = [own]
    q = (session.query(Schedule)
         .filter(Schedule.team_id == own.opponent,
                 Schedule.opponent == own.team_id,
                 Schedule.week == own.week,
                 Schedule.id != own.id))
    # Narrow to the same season WHEN WE KNOW IT. `season_id` is nullable and
    # legacy rows have it NULL, and `NULL == NULL` is NULL in SQL — filtering
    # unconditionally would silently find no mirror for exactly those rows and
    # leave the away team on the old kickoff with no error. Only add the
    # predicate when it can actually match.
    if own.season_id is not None:
        q = q.filter(Schedule.season_id == own.season_id)
    mirror = q.first()
    if mirror is not None:
        rows.append(mirror)
    return rows


def _sibling_matches(session, match):
    """Legacy fixtures can carry a second Match hung off the mirror Schedule."""
    from app.models import Match

    out = []
    for sched in _schedule_pair(session, match):
        if sched.id == match.schedule_id:
            continue
        sibling = session.query(Match).filter_by(schedule_id=sched.id).first()
        if sibling is not None and sibling.id != match.id:
            out.append(sibling)
    return out


def update_schedule(session, match_id, actor_id, date=None, time=None,
                    location=None, notes=None):
    """Partially edit a fixture. OMITTED FIELDS ARE LEFT ALONE.

    That is the whole contract: the client sends only what changed, so
    ``None`` here means "not supplied", never "clear it". Nothing in this
    function may coerce a missing field into a default — a stray
    ``location=''`` would blank a venue nobody asked to blank.

    ``notes`` is the one field where an explicit empty string IS meaningful
    (clearing a note), so it is distinguished from absent by the caller passing
    ``None`` vs ``''``.

    Stamps ``rescheduled_at`` only when the date or time actually MOVED, because
    that timestamp is what makes mobile warn coaches their submitted report may
    now be orphaned — stamping it on a notes edit would cry wolf.
    """
    from app.models import Match

    match = session.query(Match).get(match_id)
    if match is None:
        # Carries a message: a bodyless 404 reads to the mobile client as
        # "endpoint not deployed" and hides the whole edit sheet.
        return _err('Match not found', 404)

    try:
        new_date = _parse_date(date) if date is not None else None
        new_time = _parse_time(time) if time is not None else None
    except ValueError as exc:
        return _err(str(exc))

    if notes is not None and not isinstance(notes, str):
        # A JSON body can carry a list/dict/number where text belongs. Assigning
        # one to a Text column blows up at COMMIT — long after this function has
        # returned 200 — so reject it here as the client bug it is.
        return _err('notes must be text')

    if location is not None:
        location = str(location).strip()
        if not location:
            # The client never sends this — clearing a venue is a desktop
            # action — so an empty string is a client bug, and silently blanking
            # a NOT NULL column would be the worst possible reading of it.
            return _err('location cannot be empty; omit the field to leave it unchanged')

    old_date, old_time = match.date, match.time
    changed = []

    if new_date is not None and new_date != match.date:
        match.date = new_date
        changed.append('date')
    if new_time is not None and new_time != match.time:
        match.time = new_time
        changed.append('time')
    if location is not None and location != match.location:
        match.location = location
        changed.append('location')
    if notes is not None and notes != match.notes:
        match.notes = notes
        changed.append('notes')

    if not changed:
        # Not an error — a no-op edit is a legitimate thing for a client to
        # send, and reporting it as failure makes the app show a red toast for
        # someone who simply didn't change anything.
        return _ok('Nothing changed', match_id=match.id, changed=[],
                   match=match.to_dict())

    moved = ('date' in changed) or ('time' in changed)
    if moved:
        match.rescheduled_at = datetime.utcnow()

    # Mirror pair — both Schedule rows and any legacy sibling Match.
    for sched in _schedule_pair(session, match):
        if new_date is not None:
            sched.date = match.date
        if new_time is not None:
            sched.time = match.time
        if location is not None:
            sched.location = match.location
    for sibling in _sibling_matches(session, match):
        if new_date is not None:
            sibling.date = match.date
        if new_time is not None:
            sibling.time = match.time
        if location is not None:
            sibling.location = match.location
        if moved:
            sibling.rescheduled_at = match.rescheduled_at

    _audit(actor_id, 'update_match_schedule', match.id,
           old_value=f'{old_date} {old_time}',
           new_value=f'{match.date} {match.time} | {", ".join(changed)}')

    session.flush()

    if moved:
        _emit_rescheduled(match, actor_id)

    logger.info("Admin %s edited match %s schedule: %s", actor_id, match.id, changed)
    return _ok('Schedule updated', match_id=match.id, changed=changed,
               match=match.to_dict())


def set_schedule_status(session, match_id, actor_id, reason='', cancelled=False):
    """Postpone (``cancelled=False``) or cancel (``cancelled=True``) a fixture.

    These are NOT the same thing and must not be collapsed:

      postponed -> called off, a new date is coming. The fixture still owes both
                   teams a game.
      cancelled -> called off for good. It is never being played.

    ``reason`` is shown verbatim to members, so it is required — "cancelled"
    with no explanation is the state people email about.

    Passing the SAME status again is an idempotent success (it refreshes the
    reason), so a client retry can't turn into an error dialog.
    """
    from app.models import Match

    match = session.query(Match).get(match_id)
    if match is None:
        return _err('Match not found', 404)

    reason = (reason or '').strip() if isinstance(reason, str) else ''
    if not reason:
        return _err('reason is required — members are shown it verbatim')

    status = 'cancelled' if cancelled else 'postponed'
    was = match.schedule_status

    match.schedule_status = status
    match.schedule_status_reason = reason
    match.schedule_status_at = datetime.utcnow()
    match.schedule_status_by_user_id = actor_id

    # The mirror's Match (legacy fixtures only) has to agree, or one team sees
    # the fixture called off and the other doesn't.
    for sibling in _sibling_matches(session, match):
        sibling.schedule_status = status
        sibling.schedule_status_reason = reason
        sibling.schedule_status_at = match.schedule_status_at
        sibling.schedule_status_by_user_id = actor_id

    _audit(actor_id, 'set_match_schedule_status', match.id,
           old_value=was or 'scheduled', new_value=f'{status}: {reason}')

    session.flush()

    logger.info("Admin %s marked match %s %s: %s", actor_id, match.id, status, reason)
    return _ok(
        (f'Match was already {status} — reason updated' if was == status
         else f'Match {status}'),
        match_id=match.id, schedule_status=status,
        schedule_status_reason=reason,
        already=(was == status),
        match=match.to_dict())


def clear_schedule_status(session, match_id, actor_id):
    """Put a called-off fixture back on. Returns it to a normal match."""
    from app.models import Match

    match = session.query(Match).get(match_id)
    if match is None:
        return _err('Match not found', 404)
    if not match.schedule_status:
        return _ok('Match was not called off', match_id=match.id,
                   schedule_status=None, match=match.to_dict())

    was = match.schedule_status
    for m in [match] + _sibling_matches(session, match):
        m.schedule_status = None
        m.schedule_status_reason = None
        m.schedule_status_at = None
        m.schedule_status_by_user_id = None

    _audit(actor_id, 'clear_match_schedule_status', match.id,
           old_value=was, new_value='scheduled')
    session.flush()

    logger.info("Admin %s restored match %s (was %s)", actor_id, match.id, was)
    return _ok('Match is back on', match_id=match.id, schedule_status=None,
               match=match.to_dict())


# ---------------------------------------------------------------------------
# side effects
# ---------------------------------------------------------------------------

def _audit(actor_id, action, match_id, old_value=None, new_value=None):
    """Audit without letting a logging failure undo the edit."""
    try:
        from flask import request, has_request_context
        from app.models.admin_config import AdminAuditLog
        ip = request.remote_addr if has_request_context() else None
        ua = request.headers.get('User-Agent') if has_request_context() else None
        AdminAuditLog.log_action(
            user_id=actor_id, action=action, resource_type='match',
            resource_id=str(match_id), old_value=old_value, new_value=new_value,
            ip_address=ip, user_agent=ua)
    except Exception as exc:
        logger.warning(f"audit log skipped for {action} on match {match_id}: {exc}")


def _emit_rescheduled(match, actor_id):
    """Tell any open /live room the match moved, so coaches see the warning that
    a submitted report may now be orphaned. Best-effort — only fires if a room
    actually exists, and never takes the edit down with it."""
    try:
        from app.services.live_reporting import redis_state
        if redis_state.load_state('pub', int(match.id)) is None:
            return
        from app.core import socketio as _socketio
        _socketio.emit(
            'match_rescheduled',
            {
                'match_id': int(match.id),
                'league_type': 'pub',
                'rescheduled_at': (match.rescheduled_at.isoformat()
                                   if match.rescheduled_at else None),
                'new_date': match.date.isoformat() if match.date else None,
                'new_time': match.time.isoformat() if match.time else None,
                'rescheduled_by_user_id': actor_id,
            },
            room=f"match_{int(match.id)}",
            namespace='/live',
        )
    except Exception:
        logger.exception(f"Failed to emit match_rescheduled for match {match.id}")
