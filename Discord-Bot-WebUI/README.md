# ECS Discord Bot WebUI

This directory contains the Flask-based web application for the ECS Discord Bot & League Management System. It provides an administrative interface for league management, team coordination, and player tracking.

## Architecture

The WebUI is built with:
- **Flask**: Python web framework
- **SQLAlchemy**: ORM for PostgreSQL database
- **Celery**: Background task processing
- **Socket.IO**: Real-time communication for drafts and match reporting
- **Vite & Tailwind CSS**: Modern frontend toolchain and styling
- **Vitest**: Frontend unit testing

## Directory Structure

- `app/`: Core application logic
  - `models/`: Database models
  - `routes/`: Flask blueprints and route handlers
  - `services/`: Business logic and external integrations
  - `static/`: Frontend assets (JS, CSS, images)
  - `templates/`: Jinja2 templates
- `scripts/`: Utility and maintenance scripts
- `tests/`: Comprehensive test suite
  - `unit/`: Unit tests for Python components
  - `integration/`: Integration tests
  - `e2e/`: End-to-end tests
  - `performance/`: Performance benchmarks

## Setup & Development

### Python Setup

1. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python wsgi.py
   ```

### Frontend Setup

1. Install Node.js dependencies:
   ```bash
   npm install
   ```

2. Run development server (Vite):
   ```bash
   npm run dev
   ```

3. Build production assets:
   ```bash
   npm run build
   ```

## Testing

### Python Tests

The project uses a comprehensive test runner `run_tests.py`.

- **Run all tests**:
  ```bash
  python run_tests.py --all
  ```

- **Run unit tests only**:
  ```bash
  python run_tests.py --unit
  ```

- **Run with coverage reporting**:
  ```bash
  python run_tests.py --all --coverage
  ```

- **Run in Docker**:
  ```bash
  python run_tests.py --docker
  ```

### Frontend Tests (JS/TS)

- **Run Vitest**:
  ```bash
  npm test
  ```

- **Run Vitest with coverage**:
  ```bash
  npm run test:coverage
  ```

### Linting & Security

- **Run Python linting**:
  ```bash
  python run_tests.py --lint
  ```

- **Run JS linting**:
  ```bash
  npm run lint
  ```

- **Run security scans**:
  ```bash
  python run_tests.py --security
  ```

## Contributing

When adding new features or fixing bugs:
1. Ensure your code follows PEP 8 guidelines.
2. Add unit tests for your changes in `tests/unit/`.
3. Run the full test suite to ensure no regressions.
4. Update documentation if necessary.
