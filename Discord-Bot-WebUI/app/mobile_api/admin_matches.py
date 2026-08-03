# app/mobile_api/admin_matches.py

"""
Mobile Admin — Match Schedule

Moving a fixture and calling one off, from the touchline. Both were desktop-only
(and "postpone" was not implemented anywhere: the admin panel's button was a JS
stub that popped an alert and wrote nothing).

Bodies live in ``app/services/match_schedule_service.py`` — the mirror-pair
handling in particular has to be in one place, because a Pub League fixture is
TWO Schedule rows and moving only one leaves the away team looking at the old
kickoff time.

Gate: ``@jwt_required()`` + ``@jwt_role_required(ADMIN_ROLES)`` where ADMIN_ROLES
is the web's ``['Global Admin', 'Pub League Admin']``.

⚠️ ``sql_match_postponement.sql`` must have run before this deploys — the
postpone columns are mapped on the Match model, so an un-migrated database fails
every match query, not just these routes.
"""

import logging

from flask import g, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required
from app.services import match_schedule_service as schedule_service
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)

ADMIN_ROLES = ['Global Admin', 'Pub League Admin']


def _body():
    """Request body as a dict, JSON or form. ``get_json()`` without
    ``silent=True`` raises 400/415 in Flask 3 before any ``or {}`` can run."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    if request.form:
        return request.form.to_dict()
    return {}


_FALSY = {'false', '0', 'no', 'off', 'none', 'null', ''}


def _as_bool(value, default=False):
    """Form bodies carry only strings, and bare ``bool('false')`` is True — which
    would turn every "postpone" into a "cancel". JSON clients are unaffected."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in _FALSY


@mobile_api_v2.route('/admin/matches/<int:match_id>/schedule', methods=['PATCH'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_match_update_schedule(match_id: int):
    """Move a fixture. Body: {"date": "2026-08-14", "time": "19:30:00",
    "location": "North", "notes": "..."} — every field OPTIONAL.

    ⚠️ OMITTED FIELDS ARE LEFT ALONE. The client sends only what changed, so a
    missing key means "don't touch", never "clear". ``date`` is ``YYYY-MM-DD``
    and ``time`` is ``HH:MM:SS`` — the formats every other match payload uses;
    a combined ISO datetime is never sent and is not accepted.

    Both Schedule rows of the mirror pair move with it, so the away team's
    schedule page can't keep the old kickoff.
    """
    data = _body()
    payload, status = schedule_service.update_schedule(
        g.db_session, match_id, actor_id=int(get_jwt_identity()),
        # An explicit null reads the same as an omitted key, which is what we
        # want: the client has no way to express "clear the date", and there is
        # no valid empty date/time/location anyway. `notes` is the exception —
        # '' really does clear a note, and '' is not None, so it survives.
        date=data.get('date'),
        time=data.get('time'),
        location=data.get('location'),
        notes=data.get('notes'),
    )
    return jsonify(payload), status


@mobile_api_v2.route('/admin/matches/<int:match_id>/postpone', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_match_postpone(match_id: int):
    """Call a fixture off. Body: {"reason": "waterlogged", "cancelled": false}.

    ``cancelled: false`` = postponed, a new date is coming.
    ``cancelled: true``  = cancelled, it is never being played.

    Those are different messages to someone deciding whether to drive across
    town, so they are stored as different states and surfaced separately in
    ``Match.to_dict()['schedule_status']``.

    ``reason`` is required — members are shown it verbatim, and a fixture that
    just says "cancelled" is the one that generates the emails.

    Repeating the same call is an idempotent success (it refreshes the reason),
    so a client retry never becomes an error dialog.
    """
    data = _body()
    payload, status = schedule_service.set_schedule_status(
        g.db_session, match_id, actor_id=int(get_jwt_identity()),
        reason=data.get('reason'),
        cancelled=_as_bool(data.get('cancelled'), False),
    )
    return jsonify(payload), status


@mobile_api_v2.route('/admin/matches/<int:match_id>/postpone', methods=['DELETE'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
@transactional(max_retries=3)
def admin_match_unpostpone(match_id: int):
    """Put a called-off fixture back on.

    Not in the client spec, but a one-way door is how ``deny`` became a
    perma-lockout: a mis-tapped "cancel" with no undo would leave the fixture
    dead on every member's schedule with no way back short of SQL.
    """
    payload, status = schedule_service.clear_schedule_status(
        g.db_session, match_id, actor_id=int(get_jwt_identity()))
    return jsonify(payload), status
