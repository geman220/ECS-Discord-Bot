# app/services/substitute_reconcile_service.py

"""
Substitute reconciliation service.

Joins a schedule-generated availability poll (DiscordPoll.poll_kind ==
'availability', with a slot_map that carries real match_ids per answer) against
the OPEN team substitute requests, so a coordinator sees, per request, exactly
which poll voters are available for THAT match.

This is the read-only data layer behind the reconcile view (Phase 2b). It does
NOT contact or assign anyone — assignment still happens through the existing
unified board / notification service (Phase 3 adds one-click contact here).

Eligibility is re-derived, not trusted from the vote: a poll pings both the
Classic and Premier sub roles into one #pl-subs poll, so a voter is only a real
candidate for a request if they actually hold that league's Sub role
(get_eligible_players). Voters who lack any referenced sub role, and voters with
no linked Player, are surfaced rather than silently dropped.
"""

import logging

from app.models.core import Season
from app.models.players import Player, player_teams
from app.models.discord_polls import DiscordPoll, DiscordPollVote
from app.models.substitutes import SubstituteRequest, SubstituteResponse, get_eligible_players
from app.services.unified_substitute_service import get_unified_requests

logger = logging.getLogger(__name__)


def build_poll_reconcile(session, poll_id):
    """
    Build the reconcile payload for one availability poll.

    Returns None if the poll doesn't exist. Otherwise a dict:
        {
          poll: {id, title, match_date, message_url, kind},
          season_stale: bool,           # poll is from a non-current season
          voters_total: int,
          requests: [ {id, team_name, league_type, match_label, match_date,
                       needed, assigned, positions,
                       candidates: [{player_id, name, pronouns, eligible,
                                     conflicts: [str], contact}]} ],
          unmapped: [discord_id],       # voted but no linked Player
          ineligible_voters: [{player_id, name, discord_id}],  # voted, no sub role
        }
    """
    poll = session.query(DiscordPoll).get(poll_id)
    if not poll:
        return None

    slot_map = poll.slot_map or {}

    current = session.query(Season).filter_by(
        league_type='Pub League', is_current=True
    ).first()
    season_stale = bool(poll.season_id and current and poll.season_id != current.id)

    # --- Current votes (removed_at IS NULL) grouped by answer_id ---
    votes = session.query(DiscordPollVote).filter(
        DiscordPollVote.poll_id == poll.id,
        DiscordPollVote.removed_at.is_(None),
    ).all()
    voters_by_answer = {}   # str(answer_id) -> set(discord_user_id)
    all_voter_ids = set()
    for v in votes:
        voters_by_answer.setdefault(str(v.answer_id), set()).add(v.discord_user_id)
        all_voter_ids.add(v.discord_user_id)

    # --- Map discord_user_id -> Player (surface the unmapped) ---
    player_by_discord = {}
    if all_voter_ids:
        for p in session.query(Player).filter(Player.discord_id.in_(all_voter_ids)).all():
            if p.discord_id:
                player_by_discord[str(p.discord_id)] = p
    unmapped = sorted(all_voter_ids - set(player_by_discord.keys()))

    # --- Eligibility sets per league_type referenced in the slot_map ---
    league_types = {b.get('league_type') for b in slot_map.values() if b.get('league_type')}
    eligible_ids_by_league = {
        lt: {p.id for p in get_eligible_players(lt, session=session)}
        for lt in league_types
    }

    # --- Map each covered match_id -> the buckets (answer/league) covering it ---
    poll_match_ids = set()
    buckets_by_match = {}   # match_id -> [(answer_id_str, bucket), ...]
    for aid_str, bucket in slot_map.items():
        for mid in (bucket.get('match_ids') or []):
            poll_match_ids.add(int(mid))
            buckets_by_match.setdefault(int(mid), []).append((aid_str, bucket))

    # --- Open Pub League requests intersecting the poll's matches ---
    # league='pub_league' so ECS FC rows can't eat into the 100-item page cap.
    items, _total, _page, _pages = get_unified_requests(
        session, league='pub_league', status='active', page=1, per_page=100
    )
    req_items = [it for it in items if it.get('match_id') in poll_match_ids]

    request_ids = [it['id'] for it in req_items]
    team_ids = {it['team_id'] for it in req_items if it.get('team_id')}

    # roster (players + coaches) per team, for conflict-of-interest flags
    roster_by_team = {}
    if team_ids:
        rows = session.execute(
            player_teams.select().where(player_teams.c.team_id.in_(team_ids))
        ).fetchall()
        for r in rows:
            roster_by_team.setdefault(r.team_id, set()).add(r.player_id)

    # existing responses + requesters, for contact status / self-request flag
    resp_map = {}            # (request_id, player_id) -> is_available (True/False/None)
    requester_by_request = {}
    if request_ids:
        for sr in session.query(SubstituteRequest).filter(
            SubstituteRequest.id.in_(request_ids)
        ).all():
            requester_by_request[sr.id] = sr.requested_by
        for r in session.query(SubstituteResponse).filter(
            SubstituteResponse.request_id.in_(request_ids)
        ).all():
            resp_map[(r.request_id, r.player_id)] = r.is_available

    requests_out = []
    for it in req_items:
        mid = it['match_id']
        lt = it.get('league_type') or 'Classic'
        eligible_ids = eligible_ids_by_league.get(lt, set())
        roster = roster_by_team.get(it.get('team_id'), set())
        requested_by_user = requester_by_request.get(it['id'])

        # voters available for THIS match in THIS league
        cand_discord = set()
        for aid_str, bucket in buckets_by_match.get(mid, []):
            if bucket.get('league_type') != lt:
                continue
            cand_discord |= voters_by_answer.get(aid_str, set())

        candidates = []
        for duid in sorted(cand_discord):
            p = player_by_discord.get(duid)
            if not p:
                continue  # unmapped voters surfaced globally
            conflicts = []
            if p.id in roster:
                conflicts.append('plays/coaches this team')
            if requested_by_user and p.user_id == requested_by_user:
                conflicts.append('is the requester')
            if (it['id'], p.id) in resp_map:
                avail = resp_map[(it['id'], p.id)]
                contact = 'available' if avail is True else ('declined' if avail is False else 'pending')
            else:
                contact = 'not_contacted'
            candidates.append({
                'player_id': p.id,
                'name': p.name,
                'pronouns': p.pronouns,
                'eligible': p.id in eligible_ids,
                'conflicts': conflicts,
                'contact': contact,
            })
        # eligible & conflict-free first, then by name
        candidates.sort(key=lambda c: (not c['eligible'], bool(c['conflicts']), (c['name'] or '')))

        requests_out.append({
            'id': it['id'],
            'team_name': it.get('team_name'),
            'league_type': lt,
            'match_label': it.get('match_label'),
            'match_date': it.get('match_date'),
            'needed': it.get('needed'),
            'assigned': it.get('assigned'),
            'positions': it.get('positions'),
            'candidates': candidates,
        })

    # voters who answered but hold none of the referenced sub roles
    all_eligible = set().union(*eligible_ids_by_league.values()) if eligible_ids_by_league else set()
    ineligible_voters = [
        {'player_id': p.id, 'name': p.name, 'discord_id': duid}
        for duid, p in player_by_discord.items()
        if p.id not in all_eligible
    ]

    return {
        'poll': {
            'id': poll.id,
            'title': poll.title,
            'match_date': poll.match_date,
            'message_url': poll.discord_message_url,
            'kind': poll.poll_kind,
        },
        'season_stale': season_stale,
        'voters_total': len(all_voter_ids),
        'requests': requests_out,
        'unmapped': unmapped,
        'ineligible_voters': ineligible_voters,
    }
