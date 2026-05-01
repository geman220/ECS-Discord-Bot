# app/tasks/wallet_refresh_tasks.py

"""
Wallet pass refresh tasks.

Async work kicked from `app/wallet_pass/services/auto_refresh.py` listeners:
- push_wallet_refresh_for_player: bumps + pushes the player's active passes
- push_wallet_refresh_for_match: bumps + pushes passes for everyone on a match's roster
- refresh_relevant_dates_daily: nightly sweep that updates relevantDate when
  the next-upcoming match has changed (e.g. previous match completed).
"""

import logging
from datetime import datetime

from app.decorators import celery_task

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.wallet_refresh_tasks.push_wallet_refresh_for_player',
    bind=True,
    queue='celery',
    max_retries=2,
)
def push_wallet_refresh_for_player(self, session, player_id: int, void: bool = False, reason: str = ''):
    """Refresh (or void) every active WalletPass row tied to this player.

    Called by the SQLAlchemy after_commit listener when a wallet-relevant
    Player column changed.
    """
    try:
        from app.models import Player
        from app.models.wallet import WalletPass
        from app.wallet_pass.services.push_service import trigger_wallet_refresh

        player = session.query(Player).get(player_id)
        if not player:
            return {'success': False, 'error': 'player not found'}

        # Active passes for this player (player_id link OR via user_id).
        passes = session.query(WalletPass).filter(
            WalletPass.status == 'active',
            (WalletPass.player_id == player_id) |
            ((WalletPass.player_id.is_(None)) & (WalletPass.user_id == player.user_id))
        ).all()

        if not passes:
            return {'success': True, 'count': 0, 'note': 'no active passes'}

        results = []
        for wp in passes:
            if void:
                # Mark voided BEFORE pushing so the regenerated pass reflects it.
                wp.void(reason=reason or 'player deactivated')
                session.commit()
                results.append({'pass_id': wp.id, 'voided': True})
            r = trigger_wallet_refresh(wp, commit=False)
            results.append({'pass_id': wp.id, 'apple': r.get('apple'), 'google': r.get('google')})
        session.commit()
        logger.info(f"wallet refresh for player {player_id}: {len(passes)} pass(es), reason={reason or 'attr_change'}")
        return {'success': True, 'count': len(passes), 'results': results}
    except Exception as e:
        logger.error(f"push_wallet_refresh_for_player({player_id}) failed: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


@celery_task(
    name='app.tasks.wallet_refresh_tasks.push_wallet_refresh_for_match',
    bind=True,
    queue='celery',
    max_retries=2,
)
def push_wallet_refresh_for_match(self, session, league_type: str, match_id: int):
    """Refresh wallet passes for everyone on a match's roster.

    Called when a Match row's date/time/location/teams change — those
    affect the embedded relevantDate / location entry on each player's
    pass (when this match is their next upcoming).
    """
    try:
        from app.models import Player, Match
        from app.models.ecs_fc import EcsFcMatch
        from app.models.players import player_teams
        from app.models.wallet import WalletPass
        from app.wallet_pass.services.push_service import trigger_wallet_refresh

        if league_type == 'pub_league':
            match = session.query(Match).get(match_id)
            if not match:
                return {'success': False, 'error': 'match not found'}
            team_ids = [tid for tid in (match.home_team_id, match.away_team_id) if tid]
        elif league_type == 'ecs_fc':
            match = session.query(EcsFcMatch).get(match_id)
            if not match:
                return {'success': False, 'error': 'match not found'}
            team_ids = [match.team_id] if match.team_id else []
        else:
            return {'success': False, 'error': f'unknown league_type {league_type}'}

        if not team_ids:
            return {'success': True, 'count': 0, 'note': 'no team_ids'}

        # Players on either roster. Dedupe via subquery (JSON column on Player
        # blocks SELECT DISTINCT player.*).
        player_ids_q = session.query(player_teams.c.player_id).filter(
            player_teams.c.team_id.in_(team_ids)
        ).distinct()
        passes = session.query(WalletPass).filter(
            WalletPass.status == 'active',
            WalletPass.player_id.in_(player_ids_q)
        ).all()

        for wp in passes:
            trigger_wallet_refresh(wp, commit=False)
        session.commit()
        logger.info(f"wallet refresh for match {league_type}/{match_id}: {len(passes)} pass(es)")
        return {'success': True, 'count': len(passes)}
    except Exception as e:
        logger.error(
            f"push_wallet_refresh_for_match({league_type}/{match_id}) failed: {e}",
            exc_info=True,
        )
        return {'success': False, 'error': str(e)}


@celery_task(
    name='app.tasks.wallet_refresh_tasks.refresh_relevant_dates_daily',
    bind=True,
    queue='celery',
    max_retries=1,
)
def refresh_relevant_dates_daily(self, session):
    """Sweep all active player-linked WalletPass rows once a day.

    For each, recompute the next upcoming match. If different from what
    was baked at last generation (we use updated_at as a proxy — if the
    pass hasn't been regenerated since the last match completed, push a
    refresh so Apple Wallet pulls a fresh .pkpass with the new
    relevantDate). This is the "next match advances after the previous
    one completes" gap-filler.
    """
    try:
        from datetime import timedelta
        from app.models.wallet import WalletPass
        from app.wallet_pass.services.push_service import trigger_wallet_refresh
        from app.wallet_pass.generators.apple import _get_next_match_relevance

        passes = session.query(WalletPass).filter(
            WalletPass.status == 'active',
            WalletPass.player_id.isnot(None),
        ).all()

        refreshed = 0
        skipped = 0
        for wp in passes:
            try:
                next_info = _get_next_match_relevance(wp)
            except Exception as e:
                logger.warning(f"refresh_relevant_dates_daily: next-match lookup failed for pass {wp.id}: {e}")
                skipped += 1
                continue

            # If pass was generated within the last 6 hours, no point pushing
            # — the relevantDate is already current.
            if wp.updated_at and (datetime.utcnow() - wp.updated_at) < timedelta(hours=6):
                skipped += 1
                continue

            # If the next match's kickoff is already past (no upcoming
            # matches), still bump so Apple Wallet drops the stale
            # relevantDate. Otherwise refresh either way to capture any
            # changes since last generation.
            trigger_wallet_refresh(wp, commit=False)
            refreshed += 1

        session.commit()
        logger.info(f"daily relevantDate refresh: refreshed={refreshed}, skipped={skipped}")
        return {'success': True, 'refreshed': refreshed, 'skipped': skipped}
    except Exception as e:
        logger.error(f"refresh_relevant_dates_daily failed: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}
