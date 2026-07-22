# app/services/member_hub_service.py

"""
Member Hub read-model (Phase 2 of the registration-lifecycle overhaul).

Aggregates a single person's whole picture — approval, memberships (role+status per
league_type per season, from the `league_membership` spine), sub status, payment,
Discord state, and quick-profile lineage — for the person-360 admin page. Read-only;
never mutates. Reads the spine (already backfilled + dual-written) so the Hub reflects
the unified model rather than the old scattered booleans.

Design: ~/.claude/plans/registration-lifecycle-overhaul.md  §10.2
"""

import logging

from app.core import db
from app.models import (
    User, Player, Season, Team, LeagueMembership, QuickProfile,
)

logger = logging.getLogger(__name__)

_ROLE_ORDER = {'player': 0, 'coach': 1, 'sub': 2, 'waitlist': 3}
_LANE_LABEL = {'classic': 'Classic', 'premier': 'Premier', 'ecs_fc': 'ECS FC'}


def _sess(session=None):
    if session is not None:
        return session
    try:
        from flask import g
        s = getattr(g, 'db_session', None)
        if s is not None:
            return s
    except Exception:
        pass
    return db.session


def get_member_360(user_id, session=None):
    """Return the full Member Hub view for a user, or None if the user doesn't exist.

    Shape:
      {
        'user': {...approval + account...},
        'player': {...player flags...} | None,
        'current_memberships': [ {league_type, lane_label, role, status, team_id, team_name, ...} ],
        'past_memberships':    [ {..., season_name} ],
        'waitlist': {lane, status} | None,
        'quick_profile': {claim_code, status, ...} | None,
      }
    """
    s = _sess(session)
    user = s.get(User, user_id)
    if user is None:
        return None

    player = user.player  # may be None

    out = {
        'user': {
            'id': user.id,
            'username': user.username,
            'email': getattr(user, 'email', None),
            'is_approved': user.is_approved,
            'is_active': user.is_active,
            'approval_status': user.approval_status,
            'approval_league': user.approval_league,
            'approved_at': user.approved_at.isoformat() if user.approved_at else None,
            'approval_notes': user.approval_notes,
            'roles': [r.name for r in user.roles],
            'waitlist_league': getattr(user, 'waitlist_league', None),
            'waitlist_joined_at': user.waitlist_joined_at.isoformat() if user.waitlist_joined_at else None,
        },
        'player': None,
        'current_memberships': [],
        'past_memberships': [],
        'waitlist': None,
        'quick_profile': None,
        'is_returning': False,
        'stats': None,
        'notes': [],
        'player_notes': None,
    }

    if player is not None:
        out['player'] = {
            'id': player.id,
            'name': player.name,
            'profile_picture_url': player.profile_picture_url,
            'discord_id': player.discord_id,
            'discord_username': getattr(player, 'discord_username', None),
            'discord_in_server': getattr(player, 'discord_in_server', None),
            'is_current_player': player.is_current_player,
            'is_sub': player.is_sub,
            'is_coach': player.is_coach,
            'pronouns': getattr(player, 'pronouns', None),
            'favorite_position': getattr(player, 'favorite_position', None),
            'jersey_size': getattr(player, 'jersey_size', None),
        }

        # Which seasons are current (for the current-vs-past split)
        current_ids = {
            sid for (sid,) in s.query(Season.id).filter(Season.is_current.is_(True)).all()
        }

        rows = (
            s.query(LeagueMembership, Season.name, Team.name)
            .join(Season, Season.id == LeagueMembership.season_id)
            .outerjoin(Team, Team.id == LeagueMembership.team_id)
            .filter(LeagueMembership.player_id == player.id)
            .all()
        )

        def _card(lm, season_name, team_name):
            return {
                'id': lm.id,
                'season_id': lm.season_id,
                'season_name': season_name,
                'league_type': lm.league_type,
                'lane_label': _LANE_LABEL.get(lm.league_type, lm.league_type),
                'role': lm.role,
                'status': lm.status,
                'team_id': lm.team_id,
                'team_name': team_name,
                'needs_reconfirm': lm.needs_reconfirm,
                'last_engaged_at': lm.last_engaged_at.isoformat() if lm.last_engaged_at else None,
                'paid_at': lm.paid_at.isoformat() if lm.paid_at else None,
            }

        current, past = [], []
        for lm, season_name, team_name in rows:
            card = _card(lm, season_name, team_name)
            (current if lm.season_id in current_ids else past).append(card)

        # sort current by role priority then lane; past newest-first by season_id (chronological)
        current.sort(key=lambda c: (_ROLE_ORDER.get(c['role'], 9), c['league_type']))
        past.sort(key=lambda c: c['season_id'], reverse=True)
        out['current_memberships'] = current
        out['past_memberships'] = past

        # Returning vs new: played a prior season, or has any career stats on record.
        has_career = bool(getattr(player, 'career_stats', None))
        out['is_returning'] = bool(past) or has_career

        # Career stats (guarded — never let a stats hiccup blank the whole hub).
        try:
            out['stats'] = {
                'career_goals': player.get_career_goals(),
                'career_assists': player.get_career_assists(),
                'career_yellow': player.get_career_yellow_cards(),
                'career_red': player.get_career_red_cards(),
                'has_data': has_career,
            }
        except Exception:
            logger.exception("member hub: career stats failed for player %s", player.id)
            out['stats'] = {'career_goals': 0, 'career_assists': 0, 'career_yellow': 0,
                            'career_red': 0, 'has_data': False}

        # Admin/coach/NAD notes thread (newest first via the relationship order_by) + the
        # free-text player_notes field.
        out['player_notes'] = getattr(player, 'player_notes', None)
        out['notes'] = [{
            'id': n.id,
            'content': n.content,
            'author': (n.author.username if getattr(n, 'author', None) else 'system'),
            'created_at': n.created_at.strftime('%Y-%m-%d %H:%M') if n.created_at else '',
        } for n in (getattr(player, 'admin_notes', None) or [])]

        # waitlist view derived from a current waitlist membership (user-column fallback runs below,
        # outside this block, so a player-less waitlisted user is still shown as waitlisted)
        # Only an ACTIVE waitlist row counts — a retired row keeps role='waitlist' with a
        # terminal status ('removed' when cleared at a boundary, 'converted' when placed),
        # and must not surface as a live waitlist card.
        wl = next((c for c in current
                   if c['role'] == 'waitlist' and c['status'] in ('waiting', 'offered')), None)
        if wl:
            out['waitlist'] = {
                'lane': wl['league_type'],
                'lane_label': _LANE_LABEL.get(wl['league_type'], wl['league_type']),
                'status': wl['status'],
            }

        # quick-profile lineage (if this player was claimed/linked from a walk-in)
        qp = (s.query(QuickProfile)
              .filter(QuickProfile.claimed_by_player_id == player.id)
              .order_by(QuickProfile.id.desc())
              .first())
        if qp:
            out['quick_profile'] = {
                'id': qp.id,
                'claim_code': qp.claim_code,
                'status': qp.status,
                'player_name': qp.player_name,
            }

    # Waitlist is a USER-level fact — a waitlisted user may have no Player row yet, so
    # this fallback runs regardless of `player`. Normalize the raw stored value
    # ('pub_league_classic' / 'Classic' / 'ecs-fc' / 'not_sure') to the same canonical lane
    # code the spine branch emits, so `waitlist.lane`/`lane_label` are consistent either way.
    if out['waitlist'] is None and getattr(user, 'waitlist_league', None):
        from app.services.league_membership_sync import _norm_league_type
        lane = _norm_league_type(user.waitlist_league)  # None for 'not_sure'
        out['waitlist'] = {
            'lane': lane,
            'lane_label': _LANE_LABEL.get(lane, 'Undecided') if lane else 'Undecided',
            'status': 'waiting',
        }

    return out
