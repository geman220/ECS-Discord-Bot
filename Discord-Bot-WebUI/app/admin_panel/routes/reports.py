# app/admin_panel/routes/reports.py

"""
Admin Panel Reports & Data Exports

A centralized "Reports" hub for pulling structured data out of the database and
exporting it to Excel (.xlsx). Reports included:

- Player Stats      : goals/assists/cards, per-season (per-league rows) or career totals
- Attendance        : RSVP response/attendance/reliability per player
- Player Movement   : Classic <-> Premier promotions/drops across seasons
- Retention/Churn   : new vs returning vs lapsed players season-over-season
- Roster History    : each player's team-by-season timeline
- Leaderboards      : top scorers / assists / discipline for a season or all-time
- Kit / Jersey Size : jersey-size counts for ordering
- Team Standings    : W/D/L, GF/GA, goal diff, points by season/league
- Discipline        : cards broken down by reason (foul/dissent/...)
- Contactability    : SMS/phone/Discord reachability + profile freshness

Each report's data is built once by a ``_build_*`` helper that both the on-page
preview and the Excel export call, so the spreadsheet always matches the preview.
Exports mirror the existing Excel pattern in app/user_management.py:
DataFrame -> openpyxl ExcelWriter -> auto-width columns -> attachment response.

Stats are stored per-league (a player on both Premier and Classic in one season
has two PlayerSeasonStats rows); season-mode exports preserve those rows. Career
mode aggregates across the selected scope.
"""

import io
import logging
from datetime import datetime
from collections import defaultdict

from flask import render_template, request, g, redirect, url_for, flash, make_response
from flask_login import login_required
from sqlalchemy.orm import joinedload

from .. import admin_panel_bp
from app.decorators import role_required
from app.models import (
    Player, PlayerSeasonStats, PlayerAttendanceStats, PlayerTeamSeason,
    Season, League, Team, Standings, PlayerEvent, PlayerEventType, Match, Schedule,
)

logger = logging.getLogger(__name__)

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:  # pragma: no cover
    PANDAS_AVAILABLE = False

REPORT_ROLES = ['Global Admin', 'Pub League Admin']
PREVIEW_LIMIT = 25


# =====================================================================
# Shared helpers
# =====================================================================

def _pub_league_seasons(session):
    """Pub League seasons ordered chronologically (oldest first)."""
    return (
        session.query(Season)
        .filter(Season.league_type == 'pub_league')
        .order_by(Season.start_date.asc(), Season.id.asc())
        .all()
    )


def _all_seasons(session):
    """All seasons (pub league + ECS FC), newest first for dropdowns."""
    return (
        session.query(Season)
        # start_date.is_(None) sorts False (0) before True (1) -> dated seasons first
        .order_by(Season.start_date.is_(None), Season.start_date.desc(), Season.id.desc())
        .all()
    )


def _league_names(session):
    """Distinct league names (Premier / Classic / ECS FC) for filtering."""
    rows = session.query(League.name).distinct().order_by(League.name).all()
    return [r[0] for r in rows if r[0]]


def _season_ids_in_range(session, season_from, season_to):
    """Resolve a (from, to) season pair to the inclusive list of season ids.

    Returns None when neither bound is set (meaning "all seasons"). Order of the
    two arguments does not matter; seasons are sorted chronologically and the
    inclusive slice between the two chosen seasons is returned.
    """
    if not season_from and not season_to:
        return None
    ordered = (
        session.query(Season)
        .order_by(Season.start_date.is_(None), Season.start_date.asc(), Season.id.asc())
        .all()
    )
    index = {s.id: i for i, s in enumerate(ordered)}
    bounds = [index[x] for x in (season_from, season_to) if x in index]
    if not bounds:
        return None
    lo, hi = min(bounds), max(bounds)
    return [s.id for s in ordered if lo <= index[s.id] <= hi]


def _season_name(session, season_id):
    if not season_id:
        return None
    s = session.query(Season).get(season_id)
    return s.name if s else None


def _pandas_guard():
    """Return a redirect response if pandas is unavailable, else None."""
    if not PANDAS_AVAILABLE:
        flash('Excel export requires pandas/openpyxl. Please install them: pip install pandas openpyxl', 'error')
        return redirect(url_for('admin_panel.reports_center'))
    return None


def _build_xlsx_response(sheets, filename_prefix):
    """Build an .xlsx download response from a list of (sheet_name, rows) tuples.

    Each ``rows`` is a list of dicts (one per row). Empty sheets are written with
    a placeholder so the workbook is never invalid. Column widths auto-fit.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, rows in sheets:
            safe_name = (sheet_name or 'Sheet')[:31]
            df = pd.DataFrame(rows if rows else [{'(no data)': 'No records matched the selected filters.'}])
            df.to_excel(writer, index=False, sheet_name=safe_name)

            worksheet = writer.sheets[safe_name]
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if cell.value is not None and len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except Exception:
                        pass
                worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)

    output.seek(0)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'{filename_prefix}_{timestamp}.xlsx'
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response


def _player_team_lookup(session):
    """Map (player_id, season_id, league_name) -> [team names] for that season."""
    rows = (
        session.query(
            PlayerTeamSeason.player_id,
            PlayerTeamSeason.season_id,
            League.name,
            Team.name,
        )
        .join(Team, PlayerTeamSeason.team_id == Team.id)
        .join(League, Team.league_id == League.id)
        .all()
    )
    lookup = defaultdict(list)
    for player_id, season_id, league_name, team_name in rows:
        lookup[(player_id, season_id, league_name)].append(team_name)
    return lookup


def _current_team_name(player):
    """Best-effort current team name for a player."""
    if player.primary_team_id and player.primary_team:
        return player.primary_team.name
    if player.teams:
        return player.teams[0].name
    return ''


def _preview(rows):
    """Return the first PREVIEW_LIMIT rows for on-page preview."""
    return rows[:PREVIEW_LIMIT]


def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else 0.0


def _avg(values):
    return round(sum(values) / len(values), 1) if values else 0.0


# =====================================================================
# Reports hub
# =====================================================================

@admin_panel_bp.route('/reports/center')
@login_required
@role_required(REPORT_ROLES)
def reports_center():
    """Landing page listing all available reports."""
    return render_template('admin_panel/reports/index_flowbite.html')


# =====================================================================
# 1. Player Stats (goals / assists / cards)
# =====================================================================

def _build_player_stats(session, season_ids, league_name, current_only, min_goals=0):
    """Return {'career': [...rows], 'season': [...rows]} for the given scope."""
    query = (
        session.query(PlayerSeasonStats)
        .options(
            joinedload(PlayerSeasonStats.player),
            joinedload(PlayerSeasonStats.season),
            joinedload(PlayerSeasonStats.league),
        )
        .join(Player, PlayerSeasonStats.player_id == Player.id)
    )
    if current_only:
        query = query.filter(Player.is_current_player.is_(True))
    if season_ids is not None:
        query = query.filter(PlayerSeasonStats.season_id.in_(season_ids))
    if league_name:
        query = query.join(League, PlayerSeasonStats.league_id == League.id).filter(League.name == league_name)

    stat_rows = query.all()
    team_lookup = _player_team_lookup(session)

    season_sheet = []
    career = {}
    for s in stat_rows:
        player = s.player
        league_label = s.league.name if s.league else '(unassigned)'
        season_label = s.season.name if s.season else '(unknown)'
        teams = team_lookup.get((s.player_id, s.season_id, league_label), [])
        season_sheet.append({
            'Player': player.name if player else f'#{s.player_id}',
            'Season': season_label,
            'League': league_label,
            'Team': ', '.join(teams),
            'Goals': s.goals,
            'Assists': s.assists,
            'Yellow Cards': s.yellow_cards,
            'Red Cards': s.red_cards,
        })

        acc = career.get(s.player_id)
        if acc is None:
            acc = {
                'Player': player.name if player else f'#{s.player_id}',
                'Primary League': player.primary_league.name if player and player.primary_league else '',
                'Current Team': _current_team_name(player) if player else '',
                'Goals': 0, 'Assists': 0, 'Yellow Cards': 0, 'Red Cards': 0,
                '_seasons': set(),
            }
            career[s.player_id] = acc
        acc['Goals'] += s.goals
        acc['Assists'] += s.assists
        acc['Yellow Cards'] += s.yellow_cards
        acc['Red Cards'] += s.red_cards
        acc['_seasons'].add(s.season_id)

    if min_goals:
        season_sheet = [r for r in season_sheet if r['Goals'] >= min_goals]
    season_sheet.sort(key=lambda r: (r['Player'].lower(), r['Season'], r['League']))

    career_sheet = []
    for acc in career.values():
        acc['Seasons Played'] = len(acc.pop('_seasons'))
        career_sheet.append(acc)
    if min_goals:
        career_sheet = [r for r in career_sheet if r['Goals'] >= min_goals]
    career_sheet.sort(key=lambda r: (-r['Goals'], r['Player'].lower()))

    return {'career': career_sheet, 'season': season_sheet}


def _player_stats_args():
    return {
        'mode': request.args.get('mode', 'both'),
        'season_from': request.args.get('season_from', type=int),
        'season_to': request.args.get('season_to', type=int),
        'league_name': request.args.get('league') or None,
        'current_only': request.args.get('current_only', type=int),
        'min_goals': request.args.get('min_goals', type=int) or 0,
    }


@admin_panel_bp.route('/reports/player-stats')
@login_required
@role_required(REPORT_ROLES)
def player_stats_report():
    session = g.db_session
    args = _player_stats_args()
    season_ids = _season_ids_in_range(session, args['season_from'], args['season_to'])
    data = _build_player_stats(session, season_ids, args['league_name'], args['current_only'], args['min_goals'])

    primary = 'season' if args['mode'] == 'season' else 'career'
    rows = data[primary]

    kpis = [
        {'label': 'Players', 'value': len(data['career'])},
        {'label': 'Total Goals', 'value': sum(r['Goals'] for r in data['career'])},
        {'label': 'Total Assists', 'value': sum(r['Assists'] for r in data['career'])},
        {'label': 'Avg Goals / Player', 'value': _avg([r['Goals'] for r in data['career']])},
    ]
    chips = []
    if args['league_name']:
        chips.append(f"League: {args['league_name']}")
    if args['season_from'] or args['season_to']:
        chips.append(f"Seasons: {_season_name(session, args['season_from']) or 'earliest'} → {_season_name(session, args['season_to']) or 'latest'}")
    if args['current_only']:
        chips.append('Current players only')
    if args['min_goals']:
        chips.append(f"Min {args['min_goals']} goals")

    return render_template(
        'admin_panel/reports/player_stats_flowbite.html',
        seasons=_all_seasons(session),
        leagues=_league_names(session),
        args=args,
        kpis=kpis,
        chips=chips,
        preview_rows=_preview(rows),
        total_count=len(rows),
        preview_label='Career totals' if primary == 'career' else 'Season-by-season',
    )


@admin_panel_bp.route('/reports/player-stats/export')
@login_required
@role_required(REPORT_ROLES)
def player_stats_export():
    guard = _pandas_guard()
    if guard:
        return guard
    session = g.db_session
    args = _player_stats_args()
    season_ids = _season_ids_in_range(session, args['season_from'], args['season_to'])
    data = _build_player_stats(session, season_ids, args['league_name'], args['current_only'], args['min_goals'])

    sheets = []
    if args['mode'] in ('career', 'both'):
        sheets.append(('Career Totals', data['career']))
    if args['mode'] in ('season', 'both'):
        sheets.append(('By Season', data['season']))
    if not sheets:
        sheets = [('Career Totals', data['career'])]
    return _build_xlsx_response(sheets, 'player_stats')


# =====================================================================
# 2. Attendance & Reliability
# =====================================================================

def _build_attendance(session, league_name, current_only, min_invited=0):
    query = (
        session.query(PlayerAttendanceStats)
        .options(joinedload(PlayerAttendanceStats.player).joinedload(Player.primary_league))
        .join(Player, PlayerAttendanceStats.player_id == Player.id)
    )
    if current_only:
        query = query.filter(Player.is_current_player.is_(True))
    if league_name:
        query = query.join(League, Player.primary_league_id == League.id).filter(League.name == league_name)
    if min_invited:
        query = query.filter(PlayerAttendanceStats.total_matches_invited >= min_invited)

    rows = []
    for a in query.all():
        player = a.player
        rows.append({
            'Player': player.name if player else f'#{a.player_id}',
            'Primary League': player.primary_league.name if player and player.primary_league else '',
            'Current Team': _current_team_name(player) if player else '',
            'Matches Invited': a.total_matches_invited,
            'Responses': a.total_responses,
            'Yes': a.yes_responses,
            'No': a.no_responses,
            'Maybe': a.maybe_responses,
            'No Response': a.no_response_count,
            'Response Rate %': round(a.response_rate, 1),
            'Attendance Rate %': round(a.attendance_rate, 1),
            'Adjusted Attendance %': round(a.adjusted_attendance_rate, 1),
            'Reliability Score': round(a.reliability_score, 1),
            'Season Attendance %': round(a.season_attendance_rate, 1),
            'Last Match': a.last_match_date.strftime('%Y-%m-%d') if a.last_match_date else '',
        })
    rows.sort(key=lambda r: (-r['Reliability Score'], r['Player'].lower()))
    return rows


@admin_panel_bp.route('/reports/attendance')
@login_required
@role_required(REPORT_ROLES)
def attendance_report():
    session = g.db_session
    league_name = request.args.get('league') or None
    current_only = request.args.get('current_only', type=int)
    min_invited = request.args.get('min_invited', type=int) or 0
    rows = _build_attendance(session, league_name, current_only, min_invited)

    kpis = [
        {'label': 'Players', 'value': len(rows)},
        {'label': 'Avg Attendance %', 'value': _avg([r['Attendance Rate %'] for r in rows])},
        {'label': 'Avg Response %', 'value': _avg([r['Response Rate %'] for r in rows])},
        {'label': 'Avg Reliability', 'value': _avg([r['Reliability Score'] for r in rows])},
    ]
    chips = []
    if league_name:
        chips.append(f"League: {league_name}")
    if current_only:
        chips.append('Current players only')
    if min_invited:
        chips.append(f"Min {min_invited} matches invited")

    return render_template(
        'admin_panel/reports/attendance_flowbite.html',
        leagues=_league_names(session),
        args={'league_name': league_name, 'current_only': current_only, 'min_invited': min_invited},
        kpis=kpis,
        chips=chips,
        preview_rows=_preview(rows),
        total_count=len(rows),
    )


@admin_panel_bp.route('/reports/attendance/export')
@login_required
@role_required(REPORT_ROLES)
def attendance_export():
    guard = _pandas_guard()
    if guard:
        return guard
    rows = _build_attendance(
        g.db_session,
        request.args.get('league') or None,
        request.args.get('current_only', type=int),
        request.args.get('min_invited', type=int) or 0,
    )
    return _build_xlsx_response([('Attendance', rows)], 'attendance')


# =====================================================================
# 3. Player Movement (Classic <-> Premier across seasons)
# =====================================================================

MOVEMENT_CATEGORIES = [
    'Promoted (Classic→Premier)', 'Dropped (Premier→Classic)', 'Both ways',
    'Premier only', 'Classic only', 'Other',
]


def _movement_records(session, movers_only=False):
    """Compute each player's pub-league playing path across seasons.

    If a player is rostered in BOTH Classic and Premier in the same season, that
    season counts as Premier (the higher tier). A Classic->Premier "move up"
    therefore only counts when the player was in Classic *alone* in an earlier
    season and Premier in a later one; a dual-league season is never itself a move.
    """
    seasons = _pub_league_seasons(session)
    season_index = {s.id: i for i, s in enumerate(seasons)}
    season_name = {s.id: s.name for s in seasons}
    pub_season_ids = list(season_index.keys())
    if not pub_season_ids:
        return []

    rows = (
        session.query(
            PlayerTeamSeason.player_id,
            PlayerTeamSeason.season_id,
            Player.name,
            League.name,
        )
        .join(Player, PlayerTeamSeason.player_id == Player.id)
        .join(Team, PlayerTeamSeason.team_id == Team.id)
        .join(League, Team.league_id == League.id)
        .filter(PlayerTeamSeason.season_id.in_(pub_season_ids))
        .all()
    )

    by_player = defaultdict(lambda: defaultdict(set))
    names = {}
    for player_id, season_id, pname, league in rows:
        names[player_id] = pname
        by_player[player_id][season_id].add(league)

    def playing_league(league_set):
        # Rostered in both leagues the same season => count as Premier (the higher
        # tier). Otherwise the one league they were rostered in.
        if 'Premier' in league_set:
            return 'Premier'
        if 'Classic' in league_set:
            return 'Classic'
        return sorted(league_set)[0] if league_set else None

    results = []
    for player_id, season_map in by_player.items():
        ordered = sorted(season_map.keys(), key=lambda sid: season_index.get(sid, 0))
        path_pairs = []  # (season_id, league)
        for sid in ordered:
            lg = playing_league(season_map[sid])
            if lg is None:
                continue
            if not path_pairs or path_pairs[-1][1] != lg:
                path_pairs.append((sid, lg))
        if not path_pairs:
            continue

        leagues_seen = [lg for _, lg in path_pairs]
        promoted = any(
            leagues_seen[i] == 'Classic' and 'Premier' in leagues_seen[i + 1:]
            for i in range(len(leagues_seen))
        )
        dropped = any(
            leagues_seen[i] == 'Premier' and 'Classic' in leagues_seen[i + 1:]
            for i in range(len(leagues_seen))
        )
        if promoted and dropped:
            movement = 'Both ways'
        elif promoted:
            movement = 'Promoted (Classic→Premier)'
        elif dropped:
            movement = 'Dropped (Premier→Classic)'
        elif set(leagues_seen) == {'Premier'}:
            movement = 'Premier only'
        elif set(leagues_seen) == {'Classic'}:
            movement = 'Classic only'
        else:
            movement = 'Other'

        if movers_only and movement not in ('Promoted (Classic→Premier)', 'Dropped (Premier→Classic)', 'Both ways'):
            continue

        path_str = ' → '.join(f'{lg} ({season_name.get(sid, "?")})' for sid, lg in path_pairs)
        first_sid, first_lg = path_pairs[0]
        last_sid, last_lg = path_pairs[-1]
        results.append({
            'Player': names.get(player_id, f'#{player_id}'),
            'Seasons Played': len(ordered),
            'First League': first_lg,
            'First Season': season_name.get(first_sid, ''),
            'Latest League': last_lg,
            'Latest Season': season_name.get(last_sid, ''),
            'Movement': movement,
            'Path': path_str,
        })

    results.sort(key=lambda r: (r['Movement'], r['Player'].lower()))
    return results


@admin_panel_bp.route('/reports/movement')
@login_required
@role_required(REPORT_ROLES)
def movement_report():
    session = g.db_session
    movers_only = request.args.get('movers_only', type=int)
    rows = _movement_records(session, movers_only=bool(movers_only))

    counts = {c: 0 for c in MOVEMENT_CATEGORIES}
    for r in rows:
        counts[r['Movement']] = counts.get(r['Movement'], 0) + 1
    kpis = [
        {'label': 'Players Tracked', 'value': len(rows)},
        {'label': 'Promoted', 'value': counts['Promoted (Classic→Premier)']},
        {'label': 'Dropped', 'value': counts['Dropped (Premier→Classic)']},
        {'label': 'Both Ways', 'value': counts['Both ways']},
    ]
    chart_data = {
        'labels': MOVEMENT_CATEGORIES,
        'counts': [counts[c] for c in MOVEMENT_CATEGORIES],
    }
    chips = ['Movers only'] if movers_only else []

    return render_template(
        'admin_panel/reports/movement_flowbite.html',
        args={'movers_only': movers_only},
        kpis=kpis,
        chips=chips,
        chart_data=chart_data,
        preview_rows=_preview(rows),
        total_count=len(rows),
    )


@admin_panel_bp.route('/reports/movement/export')
@login_required
@role_required(REPORT_ROLES)
def movement_export():
    guard = _pandas_guard()
    if guard:
        return guard
    rows = _movement_records(g.db_session, movers_only=bool(request.args.get('movers_only', type=int)))
    return _build_xlsx_response([('Player Movement', rows)], 'player_movement')


# =====================================================================
# 4. Retention / Churn (season over season)
# =====================================================================

def _build_retention(session):
    seasons = _pub_league_seasons(session)
    members = defaultdict(set)
    pairs = (
        session.query(PlayerTeamSeason.season_id, PlayerTeamSeason.player_id)
        .filter(PlayerTeamSeason.season_id.in_([s.id for s in seasons]))
        .all()
    )
    for season_id, player_id in pairs:
        members[season_id].add(player_id)

    rows = []
    prev_set = None
    for s in seasons:
        cur = members.get(s.id, set())
        if prev_set is None:
            new, returning, lapsed, retention = cur, set(), set(), None
        else:
            new = cur - prev_set
            returning = cur & prev_set
            lapsed = prev_set - cur
            retention = _pct(len(returning), len(prev_set)) if prev_set else None
        rows.append({
            'Season': s.name,
            'Total Players': len(cur),
            'New Players': len(new),
            'Returning': len(returning),
            'Lapsed From Prior': len(lapsed),
            'Retention % (of prior)': retention if retention is not None else 'n/a',
        })
        prev_set = cur
    return rows


@admin_panel_bp.route('/reports/retention')
@login_required
@role_required(REPORT_ROLES)
def retention_report():
    session = g.db_session
    rows = _build_retention(session)

    latest = rows[-1] if rows else None
    numeric_ret = [r['Retention % (of prior)'] for r in rows if isinstance(r['Retention % (of prior)'], (int, float))]
    kpis = [
        {'label': 'Seasons Tracked', 'value': len(rows)},
        {'label': 'Latest Total Players', 'value': latest['Total Players'] if latest else 0},
        {'label': 'Latest Retention %', 'value': latest['Retention % (of prior)'] if latest else 'n/a'},
        {'label': 'Avg Retention %', 'value': _avg(numeric_ret)},
    ]
    chart_data = {
        'labels': [r['Season'] for r in rows],
        'retention': [r['Retention % (of prior)'] if isinstance(r['Retention % (of prior)'], (int, float)) else None for r in rows],
        'total': [r['Total Players'] for r in rows],
    }

    return render_template(
        'admin_panel/reports/retention_flowbite.html',
        kpis=kpis,
        chart_data=chart_data,
        preview_rows=_preview(rows),
        total_count=len(rows),
    )


@admin_panel_bp.route('/reports/retention/export')
@login_required
@role_required(REPORT_ROLES)
def retention_export():
    guard = _pandas_guard()
    if guard:
        return guard
    rows = _build_retention(g.db_session)
    return _build_xlsx_response([('Retention', rows)], 'retention')


# =====================================================================
# 5. Roster History (player team-by-season timeline)
# =====================================================================

def _build_roster_history(session, season_id):
    query = (
        session.query(PlayerTeamSeason)
        .options(
            joinedload(PlayerTeamSeason.player),
            joinedload(PlayerTeamSeason.team).joinedload(Team.league),
            joinedload(PlayerTeamSeason.season),
        )
    )
    if season_id:
        query = query.filter(PlayerTeamSeason.season_id == season_id)

    seasons = _all_seasons(session)
    season_order = {s.id: -i for i, s in enumerate(seasons)}  # newest first -> ascending later

    rows = []
    for a in query.all():
        player = a.player
        team = a.team
        rows.append({
            'Player': player.name if player else f'#{a.player_id}',
            'Season': a.season.name if a.season else '',
            'League': team.league.name if team and team.league else '',
            'Team': team.name if team else '',
            '_season_sort': season_order.get(a.season_id, 0),
        })
    rows.sort(key=lambda r: (r['Player'].lower(), r['_season_sort']))
    for r in rows:
        r.pop('_season_sort', None)
    return rows


@admin_panel_bp.route('/reports/roster-history')
@login_required
@role_required(REPORT_ROLES)
def roster_history_report():
    session = g.db_session
    season_id = request.args.get('season_id', type=int)
    rows = _build_roster_history(session, season_id)

    distinct_players = len({r['Player'] for r in rows})
    distinct_seasons = len({r['Season'] for r in rows})
    kpis = [
        {'label': 'Assignments', 'value': len(rows)},
        {'label': 'Distinct Players', 'value': distinct_players},
        {'label': 'Seasons', 'value': distinct_seasons},
    ]
    chips = []
    if season_id:
        chips.append(f"Season: {_season_name(session, season_id)}")

    return render_template(
        'admin_panel/reports/roster_history_flowbite.html',
        seasons=_all_seasons(session),
        args={'season_id': season_id},
        kpis=kpis,
        chips=chips,
        preview_rows=_preview(rows),
        total_count=len(rows),
    )


@admin_panel_bp.route('/reports/roster-history/export')
@login_required
@role_required(REPORT_ROLES)
def roster_history_export():
    guard = _pandas_guard()
    if guard:
        return guard
    rows = _build_roster_history(g.db_session, request.args.get('season_id', type=int))
    return _build_xlsx_response([('Roster History', rows)], 'roster_history')


# =====================================================================
# 6. Leaderboards (top scorers / assists / discipline)
# =====================================================================

LEADERBOARD_SORTS = {
    'goals': ('Goals', 'Assists'),
    'assists': ('Assists', 'Goals'),
    'ga': ('G+A', 'Goals'),
    'yellow': ('Yellow Cards', 'Red Cards'),
    'red': ('Red Cards', 'Yellow Cards'),
}


def _build_leaderboards(session, season_id, league_name, sort='goals', min_goals=0):
    query = (
        session.query(PlayerSeasonStats)
        .options(joinedload(PlayerSeasonStats.player), joinedload(PlayerSeasonStats.league))
        .join(Player, PlayerSeasonStats.player_id == Player.id)
    )
    if season_id:
        query = query.filter(PlayerSeasonStats.season_id == season_id)
    if league_name:
        query = query.join(League, PlayerSeasonStats.league_id == League.id).filter(League.name == league_name)

    agg = {}
    for s in query.all():
        acc = agg.get(s.player_id)
        if acc is None:
            acc = {
                'Player': s.player.name if s.player else f'#{s.player_id}',
                'League': s.league.name if s.league else '',
                'Goals': 0, 'Assists': 0, 'G+A': 0, 'Yellow Cards': 0, 'Red Cards': 0,
            }
            agg[s.player_id] = acc
        acc['Goals'] += s.goals
        acc['Assists'] += s.assists
        acc['Yellow Cards'] += s.yellow_cards
        acc['Red Cards'] += s.red_cards
        acc['G+A'] = acc['Goals'] + acc['Assists']

    rows = list(agg.values())
    if min_goals:
        rows = [r for r in rows if r['Goals'] >= min_goals]

    primary, secondary = LEADERBOARD_SORTS.get(sort, LEADERBOARD_SORTS['goals'])
    rows.sort(key=lambda r: (-r[primary], -r[secondary], r['Player'].lower()))

    out = []
    for i, r in enumerate(rows, start=1):
        row = {'Rank': i}
        row.update(r)
        out.append(row)
    return out


@admin_panel_bp.route('/reports/leaderboards')
@login_required
@role_required(REPORT_ROLES)
def leaderboards_report():
    session = g.db_session
    season_id = request.args.get('season_id', type=int)
    league_name = request.args.get('league') or None
    sort = request.args.get('sort', 'goals')
    min_goals = request.args.get('min_goals', type=int) or 0
    rows = _build_leaderboards(session, season_id, league_name, sort, min_goals)

    top = rows[0] if rows else None
    kpis = [
        {'label': 'Players', 'value': len(rows)},
        {'label': 'Total Goals', 'value': sum(r['Goals'] for r in rows)},
        {'label': 'Total Assists', 'value': sum(r['Assists'] for r in rows)},
        {'label': 'Top Scorer', 'value': f"{top['Player']} ({top['Goals']})" if top else '—'},
    ]
    chips = []
    if season_id:
        chips.append(f"Season: {_season_name(session, season_id)}")
    if league_name:
        chips.append(f"League: {league_name}")
    if sort != 'goals':
        chips.append(f"Sorted by {sort}")
    if min_goals:
        chips.append(f"Min {min_goals} goals")

    return render_template(
        'admin_panel/reports/leaderboards_flowbite.html',
        seasons=_all_seasons(session),
        leagues=_league_names(session),
        args={'season_id': season_id, 'league_name': league_name, 'sort': sort, 'min_goals': min_goals},
        kpis=kpis,
        chips=chips,
        preview_rows=_preview(rows),
        total_count=len(rows),
    )


@admin_panel_bp.route('/reports/leaderboards/export')
@login_required
@role_required(REPORT_ROLES)
def leaderboards_export():
    guard = _pandas_guard()
    if guard:
        return guard
    rows = _build_leaderboards(
        g.db_session,
        request.args.get('season_id', type=int),
        request.args.get('league') or None,
        request.args.get('sort', 'goals'),
        request.args.get('min_goals', type=int) or 0,
    )
    return _build_xlsx_response([('Leaderboard', rows)], 'leaderboards')


# =====================================================================
# 7. Kit / Jersey Size
# =====================================================================

def _build_jersey(session, league_name, current_only):
    query = (
        session.query(Player)
        .options(joinedload(Player.primary_league), joinedload(Player.primary_team), joinedload(Player.teams))
    )
    if current_only:
        query = query.filter(Player.is_current_player.is_(True))
    if league_name:
        query = query.join(League, Player.primary_league_id == League.id).filter(League.name == league_name)

    summary = defaultdict(int)
    detail = []
    for p in query.all():
        size = (p.jersey_size or '').strip() or 'Unspecified'
        summary[size] += 1
        detail.append({
            'Player': p.name,
            'Primary League': p.primary_league.name if p.primary_league else '',
            'Current Team': _current_team_name(p),
            'Jersey Size': size,
            'Jersey Number': p.jersey_number if p.jersey_number is not None else '',
        })

    summary_rows = [{'Jersey Size': s, 'Players': c} for s, c in summary.items()]
    summary_rows.sort(key=lambda r: (-r['Players'], r['Jersey Size']))
    detail.sort(key=lambda r: (r['Jersey Size'], r['Player'].lower()))
    return {'summary': summary_rows, 'detail': detail}


@admin_panel_bp.route('/reports/jersey-sizes')
@login_required
@role_required(REPORT_ROLES)
def jersey_report():
    session = g.db_session
    league_name = request.args.get('league') or None
    current_only = request.args.get('current_only', type=int)
    data = _build_jersey(session, league_name, current_only)

    total = sum(r['Players'] for r in data['summary'])
    most_common = data['summary'][0]['Jersey Size'] if data['summary'] else '—'
    kpis = [
        {'label': 'Players', 'value': total},
        {'label': 'Distinct Sizes', 'value': len(data['summary'])},
        {'label': 'Most Common Size', 'value': most_common},
    ]
    chips = []
    if league_name:
        chips.append(f"League: {league_name}")
    if current_only:
        chips.append('Current players only')

    return render_template(
        'admin_panel/reports/jersey_flowbite.html',
        leagues=_league_names(session),
        args={'league_name': league_name, 'current_only': current_only},
        kpis=kpis,
        chips=chips,
        preview_rows=_preview(data['summary']),
        total_count=len(data['summary']),
    )


@admin_panel_bp.route('/reports/jersey-sizes/export')
@login_required
@role_required(REPORT_ROLES)
def jersey_export():
    guard = _pandas_guard()
    if guard:
        return guard
    data = _build_jersey(
        g.db_session,
        request.args.get('league') or None,
        request.args.get('current_only', type=int),
    )
    return _build_xlsx_response(
        [('Summary by Size', data['summary']), ('Players', data['detail'])],
        'jersey_sizes',
    )


# =====================================================================
# 8. Team Standings
# =====================================================================

def _build_standings(session, season_id, league_name):
    query = (
        session.query(Standings)
        .options(joinedload(Standings.team).joinedload(Team.league), joinedload(Standings.season))
    )
    if season_id:
        query = query.filter(Standings.season_id == season_id)
    if league_name:
        query = query.join(Team, Standings.team_id == Team.id).join(League, Team.league_id == League.id).filter(League.name == league_name)

    rows = []
    for st in query.all():
        team = st.team
        rows.append({
            'Season': st.season.name if st.season else '',
            'League': team.league.name if team and team.league else '',
            'Team': team.name if team else f'#{st.team_id}',
            'Played': st.played,
            'W': st.wins,
            'D': st.draws,
            'L': st.losses,
            'GF': st.goals_for,
            'GA': st.goals_against,
            'GD': st.goal_difference,
            'Points': st.points,
        })
    rows.sort(key=lambda r: (r['Season'], -r['Points'], -r['GD'], -r['GF']))
    return rows


@admin_panel_bp.route('/reports/standings')
@login_required
@role_required(REPORT_ROLES)
def standings_report():
    session = g.db_session
    season_id = request.args.get('season_id', type=int)
    league_name = request.args.get('league') or None
    rows = _build_standings(session, season_id, league_name)

    kpis = [
        {'label': 'Teams', 'value': len(rows)},
        {'label': 'Matches Played', 'value': sum(r['Played'] for r in rows)},
        {'label': 'Goals Scored', 'value': sum(r['GF'] for r in rows)},
        {'label': 'Top Team', 'value': rows[0]['Team'] if rows else '—'},
    ]
    chips = []
    if season_id:
        chips.append(f"Season: {_season_name(session, season_id)}")
    if league_name:
        chips.append(f"League: {league_name}")

    return render_template(
        'admin_panel/reports/standings_flowbite.html',
        seasons=_all_seasons(session),
        leagues=_league_names(session),
        args={'season_id': season_id, 'league_name': league_name},
        kpis=kpis,
        chips=chips,
        preview_rows=_preview(rows),
        total_count=len(rows),
        highlight_top=1,
    )


@admin_panel_bp.route('/reports/standings/export')
@login_required
@role_required(REPORT_ROLES)
def standings_export():
    guard = _pandas_guard()
    if guard:
        return guard
    rows = _build_standings(
        g.db_session,
        request.args.get('season_id', type=int),
        request.args.get('league') or None,
    )
    return _build_xlsx_response([('Standings', rows)], 'standings')


# =====================================================================
# 9. Discipline (cards by reason)
# =====================================================================

CARD_REASONS = {
    'FOUL': 'Foul',
    'DISSENT': 'Dissent',
    'PERSISTENT_INFRINGEMENT': 'Persistent Infringement',
    'SERIOUS_FOUL_PLAY': 'Serious Foul Play',
}


def _build_discipline(session, season_id):
    query = (
        session.query(PlayerEvent)
        .options(joinedload(PlayerEvent.player).joinedload(Player.primary_team))
        .filter(
            PlayerEvent.event_type.in_([PlayerEventType.YELLOW_CARD, PlayerEventType.RED_CARD]),
            PlayerEvent.player_id.isnot(None),
        )
    )
    if season_id:
        query = (
            query.join(Match, PlayerEvent.match_id == Match.id)
            .join(Schedule, Match.schedule_id == Schedule.id)
            .filter(Schedule.season_id == season_id)
        )

    agg = {}
    for e in query.all():
        player = e.player
        acc = agg.get(e.player_id)
        if acc is None:
            acc = {
                'Player': player.name if player else f'#{e.player_id}',
                'Current Team': _current_team_name(player) if player else '',
                'Yellow Cards': 0, 'Red Cards': 0,
                'Foul': 0, 'Dissent': 0, 'Persistent Infringement': 0,
                'Serious Foul Play': 0, 'Unspecified': 0,
            }
            agg[e.player_id] = acc
        if e.event_type == PlayerEventType.YELLOW_CARD:
            acc['Yellow Cards'] += 1
        else:
            acc['Red Cards'] += 1
        reason_label = CARD_REASONS.get(e.card_reason, 'Unspecified')
        acc[reason_label] += 1

    rows = []
    for acc in agg.values():
        acc['Total Cards'] = acc['Yellow Cards'] + acc['Red Cards']
        rows.append(acc)
    rows.sort(key=lambda r: (-r['Total Cards'], -r['Red Cards'], r['Player'].lower()))
    return rows


@admin_panel_bp.route('/reports/discipline')
@login_required
@role_required(REPORT_ROLES)
def discipline_report():
    session = g.db_session
    season_id = request.args.get('season_id', type=int)
    rows = _build_discipline(session, season_id)

    kpis = [
        {'label': 'Players Booked', 'value': len(rows)},
        {'label': 'Yellow Cards', 'value': sum(r['Yellow Cards'] for r in rows)},
        {'label': 'Red Cards', 'value': sum(r['Red Cards'] for r in rows)},
        {'label': 'Total Cards', 'value': sum(r['Total Cards'] for r in rows)},
    ]
    chips = []
    if season_id:
        chips.append(f"Season: {_season_name(session, season_id)}")

    return render_template(
        'admin_panel/reports/discipline_flowbite.html',
        seasons=_all_seasons(session),
        args={'season_id': season_id},
        kpis=kpis,
        chips=chips,
        preview_rows=_preview(rows),
        total_count=len(rows),
    )


@admin_panel_bp.route('/reports/discipline/export')
@login_required
@role_required(REPORT_ROLES)
def discipline_export():
    guard = _pandas_guard()
    if guard:
        return guard
    rows = _build_discipline(g.db_session, request.args.get('season_id', type=int))
    return _build_xlsx_response([('Discipline', rows)], 'discipline')


# =====================================================================
# 10. Contactability (comms reach)
# =====================================================================

def _build_contactability(session, league_name, current_only):
    query = (
        session.query(Player)
        .options(
            joinedload(Player.user),
            joinedload(Player.primary_league),
            joinedload(Player.primary_team),
            joinedload(Player.teams),
        )
    )
    if current_only:
        query = query.filter(Player.is_current_player.is_(True))
    if league_name:
        query = query.join(League, Player.primary_league_id == League.id).filter(League.name == league_name)

    rows = []
    for p in query.all():
        rows.append({
            'Player': p.name,
            'Primary League': p.primary_league.name if p.primary_league else '',
            'Current Team': _current_team_name(p),
            'Email': p.user.email if p.user else '',
            'Phone Verified': 'Yes' if p.is_phone_verified else 'No',
            'SMS Consent': 'Yes' if p.sms_consent_given else 'No',
            'Discord Linked': 'Yes' if p.discord_id else 'No',
            'In Discord Server': 'Yes' if p.discord_in_server else 'No',
            'Profile Updated': p.profile_last_updated.strftime('%Y-%m-%d') if p.profile_last_updated else '',
        })
    rows.sort(key=lambda r: r['Player'].lower())
    return rows


@admin_panel_bp.route('/reports/contactability')
@login_required
@role_required(REPORT_ROLES)
def contactability_report():
    session = g.db_session
    league_name = request.args.get('league') or None
    current_only = request.args.get('current_only', type=int)
    rows = _build_contactability(session, league_name, current_only)

    total = len(rows)
    sms = sum(1 for r in rows if r['SMS Consent'] == 'Yes')
    discord = sum(1 for r in rows if r['Discord Linked'] == 'Yes')
    verified = sum(1 for r in rows if r['Phone Verified'] == 'Yes')
    kpis = [
        {'label': 'Players', 'value': total},
        {'label': 'SMS-Reachable %', 'value': _pct(sms, total)},
        {'label': 'Discord-Linked %', 'value': _pct(discord, total)},
        {'label': 'Phone-Verified %', 'value': _pct(verified, total)},
    ]
    chips = []
    if league_name:
        chips.append(f"League: {league_name}")
    if current_only:
        chips.append('Current players only')

    return render_template(
        'admin_panel/reports/contactability_flowbite.html',
        leagues=_league_names(session),
        args={'league_name': league_name, 'current_only': current_only},
        kpis=kpis,
        chips=chips,
        preview_rows=_preview(rows),
        total_count=len(rows),
    )


@admin_panel_bp.route('/reports/contactability/export')
@login_required
@role_required(REPORT_ROLES)
def contactability_export():
    guard = _pandas_guard()
    if guard:
        return guard
    rows = _build_contactability(
        g.db_session,
        request.args.get('league') or None,
        request.args.get('current_only', type=int),
    )
    return _build_xlsx_response([('Contactability', rows)], 'contactability')
