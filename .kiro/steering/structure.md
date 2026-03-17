# Project Structure: ECS Discord Bot & WebUI

## Repository Organization

The project follows a split-module architecture with a root Discord bot and a secondary administrative web application:

```
/Users/hodo/repos/emeraldcitysupporters/ECS-Discord-Bot/
├── ECS_Discord_Bot.py          # Root entry point for the Discord bot
├── api/                        # Shared API client and utility modules
├── docs/                       # Project documentation (Markdown files)
├── tests/                      # Unit tests for the root bot
├── utils.py, common.py         # Shared utility and common functions
└── Discord-Bot-WebUI/          # Sub-project: Flask web application
    ├── app/                    # Core WebUI logic (Models, Routes, Services)
    ├── scripts/                # Utility and maintenance scripts
    ├── static/                 # Frontend assets (JS, CSS, images)
    ├── tests/                  # Unit and integration tests for WebUI
    ├── wsgi.py                 # WebUI entry point
    └── package.json            # Frontend dependency and test configuration
```

## Source Code Structure

### **1. Discord Bot (Root)**
- **Entry Points**: `ECS_Discord_Bot.py` (bot execution), `bot_rest_api.py` (internal FastAPI).
- **Command Modules**: `match_commands.py`, `general_commands.py`, `admin_commands.py`, `publeague_commands.py`.
- **Logic & Utils**: `match_utils.py`, `api_helpers.py`, `automations.py`.
- **Shared States**: `shared_states.py` for bot state management.

### **2. Web Interface (Discord-Bot-WebUI/)**
- **Models**: `app/models/` contains SQLAlchemy database definitions.
- **Routes**: `app/routes/` organized by functional area (e.g., `match_routes.py`, `league_routes.py`).
- **Services**: `app/services/` contains external integration logic.
- **Background Tasks**: `celery_worker.py` and specialized workers in the `Discord-Bot-WebUI/` root.

## Key Conventions

### **Python Naming Patterns**
- **Modules**: Snake case (`match_commands.py`).
- **Functions/Variables**: Snake case (`get_next_match()`).
- **Classes**: Pascal case (`MatchCommands`).
- **Constants**: Upper snake case (`WEBUI_API_URL`).

### **Shared Database (PostgreSQL)**
- The database is the primary source of truth shared between the Bot and WebUI.
- All persistent states (player rosters, match dates, league results) are stored here.
- Migrations are managed via `flask-migrate` within the `Discord-Bot-WebUI/` directory.

### **Internal Communication**
- The WebUI communicates with the Bot via HTTP requests to the FastAPI bridge (port 5001).
- The Bot communicates with the WebUI via the `api/utils/api_client.py` wrapper.

## Build & Testing Artifacts
- **htmlcov/**: Generated Python coverage reports.
- **node_modules/**: Frontend dependencies in `Discord-Bot-WebUI/` (gitignored).
- **logs/**: Local log files for bot and web services (gitignored).
