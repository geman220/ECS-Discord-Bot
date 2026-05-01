# app/tasks/check_in_tasks.py

"""
Match Check-In Tasks

Scheduled background work for the match check-in feature:
- Nightly token backfill: ensure every upcoming match has an active venue
  token so admins always have a printable QR ready.
"""

import logging
from datetime import datetime, timedelta

from app.decorators import celery_task

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.check_in_tasks.backfill_wallet_passes_for_active_players',
    bind=True,
    queue='celery',
    max_retries=1,
)
def backfill_wallet_passes_for_active_players(self, session, season_id: int = None):
    """Create WalletPass rows for active Pub League players who don't have one.

    Without a WalletPass row, the GET /api/v1/membership/pass/lookup endpoint
    returns 404 for that player — the in-app coach scanner can't render their
    identity card. Backfill creates a row with a stable barcode_data so
    member_token lookups resolve.

    Idempotent: skips players with an existing active WalletPass.
    Scope: pub_league pass type, players where is_current_player=True with a
    user_id and a team. ECS membership passes (for non-pub-league supporters)
    are out of scope here — those flow through WooCommerce.
    """
    try:
        from app.models import Player, Season
        from app.models.wallet import WalletPass, WalletPassType, create_pub_league_pass

        pub_type = WalletPassType.get_pub_league()
        if not pub_type:
            return {'success': False, 'error': 'Pub League pass type not configured'}

        if season_id:
            season = session.query(Season).get(season_id)
        else:
            season = session.query(Season).filter_by(
                league_type='Pub League', is_current=True
            ).first()
        if not season:
            return {'success': False, 'error': 'No current Pub League season'}

        # Active players with a user account.
        players = session.query(Player).filter(
            Player.is_current_player.is_(True),
            Player.user_id.isnot(None),
        ).all()

        created = 0
        skipped = 0
        skipped_no_team = 0
        for p in players:
            has_team = (p.primary_team is not None) or (
                getattr(p, 'teams', None) and len(p.teams) > 0
            )
            if not has_team:
                skipped_no_team += 1
                continue

            existing = session.query(WalletPass).filter(
                WalletPass.user_id == p.user_id,
                WalletPass.pass_type_id == pub_type.id,
                WalletPass.status == 'active',
            ).first()
            if existing:
                skipped += 1
                continue

            wp = create_pub_league_pass(p, season)
            session.add(wp)
            created += 1

        logger.info(
            f"WalletPass backfill: created {created}, skipped {skipped} "
            f"(existing), skipped {skipped_no_team} (no team); season={season.name}"
        )
        return {
            'success': True,
            'created': created,
            'skipped': skipped,
            'skipped_no_team': skipped_no_team,
            'season': season.name,
        }
    except Exception as e:
        logger.error(f"WalletPass backfill failed: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


@celery_task(
    name='app.tasks.check_in_tasks.generate_check_in_tokens_for_upcoming_matches',
    bind=True,
    queue='celery',
    max_retries=1,
)
def generate_check_in_tokens_for_upcoming_matches(self, session, days: int = 14):
    """Ensure every match in the next `days` days has an active venue token.

    Idempotent — uses MatchCheckInToken.get_or_create_for_match. Skips
    matches that already have one. Safe to run repeatedly.
    """
    try:
        from app.models import Match, MatchCheckInToken
        from app.models.ecs_fc import EcsFcMatch

        today = datetime.utcnow().date()
        horizon = today + timedelta(days=days)

        created = 0
        skipped = 0

        # Pub league
        pl_matches = session.query(Match).filter(
            Match.date >= today, Match.date <= horizon
        ).all()
        for m in pl_matches:
            existing = MatchCheckInToken.find_active_for_match('pub_league', m.id)
            if existing:
                skipped += 1
                continue
            ct = MatchCheckInToken(
                token=MatchCheckInToken.generate_token(),
                match_id=m.id,
                league_type='pub_league',
            )
            session.add(ct)
            created += 1

        # ECS FC
        ecs_matches = session.query(EcsFcMatch).filter(
            EcsFcMatch.match_date >= today, EcsFcMatch.match_date <= horizon
        ).all()
        for m in ecs_matches:
            existing = MatchCheckInToken.find_active_for_match('ecs_fc', m.id)
            if existing:
                skipped += 1
                continue
            ct = MatchCheckInToken(
                token=MatchCheckInToken.generate_token(),
                match_id=m.id,
                league_type='ecs_fc',
            )
            session.add(ct)
            created += 1

        logger.info(
            f"Check-in token backfill: created {created}, skipped {skipped} (existing); "
            f"window={days} days"
        )
        return {
            'success': True,
            'created': created,
            'skipped': skipped,
            'days': days,
        }
    except Exception as e:
        logger.error(f"Check-in token backfill failed: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}
