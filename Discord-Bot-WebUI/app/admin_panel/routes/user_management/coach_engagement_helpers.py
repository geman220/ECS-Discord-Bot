# app/admin_panel/routes/user_management/coach_engagement_helpers.py

"""
Coach Engagement analytics.

Answers "which coaches are actually doing the work vs. coach-in-name-only" by
combining, per team per season, every per-coach signal we capture:

  - match reports   : PlayerEvent.reported_by  (web + mobile)
  - score verifies  : Match.{home,away}_team_verified_by
  - lineups         : MatchLineup.created_by / last_updated_by
  - RSVP work        : CoachEngagementEvent (views/reminders/overrides, web+mobile)
  - team chat        : DiscordMessageStat (team channel messages)

Scoping note: Pub League teams are RECREATED each season, so a team_id already
encodes exactly one (team, season). Filtering by a season's team_ids therefore
scopes reports/lineups/RSVP/chat to that season without any date math. Coach
identity (player_teams.is_coach) is a current-only flag, so engagement is most
reliable for the CURRENT season; prior seasons degrade as rosters get rewritten.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, or_

from app.models import (
    Team, Player, Match, League, Season, MatchLineup, PlayerEvent,
    player_teams, CoachEngagementEvent, DiscordMessageStat,
)

logger = logging.getLogger(__name__)

# Weights turning heterogeneous signals into one comparable activity score.
# Tunable in one place. Reports + lineups are the core coaching duties, so they
# carry the most weight; chat/RSVP are supporting signals.
WEIGHTS = {
    'matches_reported': 3,
    'matches_verified': 1,
    'lineups_set': 3,
    'rsvp_reminders': 2,
    'rsvp_active_days': 1,
    'discord_active_days': 1,
}
RSVP_ACTION_TYPES = ('rsvp_view', 'rsvp_reminder', 'rsvp_override')
# A coach is "carrying" the team if they own most of the tracked work AND the
# team has other coaches who are doing materially less.
CARRY_THRESHOLD_PCT = 60


def list_engagement_seasons(session):
    """Seasons that actually have teams, newest first, with current flagged."""
    rows = (
        session.query(Season.id, Season.name, Season.league_type, Season.is_current)
        .join(League, League.season_id == Season.id)
        .join(Team, Team.league_id == League.id)
        .distinct()
        .order_by(Season.is_current.desc(), Season.id.desc())
        .all()
    )
    return [
        {'id': r.id, 'name': r.name, 'league_type': r.league_type, 'is_current': r.is_current}
        for r in rows
    ]


def _resolve_season(session, season_id):
    """Return the Season to analyze: explicit id, else current Pub League, else newest."""
    if season_id:
        season = session.query(Season).get(int(season_id))
        if season:
            return season
    season = (
        session.query(Season)
        .filter(Season.league_type == 'Pub League', Season.is_current == True)  # noqa: E712
        .first()
    )
    if season:
        return season
    return session.query(Season).order_by(Season.id.desc()).first()


def _activity_score(metrics):
    return sum(metrics.get(k, 0) * w for k, w in WEIGHTS.items())


def get_coach_engagement(session, season_id=None):
    """Build the per-team, per-coach engagement breakdown for one season."""
    season = _resolve_season(session, season_id)
    if not season:
        return {
            'season': None,
            'available_seasons': list_engagement_seasons(session),
            'teams': [],
            'summary': {},
            'generated_at': datetime.utcnow().isoformat(),
        }

    # --- teams in this season -------------------------------------------------
    team_rows = (
        session.query(Team.id, Team.name, League.name.label('league_name'))
        .join(League, Team.league_id == League.id)
        .filter(League.season_id == season.id, Team.is_active == True)  # noqa: E712
        .order_by(League.name, Team.name)
        .all()
    )
    team_ids = [t.id for t in team_rows]
    if not team_ids:
        return {
            'season': season.to_dict(),
            'available_seasons': list_engagement_seasons(session),
            'teams': [],
            'summary': {'teams': 0, 'coaches': 0, 'inactive_coaches': 0,
                        'teams_with_carrier': 0, 'teams_fully_active': 0},
            'generated_at': datetime.utcnow().isoformat(),
        }

    # --- coaches per team -----------------------------------------------------
    coach_rows = (
        session.query(
            player_teams.c.team_id,
            Player.id.label('player_id'),
            Player.name,
            Player.user_id,
            Player.discord_id,
        )
        .join(Player, Player.id == player_teams.c.player_id)
        .filter(player_teams.c.team_id.in_(team_ids), player_teams.c.is_coach == True)  # noqa: E712
        .all()
    )
    # team_id -> [coach dict]; (team_id, user_id) -> coach dict
    coaches_by_team = {tid: [] for tid in team_ids}
    coach_index = {}
    coach_user_ids = set()
    coach_discord_ids = set()
    for r in coach_rows:
        if not r.user_id:
            continue
        entry = {
            'user_id': r.user_id,
            'player_id': r.player_id,
            'name': r.name,
            'discord_id': r.discord_id,
            'discord_linked': bool(r.discord_id),
            'matches_reported': 0,
            'matches_verified': 0,
            'lineups_set': 0,
            'rsvp_views': 0,
            'rsvp_reminders': 0,
            'rsvp_active_days': 0,
            'discord_messages': 0,
            'discord_active_days': 0,
            'last_discord_at': None,
            'last_report_at': None,
            'last_rsvp_at': None,
            'last_lineup_at': None,
        }
        coaches_by_team[r.team_id].append(entry)
        coach_index[(r.team_id, r.user_id)] = entry
        coach_user_ids.add(r.user_id)
        if r.discord_id:
            coach_discord_ids.add(str(r.discord_id))

    # --- matches in this season (real matches only) ---------------------------
    match_rows = (
        session.query(
            Match.id, Match.home_team_id, Match.away_team_id,
            Match.home_team_score, Match.away_team_score,
            Match.reported_at,
            Match.home_team_verified_by, Match.home_team_verified_at,
            Match.away_team_verified_by, Match.away_team_verified_at,
        )
        .filter(
            or_(Match.home_team_id.in_(team_ids), Match.away_team_id.in_(team_ids)),
            Match.home_team_id != Match.away_team_id,  # drop BYE/special self-matches
        )
        .all()
    )
    match_ids = [m.id for m in match_rows]
    # team_id -> match count / reported count
    team_match_count = {tid: 0 for tid in team_ids}
    team_reported_count = {tid: 0 for tid in team_ids}
    for m in match_rows:
        reported = m.home_team_score is not None and m.away_team_score is not None
        for tid in (m.home_team_id, m.away_team_id):
            if tid in team_match_count:
                team_match_count[tid] += 1
                if reported:
                    team_reported_count[tid] += 1
        # verifier attribution
        if m.home_team_verified_by and (m.home_team_id, m.home_team_verified_by) in coach_index:
            c = coach_index[(m.home_team_id, m.home_team_verified_by)]
            c['matches_verified'] += 1
            c['last_report_at'] = _max_dt(c['last_report_at'], m.home_team_verified_at or m.reported_at)
        if m.away_team_verified_by and (m.away_team_id, m.away_team_verified_by) in coach_index:
            c = coach_index[(m.away_team_id, m.away_team_verified_by)]
            c['matches_verified'] += 1
            c['last_report_at'] = _max_dt(c['last_report_at'], m.away_team_verified_at or m.reported_at)

    # match_id -> (home_team_id, away_team_id) for report attribution
    match_teams = {m.id: (m.home_team_id, m.away_team_id) for m in match_rows}

    # --- match reports via PlayerEvent.reported_by ----------------------------
    # Distinct (reporter_user, match) pairs → attribute to whichever of that
    # match's two teams the reporter coaches.
    if match_ids:
        ev_rows = (
            session.query(PlayerEvent.match_id, PlayerEvent.reported_by)
            .filter(
                PlayerEvent.match_id.in_(match_ids),
                PlayerEvent.reported_by.isnot(None),
            )
            .distinct()
            .all()
        )
        for match_id, reporter in ev_rows:
            home_tid, away_tid = match_teams.get(match_id, (None, None))
            for tid in (home_tid, away_tid):
                key = (tid, reporter)
                if key in coach_index:
                    coach_index[key]['matches_reported'] += 1

    # --- lineups via MatchLineup ----------------------------------------------
    lineup_rows = (
        session.query(
            MatchLineup.team_id, MatchLineup.created_by,
            MatchLineup.last_updated_by, MatchLineup.updated_at,
        )
        .filter(MatchLineup.team_id.in_(team_ids))
        .all()
    )
    for lr in lineup_rows:
        # Credit the creator; if a different coach last edited, credit them too.
        editors = {lr.created_by}
        if lr.last_updated_by:
            editors.add(lr.last_updated_by)
        for uid in editors:
            key = (lr.team_id, uid)
            if key in coach_index:
                coach_index[key]['lineups_set'] += 1
                coach_index[key]['last_lineup_at'] = _max_dt(
                    coach_index[key]['last_lineup_at'], lr.updated_at)

    # --- RSVP engagement (CoachEngagementEvent) -------------------------------
    if coach_user_ids:
        ce_rows = (
            session.query(
                CoachEngagementEvent.user_id,
                CoachEngagementEvent.team_id,
                CoachEngagementEvent.activity_type,
                func.sum(CoachEngagementEvent.count).label('total'),
                func.count(func.distinct(CoachEngagementEvent.stat_date)).label('days'),
                func.max(CoachEngagementEvent.last_at).label('last_at'),
            )
            .filter(
                CoachEngagementEvent.team_id.in_(team_ids),
                CoachEngagementEvent.user_id.in_(coach_user_ids),
                CoachEngagementEvent.activity_type.in_(RSVP_ACTION_TYPES),
            )
            .group_by(
                CoachEngagementEvent.user_id,
                CoachEngagementEvent.team_id,
                CoachEngagementEvent.activity_type,
            )
            .all()
        )
        # accumulate active-day sets approximately via summed distinct days per type
        for row in ce_rows:
            key = (row.team_id, row.user_id)
            c = coach_index.get(key)
            if not c:
                continue
            if row.activity_type == 'rsvp_reminder':
                c['rsvp_reminders'] += int(row.total or 0)
            elif row.activity_type == 'rsvp_view':
                c['rsvp_views'] += int(row.total or 0)
            # rsvp_override folds into general activity via reminders weighting? keep as view-like
            c['rsvp_active_days'] = max(c['rsvp_active_days'], int(row.days or 0))
            c['last_rsvp_at'] = _max_dt(c['last_rsvp_at'], row.last_at)

    # --- Discord team-channel chat (DiscordMessageStat) -----------------------
    if coach_discord_ids:
        dm_rows = (
            session.query(
                DiscordMessageStat.team_id,
                DiscordMessageStat.discord_user_id,
                func.sum(DiscordMessageStat.message_count).label('msgs'),
                func.count(func.distinct(DiscordMessageStat.stat_date)).label('days'),
                func.max(DiscordMessageStat.last_message_at).label('last_at'),
            )
            .filter(
                DiscordMessageStat.team_id.in_(team_ids),
                DiscordMessageStat.discord_user_id.in_(coach_discord_ids),
            )
            .group_by(DiscordMessageStat.team_id, DiscordMessageStat.discord_user_id)
            .all()
        )
        # discord_user_id -> coach entries (per team). Match on team + discord id.
        discord_to_user = {}
        for (tid, uid), c in coach_index.items():
            if c['discord_id']:
                discord_to_user[(tid, str(c['discord_id']))] = c
        for row in dm_rows:
            c = discord_to_user.get((row.team_id, str(row.discord_user_id)))
            if not c:
                continue
            c['discord_messages'] += int(row.msgs or 0)
            c['discord_active_days'] = max(c['discord_active_days'], int(row.days or 0))
            c['last_discord_at'] = _max_dt(c['last_discord_at'], row.last_at)

    # --- assemble per-team output --------------------------------------------
    teams_out = []
    total_coaches = 0
    inactive_coaches = 0
    teams_with_carrier = 0
    teams_fully_active = 0

    for t in team_rows:
        coaches = coaches_by_team.get(t.id, [])
        for c in coaches:
            c['activity_score'] = _activity_score(c)
            c['last_active'] = _max_iso(
                c['last_report_at'], c['last_rsvp_at'],
                c['last_lineup_at'], c['last_discord_at'])
            c['is_inactive'] = c['activity_score'] == 0
        team_score = sum(c['activity_score'] for c in coaches) or 0
        for c in coaches:
            c['contribution_pct'] = (
                round(c['activity_score'] / team_score * 100) if team_score else 0)
            # clean up internal datetime objects → iso strings
            for k in ('last_report_at', 'last_rsvp_at', 'last_lineup_at', 'last_discord_at'):
                c[k] = _to_iso(c[k])
            c.pop('discord_id', None)

        coaches.sort(key=lambda x: x['activity_score'], reverse=True)

        active = [c for c in coaches if not c['is_inactive']]
        team_inactive = [c for c in coaches if c['is_inactive']]
        has_carrier = bool(
            len(coaches) > 1 and coaches and team_score > 0
            and coaches[0]['contribution_pct'] >= CARRY_THRESHOLD_PCT
            and len(active) < len(coaches)
        )

        total_coaches += len(coaches)
        inactive_coaches += len(team_inactive)
        if has_carrier:
            teams_with_carrier += 1
        if coaches and not team_inactive:
            teams_fully_active += 1

        teams_out.append({
            'team_id': t.id,
            'team_name': t.name,
            'league_name': t.league_name,
            'total_matches': team_match_count.get(t.id, 0),
            'reported_matches': team_reported_count.get(t.id, 0),
            'unreported_matches': team_match_count.get(t.id, 0) - team_reported_count.get(t.id, 0),
            'coaches': coaches,
            'coach_count': len(coaches),
            'inactive_coach_count': len(team_inactive),
            'has_carrier': has_carrier,
            'team_activity_score': team_score,
        })

    # surface the most lopsided / least-covered teams first
    teams_out.sort(key=lambda x: (
        -int(x['has_carrier']),
        -x['inactive_coach_count'],
        -x['unreported_matches'],
        x['team_name'],
    ))

    return {
        'season': season.to_dict(),
        'available_seasons': list_engagement_seasons(session),
        'teams': teams_out,
        'summary': {
            'teams': len(teams_out),
            'coaches': total_coaches,
            'inactive_coaches': inactive_coaches,
            'teams_with_carrier': teams_with_carrier,
            'teams_fully_active': teams_fully_active,
        },
        'generated_at': datetime.utcnow().isoformat(),
    }


STALE_CHANNEL_DAYS = 14


def get_discord_channel_metrics(session, season_id=None, days=None):
    """Community-level Discord channel usage + actionable engagement signals.

    Per channel: messages, distinct senders, active days, last activity, days
    since active + stale flag, and sender concentration (top poster's share —
    high = one person carrying the channel). Plus a community member leaderboard,
    a weekly message trend, and silent team channels (dead channels are visible,
    not just busy ones).

    days: optional recency window (e.g. 90). None = all-time.
    """
    season = _resolve_season(session, season_id)
    now = datetime.utcnow()
    cutoff = (now - timedelta(days=days)).date() if days else None

    def _window(q):
        return q.filter(DiscordMessageStat.stat_date >= cutoff) if cutoff else q

    # --- per-channel aggregates ----------------------------------------------
    channel_rows = _window(
        session.query(
            DiscordMessageStat.channel_id,
            func.max(DiscordMessageStat.channel_name).label('channel_name'),
            DiscordMessageStat.team_id,
            func.sum(DiscordMessageStat.message_count).label('msgs'),
            func.count(func.distinct(DiscordMessageStat.discord_user_id)).label('senders'),
            func.count(func.distinct(DiscordMessageStat.stat_date)).label('active_days'),
            func.max(DiscordMessageStat.last_message_at).label('last_at'),
        )
        .group_by(DiscordMessageStat.channel_id, DiscordMessageStat.team_id)
    ).all()

    # --- per-(channel,user) totals → top-sender concentration ----------------
    cu_rows = _window(
        session.query(
            DiscordMessageStat.channel_id,
            DiscordMessageStat.discord_user_id,
            func.sum(DiscordMessageStat.message_count).label('msgs'),
        ).group_by(DiscordMessageStat.channel_id, DiscordMessageStat.discord_user_id)
    ).all()
    top_sender = {}  # channel_id -> (discord_user_id, msgs)
    for r in cu_rows:
        cur = top_sender.get(r.channel_id)
        if cur is None or (r.msgs or 0) > cur[1]:
            top_sender[r.channel_id] = (r.discord_user_id, int(r.msgs or 0))

    # --- community member leaderboard ----------------------------------------
    member_rows = _window(
        session.query(
            DiscordMessageStat.discord_user_id,
            func.sum(DiscordMessageStat.message_count).label('msgs'),
            func.count(func.distinct(DiscordMessageStat.channel_id)).label('channels'),
            func.max(DiscordMessageStat.last_message_at).label('last_at'),
        ).group_by(DiscordMessageStat.discord_user_id)
        .order_by(func.sum(DiscordMessageStat.message_count).desc())
        .limit(25)
    ).all()
    discord_ids = [r.discord_user_id for r in member_rows] + [
        v[0] for v in top_sender.values()]
    name_map = {}
    if discord_ids:
        for did, name in (
            session.query(Player.discord_id, Player.name)
            .filter(Player.discord_id.in_([str(d) for d in discord_ids]))
            .all()
        ):
            name_map[str(did)] = name

    top_members = [{
        'name': name_map.get(str(r.discord_user_id), 'Unknown / unlinked'),
        'discord_user_id': r.discord_user_id,
        'messages': int(r.msgs or 0),
        'channels': int(r.channels or 0),
        'last_activity_at': _to_iso(r.last_at),
    } for r in member_rows]

    # --- weekly trend (last 12 weeks) ----------------------------------------
    trend_cut = (now - timedelta(weeks=12)).date()
    week = func.date_trunc('week', DiscordMessageStat.stat_date)
    trend_rows = (
        session.query(week.label('wk'), func.sum(DiscordMessageStat.message_count).label('msgs'))
        .filter(DiscordMessageStat.stat_date >= trend_cut)
        .group_by('wk').order_by('wk').all()
    )
    weekly_trend = [{'week': _to_iso(r.wk), 'messages': int(r.msgs or 0)} for r in trend_rows]

    # --- team names + silent team channels -----------------------------------
    team_name_map = {}
    silent_team_channels = []
    if season:
        team_rows = (
            session.query(Team.id, Team.name, Team.discord_channel_id)
            .join(League, Team.league_id == League.id)
            .filter(League.season_id == season.id, Team.is_active == True)  # noqa: E712
            .all()
        )
        team_name_map = {t.id: t.name for t in team_rows}
        seen_team_ids = {r.team_id for r in channel_rows if r.team_id}
        for t in team_rows:
            if t.discord_channel_id and t.id not in seen_team_ids:
                silent_team_channels.append({'team_id': t.id, 'team_name': t.name,
                                             'channel_id': t.discord_channel_id})

    channels = []
    stale_count = 0
    for r in channel_rows:
        last_at = r.last_at
        days_since = (now - last_at).days if isinstance(last_at, datetime) else None
        is_stale = days_since is not None and days_since >= STALE_CHANNEL_DAYS
        if is_stale:
            stale_count += 1
        msgs = int(r.msgs or 0)
        ts = top_sender.get(r.channel_id)
        ts_pct = round(ts[1] / msgs * 100) if (ts and msgs) else 0
        channels.append({
            'channel_id': r.channel_id,
            'channel_name': r.channel_name or (team_name_map.get(r.team_id) or r.channel_id),
            'team_id': r.team_id,
            'team_name': team_name_map.get(r.team_id),
            'is_team_channel': r.team_id is not None,
            'messages': msgs,
            'distinct_senders': int(r.senders or 0),
            'active_days': int(r.active_days or 0),
            'last_activity_at': _to_iso(last_at),
            'days_since_active': days_since,
            'is_stale': is_stale,
            'top_sender_name': name_map.get(str(ts[0])) if ts else None,
            'top_sender_pct': ts_pct,
        })
    channels.sort(key=lambda x: x['messages'], reverse=True)

    total_messages = sum(c['messages'] for c in channels)
    return {
        'season': season.to_dict() if season else None,
        'window_days': days,
        'channels': channels,
        'silent_team_channels': silent_team_channels,
        'top_members': top_members,
        'weekly_trend': weekly_trend,
        'totals': {
            'channels_active': len(channels),
            'total_messages': total_messages,
            'team_channels_active': sum(1 for c in channels if c['is_team_channel']),
            'silent_team_channels': len(silent_team_channels),
            'stale_channels': stale_count,
            'distinct_participants': len(member_rows),
        },
        'generated_at': datetime.utcnow().isoformat(),
    }


def _coach_team_metrics(session, team_id, user_id, discord_id):
    """Engagement metrics for ONE coach on ONE (season-specific) team."""
    match_rows = (
        session.query(
            Match.id, Match.home_team_id, Match.away_team_id,
            Match.home_team_score, Match.away_team_score,
            Match.home_team_verified_by, Match.home_team_verified_at,
            Match.away_team_verified_by, Match.away_team_verified_at,
        )
        .filter(
            or_(Match.home_team_id == team_id, Match.away_team_id == team_id),
            Match.home_team_id != Match.away_team_id,
        )
        .all()
    )
    match_ids = [m.id for m in match_rows]
    total_matches = len(match_rows)
    reported_matches = sum(
        1 for m in match_rows
        if m.home_team_score is not None and m.away_team_score is not None
    )

    last_dt = None
    matches_verified = 0
    for m in match_rows:
        if m.home_team_id == team_id and m.home_team_verified_by == user_id:
            matches_verified += 1
            last_dt = _max_dt(last_dt, m.home_team_verified_at)
        if m.away_team_id == team_id and m.away_team_verified_by == user_id:
            matches_verified += 1
            last_dt = _max_dt(last_dt, m.away_team_verified_at)

    matches_reported = 0
    if match_ids:
        matches_reported = (
            session.query(func.count(func.distinct(PlayerEvent.match_id)))
            .filter(
                PlayerEvent.match_id.in_(match_ids),
                PlayerEvent.reported_by == user_id,
            )
            .scalar()
        ) or 0

    lineup_rows = (
        session.query(MatchLineup.match_id, MatchLineup.updated_at)
        .filter(
            MatchLineup.team_id == team_id,
            or_(MatchLineup.created_by == user_id, MatchLineup.last_updated_by == user_id),
        )
        .all()
    )
    lineups_set = len(lineup_rows)
    for lr in lineup_rows:
        last_dt = _max_dt(last_dt, lr.updated_at)

    rsvp_views = rsvp_reminders = rsvp_active_days = 0
    ce_rows = (
        session.query(
            CoachEngagementEvent.activity_type,
            func.sum(CoachEngagementEvent.count).label('total'),
            func.count(func.distinct(CoachEngagementEvent.stat_date)).label('days'),
            func.max(CoachEngagementEvent.last_at).label('last_at'),
        )
        .filter(
            CoachEngagementEvent.team_id == team_id,
            CoachEngagementEvent.user_id == user_id,
            CoachEngagementEvent.activity_type.in_(RSVP_ACTION_TYPES),
        )
        .group_by(CoachEngagementEvent.activity_type)
        .all()
    )
    for row in ce_rows:
        if row.activity_type == 'rsvp_reminder':
            rsvp_reminders += int(row.total or 0)
        elif row.activity_type == 'rsvp_view':
            rsvp_views += int(row.total or 0)
        rsvp_active_days = max(rsvp_active_days, int(row.days or 0))
        last_dt = _max_dt(last_dt, row.last_at)

    discord_messages = discord_active_days = 0
    if discord_id:
        dm = (
            session.query(
                func.sum(DiscordMessageStat.message_count).label('msgs'),
                func.count(func.distinct(DiscordMessageStat.stat_date)).label('days'),
                func.max(DiscordMessageStat.last_message_at).label('last_at'),
            )
            .filter(
                DiscordMessageStat.team_id == team_id,
                DiscordMessageStat.discord_user_id == str(discord_id),
            )
            .first()
        )
        if dm:
            discord_messages = int(dm.msgs or 0)
            discord_active_days = int(dm.days or 0)
            last_dt = _max_dt(last_dt, dm.last_at)

    metrics = {
        'matches_reported': matches_reported,
        'matches_verified': matches_verified,
        'lineups_set': lineups_set,
        'rsvp_views': rsvp_views,
        'rsvp_reminders': rsvp_reminders,
        'rsvp_active_days': rsvp_active_days,
        'discord_messages': discord_messages,
        'discord_active_days': discord_active_days,
        'total_matches': total_matches,
        'reported_matches': reported_matches,
    }
    metrics['activity_score'] = _activity_score(metrics)
    metrics['last_active'] = _to_iso(last_dt)
    return metrics


def get_coach_history(session, player_id):
    """Cross-season participation timeline for one coach.

    For every season that has teams, classify this person as:
      - 'coached'  : flagged as coach of a team that season (+ engagement metrics)
      - 'played'   : on a roster but not a coach
      - 'absent'   : not in the league that season
    Past-season coach status comes from PlayerTeamSeason.is_coach (captured at
    rollover); the current season uses the live player_teams.is_coach. Seasons
    before that snapshot existed will under-report coaching (data genuinely lost).
    """
    player = session.query(Player).get(int(player_id))
    if not player:
        return None

    user_id = player.user_id
    discord_id = player.discord_id

    # coached: season_id -> set(team_id)  (PlayerTeamSeason snapshot, all seasons)
    coached = {}
    for season_id, team_id in (
        session.query(PlayerTeamSeason.season_id, PlayerTeamSeason.team_id)
        .filter(PlayerTeamSeason.player_id == player.id, PlayerTeamSeason.is_coach == True)  # noqa: E712
        .all()
    ):
        coached.setdefault(season_id, set()).add(team_id)

    # any membership: season_id -> set(team_id)
    member = {}
    for season_id, team_id in (
        session.query(PlayerTeamSeason.season_id, PlayerTeamSeason.team_id)
        .filter(PlayerTeamSeason.player_id == player.id)
        .all()
    ):
        member.setdefault(season_id, set()).add(team_id)

    # current season (live player_teams) — both coached & membership
    cur_rows = (
        session.query(Team.id, League.season_id, player_teams.c.is_coach)
        .join(League, Team.league_id == League.id)
        .join(player_teams, player_teams.c.team_id == Team.id)
        .filter(player_teams.c.player_id == player.id)
        .all()
    )
    for team_id, season_id, is_coach in cur_rows:
        member.setdefault(season_id, set()).add(team_id)
        if is_coach:
            coached.setdefault(season_id, set()).add(team_id)

    # team names for everything we touched
    all_team_ids = {tid for s in member.values() for tid in s} | {tid for s in coached.values() for tid in s}
    team_name = {}
    if all_team_ids:
        team_name = {tid: name for tid, name in
                     session.query(Team.id, Team.name).filter(Team.id.in_(all_team_ids)).all()}

    seasons = list_engagement_seasons(session)
    timeline = []
    seasons_coached = 0
    total_score = 0
    for s in seasons:
        sid = s['id']
        if sid in coached and coached[sid]:
            seasons_coached += 1
            teams = []
            for tid in coached[sid]:
                m = _coach_team_metrics(session, tid, user_id, discord_id)
                m['team_id'] = tid
                m['team_name'] = team_name.get(tid, f'Team {tid}')
                total_score += m['activity_score']
                teams.append(m)
            teams.sort(key=lambda x: x['activity_score'], reverse=True)
            # engagement level for the season (max across teams coached)
            top = max((t['activity_score'] for t in teams), default=0)
            level = 'inactive' if top == 0 else ('low' if top < 6 else 'active')
            timeline.append({
                'season': s, 'status': 'coached', 'teams': teams, 'level': level,
            })
        elif sid in member and member[sid]:
            timeline.append({
                'season': s, 'status': 'played',
                'teams': [{'team_id': tid, 'team_name': team_name.get(tid, f'Team {tid}')}
                          for tid in member[sid]],
            })
        else:
            timeline.append({'season': s, 'status': 'absent'})

    return {
        'player': {'id': player.id, 'name': player.name,
                   'discord_linked': bool(discord_id), 'is_coach_now': bool(player.is_coach)},
        'timeline': timeline,
        'summary': {
            'seasons_total': len(seasons),
            'seasons_coached': seasons_coached,
            'total_activity_score': total_score,
        },
        'generated_at': datetime.utcnow().isoformat(),
    }


# --- small datetime helpers --------------------------------------------------
def _max_dt(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _to_iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else None


def _max_iso(*dts):
    best = None
    for d in dts:
        if isinstance(d, datetime):
            best = _max_dt(best, d)
    return _to_iso(best)
