# Product Overview: ECS Discord Bot & League Management System

The ECS Discord Bot is a comprehensive soccer team and league management system designed for the Emerald City Supporters (ECS), specifically supporting the ECS FC and Pub League. The system:

- Integrates Discord with a web interface for seamless league administration.
- Automates match thread creation, live score updates, and fan engagement on Discord.
- Manages multiple seasons, leagues, teams, and players through a Flask-based WebUI.
- Tracks player RSVPs, match statistics (goals, assists, cards), and league standings.
- Facilitates communication between coaches and players via Discord role-based messaging.
- Verifies ECS membership via WooCommerce order integration.

## Key Components

- **Discord Bot**: Real-time interaction, match updates, and team communication.
- **Flask Web Application (WebUI)**: Administrative portal for season, team, and player management.
- **FastAPI Bridge**: Internal API allowing the WebUI to trigger Discord bot actions.
- **Integrated Backend**: Shared PostgreSQL database and Redis/Celery for background tasks.
- **Match Management**: Automated scheduling and live reporting via external APIs (ESPN, OpenWeather).

## Target Users

- **League Administrators**: Manage seasons, league structures, and global settings.
- **Team Coaches**: Manage rosters, communicate with players, and report match results.
- **Players**: Register for teams, RSVP for matches, and track personal statistics.
- **ECS Members/Fans**: Participate in match predictions, view stats, and engage in Discord match threads.
