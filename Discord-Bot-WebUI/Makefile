# Makefile for Discord Bot WebUI

.PHONY: help test test-unit test-integration test-docker test-coverage install-test clean

help:
	@echo "Available commands:"
	@echo "  make test              - Run all tests"
	@echo "  make test-unit         - Run unit tests only"
	@echo "  make test-integration  - Run integration tests"
	@echo "  make test-docker       - Run tests in Docker"
	@echo "  make test-coverage     - Run tests with coverage report"
	@echo "  make install-test      - Install test dependencies"
	@echo "  make clean             - Clean test artifacts"

# Install test dependencies
install-test:
	pip install -r requirements.txt -r requirements-test.txt

# Run all tests
test:
	pytest -v

# Run unit tests only
test-unit:
	pytest -v -m unit tests/unit/

# Run integration tests only
test-integration:
	pytest -v -m integration tests/integration/

# Run tests in Docker
test-docker:
	docker-compose -f docker-compose.test.yml up --build --abort-on-container-exit
	docker-compose -f docker-compose.test.yml down

# Run tests with coverage
test-coverage:
	pytest -v --cov=app --cov-report=html --cov-report=term-missing
	@echo "Coverage report generated in htmlcov/index.html"

# Run specific test file or pattern
test-specific:
	@read -p "Enter test pattern (e.g., test_auth): " pattern; \
	pytest -v -k "$$pattern"

# Clean test artifacts
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete