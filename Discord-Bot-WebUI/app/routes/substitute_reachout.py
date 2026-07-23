# app/routes/substitute_reachout.py

"""
Substitute Reach-out Response Routes

Public (login-required) web pages where a sub responds to an admin/coach
reach-out via a secure per-recipient token. A reach-out feeds the SAME
availability pool as the Discord poll (record_reachout_response).

Privacy invariant: the reach-out (general OR targeted) NEVER reveals the team,
opponent, or the originating request — only the date + time slot(s) + the ask.
"""

import logging
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.core import db
from app.models.substitutes import SubstituteReachout, SubstituteReachoutRecipient

logger = logging.getLogger(__name__)

substitute_reachout_bp = Blueprint('substitute_reachout', __name__, url_prefix='/sub-reachout')


def _format_slot(slot) -> str:
    """'08:20' -> '8:20am'."""
    try:
        hh, mm = str(slot).split(':')
        h, m = int(hh), int(mm)
        ampm = 'am' if h < 12 else 'pm'
        h12 = h % 12 or 12
        return f"{h12}:{m:02d}{ampm}"
    except Exception:
        return str(slot)


def _load(token):
    """Return (recipient, reachout) for a token, or (None, None)."""
    recipient = db.session.query(SubstituteReachoutRecipient).filter_by(
        response_token=token
    ).first()
    if not recipient:
        return None, None
    reachout = db.session.query(SubstituteReachout).get(recipient.reachout_id)
    return recipient, reachout


def _details(reachout):
    """Team-agnostic display details for a reach-out (no team/opponent)."""
    slots = reachout.time_slots or []
    return {
        'league_type': reachout.league_type,
        'date': reachout.match_date.strftime('%A, %B %d, %Y') if reachout.match_date else 'TBD',
        'time_slots': [_format_slot(s) for s in slots],
        'message': reachout.message or '',
    }


@substitute_reachout_bp.route('/<token>')
@login_required
def view_reachout(token):
    """Render the reach-out response page. User must be the recipient's player."""
    recipient, reachout = _load(token)

    if not recipient or not reachout:
        return render_template(
            'substitute_reachout_flowbite.html',
            error='This reach-out link is invalid or has expired.',
        )

    # Verify the logged-in user matches the contacted player.
    if not current_user.player or current_user.player.id != recipient.player_id:
        flash('You are not authorized to respond to this reach-out', 'error')
        return redirect(url_for('main.index'))

    already_responded = recipient.responded_at is not None
    token_expired = not recipient.is_token_valid()

    if not already_responded and token_expired:
        return render_template(
            'substitute_reachout_flowbite.html',
            error='This reach-out link has expired.',
        )

    return render_template(
        'substitute_reachout_flowbite.html',
        token=token,
        recipient=recipient,
        details=_details(reachout),
        already_responded=already_responded,
        error=None,
    )


@substitute_reachout_bp.route('/<token>/respond', methods=['POST'])
@login_required
def submit_reachout(token):
    """Record a reach-out response and fold it into the availability pool."""
    from app.services.substitute_availability_service import record_reachout_response

    recipient, reachout = _load(token)

    if not recipient or not reachout:
        flash('This reach-out link is invalid or has expired.', 'error')
        return redirect(url_for('main.index'))

    if not current_user.player or current_user.player.id != recipient.player_id:
        flash('You are not authorized to respond to this reach-out', 'error')
        return redirect(url_for('main.index'))

    if recipient.responded_at is not None:
        flash('You have already responded to this reach-out.', 'info')
        return redirect(url_for('substitute_reachout.view_reachout', token=token))

    if not recipient.is_token_valid():
        flash('This reach-out link has expired.', 'error')
        return redirect(url_for('main.index'))

    is_available = request.form.get('is_available') == 'yes'

    try:
        recipient.is_available = is_available
        recipient.responded_at = datetime.utcnow()
        recipient.response_method = 'web'

        record_reachout_response(
            db.session,
            player_id=recipient.player_id,
            match_date=reachout.match_date,
            league_type=reachout.league_type,
            is_available=is_available,
            time_slots=reachout.time_slots,
            match_ids=reachout.match_ids,
            source='reachout_web',
            season_id=reachout.season_id,
        )
        db.session.commit()
        flash('Thank you! Your response has been recorded.', 'success')
    except Exception as e:
        logger.error(f"Error processing reach-out response: {e}")
        db.session.rollback()
        flash('An error occurred while processing your response.', 'error')

    return redirect(url_for('substitute_reachout.view_reachout', token=token))
