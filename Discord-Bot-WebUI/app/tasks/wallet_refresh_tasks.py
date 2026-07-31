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
        from app.wallet_pass.services.push_service import (
            mark_wallet_pass_updated, push_wallet_pass,
        )

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

        # Bump every pass, then COMMIT, and only then push. Pushing inside the
        # loop raced the commit: the device calls back within ~1s on another
        # worker, read the un-committed updated_at, and dropped the update as a
        # "spurious push". See push_wallet_pass() for the full contract.
        results = []
        for wp in passes:
            if void:
                # Mark voided BEFORE pushing so the regenerated pass reflects it.
                wp.void(reason=reason or 'player deactivated')
                results.append({'pass_id': wp.id, 'voided': True})
            mark_wallet_pass_updated(wp)
        session.commit()

        for wp in passes:
            r = push_wallet_pass(wp)
            results.append({'pass_id': wp.id, 'apple': r.get('apple'), 'google': r.get('google')})
        logger.info(f"wallet refresh for player {player_id}: {len(passes)} pass(es), reason={reason or 'attr_change'}")
        return {'success': True, 'count': len(passes), 'results': results}
    except Exception as e:
        logger.error(f"push_wallet_refresh_for_player({player_id}) failed: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


@celery_task(
    name='app.tasks.wallet_refresh_tasks.push_wallet_refresh_batch',
    bind=True,
    queue='celery',
    max_retries=2,
)
def push_wallet_refresh_batch(self, session, players=None, reason=''):
    """Refresh (or void) wallet passes for MANY players in one task.

    Used by the after_commit listener so a bulk operation (e.g. approving or
    deactivating hundreds of users in one transaction) dispatches a single task
    instead of one push_wallet_refresh_for_player task per player. `players` is a
    list of {'player_id': int, 'void': bool}. Each player is handled independently
    so one failure doesn't abort the rest.
    """
    from app.models import Player
    from app.models.wallet import WalletPass
    from app.wallet_pass.services.push_service import (
        mark_wallet_pass_updated, push_wallet_pass,
    )

    players = players or []
    total_passes = 0
    failed_players = 0
    # Commit PER PLAYER, then push everything once the loop is done.
    #
    # Both halves of that matter. Committing per player keeps one bad row from
    # taking the batch down with it: a single `session.rollback()` discards every
    # uncommitted bump in the transaction, so accumulating 500 players' bumps and
    # committing once means a failure at #300 silently wipes 1-299 and nothing
    # retries. Pushing only after the commit is the Apple ordering contract —
    # see push_wallet_pass().
    to_push = []
    for entry in players:
        pid = entry.get('player_id')
        if not pid:
            continue
        void = entry.get('void', False)
        try:
            player = session.query(Player).get(pid)
            if not player:
                continue
            passes = session.query(WalletPass).filter(
                WalletPass.status == 'active',
                (WalletPass.player_id == pid) |
                ((WalletPass.player_id.is_(None)) & (WalletPass.user_id == player.user_id))
            ).all()
            for wp in passes:
                if void:
                    wp.void(reason=reason or 'player deactivated')
                mark_wallet_pass_updated(wp)
            session.commit()
            # Only queue for push once this player's bump is durable.
            to_push.extend(passes)
            total_passes += len(passes)
        except Exception as e:
            logger.error(f"wallet batch refresh for player {pid} failed: {e}", exc_info=True)
            failed_players += 1
            try:
                session.rollback()
            except Exception:
                pass

    for wp in to_push:
        push_wallet_pass(wp)
    logger.info(
        f"wallet batch refresh: {len(players)} player(s), {total_passes} pass(es), "
        f"{failed_players} failed, reason={reason or 'attr_change'}"
    )
    return {
        'success': failed_players == 0,
        'players': len(players),
        'passes': total_passes,
        'failed_players': failed_players,
    }


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
        from app.wallet_pass.services.push_service import (
            mark_wallet_pass_updated, push_wallet_pass,
        )

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

        # Bump-all -> commit -> push-all; see push_wallet_pass().
        for wp in passes:
            mark_wallet_pass_updated(wp)
        session.commit()
        for wp in passes:
            push_wallet_pass(wp)
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
        from app.wallet_pass.services.push_service import (
            mark_wallet_pass_updated, push_wallet_pass,
        )
        from app.wallet_pass.generators.apple import _get_next_match_relevance

        passes = session.query(WalletPass).filter(
            WalletPass.status == 'active',
            WalletPass.player_id.isnot(None),
        ).all()

        refreshed = 0
        skipped = 0
        to_push = []
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
            mark_wallet_pass_updated(wp)
            to_push.append(wp)
            refreshed += 1

        # ONE commit for the whole sweep, then the nudges. This loop is what
        # produced the 04:00 "Device received spurious push ... returned no
        # serial numbers" entries: it pushed every device up front and
        # committed minutes later, so every callback lost the race.
        session.commit()
        for wp in to_push:
            push_wallet_pass(wp)
        logger.info(f"daily relevantDate refresh: refreshed={refreshed}, skipped={skipped}")
        return {'success': True, 'refreshed': refreshed, 'skipped': skipped}
    except Exception as e:
        logger.error(f"refresh_relevant_dates_daily failed: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}
