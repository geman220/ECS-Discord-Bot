# app/admin_panel/routes/match_operations/reports.py

"""
Match Operations Report Exports

Streaming CSV exports for the Match Reports page:
- /match-operations/reports/export/matches   -> match results (Match + Schedule + scores)
- /match-operations/reports/export/standings -> league standings (Standings model)
- /match-operations/reports/export/team       -> a single team's stats + roster

Plus a small JSON endpoint that powers the "Matches per Week" chart with a real
per-week count (instead of hard-coded sample data).

All data is read from real models. No values are fabricated. Optional filters
(season_id, league_id) narrow the result set; absent filters export everything.
"""

import csv
import io
import logging
from datetime import datetime

from flask import request, Response, jsonify, abort
from flask_login import login_required
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload

from app.admin_panel import admin_panel_bp
from app.core import db
from app.decorators import role_required

logger = logging.getLogger(__name__)

REPORT_ROLES = ['Global Admin', 'Pub League Admin']


def _csv_response(header, rows, filename_prefix):
    """Stream a CSV download from an iterable of row tuples/lists.

    ``header`` is a list of column names; ``rows`` is an iterable of sequences.
    Returns a Flask Response with text/csv + an attachment Content-Disposition.
    """
    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(header)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for row in rows:
            writer.writerow(row)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'{filename_prefix}_{timestamp}.csv'
    return Response(
        generate(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )


def _resolve_season(season_id):
    """Return the requested season, or the current one as a fallback (may be None)."""
    from app.models import Season
    if season_id:
        return Season.query.get(season_id)
    season = Season.query.filter_by(is_current=True, league_type="Pub League").first()
    if not season:
        season = Season.query.filter_by(is_current=True).first()
    return season


@admin_panel_bp.route('/match-operations/reports/export/matches')
@login_required
@role_required(REPORT_ROLES)
def export_match_results():
    """Stream match results (scores) as CSV. Optional ?season_id= & ?league_id=."""
    from app.models import Match, Team, League, Schedule

    season_id = request.args.get('season_id', type=int)
    league_id = request.args.get('league_id', type=int)

    query = Match.query.options(
        joinedload(Match.home_team),
        joinedload(Match.away_team),
        joinedload(Match.schedule),
    )

    season = _resolve_season(season_id)
    if season:
        query = query.join(Schedule, Match.schedule_id == Schedule.id).filter(
            Schedule.season_id == season.id
        )

    if league_id:
        team_ids = [t.id for t in Team.query.filter_by(league_id=league_id).all()]
        if team_ids:
            query = query.filter(
                or_(Match.home_team_id.in_(team_ids), Match.away_team_id.in_(team_ids))
            )
        else:
            # League has no teams -> no matches; force an empty result set.
            query = query.filter(Match.id.in_([]))

    matches = query.order_by(Match.date.desc(), Match.time.desc()).all()

    header = [
        'Match ID', 'Date', 'Time', 'Week', 'Week Type',
        'Home Team', 'Away Team', 'Home Score', 'Away Score',
        'Result', 'Location', 'Home Verified', 'Away Verified',
    ]

    def rows():
        for m in matches:
            home = m.home_team.name if m.home_team else 'TBD'
            away = m.away_team.name if m.away_team else 'TBD'
            hs, as_ = m.home_team_score, m.away_team_score
            if hs is not None and as_ is not None:
                if hs > as_:
                    result = 'Home Win'
                elif hs < as_:
                    result = 'Away Win'
                else:
                    result = 'Draw'
            else:
                result = 'Not Reported'
            yield [
                m.id,
                m.date.isoformat() if m.date else '',
                m.time.strftime('%H:%M') if m.time else '',
                (m.schedule.week if m.schedule else '') or '',
                getattr(m, 'week_type', '') or '',
                home,
                away,
                '' if hs is None else hs,
                '' if as_ is None else as_,
                result,
                getattr(m, 'location', '') or '',
                'Yes' if getattr(m, 'home_team_verified', False) else 'No',
                'Yes' if getattr(m, 'away_team_verified', False) else 'No',
            ]

    return _csv_response(header, rows(), 'match_results')


@admin_panel_bp.route('/match-operations/reports/export/standings')
@login_required
@role_required(REPORT_ROLES)
def export_standings():
    """Stream league standings (Standings model) as CSV. Optional ?season_id= & ?league_id=."""
    from app.models import Team, League
    from app.models.stats import Standings

    season_id = request.args.get('season_id', type=int)
    league_id = request.args.get('league_id', type=int)

    season = _resolve_season(season_id)

    query = Standings.query.options(
        joinedload(Standings.team).joinedload(Team.league)
    )
    if season:
        query = query.filter(Standings.season_id == season.id)
    if league_id:
        query = query.join(Team, Standings.team_id == Team.id).filter(
            Team.league_id == league_id
        )

    standings = query.all()

    # Premier and Classic are SEPARATE competitions, so group by division and rank
    # within each (position resets per league) rather than pooling into one order.
    from collections import defaultdict
    by_league = defaultdict(list)
    for s in standings:
        league_name = s.team.league.name if s.team and s.team.league else ''
        by_league[league_name].append(s)

    header = [
        'Position', 'Team', 'League', 'Played', 'Wins', 'Draws', 'Losses',
        'Goals For', 'Goals Against', 'Goal Difference', 'Points',
    ]

    def rows():
        for league_name in sorted(by_league.keys()):
            ranked = sorted(
                by_league[league_name],
                key=lambda s: (s.points or 0, s.goal_difference or 0, s.goals_for or 0),
                reverse=True,
            )
            for i, s in enumerate(ranked, start=1):
                team = s.team
                yield [
                    i,
                    team.name if team else f'#{s.team_id}',
                    league_name,
                    s.played or 0,
                    s.wins or 0,
                    s.draws or 0,
                    s.losses or 0,
                    s.goals_for or 0,
                    s.goals_against or 0,
                    s.goal_difference if s.goal_difference is not None else ((s.goals_for or 0) - (s.goals_against or 0)),
                    s.points or 0,
                ]

    return _csv_response(header, rows(), 'league_standings')


@admin_panel_bp.route('/match-operations/reports/export/team')
@login_required
@role_required(REPORT_ROLES)
def export_team_report():
    """Stream a single team's standings line + roster as CSV. Requires ?team_id=."""
    from app.models import Team, League
    from app.models.players import Player, player_teams
    from app.models.stats import Standings

    team_id = request.args.get('team_id', type=int)
    if not team_id:
        abort(400, description='team_id is required')

    team = Team.query.options(joinedload(Team.league)).get(team_id)
    if not team:
        abort(404, description='Team not found')

    # Most-recent standings row for this team (highest season_id).
    standing = (
        Standings.query.filter_by(team_id=team.id)
        .order_by(Standings.season_id.desc())
        .first()
    )

    # Roster with coach flag, ordered coaches-first then by name.
    roster = (
        db.session.query(Player, player_teams.c.is_coach)
        .join(player_teams, Player.id == player_teams.c.player_id)
        .filter(player_teams.c.team_id == team.id)
        .order_by(player_teams.c.is_coach.desc(), Player.name.asc())
        .all()
    )

    league_name = team.league.name if team.league else ''

    header = ['Section', 'Field', 'Value']

    def rows():
        # Team summary block.
        yield ['Team', 'Name', team.name]
        yield ['Team', 'League', league_name]
        if standing:
            yield ['Stats', 'Played', standing.played or 0]
            yield ['Stats', 'Wins', standing.wins or 0]
            yield ['Stats', 'Draws', standing.draws or 0]
            yield ['Stats', 'Losses', standing.losses or 0]
            yield ['Stats', 'Goals For', standing.goals_for or 0]
            yield ['Stats', 'Goals Against', standing.goals_against or 0]
            gd = standing.goal_difference if standing.goal_difference is not None \
                else ((standing.goals_for or 0) - (standing.goals_against or 0))
            yield ['Stats', 'Goal Difference', gd]
            yield ['Stats', 'Points', standing.points or 0]
        # Roster block: one row per player.
        for player, is_coach in roster:
            role = 'Coach' if is_coach or getattr(player, 'is_coach', False) else 'Player'
            jersey = player.jersey_number if player.jersey_number is not None else ''
            position = getattr(player, 'favorite_position', '') or ''
            yield ['Roster', f'{role}: {player.name}',
                   f'#{jersey} {position}'.strip() if (jersey != '' or position) else '']

    return _csv_response(header, rows(), f'team_{team_id}_report')


@admin_panel_bp.route('/match-operations/reports/matches-per-week')
@login_required
@role_required(REPORT_ROLES)
def matches_per_week_data():
    """Return real per-week match counts for the Matches per Week chart.

    Counts matches grouped by their Schedule.week within the (current or
    requested) season. Returns sorted labels + counts; never fabricates data.
    """
    try:
        from app.models import Match, Schedule

        season_id = request.args.get('season_id', type=int)
        season = _resolve_season(season_id)

        query = (
            db.session.query(Schedule.week, func.count(func.distinct(Match.id)))
            .join(Match, Match.schedule_id == Schedule.id)
            .filter(Schedule.week.isnot(None), Schedule.week != '')
        )
        if season:
            query = query.filter(Schedule.season_id == season.id)

        results = query.group_by(Schedule.week).all()

        # Sort weeks numerically when possible, else lexically.
        def week_key(item):
            w = item[0]
            return (0, int(w)) if str(w).isdigit() else (1, str(w))

        results.sort(key=week_key)

        labels = [f'Week {w}' if str(w).isdigit() else str(w) for w, _ in results]
        counts = [int(c) for _, c in results]

        return jsonify({'success': True, 'labels': labels, 'counts': counts})
    except Exception as e:
        logger.error(f"Error building matches-per-week data: {e}")
        return jsonify({'success': False, 'error': 'Failed to load per-week match counts'}), 500
