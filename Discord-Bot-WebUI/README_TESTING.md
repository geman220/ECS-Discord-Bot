# Testing Guide

## Quick Start

```bash
# Install test dependencies
pip install -r requirements.txt -r requirements-test.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test types
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only
pytest -m smoke         # Critical path tests only
```

## Test Structure

```
tests/
├── unit/           # Fast, isolated tests
├── integration/    # System interaction tests  
├── e2e/           # End-to-end user journeys
├── contracts/     # API stability tests
├── performance/   # Benchmarks and load tests
├── factories.py   # Test data generation
├── helpers.py     # Test utilities
└── conftest.py    # pytest configuration
```

## GitHub Actions

Tests run automatically on:
- Every push to any branch
- Every pull request
- Minimum 70% coverage required
- All tests must pass to merge

## Adding New Tests

1. **Use factories** for test data:
   ```python
   user = UserFactory()
   match = MatchFactory(home_team=user.player.team)
   ```

2. **Test behavior, not implementation**:
   ```python
   def test_user_can_view_their_matches():
       # Given: User has upcoming matches
       # When: User visits matches page  
       # Then: User sees their matches listed
   ```

3. **Use appropriate test type**:
   - Unit: Single function/method
   - Integration: Multiple components
   - E2E: Complete user workflow

## Coverage Reports

After running tests with coverage:
```bash
open htmlcov/index.html  # View detailed coverage report
```

See `TESTING_STRATEGY.md` for complete implementation details.