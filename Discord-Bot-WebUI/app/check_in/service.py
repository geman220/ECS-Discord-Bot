# app/check_in/service.py

"""
Match Check-In Service

Single source of truth for the check-in business rules. Used by:
- Mobile API endpoints (player self check-in, coach scan, roster)
- Admin panel routes (manual mark, generate token, attendance review)

Status taxonomy (matches Flutter spec):
    'success'             First successful check-in for this player+match
    'already_checked_in'  Player already in match_attendance
    'outside_window'      Outside ±MATCH_CHECKIN_WINDOW_HOURS of kickoff
    'not_rsvp_yes'        Player isn't on the YES list for this match
    'unknown_member'      The scanned player_token didn't resolve
    'unauthorized'        Caller can't act for this match
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from app.core import db
from app.models import (
    Player, Match, Availability, MatchAttendance, MatchCheckInToken,
)
from app.models.ecs_fc import EcsFcMatch, EcsFcAvailability
from app.models.players import player_teams
from app.models.wallet import WalletPass, WalletPassCheckin

from .constants import MATCH_CHECKIN_WINDOW_HOURS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Match resolution
# ---------------------------------------------------------------------------

def get_match(session, league_type: str, match_id: int):
    """Return the Match or EcsFcMatch row, or None.

    Two physical tables (matches, ecs_fc_matches) — caller passes
    league_type so we know which to query.
    """
    if league_type == 'pub_league':
        return session.query(Match).get(match_id)
    if league_type == 'ecs_fc':
        return session.query(EcsFcMatch).get(match_id)
    return None


def get_match_kickoff(match) -> Optional[datetime]:
    """Compose a naive datetime from a match's date + time columns.

    pub_league `Match` uses .date / .time.
    ecs_fc `EcsFcMatch` uses .match_date / .match_time.
    """
    if match is None:
        return None
    if isinstance(match, Match):
        d, t = match.date, match.time
    elif isinstance(match, EcsFcMatch):
        d, t = match.match_date, match.match_time
    else:
        return None
    if not d or not t:
        return None
    return datetime.combine(d, t)


def is_within_checkin_window(match, hours: int = MATCH_CHECKIN_WINDOW_HOURS, now: Optional[datetime] = None) -> bool:
    """True if (now) is within ±hours of kickoff."""
    kickoff = get_match_kickoff(match)
    if kickoff is None:
        return False
    if now is None:
        now = datetime.utcnow()
    delta = abs((now - kickoff).total_seconds())
    return delta <= hours * 3600


def build_match_label(match) -> str:
    """Short human-readable label like 'Rangers vs United'.

    For ECS FC matches the opponent is external (.opponent_name); for
    pub_league we have both team names as relationships.
    """
    if isinstance(match, Match):
        home = match.home_team.name if match.home_team else "Home"
        away = match.away_team.name if match.away_team else "Away"
        return f"{home} vs {away}"
    if isinstance(match, EcsFcMatch):
        ecs_team = match.team.name if match.team else "ECS FC"
        opp = match.opponent_name or "Opponent"
        return f"{ecs_team} vs {opp}" if match.is_home_match else f"{opp} vs {ecs_team}"
    return "Match"


# ---------------------------------------------------------------------------
# Roster + RSVP
# ---------------------------------------------------------------------------

def _match_team_ids(match) -> List[int]:
    if isinstance(match, Match):
        return [tid for tid in (match.home_team_id, match.away_team_id) if tid]
    if isinstance(match, EcsFcMatch):
        return [match.team_id] if match.team_id else []
    return []


def is_player_on_roster(session, player: Player, match) -> bool:
    """True if the player is on either team participating in this match."""
    if not player or match is None:
        return False
    team_ids = _match_team_ids(match)
    if not team_ids:
        return False
    # player_teams association table — exists row tying player to one of these teams
    row = session.query(player_teams).filter(
        player_teams.c.player_id == player.id,
        player_teams.c.team_id.in_(team_ids),
    ).first()
    return row is not None


def did_player_rsvp_yes(session, player: Player, match) -> bool:
    """True if the player has an Availability/EcsFcAvailability row with response='yes'."""
    if not player or match is None:
        return False
    if isinstance(match, Match):
        row = session.query(Availability).filter_by(
            match_id=match.id, player_id=player.id
        ).first()
    elif isinstance(match, EcsFcMatch):
        row = session.query(EcsFcAvailability).filter_by(
            ecs_fc_match_id=match.id, player_id=player.id
        ).first()
    else:
        return False
    return bool(row and row.response == 'yes')


def get_match_roster_yes(session, match) -> List[Player]:
    """Return all players who RSVP'd 'yes' for this match (both teams)."""
    if match is None:
        return []
    if isinstance(match, Match):
        rows = session.query(Availability).filter_by(
            match_id=match.id, response='yes'
        ).all()
        player_ids = [r.player_id for r in rows if r.player_id]
    elif isinstance(match, EcsFcMatch):
        rows = session.query(EcsFcAvailability).filter_by(
            ecs_fc_match_id=match.id, response='yes'
        ).all()
        player_ids = [r.player_id for r in rows if r.player_id]
    else:
        return []
    if not player_ids:
        return []
    return session.query(Player).filter(Player.id.in_(player_ids)).all()


# ---------------------------------------------------------------------------
# Coach / admin access
# ---------------------------------------------------------------------------

def is_coach_of_match(session, player: Optional[Player], match) -> bool:
    """True if the player is a coach of any team in this match.

    Uses player_teams.is_coach. For pub_league: coach of home OR away team.
    For ecs_fc: coach of the single ECS FC team (opponent is external).
    """
    if not player or match is None:
        return False
    team_ids = _match_team_ids(match)
    if not team_ids:
        return False
    row = session.query(player_teams).filter(
        player_teams.c.player_id == player.id,
        player_teams.c.team_id.in_(team_ids),
        player_teams.c.is_coach.is_(True),
    ).first()
    return row is not None


_ADMIN_ROLE_NAMES = {'Global Admin', 'Pub League Admin', 'ECS FC Admin'}


def has_admin_role(user, session=None) -> bool:
    """True if the user has Global Admin / Pub League Admin / ECS FC Admin role.

    Loads roles via a fresh query against the request-scoped session
    (g.db_session) — matches the @role_required pattern so this works even
    when current_user is a Flask-Login proxy whose `roles` relationship
    isn't eagerly loaded. Honors role impersonation when active.
    """
    if not user:
        return False
    user_id = getattr(user, 'id', None)
    if not user_id:
        return False

    try:
        from app.role_impersonation import is_impersonation_active, get_effective_roles
        if is_impersonation_active():
            names = set(get_effective_roles() or [])
            return bool(names & _ADMIN_ROLE_NAMES)
    except Exception:
        pass  # role_impersonation may not be importable in all contexts.

    try:
        from flask import g
        from sqlalchemy.orm import selectinload
        from app.models import User

        # Prefer the request-scoped session so we use the same connection /
        # transaction state as the surrounding route work.
        sess = session or getattr(g, 'db_session', None)
        if sess is None:
            from app.core import db
            sess = db.session

        db_user = sess.query(User).options(selectinload(User.roles)).get(user_id)
        if not db_user:
            return False
        names = {r.name for r in (db_user.roles or [])}
        return bool(names & _ADMIN_ROLE_NAMES)
    except Exception as e:
        logger.warning(f"has_admin_role lookup failed for user_id={user_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------

def resolve_member_token(session, token: str) -> Optional[Player]:
    """Resolve a member_token (WalletPass.barcode_data) to a Player.

    Returns None if the token doesn't match any active wallet pass, or if
    the matched pass isn't tied to a Player (e.g., a generic ECS membership
    pass that wasn't linked to a portal account).
    """
    if not token:
        return None
    wp = session.query(WalletPass).filter_by(barcode_data=token).first()
    if not wp:
        return None
    if wp.player_id:
        return session.query(Player).get(wp.player_id)
    if wp.user_id:
        return session.query(Player).filter_by(user_id=wp.user_id).first()
    return None


def resolve_player_id_or_token(session, value: str) -> Optional[Player]:
    """For coach_manual: try as member_token first, then as integer Player.id.

    The Flutter coach screen uses this branch when a coach long-presses a
    player in the "Not Yet" list — the app sends the player's integer ID
    as a string instead of scanning a QR.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    # Try as token (member_token) first.
    p = resolve_member_token(session, value)
    if p:
        return p
    # Fall back: integer player_id.
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return session.query(Player).get(pid)


# ---------------------------------------------------------------------------
# Main check-in function
# ---------------------------------------------------------------------------

def perform_check_in(
    *,
    session,
    league_type: str,
    match_id: int,
    player: Player,
    source: str,
    recorded_by_user_id: Optional[int] = None,
    venue_token: Optional[MatchCheckInToken] = None,
    bypass_rsvp: bool = False,
    bypass_window: bool = False,
    notes: Optional[str] = None,
) -> dict:
    """Validate + record a check-in. Returns the spec's status payload.

    Caller is responsible for committing the session. We use db.session.add()
    inside MatchAttendance.record() and don't flush — the route's
    @transactional or `with managed_session() as s: s.commit()` handles it.
    """
    match = get_match(session, league_type, match_id)
    if not match:
        return {
            'status': 'unknown_match',
            'message': 'Match not found.',
        }

    if not player:
        return {
            'status': 'unknown_member',
            'message': 'Player not found.',
        }

    # Roster check — admin override always applies for coach_manual / admin.
    if source not in ('coach_manual', 'admin'):
        if not is_player_on_roster(session, player, match):
            return {
                'status': 'unknown_member',
                'message': 'Player is not on the match roster.',
            }

    # Time-window check (skippable by admin override / coach_manual at the
    # caller's discretion via bypass_window — default on for non-self).
    if not bypass_window and not is_within_checkin_window(match):
        return {
            'status': 'outside_window',
            'message': f'Check-in is only available within {MATCH_CHECKIN_WINDOW_HOURS} hours of kickoff.',
            'match_id': match.id,
            'player_name': player.name,
        }

    # RSVP check — coach_manual and admin bypass.
    if not bypass_rsvp and source not in ('coach_manual', 'admin'):
        if not did_player_rsvp_yes(session, player, match):
            return {
                'status': 'not_rsvp_yes',
                'message': "Player didn't RSVP YES for this match.",
                'match_id': match.id,
                'player_name': player.name,
            }

    # Idempotent insert.
    venue_token_id = venue_token.id if venue_token is not None else None
    row, created = MatchAttendance.record(
        league_type=league_type,
        match_id=match.id,
        player_id=player.id,
        source=source,
        recorded_by_user_id=recorded_by_user_id,
        venue_token_id=venue_token_id,
        notes=notes,
    )

    # Cross-write to WalletPassCheckin for unified pass-history view, but
    # only on first creation — re-scans don't pad the history.
    if created:
        try:
            _record_wallet_pass_checkin_if_applicable(
                session, player, match, recorded_by_user_id
            )
        except Exception as e:
            # Cross-write is best-effort — don't fail the check-in if the
            # wallet pass insert hits a snag.
            logger.warning(f"WalletPassCheckin cross-write failed for player {player.id}: {e}")

    status = 'success' if created else 'already_checked_in'
    label = build_match_label(match)
    message = (
        f"{player.name} checked in for {label}." if created else
        f"{player.name} was already checked in for {label}."
    )

    return {
        'status': status,
        'message': message,
        'match_id': match.id,
        'player_name': player.name,
        'checked_in_at': row.checked_in_at.isoformat() + 'Z' if row.checked_in_at else None,
    }


def _record_wallet_pass_checkin_if_applicable(
    session, player: Player, match, recorded_by_user_id: Optional[int]
):
    """Insert a WalletPassCheckin row so match check-ins appear in the
    existing wallet check-in history alongside bar-pass scans.

    If the player has no active WalletPass we silently skip (this is a
    best-effort cross-write).
    """
    wp = session.query(WalletPass).filter(
        WalletPass.player_id == player.id,
        WalletPass.status == 'active'
    ).first()
    if not wp:
        return
    label = build_match_label(match)
    location = getattr(match, 'location', None)
    checkin = WalletPassCheckin(
        wallet_pass_id=wp.id,
        check_in_type='qr_scan',
        location=location,
        event_name=label,
        checked_by_user_id=recorded_by_user_id,
        was_valid=True,
        validation_message='Match check-in',
    )
    session.add(checkin)


# ---------------------------------------------------------------------------
# Roster view (for the coach scanner's split list)
# ---------------------------------------------------------------------------

def build_roster_view(session, match, league_type: str, include_all: bool = False) -> dict:
    """Return the spec's roster payload: split list for the coach scanner."""
    if include_all:
        # Everyone on either team's roster, regardless of RSVP.
        team_ids = _match_team_ids(match)
        if not team_ids:
            players = []
        else:
            rows = session.query(Player).join(
                player_teams, Player.id == player_teams.c.player_id
            ).filter(player_teams.c.team_id.in_(team_ids)).distinct().all()
            players = rows
    else:
        players = get_match_roster_yes(session, match)

    attendance_rows = MatchAttendance.list_for_match(league_type, match.id)
    attendance_by_player = {a.player_id: a for a in attendance_rows}

    entries = []
    for p in players:
        att = attendance_by_player.get(p.id)
        entries.append({
            'player_id': p.id,
            'player_name': p.name,
            'profile_picture_url': _profile_url(p),
            'jersey_number': getattr(p, 'jersey_number', None),
            'checked_in': att is not None,
            'checked_in_at': (att.checked_in_at.isoformat() + 'Z') if att and att.checked_in_at else None,
            'checked_in_by': att.checked_in_by if att else None,
        })

    # Sort: checked-in first (by most recent), then not-yet alphabetically.
    def sort_key(e):
        return (
            0 if e['checked_in'] else 1,
            -datetime.fromisoformat(e['checked_in_at'].rstrip('Z')).timestamp()
                if e['checked_in_at'] else 0,
            e['player_name'].lower(),
        )
    entries.sort(key=sort_key)

    return {
        'match_id': match.id,
        'league_type': league_type,
        'entries': entries,
    }


def _profile_url(player) -> Optional[str]:
    """Build absolute profile picture URL.

    Uses request.host_url when in a request context, falls back to relative.
    """
    if not player or not player.profile_picture_url:
        return None
    if player.profile_picture_url.startswith('http'):
        return player.profile_picture_url
    try:
        from flask import request
        return f"{request.host_url.rstrip('/')}{player.profile_picture_url}"
    except Exception:
        return player.profile_picture_url
