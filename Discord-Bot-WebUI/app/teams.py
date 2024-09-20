from flask import Blueprint, render_template, redirect, url_for, flash, request
from collections import defaultdict
from sqlalchemy import func
from sqlalchemy.orm import aliased, joinedload, selectinload
from app import db
from app.models import Team, Player, Schedule, League, Season, Goal, Assist, YellowCard, RedCard, Match, Standings
from flask_login import login_required

teams_bp = Blueprint('teams', __name__)

def populate_team_stats(team, season):
    # Calculate top scorer
    top_scorer_name, top_scorer_goals = db.session.query(Player.name, func.count(Goal.id))\
        .join(Goal, Goal.player_id == Player.id)\
        .join(Match, Goal.match_id == Match.id)\
        .join(Team, Team.id == team.id)\
        .join(League, League.id == Team.league_id)\
        .filter(
            ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
            League.season_id == season.id,
            Player.team_id == team.id
        )\
        .group_by(Player.name)\
        .order_by(func.count(Goal.id).desc())\
        .first() or ("No goals scored", 0)

    # Calculate top assister
    top_assister_name, top_assister_assists = db.session.query(Player.name, func.count(Assist.id))\
        .join(Assist, Assist.player_id == Player.id)\
        .join(Match, Assist.match_id == Match.id)\
        .join(Team, Team.id == team.id)\
        .join(League, League.id == Team.league_id)\
        .filter(
            ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
            League.season_id == season.id,
            Player.team_id == team.id
        )\
        .group_by(Player.name)\
        .order_by(func.count(Assist.id).desc())\
        .first() or ("No assists recorded", 0)

    # Calculate recent form
    matches = Match.query.join(Team, (Match.home_team_id == team.id) | (Match.away_team_id == team.id))\
        .join(League, League.id == Team.league_id)\
        .filter(
            League.season_id == season.id,
            (Match.home_team_id == team.id) | (Match.away_team_id == team.id)
        )\
        .order_by(Match.date.desc()).limit(5).all()

    recent_form = ''.join([
        'W' if (match.home_team_id == team.id and (match.home_team_score or 0) > (match.away_team_score or 0)) or
               (match.away_team_id == team.id and (match.away_team_score or 0) > (match.home_team_score or 0))
        else 'D' if (match.home_team_score or 0) == (match.away_team_score or 0)
        else 'L'
        for match in matches
        if match.home_team_score is not None and match.away_team_score is not None
    ])

    # Calculate average goals per match
    total_goals = sum([
        (match.home_team_score or 0) if match.home_team_id == team.id else (match.away_team_score or 0)
        for match in matches
    ])
    avg_goals_per_match = total_goals / len(matches) if matches else 0

    return {
        "top_scorer_name": top_scorer_name,
        "top_scorer_goals": top_scorer_goals,
        "top_assister_name": top_assister_name,
        "top_assister_assists": top_assister_assists,
        "recent_form": recent_form,
        "avg_goals_per_match": avg_goals_per_match
    }

def update_standings(match):
    home_team_standing = Standings.query.filter_by(team_id=match.home_team_id, season_id=match.schedule.season.id).first()
    away_team_standing = Standings.query.filter_by(team_id=match.away_team_id, season_id=match.schedule.season.id).first()

    # Update games played
    home_team_standing.played += 1
    away_team_standing.played += 1

    # Determine the match outcome and update standings
    if match.home_team_score > match.away_team_score:
        # Home team wins
        home_team_standing.won += 1
        home_team_standing.points += 3
        away_team_standing.lost += 1
    elif match.home_team_score < match.away_team_score:
        # Away team wins
        away_team_standing.won += 1
        away_team_standing.points += 3
        home_team_standing.lost += 1
    else:
        # Draw
        home_team_standing.drawn += 1
        away_team_standing.drawn += 1
        home_team_standing.points += 1
        away_team_standing.points += 1

    # Update goals for and against
    home_team_standing.goals_for += match.home_team_score
    home_team_standing.goals_against += match.away_team_score
    away_team_standing.goals_for += match.away_team_score
    away_team_standing.goals_against += match.home_team_score

    # Update goal difference
    home_team_standing.goal_difference = home_team_standing.goals_for - home_team_standing.goals_against
    away_team_standing.goal_difference = away_team_standing.goals_for - away_team_standing.goals_against

    # Commit the standings update
    db.session.commit()

@teams_bp.route('/<int:team_id>')
@login_required
def team_details(team_id):
    team = Team.query.get_or_404(team_id)
    league = team.league
    season = league.season  # Assuming league.season gives the current season
    players = Player.query.filter_by(team_id=team_id).all()

    # Fetch the stats for each player for the current season
    for player in players:
        player.goals_count = db.session.query(func.count(Goal.id))\
            .join(Match, Goal.match_id == Match.id)\
            .filter(
                Goal.player_id == player.id,
                (Match.home_team_id == team.id) | (Match.away_team_id == team.id),
                league.season_id == season.id  # Assuming the league is associated with the current season
            ).scalar()

        player.assists_count = db.session.query(func.count(Assist.id))\
            .join(Match, Assist.match_id == Match.id)\
            .filter(
                Assist.player_id == player.id,
                (Match.home_team_id == team.id) | (Match.away_team_id == team.id),
                league.season_id == season.id
            ).scalar()

        player.yellow_cards_count = db.session.query(func.count(YellowCard.id))\
            .join(Match, YellowCard.match_id == Match.id)\
            .filter(
                YellowCard.player_id == player.id,
                (Match.home_team_id == team.id) | (Match.away_team_id == team.id),
                league.season_id == season.id
            ).scalar()

        player.red_cards_count = db.session.query(func.count(RedCard.id))\
            .join(Match, RedCard.match_id == Match.id)\
            .filter(
                RedCard.player_id == player.id,
                (Match.home_team_id == team.id) | (Match.away_team_id == team.id),
                league.season_id == season.id
            ).scalar()

    # Aliases for home and away teams
    home_team = aliased(Team)
    away_team = aliased(Team)

    # Updated query to fetch the schedule with opponent team names and scores, using joinedload to eagerly load related entities
    matches = Match.query.options(
        selectinload(Match.goals),
        selectinload(Match.assists),
        selectinload(Match.yellow_cards),
        selectinload(Match.red_cards),
        selectinload(Match.home_team).selectinload(Team.players),
        selectinload(Match.away_team).selectinload(Team.players)
    ).filter(
        (Match.home_team_id == team_id) | (Match.away_team_id == team_id)
    ).order_by(Match.date).all()

    # Group the schedule by date
    grouped_schedule = defaultdict(list)
    for match in matches:
        # Determine opponent_name regardless of whether the scores are available
        if match.home_team_id == team_id:
            opponent_name = match.away_team.name
            your_team_name = match.home_team.name
        else:
            opponent_name = match.home_team.name
            your_team_name = match.away_team.name

        # Handle cases where scores are not reported yet
        if match.home_team_score is not None and match.away_team_score is not None:
            if match.home_team_id == team_id:
                your_team_score = match.home_team_score
                opponent_score = match.away_team_score
                result_class = 'success' if your_team_score > opponent_score else 'danger' if your_team_score < opponent_score else 'secondary'
            else:
                your_team_score = match.away_team_score
                opponent_score = match.home_team_score
                result_class = 'success' if your_team_score > opponent_score else 'danger' if your_team_score < opponent_score else 'secondary'
        else:
            your_team_score = 'N/A'
            opponent_score = 'N/A'
            result_class = 'secondary'

        grouped_schedule[match.date].append({
            'id': match.id,
            'time': match.time,
            'location': match.location,
            'opponent_name': opponent_name,
            'your_team_name': your_team_name,
            'home_team_name': match.home_team.name,
            'away_team_name': match.away_team.name,
            'your_team_score': your_team_score,
            'opponent_score': opponent_score,
            'result_class': result_class,
            'reported': match.reported,  # Access the reported property
            'home_players': match.home_team.players,  # Pass home team players
            'away_players': match.away_team.players   # Pass away team players
        })

    return render_template('team_details.html', team=team, players=players, schedule=grouped_schedule, league=league, season=season)

@teams_bp.route('/')
@login_required
def teams_overview():
    teams = Team.query.order_by(Team.name).all()
    return render_template('teams_overview.html', teams=teams)

@teams_bp.route('/report_match/<int:match_id>', methods=['POST'])
@login_required
def report_match(match_id):
    match = Match.query.get_or_404(match_id)
    
    # If you need season_id
    season_id = match.home_team.league.season.id
    
    # Update match scores
    match.home_team_score = int(request.form['home_team_score'])
    match.away_team_score = int(request.form['away_team_score'])
    match.notes = request.form.get('notes', '')

    # Dictionary to store stats changes
    player_stats_changes = {}

    def update_player_stats(player_id, stat_type):
        if player_id not in player_stats_changes:
            player_stats_changes[player_id] = {'goals': 0, 'assists': 0, 'yellow_cards': 0, 'red_cards': 0}
        player_stats_changes[player_id][stat_type] += 1

    # Process goal scorers
    goal_scorers = request.form.getlist('goal_scorers[]')
    goal_minutes = request.form.getlist('goal_minutes[]')
    for player_id, minute in zip(goal_scorers, goal_minutes):
        goal = Goal(player_id=player_id, match_id=match.id, minute=minute or None)
        db.session.add(goal)
        update_player_stats(player_id, 'goals')

    # Process assist providers
    assist_providers = request.form.getlist('assist_providers[]')
    assist_minutes = request.form.getlist('assist_minutes[]')
    for player_id, minute in zip(assist_providers, assist_minutes):
        assist = Assist(player_id=player_id, match_id=match.id, minute=minute or None)
        db.session.add(assist)
        update_player_stats(player_id, 'assists')

    # Process yellow cards
    yellow_cards = request.form.getlist('yellow_cards[]')
    yellow_card_minutes = request.form.getlist('yellow_card_minutes[]')
    for player_id, minute in zip(yellow_cards, yellow_card_minutes):
        yellow_card = YellowCard(player_id=player_id, match_id=match.id, minute=minute or None)
        db.session.add(yellow_card)
        update_player_stats(player_id, 'yellow_cards')

    # Process red cards
    red_cards = request.form.getlist('red_cards[]')
    red_card_minutes = request.form.getlist('red_card_minutes[]')
    for player_id, minute in zip(red_cards, red_card_minutes):
        red_card = RedCard(player_id=player_id, match_id=match.id, minute=minute or None)
        db.session.add(red_card)
        update_player_stats(player_id, 'red_cards')

    # Commit all changes to the match
    db.session.commit()

    # Update player stats
    for player_id, stats_changes in player_stats_changes.items():
        player = Player.query.get(player_id)
        if player:
            player.update_season_stats(season_id, stats_changes)

    # Update standings
    update_standings(match)

    flash('Match report updated successfully.', 'success')

    # Redirect back to the page where the modal was opened
    return redirect(request.referrer)

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
