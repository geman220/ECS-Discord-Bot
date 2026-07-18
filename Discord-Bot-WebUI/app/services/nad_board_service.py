# app/services/nad_board_service.py

"""
NAD Board service — single source of truth for "who is a NAD".

A NAD ("Newly Acquired Drinker") is an *approved* player in their FIRST league
season. Both the mobile API (`GET /api/v1/admin/nad-board`), the admin-panel web
board, and the Discord `/nads` command derive their list from here so the three
front-ends can never drift apart (this codebase has been bitten by parallel
calculators before).

Derivation for a target season S:
    approved player (User.approval_status == 'approved') who is NEW — has no Pub
    League PlayerTeamSeason in a season that started before S — and who belongs
    to S: either has a PlayerTeamSeason in S (drafted) OR, when S is the current
    season, is an active current player not yet drafted (team_id null — the
    pre-draft pool coaches most want to scout).

Visibility:
    Admins (Pub League / Global) see every NAD. Coaches see the shared pre-draft
    pool (unassigned NADs) plus NADs already assigned to a team in a league they
    coach.
"""

import logging

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.models import User, Player, Season
from app.models.players import PlayerTeamSeason, Team, PlayerAdminNote, player_teams
from app.constants.positions import label_for, to_label_array

logger = logging.getLogger(__name__)

ADMIN_ROLE_NAMES = {'Global Admin', 'Pub League Admin'}


def current_pub_league_season(session):
    """Latest current Pub League season (one is_current row exists per league_type)."""
    return session.query(Season).filter(
        Season.league_type == 'Pub League',
        Season.is_current == True  # noqa: E712
    ).order_by(Season.start_date.desc().nullslast()).first()


def compute_nad_board(session, *, season_id=None, search='', limit=100, viewer_user_id=None):
    """Compute the NAD board for a season, scoped to the viewer.

    Args:
        session: an open DB session.
        season_id: target season id; defaults to the current Pub League season.
        search: case-insensitive name substring filter.
        limit: max NADs returned (already-capped by the caller if needed).
        viewer_user_id: the requesting user's id. Admins see all; coaches are
            scoped to unassigned NADs + NADs in a league they coach. Pass None
            for unscoped/full visibility (e.g. internal bot calls).

    Returns:
        dict: {season_id, season_name, team_nad_counts, nads: [...]}
    """
    # --- resolve target season ---
    target_season = session.query(Season).get(season_id) if season_id else current_pub_league_season(session)
    if not target_season:
        return {'season_id': None, 'season_name': None, 'team_nad_counts': {}, 'nads': []}

    is_current_target = bool(target_season.is_current)

    # --- prior Pub League seasons (a NAD has none) ---
    prior_q = session.query(Season.id).filter(
        Season.league_type == 'Pub League', Season.id != target_season.id
    )
    if target_season.start_date is not None:
        prior_q = prior_q.filter(
            (Season.start_date < target_season.start_date) | (Season.start_date.is_(None))
        )
    else:
        prior_q = prior_q.filter(Season.id < target_season.id)
    prior_season_ids = [sid for (sid,) in prior_q.all()]

    # --- players assigned to a team in the target season (gives their team) ---
    target_team_by_player = {}
    for pid, tid in session.query(
        PlayerTeamSeason.player_id, PlayerTeamSeason.team_id
    ).filter(PlayerTeamSeason.season_id == target_season.id).all():
        target_team_by_player[pid] = tid

    candidate_ids = set(target_team_by_player.keys())

    # For the CURRENT season, also surface approved active players not yet drafted.
    if is_current_target:
        for (pid,) in session.query(Player.id).join(
            User, Player.user_id == User.id
        ).filter(
            Player.is_current_player == True,  # noqa: E712
            User.approval_status == 'approved'
        ).all():
            candidate_ids.add(pid)

    # Drop anyone who played a prior Pub League season — not new.
    if prior_season_ids and candidate_ids:
        returning = session.query(PlayerTeamSeason.player_id).filter(
            PlayerTeamSeason.player_id.in_(candidate_ids),
            PlayerTeamSeason.season_id.in_(prior_season_ids)
        ).distinct().all()
        candidate_ids.difference_update(pid for (pid,) in returning)

    if not candidate_ids:
        return {
            'season_id': target_season.id, 'season_name': target_season.name,
            'team_nad_counts': {}, 'nads': []
        }

    # --- viewer scoping: admin sees all, coach is division/pool scoped ---
    is_admin = True
    coach_league_ids = set()
    if viewer_user_id is not None:
        user = session.query(User).get(viewer_user_id)
        role_names = {r.name for r in user.roles} if user else set()
        is_admin = bool(role_names & ADMIN_ROLE_NAMES)
        if not is_admin and user is not None:
            coach_pid = getattr(getattr(user, 'player', None), 'id', None)
            if coach_pid:
                coach_league_ids = {
                    lid for (lid,) in session.query(Team.league_id).join(
                        player_teams, player_teams.c.team_id == Team.id
                    ).filter(
                        player_teams.c.player_id == coach_pid,
                        player_teams.c.is_coach == True  # noqa: E712
                    ).distinct().all()
                }

    # --- fetch candidate players (approved only) ---
    players_q = session.query(Player).join(User, Player.user_id == User.id).filter(
        Player.id.in_(candidate_ids),
        User.approval_status == 'approved'
    )
    if search:
        players_q = players_q.filter(Player.name.ilike(f'%{search}%'))
    candidate_players = players_q.options(joinedload(Player.user)).order_by(Player.id.desc()).all()

    # --- team names/leagues for referenced teams ---
    team_ids = {tid for tid in target_team_by_player.values() if tid}
    teams_map = {}
    if team_ids:
        for tid, tname, tleague in session.query(
            Team.id, Team.name, Team.league_id
        ).filter(Team.id.in_(team_ids)).all():
            teams_map[tid] = {'name': tname, 'league_id': tleague}

    # --- apply coach visibility, then cap ---
    visible_players = []
    for p in candidate_players:
        tid = target_team_by_player.get(p.id)
        if not is_admin and tid is not None:
            tinfo = teams_map.get(tid)
            if not tinfo or tinfo['league_id'] not in coach_league_ids:
                continue  # assigned outside this coach's division
        visible_players.append(p)
        if len(visible_players) >= limit:
            break

    # --- note counts in one grouped query (no N+1) ---
    vis_ids = [p.id for p in visible_players]
    note_counts = dict(
        session.query(PlayerAdminNote.player_id, func.count(PlayerAdminNote.id))
        .filter(PlayerAdminNote.player_id.in_(vis_ids))
        .group_by(PlayerAdminNote.player_id).all()
    ) if vis_ids else {}

    nads = []
    team_nad_counts = {}
    for p in visible_players:
        tid = target_team_by_player.get(p.id)
        tinfo = teams_map.get(tid) if tid else None
        if tid:
            team_nad_counts[str(tid)] = team_nad_counts.get(str(tid), 0) + 1
        nads.append({
            'type': 'player',
            'id': p.id,                      # use with /admin/players/<id>/notes + edits
            'user_id': p.user_id,
            'name': p.name,
            'profile_picture_url': p.profile_picture_url,
            'pronouns': p.pronouns,
            'favorite_position': label_for(p.favorite_position),
            'other_positions': to_label_array(p.other_positions),
            'positions_not_to_play': to_label_array(p.positions_not_to_play),
            'frequency_play_goal': p.frequency_play_goal,
            'jersey_size': p.jersey_size,
            'team_id': tid,
            'team_name': tinfo['name'] if tinfo else None,
            'note_count': note_counts.get(p.id, 0),
            'created_at': (
                p.created_at.isoformat() if p.created_at
                else (p.user.created_at.isoformat() if p.user and p.user.created_at else None)
            ),
            'notes_endpoint': f'/api/v1/admin/players/{p.id}/notes',
        })

    return {
        'season_id': target_season.id,
        'season_name': target_season.name,
        'team_nad_counts': team_nad_counts,
        'nads': nads,
    }
