# app/services/draft_queue_service.py

"""
Draft queue ("bookmark") service — a coach's private watchlist of players they
are considering drafting.

Shared by the web endpoints (app/draft_enhanced.py) and the mobile API
(app/mobile_api/draft.py) so both platforms see the same queue.

Semantics:
- Scoped per (user, season, league): co-coaches of the same team each keep
  their own queue, and a user coaching in two leagues keeps separate queues.
- Rows are NOT deleted when a player is drafted — reads filter out players
  already on a team in the league. An undo/remove puts the player straight
  back into every queue that held them.
"""

import logging

from sqlalchemy import func, and_, exists

from app.models import DraftQueueEntry, Player, Team, player_teams, player_league
from app.models.ecs_fc import is_ecs_fc_league

logger = logging.getLogger(__name__)

# Sanity cap — a queue is a shortlist, not a second player pool.
MAX_QUEUE_SIZE = 50


def _drafted_player_ids(session, league_id):
    """Player ids already on a team in this league (i.e. drafted).

    ECS FC leagues allow multi-team membership — a player on one team is still
    draftable to another (every pick path exempts ECS FC from the
    already-drafted guard), so nobody counts as 'drafted' for queue purposes.
    """
    if is_ecs_fc_league(league_id):
        return set()
    rows = session.query(player_teams.c.player_id).join(
        Team, Team.id == player_teams.c.team_id
    ).filter(Team.league_id == league_id).all()
    return {r[0] for r in rows}


def _player_in_league(session, player, league_id):
    """Same eligibility predicate the draft pool uses (primary league OR
    player_league membership) — keeps cross-league bookmarks out."""
    if player.primary_league_id == league_id:
        return True
    return session.query(
        exists().where(and_(
            player_league.c.player_id == player.id,
            player_league.c.league_id == league_id,
        ))
    ).scalar()


def get_queue(session, user_id, league):
    """The user's queue for a league, ordered, with drafted players filtered out.

    Returns a list of dicts ready for JSON:
    [{player_id, name, favorite_position, profile_picture_url, sort_order}]
    """
    drafted = _drafted_player_ids(session, league.id)
    rows = (
        session.query(DraftQueueEntry, Player)
        .join(Player, Player.id == DraftQueueEntry.player_id)
        .filter(
            DraftQueueEntry.user_id == user_id,
            DraftQueueEntry.season_id == league.season_id,
            DraftQueueEntry.league_id == league.id,
        )
        .order_by(DraftQueueEntry.sort_order.asc(), DraftQueueEntry.id.asc())
        .all()
    )
    return [
        {
            'player_id': p.id,
            'name': p.name,
            'favorite_position': p.favorite_position,
            'profile_picture_url': p.profile_picture_url,
            'sort_order': e.sort_order,
        }
        for (e, p) in rows
        if p.id not in drafted
    ]


def add_to_queue(session, user_id, league, player_id):
    """Bookmark a player. Idempotent. Returns (ok, error_message)."""
    player = session.query(Player).filter(Player.id == player_id).first()
    if not player:
        return False, 'Player not found'
    if not player.is_current_player:
        return False, 'Player is not active this season'
    if not _player_in_league(session, player, league.id):
        return False, 'Player is not in this league'
    if player_id in _drafted_player_ids(session, league.id):
        return False, 'Player has already been drafted'

    existing = session.query(DraftQueueEntry).filter_by(
        user_id=user_id, season_id=league.season_id,
        league_id=league.id, player_id=player_id,
    ).first()
    if existing:
        return True, None

    count = session.query(func.count(DraftQueueEntry.id)).filter_by(
        user_id=user_id, season_id=league.season_id, league_id=league.id,
    ).scalar() or 0
    if count >= MAX_QUEUE_SIZE:
        return False, f'Queue is full (max {MAX_QUEUE_SIZE} players)'

    next_order = session.query(func.coalesce(func.max(DraftQueueEntry.sort_order), 0)).filter_by(
        user_id=user_id, season_id=league.season_id, league_id=league.id,
    ).scalar() + 1
    session.add(DraftQueueEntry(
        user_id=user_id, season_id=league.season_id, league_id=league.id,
        player_id=player_id, sort_order=next_order,
    ))
    return True, None


def remove_from_queue(session, user_id, league, player_id):
    """Un-bookmark a player. Idempotent; returns True if a row was deleted."""
    deleted = session.query(DraftQueueEntry).filter_by(
        user_id=user_id, season_id=league.season_id,
        league_id=league.id, player_id=player_id,
    ).delete(synchronize_session=False)
    return bool(deleted)


def reorder_queue(session, user_id, league, player_ids):
    """Apply a new order. player_ids is the full desired order (top first);
    ids not in the user's queue are ignored, queued ids missing from the list
    keep their relative order after the reordered ones."""
    entries = session.query(DraftQueueEntry).filter_by(
        user_id=user_id, season_id=league.season_id, league_id=league.id,
    ).order_by(DraftQueueEntry.sort_order.asc(), DraftQueueEntry.id.asc()).all()
    by_player = {e.player_id: e for e in entries}

    order = 0
    seen = set()
    for pid in player_ids:
        entry = by_player.get(pid)
        if entry and pid not in seen:
            order += 1
            entry.sort_order = order
            seen.add(pid)
    for entry in entries:  # anything the client didn't mention keeps its place at the end
        if entry.player_id not in seen:
            order += 1
            entry.sort_order = order
