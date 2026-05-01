# app/mobile_api/check_in.py

"""
Match Check-In Mobile API

Endpoints powering the Flutter app's membership QR + match check-in feature:

- GET  /api/v1/membership/pass/lookup?token=...   Resolve member_token to identity
- POST /api/v1/check-in/<venue_token>             Player self check-in at the pitch
- POST /api/v1/matches/<lt>/<id>/attendance       Coach/admin scans a player
- GET  /api/v1/matches/<lt>/<id>/attendance       Live roster (split list)

For non-match league events (parties, field setup help), see
app/mobile_api/points_events.py — the original 501 stub at
POST /api/v1/events/<id>/check_in has been retired.

All endpoints require X-API-Key (enforced by mobile_api middleware) and
@jwt_required() bearer auth. Per the Flutter contract, business-rule
rejections return 200 with a status field — HTTP code is secondary.
"""

import logging
from datetime import datetime
from typing import Optional

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import Player, Season, MatchCheckInToken
from app.models.wallet import WalletPass
from app.check_in.service import (
    perform_check_in, get_match, build_roster_view,
    is_coach_of_match, has_admin_role,
    resolve_member_token, resolve_player_id_or_token,
)

logger = logging.getLogger(__name__)


VALID_LEAGUE_TYPES = ('pub_league', 'ecs_fc')


def _build_profile_picture_url(player) -> Optional[str]:
    """Return absolute URL for the player's avatar, or None."""
    if not player or not player.profile_picture_url:
        return None
    if player.profile_picture_url.startswith('http'):
        return player.profile_picture_url
    return f"{request.host_url.rstrip('/')}{player.profile_picture_url}"


def _resolve_player_team_division_season(session_db, player):
    """Return (team_name, division, season_name) for a player.

    Mirrors the logic already used by GET /api/v1/membership/pass so the
    lookup view stays consistent with what the in-app pass shows.
    """
    team_name = "ECS FC"
    if player.primary_team:
        team_name = player.primary_team.name
    elif getattr(player, 'teams', None) and len(player.teams) > 0:
        team_name = player.teams[0].name

    division = player.league.name if player.league else "Pub League"

    current_season = session_db.query(Season).filter_by(
        league_type='Pub League',
        is_current=True
    ).first()
    season_name = current_season.name if current_season else "Spring 2025"

    return team_name, division, season_name


def _public_status_for(wallet_pass: Optional[WalletPass], player: Player) -> str:
    """Map internal status to the spec's public-facing values.

    Spec values: 'active' | 'inactive' | 'expired' | 'suspended'.
    """
    if not player or not player.is_current_player:
        return 'inactive'
    if wallet_pass:
        if wallet_pass.status == 'voided':
            return 'suspended'
        if wallet_pass.is_expired:
            return 'expired'
        if wallet_pass.is_valid:
            return 'active'
        return 'inactive'
    # No WalletPass row but player is current — treat as active.
    return 'active'


@mobile_api_v2.route('/membership/pass/lookup', methods=['GET'])
@jwt_required()
def lookup_membership_pass():
    """Resolve a member_token to a public-safe identity card.

    Used by the in-app coach scanner: when a coach scans a player's QR,
    the app calls this to render the player's identity before tapping
    "Check In". Intentionally omits contact info (email/phone/discord_id).

    Query params:
        token: The member_token (a WalletPass.barcode_data value)

    Returns:
        200 with identity payload, or 404 with {"msg": "Member not found"}.
    """
    token = (request.args.get('token') or '').strip()
    if not token:
        return jsonify({"msg": "Missing token"}), 400

    try:
        with managed_session() as session_db:
            wallet_pass = session_db.query(WalletPass).filter_by(
                barcode_data=token
            ).first()

            # Resolve to a Player. Prefer wallet_pass.player_id (canonical link).
            # Some wallet passes (ECS membership) might not be tied to a player —
            # fall back to user_id → Player.
            player = None
            if wallet_pass:
                if wallet_pass.player_id:
                    player = session_db.query(Player).get(wallet_pass.player_id)
                elif wallet_pass.user_id:
                    player = session_db.query(Player).filter_by(
                        user_id=wallet_pass.user_id
                    ).first()

            if not player:
                return jsonify({"msg": "Member not found"}), 404

            team_name, division, season_name = _resolve_player_team_division_season(
                session_db, player
            )

            return jsonify({
                "member_token": token,
                "player_name": player.name,
                "team_name": team_name,
                "division": division,
                "season": season_name,
                "status": _public_status_for(wallet_pass, player),
                "profile_picture_url": _build_profile_picture_url(player),
                "player_id": player.id,
            }), 200

    except Exception as e:
        logger.error(f"Error looking up member token: {e}", exc_info=True)
        return jsonify({"msg": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# POST /api/v1/check-in/<venue_token> — player self check-in
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/check-in/<venue_token>', methods=['POST'])
@jwt_required()
def player_self_check_in(venue_token: str):
    """Player self check-in via venue QR / NFC sticker.

    JWT identifies the player. Body is empty (or {}).
    Returns the spec status payload — always 200 except 401 (no JWT)
    or 404 (unknown token).
    """
    try:
        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())
            player = session_db.query(Player).filter_by(user_id=current_user_id).first()
            if not player:
                return jsonify({"msg": "Player profile not found"}), 404

            ct = MatchCheckInToken.find_active_by_token(venue_token)
            if not ct:
                return jsonify({"msg": "Invalid or revoked check-in code"}), 404

            payload = perform_check_in(
                session=session_db,
                league_type=ct.league_type,
                match_id=ct.match_id,
                player=player,
                source='self',
                recorded_by_user_id=current_user_id,
                venue_token=ct,
                bypass_rsvp=False,
                bypass_window=False,
            )
            session_db.commit()
            return jsonify(payload), 200

    except Exception as e:
        logger.error(f"Error in player self check-in: {e}", exc_info=True)
        return jsonify({"msg": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# GET /api/v1/matches/<league_type>/<match_id>/attendance — live roster
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/matches/<league_type>/<int:match_id>/attendance', methods=['GET'])
@jwt_required()
def match_attendance_roster(league_type: str, match_id: int):
    """Roster split view for the coach scanner.

    Default scope: RSVP=yes for both teams. ?include_all=true returns the
    full team roster regardless of RSVP.
    """
    if league_type not in VALID_LEAGUE_TYPES:
        return jsonify({"msg": f"Invalid league_type: {league_type}"}), 400

    try:
        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())
            from app.models import User
            user = session_db.query(User).get(current_user_id)
            caller_player = session_db.query(Player).filter_by(user_id=current_user_id).first()

            match = get_match(session_db, league_type, match_id)
            if not match:
                return jsonify({"msg": "Match not found"}), 404

            # Authorization: admin OR coach of this match.
            if not (has_admin_role(user) or is_coach_of_match(session_db, caller_player, match)):
                return jsonify({"status": "unauthorized",
                                "message": "You aren't a coach of this match."}), 403

            include_all = request.args.get('include_all', '').lower() in ('1', 'true', 'yes')
            payload = build_roster_view(session_db, match, league_type, include_all=include_all)
            return jsonify(payload), 200

    except Exception as e:
        logger.error(f"Error fetching roster for {league_type}/{match_id}: {e}", exc_info=True)
        return jsonify({"msg": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# POST /api/v1/matches/<league_type>/<match_id>/attendance — coach scan
# ---------------------------------------------------------------------------

@mobile_api_v2.route('/matches/<league_type>/<int:match_id>/attendance', methods=['POST'])
@jwt_required()
def coach_scan_attendance(league_type: str, match_id: int):
    """Coach (or admin) marks a player present.

    Body:
        {"player_token": "<member_token>" | "<player_id>", "source": "coach"|"coach_manual"|"admin"}

    For source='coach_manual', player_token may be a stringified Player.id —
    the coach long-pressed someone in the "Not Yet" list.
    """
    if league_type not in VALID_LEAGUE_TYPES:
        return jsonify({"msg": f"Invalid league_type: {league_type}"}), 400

    data = request.get_json(silent=True) or {}
    player_token = (data.get('player_token') or '').strip()
    source = (data.get('source') or 'coach').strip()
    if source not in ('coach', 'coach_manual', 'admin'):
        return jsonify({"msg": f"Invalid source: {source}"}), 400
    if not player_token:
        return jsonify({"msg": "Missing player_token"}), 400

    try:
        with managed_session() as session_db:
            current_user_id = int(get_jwt_identity())
            from app.models import User
            user = session_db.query(User).get(current_user_id)
            caller_player = session_db.query(Player).filter_by(user_id=current_user_id).first()

            match = get_match(session_db, league_type, match_id)
            if not match:
                return jsonify({"msg": "Match not found"}), 404

            is_admin = has_admin_role(user)
            is_coach = is_coach_of_match(session_db, caller_player, match)
            if not (is_admin or is_coach):
                return jsonify({"status": "unauthorized",
                                "message": "You aren't a coach of this match."}), 403

            # admin-source requires admin role; non-admins can only submit coach/coach_manual.
            if source == 'admin' and not is_admin:
                return jsonify({"status": "unauthorized",
                                "message": "Admin source requires admin role."}), 403

            if source == 'coach_manual':
                target_player = resolve_player_id_or_token(session_db, player_token)
            else:
                target_player = resolve_member_token(session_db, player_token)

            if not target_player:
                return jsonify({
                    "status": "unknown_member",
                    "message": "Couldn't resolve that player.",
                }), 200

            payload = perform_check_in(
                session=session_db,
                league_type=league_type,
                match_id=match_id,
                player=target_player,
                source=source,
                recorded_by_user_id=current_user_id,
                bypass_rsvp=(source in ('coach_manual', 'admin')),
                bypass_window=False,
            )
            session_db.commit()
            return jsonify(payload), 200

    except Exception as e:
        logger.error(f"Error in coach scan check-in: {e}", exc_info=True)
        return jsonify({"msg": "Internal server error"}), 500


