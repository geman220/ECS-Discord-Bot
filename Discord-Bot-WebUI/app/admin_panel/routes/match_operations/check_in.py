# app/admin_panel/routes/match_operations/check_in.py

"""
Match Check-In Admin Routes

Admin panel pages and JSON APIs for managing match check-in tokens and
attendance:

- List view: every upcoming match with its token status + attendance count
- Per-match detail: split roster (Not Yet / Checked In), printable QR
- Generate/revoke venue tokens (one active token per match)
- Manual mark / unmark attendance (admin or coach override)
- CSV export
- Bulk generate tokens for all upcoming matches
"""

import csv
import io
import logging
from datetime import datetime, timedelta

from flask import render_template, request, jsonify, send_file, url_for, abort, current_app
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.core.session_manager import managed_session
from app.decorators import role_required
from app.utils.db_utils import transactional

from app.models import (
    Match, Team, MatchCheckInToken, MatchAttendance, Player,
)
from app.models.ecs_fc import EcsFcMatch

from app.check_in.service import (
    perform_check_in, get_match, build_match_label, get_match_kickoff,
    is_coach_of_match, has_admin_role, build_roster_view,
)

logger = logging.getLogger(__name__)


# Roles that can use the check-in admin pages.
# Coaches can see/manage their own matches via the same UI; their visibility
# is filtered at the route level (we don't accept Pub League Coach as a
# blanket role yet — coach association is via player_teams.is_coach).
_ADMIN_ROLES = ['Global Admin', 'Pub League Admin', 'ECS FC Admin']


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _public_check_in_url(token: str) -> str:
    """Build the absolute /check-in/<token> URL that the QR encodes."""
    return f"{request.host_url.rstrip('/')}/check-in/{token}"


def _can_view_match(session_db, match, league_type: str) -> bool:
    """True if the current user is admin OR coach of this match."""
    if has_admin_role(current_user, session=session_db):
        return True
    caller = session_db.query(Player).filter_by(user_id=current_user.id).first()
    return is_coach_of_match(session_db, caller, match)


def _list_upcoming_matches(session_db, days: int = 14):
    """Yield (league_type, match) tuples for matches in the next `days` days.

    Excludes special-week placeholders (FUN / TST / BYE) and same-team-vs-itself
    rows — those aren't real matches and shouldn't appear in the check-in list.
    """
    today = datetime.utcnow().date()
    horizon = today + timedelta(days=days)

    # Pub league: real matches only.
    pl_matches = session_db.query(Match).filter(
        Match.date >= today,
        Match.date <= horizon,
        Match.is_special_week.is_(False),
        Match.home_team_id != Match.away_team_id,
    ).order_by(Match.date, Match.time).all()
    for m in pl_matches:
        yield ('pub_league', m)

    # ECS FC: single team_id, opponent is external — no same-team check applies.
    ecs_matches = session_db.query(EcsFcMatch).filter(
        EcsFcMatch.match_date >= today,
        EcsFcMatch.match_date <= horizon,
    ).order_by(EcsFcMatch.match_date, EcsFcMatch.match_time).all()
    for m in ecs_matches:
        yield ('ecs_fc', m)


def _attendance_count(session_db, league_type: str, match_id: int) -> int:
    return session_db.query(MatchAttendance).filter_by(
        league_type=league_type, match_id=match_id
    ).count()


def _yes_count(session_db, league_type: str, match_id: int) -> int:
    """RSVP=yes count (denominator for the 'X of Y' display)."""
    if league_type == 'pub_league':
        from app.models import Availability
        return session_db.query(Availability).filter_by(
            match_id=match_id, response='yes'
        ).count()
    if league_type == 'ecs_fc':
        from app.models.ecs_fc import EcsFcAvailability
        return session_db.query(EcsFcAvailability).filter_by(
            ecs_fc_match_id=match_id, response='yes'
        ).count()
    return 0


# ---------------------------------------------------------------------------
# List view
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/match-operations/check-in')
@login_required
@role_required(_ADMIN_ROLES)
def match_check_in_index():
    """List of upcoming matches with token status + attendance count.

    Coaches don't get this index — their dashboard surfaces specific matches
    (see coach_dashboard.py).
    """
    days = request.args.get('days', 14, type=int)
    days = max(1, min(60, days))  # clamp

    rows = []
    with managed_session() as session_db:
        for league_type, match in _list_upcoming_matches(session_db, days=days):
            token = MatchCheckInToken.find_active_for_match(league_type, match.id)
            checked_in = _attendance_count(session_db, league_type, match.id)
            yes = _yes_count(session_db, league_type, match.id)
            rows.append({
                'league_type': league_type,
                'match_id': match.id,
                'label': build_match_label(match),
                'kickoff': get_match_kickoff(match),
                'location': getattr(match, 'location', None),
                'has_token': token is not None,
                'token_value': token.token if token else None,
                'checked_in_count': checked_in,
                'yes_count': yes,
                'detail_url': url_for(
                    'admin_panel.match_check_in_detail',
                    league_type=league_type, match_id=match.id
                ),
            })

    return render_template(
        'admin_panel/match_operations/check_in/index.html',
        rows=rows,
        days=days,
    )


@admin_panel_bp.route('/match-operations/check-in/api/backfill-wallet-passes', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
def match_check_in_backfill_wallet_passes():
    """Kick the WalletPass backfill task — runs async, returns task id.

    Why: the new GET /api/v1/membership/pass/lookup endpoint resolves
    member_tokens via WalletPass.barcode_data. Players without a WalletPass
    row 404 there, so the coach scanner can't render their identity card.
    This task creates rows for active Pub League players who don't have one.
    """
    from app.tasks.check_in_tasks import backfill_wallet_passes_for_active_players

    async_result = backfill_wallet_passes_for_active_players.delay()
    return jsonify({
        'success': True,
        'message': 'WalletPass backfill kicked off in the background. Check task monitor for results.',
        'task_id': async_result.id,
    })


@admin_panel_bp.route('/match-operations/check-in/api/generate-tokens-for-upcoming', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def match_check_in_generate_bulk():
    """Generate (or keep existing) venue tokens for every upcoming match.

    Idempotent — get_or_create_for_match skips matches that already have one.
    """
    days = request.json.get('days', 14) if request.is_json else 14
    days = max(1, min(60, int(days)))

    created = 0
    skipped = 0
    with managed_session() as session_db:
        for league_type, match in _list_upcoming_matches(session_db, days=days):
            existing = MatchCheckInToken.find_active_for_match(league_type, match.id)
            if existing:
                skipped += 1
                continue
            ct = MatchCheckInToken(
                token=MatchCheckInToken.generate_token(),
                match_id=match.id,
                league_type=league_type,
                created_by_user_id=current_user.id,
            )
            session_db.add(ct)
            created += 1
        session_db.commit()

    return jsonify({
        'success': True,
        'message': f"Generated {created} token{'' if created == 1 else 's'}; {skipped} already existed.",
        'created': created,
        'skipped': skipped,
    })


# ---------------------------------------------------------------------------
# Per-match detail
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/match-operations/check-in/<league_type>/<int:match_id>')
@login_required
@role_required(_ADMIN_ROLES + ['ECS FC Coach'])  # coaches need this UI too
def match_check_in_detail(league_type: str, match_id: int):
    """Per-match check-in admin page.

    Shows roster split (Not Yet / Checked In), the venue QR, generate/revoke
    actions, and manual mark/unmark.
    """
    if league_type not in ('pub_league', 'ecs_fc'):
        abort(404)

    with managed_session() as session_db:
        match = get_match(session_db, league_type, match_id)
        if not match:
            abort(404)

        if not _can_view_match(session_db, match, league_type):
            abort(403)

        token = MatchCheckInToken.find_active_for_match(league_type, match.id)

        # Pre-render the roster server-side; JS refreshes via /api/roster.
        roster_view = build_roster_view(session_db, match, league_type, include_all=False)
        full_roster_view = build_roster_view(session_db, match, league_type, include_all=True)

        ctx = {
            'league_type': league_type,
            'match': match,
            'match_label': build_match_label(match),
            'kickoff': get_match_kickoff(match),
            'location': getattr(match, 'location', None),
            'token': token,
            'check_in_url': _public_check_in_url(token.token) if token else None,
            'roster_yes': roster_view['entries'],
            'roster_full': full_roster_view['entries'],
            'qr_url': url_for(
                'admin_panel.match_check_in_qr_png',
                league_type=league_type, match_id=match.id
            ) if token else None,
            'print_url': url_for(
                'admin_panel.match_check_in_qr_print',
                league_type=league_type, match_id=match.id
            ) if token else None,
            'export_url': url_for(
                'admin_panel.match_check_in_export_csv',
                league_type=league_type, match_id=match.id
            ),
        }

    return render_template('admin_panel/match_operations/check_in/detail.html', **ctx)


# ---------------------------------------------------------------------------
# Generate / revoke
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/match-operations/check-in/<league_type>/<int:match_id>/api/generate-token', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def match_check_in_generate_token(league_type: str, match_id: int):
    """Generate (or rotate) the venue token for this match.

    If an active token exists, revoke it and create a new one — useful when
    a token was leaked or printed incorrectly.
    """
    if league_type not in ('pub_league', 'ecs_fc'):
        return jsonify({'success': False, 'message': 'Invalid league_type'}), 400

    with managed_session() as session_db:
        match = get_match(session_db, league_type, match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        rotate = (request.json or {}).get('rotate', False) if request.is_json else False
        existing = MatchCheckInToken.find_active_for_match(league_type, match.id)
        if existing and rotate:
            existing.revoked_at = datetime.utcnow()
            existing = None
        if existing:
            ct = existing
            created = False
        else:
            ct = MatchCheckInToken(
                token=MatchCheckInToken.generate_token(),
                match_id=match.id,
                league_type=league_type,
                created_by_user_id=current_user.id,
            )
            session_db.add(ct)
            created = True
        session_db.commit()

        return jsonify({
            'success': True,
            'message': 'Token generated.' if created else 'Active token already exists.',
            'token': ct.token,
            'check_in_url': _public_check_in_url(ct.token),
            'created': created,
        })


@admin_panel_bp.route('/match-operations/check-in/<league_type>/<int:match_id>/api/revoke-token', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def match_check_in_revoke_token(league_type: str, match_id: int):
    if league_type not in ('pub_league', 'ecs_fc'):
        return jsonify({'success': False, 'message': 'Invalid league_type'}), 400

    with managed_session() as session_db:
        existing = MatchCheckInToken.find_active_for_match(league_type, match_id)
        if not existing:
            return jsonify({'success': False, 'message': 'No active token to revoke'}), 404
        existing.revoked_at = datetime.utcnow()
        session_db.commit()
        return jsonify({'success': True, 'message': 'Token revoked.'})


# ---------------------------------------------------------------------------
# QR rendering
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/match-operations/check-in/<league_type>/<int:match_id>/qr.png')
@login_required
@role_required(_ADMIN_ROLES + ['ECS FC Coach'])
def match_check_in_qr_png(league_type: str, match_id: int):
    """Serve a PNG QR for the active venue token. Used by the detail page."""
    import qrcode
    from PIL import Image  # noqa: F401  (forces PIL availability check)

    with managed_session() as session_db:
        token = MatchCheckInToken.find_active_for_match(league_type, match_id)
        if not token:
            abort(404)

        url = _public_check_in_url(token.token)
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')

        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return send_file(buf, mimetype='image/png')


@admin_panel_bp.route('/match-operations/check-in/<league_type>/<int:match_id>/qr/print')
@login_required
@role_required(_ADMIN_ROLES + ['ECS FC Coach'])
def match_check_in_qr_print(league_type: str, match_id: int):
    """Printable HTML for the venue QR.

    Designed for 8.5x11 letter paper — match label, kickoff, the QR, and
    a short instruction line. Pop the page and Cmd+P.
    """
    with managed_session() as session_db:
        match = get_match(session_db, league_type, match_id)
        if not match:
            abort(404)
        token = MatchCheckInToken.find_active_for_match(league_type, match_id)
        if not token:
            abort(404)
        return render_template(
            'admin_panel/match_operations/check_in/qr_print.html',
            match_label=build_match_label(match),
            kickoff=get_match_kickoff(match),
            location=getattr(match, 'location', None),
            qr_url=url_for(
                'admin_panel.match_check_in_qr_png',
                league_type=league_type, match_id=match.id
            ),
        )


# ---------------------------------------------------------------------------
# Manual mark / unmark
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/match-operations/check-in/<league_type>/<int:match_id>/api/manual-mark', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES + ['ECS FC Coach'])
@transactional
def match_check_in_manual_mark(league_type: str, match_id: int):
    """Mark a player present without a scan (admin / coach override)."""
    if league_type not in ('pub_league', 'ecs_fc'):
        return jsonify({'success': False, 'message': 'Invalid league_type'}), 400

    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    notes = data.get('notes')
    if not player_id:
        return jsonify({'success': False, 'message': 'Missing player_id'}), 400

    with managed_session() as session_db:
        match = get_match(session_db, league_type, match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        if not _can_view_match(session_db, match, league_type):
            return jsonify({'success': False, 'message': 'Not authorized'}), 403

        player = session_db.query(Player).get(int(player_id))
        if not player:
            return jsonify({'success': False, 'message': 'Player not found'}), 404

        # Admin uses 'admin' source for audit; coach uses 'coach_manual'.
        source = 'admin' if has_admin_role(current_user) else 'coach_manual'
        result = perform_check_in(
            session=session_db,
            league_type=league_type,
            match_id=match_id,
            player=player,
            source=source,
            recorded_by_user_id=current_user.id,
            bypass_rsvp=True,
            bypass_window=True,  # admin override on the window too
            notes=notes,
        )
        session_db.commit()
        return jsonify({
            'success': result['status'] in ('success', 'already_checked_in'),
            'message': result['message'],
            'status': result['status'],
        })


@admin_panel_bp.route('/match-operations/check-in/<league_type>/<int:match_id>/api/unmark', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES + ['ECS FC Coach'])
@transactional
def match_check_in_unmark(league_type: str, match_id: int):
    """Remove a match_attendance row (correction)."""
    if league_type not in ('pub_league', 'ecs_fc'):
        return jsonify({'success': False, 'message': 'Invalid league_type'}), 400

    data = request.get_json(silent=True) or {}
    player_id = data.get('player_id')
    if not player_id:
        return jsonify({'success': False, 'message': 'Missing player_id'}), 400

    with managed_session() as session_db:
        match = get_match(session_db, league_type, match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        if not _can_view_match(session_db, match, league_type):
            return jsonify({'success': False, 'message': 'Not authorized'}), 403

        row = MatchAttendance.find_for_match_player(league_type, match_id, int(player_id))
        if not row:
            return jsonify({'success': False, 'message': 'No check-in to remove'}), 404

        session_db.delete(row)
        session_db.commit()
        return jsonify({'success': True, 'message': 'Check-in removed.'})


# ---------------------------------------------------------------------------
# Roster API (for live JS refresh)
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/match-operations/check-in/<league_type>/<int:match_id>/api/roster')
@login_required
@role_required(_ADMIN_ROLES + ['ECS FC Coach'])
def match_check_in_api_roster(league_type: str, match_id: int):
    if league_type not in ('pub_league', 'ecs_fc'):
        return jsonify({'success': False, 'message': 'Invalid league_type'}), 400
    include_all = request.args.get('include_all', '').lower() in ('1', 'true', 'yes')

    with managed_session() as session_db:
        match = get_match(session_db, league_type, match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404
        if not _can_view_match(session_db, match, league_type):
            return jsonify({'success': False, 'message': 'Not authorized'}), 403

        payload = build_roster_view(session_db, match, league_type, include_all=include_all)
        payload['success'] = True
        return jsonify(payload)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/match-operations/check-in/<league_type>/<int:match_id>/export.csv')
@login_required
@role_required(_ADMIN_ROLES + ['ECS FC Coach'])
def match_check_in_export_csv(league_type: str, match_id: int):
    if league_type not in ('pub_league', 'ecs_fc'):
        abort(404)

    with managed_session() as session_db:
        match = get_match(session_db, league_type, match_id)
        if not match:
            abort(404)
        if not _can_view_match(session_db, match, league_type):
            abort(403)

        rows = MatchAttendance.list_for_match(league_type, match_id)
        # Resolve player names + recorder names in one pass.
        player_ids = [r.player_id for r in rows]
        players = {p.id: p for p in session_db.query(Player).filter(Player.id.in_(player_ids)).all()} if player_ids else {}

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            'match_id', 'league_type', 'match_label', 'player_id', 'player_name',
            'jersey_number', 'checked_in_at', 'checked_in_by', 'recorded_by_user_id', 'notes'
        ])
        label = build_match_label(match)
        for r in rows:
            p = players.get(r.player_id)
            writer.writerow([
                r.match_id, r.league_type, label, r.player_id,
                p.name if p else '',
                getattr(p, 'jersey_number', '') if p else '',
                r.checked_in_at.isoformat() if r.checked_in_at else '',
                r.checked_in_by,
                r.recorded_by_user_id or '',
                (r.notes or '').replace('\n', ' '),
            ])

        out = io.BytesIO(buf.getvalue().encode('utf-8'))
        out.seek(0)
        filename = f"attendance_{league_type}_{match_id}.csv"
        return send_file(
            out,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename,
        )
