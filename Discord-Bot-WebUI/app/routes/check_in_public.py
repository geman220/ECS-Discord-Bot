# app/routes/check_in_public.py

"""
Public Check-In Routes

Two unauthenticated HTML pages that the QR codes / NFC stickers encode:

- GET /m/<token>           Member identity card (camera-app scans of player QR)
- GET /check-in/<token>    Venue landing page (printed sign / NFC at the pitch)

When the user has the iOS/Android app installed, the universal-link
association on these paths intercepts the URL and routes into the app
instead — only browser users actually see the HTML rendered here.

The HTML is intentionally minimal and contact-info-free. Returns 404
for unknown tokens so we don't leak which tokens exist.
"""

import logging
from datetime import datetime, timedelta
from flask import Blueprint, render_template, abort

from app.core.session_manager import managed_session
from app.models import Player
from app.models.wallet import WalletPass

logger = logging.getLogger(__name__)

check_in_public_bp = Blueprint('check_in_public', __name__)


def _build_profile_picture_url(player, host_url: str):
    if not player or not player.profile_picture_url:
        return None
    if player.profile_picture_url.startswith('http'):
        return player.profile_picture_url
    return f"{host_url.rstrip('/')}{player.profile_picture_url}"


@check_in_public_bp.route('/m/<token>', methods=['GET'])
def member_identity(token: str):
    """Public member identity page.

    Renders a minimal HTML card with photo, name, team, division, season,
    and an active/expired/suspended status badge. No email, phone, or
    discord handle (those would leak PII via casual QR scans).

    Universal-link interception: when the ECS FC app is installed, iOS/
    Android intercept this URL via /.well-known/apple-app-site-association
    and /assetlinks.json — only browser users see this template.
    """
    from flask import request

    try:
        with managed_session() as session_db:
            wallet_pass = session_db.query(WalletPass).filter_by(
                barcode_data=token
            ).first()

            player = None
            if wallet_pass:
                if wallet_pass.player_id:
                    player = session_db.query(Player).get(wallet_pass.player_id)
                elif wallet_pass.user_id:
                    player = session_db.query(Player).filter_by(
                        user_id=wallet_pass.user_id
                    ).first()

            if not player:
                return render_template('public/member_pass_404.html'), 404

            team_name = "ECS FC"
            if player.primary_team:
                team_name = player.primary_team.name
            elif getattr(player, 'teams', None) and len(player.teams) > 0:
                team_name = player.teams[0].name

            division = player.league.name if player.league else "Pub League"

            # Status badge value: only emit something when it's not a generic
            # "active" so the template can omit the badge by default.
            status = 'active'
            badge_label = None
            if not player.is_current_player:
                status = 'inactive'
                badge_label = 'Inactive'
            elif wallet_pass:
                if wallet_pass.status == 'voided':
                    status = 'suspended'
                    badge_label = 'Suspended'
                elif wallet_pass.is_expired:
                    status = 'expired'
                    badge_label = 'Expired'
                elif not wallet_pass.is_valid:
                    status = 'inactive'
                    badge_label = 'Inactive'

            return render_template(
                'public/member_pass.html',
                player_name=player.name,
                team_name=team_name,
                division=division,
                profile_picture_url=_build_profile_picture_url(player, request.host_url),
                status=status,
                badge_label=badge_label,
                jersey_number=getattr(player, 'jersey_number', None),
            )

    except Exception as e:
        logger.error(f"Error rendering member identity for token {token[:8]}...: {e}", exc_info=True)
        abort(500)


@check_in_public_bp.route('/check-in/<token>', methods=['GET'])
def check_in_landing(token: str):
    """Public venue check-in landing page.

    Encoded by the printed QR sign / NFC sticker at the pitch. App-installed
    users get intercepted via universal links; browser users see this HTML
    pointing them at the app.
    """
    try:
        # Lazy import — model lives in slice 2; defer so /m/ keeps working
        # if this module is loaded before the model is in place.
        from app.models.match_check_in import MatchCheckInToken
        with managed_session() as session_db:
            ct = session_db.query(MatchCheckInToken).filter_by(
                token=token, revoked_at=None
            ).first()
            if not ct:
                return render_template('public/check_in_landing_404.html'), 404

            match_label, kickoff_local = _describe_match(session_db, ct.league_type, ct.match_id)
            return render_template(
                'public/check_in_landing.html',
                match_label=match_label,
                kickoff_local=kickoff_local,
            )

    except Exception as e:
        logger.error(f"Error rendering check-in landing for token {token[:8]}...: {e}", exc_info=True)
        abort(500)


def _describe_match(session_db, league_type: str, match_id: int):
    """Return (match_label, kickoff_local_display) for the landing page."""
    try:
        if league_type == 'pub_league':
            from app.models import Match
            match = session_db.query(Match).get(match_id)
            if not match:
                return ("Match", None)
            home = match.home_team.name if match.home_team else "Home"
            away = match.away_team.name if match.away_team else "Away"
            label = f"{home} vs {away}"
            kickoff = datetime.combine(match.date, match.time) if match.date and match.time else None
        elif league_type == 'ecs_fc':
            from app.models.ecs_fc import EcsFcMatch
            match = session_db.query(EcsFcMatch).get(match_id)
            if not match:
                return ("Match", None)
            ecs_team = match.team.name if match.team else "ECS FC"
            opp = match.opponent_name or "Opponent"
            label = f"{ecs_team} vs {opp}" if match.is_home_match else f"{opp} vs {ecs_team}"
            kickoff = datetime.combine(match.match_date, match.match_time) if match.match_date and match.match_time else None
        else:
            return ("Match", None)

        kickoff_local = kickoff.strftime('%a %b %-d, %-I:%M %p') if kickoff else None
        return (label, kickoff_local)
    except Exception:
        return ("Match", None)
