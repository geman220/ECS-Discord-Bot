from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_wtf.csrf import validate_csrf, CSRFError
from collections import defaultdict
from datetime import datetime, date
from sqlalchemy import func
from sqlalchemy.orm import aliased, joinedload, selectinload
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import Team, Player, Schedule, League, Season, Match, Standings, PlayerEventType, PlayerEvent, PlayerSeasonStats, PlayerCareerStats
from app.main import fetch_upcoming_matches
from app.forms import ReportMatchForm, PlayerEventForm
from flask_login import login_required, current_user
import logging

# Initialize logger
logger = logging.getLogger(__name__)

teams_bp = Blueprint('teams', __name__)

from sqlalchemy import func

def populate_team_stats(team, season):
    # Calculate top scorer using PlayerSeasonStats
    top_scorer = db.session.query(Player.name, PlayerSeasonStats.goals)\
        .join(PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id)\
        .filter(
            PlayerSeasonStats.season_id == season.id,
            Player.team_id == team.id
        )\
        .order_by(PlayerSeasonStats.goals.desc())\
        .first()

    if top_scorer and top_scorer[1] > 0:
        top_scorer_name, top_scorer_goals = top_scorer
    else:
        top_scorer_name, top_scorer_goals = "No goals scored", 0

    # Calculate top assister using PlayerSeasonStats
    top_assister = db.session.query(Player.name, PlayerSeasonStats.assists)\
        .join(PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id)\
        .filter(
            PlayerSeasonStats.season_id == season.id,
            Player.team_id == team.id
        )\
        .order_by(PlayerSeasonStats.assists.desc())\
        .first()

    if top_assister and top_assister[1] > 0:
        top_assister_name, top_assister_assists = top_assister
    else:
        top_assister_name, top_assister_assists = "No assists recorded", 0

    # Fetch last 5 matches for recent form
    matches = Match.query \
        .join(Team, ((Match.home_team_id == Team.id) | (Match.away_team_id == Team.id))) \
        .join(League, Team.league_id == League.id) \
        .filter(
            ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
            League.season_id == season.id,
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None)
        ) \
        .order_by(Match.date.desc()) \
        .limit(5) \
        .all()

    recent_form_list = []
    for match in matches:
        if match.home_team_id == team.id:
            if match.home_team_score > match.away_team_score:
                recent_form_list.append('W')
            elif match.home_team_score == match.away_team_score:
                recent_form_list.append('D')
            else:
                recent_form_list.append('L')
        else:
            if match.away_team_score > match.home_team_score:
                recent_form_list.append('W')
            elif match.away_team_score == match.home_team_score:
                recent_form_list.append('D')
            else:
                recent_form_list.append('L')

    recent_form = ' '.join(recent_form_list) if recent_form_list else "N/A"

    # Calculate average goals per match
    total_goals = db.session.query(func.sum(PlayerSeasonStats.goals)) \
        .join(Player, PlayerSeasonStats.player_id == Player.id) \
        .filter(
            PlayerSeasonStats.season_id == season.id,
            Player.team_id == team.id
        ).scalar() or 0

    matches_played = db.session.query(func.count(Match.id)) \
        .join(Team, ((Match.home_team_id == Team.id) | (Match.away_team_id == Team.id))) \
        .join(League, Team.league_id == League.id) \
        .filter(
            ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
            League.season_id == season.id,
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None)
        ).scalar() or 0

    avg_goals_per_match = round(total_goals / matches_played, 2) if matches_played else 0

    return {
        "top_scorer_name": top_scorer_name,
        "top_scorer_goals": top_scorer_goals,
        "top_assister_name": top_assister_name,
        "top_assister_assists": top_assister_assists,
        "recent_form": recent_form,
        "avg_goals_per_match": avg_goals_per_match
    }

def update_standings(match, old_home_score=None, old_away_score=None):
    logger = logging.getLogger(__name__)

    home_team = match.home_team
    away_team = match.away_team
    league = home_team.league
    season = league.season

    try:
        # Fetch or create standings for home and away teams
        home_team_standing = Standings.query.filter_by(team_id=home_team.id, season_id=season.id).first()
        if home_team_standing is None:
            home_team_standing = Standings(team_id=home_team.id, season_id=season.id)
            db.session.add(home_team_standing)

        away_team_standing = Standings.query.filter_by(team_id=away_team.id, season_id=season.id).first()
        if away_team_standing is None:
            away_team_standing = Standings(team_id=away_team.id, season_id=season.id)
            db.session.add(away_team_standing)

        # Revert old match result if provided
        if old_home_score is not None and old_away_score is not None:
            logger.info(f"Reverting old match result for Match ID: {match.id}")
            if old_home_score > old_away_score:
                home_team_standing.wins -= 1
                away_team_standing.losses -= 1
            elif old_home_score < old_away_score:
                away_team_standing.wins -= 1
                home_team_standing.losses -= 1
            else:
                home_team_standing.draws -= 1
                away_team_standing.draws -= 1

            # Update goals for/against and goal difference
            home_team_standing.goals_for -= old_home_score
            home_team_standing.goals_against -= old_away_score
            away_team_standing.goals_for -= old_away_score
            away_team_standing.goals_against -= old_home_score

            home_team_standing.goal_difference = home_team_standing.goals_for - home_team_standing.goals_against
            away_team_standing.goal_difference = away_team_standing.goals_for - away_team_standing.goals_against

            home_team_standing.points = (home_team_standing.wins * 3) + home_team_standing.draws
            away_team_standing.points = (away_team_standing.wins * 3) + away_team_standing.draws

            home_team_standing.played -= 1
            away_team_standing.played -= 1

        # Apply the new match result
        if match.home_team_score > match.away_team_score:
            home_team_standing.wins += 1
            away_team_standing.losses += 1
        elif match.home_team_score < match.away_team_score:
            away_team_standing.wins += 1
            home_team_standing.losses += 1
        else:
            home_team_standing.draws += 1
            away_team_standing.draws += 1

        home_team_standing.points = (home_team_standing.wins * 3) + home_team_standing.draws
        away_team_standing.points = (away_team_standing.wins * 3) + away_team_standing.draws

        home_team_standing.goals_for += match.home_team_score
        home_team_standing.goals_against += match.away_team_score
        away_team_standing.goals_for += match.away_team_score
        away_team_standing.goals_against += match.home_team_score

        home_team_standing.goal_difference = home_team_standing.goals_for - home_team_standing.goals_against
        away_team_standing.goal_difference = away_team_standing.goals_for - away_team_standing.goals_against

        home_team_standing.played += 1
        away_team_standing.played += 1

        db.session.commit()
        logger.info(f"Standings updated for Match ID {match.id}")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating standings for Match ID {match.id}: {str(e)}")
        raise

def process_events(match, data, event_type, add_key, remove_key):
    logger = logging.getLogger(__name__)

    logger.info(f"Processing {event_type.name} events for Match ID {match.id}")
    events_to_add = data.get(add_key, [])
    events_to_remove = data.get(remove_key, [])

    # Log events being added/removed
    logger.debug(f"Events to add: {events_to_add}")
    logger.debug(f"Events to remove: {events_to_remove}")

    try:
        # Process events to remove
        for event_data in events_to_remove:
            stat_id = event_data.get('stat_id')
            if stat_id:
                event = PlayerEvent.query.get(stat_id)
                if event:
                    update_player_stats(event.player_id, event.event_type.value, increment=False)
                    db.session.delete(event)
                    db.session.flush()  # Ensure deletion is handled immediately
                    logger.info(f"Removed {event_type.name}: Stat ID {stat_id}")
                else:
                    logger.warning(f"Event with Stat ID {stat_id} not found. Skipping removal.")

        # Process events to add or update
        for event_data in events_to_add:
            player_id = event_data.get('player_id')
            minute = event_data.get('minute')
            stat_id = event_data.get('stat_id')

            player_id = int(player_id)
            if stat_id:
                stat_id = int(stat_id)

            player = Player.query.filter(
                (Player.id == player_id) &
                (Player.team_id.in_([match.home_team_id, match.away_team_id]))
            ).first()

            if not player:
                raise ValueError(f"Player with ID {player_id} is not part of this match.")

            if stat_id:
                event = PlayerEvent.query.get(stat_id)
                if event:
                    if event.player_id != player_id:
                        update_player_stats(event.player_id, event.event_type, increment=False)
                        update_player_stats(player_id, event_type.value, increment=True)
                        event.player_id = player_id
                    event.minute = minute if minute else None
                    logger.info(f"Updated {event_type.name}: Player ID {player_id}, Stat ID {stat_id}")
                else:
                    logger.warning(f"Event with Stat ID {stat_id} not found. Cannot update.")
            else:
                new_event = PlayerEvent(
                    player_id=player_id,
                    match_id=match.id,
                    minute=minute,
                    event_type=event_type
                )
                db.session.add(new_event)
                logger.info(f"Added {event_type.name}: Player ID {player_id}, Minute {minute}")
                update_player_stats(player_id, event_type.value)

        db.session.commit()
        logger.info(f"Events processed for Match ID {match.id}")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing {event_type.name} events for Match ID {match.id}: {e}")
        raise

def update_player_stats(player_id, event_type, increment=True):
    logger.info(f"Updating stats for player_id={player_id}, event_type={event_type}, increment={increment}")
    player = Player.query.get(player_id)
    season_id = current_season_id()

    # Get or create season stats
    season_stats = PlayerSeasonStats.query.filter_by(player_id=player_id, season_id=season_id).first()
    if not season_stats:
        season_stats = PlayerSeasonStats(player_id=player_id, season_id=season_id, goals=0, assists=0, yellow_cards=0, red_cards=0)
        db.session.add(season_stats)

    # Get or create career stats (ensure it's a single object, not a list)
    career_stats = PlayerCareerStats.query.filter_by(player_id=player_id).first()
    if not career_stats:
        career_stats = PlayerCareerStats(player_id=player_id, goals=0, assists=0, yellow_cards=0, red_cards=0)
        db.session.add(career_stats)

    # Determine the adjustment value
    adjustment = 1 if increment else -1

    try:
        # Update season and career stats for the respective event type
        if event_type == PlayerEventType.GOAL.value:
            season_stats.goals = max((season_stats.goals or 0) + adjustment, 0)
            career_stats.goals = max((career_stats.goals or 0) + adjustment, 0)
            logger.info(f"Updated goals: season {season_stats.goals}, career {career_stats.goals}")
        elif event_type == PlayerEventType.ASSIST.value:
            season_stats.assists = max((season_stats.assists or 0) + adjustment, 0)
            career_stats.assists = max((career_stats.assists or 0) + adjustment, 0)
            logger.info(f"Updated assists: season {season_stats.assists}, career {career_stats.assists}")
        elif event_type == PlayerEventType.YELLOW_CARD.value:
            season_stats.yellow_cards = max((season_stats.yellow_cards or 0) + adjustment, 0)
            career_stats.yellow_cards = max((career_stats.yellow_cards or 0) + adjustment, 0)
            logger.info(f"Updated yellow cards: season {season_stats.yellow_cards}, career {career_stats.yellow_cards}")
        elif event_type == PlayerEventType.RED_CARD.value:
            season_stats.red_cards = max((season_stats.red_cards or 0) + adjustment, 0)
            career_stats.red_cards = max((career_stats.red_cards or 0) + adjustment, 0)
            logger.info(f"Updated red cards: season {season_stats.red_cards}, career {career_stats.red_cards}")
        
        # Commit the changes to the database
        db.session.commit()

    except Exception as e:
        logger.exception(f"Error updating stats for player_id={player_id}: {e}")
        db.session.rollback()  # Rollback in case of any error
        raise

def current_season_id():
    current_season = Season.query.filter_by(is_current=True).first()
    return current_season.id if current_season else None

@teams_bp.route('/<int:team_id>')
@login_required
def team_details(team_id):
    team = Team.query.get_or_404(team_id)
    league = League.query.get(team.league_id)
    season = league.season if league.season else None
    players = Player.query.filter_by(team_id=team_id).all()

    report_form = ReportMatchForm()

    # Fetch the player profile associated with the current user
    player = getattr(current_user, 'player', None)
    user_team = player.team if player else None

    # Fetch all matches for detailed schedule
    all_matches = Match.query.options(
        selectinload(Match.home_team).selectinload(Team.players),
        selectinload(Match.away_team).selectinload(Team.players)
    ).filter(
        (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
        (Match.home_team.has(league_id=league.id)) | (Match.away_team.has(league_id=league.id))
    ).order_by(Match.date.asc()).all()  # Changed to ascending order

    # Group the schedule by date
    schedule = defaultdict(list)
    for match in all_matches:
        # Always assign actual home and away team names
        home_team_name = match.home_team.name
        away_team_name = match.away_team.name

        # Determine display variables based on whether current team is home or away
        if match.home_team_id == team_id:
            display_home = home_team_name
            display_away = away_team_name
            your_team_score = match.home_team_score if match.home_team_score is not None else 'N/A'
            opponent_score = match.away_team_score if match.away_team_score is not None else 'N/A'
        else:
            # Swap display_home and display_away when current team is away
            display_home = away_team_name
            display_away = home_team_name
            your_team_score = match.away_team_score if match.away_team_score is not None else 'N/A'
            opponent_score = match.home_team_score if match.home_team_score is not None else 'N/A'

        # Determine match result
        if your_team_score != 'N/A' and opponent_score != 'N/A':
            if your_team_score > opponent_score:
                result_text = 'W'
                result_class = 'success'  # Green
            elif your_team_score < opponent_score:
                result_text = 'L'
                result_class = 'danger'  # Red
            else:
                result_text = 'T'
                result_class = 'warning'  # Yellow
        else:
            result_text = '-'
            result_class = 'secondary'  # Grey

        # Prepare display score
        if your_team_score != 'N/A' and opponent_score != 'N/A':
            display_score = f"{your_team_score} - {opponent_score}"
        else:
            display_score = '-'

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
            'home_players': match.home_team.players,
            'away_players': match.away_team.players
        })

    # Determine the next upcoming match date
    if schedule:
        today = datetime.today().date()
        match_dates = sorted(schedule.keys())
        next_match_date = None
        for match_date in match_dates:
            if match_date >= today:
                next_match_date = match_date
                break
        if next_match_date is None:
            # All matches are in the past; default to the last date
            next_match_date = match_dates[-1]
    else:
        next_match_date = None

    # Prepare player choices for each match
    player_choices_per_match = {}
    for date, matches_on_date in schedule.items():
        for match in matches_on_date:
            home_team_id = match['home_team_id']
            away_team_id = match['away_team_id']

            match_players = Player.query.filter(Player.team_id.in_([home_team_id, away_team_id])).all()

            # Get team names
            home_team_name = match['home_team_name']
            away_team_name = match['away_team_name']

            # Structure the players by team using team names
            player_choices_per_match[match['id']] = {
                home_team_name: {player.id: player.name for player in match_players if player.team_id == home_team_id},
                away_team_name: {player.id: player.name for player in match_players if player.team_id == away_team_id}
            }

    return render_template(
        'team_details.html',
        report_form=report_form,
        team=team,
        league=league,
        season=season,
        players=players,
        schedule=schedule,
        player_choices=player_choices_per_match,
        current_user=current_user,  # Ensure current_user is passed if used in the template
        next_match_date=next_match_date  # Pass the next upcoming match date
    )

@teams_bp.route('/')
@login_required
def teams_overview():
    teams = Team.query.order_by(Team.name).all()
    return render_template('teams_overview.html', teams=teams)

@teams_bp.route('/report_match/<int:match_id>', methods=['GET', 'POST'])
@login_required
def report_match(match_id):
    logger.info(f"Starting report_match for Match ID: {match_id}")

    # Fetch the match by ID
    match = Match.query.get(match_id)
    if not match:
        logger.error(f"Match ID {match_id} not found.")
        return jsonify({'success': False, 'message': 'Match not found.'}), 404

    logger.info(f"Match found: {match} with Home Team ID: {match.home_team_id}, Away Team ID: {match.away_team_id}")

    # Proceed with GET or POST handling
    if request.method == 'GET':
        try:
            # Fetch existing events for the match
            goals = PlayerEvent.query.filter_by(match_id=match.id, event_type=PlayerEventType.GOAL).all()
            goal_scorers = [{'id': goal.id, 'player_id': goal.player_id, 'minute': goal.minute} for goal in goals]

            assists = PlayerEvent.query.filter_by(match_id=match.id, event_type=PlayerEventType.ASSIST).all()
            assist_providers = [{'id': assist.id, 'player_id': assist.player_id, 'minute': assist.minute} for assist in assists]

            yellow_cards = PlayerEvent.query.filter_by(match_id=match.id, event_type=PlayerEventType.YELLOW_CARD).all()
            yellow_card_entries = [{'id': yellow_card.id, 'player_id': yellow_card.player_id, 'minute': yellow_card.minute} for yellow_card in yellow_cards]

            red_cards = PlayerEvent.query.filter_by(match_id=match.id, event_type=PlayerEventType.RED_CARD).all()
            red_card_entries = [{'id': red_card.id, 'player_id': red_card.player_id, 'minute': red_card.minute} for red_card in red_cards]

            # Return the collected data as JSON
            return jsonify({
                'home_team_score': match.home_team_score,
                'away_team_score': match.away_team_score,
                'notes': match.notes,
                'goal_scorers': goal_scorers,
                'assist_providers': assist_providers,
                'yellow_cards': yellow_card_entries,
                'red_cards': red_card_entries,
            }), 200

        except Exception as e:
            logger.exception(f"Error fetching match data for Match ID {match_id}: {str(e)}")
            return jsonify({'success': False, 'message': 'An error occurred while fetching match data.'}), 500

    elif request.method == 'POST':
        logger.info(f"POST request detected, updating data for Match ID: {match_id}")

        # Verify CSRF token
        try:
            csrf_token = request.headers.get('X-CSRFToken')
            validate_csrf(csrf_token)
        except CSRFError as e:
            logger.error(f"CSRF validation failed: {str(e)}")
            return jsonify({'success': False, 'message': 'CSRF token missing or invalid.'}), 400

        if not request.is_json:
            logger.error("Request content type is not application/json.")
            return jsonify({'success': False, 'message': 'Unsupported Media Type'}), 415

        data = request.get_json()
        logger.info(f"Received data: {data}")
        if not data:
            logger.error("No data received in the request.")
            return jsonify({'success': False, 'message': 'No data received.'}), 400

        try:
            # Fetch old match scores before updating
            old_home_score = match.home_team_score
            old_away_score = match.away_team_score

            # Update match scores and notes
            try:
                match.home_team_score = int(data.get('home_team_score', match.home_team_score))
                match.away_team_score = int(data.get('away_team_score', match.away_team_score))
            except ValueError as e:
                logger.error(f"Invalid score value: {str(e)}")
                return jsonify({'success': False, 'message': 'Invalid score value provided.'}), 400

            match.notes = data.get('notes', match.notes)

            # Process events
            process_events(match, data, PlayerEventType.GOAL, 'goals_to_add', 'goals_to_remove')
            process_events(match, data, PlayerEventType.ASSIST, 'assists_to_add', 'assists_to_remove')
            process_events(match, data, PlayerEventType.YELLOW_CARD, 'yellow_cards_to_add', 'yellow_cards_to_remove')
            process_events(match, data, PlayerEventType.RED_CARD, 'red_cards_to_add', 'red_cards_to_remove')

            db.session.commit()
            logger.info(f"All changes committed to the database for Match ID: {match_id}")

            # Update standings after reporting the match
            update_standings(match, old_home_score, old_away_score)
            logger.info(f"Standings updated for Match ID {match_id}")

            return jsonify({'success': True}), 200

        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Database error reporting match {match_id}: {str(e)}")
            return jsonify({'success': False, 'message': 'An error occurred while reporting the match.'}), 500

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Unexpected error reporting match {match_id}: {str(e)}")
            return jsonify({'success': False, 'message': 'An unexpected error occurred.'}), 500

    else:
        logger.error(f"Unsupported method {request.method} for report_match endpoint.")
        return jsonify({'success': False, 'message': 'Method not allowed.'}), 405

@teams_bp.route('/standings')
@login_required
def view_standings():
    # Get the current season
    season = Season.query.filter_by(is_current=True, league_type='Pub League').first()

    if not season:
        flash('No current season found.', 'warning')
        return redirect(url_for('home.index'))

    # Fetch standings for Premier League
    premier_standings = Standings.query.join(Team).join(League).filter(
        Standings.season_id == season.id,
        Team.id == Standings.team_id,
        League.id == Team.league_id,
        League.name == 'Premier'
    ).order_by(
        Standings.points.desc(),
        Standings.goal_difference.desc(),
        Standings.goals_for.desc()
    ).all()

    # Fetch standings for Classic League
    classic_standings = Standings.query.join(Team).join(League).filter(
        Standings.season_id == season.id,
        Team.id == Standings.team_id,
        League.id == Team.league_id,
        League.name == 'Classic'
    ).order_by(
        Standings.points.desc(),
        Standings.goal_difference.desc(),
        Standings.goals_for.desc()
    ).all()

    # Fetch additional stats for Premier teams
    premier_stats = {}
    for standing in premier_standings:
        team_stats = populate_team_stats(standing.team, season)
        premier_stats[standing.team.id] = team_stats

    # Fetch additional stats for Classic teams
    classic_stats = {}
    for standing in classic_standings:
        team_stats = populate_team_stats(standing.team, season)
        classic_stats[standing.team.id] = team_stats

    return render_template(
        'view_standings.html',
        premier_standings=premier_standings,
        classic_standings=classic_standings,
        premier_stats=premier_stats,
        classic_stats=classic_stats
    )