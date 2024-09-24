from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_wtf.csrf import validate_csrf, CSRFError
from collections import defaultdict
from sqlalchemy import func
from sqlalchemy.orm import aliased, joinedload, selectinload
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import Team, Player, Schedule, League, Season, Match, Standings, PlayerEventType, PlayerEvent, PlayerSeasonStats
from app.main import fetch_upcoming_matches
from app.forms import ReportMatchForm, PlayerEventForm
from flask_login import login_required, current_user
import logging

# Initialize logger
logger = logging.getLogger(__name__)

teams_bp = Blueprint('teams', __name__)

def populate_team_stats(team, season, for_match_reporting=False):
    # Calculate top scorer using PlayerSeasonStats
    top_scorer = db.session.query(Player.name, PlayerSeasonStats.goals)\
        .join(PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id)\
        .filter(
            PlayerSeasonStats.season_id == season.id,
            Player.team_id == team.id
        )\
        .order_by(PlayerSeasonStats.goals.desc())\
        .first()

    top_scorer_name, top_scorer_goals = top_scorer if top_scorer and top_scorer.goals > 0 else ("No goals scored", 0)

    # Calculate top assister using PlayerSeasonStats
    top_assister = db.session.query(Player.name, PlayerSeasonStats.assists)\
        .join(PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id)\
        .filter(
            PlayerSeasonStats.season_id == season.id,
            Player.team_id == team.id
        )\
        .order_by(PlayerSeasonStats.assists.desc())\
        .first()

    top_assister_name, top_assister_assists = top_assister if top_assister and top_assister.assists > 0 else ("No assists recorded", 0)

    # Calculate recent form using Match results
    if for_match_reporting:
        # Use match reporting logic
        matches = Match.query.filter(
            ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
            team.league_id == season.league_id  # This logic works for match reporting
        ).order_by(Match.date.desc()).limit(5).all()
    else:
        # Use standings logic
        matches = Match.query.filter(
            ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
            team.league_id == League.id,  # Access the league through the team model
            League.season_id == season.id  # This logic works for standings
        ).order_by(Match.date.desc()).limit(5).all()

    recent_form = ''.join([
        'W' if (match.home_team_id == team.id and (match.home_team_score or 0) > (match.away_team_score or 0)) or
               (match.away_team_id == team.id and (match.away_team_score or 0) > (match.home_team_score or 0))
        else 'D' if (match.home_team_score or 0) == (match.away_team_score or 0)
        else 'L'
        for match in matches
        if match.home_team_score is not None and match.away_team_score is not None
    ]) or "N/A"

    # Calculate average goals per match using PlayerSeasonStats
    total_goals = db.session.query(func.sum(PlayerSeasonStats.goals))\
        .join(Player, PlayerSeasonStats.player_id == Player.id)\
        .filter(
            PlayerSeasonStats.season_id == season.id,
            Player.team_id == team.id
        ).scalar() or 0

    matches_played = db.session.query(func.count(Match.id))\
        .filter(
            ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
            team.league_id == (season.league_id if for_match_reporting else League.id),  # Adjust league access
            (None if for_match_reporting else League.season_id == season.id)  # Skip season filter for match reporting
        ).scalar() or 1

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
        away_team_standing = Standings.query.filter_by(team_id=away_team.id, season_id=season.id).first()

        # Revert old match result if provided (i.e., if editing a match)
        if old_home_score is not None and old_away_score is not None:
            logger.info(f"Reverting old match result for Match ID: {match.id}")
            if old_home_score > old_away_score:
                # Revert a previous win for the home team
                home_team_standing.wins -= 1
                away_team_standing.losses -= 1
            elif old_home_score < old_away_score:
                # Revert a previous win for the away team
                away_team_standing.wins -= 1
                home_team_standing.losses -= 1
            else:
                # Revert a previous draw
                home_team_standing.draws -= 1
                away_team_standing.draws -= 1

            # Update goals for/against and goal difference
            home_team_standing.goals_for -= old_home_score
            home_team_standing.goals_against -= old_away_score
            away_team_standing.goals_for -= old_away_score
            away_team_standing.goals_against -= old_home_score

            home_team_standing.goal_difference = home_team_standing.goals_for - home_team_standing.goals_against
            away_team_standing.goal_difference = away_team_standing.goals_for - away_team_standing.goals_against

            # Revert points based on old result
            home_team_standing.points = (home_team_standing.wins * 3) + home_team_standing.draws
            away_team_standing.points = (away_team_standing.wins * 3) + away_team_standing.draws

            # Decrement played matches
            home_team_standing.played -= 1
            away_team_standing.played -= 1

        # Now apply the new match result
        if match.home_team_score > match.away_team_score:
            home_team_standing.wins += 1
            away_team_standing.losses += 1
        elif match.home_team_score < match.away_team_score:
            away_team_standing.wins += 1
            home_team_standing.losses += 1
        else:
            home_team_standing.draws += 1
            away_team_standing.draws += 1

        # Update points for the new result
        home_team_standing.points = (home_team_standing.wins * 3) + home_team_standing.draws
        away_team_standing.points = (away_team_standing.wins * 3) + away_team_standing.draws

        # Update goals for and against
        home_team_standing.goals_for += match.home_team_score
        home_team_standing.goals_against += match.away_team_score
        away_team_standing.goals_for += match.away_team_score
        away_team_standing.goals_against += match.home_team_score

        # Update goal difference
        home_team_standing.goal_difference = home_team_standing.goals_for - home_team_standing.goals_against
        away_team_standing.goal_difference = away_team_standing.goals_for - away_team_standing.goals_against

        # Increment played matches
        home_team_standing.played += 1
        away_team_standing.played += 1

        # Commit the standings updates
        db.session.commit()
        logger.info(f"Standings updated for Match ID {match.id}")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating standings: {str(e)}")
        raise e

def process_events(match, data, event_type, add_key, remove_key):
    logger.info(f"Processing events for {event_type.name}")

    # Retrieve events to add and remove from the data
    events_to_add = data.get(add_key, [])
    events_to_remove = data.get(remove_key, [])

    # Log the events for debugging purposes
    logger.info(f"Events to add for {event_type.name}: {events_to_add}")
    logger.info(f"Events to remove for {event_type.name}: {events_to_remove}")

    # Convert event_type to its value for comparison (if needed)
    event_type_value = event_type.value

    # Process events to remove
    for event_data in events_to_remove:
        stat_id = event_data.get('stat_id')
        if stat_id:
            event = PlayerEvent.query.get(stat_id)
            if event:
                # Decrement player stats
                update_player_stats(event.player_id, event.event_type.value, increment=False)
                db.session.delete(event)
                logger.info(f"Removed {event_type.name}: Player ID {event.player_id}, Stat ID: {stat_id}")

    # Process events to add or update
    for event_data in events_to_add:
        player_id = event_data.get('player_id')
        minute = event_data.get('minute')
        stat_id = event_data.get('stat_id')
        
        # Convert IDs to integers
        player_id = int(player_id)
        if stat_id:
            stat_id = int(stat_id)

        if stat_id:
            # Update existing event
            event = PlayerEvent.query.get(stat_id)
            if event:
                # Check if player_id has changed
                if event.player_id != player_id:
                    # Decrement stats for old player
                    update_player_stats(event.player_id, event.event_type, increment=False)
                    # Increment stats for new player
                    update_player_stats(player_id, event_type_value, increment=True)
                    # Update player_id in the event
                    event.player_id = player_id
                # Update minute
                event.minute = minute if minute else None
                logger.info(f"Updated {event_type.name}: Player ID {player_id}, Minute {event.minute}, Stat ID: {stat_id}")
        else:
            # Add new event
            new_event = PlayerEvent(
                player_id=player_id,
                match_id=match.id,
                minute=minute if minute else None,
                event_type=event_type  # Use enum member directly
            )
            db.session.add(new_event)
            logger.info(f"Added New {event_type.name}: Player ID {player_id}, Minute {minute}")
            # Increment player stats
            update_player_stats(player_id, event_type_value)

def update_player_stats(player_id, event_type, increment=True):
    logger.info(f"Updating stats for player_id={player_id}, event_type={event_type}, increment={increment}")
    player = Player.query.get(player_id)
    season_id = current_season_id()
    season_stats = PlayerSeasonStats.query.filter_by(player_id=player_id, season_id=season_id).first()
    career_stats = player.career_stats

    if not season_stats:
        # If season stats do not exist, create them
        season_stats = PlayerSeasonStats(player_id=player_id, season_id=season_id, goals=0, assists=0, yellow_cards=0, red_cards=0)
        db.session.add(season_stats)

    if not career_stats:
        # If career stats do not exist, create them
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
    except Exception as e:
        logger.exception(f"Error updating stats for player_id={player_id}: {e}")
        raise

def current_season_id():
    current_season = Season.query.filter_by(is_current=True).first()
    return current_season.id if current_season else None

@teams_bp.route('/<int:team_id>')
@login_required
def team_details(team_id):
    team = Team.query.get_or_404(team_id)
    league = League.query.get(team.league_id)
    season = league.season  # Assuming league.season gives the current season
    players = Player.query.filter_by(team_id=team_id).all()

    report_form = ReportMatchForm()

    # Fetch the player profile associated with the current user
    player = getattr(current_user, 'player', None)
    user_team = player.team if player else None

    grouped_matches = fetch_upcoming_matches(team, match_limit=None, include_past_matches=True) 

    # Initialize player_choices_per_match as an empty dictionary
    player_choices_per_match = {}

    # Fetch the stats for each player for the current season using PlayerSeasonStats
    player_stats = db.session.query(PlayerSeasonStats)\
        .join(Player, PlayerSeasonStats.player_id == Player.id)\
        .filter(
            Player.team_id == team_id,
            PlayerSeasonStats.season_id == season.id
        ).all()

    # Create a dictionary for easy access
    stats_dict = {stats.player_id: stats for stats in player_stats}

    # Assign stats to players
    for player in players:
        stats = stats_dict.get(player.id, None)
        if stats:
            player.goals_count = stats.goals or 0
            player.assists_count = stats.assists or 0
            player.yellow_cards_count = stats.yellow_cards or 0
            player.red_cards_count = stats.red_cards or 0
        else:
            player.goals_count = 0
            player.assists_count = 0
            player.yellow_cards_count = 0
            player.red_cards_count = 0

    # Fetch matches related to the team, using the team to access the league
    matches = Match.query.options(
        selectinload(Match.home_team).selectinload(Team.players),
        selectinload(Match.away_team).selectinload(Team.players)
    ).filter(
        (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
        (Match.home_team.has(league_id=league.id)) | (Match.away_team.has(league_id=league.id))
    ).order_by(Match.date.desc()).all()

    # Assign result_class based on match outcome
    for match in matches:
        if match.home_team_id == team_id:
            if (match.home_team_score or 0) > (match.away_team_score or 0):
                match.result_class = 'success'  # Win
            elif (match.home_team_score or 0) < (match.away_team_score or 0):
                match.result_class = 'danger'   # Loss
            else:
                match.result_class = 'secondary'  # Draw
        else:
            if (match.away_team_score or 0) > (match.home_team_score or 0):
                match.result_class = 'success'  # Win
            elif (match.away_team_score or 0) < (match.home_team_score or 0):
                match.result_class = 'danger'   # Loss
            else:
                match.result_class = 'secondary'  # Draw

    # Calculate recent form
    recent_form = ''.join([
        'W' if match.result_class == 'success' else
        'L' if match.result_class == 'danger' else
        'D'
        for match in matches
    ]) or "N/A"

    # Calculate average goals per match using PlayerSeasonStats
    total_goals = db.session.query(func.sum(PlayerSeasonStats.goals))\
        .join(Player, PlayerSeasonStats.player_id == Player.id)\
        .filter(
            Player.team_id == team_id,
            PlayerSeasonStats.season_id == season.id
        ).scalar() or 0

    matches_played = db.session.query(func.count(Match.id))\
        .filter(
            (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
            (Match.home_team.has(league_id=league.id)) | (Match.away_team.has(league_id=league.id))
        ).scalar() or 1

    avg_goals_per_match = round(total_goals / matches_played, 2) if matches_played else 0

    # Fetch all matches for detailed schedule
    all_matches = Match.query.options(
        selectinload(Match.home_team).selectinload(Team.players),
        selectinload(Match.away_team).selectinload(Team.players)
    ).filter(
        (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
        (Match.home_team.has(league_id=league.id)) | (Match.away_team.has(league_id=league.id))
    ).order_by(Match.date.desc()).all()

    # Group the schedule by date
    schedule = defaultdict(list)
    for match in all_matches:
        # Determine opponent_name and team names
        if match.home_team_id == team_id:
            opponent_name = match.away_team.name
            your_team_score = match.home_team_score if match.home_team_score is not None else 'N/A'
            opponent_score = match.away_team_score if match.away_team_score is not None else 'N/A'
            result_class = 'success' if (match.home_team_score or 0) > (match.away_team_score or 0) else \
                           'danger' if (match.home_team_score or 0) < (match.away_team_score or 0) else \
                           'secondary'
            opponent_team_name = match.away_team.name
            home_team_name = match.home_team.name
        else:
            opponent_name = match.home_team.name
            your_team_score = match.away_team_score if match.away_team_score is not None else 'N/A'
            opponent_score = match.home_team_score if match.home_team_score is not None else 'N/A'
            result_class = 'success' if (match.away_team_score or 0) > (match.home_team_score or 0) else \
                           'danger' if (match.away_team_score or 0) < (match.home_team_score or 0) else \
                           'secondary'
            opponent_team_name = match.home_team.name
            home_team_name = match.away_team.name

        match.result_class = result_class  # Assign result_class to match object

        schedule[match.date].append({
            'id': match.id,
            'time': match.time,
            'location': match.location,
            'opponent_name': opponent_name,
            'home_team_name': home_team_name,
            'opponent_team_name': opponent_team_name,
            'your_team_score': your_team_score,
            'opponent_score': opponent_score,
            'result_class': result_class,
            'reported': match.reported,
            'home_players': match.home_team.players,
            'away_players': match.away_team.players
        })

    # Prepare player choices for each match
    player_choices_per_match = {}
    for date, matches in grouped_matches.items():
        for match_data in matches:
            match = match_data['match']
            home_team_id = match_data['home_team_id']
            opponent_team_id = match_data['opponent_team_id']
        
            # Rename variable here as well
            match_players = Player.query.filter(Player.team_id.in_([home_team_id, opponent_team_id])).all()
        
            # Get team names
            home_team_name = Team.query.get(home_team_id).name
            opponent_team_name = Team.query.get(opponent_team_id).name
        
            # Structure the players by team using team names
            player_choices_per_match[match.id] = {
                home_team_name: {player.id: player.name for player in match_players if player.team_id == home_team_id},
                opponent_team_name: {player.id: player.name for player in match_players if player.team_id == opponent_team_id}
            }

    return render_template(
        'team_details.html',
        report_form=report_form,
        matches=matches,
        team=team,
        league=league,
        season=season,
        players=players,  # Pass the players with their stats
        recent_form=recent_form,
        avg_goals_per_match=avg_goals_per_match,
        grouped_matches=grouped_matches,
        player_choices=player_choices_per_match,
        schedule=schedule  # Add schedule here
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

    # Fetch all standings for the current season in one query
    all_standings = Standings.query.filter_by(season_id=season.id).all()
    standings_by_team = {standing.team_id: standing for standing in all_standings}

    # Get all teams in Premier and Classic leagues for the current season
    premier_teams = Team.query.join(League).filter(
        League.name == 'Premier',
        League.season_id == season.id
    ).all()

    classic_teams = Team.query.join(League).filter(
        League.name == 'Classic',
        League.season_id == season.id
    ).all()

    # Initialize standings for all Premier league teams
    premier_standings = []
    for team in premier_teams:
        standing = standings_by_team.get(team.id)
        if not standing:
            standing = Standings(
                team_id=team.id,
                season_id=season.id,
                played=0,
                won=0,
                drawn=0,
                lost=0,
                goals_for=0,
                goals_against=0,
                goal_difference=0,
                points=0
            )
            db.session.add(standing)
            db.session.commit()

        # Populate team stats
        team_stats = populate_team_stats(team, season)
        premier_standings.append((standing, team_stats))

    # Sort the premier standings
    premier_standings.sort(key=lambda s: (s[0].points, s[0].goal_difference, s[0].goals_for), reverse=True)

    # Initialize standings for all Classic league teams
    classic_standings = []
    for team in classic_teams:
        standing = standings_by_team.get(team.id)
        if not standing:
            standing = Standings(
                team_id=team.id,
                season_id=season.id,
                played=0,
                won=0,
                drawn=0,
                lost=0,
                goals_for=0,
                goals_against=0,
                goal_difference=0,
                points=0
            )
            db.session.add(standing)
            db.session.commit()

        # Populate team stats
        team_stats = populate_team_stats(team, season)
        classic_standings.append((standing, team_stats))

    # Sort the classic standings
    classic_standings.sort(key=lambda s: (s[0].points, s[0].goal_difference, s[0].goals_for), reverse=True)

    return render_template('view_standings.html', premier_standings=premier_standings, classic_standings=classic_standings)