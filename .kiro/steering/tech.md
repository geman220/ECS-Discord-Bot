# Technology Stack: ECS Discord Bot & WebUI

## Core Technologies

- **Python**: Primary development platform (3.11+)
  - **Discord.py**: Async framework for the Discord bot.
  - **Flask**: Production-ready web framework for the administrative WebUI.
  - **FastAPI**: Lightweight REST API for internal communication (co-located with bot).

- **Frontend (WebUI)**:
  - **Vite & Tailwind CSS**: Modern toolchain and styling for the Web interface.
  - **Socket.IO**: Real-time communication for live match reporting and player drafts.

- **Storage & Caching**:
  - **PostgreSQL**: Primary relational database with SQLAlchemy ORM.
  - **Redis**: Session management, result caching, and message queue for Celery.

- **Asynchronous Processing**:
  - **Celery**: Background task queue with specialized workers (Discord, Live Reporting, Player Sync).

- **Containerization**:
  - **Docker & Docker Compose**: Microservices architecture for easy deployment and isolation.

## Key Dependencies

- **aiohttp**: Async HTTP requests for API integrations (ESPN, OpenWeather).
- **WooCommerce**: Integration for membership verification.
- **Pytest**: Core testing framework.

## Common Commands

### **Discord Bot (Root)**
```bash
# Run unit tests
pytest tests/

# Run bot locally (requires .env)
python ECS_Discord_Bot.py
```

### **WebUI (Discord-Bot-WebUI/)**
```bash
# Run all Python tests (unit + integration)
python run_tests.py --all

# Run frontend tests (Vitest)
npm test

# Build production assets
npm run build
```

### **Docker Operations**
```bash
# Build and start all services
docker-compose up -d --build

# View service logs
docker-compose logs -f [service_name]

# Apply database migrations
docker-compose exec webui flask db upgrade
```

## Development Environment Setup

1. Install Python 3.11+
2. Install Docker & Docker Compose
3. Install Node.js (for WebUI development)
4. Configure `.env` from `.env_example`
5. Initialize local Postgres and Redis (or use Docker)
