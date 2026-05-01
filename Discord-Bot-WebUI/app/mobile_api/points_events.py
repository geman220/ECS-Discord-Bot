# app/mobile_api/points_events.py

"""
Points Events Mobile API

Admin tools for awarding participation points to players for non-match league
events (parties, field setup help, Discord engagement, etc.). Mirrors the
match check-in module's response shape so the Flutter `CheckInResult` parser
keeps working.

Endpoints:

    GET    /api/v1/admin/events/types                       List types
    POST   /api/v1/admin/events/types                       Create
    GET    /api/v1/admin/events/types/<id>                  Get one
    PUT    /api/v1/admin/events/types/<id>                  Update / restore
    DELETE /api/v1/admin/events/types/<id>                  Soft archive
    POST   /api/v1/admin/events/types/<id>/award            Scan-and-award
    GET    /api/v1/admin/events/types/<id>/awards           Audit log
    GET    /api/v1/admin/players/<player_id>/points         Player history (admin)
    GET    /api/v1/me/points                                Caller's own balance

Auth: admin role required for everything except /me/points (any logged-in
user). X-API-Key + JWT enforced by middleware.

Award business outcomes return HTTP 200 with a `status` field — same
convention as perform_check_in at app/check_in/service.py:341-347. Validation
errors return 400 with {"msg": ...}; auth errors 403; not-found 404; name
collisions 409.
"""

import json
import logging
from datetime import datetime
from typing import Optional, Tuple

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.decorators import jwt_role_required
from app.models import (
    User, Player, PointsEventType, PointsEventAward, AdminAuditLog,
)
from app.check_in.service import resolve_player_id_or_token, has_admin_role
from app.utils.safe_redis import get_safe_redis

logger = logging.getLogger(__name__)


ADMIN_ROLES = ['Pub League Admin', 'Global Admin', 'ECS FC Admin']
DEBOUNCE_TTL_SECONDS = 30
DEFAULT_LIMIT = 50
MAX_LIMIT_TYPES = 100
MAX_LIMIT_AWARDS = 500


# ---------------------------------------------------------------------------
# Inline helpers
# ---------------------------------------------------------------------------

def _iso_z(dt: Optional[datetime]) -> Optional[str]:
    """UTC ISO-8601 with 'Z' suffix, or None."""
    return dt.isoformat() + 'Z' if dt else None


def _build_profile_picture_url(player: Optional[Player]) -> Optional[str]:
    """Absolute URL for a player's avatar, or None.

    Inline copy of the helper at app/mobile_api/check_in.py:42-48 — coach_rsvp
    style, kept local rather than extracted to avoid a shared-util dependency.
    """
    if not player or not player.profile_picture_url:
        return None
    if player.profile_picture_url.startswith('http'):
        return player.profile_picture_url
    return f"{request.host_url.rstrip('/')}{player.profile_picture_url}"


def _audit(action: str, resource_id, *, old_value=None, new_value=None) -> None:
    """Wrap AdminAuditLog.log_action with safe defaults.

    Audit failures must never block the primary action. AdminAuditLog itself
    catches errors internally; this wrapper just sets the resource_type and
    pulls request metadata.
    """
    try:
        AdminAuditLog.log_action(
            user_id=int(get_jwt_identity()),
            action=action,
            resource_type='points_events',
            resource_id=str(resource_id) if resource_id is not None else None,
            old_value=old_value,
            new_value=new_value,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
    except Exception as e:
        logger.error(f"Failed to log points-events audit ({action}): {e}")


def _name_in_use(session, name: str, *, exclude_id: Optional[int] = None) -> bool:
    """True if an active (non-archived) type already uses this name (case-insensitive).

    The partial unique index on LOWER(name) WHERE NOT is_archived is the
    safety net; this pre-check just lets us return a clean 409 instead of
    bubbling an IntegrityError.
    """
    q = session.query(PointsEventType.id).filter(
        func.lower(PointsEventType.name) == name.strip().lower(),
        PointsEventType.is_archived.is_(False),
    )
    if exclude_id is not None:
        q = q.filter(PointsEventType.id != exclude_id)
    return q.first() is not None


def _validate_event_type_payload(
    data: dict, *, partial: bool
) -> Tuple[Optional[dict], Optional[str]]:
    """Validate request body for create/update.

    Returns (cleaned_dict, None) on success; (None, error_msg) on failure.
    For partial=True (PUT), only fields present are validated.
    """
    if not isinstance(data, dict):
        return None, "Request body must be a JSON object"

    cleaned: dict = {}

    if 'name' in data or not partial:
        name_raw = data.get('name')
        if name_raw is None or not isinstance(name_raw, str):
            return None, "name is required and must be a string"
        name = name_raw.strip()
        if not (1 <= len(name) <= 60):
            return None, "name must be 1-60 characters"
        cleaned['name'] = name

    if 'description' in data:
        desc = data.get('description')
        if desc is None:
            cleaned['description'] = None
        elif not isinstance(desc, str):
            return None, "description must be a string"
        else:
            desc = desc.strip()
            if len(desc) > 500:
                return None, "description must be 500 characters or fewer"
            cleaned['description'] = desc or None

    if 'default_points' in data or not partial:
        pts_raw = data.get('default_points')
        try:
            pts = int(pts_raw)
        except (TypeError, ValueError):
            return None, "default_points must be an integer"
        if not (1 <= pts <= 10000):
            return None, "default_points must be between 1 and 10000"
        cleaned['default_points'] = pts

    # Optional un-archive / archive via PUT.
    if 'is_archived' in data:
        ia = data.get('is_archived')
        if not isinstance(ia, bool):
            return None, "is_archived must be a boolean"
        cleaned['is_archived'] = ia

    return cleaned, None


def _serialize_type(t: PointsEventType, *, totals: Optional[dict] = None) -> dict:
    """Serialize a type with optional aggregate counts."""
    payload = t.to_dict()
    if totals is not None:
        payload['total_awards'] = int(totals.get('total_awards') or 0)
        payload['total_points_awarded'] = int(totals.get('total_points_awarded') or 0)
    return payload


def _aggregate_totals_by_type(session, type_ids):
    """Return {type_id: {'total_awards', 'total_points_awarded'}} for the ids."""
    if not type_ids:
        return {}
    rows = (
        session.query(
            PointsEventAward.event_type_id,
            func.count(PointsEventAward.id),
            func.coalesce(func.sum(PointsEventAward.points_awarded), 0),
        )
        .filter(PointsEventAward.event_type_id.in_(type_ids))
        .group_by(PointsEventAward.event_type_id)
        .all()
    )
    return {
        type_id: {'total_awards': count, 'total_points_awarded': int(total)}
        for (type_id, count, total) in rows
    }


def _validate_award_payload(
    data: dict
) -> Tuple[Optional[dict], Optional[str]]:
    """Validate body for the scan endpoint."""
    if not isinstance(data, dict):
        return None, "Request body must be a JSON object"

    token = data.get('player_token')
    if not isinstance(token, str) or not token.strip():
        return None, "player_token is required"
    cleaned = {'player_token': token.strip()}

    override = data.get('points_override', None)
    if override is not None:
        try:
            override = int(override)
        except (TypeError, ValueError):
            return None, "points_override must be an integer"
        if not (1 <= override <= 10000):
            return None, "points_override must be between 1 and 10000"
        cleaned['points_override'] = override
    else:
        cleaned['points_override'] = None

    note = data.get('note')
    if note is None:
        cleaned['note'] = None
    elif not isinstance(note, str):
        return None, "note must be a string"
    else:
        note = note.strip()
        if len(note) > 255:
            return None, "note must be 255 characters or fewer"
        cleaned['note'] = note or None

    return cleaned, None


def _debounce_key(type_id: int, player_id: int) -> str:
    return f"points_award:debounce:{type_id}:{player_id}"


# ---------------------------------------------------------------------------
# GET /admin/events/types — list
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/admin/events/types', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def list_event_types_route():
    include_archived = request.args.get('include_archived', '').lower() in ('1', 'true', 'yes')
    try:
        with managed_session() as session_db:
            q = session_db.query(PointsEventType)
            if not include_archived:
                q = q.filter(PointsEventType.is_archived.is_(False))
            types = q.order_by(PointsEventType.name.asc()).all()

            totals_by_id = _aggregate_totals_by_type(
                session_db, [t.id for t in types]
            )
            payload = [
                _serialize_type(t, totals=totals_by_id.get(t.id, {}))
                for t in types
            ]
            return jsonify({"types": payload}), 200
    except Exception as e:
        logger.error(f"Error listing event types: {e}", exc_info=True)
        return jsonify({"msg": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# POST /admin/events/types — create
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/admin/events/types', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def create_event_type_route():
    data = request.get_json(silent=True) or {}
    cleaned, err = _validate_event_type_payload(data, partial=False)
    if err:
        return jsonify({"msg": err}), 400

    try:
        with managed_session() as session_db:
            if _name_in_use(session_db, cleaned['name']):
                return jsonify({
                    "msg": "An event type with that name already exists."
                }), 409

            t = PointsEventType(
                name=cleaned['name'],
                description=cleaned.get('description'),
                default_points=cleaned['default_points'],
                created_by_user_id=int(get_jwt_identity()),
            )
            session_db.add(t)
            try:
                session_db.flush()
            except IntegrityError:
                session_db.rollback()
                return jsonify({
                    "msg": "An event type with that name already exists."
                }), 409

            _audit(
                'create_event_type', t.id,
                new_value=f"name={t.name} default_points={t.default_points}",
            )
            session_db.commit()
            return jsonify(_serialize_type(t, totals={})), 201
    except Exception as e:
        logger.error(f"Error creating event type: {e}", exc_info=True)
        return jsonify({"msg": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# GET /admin/events/types/<id> — read one
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/admin/events/types/<int:type_id>', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def get_event_type_route(type_id: int):
    try:
        with managed_session() as session_db:
            t = session_db.query(PointsEventType).get(type_id)
            if not t:
                return jsonify({"msg": "Event type not found"}), 404
            totals = _aggregate_totals_by_type(session_db, [t.id]).get(t.id, {})
            return jsonify(_serialize_type(t, totals=totals)), 200
    except Exception as e:
        logger.error(f"Error fetching event type {type_id}: {e}", exc_info=True)
        return jsonify({"msg": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# PUT /admin/events/types/<id> — update / restore
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/admin/events/types/<int:type_id>', methods=['PUT'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def update_event_type_route(type_id: int):
    data = request.get_json(silent=True) or {}
    cleaned, err = _validate_event_type_payload(data, partial=True)
    if err:
        return jsonify({"msg": err}), 400

    try:
        with managed_session() as session_db:
            t = session_db.query(PointsEventType).get(type_id)
            if not t:
                return jsonify({"msg": "Event type not found"}), 404

            old_snapshot = (
                f"name={t.name} default_points={t.default_points} "
                f"is_archived={t.is_archived}"
            )

            if 'name' in cleaned and cleaned['name'].lower() != t.name.lower():
                # Effective archived state after this update — if the body
                # restores the type, the new name must not collide.
                effective_archived = cleaned.get('is_archived', t.is_archived)
                if not effective_archived and _name_in_use(
                    session_db, cleaned['name'], exclude_id=t.id
                ):
                    return jsonify({
                        "msg": "An event type with that name already exists."
                    }), 409

            for field in ('name', 'description', 'default_points', 'is_archived'):
                if field in cleaned:
                    setattr(t, field, cleaned[field])

            try:
                session_db.flush()
            except IntegrityError:
                session_db.rollback()
                return jsonify({
                    "msg": "An event type with that name already exists."
                }), 409

            new_snapshot = (
                f"name={t.name} default_points={t.default_points} "
                f"is_archived={t.is_archived}"
            )
            _audit(
                'update_event_type', t.id,
                old_value=old_snapshot, new_value=new_snapshot,
            )
            session_db.commit()
            totals = _aggregate_totals_by_type(session_db, [t.id]).get(t.id, {})
            return jsonify(_serialize_type(t, totals=totals)), 200
    except Exception as e:
        logger.error(f"Error updating event type {type_id}: {e}", exc_info=True)
        return jsonify({"msg": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# DELETE /admin/events/types/<id> — soft archive
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/admin/events/types/<int:type_id>', methods=['DELETE'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def archive_event_type_route(type_id: int):
    try:
        with managed_session() as session_db:
            t = session_db.query(PointsEventType).get(type_id)
            if not t:
                return jsonify({"msg": "Event type not found"}), 404
            if t.is_archived:
                return jsonify({"msg": "Event type already archived"}), 200
            t.is_archived = True
            _audit('archive_event_type', t.id, new_value="archived")
            session_db.commit()
            return jsonify({"msg": "Event type archived"}), 200
    except Exception as e:
        logger.error(f"Error archiving event type {type_id}: {e}", exc_info=True)
        return jsonify({"msg": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# POST /admin/events/types/<id>/award — the scan
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/admin/events/types/<int:type_id>/award', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def award_points_route(type_id: int):
    data = request.get_json(silent=True) or {}
    cleaned, err = _validate_award_payload(data)
    if err:
        return jsonify({"msg": err}), 400

    try:
        with managed_session() as session_db:
            t = session_db.query(PointsEventType).get(type_id)
            if not t:
                return jsonify({"msg": "Event type not found"}), 404
            if t.is_archived:
                return jsonify({
                    "status": "type_archived",
                    "message": "This event type has been archived.",
                }), 200

            player = resolve_player_id_or_token(session_db, cleaned['player_token'])
            if not player:
                return jsonify({
                    "status": "unknown_member",
                    "message": "Couldn't resolve that player.",
                }), 200

            points = cleaned['points_override'] or t.default_points
            note = cleaned['note']
            recorded_by_user_id = int(get_jwt_identity())

            redis = get_safe_redis()
            key = _debounce_key(type_id, player.id)
            placeholder = json.dumps({"placeholder": True})

            # Try to acquire the debounce lock. Returns True on first writer,
            # False on either (a) key already exists OR (b) Redis unavailable.
            acquired = redis.set(key, placeholder, nx=True, ex=DEBOUNCE_TTL_SECONDS)
            if not acquired:
                existing = redis.get(key)
                if existing:
                    # Real debounce hit — return existing award_id if we
                    # stored it after a previous insert.
                    award_id = None
                    points_already = points
                    try:
                        existing_str = (
                            existing.decode('utf-8')
                            if isinstance(existing, (bytes, bytearray))
                            else str(existing)
                        )
                        parsed = json.loads(existing_str)
                        if isinstance(parsed, dict):
                            award_id = parsed.get('award_id')
                            points_already = parsed.get('points_awarded') or points
                    except (ValueError, TypeError):
                        pass

                    new_total = PointsEventAward.total_for_player(
                        session_db, player.id
                    )
                    return jsonify({
                        "status": "already_awarded",
                        "award_id": award_id,
                        "match_id": None,
                        "player_name": player.name,
                        "player_id": player.id,
                        "points_awarded": points_already,
                        "new_total": new_total,
                        "checked_in_at": _iso_z(datetime.utcnow()),
                    }), 200
                # Redis is down — fail open. Proceed with the insert.
                logger.warning(
                    "Redis unavailable for points-award debounce; failing open"
                )

            award = PointsEventAward(
                event_type_id=type_id,
                player_id=player.id,
                points_awarded=points,
                recorded_by_user_id=recorded_by_user_id,
                note=note,
            )
            session_db.add(award)
            session_db.flush()  # populate award.id

            # Re-set the debounce key with the real award_id so concurrent
            # rescans within the window can return the same id (UX win).
            try:
                redis.set(
                    key,
                    json.dumps({
                        "award_id": award.id,
                        "points_awarded": points,
                    }),
                    ex=DEBOUNCE_TTL_SECONDS,
                )
            except Exception as e:
                # Non-fatal — debounce just won't return the award_id on the
                # follow-up scan; the row is already inserted.
                logger.warning(f"Could not persist debounce metadata: {e}")

            new_total = PointsEventAward.total_for_player(session_db, player.id)
            _audit(
                'award_points', award.id,
                new_value=(
                    f"{points} pts to player {player.id} "
                    f"for type {type_id}"
                ),
            )
            session_db.commit()

            return jsonify({
                "status": "success",
                "award_id": award.id,
                "match_id": None,
                "player_name": player.name,
                "player_id": player.id,
                "points_awarded": points,
                "new_total": new_total,
                "checked_in_at": _iso_z(award.recorded_at),
            }), 200
    except Exception as e:
        logger.error(f"Error awarding points for type {type_id}: {e}", exc_info=True)
        return jsonify({"msg": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# GET /admin/events/types/<id>/awards — audit list
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/admin/events/types/<int:type_id>/awards', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def list_awards_for_type_route(type_id: int):
    limit = min(request.args.get('limit', DEFAULT_LIMIT, type=int), MAX_LIMIT_AWARDS)
    offset = max(request.args.get('offset', 0, type=int), 0)
    since_raw = request.args.get('since')
    since_dt: Optional[datetime] = None
    if since_raw:
        try:
            # Accept both with and without trailing 'Z'.
            since_clean = since_raw.rstrip('Z')
            since_dt = datetime.fromisoformat(since_clean)
        except ValueError:
            return jsonify({"msg": "since must be a valid ISO-8601 timestamp"}), 400

    try:
        with managed_session() as session_db:
            t = session_db.query(PointsEventType).get(type_id)
            if not t:
                return jsonify({"msg": "Event type not found"}), 404

            base_q = (
                session_db.query(PointsEventAward)
                .filter(PointsEventAward.event_type_id == type_id)
            )
            if since_dt:
                base_q = base_q.filter(PointsEventAward.recorded_at >= since_dt)

            total_awards = base_q.count()

            rows = (
                base_q.order_by(PointsEventAward.recorded_at.desc())
                .limit(limit)
                .offset(offset)
                .all()
            )

            # Bulk-fetch related players + recorders to avoid N+1.
            player_ids = {r.player_id for r in rows}
            user_ids = {r.recorded_by_user_id for r in rows if r.recorded_by_user_id}
            players_by_id = {
                p.id: p for p in
                (session_db.query(Player).filter(Player.id.in_(player_ids)).all()
                 if player_ids else [])
            }
            users_by_id = {
                u.id: u for u in
                (session_db.query(User).filter(User.id.in_(user_ids)).all()
                 if user_ids else [])
            }

            awards = []
            for r in rows:
                player = players_by_id.get(r.player_id)
                recorder = users_by_id.get(r.recorded_by_user_id)
                awards.append({
                    "award_id": r.id,
                    "player_id": r.player_id,
                    "player_name": player.name if player else None,
                    "profile_picture_url": _build_profile_picture_url(player),
                    "points_awarded": r.points_awarded,
                    "recorded_at": _iso_z(r.recorded_at),
                    "recorded_by_user_id": r.recorded_by_user_id,
                    "recorded_by_name": recorder.username if recorder else None,
                    "note": r.note,
                })

            return jsonify({
                "type_id": t.id,
                "type_name": t.name,
                "default_points": t.default_points,
                "total_awards": total_awards,
                "awards": awards,
            }), 200
    except Exception as e:
        logger.error(
            f"Error listing awards for type {type_id}: {e}", exc_info=True
        )
        return jsonify({"msg": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# GET /admin/players/<player_id>/points — admin player view
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/admin/players/<int:player_id>/points', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_get_player_points_route(player_id: int):
    try:
        with managed_session() as session_db:
            player = session_db.query(Player).get(player_id)
            if not player:
                return jsonify({"msg": "Player not found"}), 404

            payload = _build_player_points_payload(
                session_db, player, include_audit_metadata=True
            )
            return jsonify(payload), 200
    except Exception as e:
        logger.error(
            f"Error fetching points for player {player_id}: {e}", exc_info=True
        )
        return jsonify({"msg": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# GET /me/points — caller's own balance
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/me/points', methods=['GET'])
@jwt_required()
def me_points_route():
    try:
        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())
            player = session_db.query(Player).filter_by(
                user_id=current_user_id
            ).first()
            if not player:
                return jsonify({"msg": "Player profile not found"}), 404

            payload = _build_player_points_payload(
                session_db, player, include_audit_metadata=False
            )
            return jsonify(payload), 200
    except Exception as e:
        logger.error(f"Error fetching /me/points: {e}", exc_info=True)
        return jsonify({"msg": "Internal server error"}), 500


def _build_player_points_payload(
    session, player: Player, *, include_audit_metadata: bool
) -> dict:
    """Shared shape for /admin/players/<id>/points and /me/points.

    `include_audit_metadata=False` strips award_id, recorded_by_user_id, and
    note from each entry — players see what + when, not who recorded it or
    private notes.
    """
    rows = (
        session.query(PointsEventAward)
        .filter(PointsEventAward.player_id == player.id)
        .order_by(PointsEventAward.recorded_at.desc())
        .all()
    )

    type_ids = {r.event_type_id for r in rows}
    types_by_id = {
        t.id: t for t in
        (session.query(PointsEventType).filter(PointsEventType.id.in_(type_ids)).all()
         if type_ids else [])
    }

    awards_payload = []
    for r in rows:
        t = types_by_id.get(r.event_type_id)
        entry = {
            "type_id": r.event_type_id,
            "type_name": t.name if t else None,
            "points_awarded": r.points_awarded,
            "recorded_at": _iso_z(r.recorded_at),
        }
        if include_audit_metadata:
            entry.update({
                "award_id": r.id,
                "note": r.note,
            })
        awards_payload.append(entry)

    total_points = sum(r.points_awarded for r in rows)
    last_award_at = rows[0].recorded_at if rows else None

    payload = {
        "player_id": player.id,
        "player_name": player.name,
        "total_points": total_points,
        "last_award_at": _iso_z(last_award_at),
        "awards": awards_payload,
    }
    return payload
