from flask import Blueprint, jsonify, render_template
from app.models import Match, Team, Season, League
from sqlalchemy.orm import aliased
from flask_login import login_required
from app.decorators import role_required


calendar_bp = Blueprint('calendar', __name__)

@calendar_bp.route('/calendar/events', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def get_schedule():
    # Get all current seasons
    seasons = Season.query.filter_by(is_current=True).all()

    if not seasons:
        return jsonify({'error': 'No current season found.'}), 404

    # Collect all league IDs for the current seasons (Pub League and ECS FC)
    league_ids = [league.id for season in seasons for league in season.leagues]

    # Create aliases for the home and away teams
    home_team = aliased(Team)
    away_team = aliased(Team)

    # Query all matches for all current seasons using the league IDs
    matches = (Match.query
               .join(home_team, Match.home_team_id == home_team.id)
               .join(away_team, Match.away_team_id == away_team.id)
               .with_entities(
                   Match.id,
                   Match.date,
                   Match.time,
                   Match.location,
                   home_team.name.label('home_team_name'),
                   away_team.name.label('away_team_name'),
                   home_team.league_id.label('home_league_id')
               )
               .filter(home_team.league_id.in_(league_ids))
               .all())

    if not matches:
        return jsonify({'message': 'No matches found'}), 404

    # Format the matches as events for FullCalendar
    events = []
    for match in matches:
        # Use the league of the home team as the division (adjust as necessary)
        division = 'Premier' if match.home_league_id == 10 else 'Classic'
        events.append({
            'id': match.id,  # This is needed for linking to the match detail page
            'title': f"{division}: {match.home_team_name} vs {match.away_team_name}",
            'start': f"{match.date.isoformat()}T{match.time.strftime('%H:%M:%S')}",
            'description': f"Location: {match.location}",
            'color': 'blue' if division == 'Premier' else 'green',  # Color-code divisions
            'url': f"/matches/{match.id}"  # Link to match detail page
        })

    return jsonify(events)

@calendar_bp.route('/calendar', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def calendar_view():
    return render_template('calendar.html')
