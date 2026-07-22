# app/services/classic_board_service.py

"""
Classic Board Service — canonical single source for the Classic board payload
(web page, mobile GET /api/v1/classic-board, and the rating screen's player
context all derive from compute_classic_board so they can never drift).

Scores in the payload are the FINAL averaged metrics (override -> else coach
average) from classic_rating_service — never per-coach raw rows; the blind
per-coach data has no path through this module.
"""

import logging

from sqlalchemy import func

from sqlalchemy import func as sa_func

from app.attendance_service import AttendanceService
from app.constants.positions import label_for, parse_positions, POSITION_LABELS
from app.models import (
    Player, PlayerAdminNote, PlayerCareerStats, PlayerTeamSeason, Team, player_teams,
)
from app.services import classic_rating_service as rating_service

logger = logging.getLogger(__name__)


def gk_willingness(player):
    """Human-readable goalkeeper willingness from the free-text
    frequency_play_goal field ('' when unset)."""
    return (player.frequency_play_goal or '').strip()


def wants_gk(player):
    """True when the player has any willingness to play goalkeeper — either an
    affirmative frequency answer or Goalkeeper among their positions."""
    freq = gk_willingness(player).lower()
    if freq and freq not in ('no', 'never', 'none', 'n/a', 'na'):
        return True
    positions = parse_positions(player.favorite_position) + parse_positions(player.other_positions)
    return 'goalkeeper' in positions


def _position_labels(raw):
    return [POSITION_LABELS.get(slug, slug) for slug in parse_positions(raw)]


def compute_classic_board(session, *, include_scores=True):
    """All current-season Classic players with draft-relevant context.

    Returns {'season_id', 'season_name', 'league_id', 'players': [...],
             'metrics': [...]} — players ordered by name. include_scores=False
    drops the averaged ratings block (for viewers without score access).
    """
    league = rating_service.current_classic_league(session)
    if league is None:
        return {'season_id': None, 'season_name': None, 'league_id': None,
                'players': [], 'metrics': []}
    season = league.season
    season_id = league.season_id

    coach_user_ids = rating_service.get_classic_coach_user_ids(session)
    players = rating_service.get_rateable_players(session, league)
    # Coaches appear on the board too (marked), just never in the rateable set.
    coach_players = []
    if coach_user_ids:
        belongs_ids = {p.id for p in players}
        coach_players = [
            p for p in session.query(Player)
            .filter(Player.user_id.in_(coach_user_ids),
                    Player.is_current_player.is_(True))
            .all()
            if p.id not in belongs_ids and (
                p.primary_league_id == league.id
                or any(l.id == league.id for l in p.other_leagues)
            )
        ]
    all_players = sorted(players + coach_players, key=lambda p: (p.name or '').lower())
    player_ids = [p.id for p in all_players]
    coach_player_ids = {p.id for p in coach_players}

    # Batch loads — one query each.
    attendance = {}
    try:
        attendance = AttendanceService.get_attendance_stats(player_ids) if player_ids else {}
    except Exception as e:
        logger.warning(f"classic board attendance load failed: {e}")

    career = {}
    if player_ids:
        for row in session.query(PlayerCareerStats).filter(
                PlayerCareerStats.player_id.in_(player_ids)).all():
            career[row.player_id] = {'goals': row.goals or 0, 'assists': row.assists or 0}

    # New = no PlayerTeamSeason in any season other than the current one.
    new_ids = set(player_ids)
    if player_ids:
        prior = session.query(func.distinct(PlayerTeamSeason.player_id)).filter(
            PlayerTeamSeason.player_id.in_(player_ids),
            PlayerTeamSeason.season_id != season_id,
        ).all()
        new_ids -= {pid for (pid,) in prior}

    # Current Classic team assignment (from player_teams x this league's teams).
    team_by_player = {}
    league_team_ids = [t.id for t in league.teams if t.name != 'Practice']
    if player_ids and league_team_ids:
        rows = (
            session.query(player_teams.c.player_id, Team.id, Team.name)
            .join(Team, Team.id == player_teams.c.team_id)
            .filter(player_teams.c.player_id.in_(player_ids),
                    Team.id.in_(league_team_ids))
            .all()
        )
        for pid, team_id, team_name in rows:
            team_by_player[pid] = {'team_id': team_id, 'team_name': team_name}

    finals = rating_service.get_final_scores(session, season_id) if include_scores else {}

    # NADs keep their scouting-note thread visible here too (same
    # PlayerAdminNote thread as the NAD board; hidden after graduation by the
    # existing service policy).
    nad_ids = set()
    note_counts = {}
    try:
        from app.services.nad_board_service import nad_player_id_set
        nad_ids = nad_player_id_set(session) & set(player_ids)
        if nad_ids:
            rows = (
                session.query(PlayerAdminNote.player_id, sa_func.count(PlayerAdminNote.id))
                .filter(PlayerAdminNote.player_id.in_(nad_ids))
                .group_by(PlayerAdminNote.player_id)
                .all()
            )
            note_counts = {pid: count for pid, count in rows}
    except Exception as e:
        logger.warning(f"classic board NAD/notes load failed: {e}")

    out_players = []
    for p in all_players:
        att = attendance.get(p.id) or {}
        entry = {
            'id': p.id,
            'user_id': p.user_id,
            'name': p.name,
            'profile_picture_url': p.profile_picture_url,
            'avatar_url': p.avatar_image_url,
            'pronouns': p.pronouns,
            'balance_gender': p.balance_gender,
            'is_coach': p.id in coach_player_ids,
            'is_new': p.id in new_ids and p.id not in coach_player_ids,
            'favorite_position': label_for(p.favorite_position) if p.favorite_position else None,
            'other_positions': _position_labels(p.other_positions),
            'positions_not_to_play': _position_labels(p.positions_not_to_play),
            'gk_willingness': gk_willingness(p),
            'wants_gk': wants_gk(p),
            'attendance_rate': att.get('adjusted_attendance_rate'),
            'has_attendance_data': bool(att.get('total_matches_invited')),
            'career_goals': career.get(p.id, {}).get('goals', 0),
            'career_assists': career.get(p.id, {}).get('assists', 0),
            'team_id': team_by_player.get(p.id, {}).get('team_id'),
            'team_name': team_by_player.get(p.id, {}).get('team_name'),
            'is_nad': p.id in nad_ids,
            'note_count': note_counts.get(p.id, 0),
        }
        if include_scores and p.id not in coach_player_ids:
            score = finals.get(p.id)
            entry['ratings'] = {
                'is_rated': bool(score and score['is_rated']),
                'composite': float(score['composite']) if score and score['composite'] is not None else None,
                'metrics': {
                    m: (float(score['metrics'][m]['value'])
                        if score and score['metrics'][m]['value'] is not None else None)
                    for m in rating_service.METRICS
                } if score else {m: None for m in rating_service.METRICS},
            }
        out_players.append(entry)

    return {
        'season_id': season_id,
        'season_name': season.name if season else None,
        'league_id': league.id,
        'players': out_players,
        'metrics': rating_service.get_metrics(session),
    }
