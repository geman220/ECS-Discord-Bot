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
