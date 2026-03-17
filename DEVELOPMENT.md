# ECS Discord Bot - Development Guide

This document provides a technical overview of the ECS Discord Bot and League Management System, intended for developers contributing to the project.

## System Overview

The system is a distributed application consisting of several interconnected components:

1.  **Discord Bot (`ECS_Discord_Bot.py`)**: The primary interface for users on Discord. Built with `discord.py`, it handles slash commands, event monitoring, and real-time match updates.
2.  **Web Interface (`Discord-Bot-WebUI/`)**: A Flask-based administrative panel for managing leagues, teams, and players.
3.  **FastAPI Bridge (`bot_rest_api.py`)**: A REST API co-located with the Discord bot, allowing the WebUI to trigger bot actions (e.g., creating roles, sending messages).
4.  **Celery Workers**: Background processors for long-running tasks:
    *   `celery-worker`: General tasks (email, SMS).
    *   `celery-discord-worker`: Discord API operations.
    *   `celery-live-reporting-worker`: Real-time match data processing.
5.  **Shared Database**: A PostgreSQL database shared between the Bot and WebUI.

## Core Components & Data Flow

### **1. Bot-WebUI Communication**
The Bot and WebUI communicate via two primary methods:
-   **Shared Database**: Both systems read/write to the same PostgreSQL instance for persistent data (e.g., match dates, player info).
-   **REST API**: The WebUI makes HTTP requests to the Bot's FastAPI server (port 5001) for real-time actions.
-   **Redis/Celery**: Asynchronous tasks are queued in Redis and picked up by specialized workers.

### **2. Match Day Lifecycle**
1.  **Scheduling**: Match dates are imported via `/createschedule` or the WebUI.
2.  **Preparation**: 24 hours before kickoff, a background task creates a Discord thread and starts monitoring the match.
3.  **Live Updates**: During the match, `match_utils.py` fetches data from ESPN and updates the Discord thread.
4.  **Completion**: Post-match, stats are finalized and predictions are scored.

## Development Workflow

### **1. Code Organization**
-   Bot logic is modularized into `match_commands.py`, `general_commands.py`, `admin_commands.py`, etc.
-   Common utilities reside in `utils.py` and `common.py`.
-   WebUI logic follows the Flask Blueprint pattern in `Discord-Bot-WebUI/app/routes/`.

### **2. Adding New Commands**
To add a new Discord command:
1.  Identify the appropriate command module (e.g., `general_commands.py`).
2.  Implement the command using `@app_commands.command()`.
3.  Register the command in `ECS_Discord_Bot.py`.
4.  **Add a unit test** in `tests/` mocking the Discord interaction.

### **3. Database Migrations**
We use `Alembic` (via `Flask-Migrate`) for database migrations.
```bash
cd Discord-Bot-WebUI
# Create a new migration
flask db migrate -m "Description of changes"
# Apply migrations
flask db upgrade
```

## Testing Strategy

### **1. Unit Testing**
-   **Bot**: Use `pytest` with `unittest.mock` to mock Discord objects (`Interaction`, `Member`, `Guild`).
-   **WebUI**: Use the Flask test client and an in-memory SQLite database for fast unit tests.
-   **Utils**: Pure functions in `utils.py` should be tested for edge cases.

### **2. Integration Testing**
Integration tests verify the communication between the Bot API and the WebUI. These often require a running Redis/PostgreSQL instance (provided in `docker-compose.test.yml`).

### **3. Running Tests**
The easiest way to run the entire test suite is using the unified build and test scripts:
- **Mac/Linux**: `./buildAndTest.sh`
- **Windows**: `.\buildAndTest.ps1`

Alternatively, you can run them individually:
- Root tests: `pytest tests/`

-   WebUI tests: `cd Discord-Bot-WebUI && python run_tests.py --all`
-   Frontend tests: `cd Discord-Bot-WebUI && npm test`

## Best Practices

1.  **Asynchronous Programming**: Always use `await` for I/O-bound operations in the bot.
2.  **Error Handling**: Use the provided logging infrastructure. Never let an exception crash the main bot loop.
3.  **Security**: Never hardcode secrets. Use environment variables and `.env` files.
4.  **Type Hinting**: Use Python type hints to improve code clarity and catch bugs early.
5.  **Documentation**: Update docstrings for all new functions and classes.
