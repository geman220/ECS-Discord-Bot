# app/services/live_reporting/live_match_queries.py

"""
Currently-live match queries (admin views).

Single source of truth for "which matches are being live-reported right now",
across both Pub League (LiveMatch) and ECS FC (EcsFcLiveMatch). The admin
Match Operations "Live" KPI and the Live Matches page both derive from here so
the count can never drift from the list it links to.

A match counts as live when its live-state row is status='in_progress', the
report hasn't been submitted yet, and the row was touched recently — the
staleness guard keeps a forgotten in_progress row (a coach who never hit submit)
from showing as "live" for days, the same resolved-by-default principle used for
stale substitute requests.

These read straight off the DB tables that BOTH the V1 and V2 socket engines
write, so the data is correct regardless of LIVE_MATCH_STATE_V2_ENABLED.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# A live-state row older than this with no activity is treated as abandoned,
# not live (mirrors the sub-request grace-window idea).
LIVE_STALE_HOURS = 6


def _cutoff():
    return datetime.utcnow() - timedelta(hours=LIVE_STALE_HOURS)


def count_live_matches(session) -> int:
    """Cheap count of matches actively being live-reported (both leagues)."""
    from app.database.db_models import LiveMatch
    from app.models.ecs_fc import EcsFcLiveMatch

    cutoff = _cutoff()
    pub = session.query(LiveMatch).filter(
        LiveMatch.status == 'in_progress',
        LiveMatch.report_submitted.is_(False),
        LiveMatch.last_updated >= cutoff,
    ).count()
    ecs = session.query(EcsFcLiveMatch).filter(
        EcsFcLiveMatch.status == 'in_progress',
        EcsFcLiveMatch.last_updated >= cutoff,
    ).count()
    return pub + ecs


def get_live_match_overviews(session):
    """Full detail for each currently-live match, newest activity first.

    Returns a list of plain dicts (template/JSON friendly). `room` is the
    Socket.IO room name a read-only admin observer would join for live updates.
    """
    overviews = []
    cutoff = _cutoff()

    # ---- Pub League ----
    try:
        from app.database.db_models import LiveMatch, MatchEvent
        from app.models import Match, Team
        from app.sockets.live_reporting import get_active_reporters

        live_rows = session.query(LiveMatch).filter(
            LiveMatch.status == 'in_progress',
            LiveMatch.report_submitted.is_(False),
            LiveMatch.last_updated >= cutoff,
        ).order_by(LiveMatch.last_updated.desc()).all()

        for lm in live_rows:
            match = session.query(Match).get(lm.match_id)
            if not match:
                continue
            home = session.query(Team).get(match.home_team_id) if match.home_team_id else None
            away = session.query(Team).get(match.away_team_id) if match.away_team_id else None
            event_count = session.query(MatchEvent).filter(MatchEvent.match_id == lm.match_id).count()
            try:
                reporters = get_active_reporters(session, lm.match_id)
            except Exception:
                reporters = []
            overviews.append({
                'league_type': 'pub',
                'match_id': lm.match_id,
                'room': f"match_{lm.match_id}",
                'home_team_id': match.home_team_id,
                'away_team_id': match.away_team_id,
                'home_team_name': home.name if home else 'Home',
                'away_team_name': away.name if away else 'Away',
                'home_score': lm.home_score or 0,
                'away_score': lm.away_score or 0,
                'current_period': lm.current_period,
                'elapsed_seconds': lm.elapsed_seconds or 0,
                'timer_running': bool(lm.timer_running),
                'report_submitted': bool(lm.report_submitted),
                'last_updated': lm.last_updated,
                'date': match.date,
                'time': match.time,
                'event_count': event_count,
                'reporters': reporters,
                'reporter_count': len(reporters),
            })
    except Exception as e:
        logger.warning(f"get_live_match_overviews/pub: {e}")

    # ---- ECS FC ----
    try:
        from app.models.ecs_fc import EcsFcLiveMatch, EcsFcMatch, EcsFcMatchEvent

        live_rows = session.query(EcsFcLiveMatch).filter(
            EcsFcLiveMatch.status == 'in_progress',
            EcsFcLiveMatch.last_updated >= cutoff,
        ).order_by(EcsFcLiveMatch.last_updated.desc()).all()

        for elm in live_rows:
            match = session.query(EcsFcMatch).get(elm.ecs_fc_match_id)
            if not match:
                continue
            event_count = session.query(EcsFcMatchEvent).filter(
                EcsFcMatchEvent.match_id == elm.ecs_fc_match_id
            ).count()
            team_name = match.team.name if match.team else 'ECS FC'
            # ECS FC is single-team vs an external opponent; present home/away by venue.
            if match.is_home_match:
                home_name, away_name = team_name, match.opponent_name
            else:
                home_name, away_name = match.opponent_name, team_name
            overviews.append({
                'league_type': 'ecs_fc',
                'match_id': elm.ecs_fc_match_id,
                'room': f"ecs_fc_match_{elm.ecs_fc_match_id}",
                'home_team_id': match.team_id if match.is_home_match else None,
                'away_team_id': match.team_id if not match.is_home_match else None,
                'home_team_name': home_name,
                'away_team_name': away_name,
                'home_score': match.home_score if match.home_score is not None else 0,
                'away_score': match.away_score if match.away_score is not None else 0,
                'current_period': None,
                'elapsed_seconds': 0,
                'timer_running': False,
                'report_submitted': False,
                'last_updated': elm.last_updated,
                'date': match.match_date,
                'time': match.match_time,
                'event_count': event_count,
                'reporters': [],
                'reporter_count': 0,
            })
    except Exception as e:
        logger.warning(f"get_live_match_overviews/ecs_fc: {e}")

    overviews.sort(key=lambda o: o['last_updated'] or datetime.min, reverse=True)
    return overviews
