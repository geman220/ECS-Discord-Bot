# Testing Guide for Discord Bot WebUI

This guide covers the comprehensive testing framework implemented for the Discord Bot WebUI project.

## Overview

The testing framework provides:
- **Unit Tests**: Fast, isolated tests for individual components
- **Integration Tests**: Tests for component interactions and database operations
- **Coverage Reporting**: Code coverage analysis with minimum 70% threshold
- **Security Scanning**: Automated security vulnerability detection
- **Performance Testing**: Performance and load testing capabilities
- **CI/CD Integration**: Automated testing in GitHub Actions

## Quick Start

### 1. Install Test Dependencies

```bash
# Install all dependencies including test tools
pip install -r requirements.txt -r requirements-test.txt
```

### 2. Run Tests

```bash
# Run all tests
python run_tests.py

# Run specific test types
python run_tests.py --unit              # Unit tests only
python run_tests.py --integration       # Integration tests only
python run_tests.py --coverage          # With coverage report
python run_tests.py --lint              # Code linting
python run_tests.py --security          # Security scanning
python run_tests.py --full              # Complete test suite

# Using Make (alternative)
make test                               # All tests
make test-unit                          # Unit tests only
make test-integration                   # Integration tests only
make test-coverage                      # With coverage report
make test-docker                        # Tests in Docker
```

### 3. Using Docker

```bash
# Run tests in Docker environment
docker-compose -f docker-compose.test.yml up --build
```

## Test Structure

```
tests/
├── conftest.py                 # Shared fixtures and configuration
├── unit/                       # Unit tests (fast, isolated)
│   ├── models/                 # Model tests
│   │   └── test_user.py
│   ├── api/                    # API endpoint tests
│   │   └── test_auth.py
│   └── utils/                  # Utility function tests
│       └── test_sms_helpers.py
├── integration/                # Integration tests (slower, with DB)
│   └── test_database.py
└── fixtures/                   # Test data fixtures
```

## Test Categories

### Unit Tests
- **Location**: `tests/unit/`
- **Purpose**: Test individual functions and methods in isolation
- **Speed**: Fast (< 1 second per test)
- **Dependencies**: Minimal, uses mocks for external services

**Examples**:
- User model password hashing
- SMS helper functions
- Authentication logic
- Data validation

### Integration Tests
- **Location**: `tests/integration/`
- **Purpose**: Test component interactions and database operations
- **Speed**: Slower (database setup/teardown)
- **Dependencies**: Real database, Redis

**Examples**:
- Database transactions
- API endpoint flows
- External service integrations
- Complex business logic

## Key Test Areas

### 1. Authentication & Security
- User login/logout flows
- Password hashing and verification
- Two-factor authentication
- Session management
- Role-based access control
- OAuth2 integration (Discord)

### 2. Database Operations
- Model creation and validation
- Transaction handling
- Constraint enforcement
- Cascade operations
- Query performance
- Connection management

### 3. API Endpoints
- Request/response validation
- Error handling
- Rate limiting
- Authentication/authorization
- Data serialization

### 4. Communication Systems
- SMS sending and receiving
- Email notifications
- Discord integration
- Message formatting
- Rate limiting

### 5. Business Logic
- RSVP processing
- Match scheduling
- Substitute system
- Statistics calculation
- Notification workflows

## Coverage Requirements

- **Minimum Coverage**: 70%
- **Target Coverage**: 85%
- **Critical Components**: 90%+ (auth, database, API)

View coverage report:
```bash
# Generate HTML report
python run_tests.py --coverage
# Open htmlcov/index.html in browser
```

## Writing Tests

### Test Naming Convention
- Test files: `test_*.py`
- Test classes: `Test*`
- Test methods: `test_*`

### Example Unit Test
```python
@pytest.mark.unit
def test_user_password_hashing(db):
    """Test password hashing functionality."""
    user = User(username='test', email='test@example.com')
    user.set_password('secure_password')
    
    assert user.check_password('secure_password')
    assert not user.check_password('wrong_password')
```

### Example Integration Test
```python
@pytest.mark.integration
def test_user_login_flow(client, user):
    """Test complete user login flow."""
    response = client.post('/auth/login', data={
        'username': 'testuser',
        'password': 'password123'
    })
    
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert 'user_id' in session
```

## Fixtures

Common fixtures are defined in `tests/conftest.py`:

- `app`: Flask application instance
- `client`: Test client for HTTP requests
- `db`: Database session with automatic rollback
- `user`: Test user
- `admin_user`: Admin user
- `league`, `season`, `team`: Test data objects
- `mock_redis`, `mock_celery`: Mock external services

## Test Markers

Use pytest markers to categorize tests:

```python
@pytest.mark.unit          # Unit tests
@pytest.mark.integration   # Integration tests
@pytest.mark.slow          # Slow-running tests
@pytest.mark.api           # API tests
@pytest.mark.auth          # Authentication tests
@pytest.mark.celery        # Celery task tests
```

Run specific markers:
```bash
pytest -m unit             # Run only unit tests
pytest -m "not slow"       # Skip slow tests
pytest -m "api and auth"   # Run API authentication tests
```

## Continuous Integration

Tests run automatically on:
- Push to main/master/develop branches
- Pull requests
- Scheduled runs (daily)

GitHub Actions workflow includes:
- Unit and integration tests
- Code coverage reporting
- Security scanning
- Code linting
- Performance testing

## Performance Testing

Monitor test performance and application performance:

```bash
# Run performance tests
pytest tests/ -m slow --benchmark-sort=mean

# Database query performance
pytest tests/integration/test_database.py::test_complex_query_performance
```

## Security Testing

Automated security scanning includes:
- **Bandit**: Python security linter
- **Safety**: Dependency vulnerability scanner
- **OWASP**: Web application security testing

```bash
# Run security scans
python run_tests.py --security
```

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   - Ensure PostgreSQL is running
   - Check DATABASE_URL environment variable
   - Verify database exists and is accessible

2. **Redis Connection Errors**
   - Ensure Redis is running
   - Check REDIS_URL environment variable
   - Use different Redis database for testing

3. **Import Errors**
   - Ensure PYTHONPATH includes project root
   - Check for missing dependencies
   - Verify virtual environment is activated

4. **Test Failures**
   - Check test data setup
   - Verify mocks are correctly configured
   - Review test isolation (database rollback)

### Debug Commands

```bash
# Run specific test with verbose output
pytest tests/unit/test_user.py::test_user_creation -v -s

# Run tests with debugging
pytest --pdb tests/unit/test_user.py

# Show test coverage for specific file
pytest --cov=app.models tests/unit/models/ --cov-report=term-missing
```

## Best Practices

1. **Test Isolation**: Each test should be independent and clean up after itself
2. **Fast Tests**: Keep unit tests fast by using mocks for external dependencies
3. **Realistic Data**: Use realistic test data that matches production scenarios
4. **Error Cases**: Test both success and failure scenarios
5. **Edge Cases**: Include boundary conditions and edge cases
6. **Documentation**: Document complex test scenarios and setup requirements

## Contributing

When adding new features:

1. Write tests first (TDD approach)
2. Ensure minimum coverage requirements are met
3. Add integration tests for complex workflows
4. Update this documentation for new test patterns
5. Run full test suite before submitting PRs

## Resources

- [pytest Documentation](https://docs.pytest.org/)
- [Flask Testing Guide](https://flask.palletsprojects.com/en/2.0.x/testing/)
- [SQLAlchemy Testing](https://docs.sqlalchemy.org/en/14/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites)
- [Coverage.py Documentation](https://coverage.readthedocs.io/)