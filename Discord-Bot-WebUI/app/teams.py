# app/teams.py

"""
Teams Module

This module defines routes related to teams, including viewing team details,
an overview of teams, reporting match results, and displaying league standings.
It handles both current and historical player data and match reports.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, jsonify, g
)
from flask_login import login_required
from flask_wtf.csrf import validate_csrf, CSRFError
from sqlalchemy import or_
from sqlalchemy.orm import selectinload, joinedload

from app.models import (
    Team, Player, League, Season, Match, Standings,
    PlayerEventType, PlayerEvent, PlayerTeamSeason
)
from app.forms import ReportMatchForm
from app.teams_helpers import populate_team_stats, update_standings, process_events
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)
teams_bp = Blueprint('teams', __name__)


@teams_bp.route('/<int:team_id>', endpoint='team_details')
@login_required
def team_details(team_id):
    """
    Display details about a specific team, including current/historical players and matches.

    The view fetches the team along with its players, determines whether to show
    current players or historical players (based on season status), gathers matches,
    and prepares data for rendering the team details page.

    Args:
        team_id (int): The ID of the team to display.

    Returns:
        A rendered template for team details.
    """
    session = g.db_session

    # Load team along with its associated players using eager loading.
    team = (
        session.query(Team)
        .options(joinedload(Team.players))
        .get(team_id)
    )
    if not team:
        flash('Team not found.', 'danger')
        return redirect(url_for('teams.teams_overview'))

    league = session.query(League).get(team.league_id)
    season = league.season if league else None

    # Retrieve current players from the many-to-many relationship.
    current_players = team.players

    # Retrieve historical players from PlayerTeamSeason if a season exists.
    historical_players = []
    if season:
        historical_players = (
            session.query(Player)
            .join(PlayerTeamSeason, Player.id == PlayerTeamSeason.player_id)
            .filter(
                PlayerTeamSeason.team_id == team_id,
                PlayerTeamSeason.season_id == season.id
            )
            .all()
        )

    # Choose to display current players if available or if the season is current.
    players = current_players if current_players or (season and season.is_current) else historical_players

    report_form = ReportMatchForm()

    # Fetch matches for this team within the same league.
    all_matches = (
        session.query(Match)
        .options(
            selectinload(Match.home_team).joinedload(Team.players),
            selectinload(Match.away_team).joinedload(Team.players)
        )
        .filter(
            ((Match.home_team_id == team_id) | (Match.away_team_id == team_id)),
            ((Match.home_team.has(league_id=league.id)) | (Match.away_team.has(league_id=league.id)))
        )
        .order_by(Match.date.asc())
        .all()
    )

    # Build a schedule mapping dates to match details and gather player choices.
    schedule = defaultdict(list)
    player_choices = {}

    for match in all_matches:
        home_team_name = match.home_team.name if match.home_team else 'Unknown'
        away_team_name = match.away_team.name if match.away_team else 'Unknown'

        # Load players differently for historical vs. current seasons.
        if season and not season.is_current:
            home_players = (
                session.query(Player)
                .join(PlayerTeamSeason)
                .filter(
                    PlayerTeamSeason.team_id == match.home_team_id,
                    PlayerTeamSeason.season_id == season.id
                )
                .all()
            )
            away_players = (
                session.query(Player)
                .join(PlayerTeamSeason)
                .filter(
                    PlayerTeamSeason.team_id == match.away_team_id,
                    PlayerTeamSeason.season_id == season.id
                )
                .all()
            )
            home_team_players = {p.id: p.name for p in home_players}
            away_team_players = {p.id: p.name for p in away_players}
        else:
            home_team_players = {p.id: p.name for p in match.home_team.players} if match.home_team else {}
            away_team_players = {p.id: p.name for p in match.away_team.players} if match.away_team else {}

        player_choices[match.id] = {
            home_team_name: home_team_players,
            away_team_name: away_team_players
        }

        # Determine scores for display.
        if match.home_team_id == team_id:
            your_team_score = match.home_team_score if match.home_team_score is not None else 'N/A'
            opponent_score = match.away_team_score if match.away_team_score is not None else 'N/A'
        else:
            your_team_score = match.away_team_score if match.away_team_score is not None else 'N/A'
            opponent_score = match.home_team_score if match.home_team_score is not None else 'N/A'

        # Determine match result (Win/Loss/Tie) if scores are available.
        if your_team_score != 'N/A' and opponent_score != 'N/A':
            if your_team_score > opponent_score:
                result_text = 'W'
                result_class = 'success'
            elif your_team_score < opponent_score:
                result_text = 'L'
                result_class = 'danger'
            else:
                result_text = 'T'
                result_class = 'warning'
        else:
            result_text = '-'
            result_class = 'secondary'

        display_score = f"{your_team_score} - {opponent_score}" if your_team_score != 'N/A' else '-'

        schedule[match.date].append({
            'id': match.id,
            'time': match.time,
            'location': match.location,
            'opponent_name': away_team_name if match.home_team_id == team_id else home_team_name,
            'home_team_name': home_team_name,
            'away_team_name': away_team_name,
            'home_team_id': match.home_team_id,
            'away_team_id': match.away_team_id,
            'your_team_score': your_team_score,
            'opponent_score': opponent_score,
            'result_class': result_class,
            'result_text': result_text,
            'display_score': display_score,
            'reported': match.reported,
        })

    # Determine the next match date for display.
    next_match_date = None
    if schedule:
        today = datetime.today().date()
        match_dates = sorted(schedule.keys())
        for md in match_dates:
            if md >= today:
                next_match_date = md
                break
        if not next_match_date:
            next_match_date = match_dates[-1]

    return render_template(
        'team_details.html',
        report_form=report_form,
        team=team,
        league=league,
        season=season,
        players=players,
        schedule=schedule,
        safe_current_user=safe_current_user,
        next_match_date=next_match_date,
        player_choices=player_choices
    )


@teams_bp.route('/', endpoint='teams_overview')
@login_required
def teams_overview():
    """
    Show an overview of teams for the current Pub League and/or ECS FC seasons.

    Retrieves the current seasons and then queries for teams associated with those seasons.
    """
    session = g.db_session

    # Retrieve current Pub League and ECS FC seasons.
    current_pub_season = (
        session.query(Season)
        .filter_by(is_current=True, league_type='Pub League')
        .first()
    )
    current_ecs_season = (
        session.query(Season)
        .filter_by(is_current=True, league_type='ECS FC')
        .first()
    )

    if not current_pub_season and not current_ecs_season:
        flash('No current season found for either Pub League or ECS FC.', 'warning')
        return redirect(url_for('home.index'))

    # Build conditions based on which current seasons exist.
    conditions = []
    if current_pub_season:
        conditions.append(League.season_id == current_pub_season.id)
    if current_ecs_season:
        conditions.append(League.season_id == current_ecs_season.id)

    teams_query = (
        session.query(Team)
        .join(League, Team.league_id == League.id)
    )

    if len(conditions) == 1:
        teams_query = teams_query.filter(conditions[0])
    elif len(conditions) == 2:
        teams_query = teams_query.filter(or_(*conditions))

    teams = teams_query.order_by(Team.name).all()
    return render_template('teams_overview.html', teams=teams)


@teams_bp.route('/report_match/<int:match_id>', endpoint='report_match', methods=['GET', 'POST'])
@login_required
def report_match(match_id):
    """
    GET: Return existing match report data (scores, events, etc.) as JSON.
    POST: Update the match report with new scores, events, and notes.

    CSRF validation is performed on POST requests.
    
    Args:
        match_id (int): The ID of the match to report.
    
    Returns:
        JSON response with status and message, or a rendered template.
    """
    session = g.db_session
    logger.info(f"Starting report_match for Match ID: {match_id}")
    match = session.query(Match).get(match_id)
    if not match:
        flash('Match not found.', 'danger')
        return redirect(url_for('teams.teams_overview'))

    if request.method == 'GET':
        try:
            event_mapping = {
                PlayerEventType.GOAL: 'goal_scorers',
                PlayerEventType.ASSIST: 'assist_providers',
                PlayerEventType.YELLOW_CARD: 'yellow_cards',
                PlayerEventType.RED_CARD: 'red_cards'
            }

            data = {
                'goal_scorers': [],
                'assist_providers': [],
                'yellow_cards': [],
                'red_cards': [],
                'home_team_score': match.home_team_score or 0,
                'away_team_score': match.away_team_score or 0,
                'notes': match.notes or ''
            }

            # Build a dictionary of events for each type.
            for event_type, field_name in event_mapping.items():
                events = (
                    session.query(PlayerEvent)
                    .filter_by(match_id=match.id, event_type=event_type)
                    .all()
                )
                data[field_name] = [
                    {
                        'id': ev.id,
                        'player_id': ev.player_id,
                        'minute': ev.minute or ''
                    }
                    for ev in events
                ]

            logger.debug(f"Returning match data: {data}")
            return jsonify(data), 200

        except Exception as e:
            logger.exception(f"Error fetching match data: {e}")
            return jsonify({'success': False, 'message': 'An error occurred.'}), 500

    elif request.method == 'POST':
        try:
            csrf_token = request.headers.get('X-CSRFToken')
            validate_csrf(csrf_token)
        except CSRFError as e:
            logger.error(f"CSRF validation failed: {e}")
            return jsonify({'success': False, 'message': 'Invalid CSRF token.'}), 400

        if not request.is_json:
            return jsonify({'success': False, 'message': 'Invalid content type.'}), 415

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received.'}), 400

        old_home_score = match.home_team_score
        old_away_score = match.away_team_score

        # Update match scores.
        try:
            match.home_team_score = int(data.get('home_team_score', old_home_score or 0))
            match.away_team_score = int(data.get('away_team_score', old_away_score or 0))
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid score values.'}), 400

        match.notes = data.get('notes', match.notes)

        # Process player events for the match.
        process_events(session, match, data, PlayerEventType.GOAL, 'goals_to_add', 'goals_to_remove')
        process_events(session, match, data, PlayerEventType.ASSIST, 'assists_to_add', 'assists_to_remove')
        process_events(session, match, data, PlayerEventType.YELLOW_CARD, 'yellow_cards_to_add', 'yellow_cards_to_remove')
        process_events(session, match, data, PlayerEventType.RED_CARD, 'red_cards_to_add', 'red_cards_to_remove')

        # Update standings based on the new match data.
        update_standings(session, match, old_home_score, old_away_score)
        logger.info(f"Match ID {match_id} reported successfully.")
        return jsonify({'success': True}), 200

    else:
        return jsonify({'success': False, 'message': 'Method not allowed.'}), 405


@teams_bp.route('/standings', endpoint='view_standings')
@login_required
def view_standings():
    """
    Display the standings for the current Pub League, separated into Premier and Classic divisions.

    Retrieves the current Pub League season, queries standings for each division,
    and populates team statistics for display.
    """
    session = g.db_session
    season = session.query(Season).filter_by(is_current=True, league_type='Pub League').first()
    if not season:
        flash('No current season found.', 'warning')
        return redirect(url_for('home.index'))

    def get_standings(league_name):
        return (
            session.query(Standings)
            .join(Team)
            .join(League)
            .filter(
                Standings.season_id == season.id,
                Team.id == Standings.team_id,
                League.id == Team.league_id,
                League.name == league_name
            )
            .order_by(
                Standings.points.desc(),
                Standings.goal_difference.desc(),
                Standings.goals_for.desc()
            )
            .all()
        )

    premier_standings = get_standings('Premier')
    classic_standings = get_standings('Classic')

    # Populate detailed stats for each team.
    premier_stats = {s.team.id: populate_team_stats(s.team, season) for s in premier_standings}
    classic_stats = {s.team.id: populate_team_stats(s.team, season) for s in classic_standings}

    return render_template(
        'view_standings.html',
        premier_standings=premier_standings,
        classic_standings=classic_standings,
        premier_stats=premier_stats,
        classic_stats=classic_stats
    )