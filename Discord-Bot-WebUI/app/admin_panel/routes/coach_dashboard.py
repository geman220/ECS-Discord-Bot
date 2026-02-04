# app/admin_panel/routes/coach_dashboard.py

"""
Admin Panel Coach Dashboard Routes

This module provides an admin view of all team coach dashboards with:
- Toggle between ECS FC and Pub League
- Current season teams only
- Full RSVP management and match reporting capabilities
"""

import logging
from datetime import date as dt_date, datetime as dt_datetime
from flask import render_template, request, jsonify, g
from flask_login import login_required
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import joinedload

from .. import admin_panel_bp
from app.decorators import role_required
from app.models import (
    Team, League, Season, Match, Schedule, Player, Standings,
    PlayerSeasonStats, PlayerAttendanceStats, Availability,
    SubstituteRequest, EcsFcMatch, EcsFcAvailability
)
from app.models.players import player_teams

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/coach-dashboard')
@admin_panel_bp.route('/coach-dashboard/<int:team_id>')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def coach_dashboard(team_id=None):
    """
    Admin Coach Dashboard - comprehensive view of teams with:
    - Toggle between ECS FC and Pub League
    - Current season teams only
    - Tab navigation for all teams within selected league type
    - Full coach dashboard view for selected team
    """
    session = g.db_session

    # Get filter parameters - default to Pub League
    league_type_filter = request.args.get('league_type', 'pub_league')

    # Determine the season league type for querying
    if league_type_filter == 'ecs_fc':
        season_league_type = 'ECS FC'
    else:
        season_league_type = 'Pub League'

    # Get current season for the selected league type
    current_season = session.query(Season).filter(
        Season.is_current == True,
        Season.league_type == season_league_type
    ).first()

    if not current_season:
        return render_template('admin_panel/coach/dashboard_flowbite.html',
                             all_teams=[],
                             selected_team=None,
                             team_stats={},
                             todays_matches=[],
                             needs_reporting=[],
                             upcoming_matches=[],
                             past_matches=[],
                             player_choices={},
                             league_type_filter=league_type_filter,
                             current_season=None,
                             pending_sub_requests=[])

    # Get all active teams for the current season
    teams_query = session.query(Team).join(League).filter(
        Team.is_active == True,
        League.season_id == current_season.id
    ).options(
        joinedload(Team.league)
    )

    # For Pub League, we might want to further filter by division type
    if league_type_filter == 'pub_league':
        # Get Premier and Classic teams
        teams_query = teams_query.filter(
            or_(
                func.lower(League.name).contains('premier'),
                func.lower(League.name).contains('classic')
            )
        )
    else:
        # ECS FC teams
        teams_query = teams_query.filter(
            func.lower(League.name).contains('ecs')
        )

    all_teams = teams_query.order_by(Team.name).all()

    if not all_teams:
        return render_template('admin_panel/coach/dashboard_flowbite.html',
                             all_teams=[],
                             selected_team=None,
                             team_stats={},
                             todays_matches=[],
                             needs_reporting=[],
                             upcoming_matches=[],
                             past_matches=[],
                             player_choices={},
                             league_type_filter=league_type_filter,
                             current_season=current_season,
                             pending_sub_requests=[])

    # If no team selected, use first team
    if not team_id:
        team_id = all_teams[0].id

    # Verify selected team is in our filtered list
    selected_team = None
    for team in all_teams:
        if team.id == team_id:
            selected_team = team
            break

    if not selected_team:
        selected_team = all_teams[0]
        team_id = selected_team.id

    # Get matches for selected team
    today = dt_date.today()
    now = dt_datetime.now()

    # Determine team's league type
    league_name = selected_team.league.name.lower() if selected_team.league else ''
    if 'ecs' in league_name:
        team_league_type = 'ECS FC'
    elif 'premier' in league_name:
        team_league_type = 'Premier'
    elif 'classic' in league_name:
        team_league_type = 'Classic'
    else:
        team_league_type = 'Pub League'

    # Query matches for selected team
    all_matches = []
    if team_league_type == 'ECS FC':
        ecs_matches = session.query(EcsFcMatch).filter(
            EcsFcMatch.team_id == team_id
        ).order_by(EcsFcMatch.match_date.asc(), EcsFcMatch.match_time.asc()).all()

        for match in ecs_matches:
            match.league_type = 'ECS FC'
            match.is_ecs_fc = True
            match.date = match.match_date
            match.time = match.match_time
            match.home_team = session.query(Team).get(match.team_id) if match.is_home_match else None
            match.away_team = session.query(Team).get(match.team_id) if not match.is_home_match else None
            match.home_team_id = match.team_id if match.is_home_match else None
            match.away_team_id = match.team_id if not match.is_home_match else None
            match.home_team_score = match.home_score
            match.away_team_score = match.away_score

        all_matches.extend(ecs_matches)
    else:
        pub_matches = session.query(Match).join(
            Schedule, Match.schedule_id == Schedule.id
        ).filter(
            Schedule.season_id == current_season.id,
            or_(
                Match.home_team_id == team_id,
                Match.away_team_id == team_id
            )
        ).order_by(Match.date.asc(), Match.time.asc()).all()

        for match in pub_matches:
            match.league_type = team_league_type
            match.is_ecs_fc = False
            match.home_team = session.query(Team).get(match.home_team_id)
            match.away_team = session.query(Team).get(match.away_team_id)

        all_matches.extend(pub_matches)

    # Sort matches
    all_matches.sort(key=lambda m: (m.date, m.time) if m.date and m.time else (dt_datetime.max.date(), dt_datetime.max.time()))

    # Categorize matches
    todays_matches = []
    needs_reporting = []
    upcoming_matches = []
    past_matches = []

    for match in all_matches:
        match_datetime = dt_datetime.combine(match.date, match.time) if match.date and match.time else None
        is_reported = match.home_team_score is not None and match.away_team_score is not None
        is_special = getattr(match, 'is_special_week', False) or getattr(match, 'week_type', 'REGULAR') in ['TST', 'FUN', 'BYE', 'PRACTICE']

        if match_datetime:
            if match.date == today:
                if not is_special:
                    todays_matches.append(match)
                else:
                    past_matches.append(match)
            elif match.date < today:
                if is_reported or is_special:
                    past_matches.append(match)
                else:
                    needs_reporting.append(match)
            else:
                upcoming_matches.append(match)

    past_matches.reverse()
    needs_reporting.sort(key=lambda m: (m.date, m.time) if m.date and m.time else (dt_datetime.max.date(), dt_datetime.max.time()))

    # Add RSVP counts for each match
    coached_team_players = session.query(Player.id).join(
        player_teams, Player.id == player_teams.c.player_id
    ).filter(player_teams.c.team_id == team_id).all()
    coached_team_player_ids = [p.id for p in coached_team_players]

    for match in all_matches:
        if hasattr(match, 'is_ecs_fc') and match.is_ecs_fc:
            if coached_team_player_ids:
                availability_data = session.query(
                    EcsFcAvailability.response,
                    func.count(EcsFcAvailability.id)
                ).filter(
                    EcsFcAvailability.ecs_fc_match_id == match.id,
                    EcsFcAvailability.player_id.in_(coached_team_player_ids)
                ).group_by(EcsFcAvailability.response).all()
            else:
                availability_data = []
        else:
            if coached_team_player_ids:
                availability_data = session.query(
                    Availability.response,
                    func.count(Availability.id)
                ).filter(
                    Availability.match_id == match.id,
                    Availability.player_id.in_(coached_team_player_ids)
                ).group_by(Availability.response).all()
            else:
                availability_data = []

        rsvp_counts = {'YES': 0, 'NO': 0, 'MAYBE': 0}
        for response, count in availability_data:
            if response and response.upper() in rsvp_counts:
                rsvp_counts[response.upper()] = count

        match.rsvp_counts = rsvp_counts

    # Get team statistics
    team_stats = {}
    team_league = session.query(League).get(selected_team.league_id)
    league_season_id = team_league.season_id if team_league else current_season.id

    standings = session.query(Standings).filter_by(
        team_id=team_id,
        season_id=league_season_id
    ).first()

    top_scorers = session.query(Player, PlayerSeasonStats).join(
        PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id
    ).join(
        player_teams, Player.id == player_teams.c.player_id
    ).filter(
        player_teams.c.team_id == team_id,
        PlayerSeasonStats.season_id == league_season_id,
        PlayerSeasonStats.goals > 0
    ).order_by(PlayerSeasonStats.goals.desc()).limit(5).all()

    top_assists = session.query(Player, PlayerSeasonStats).join(
        PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id
    ).join(
        player_teams, Player.id == player_teams.c.player_id
    ).filter(
        player_teams.c.team_id == team_id,
        PlayerSeasonStats.season_id == league_season_id,
        PlayerSeasonStats.assists > 0
    ).order_by(PlayerSeasonStats.assists.desc()).limit(5).all()

    roster_query = session.query(Player, PlayerAttendanceStats, PlayerSeasonStats).outerjoin(
        PlayerAttendanceStats, and_(
            Player.id == PlayerAttendanceStats.player_id,
            PlayerAttendanceStats.current_season_id == league_season_id
        )
    ).outerjoin(
        PlayerSeasonStats, and_(
            Player.id == PlayerSeasonStats.player_id,
            PlayerSeasonStats.season_id == league_season_id
        )
    ).join(
        player_teams, Player.id == player_teams.c.player_id
    ).filter(
        player_teams.c.team_id == team_id
    ).order_by(Player.name).all()

    team_stats[team_id] = {
        'standings': standings,
        'top_scorers': top_scorers,
        'top_assists': top_assists,
        'roster': roster_query,
        'season': current_season,
        'league_type': team_league_type,
        'season_id': league_season_id
    }

    # Get pending sub requests for teams in this league type
    team_ids = [t.id for t in all_teams]
    pending_sub_requests = session.query(SubstituteRequest).filter(
        SubstituteRequest.status == 'PENDING',
        SubstituteRequest.team_id.in_(team_ids)
    ).order_by(
        SubstituteRequest.created_at.desc() if hasattr(SubstituteRequest, 'created_at') else SubstituteRequest.id.desc()
    ).limit(10).all()

    # Build player choices for match reporting
    player_choices = {}
    for match in all_matches:
        if hasattr(match, 'is_ecs_fc') and match.is_ecs_fc:
            team = match.home_team if match.home_team else match.away_team
            if team:
                players = session.query(Player).join(Player.teams).filter(Team.id == team.id).all()
                player_choices[match.id] = {
                    team.name: {p.id: p.name for p in players},
                    getattr(match, 'opponent_name', 'Opponent'): {}
                }
        elif match.home_team and match.away_team:
            home_players = session.query(Player).join(Player.teams).filter(Team.id == match.home_team_id).all()
            away_players = session.query(Player).join(Player.teams).filter(Team.id == match.away_team_id).all()
            player_choices[match.id] = {
                match.home_team.name: {p.id: p.name for p in home_players},
                match.away_team.name: {p.id: p.name for p in away_players}
            }

    return render_template('admin_panel/coach/dashboard_flowbite.html',
                         all_teams=all_teams,
                         selected_team=selected_team,
                         coached_teams=[selected_team],
                         team_stats=team_stats,
                         team_league_types={team_id: team_league_type},
                         todays_matches=todays_matches,
                         needs_reporting=needs_reporting,
                         upcoming_matches=upcoming_matches,
                         past_matches=past_matches,
                         player_choices=player_choices,
                         league_type_filter=league_type_filter,
                         current_season=current_season,
                         pending_sub_requests=pending_sub_requests,
                         today=today)
