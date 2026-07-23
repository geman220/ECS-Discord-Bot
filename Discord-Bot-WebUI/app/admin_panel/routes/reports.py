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
from sqlalchemy import or_
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
        .filter(Season.league_type == 'Pub League')
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
            df = pd.DataFrame(
                [{k: v for k, v in r.items() if not k.startswith('_')} for r in rows]
                if rows else [{'(no data)': 'No records matched the selected filters.'}]
            )
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


def _current_only_default_on():
    """Resolve a 'current players only' checkbox that defaults ON.

    A GET checkbox submits nothing when unchecked, so a plain default-on can never
    be turned off. The filter form carries a hidden ``applied=1`` marker: once the
    form has been submitted we honor the checkbox exactly; on first load (no marker)
    we default to current-players-only so the report isn't diluted by every account
    ever created.
    """
    if request.args.get('applied'):
        return 1 if request.args.get('current_only') else 0
    return 1


def _avg(values):
    return round(sum(values) / len(values), 1) if values else 0.0


# =====================================================================
# Reports hub
# =====================================================================

@admin_panel_bp.route('/reports/center')
@login_required
@role_required(REPORT_ROLES)
def reports_center():
    """Landing page: on-page metrics + charts across all report families.

    All numbers are computed from the same ``_build_*`` helpers the per-report
    pages and Excel exports use, so the dashboard never disagrees with a drill-in
    or a download. Only summary aggregates / capped top-N lists are rendered here
    (the heavy row-level detail lives on the per-report pages).
    """
    session = g.db_session

    from app.utils.analytics_scope import resolve_scope
    from app.services.attendance_analytics import (
        build_attendance_rows, season_pulse, follow_up_lanes,
    )

    TOP_N = 8  # cap for the on-page follow-up lists

    # ---- Attendance (scoped season x league, from the participation spine) --
    # Season and league come from the shared scope resolver, so this reads the
    # rollup instead of the overwritten single-row cache. Turnout is played-based
    # (never counts unplayed fixtures) and league is the real league of play.
    scope = resolve_scope(session)
    pulse = season_pulse(session, scope)
    lanes = follow_up_lanes(session, scope)
    att_rows = build_attendance_rows(session, scope)

    # Turnout distribution for the bar chart. None = no matches played yet (e.g.
    # preseason) and is simply omitted rather than counted as 0%.
    att_buckets = ['0–25%', '26–50%', '51–75%', '76–90%', '91–100%']
    att_bucket_counts = [0, 0, 0, 0, 0]
    for r in att_rows:
        v = r['turnout_pct']
        if v is None:
            continue
        idx = 0 if v <= 25 else 1 if v <= 50 else 2 if v <= 75 else 3 if v <= 90 else 4
        att_bucket_counts[idx] += 1
    attendance_chart = {'labels': att_buckets, 'counts': att_bucket_counts}

    # Cap each lane for the on-page cards; the full lists live on the report.
    slipping = lanes['slipping']
    chronic = lanes['chronic']
    never = lanes['never']
    scope_args = scope.as_query_args()

    # ---- Player Movement ---------------------------------------------------
    movement_rows = _movement_records(session, movers_only=False)
    movement_counts = {c: 0 for c in MOVEMENT_CATEGORIES}
    for r in movement_rows:
        movement_counts[r['Movement']] = movement_counts.get(r['Movement'], 0) + 1
    total_movers = (
        movement_counts['Promoted (Classic→Premier)']
        + movement_counts['Dropped (Premier→Classic)']
        + movement_counts['Both ways']
    )
    movement_chart = {
        'labels': MOVEMENT_CATEGORIES,
        'counts': [movement_counts[c] for c in MOVEMENT_CATEGORIES],
    }

    # ---- Discipline (all-time across seasons) ------------------------------
    discipline_rows = _build_discipline(session, season_id=None)
    reason_labels = ['Foul', 'Dissent', 'Persistent Infringement', 'Serious Foul Play', 'Unspecified']
    reason_counts = [sum(r[label] for r in discipline_rows) for label in reason_labels]
    total_yellow = sum(r['Yellow Cards'] for r in discipline_rows)
    total_red = sum(r['Red Cards'] for r in discipline_rows)
    total_cards = total_yellow + total_red
    top_offenders = discipline_rows[:TOP_N]  # already sorted by total cards desc
    discipline_chart = {
        'labels': reason_labels,
        'counts': reason_counts,
    }

    # ---- Retention / Churn (season over season) ----------------------------
    retention_rows = _build_retention(session)
    latest_ret = retention_rows[-1] if retention_rows else None
    numeric_ret = [r['Retention % (of prior)'] for r in retention_rows
                   if isinstance(r['Retention % (of prior)'], (int, float))]
    retention_chart = {
        'labels': [r['Season'] for r in retention_rows],
        'retention': [r['Retention % (of prior)'] if isinstance(r['Retention % (of prior)'], (int, float)) else None
                      for r in retention_rows],
        'total': [r['Total Players'] for r in retention_rows],
        'new': [r['New Players'] for r in retention_rows],
        'lapsed': [r['Lapsed From Prior'] for r in retention_rows],
    }

    # ---- Top-line stat cards ----------------------------------------------
    stat_cards = [
        {
            'label': 'Season Turnout',
            'value': f"{pulse['turnout_pct']}%" if pulse['turnout_pct'] is not None else '—',
            'icon': 'ti-calendar-check', 'tone': 'primary',
            'note': f"{pulse['players']} players · {scope.season_label}",
            'url': url_for('admin_panel.attendance_report', **scope_args),
        },
        {
            'label': 'Slipping',
            'value': len(slipping),
            'icon': 'ti-trending-down-2', 'tone': 'warn',
            'note': 'below their own baseline',
            'url': url_for('admin_panel.attendance_report', **scope_args),
        },
        {
            'label': 'Never Replied',
            'value': len(never),
            'icon': 'ti-message-off', 'tone': 'info',
            'note': f"no RSVP · {scope.season_label}",
            'url': url_for('admin_panel.attendance_report', **scope_args),
        },
        {
            'label': 'Total Cards',
            'value': total_cards,
            'icon': 'ti-cards', 'tone': 'danger',
            'note': f"{total_yellow} yellow · {total_red} red · all-time",
            'url': url_for('admin_panel.discipline_report'),
        },
        {
            'label': 'Latest Retention',
            'value': (f"{latest_ret['Retention % (of prior)']}%"
                      if latest_ret and isinstance(latest_ret['Retention % (of prior)'], (int, float))
                      else 'n/a'),
            'icon': 'ti-users-group', 'tone': 'ok',
            'note': (f"{latest_ret['Season']}" if latest_ret else 'no seasons'),
            'url': url_for('admin_panel.retention_report'),
        },
    ]

    return render_template(
        'admin_panel/reports/index_flowbite.html',
        stat_cards=stat_cards,
        # attendance — scoped, from the spine
        scope=scope,
        pulse=pulse,
        attendance_chart=attendance_chart,
        attendance_total=len(att_rows),
        slipping=slipping[:TOP_N], slipping_total=len(slipping),
        chronic=chronic[:TOP_N], chronic_total=len(chronic),
        never=never[:TOP_N], never_total=len(never),
        # movement
        movement_chart=movement_chart,
        movement_total=len(movement_rows),
        total_movers=total_movers,
        # discipline
        discipline_chart=discipline_chart,
        total_yellow=total_yellow,
        total_red=total_red,
        total_cards=total_cards,
        players_booked=len(discipline_rows),
        top_offenders=top_offenders,
        # retention
        retention_chart=retention_chart,
        latest_retention=latest_ret,
        avg_retention=_avg(numeric_ret),
        seasons_tracked=len(retention_rows),
        top_n=TOP_N,
    )


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
            '_player_id': s.player_id,
        })

        acc = career.get(s.player_id)
        if acc is None:
            acc = {
                'Player': player.name if player else f'#{s.player_id}',
                'Primary League': player.primary_league.name if player and player.primary_league else '',
                'Current Team': _current_team_name(player) if player else '',
                'Goals': 0, 'Assists': 0, 'Yellow Cards': 0, 'Red Cards': 0,
                '_seasons': set(),
                '_player_id': s.player_id,
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
# 2. Attendance & Turnout  (reads the participation spine)
# =====================================================================
#
# Rewritten off player_season_participation via the shared scope resolver. The
# old version filtered on Player.primary_league_id (a pointer rollover rewrites),
# divided by scheduled-not-played fixtures, and read a one-row-per-player cache
# with no season history. All three are fixed by the spine.

def _attendance_export_rows(rows):
    """Flatten read-service rows into export-friendly dicts (spreadsheet order)."""
    out = []
    for r in rows:
        out.append({
            'Player': r['player'],
            'Team': r['team'],
            'League': r['league'],
            'Played': r['matches_played'],
            'Yes': r['rsvp_yes'],
            'No': r['rsvp_no'],
            'Maybe': r['rsvp_maybe'],
            'No Reply': r['rsvp_none'],
            'Turnout %': r['turnout_pct'] if r['turnout_pct'] is not None else '',
            'Response %': r['response_pct'] if r['response_pct'] is not None else '',
            'Checked In': r['checked_in'],
            'Career Turnout %': r.get('career_turnout') if r.get('career_turnout') is not None else '',
        })
    return out


@admin_panel_bp.route('/reports/attendance')
@login_required
@role_required(REPORT_ROLES)
def attendance_report():
    from app.utils.analytics_scope import resolve_scope
    from app.services.attendance_analytics import (
        build_attendance_rows, career_turnout, week_strips,
    )

    session = g.db_session
    scope = resolve_scope(session)
    min_played = request.args.get('min_played', type=int) or 0
    sort = request.args.get('sort') or 'turnout'

    rows = build_attendance_rows(session, scope, min_played=min_played)

    # Career baseline (lifetime, excludes the import-baseline season) + this
    # season's week-by-week strip so a rate reads as a pattern, not a number.
    career = career_turnout(session, [r['player_id'] for r in rows],
                            exclude_season_ids=scope.baseline_season_ids)
    strips = week_strips(session, scope)
    for r in rows:
        r['career_turnout'] = career.get(r['player_id'], {}).get('turnout')
        r['strip'] = strips.get(r['player_id'], [])

    # Sort. Turnout ascending surfaces who needs a nudge; players with no matches
    # played yet (turnout None) always sort to the bottom, never as "0%".
    def _turn(r):
        return r['turnout_pct'] if r['turnout_pct'] is not None else 999
    if sort == 'name':
        rows.sort(key=lambda r: r['player'].lower())
    elif sort == 'response':
        rows.sort(key=lambda r: (-(r['response_pct'] or 0), r['player'].lower()))
    elif sort == 'low':
        rows.sort(key=lambda r: (_turn(r), -r['matches_played'], r['player'].lower()))
    else:  # 'turnout' — best first
        rows.sort(key=lambda r: (-(r['turnout_pct'] if r['turnout_pct'] is not None else -1),
                                 r['player'].lower()))

    # KPIs from the weighted pulse over the SAME rows (not a mean of rates).
    total_played = sum(r['matches_played'] for r in rows)
    total_yes = sum(r['rsvp_yes'] for r in rows)
    total_answered = sum(r['rsvp_yes'] + r['rsvp_no'] + r['rsvp_maybe'] for r in rows)
    kpis = [
        {'label': 'Players', 'value': len(rows)},
        {'label': 'Turnout %', 'value': _pct(total_yes, total_played)},
        {'label': 'Response %', 'value': _pct(total_answered, total_played)},
        {'label': 'Matches Played', 'value': total_played},
    ]

    # In a multi-season scope a player has one row per season; show a Season column
    # so the otherwise-identical rows are distinguishable.
    show_season = scope.season_ids is None or len(scope.season_ids) > 1

    return render_template(
        'admin_panel/reports/attendance_flowbite.html',
        scope=scope,
        kpis=kpis,
        rows=rows,
        total_count=len(rows),
        sort=sort,
        min_played=min_played,
        show_season=show_season,
    )


@admin_panel_bp.route('/reports/attendance/export')
@login_required
@role_required(REPORT_ROLES)
def attendance_export():
    guard = _pandas_guard()
    if guard:
        return guard
    from app.utils.analytics_scope import resolve_scope
    from app.services.attendance_analytics import build_attendance_rows, career_turnout

    session = g.db_session
    scope = resolve_scope(session)
    min_played = request.args.get('min_played', type=int) or 0
    rows = build_attendance_rows(session, scope, min_played=min_played)
    career = career_turnout(session, [r['player_id'] for r in rows],
                            exclude_season_ids=scope.baseline_season_ids)
    for r in rows:
        r['career_turnout'] = career.get(r['player_id'], {}).get('turnout')
    rows.sort(key=lambda r: (-(r['turnout_pct'] if r['turnout_pct'] is not None else -1),
                             r['player'].lower()))
    return _build_xlsx_response([('Attendance', _attendance_export_rows(rows))], 'attendance')


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
            '_player_id': player_id,
        })

    results.sort(key=lambda r: (r['Movement'], r['Player'].lower()))
    return results


def _season_league(session, season_id):
    """{player_id: 'Premier'|'Classic'|<other league>} for one pub-league season.

    Dual-league players resolve to Premier (the higher tier), matching the movement
    path logic.
    """
    rows = (
        session.query(PlayerTeamSeason.player_id, League.name)
        .join(Team, PlayerTeamSeason.team_id == Team.id)
        .join(League, Team.league_id == League.id)
        .filter(PlayerTeamSeason.season_id == season_id)
        .all()
    )
    by_player = defaultdict(set)
    for pid, lname in rows:
        by_player[pid].add(lname)
    out = {}
    for pid, leagues in by_player.items():
        if 'Premier' in leagues:
            out[pid] = 'Premier'
        elif 'Classic' in leagues:
            out[pid] = 'Classic'
        else:
            out[pid] = sorted(leagues)[0]
    return out


# Flow band styling: (from, to) -> (css tone key). Kept literal so the meaning of
# each ribbon is explicit rather than guessed from color.
MOVEMENT_FLOW_ORDER = [
    ('Premier', 'Premier'), ('Premier', 'Classic'), ('Premier', 'Lapsed'),
    ('Classic', 'Premier'), ('Classic', 'Classic'), ('Classic', 'Lapsed'),
    ('New', 'Premier'), ('New', 'Classic'),
]


def _movement_flow(session, from_id, to_id):
    """Season-to-season flow between two pub-league seasons.

    Returns geometry for a proportional Sankey: left nodes (Premier/Classic/New),
    right nodes (Premier/Classic/Lapsed), and ribbons sized by player count. All
    band positions are computed here so the template just draws paths.
    """
    a = _season_league(session, from_id)
    b = _season_league(session, to_id)

    # Movement is a Premier↔Classic story, so only the two divisions are nodes. A
    # player in some other pub league (shouldn't happen, but be safe) is skipped
    # rather than silently miscounted as Classic; leaving the divisions entirely
    # reads as Lapsed.
    flow = defaultdict(int)
    for pid, la in a.items():
        if la not in ('Premier', 'Classic'):
            continue
        dst = b.get(pid)
        dst = dst if dst in ('Premier', 'Classic') else 'Lapsed'
        flow[(la, dst)] += 1
    for pid, lb in b.items():
        if pid in a or lb not in ('Premier', 'Classic'):
            continue
        flow[('New', lb)] += 1

    left_nodes = ['Premier', 'Classic', 'New']
    right_nodes = ['Premier', 'Classic', 'Lapsed']
    left_tot = {n: sum(c for (s, d), c in flow.items() if s == n) for n in left_nodes}
    right_tot = {n: sum(c for (s, d), c in flow.items() if d == n) for n in right_nodes}

    H, GAP = 320.0, 16.0

    def stack(nodes, totals):
        active = [n for n in nodes if totals[n] > 0]
        avail = H - GAP * max(len(active) - 1, 0)
        scale = avail / (sum(totals[n] for n in active) or 1)
        pos, y = {}, 10.0
        for n in active:
            h = totals[n] * scale
            pos[n] = (y, h)
            y += h + GAP
        return pos, scale

    lpos, lscale = stack(left_nodes, left_tot)
    rpos, rscale = stack(right_nodes, right_tot)
    lcur = {n: lpos[n][0] for n in lpos}
    rcur = {n: rpos[n][0] for n in rpos}

    bands = []
    for (src, dst) in MOVEMENT_FLOW_ORDER:
        c = flow.get((src, dst), 0)
        if not c or src not in lpos or dst not in rpos:
            continue
        th_l, th_r = c * lscale, c * rscale
        y0, y1 = lcur[src], rcur[dst]
        bands.append({
            'src': src, 'dst': dst, 'count': c,
            'y0_top': round(y0, 1), 'y0_bot': round(y0 + th_l, 1),
            'y1_top': round(y1, 1), 'y1_bot': round(y1 + th_r, 1),
        })
        lcur[src] += th_l
        rcur[dst] += th_r

    return {
        'left': [{'name': n, 'y': round(lpos[n][0], 1), 'h': round(lpos[n][1], 1),
                  'total': left_tot[n]} for n in left_nodes if n in lpos],
        'right': [{'name': n, 'y': round(rpos[n][0], 1), 'h': round(rpos[n][1], 1),
                   'total': right_tot[n]} for n in right_nodes if n in rpos],
        'bands': bands,
        'promoted': flow.get(('Classic', 'Premier'), 0),
        'dropped': flow.get(('Premier', 'Classic'), 0),
        'lapsed': right_tot['Lapsed'],
        'new': left_tot['New'],
    }


@admin_panel_bp.route('/reports/movement')
@login_required
@role_required(REPORT_ROLES)
def movement_report():
    session = g.db_session
    movers_only = request.args.get('movers_only', type=int)
    rows = _movement_records(session, movers_only=bool(movers_only))

    # Season-to-season flow diagram. Defaults to the two most recent pub seasons;
    # ?from=&to= override. Only meaningful with at least two seasons.
    pub_seasons = _pub_league_seasons(session)  # oldest → newest
    flow = None
    flow_from = flow_to = None
    if len(pub_seasons) >= 2:
        from_id = request.args.get('from', type=int) or pub_seasons[-2].id
        to_id = request.args.get('to', type=int) or pub_seasons[-1].id
        valid = {s.id for s in pub_seasons}
        if from_id in valid and to_id in valid and from_id != to_id:
            flow = _movement_flow(session, from_id, to_id)
            flow_from = next(s for s in pub_seasons if s.id == from_id)
            flow_to = next(s for s in pub_seasons if s.id == to_id)

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
        flow=flow,
        flow_from=flow_from,
        flow_to=flow_to,
        pub_seasons=[{'id': s.id, 'name': s.name} for s in pub_seasons],
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

def _retention_cohorts(session):
    """Per-season cohort membership across pub-league seasons (oldest→newest).

    Returns an ordered list of (season, cohorts, prev_season) where cohorts is
    {'new', 'returning', 'lapsed', 'current'} -> set(player_id). `prev_season` is
    the prior Season (or None for the first). Single source of truth for both the
    retention summary counts and the per-cohort player drill-in.
    """
    seasons = _pub_league_seasons(session)
    members = defaultdict(set)
    pairs = (
        session.query(PlayerTeamSeason.season_id, PlayerTeamSeason.player_id)
        .filter(PlayerTeamSeason.season_id.in_([s.id for s in seasons]))
        .all()
    )
    for season_id, player_id in pairs:
        members[season_id].add(player_id)

    out = []
    prev_season, prev_set = None, None
    for s in seasons:
        cur = members.get(s.id, set())
        if prev_set is None:
            cohorts = {'new': set(cur), 'returning': set(), 'lapsed': set(), 'current': cur}
        else:
            cohorts = {'new': cur - prev_set, 'returning': cur & prev_set,
                       'lapsed': prev_set - cur, 'current': cur}
        out.append((s, cohorts, prev_season))
        prev_season, prev_set = s, cur
    return out


def _retention_cohort_grid(session):
    """Triangular retention cohorts: of players who JOINED in season S, what share
    are still rostered S+1, S+2, … later.

    A cohort = players whose FIRST pub-league season is S. Reading across a row
    shows how that one intake decays over time — which a single season-over-season
    line can't separate from "the import season was thin".

    Returns {'rows': [...], 'max_offset': int, 'avg_next': float|None} where each row
    is {season, is_baseline, joined, cells:[{offset,pct,n}|None]}. Cells past the
    latest season are None (not yet knowable). Import-baseline cohorts are flagged
    and excluded from the averages the UI shows.
    """
    seasons = _pub_league_seasons(session)  # oldest → newest
    if not seasons:
        return {'rows': [], 'max_offset': 0, 'avg_next': None}

    members = defaultdict(set)
    for sid, pid in (
        session.query(PlayerTeamSeason.season_id, PlayerTeamSeason.player_id)
        .filter(PlayerTeamSeason.season_id.in_([s.id for s in seasons])).all()
    ):
        members[sid].add(pid)

    # First season index per player → their joining cohort.
    first_idx = {}
    for i, s in enumerate(seasons):
        for pid in members.get(s.id, ()):
            if pid not in first_idx:
                first_idx[pid] = i
    cohort = defaultdict(set)
    for pid, i in first_idx.items():
        cohort[i].add(pid)

    n = len(seasons)
    rows = []
    next_pcts = []  # +1 retention across non-baseline cohorts, for the average
    for i, s in enumerate(seasons):
        joiners = cohort.get(i, set())
        joined = len(joiners)
        is_baseline = bool(getattr(s, 'is_analytics_baseline', False))
        cells = []
        for k in range(0, n - i):
            still = len(joiners & members.get(seasons[i + k].id, set())) if joined else 0
            pct = round(still / joined * 100, 1) if joined else None
            cells.append({'offset': k, 'pct': pct, 'n': still})
            if k == 1 and pct is not None and not is_baseline:
                next_pcts.append(pct)
        rows.append({
            'season': s.name,
            'is_baseline': is_baseline,
            'joined': joined,
            'cells': cells,
        })

    return {
        'rows': rows,
        'max_offset': max((len(r['cells']) for r in rows), default=0),
        'avg_next': round(sum(next_pcts) / len(next_pcts), 1) if next_pcts else None,
    }


def _build_retention(session):
    rows = []
    for s, c, prev_season in _retention_cohorts(session):
        prev_total = len(c['returning']) + len(c['lapsed'])
        retention = _pct(len(c['returning']), prev_total) if prev_season else None
        rows.append({
            'Season': s.name,
            'Total Players': len(c['current']),
            'New Players': len(c['new']),
            'Returning': len(c['returning']),
            'Lapsed From Prior': len(c['lapsed']),
            'Retention % (of prior)': retention if retention is not None else 'n/a',
            '_season_id': s.id,
        })
    return rows


# Which season a cohort's "team that season" should come from.
RETENTION_COHORTS = {'new', 'returning', 'lapsed'}


def _retention_cohort_players(session, season_id, cohort):
    """The actual players behind a retention cohort count (drill-in)."""
    if cohort not in RETENTION_COHORTS:
        return []
    data = _retention_cohorts(session)
    entry = next((e for e in data if e[0].id == season_id), None)
    if not entry:
        return []
    season, cohorts, prev_season = entry
    player_ids = cohorts.get(cohort, set())
    if not player_ids:
        return []
    # Lapsed players were rostered the PRIOR season (not this one), so show that team.
    team_season_id = prev_season.id if (cohort == 'lapsed' and prev_season) else season_id
    team_map = dict(
        session.query(PlayerTeamSeason.player_id, Team.name)
        .join(Team, PlayerTeamSeason.team_id == Team.id)
        .filter(PlayerTeamSeason.player_id.in_(player_ids),
                PlayerTeamSeason.season_id == team_season_id)
        .all()
    )
    players = (
        session.query(Player)
        .options(joinedload(Player.primary_league))
        .filter(Player.id.in_(player_ids))
        .all()
    )
    rows = [{
        'Player': p.name,
        'Primary League': p.primary_league.name if p.primary_league else '',
        'Team (that season)': team_map.get(p.id, '—'),
        '_player_id': p.id,
    } for p in players]
    rows.sort(key=lambda r: r['Player'].lower())
    return rows


@admin_panel_bp.route('/reports/retention')
@login_required
@role_required(REPORT_ROLES)
def retention_report():
    session = g.db_session

    # Drill-in: ?season_id=&cohort=new|returning|lapsed → the players behind a count.
    season_id = request.args.get('season_id', type=int)
    cohort = request.args.get('cohort')
    if season_id and cohort in RETENTION_COHORTS:
        detail_rows = _retention_cohort_players(session, season_id, cohort)
        cohort_label = {'new': 'New', 'returning': 'Returning', 'lapsed': 'Lapsed'}[cohort]
        return render_template(
            'admin_panel/reports/retention_flowbite.html',
            detail_mode=True,
            detail_title=f"{cohort_label} players — {_season_name(session, season_id)}",
            preview_rows=detail_rows,
            total_count=len(detail_rows),
        )

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

    cohort_grid = _retention_cohort_grid(session)

    return render_template(
        'admin_panel/reports/retention_flowbite.html',
        detail_mode=False,
        kpis=kpis,
        chart_data=chart_data,
        cohort_grid=cohort_grid,
        summary_rows=rows,
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
            '_player_id': a.player_id,
            '_team_id': team.id if team else None,
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
                '_player_id': s.player_id,
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
        {'label': 'Top Scorer', 'value': f"{top['Player']} ({top['Goals']})" if top else '—',
         'url': (url_for('players.player_profile', player_id=top['_player_id'])
                 if top and top.get('_player_id') else None)},
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
            '_player_id': p.id,
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
    current_only = _current_only_default_on()
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
        _current_only_default_on(),
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
            '_team_id': st.team_id,
        })
    # Sort within (Season, League) so Premier and Classic don't interleave into one
    # points-ordered list that looks like a single league table but isn't.
    rows.sort(key=lambda r: (r['Season'], r['League'], -r['Points'], -r['GD'], -r['GF']))
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
        # Each match appears once per team in the Standings table, so sum(Played) is
        # exactly 2× the real match count. Halve it (round up for an odd cross-league
        # straggler) so the KPI reads as actual matches, not team-appearances.
        {'label': 'Matches Played', 'value': (sum(r['Played'] for r in rows) + 1) // 2},
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


def _build_discipline(session, season_id, card_type=None, reason=None):
    # card_type: 'yellow' / 'red' / None(=both). reason: a CARD_REASONS key
    # (e.g. 'FOUL'), 'UNSPECIFIED', or None(=all reasons).
    event_types = [PlayerEventType.YELLOW_CARD, PlayerEventType.RED_CARD]
    if card_type == 'yellow':
        event_types = [PlayerEventType.YELLOW_CARD]
    elif card_type == 'red':
        event_types = [PlayerEventType.RED_CARD]
    query = (
        session.query(PlayerEvent)
        .options(joinedload(PlayerEvent.player).joinedload(Player.primary_team))
        .filter(
            PlayerEvent.event_type.in_(event_types),
            PlayerEvent.player_id.isnot(None),
        )
    )
    if reason == 'UNSPECIFIED':
        query = query.filter(or_(PlayerEvent.card_reason.is_(None),
                                 PlayerEvent.card_reason.notin_(list(CARD_REASONS.keys()))))
    elif reason:
        query = query.filter(PlayerEvent.card_reason == reason)
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
                '_player_id': e.player_id,
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
    card_type = request.args.get('card_type') or None
    reason = request.args.get('reason') or None
    rows = _build_discipline(session, season_id, card_type=card_type, reason=reason)

    kpis = [
        {'label': 'Players Booked', 'value': len(rows)},
        {'label': 'Yellow Cards', 'value': sum(r['Yellow Cards'] for r in rows)},
        {'label': 'Red Cards', 'value': sum(r['Red Cards'] for r in rows)},
        {'label': 'Total Cards', 'value': sum(r['Total Cards'] for r in rows)},
    ]
    chips = []
    if season_id:
        chips.append(f"Season: {_season_name(session, season_id)}")
    if card_type in ('yellow', 'red'):
        chips.append(f"{card_type.title()} cards only")
    if reason:
        chips.append(f"Reason: {CARD_REASONS.get(reason, reason.replace('_', ' ').title())}")

    return render_template(
        'admin_panel/reports/discipline_flowbite.html',
        seasons=_all_seasons(session),
        card_reasons=CARD_REASONS,
        args={'season_id': season_id, 'card_type': card_type, 'reason': reason},
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
    rows = _build_discipline(
        g.db_session, request.args.get('season_id', type=int),
        card_type=request.args.get('card_type') or None,
        reason=request.args.get('reason') or None,
    )
    return _build_xlsx_response([('Discipline', rows)], 'discipline')


# =====================================================================
# 10. Contactability (comms reach)
# =====================================================================

# Contactability segment -> predicate over a built row (the actionable "gaps").
CONTACT_SEGMENTS = {
    'missing_email': ('Missing email', lambda r: not r['Email']),
    'missing_phone': ('Phone unverified', lambda r: r['Phone Verified'] == 'No'),
    'no_sms': ('No SMS consent', lambda r: r['SMS Consent'] == 'No'),
    'no_discord': ('Not on Discord', lambda r: r['Discord Linked'] == 'No'),
    'unreachable': ('Unreachable (no SMS & no Discord)',
                    lambda r: r['SMS Consent'] == 'No' and r['Discord Linked'] == 'No'),
}


def _build_contactability(session, league_name, current_only, segment=None):
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
            '_player_id': p.id,
        })
    seg = CONTACT_SEGMENTS.get(segment)
    if seg:
        rows = [r for r in rows if seg[1](r)]
    rows.sort(key=lambda r: r['Player'].lower())
    return rows


@admin_panel_bp.route('/reports/contactability')
@login_required
@role_required(REPORT_ROLES)
def contactability_report():
    session = g.db_session
    league_name = request.args.get('league') or None
    current_only = _current_only_default_on()
    segment = request.args.get('segment') or None
    # KPIs reflect the full (unsegmented) population; the table shows the segment.
    all_rows = _build_contactability(session, league_name, current_only)
    seg = CONTACT_SEGMENTS.get(segment)
    rows = [r for r in all_rows if seg[1](r)] if seg else all_rows

    total = len(all_rows)
    sms = sum(1 for r in all_rows if r['SMS Consent'] == 'Yes')
    discord = sum(1 for r in all_rows if r['Discord Linked'] == 'Yes')
    verified = sum(1 for r in all_rows if r['Phone Verified'] == 'Yes')
    # applied=1 so _current_only_default_on() honors the current_only value on the
    # drill-in instead of snapping back to the default-on.
    _seg_url = lambda s: url_for('admin_panel.contactability_report', league=league_name,
                                 current_only=current_only, applied=1, segment=s)
    kpis = [
        {'label': 'Players', 'value': total},
        {'label': 'SMS-Reachable %', 'value': _pct(sms, total), 'url': _seg_url('no_sms')},
        {'label': 'Discord-Linked %', 'value': _pct(discord, total), 'url': _seg_url('no_discord')},
        {'label': 'Phone-Verified %', 'value': _pct(verified, total), 'url': _seg_url('missing_phone')},
    ]
    chips = []
    if league_name:
        chips.append(f"League: {league_name}")
    if current_only:
        chips.append('Current players only')
    if seg:
        chips.append(seg[0])

    return render_template(
        'admin_panel/reports/contactability_flowbite.html',
        leagues=_league_names(session),
        contact_segments=CONTACT_SEGMENTS,
        args={'league_name': league_name, 'current_only': current_only, 'segment': segment},
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
        _current_only_default_on(),
        segment=request.args.get('segment') or None,
    )
    return _build_xlsx_response([('Contactability', rows)], 'contactability')
