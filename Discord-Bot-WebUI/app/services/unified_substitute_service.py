# app/services/unified_substitute_service.py

"""
Unified Substitute Service (READ-UNIFY + ACTION-DISPATCH adapter)

This is a thin read adapter that normalizes the two existing substitute-request
systems into a single shape for the unified admin board:

  - Pub League: SubstituteRequest / SubstituteResponse / SubstituteAssignment
                (match -> Match, date field `date`, home/away teams)
  - ECS FC:     EcsFcSubRequest / EcsFcSubResponse / EcsFcSubAssignment
                (match -> EcsFcMatch, date field `match_date`, opponent_name/location)

It NEVER writes. It only reads from both models, builds a normalized item dict
per request, and computes the action_urls that point at the EXISTING per-league
endpoints (see the endpoint map below). The unified board's buttons dispatch to
those endpoints unchanged — no notification / assignment / backend logic lives here.

Verified endpoint names (admin_bp nests ecs_fc_subs + substitute_pool, so they are
prefixed with `admin.`):
  ECS FC:
    assign    -> admin.ecs_fc_subs.assign_substitute      (POST .../assign)
    available -> admin.ecs_fc_subs.get_available_subs      (GET  .../available-subs)
    cancel    -> admin.ecs_fc_subs.cancel_sub_request      (POST .../cancel)
    view      -> admin_panel.ecs_fc_rsvp_status            (match_id)
    contact   -> admin_panel.ecs_fc_contact_subs           (POST, board-level)
  Pub League:
    assign    -> admin_panel.assign_substitute             (POST, request_id in body)
    available -> admin_panel.get_available_players_for_request (GET, request_id)
    cancel    -> admin.substitute_pool.cancel_substitute_request (POST, league_type+request_id)
    view      -> admin_panel.substitute_management
    contact   -> admin_panel.notify_substitute_pool        (POST, request_id in body)
"""

import logging
from datetime import datetime

from flask import url_for
from sqlalchemy.orm import joinedload, selectinload

logger = logging.getLogger(__name__)

# Status sets used for filtering. Mirrors the nightly
# expire_past_match_sub_requests task: OPEN/PENDING/APPROVED are "active".
ACTIVE_STATUSES = ('OPEN', 'PENDING', 'APPROVED')


def _fmt_day(d):
    """'Sat Jun 14' (no leading zero on the day-of-month)."""
    if not d:
        return None
    return f"{d.strftime('%a %b')} {d.day}"


def _fmt_time(t):
    """'8:20am' / '9:30pm' — lowercase am/pm, no leading zero on the hour."""
    if not t:
        return None
    hour = t.hour % 12 or 12
    ampm = 'am' if t.hour < 12 else 'pm'
    return f"{hour}:{t.minute:02d}{ampm}"


def _first_position(positions_needed):
    """First position from a comma-separated 'positions_needed' string, or None."""
    if not positions_needed:
        return None
    first = positions_needed.split(',')[0].strip()
    return first or None


def _pub_league_default_message(match, positions_needed):
    """Pub League contact default — time + position, NO team.

    'Need a sub Sat Jun 14 at 8:20am — Defender. You in?'
    Drops the '— {position}' part when no specific position is needed.
    """
    day = _fmt_day(match.date) if match else None
    tm = _fmt_time(match.time) if match else None
    when = f"{day} at {tm}" if (day and tm) else (day or 'soon')
    pos = _first_position(positions_needed)
    if pos:
        return f"Need a sub {when} — {pos}. You in?"
    return f"Need a sub {when}. You in?"


def _ecs_fc_default_message(team_name, match):
    """ECS FC contact default — team + time + field.

    'ECS FC Rainier needs a sub Sat Jun 14, 9:30pm at Starfire Field 3. Can you play?'
    """
    day = _fmt_day(match.match_date) if match else None
    tm = _fmt_time(match.match_time) if match else None
    field = (match.location if match and match.location else None) or 'the field'
    when = f"{day}, {tm}" if (day and tm) else (day or 'soon')
    return f"{team_name} needs a sub {when} at {field}. Can you play?"


def _tally_from_responses(responses):
    """Count responses by availability tri-state.

    is_available: True = available, False = unavailable, None = pending.
    A response that hasn't been responded to (no responded_at) is also pending.
    """
    available = pending = unavailable = 0
    for r in responses or []:
        if r.responded_at is None or r.is_available is None:
            pending += 1
        elif r.is_available:
            available += 1
        else:
            unavailable += 1
    return {'available': available, 'pending': pending, 'unavailable': unavailable}


def _pub_league_action_urls(req):
    """Pub League action URLs -> existing endpoints (request_id passed in body for
    assign/contact, so those are the base routes; cancel needs league_type)."""
    return {
        'available': url_for('admin_panel.get_available_players_for_request', request_id=req.id),
        'assign': url_for('admin_panel.assign_substitute'),
        'contact': url_for('admin_panel.notify_substitute_pool'),
        'cancel': url_for(
            'admin.substitute_pool.cancel_substitute_request',
            league_type=(req.league_type or 'Classic'),
            request_id=req.id,
        ),
        'view': url_for('admin_panel.substitute_management'),
    }


def _ecs_fc_action_urls(req):
    """ECS FC action URLs -> existing ecs_fc_subs blueprint + admin_panel endpoints."""
    urls = {
        'available': url_for('admin.ecs_fc_subs.get_available_subs', request_id=req.id),
        'assign': url_for('admin.ecs_fc_subs.assign_substitute', request_id=req.id),
        'contact': url_for('admin_panel.ecs_fc_contact_existing', request_id=req.id),
        'cancel': url_for('admin.ecs_fc_subs.cancel_sub_request', request_id=req.id),
        'view': None,
    }
    if req.match_id:
        urls['view'] = url_for('admin_panel.ecs_fc_rsvp_status', match_id=req.match_id)
    return urls


def _normalize_pub_league(req):
    """Normalize a SubstituteRequest into the unified item dict."""
    match = req.match
    match_date = match.date if match else None
    if match and match.home_team and match.away_team:
        match_label = f"{match.home_team.name} vs {match.away_team.name}"
    elif match:
        match_label = f"Match #{req.match_id}"
    else:
        match_label = "No match"

    assignments = req.assignments or []
    responses = req.responses or []
    tally = _tally_from_responses(responses)
    needed = req.substitutes_needed or 1
    assigned = len(assignments)
    ready = (req.status == 'OPEN' and tally['available'] > 0 and assigned < needed)

    return {
        'league': 'pub_league',
        'id': req.id,
        'league_type': req.league_type or 'Classic',
        'match_id': req.match_id,
        'team_id': req.team_id,
        'match_label': match_label,
        'match_date': match_date,
        'team_name': req.team.name if req.team else 'Unknown',
        'positions': req.positions_needed or '',
        'needed': needed,
        'assigned': assigned,
        'status': req.status,
        'notes': req.notes or '',
        'created_at': req.created_at,
        'tally': tally,
        'total_contacted': len(responses),
        'ready_to_assign': ready,
        'default_contact_message': _pub_league_default_message(match, req.positions_needed),
        'action_urls': _pub_league_action_urls(req),
    }


def _normalize_ecs_fc(req):
    """Normalize an EcsFcSubRequest into the unified item dict."""
    match = req.match
    match_date = match.match_date if match else None
    if match:
        team_label = req.team.name if req.team else (match.team.name if match.team else 'ECS FC')
        match_label = f"{team_label} vs {match.opponent_name or 'TBD'}"
    else:
        match_label = "No match"

    assignments = req.assignments or []
    responses = req.responses or []
    tally = _tally_from_responses(responses)
    needed = req.substitutes_needed or 1
    assigned = len(assignments)
    ready = (req.status == 'OPEN' and tally['available'] > 0 and assigned < needed)

    return {
        'league': 'ecs_fc',
        'id': req.id,
        'league_type': 'ECS FC',
        'match_id': req.match_id,
        'team_id': req.team_id,
        'match_label': match_label,
        'match_date': match_date,
        'team_name': req.team.name if req.team else 'Unknown',
        'positions': req.positions_needed or '',
        'needed': needed,
        'assigned': assigned,
        'status': req.status,
        'notes': req.notes or '',
        'created_at': req.created_at,
        'tally': tally,
        'total_contacted': len(responses),
        'ready_to_assign': ready,
        'default_contact_message': _ecs_fc_default_message(
            req.team.name if req.team else (match.team.name if match and match.team else 'ECS FC'),
            match,
        ),
        'action_urls': _ecs_fc_action_urls(req),
    }


def _status_matches(item_status, match_date, status_filter, today):
    """Apply the status filter to a normalized item.

    'active'    -> status in ACTIVE and match is future-or-today (excludes EXPIRED
                   + past-match, mirroring the nightly expiry rule).
    'open'      -> status == OPEN
    'filled'    -> status == FILLED
    'cancelled' -> status == CANCELLED
    'expired'   -> status == EXPIRED
    'all'       -> everything.
    """
    if status_filter == 'all':
        return True
    if status_filter == 'active':
        if item_status not in ACTIVE_STATUSES:
            return False
        # Exclude past-match requests (match already happened). Requests with no
        # match date are treated as actionable (kept in the active view).
        if match_date is not None and match_date < today:
            return False
        return True
    return item_status == status_filter.upper()


def get_unified_requests(session, *, league='all', status='active', page=1, per_page=25):
    """Return normalized substitute requests from BOTH leagues.

    Args:
        session: SQLAlchemy session.
        league:  'all' | 'pub_league' | 'ecs_fc'
        status:  'active' (default) | 'all' | 'open' | 'filled' | 'cancelled' | 'expired'
        page:    1-based page number.
        per_page: items per page.

    Returns:
        (items, total, page, pages) where items is a list of normalized dicts.
    """
    from app.models.substitutes import (
        SubstituteRequest, SubstituteResponse, SubstituteAssignment,
        EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment,
    )
    from app.models import Match

    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = max(1, min(100, int(per_page)))
    except (TypeError, ValueError):
        per_page = 25

    today = datetime.utcnow().date()
    league = (league or 'all').lower()
    status = (status or 'active').lower()

    items = []

    # --- Pub League ---
    if league in ('all', 'pub_league'):
        try:
            pl_reqs = session.query(SubstituteRequest).options(
                joinedload(SubstituteRequest.match).joinedload(Match.home_team),
                joinedload(SubstituteRequest.match).joinedload(Match.away_team),
                joinedload(SubstituteRequest.team),
                selectinload(SubstituteRequest.assignments),
                selectinload(SubstituteRequest.responses),
            ).all()
            for req in pl_reqs:
                norm = _normalize_pub_league(req)
                if _status_matches(norm['status'], norm['match_date'], status, today):
                    items.append(norm)
        except Exception as e:
            logger.error(f"Error loading Pub League sub requests: {e}", exc_info=True)

    # --- ECS FC ---
    if league in ('all', 'ecs_fc'):
        try:
            from app.models.ecs_fc import EcsFcMatch
            ecs_reqs = session.query(EcsFcSubRequest).options(
                joinedload(EcsFcSubRequest.match).joinedload(EcsFcMatch.team),
                joinedload(EcsFcSubRequest.team),
                selectinload(EcsFcSubRequest.assignments),
                selectinload(EcsFcSubRequest.responses),
            ).all()
            for req in ecs_reqs:
                norm = _normalize_ecs_fc(req)
                if _status_matches(norm['status'], norm['match_date'], status, today):
                    items.append(norm)
        except Exception as e:
            logger.error(f"Error loading ECS FC sub requests: {e}", exc_info=True)

    # Sort: soonest match first (None match_date last), then newest created.
    def _sort_key(it):
        md = it['match_date']
        return (md is None, md or today, -(it['created_at'].timestamp() if it.get('created_at') else 0))

    items.sort(key=_sort_key)

    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], total, page, pages


def get_unified_pool(session):
    """Return both substitute pools' members normalized for the side panel.

    Each member: {league, name, positions, player_id}.
    Pub League uses SubstitutePool (active rows); ECS FC uses EcsFcSubPool (active rows).
    """
    from app.models.substitutes import SubstitutePool, EcsFcSubPool

    members = []

    # --- Pub League pool ---
    try:
        pl_entries = session.query(SubstitutePool).options(
            joinedload(SubstitutePool.player)
        ).filter(SubstitutePool.is_active == True).all()  # noqa: E712
        for entry in pl_entries:
            player = entry.player
            if not player:
                continue
            members.append({
                'league': 'pub_league',
                'player_id': entry.player_id,
                'name': player.name or 'Unknown',
                'positions': entry.preferred_positions or player.favorite_position or '',
            })
    except Exception as e:
        logger.error(f"Error loading Pub League sub pool: {e}", exc_info=True)

    # --- ECS FC pool ---
    try:
        ecs_entries = session.query(EcsFcSubPool).options(
            joinedload(EcsFcSubPool.player)
        ).filter(EcsFcSubPool.is_active == True).all()  # noqa: E712
        for entry in ecs_entries:
            player = entry.player
            if not player:
                continue
            members.append({
                'league': 'ecs_fc',
                'player_id': entry.player_id,
                'name': player.name or 'Unknown',
                'positions': entry.preferred_positions or player.favorite_position or '',
            })
    except Exception as e:
        logger.error(f"Error loading ECS FC sub pool: {e}", exc_info=True)

    members.sort(key=lambda m: (m['name'] or '').lower())
    return members
