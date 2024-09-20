from app import db, create_app  # Assuming you have a create_app function in your app package
from app.models import Schedule, Match, Team

def migrate_schedule_to_matches():
    app = create_app()  # Create your Flask app instance
    with app.app_context():  # Push the application context
        # Track created matches to avoid duplicates
        created_matches = {}

        # Get all the schedule entries
        schedules = Schedule.query.all()

        for schedule in schedules:
            # Create a unique key for each match
            match_key = (
                schedule.date,
                schedule.time,
                schedule.location,
                min(schedule.team_id, schedule.opponent),  # Ensure team order doesn't matter
                max(schedule.team_id, schedule.opponent)
            )

            # Check if this match has already been created
            if match_key not in created_matches:
                # Create a corresponding match entry
                match = Match(
                    date=schedule.date,
                    time=schedule.time,
                    location=schedule.location,
                    home_team_id=schedule.team_id,
                    away_team_id=schedule.opponent
                )
                db.session.add(match)
                db.session.flush()  # Ensure match ID is available

                # Store the created match with its key
                created_matches[match_key] = match.id

            # Update the schedule entry to reference the match
            match_id = created_matches[match_key]
            schedule.match_id = match_id  # Add this column to link schedule to match

        # Commit all changes
        db.session.commit()

        print(f"Migrated {len(created_matches)} unique matches from schedules.")

# Run the migration
if __name__ == "__main__":
    migrate_schedule_to_matches()
