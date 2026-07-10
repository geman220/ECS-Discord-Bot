# app/wallet_pass/services/auto_refresh.py

"""
Auto-refresh wallet passes when relevant data changes.

Apple Wallet keeps installed passes fresh by polling our PassKit web
service after we send an empty APNs push. This module wires the trigger
side: detects when DB rows that affect pass content change, then kicks
async tasks that bump WalletPass.updated_at and push.

Watched signals:
    Player.profile_picture_url     -> thumbnail (auto-injected on pub_league)
    Player.name                    -> member_name
    Player.primary_team_id         -> team_name on the pass
    Player.is_current_player       -> if flips to False, pass is voided + final push
    Match.date / Match.time        -> relevantDate (if this match is the next one)
    Match.location/lat/lng         -> location entry in pass.json
    EcsFcMatch.match_date / .match_time -> same

Implementation:
    SQLAlchemy `before_flush` captures the dirty Player/Match instances
    and remembers what changed. `after_commit` then fans out async Celery
    tasks (one per affected entity). Listeners are session-level so they
    fire regardless of which session triggered the change.

Why after_commit, not before:
    - Avoids firing on rolled-back transactions
    - Lets the task read the committed row freely (no risk of dirty reads)
    - APNs latency doesn't block the writing transaction
"""

import logging
from typing import Set, Dict, List, Any

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import get_history

logger = logging.getLogger(__name__)


# Columns whose changes should trigger a wallet refresh for the affected player.
PLAYER_PASS_COLUMNS: Set[str] = {
    'profile_picture_url',
    'name',
    'primary_team_id',
    'is_current_player',
    'jersey_number',
}

# Pub League Match: home/away teams + when/where it kicks off.
MATCH_PASS_COLUMNS: Set[str] = {
    'date',
    'time',
    'location',
    'latitude',
    'longitude',
    'home_team_id',
    'away_team_id',
}

# ECS FC Match: single team + when/where.
ECS_FC_MATCH_PASS_COLUMNS: Set[str] = {
    'match_date',
    'match_time',
    'location',
    'latitude',
    'longitude',
    'team_id',
}


def _stash(session: Session) -> Dict[str, List[Any]]:
    """Per-session bag for accumulating refresh tasks until commit."""
    if not hasattr(session, '_wallet_refresh_pending'):
        session._wallet_refresh_pending = {
            'players': [],     # list of {player_id, columns, is_current_player}
            'matches': [],     # list of {league_type, match_id}
        }
    return session._wallet_refresh_pending


def _attribute_changed(instance, attr_name: str) -> bool:
    """True if this attribute has unsaved changes vs the row in DB."""
    try:
        hist = get_history(instance, attr_name)
        return hist.has_changes()
    except Exception:
        return False


def _attribute_old_new(instance, attr_name: str):
    """Return (old, new) for the attribute, or (None, None) on error."""
    try:
        hist = get_history(instance, attr_name)
        old = hist.deleted[0] if hist.deleted else None
        new = hist.added[0] if hist.added else None
        return old, new
    except Exception:
        return None, None


@event.listens_for(Session, 'before_flush')
def _capture_wallet_relevant_changes(session, flush_context, instances):
    """Walk session.dirty for relevant model changes. Stash for after_commit."""
    # Lazy imports — model registry isn't ready at module import time when
    # this file is loaded by app init.
    try:
        from app.models import Player, Match
        from app.models.ecs_fc import EcsFcMatch
    except Exception:
        return

    bag = _stash(session)

    for obj in session.dirty:
        if isinstance(obj, Player):
            changed = [c for c in PLAYER_PASS_COLUMNS if _attribute_changed(obj, c)]
            if not changed:
                continue
            # Detect is_current_player False transition specifically.
            became_inactive = False
            if 'is_current_player' in changed:
                old, new = _attribute_old_new(obj, 'is_current_player')
                became_inactive = (old is True or old is None) and new is False
            bag['players'].append({
                'player_id': obj.id,
                'columns': changed,
                'became_inactive': became_inactive,
            })

        elif isinstance(obj, Match):
            changed = [c for c in MATCH_PASS_COLUMNS if _attribute_changed(obj, c)]
            if changed and obj.id is not None:
                bag['matches'].append({'league_type': 'pub_league', 'match_id': obj.id})

        elif isinstance(obj, EcsFcMatch):
            changed = [c for c in ECS_FC_MATCH_PASS_COLUMNS if _attribute_changed(obj, c)]
            if changed and obj.id is not None:
                bag['matches'].append({'league_type': 'ecs_fc', 'match_id': obj.id})


@event.listens_for(Session, 'after_commit')
def _fire_wallet_refresh_tasks(session):
    bag = getattr(session, '_wallet_refresh_pending', None)
    if not bag:
        return
    # Clear before dispatch so a downstream commit (e.g. inside the task)
    # doesn't double-fire.
    session._wallet_refresh_pending = {'players': [], 'matches': []}

    if not (bag['players'] or bag['matches']):
        return

    try:
        from app.tasks.wallet_refresh_tasks import (
            push_wallet_refresh_batch,
            push_wallet_refresh_for_match,
        )
    except Exception as e:
        logger.warning(f"wallet auto-refresh: tasks not available: {e}")
        return

    # Coalesce per-player refreshes into ONE batched task instead of one task per
    # player — a bulk commit (e.g. approving/deactivating hundreds of users) would
    # otherwise fan out hundreds of wallet-refresh tasks.
    seen_players = set()
    players_payload = []
    for item in bag['players']:
        pid = item.get('player_id')
        if not pid or pid in seen_players:
            continue
        seen_players.add(pid)
        players_payload.append({'player_id': pid, 'void': item.get('became_inactive', False)})
    if players_payload:
        try:
            push_wallet_refresh_batch.delay(players=players_payload, reason='player_attr_change')
        except Exception as e:
            logger.warning(f"wallet auto-refresh: failed to enqueue batch for {len(players_payload)} players: {e}")

    seen_matches = set()
    for item in bag['matches']:
        key = (item['league_type'], item['match_id'])
        if key in seen_matches:
            continue
        seen_matches.add(key)
        try:
            push_wallet_refresh_for_match.delay(
                league_type=item['league_type'],
                match_id=item['match_id'],
            )
        except Exception as e:
            logger.warning(f"wallet auto-refresh: failed to enqueue for match {key}: {e}")


@event.listens_for(Session, 'after_rollback')
def _drop_pending_on_rollback(session):
    """Don't push refreshes for changes that didn't commit."""
    if hasattr(session, '_wallet_refresh_pending'):
        session._wallet_refresh_pending = {'players': [], 'matches': []}


def install_listeners():
    """Idempotent install marker — importing this module already registers
    the listeners (decorator side-effects). This function exists so the app
    init can call it explicitly + log that auto-refresh is on."""
    logger.info("Wallet auto-refresh listeners installed")
