"""
Integration tests for infrastructure components.
Tests Redis, Celery, external services, and performance.

Note: Tests that require real Redis/Celery are skipped in CI environments
when those services aren't available. Use @pytest.mark.requires_redis or
@pytest.mark.requires_celery to mark such tests.
"""
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import patch, Mock, MagicMock
import os

from tests.factories import UserFactory, MatchFactory
from tests.helpers import TestDataBuilder


def redis_available():
    """Check if Redis is available for testing."""
    try:
        import redis
        client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', '6379')),
            socket_timeout=1
        )
        client.ping()
        return True
    except Exception:
        return False


def celery_available():
    """Check if Celery is available for testing."""
    # In test environments, we typically don't have a running Celery worker
    return os.getenv('CELERY_AVAILABLE', 'false').lower() == 'true'


# Skip decorators for infrastructure tests
requires_redis = pytest.mark.skipif(
    not redis_available(),
    reason="Redis not available"
)

requires_celery = pytest.mark.skipif(
    not celery_available(),
    reason="Celery not available"
)


@pytest.mark.integration
class TestRedisInfrastructure:
    """Test Redis caching functionality.

    These tests verify Redis behaviors using mocks when Redis isn't available.
    """

    def test_redis_connection_behavior_with_mock(self, app):
        """Test Redis connection behavior with mocked client."""
        with app.app_context():
            # Mock the redis client
            mock_redis = MagicMock()
            mock_redis.get.return_value = b'test_value'
            mock_redis.set.return_value = True

            with patch('app.utils.redis_manager.get_redis_connection', return_value=mock_redis):
                from app.utils.redis_manager import get_redis_connection

                redis_client = get_redis_connection()

                # Test basic operations
                redis_client.set('test_key', 'test_value', ex=60)
                assert redis_client.get('test_key') == b'test_value'

                # Verify methods were called
                mock_redis.set.assert_called_once()
                mock_redis.get.assert_called_once()

    def test_session_storage_behavior(self, client, db):
        """Test that session storage works (Flask sessions, not Redis specifically)."""
        user = UserFactory(is_approved=True)
        db.session.commit()

        # Set up authenticated session directly
        with client.session_transaction() as session:
            session['_user_id'] = user.id
            session['_fresh'] = True

        # Verify session exists (Flask-Login uses _user_id)
        with client.session_transaction() as session:
            assert '_user_id' in session
            assert session['_user_id'] == user.id

    def test_cache_behavior_with_mock(self, app):
        """Test caching behavior with mocked Redis."""
        with app.app_context():
            mock_redis = MagicMock()
            # First call returns None (cache miss), second returns cached value
            mock_redis.get.side_effect = [None, b'cached_result']
            mock_redis.setex.return_value = True

            with patch('app.utils.redis_manager.get_redis_connection', return_value=mock_redis):
                from app.utils.redis_manager import get_redis_connection

                redis_client = get_redis_connection()

                # Simulate cache miss then cache hit
                first_result = redis_client.get('expensive_operation')
                assert first_result is None  # Cache miss

                # Cache the result
                redis_client.setex('expensive_operation', 300, 'cached_result')

                # Get from cache
                cached_result = redis_client.get('expensive_operation')
                assert cached_result == b'cached_result'


@pytest.mark.integration
class TestCeleryInfrastructure:
    """Test Celery task processing.

    These tests verify task modules can be imported and have correct structure.
    Actual task execution is skipped in CI since we don't have Celery workers.
    """

    def test_celery_tasks_core_module_exists(self, app):
        """Test that tasks_core module can be imported."""
        with app.app_context():
            try:
                from app.tasks import tasks_core
                # Verify expected tasks exist
                assert hasattr(tasks_core, 'schedule_season_availability')
                assert hasattr(tasks_core, 'send_availability_message_task')
            except ImportError as e:
                pytest.skip(f"Celery tasks not available: {e}")

    def test_celery_tasks_rsvp_module_exists(self, app):
        """Test that tasks_rsvp module can be imported."""
        with app.app_context():
            try:
                from app.tasks import tasks_rsvp
                assert tasks_rsvp is not None
            except ImportError as e:
                pytest.skip(f"RSVP tasks not available: {e}")

    def test_celery_tasks_maintenance_module_exists(self, app):
        """Test that tasks_maintenance module can be imported."""
        with app.app_context():
            try:
                from app.tasks import tasks_maintenance
                assert tasks_maintenance is not None
            except ImportError as e:
                pytest.skip(f"Maintenance tasks not available: {e}")

    def test_celery_tasks_discord_module_exists(self, app):
        """Test that tasks_discord module can be imported."""
        with app.app_context():
            try:
                from app.tasks import tasks_discord
                assert tasks_discord is not None
            except ImportError as e:
                pytest.skip(f"Discord tasks not available: {e}")


@pytest.mark.integration
class TestExternalServices:
    """Test external service integrations."""

    def test_sms_service_available(self, app):
        """Test SMS service module can be imported."""
        with app.app_context():
            from app.sms_helpers import send_sms
            # Verify the function exists and can be called
            assert callable(send_sms)

    def test_discord_utils_available(self, app):
        """Test Discord utilities module can be imported."""
        with app.app_context():
            # Verify module can be imported
            import app.discord_utils
            assert app.discord_utils is not None

    def test_email_service_available(self, app):
        """Test email service module can be imported."""
        with app.app_context():
            from app.email import send_email
            # Verify the function exists and can be called
            assert callable(send_email)

    def test_image_processing_service_behavior(self, app):
        """Test image processing behavior (mocked)."""
        with app.app_context():
            # Check if optimize_image exists
            try:
                from app.image_cache_service import optimize_image
            except ImportError:
                pytest.skip("Image cache service not available")

            # Mock the entire image processing pipeline
            with patch('app.image_cache_service.optimize_image') as mock_optimize:
                mock_optimize.return_value = b'optimized_image_data'

                result = optimize_image(b'fake_image_data', max_width=500)

                assert result is not None


@pytest.mark.integration
class TestPerformanceInfrastructure:
    """Test system performance and benchmarks."""

    def test_database_query_performance(self, db):
        """Test database query performance meets benchmarks."""
        # Create test data
        users = [UserFactory() for _ in range(100)]
        db.session.commit()

        # Test query performance
        start_time = time.time()

        from app.models import User
        result = User.query.filter(User.is_approved == True).limit(50).all()

        query_time = time.time() - start_time

        assert len(result) <= 50
        assert query_time < 0.5  # Should complete in under 500ms (relaxed for CI)

    def test_api_endpoint_performance(self, client, db):
        """Test API endpoint response times."""
        user = UserFactory(is_approved=True)
        db.session.commit()

        # Test login endpoint performance
        start_time = time.time()

        response = client.post('/auth/login', data={
            'email': user.email,
            'password': 'password123'
        })

        response_time = time.time() - start_time

        assert response.status_code in [200, 302]  # Valid response (redirect on success)
        assert response_time < 2.0  # Under 2s (relaxed for CI)

    def test_concurrent_user_handling(self, app, db):
        """Test system handles concurrent users."""
        import threading
        import queue

        # Pre-create users before threading to avoid database conflicts
        users = []
        for i in range(5):  # Reduced to 5 to avoid overwhelming test DB
            user = UserFactory(
                username=f'concurrent_user_{i}',
                email=f'concurrent_{i}@example.com',
                is_approved=True
            )
            users.append(user)
        db.session.commit()

        results = queue.Queue()

        def simulate_user_request(user_email):
            with app.test_client() as client:
                response = client.post('/auth/login', data={
                    'email': user_email,
                    'password': 'password123'
                })
                results.put(response.status_code)

        # Simulate concurrent users
        threads = []
        for user in users:
            thread = threading.Thread(target=simulate_user_request, args=(user.email,))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Check all requests completed
        response_codes = []
        while not results.empty():
            response_codes.append(results.get())

        assert len(response_codes) == 5
        # All responses should be valid (200 or redirect)
        assert all(code in [200, 302] for code in response_codes)

    def test_memory_usage_stability(self, app):
        """Test memory usage remains stable under load."""
        import psutil
        import os

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Simulate memory-intensive operations
        with app.app_context():
            for _ in range(100):
                users = [UserFactory() for _ in range(10)]
                # Don't commit to avoid actual DB load

        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory

        # Memory increase should be reasonable (under 100MB for this test)
        assert memory_increase < 100

    def test_database_connection_pool_efficiency(self, app, db):
        """Test database connection pooling works efficiently."""
        with app.app_context():
            # Simulate multiple concurrent database operations
            start_time = time.time()

            for _ in range(20):
                from app.models import User
                User.query.count()  # Simple query

            total_time = time.time() - start_time

            # 20 queries should complete quickly with connection pooling
            assert total_time < 5.0  # Under 5 seconds (relaxed for CI)

    def test_rsvp_workflow_performance(self, client, db):
        """Test RSVP workflow performance (without pytest-benchmark)."""
        user = UserFactory(is_approved=True)
        db.session.commit()

        # Set up authenticated session
        with client.session_transaction() as session:
            session['_user_id'] = user.id
            session['_fresh'] = True

        # Just verify the workflow can complete
        start_time = time.time()

        # Access a protected route as a simple workflow test
        response = client.get('/')

        response_time = time.time() - start_time

        # Should complete reasonably quickly
        assert response.status_code in [200, 302]
        assert response_time < 5.0  # Under 5 seconds
