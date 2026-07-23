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
        'gender_preference': req.gender_preference or '',
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
        'gender_preference': req.gender_preference or '',
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


def _apply_status_sql(query, model, status_filter):
    """Push the status filter into SQL so we don't load whole request tables just to
    show 25 rows (EXPIRED/FILLED/CANCELLED accumulate all season). The date part of
    'active' is still applied in Python by _status_matches on the reduced set."""
    if status_filter == 'all':
        return query
    if status_filter == 'active':
        return query.filter(model.status.in_(list(ACTIVE_STATUSES)))
    return query.filter(model.status == status_filter.upper())


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
            pl_q = session.query(SubstituteRequest).options(
                joinedload(SubstituteRequest.match).joinedload(Match.home_team),
                joinedload(SubstituteRequest.match).joinedload(Match.away_team),
                joinedload(SubstituteRequest.team),
                selectinload(SubstituteRequest.assignments),
                selectinload(SubstituteRequest.responses),
            )
            pl_reqs = _apply_status_sql(pl_q, SubstituteRequest, status).all()
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
            ecs_q = session.query(EcsFcSubRequest).options(
                joinedload(EcsFcSubRequest.match).joinedload(EcsFcMatch.team),
                joinedload(EcsFcSubRequest.team),
                selectinload(EcsFcSubRequest.assignments),
                selectinload(EcsFcSubRequest.responses),
            )
            ecs_reqs = _apply_status_sql(ecs_q, EcsFcSubRequest, status).all()
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


def _initials(name):
    """Two-letter initials for the photo fallback, e.g. 'Marcus Bell' -> 'MB'."""
    parts = [p for p in (name or '').split() if p]
    if not parts:
        return '?'
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _pub_pool_status(entry):
    """Tri-state membership status for a SubstitutePool row.

    pending -> in the pool but not yet approved (approved_at is None)
    break   -> approved once, now toggled inactive
    active  -> approved and active
    """
    if entry.approved_at is None:
        return 'pending'
    if not entry.is_active:
        return 'break'
    return 'active'


def _fmt_positions(raw):
    """Humanize a raw positions value for display. Handles Postgres array literals
    ('{goalkeeper,defender}'), comma strings, and slugs ('central_midfielder')
    -> 'Goalkeeper, Defender', 'Central Midfielder'. De-dupes, never raises."""
    if not raw:
        return ''
    s = str(raw).replace('{', '').replace('}', '').replace('"', '')
    labels, seen = [], set()
    for p in s.split(','):
        p = p.strip()
        if not p:
            continue
        label = p.replace('_', ' ').strip().title()
        key = label.lower()
        if label and key not in seen:
            seen.add(key)
            labels.append(label)
    return ', '.join(labels)


def get_unified_pool(session, season_id=None, include_inactive=False):
    """Return both substitute pools' members, enriched for the hub.

    Each member: {league, player_id, name, positions, avatar_url, initials,
    status, acceptance_rate, matches_played, subbed_this_season}.

    Pub League uses SubstitutePool; ECS FC uses EcsFcSubPool.

    By default (``include_inactive=False``) only active pool rows are returned —
    this preserves the behavior the reach-out "specific people" picker relies on.
    Pass ``include_inactive=True`` for the Sub Pool tab, which needs the full
    tri-state roster (Active / On break / Pending).
    """
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    from app.services.substitute_availability_service import player_sub_stats_bulk

    members = []
    # Dedupe key (player_id, league_type). The ECS FC "twin" writes BOTH a
    # SubstitutePool('ECS FC') row and an EcsFcSubPool row (and the Phase 5 backfill
    # folded legacy ECS-FC-only members into SubstitutePool too), so without this an
    # ECS FC sub would appear twice. SubstitutePool is authoritative (it's what the
    # pool-management endpoints act on), so it wins.
    seen_keys = set()

    # --- SubstitutePool (Classic / Premier / ECS FC twin) — authoritative ---
    try:
        q = session.query(SubstitutePool).options(joinedload(SubstitutePool.player))
        if not include_inactive:
            q = q.filter(SubstitutePool.is_active == True)  # noqa: E712
        pub_entries = [e for e in q.all() if e.player]
    except Exception as e:
        logger.error(f"Error querying substitute pool: {e}", exc_info=True)
        pub_entries = []

    # Stats are BEST-EFFORT. A stats-query failure (or one bad row) must never drop
    # the whole roster — previously a single throw here left the Sub Pool tab showing
    # only ECS FC. So compute stats defensively and fall back to the pool row's own
    # counters, and guard each member individually.
    try:
        stats_map = player_sub_stats_bulk(session, [e.player_id for e in pub_entries], season_id)
    except Exception as e:
        logger.error(f"Sub pool stats failed; showing roster without season stats: {e}", exc_info=True)
        stats_map = {}

    for entry in pub_entries:
        try:
            player = entry.player
            lt = entry.league_type or 'Pub League'
            key = (entry.player_id, lt)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            stats = stats_map.get(entry.player_id) or {
                'response_rate': round(entry.acceptance_rate, 1),
                'matches_played': entry.matches_played or 0,
                'subbed_this_season': 0,
            }
            members.append({
                'league': 'ecs_fc' if lt == 'ECS FC' else 'pub_league',
                'player_id': entry.player_id,
                'name': player.name or 'Unknown',
                'positions': _fmt_positions(entry.preferred_positions or player.favorite_position),
                'league_type': lt,
                'avatar_url': player.avatar_image_url if player else None,
                'initials': _initials(player.name),
                'status': _pub_pool_status(entry),
                'acceptance_rate': stats.get('response_rate', 0.0),
                'matches_played': stats.get('matches_played', 0),
                'subbed_this_season': stats.get('subbed_this_season', 0),
            })
        except Exception as e:
            logger.error(f"Skipping bad sub pool entry (player %s): %s",
                         getattr(entry, 'player_id', None), e, exc_info=True)
            continue

    # --- EcsFcSubPool — only members NOT already covered by the SubstitutePool twin ---
    try:
        q = session.query(EcsFcSubPool).options(joinedload(EcsFcSubPool.player))
        if not include_inactive:
            q = q.filter(EcsFcSubPool.is_active == True)  # noqa: E712
        for entry in q.all():
            player = entry.player
            if not player:
                continue
            key = (entry.player_id, 'ECS FC')
            if key in seen_keys:
                continue  # already listed from SubstitutePool (authoritative)
            seen_keys.add(key)
            received = entry.requests_received or 0
            accepted = entry.requests_accepted or 0
            acc_rate = round((accepted / received) * 100, 1) if received else 0.0
            members.append({
                'league': 'ecs_fc',
                'player_id': entry.player_id,
                'name': player.name or 'Unknown',
                'positions': _fmt_positions(entry.preferred_positions or player.favorite_position),
                'league_type': 'ECS FC',
                'avatar_url': player.avatar_image_url if player else None,
                'initials': _initials(player.name),
                'status': 'active' if entry.is_active else 'break',
                'acceptance_rate': acc_rate,
                'matches_played': entry.matches_played or 0,
                'subbed_this_season': 0,
            })
    except Exception as e:
        logger.error(f"Error loading ECS FC sub pool: {e}", exc_info=True)

    members.sort(key=lambda m: (m['name'] or '').lower())
    return members


def get_hub_insights(session, season_id=None):
    """Command-center insight metrics for the This Week strip.

    Returns:
        {
          avg_time_to_fill_hours: float | None,   # created_at -> first assignment
          fill_rate_pct: float | None,            # filled / actionable this season
          filled_count, actionable_count: int,
          channel_effectiveness: [ {channel, rate_pct, replies, contacted}, ... ],
        }

    Time-to-fill and fill-rate are Pub-League-scoped (the availability pool is Pub
    League), scoped by season via Match.schedule_id -> Schedule.season_id. Channel effectiveness reads reply rate by
    channel from BOTH SubstituteResponse.response_method and
    SubstituteReachoutRecipient (channels_sent + response_method).
    """
    from app.models.substitutes import (
        SubstituteRequest, SubstituteResponse, SubstituteAssignment,
        SubstituteReachoutRecipient, SubstituteReachout,
    )
    from app.models.matches import Match, Schedule

    out = {
        'avg_time_to_fill_hours': None,
        'fill_rate_pct': None,
        'filled_count': 0,
        'actionable_count': 0,
        'channel_effectiveness': [],
    }

    # --- Avg time-to-fill: created_at -> earliest assignment, per request ---
    try:
        aq = (
            session.query(SubstituteRequest.created_at, SubstituteAssignment.assigned_at)
            .join(SubstituteAssignment, SubstituteAssignment.request_id == SubstituteRequest.id)
        )
        if season_id:
            aq = aq.join(Match, SubstituteRequest.match_id == Match.id).join(
                Schedule, Match.schedule_id == Schedule.id).filter(
                Schedule.season_id == season_id
            )
        # Keep the smallest fill delay per request (earliest assignment wins),
        # keyed by the request's created_at timestamp.
        first_by_req = {}
        for created_at, assigned_at in aq.all():
            if not created_at or not assigned_at:
                continue
            delta_h = (assigned_at - created_at).total_seconds() / 3600.0
            if delta_h < 0:
                continue
            k = created_at.isoformat()
            if k not in first_by_req or delta_h < first_by_req[k]:
                first_by_req[k] = delta_h
        if first_by_req:
            out['avg_time_to_fill_hours'] = round(sum(first_by_req.values()) / len(first_by_req), 1)
    except Exception as e:
        logger.error(f"Error computing time-to-fill: {e}", exc_info=True)

    # --- Fill rate this season: FILLED / (all non-cancelled) ---
    try:
        rq = session.query(SubstituteRequest.status)
        if season_id:
            rq = rq.join(Match, SubstituteRequest.match_id == Match.id).join(
                Schedule, Match.schedule_id == Schedule.id).filter(
                Schedule.season_id == season_id
            )
        statuses = [s for (s,) in rq.all()]
        actionable = [s for s in statuses if s != 'CANCELLED']
        filled = [s for s in actionable if s == 'FILLED']
        out['actionable_count'] = len(actionable)
        out['filled_count'] = len(filled)
        if actionable:
            out['fill_rate_pct'] = round(len(filled) / len(actionable) * 100, 0)
    except Exception as e:
        logger.error(f"Error computing fill rate: {e}", exc_info=True)

    # --- Channel effectiveness: replies / contacted per channel ---
    try:
        contacted = {}  # channel -> count contacted
        replied = {}    # channel -> count replied

        # Reach-out recipients: channels_sent is a CSV of channels the DM went to.
        rq = session.query(SubstituteReachoutRecipient.channels_sent,
                           SubstituteReachoutRecipient.responded_at,
                           SubstituteReachoutRecipient.response_method)
        if season_id:
            rq = rq.join(SubstituteReachout,
                         SubstituteReachoutRecipient.reachout_id == SubstituteReachout.id).filter(
                SubstituteReachout.season_id == season_id
            )
        for channels_sent, responded_at, method in rq.all():
            chans = [c.strip().lower() for c in (channels_sent or '').split(',') if c.strip()]
            for c in chans:
                contacted[c] = contacted.get(c, 0) + 1
            if responded_at is not None:
                # Attribute the reply to the method they used if known, else all sent.
                if method:
                    m = method.strip().lower()
                    replied[m] = replied.get(m, 0) + 1
                else:
                    for c in chans:
                        replied[c] = replied.get(c, 0) + 1

        # SubstituteResponse: notification_methods sent + responded_at.
        sq = session.query(SubstituteResponse.notification_methods,
                           SubstituteResponse.responded_at,
                           SubstituteResponse.response_method)
        if season_id:
            sq = sq.join(SubstituteRequest,
                         SubstituteResponse.request_id == SubstituteRequest.id).join(
                Match, SubstituteRequest.match_id == Match.id).join(
                Schedule, Match.schedule_id == Schedule.id).filter(
                Schedule.season_id == season_id
            )
        for methods, responded_at, resp_method in sq.all():
            chans = [c.strip().lower() for c in (methods or '').split(',') if c.strip()]
            for c in chans:
                contacted[c] = contacted.get(c, 0) + 1
            if responded_at is not None:
                if resp_method:
                    m = resp_method.strip().lower()
                    replied[m] = replied.get(m, 0) + 1
                else:
                    for c in chans:
                        replied[c] = replied.get(c, 0) + 1

        # Normalize common channel aliases into display buckets.
        alias = {'push': 'Push', 'discord': 'Discord', 'sms': 'SMS', 'email': 'Email',
                 'mobile': 'Push', 'web': 'Discord'}
        buckets = {}
        for c, n in contacted.items():
            label = alias.get(c, c.title())
            b = buckets.setdefault(label, {'contacted': 0, 'replies': 0})
            b['contacted'] += n
        for c, n in replied.items():
            label = alias.get(c, c.title())
            b = buckets.setdefault(label, {'contacted': 0, 'replies': 0})
            b['replies'] += n

        eff = []
        for label, b in buckets.items():
            rate = round(b['replies'] / b['contacted'] * 100, 0) if b['contacted'] else 0
            eff.append({'channel': label, 'rate_pct': rate,
                        'replies': b['replies'], 'contacted': b['contacted']})
        eff.sort(key=lambda d: -d['rate_pct'])
        out['channel_effectiveness'] = eff
    except Exception as e:
        logger.error(f"Error computing channel effectiveness: {e}", exc_info=True)

    return out


def get_week_needs(session, match_date, season_id=None):
    """Open requests for one match_date across BOTH leagues, joined to candidates.

    For Pub League requests, candidate counts come from the canonical availability
    pool via get_candidates_for_request. ECS FC has a divergent backend (its own
    EcsFcSubResponse availability), so ECS FC needs are returned with candidate
    counts of 0 here — the slide-over loads ECS FC candidates on demand from the
    candidates-for-request JSON route.

    Returns a list of normalized request dicts (same shape as get_unified_requests)
    with extra keys: candidate_count, available_now (subs available for this slot).
    """
    from app.models.substitutes import (
        SubstituteRequest, EcsFcSubRequest,
    )
    from app.models import Match
    from app.services.substitute_availability_service import get_candidates_for_request

    needs = []

    # --- Pub League open requests on this date ---
    try:
        pl_reqs = (
            session.query(SubstituteRequest)
            .join(Match, SubstituteRequest.match_id == Match.id)
            .options(
                joinedload(SubstituteRequest.match).joinedload(Match.home_team),
                joinedload(SubstituteRequest.match).joinedload(Match.away_team),
                joinedload(SubstituteRequest.team),
                selectinload(SubstituteRequest.assignments),
                selectinload(SubstituteRequest.responses),
            )
            .filter(Match.date == match_date, SubstituteRequest.status == 'OPEN')
            .all()
        )
        for req in pl_reqs:
            norm = _normalize_pub_league(req)
            mt = req.match.time if req.match else None
            norm['time_slot'] = mt.strftime('%H:%M') if mt else None
            norm['time_label'] = _fmt_time(mt) if mt else None
            try:
                cands = get_candidates_for_request(session, req, season_id)
            except Exception:
                cands = []
            norm['candidate_count'] = len(cands)
            norm['available_now'] = sum(1 for c in cands if c.get('is_available'))
            needs.append(norm)
    except Exception as e:
        logger.error(f"Error loading Pub League week needs: {e}", exc_info=True)

    # --- ECS FC open requests on this date ---
    try:
        from app.models.ecs_fc import EcsFcMatch
        ecs_reqs = (
            session.query(EcsFcSubRequest)
            .join(EcsFcMatch, EcsFcSubRequest.match_id == EcsFcMatch.id)
            .options(
                joinedload(EcsFcSubRequest.match).joinedload(EcsFcMatch.team),
                joinedload(EcsFcSubRequest.team),
                selectinload(EcsFcSubRequest.assignments),
                selectinload(EcsFcSubRequest.responses),
            )
            .filter(EcsFcMatch.match_date == match_date, EcsFcSubRequest.status == 'OPEN')
            .all()
        )
        for req in ecs_reqs:
            norm = _normalize_ecs_fc(req)
            mt = req.match.match_time if req.match else None
            norm['time_slot'] = mt.strftime('%H:%M') if mt else None
            norm['time_label'] = _fmt_time(mt) if mt else None
            norm['candidate_count'] = norm['tally']['available']
            norm['available_now'] = norm['tally']['available']
            needs.append(norm)
    except Exception as e:
        logger.error(f"Error loading ECS FC week needs: {e}", exc_info=True)

    def _sort_key(it):
        return (it['candidate_count'] == 0, -(it['needed'] - it['assigned']))
    needs.sort(key=_sort_key)
    return needs
