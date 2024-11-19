from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_wtf.csrf import validate_csrf, CSRFError
from collections import defaultdict
from datetime import datetime
from sqlalchemy.orm import selectinload
from flask_login import login_required
from app.utils.user_helpers import safe_current_user
import logging

from app.decorators import handle_db_operation, query_operation
from app.models import (
    Team, Player, League, Season, Match, Standings,
    PlayerEventType, PlayerEvent
)
from app.forms import ReportMatchForm
from app.teams_helpers import populate_team_stats, update_standings, process_events

logger = logging.getLogger(__name__)

teams_bp = Blueprint('teams', __name__)

@teams_bp.route('/<int:team_id>', endpoint='team_details')
@login_required
@query_operation
def team_details(team_id):
    team = Team.query.get_or_404(team_id)
    league = League.query.get(team.league_id)
    season = league.season if league else None
    players = Player.query.filter_by(team_id=team_id).all()
    report_form = ReportMatchForm()

    # Fetch all matches for detailed schedule with eager loading
    all_matches = Match.query.options(
        selectinload(Match.home_team).joinedload(Team.players),
        selectinload(Match.away_team).joinedload(Team.players)
    ).filter(
        (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
        (Match.home_team.has(league_id=league.id)) | (Match.away_team.has(league_id=league.id))
    ).order_by(Match.date.asc()).all()

    # Group the schedule by date and prepare player choices
    schedule = defaultdict(list)
    player_choices = {}  # Dictionary to store player choices for each match

    for match in all_matches:
        home_team_name = match.home_team.name
        away_team_name = match.away_team.name

        # Get all players from both teams
        home_team_players = {p.id: p.name for p in match.home_team.players}
        away_team_players = {p.id: p.name for p in match.away_team.players}

        # Store player choices for this match
        player_choices[match.id] = {
            home_team_name: home_team_players,
            away_team_name: away_team_players
        }

        if match.home_team_id == team_id:
            your_team_score = match.home_team_score if match.home_team_score is not None else 'N/A'
            opponent_score = match.away_team_score if match.away_team_score is not None else 'N/A'
        else:
            your_team_score = match.away_team_score if match.away_team_score is not None else 'N/A'
            opponent_score = match.home_team_score if match.home_team_score is not None else 'N/A'

        # Determine match result
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
            'opponent_name': match.away_team.name if match.home_team_id == team_id else match.home_team.name,
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

    # Determine the next upcoming match date
    next_match_date = None
    if schedule:
        today = datetime.today().date()
        match_dates = sorted(schedule.keys())
        for match_date in match_dates:
            if match_date >= today:
                next_match_date = match_date
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
@query_operation
def teams_overview():
    teams = Team.query.order_by(Team.name).all()
    return render_template('teams_overview.html', teams=teams)

@teams_bp.route('/report_match/<int:match_id>', endpoint='report_match', methods=['GET', 'POST'])
@login_required
@handle_db_operation()
def report_match(match_id):
    logger.info(f"Starting report_match for Match ID: {match_id}")
    match = Match.query.get_or_404(match_id)
    
    if request.method == 'GET':
        try:
            # Map event types to the expected frontend field names
            event_mapping = {
                PlayerEventType.GOAL: 'goal_scorers',
                PlayerEventType.ASSIST: 'assist_providers',
                PlayerEventType.YELLOW_CARD: 'yellow_cards',
                PlayerEventType.RED_CARD: 'red_cards'
            }
            
            # Initialize with empty arrays for all event types
            data = {
                'goal_scorers': [],
                'assist_providers': [],
                'yellow_cards': [],
                'red_cards': [],
                'home_team_score': match.home_team_score or 0,  # Default to 0 if None
                'away_team_score': match.away_team_score or 0,  # Default to 0 if None
                'notes': match.notes or ''  # Default to empty string if None
            }
            
            # Fetch and populate events
            for event_type, field_name in event_mapping.items():
                events = PlayerEvent.query.filter_by(
                    match_id=match.id,
                    event_type=event_type
                ).all()
                
                data[field_name] = [
                    {
                        'id': event.id,
                        'player_id': event.player_id,
                        'minute': event.minute or ''  # Default to empty string if None
                    }
                    for event in events
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

        try:
            match.home_team_score = int(data.get('home_team_score', match.home_team_score))
            match.away_team_score = int(data.get('away_team_score', match.away_team_score))
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid score values.'}), 400

        match.notes = data.get('notes', match.notes)

        # Process events
        process_events(match, data, PlayerEventType.GOAL, 'goals_to_add', 'goals_to_remove')
        process_events(match, data, PlayerEventType.ASSIST, 'assists_to_add', 'assists_to_remove')
        process_events(match, data, PlayerEventType.YELLOW_CARD, 'yellow_cards_to_add', 'yellow_cards_to_remove')
        process_events(match, data, PlayerEventType.RED_CARD, 'red_cards_to_add', 'red_cards_to_remove')

        # Update standings
        update_standings(match, old_home_score, old_away_score)
        logger.info(f"Match ID {match_id} reported successfully.")

        return jsonify({'success': True}), 200
    else:
        return jsonify({'success': False, 'message': 'Method not allowed.'}), 405

@teams_bp.route('/standings', endpoint='view_standings')
@login_required
@query_operation
def view_standings():
    season = Season.query.filter_by(is_current=True, league_type='Pub League').first()
    if not season:
        flash('No current season found.', 'warning')
        return redirect(url_for('home.index'))

    def get_standings(league_name):
        return Standings.query.join(Team).join(League).filter(
            Standings.season_id == season.id,
            Team.id == Standings.team_id,
            League.id == Team.league_id,
            League.name == league_name
        ).order_by(
            Standings.points.desc(),
            Standings.goal_difference.desc(),
            Standings.goals_for.desc()
        ).all()

    premier_standings = get_standings('Premier')
    classic_standings = get_standings('Classic')

    premier_stats = {s.team.id: populate_team_stats(s.team, season) for s in premier_standings}
    classic_stats = {s.team.id: populate_team_stats(s.team, season) for s in classic_standings}

    return render_template(
        'view_standings.html',
        premier_standings=premier_standings,
        classic_standings=classic_standings,
        premier_stats=premier_stats,
        classic_stats=classic_stats
    )
