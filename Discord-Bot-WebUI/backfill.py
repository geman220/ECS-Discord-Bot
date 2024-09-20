from app import create_app, db
from app.models import User, Player

# Create an app context
app = create_app()
app.app_context().push()

# Query for users without linked players
users_without_players = User.query.filter(User.player == None).all()

for user in users_without_players:
    player = Player.query.filter_by(email=user.email).first()
    if player:
        player.user_id = user.id
        db.session.commit()

print("Script completed successfully.")
