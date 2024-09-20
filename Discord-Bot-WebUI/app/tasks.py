from celery import shared_task
from app import create_app, db  # Import the create_app function
from app.models import Team, Match
import requests

@shared_task
def schedule_post_availability(team1_id, team2_id, match_date, match_time):
    app, celery = create_app() 
    with app.app_context():
        # Directly use the known match ID for testing
        match_id = 111  # Replace with your forced match ID
        match = db.session.query(Match).filter_by(id=match_id).first()

        if not match:
            return "Match not found. Please ensure the match is scheduled correctly."

        # Set the URL for your FastAPI endpoint
        url = "http://discord-bot:5001/api/post_availability"

        # Prepare the payload for posting to Discord bot API
        payload = {
            "match_id": match.id,
            "home_channel_id": match.home_team.discord_channel_id,
            "away_channel_id": match.away_team.discord_channel_id,
            "match_date": match_date,
            "match_time": match_time,
            "home_team_name": match.home_team.name,
            "away_team_name": match.away_team.name
        }

        headers = {
            "Content-Type": "application/json"
        }

        # Send the request to the FastAPI endpoint
        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            return "Availability requests posted successfully"
        else:
            return f"Failed to post availability: {response.text}"

@shared_task
def test_task():
    print("Test task executed successfully")
    return "Task completed"