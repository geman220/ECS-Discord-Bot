"""
Integration tests for infrastructure components.
Tests Redis, Celery, external services, and performance.
"""
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import patch, Mock

from tests.factories import UserFactory, MatchFactory
from tests.helpers import TestDataBuilder


@pytest.mark.integration
class TestRedisInfrastructure:
    """Test Redis caching functionality."""
    
    def test_redis_connection_and_basic_operations(self, app):
        """Test Redis connection and basic operations."""
        with app.app_context():
            from app.utils.redis_manager import get_redis_connection
            
            redis_client = get_redis_connection()
            
            # Test basic operations
            redis_client.set('test_key', 'test_value', ex=60)
            assert redis_client.get('test_key').decode() == 'test_value'
            
            # Test expiration
            redis_client.set('expiring_key', 'value', ex=1)
            time.sleep(1.1)
            assert redis_client.get('expiring_key') is None
    
    def test_session_storage_in_redis(self, client, db):
        """Test user session storage in Redis."""
        user = UserFactory()
        
        # Login to create session
        response = client.post('/auth/login', data={
            'username': user.username,
            'password': 'password123'
        })
        
        # Verify session exists in Redis
        with client.session_transaction() as session:
            assert 'user_id' in session
            assert session['user_id'] == user.id
    
    def test_cache_performance(self, app):
        """Test caching improves performance."""
        with app.app_context():
            from app.utils.redis_manager import get_redis_connection
            
            redis_client = get_redis_connection()
            
            # Clear any existing cache
            redis_client.flushdb()
            
            # Simulate expensive operation (first call)
            start_time = time.time()
            
            # Mock an expensive database query
            expensive_data = {'result': 'expensive_computation', 'timestamp': time.time()}
            redis_client.setex('expensive_operation', 300, str(expensive_data))
            
            first_call_time = time.time() - start_time
            
            # Second call (from cache)
            start_time = time.time()
            cached_result = redis_client.get('expensive_operation')
            second_call_time = time.time() - start_time
            
            assert cached_result is not None
            assert second_call_time < first_call_time  # Cache is faster


@pytest.mark.integration
class TestCeleryInfrastructure:
    """Test Celery task processing."""
    
    def test_celery_task_execution(self, app, db):
        """Test basic Celery task execution."""
        with app.app_context():
            from app.tasks.tasks_core import test_task
            
            # Execute task synchronously for testing
            result = test_task.apply(args=['test_message'])
            
            assert result.successful()
            assert 'test_message' in result.result
    
    def test_rsvp_reminder_task(self, app, db):
        """Test RSVP reminder task processing."""
        # Setup: User with upcoming match
        user, matches = TestDataBuilder.create_user_with_upcoming_matches(1)
        match = matches[0]
        
        with app.app_context():
            with patch('app.sms_helpers.send_sms') as mock_sms:
                mock_sms.return_value = True
                
                from app.tasks.tasks_rsvp import send_rsvp_reminders_for_match
                
                # Execute task
                result = send_rsvp_reminders_for_match.apply(args=[match.id])
                
                assert result.successful()
                mock_sms.assert_called()
    
    def test_celery_error_handling(self, app, db):
        """Test Celery task error handling and retries."""
        with app.app_context():
            from app.tasks.tasks_core import failing_task
            
            # Execute failing task
            with patch('app.tasks.tasks_core.some_external_service') as mock_service:
                mock_service.side_effect = Exception('Service unavailable')
                
                result = failing_task.apply(args=['test'])
                
                # Task should handle error gracefully
                assert result.state in ['FAILURE', 'RETRY']
    
    def test_scheduled_task_execution(self, app, db):
        """Test scheduled tasks execute correctly."""
        with app.app_context():
            from app.tasks.tasks_maintenance import cleanup_old_sessions
            
            # Create old session data
            from app.utils.redis_manager import get_redis_connection
            redis_client = get_redis_connection()
            
            # Set expired session
            old_session_key = 'session:expired:123'
            redis_client.set(old_session_key, 'old_data')
            
            # Run cleanup task
            result = cleanup_old_sessions.apply()
            
            assert result.successful()


@pytest.mark.integration
class TestExternalServices:
    """Test external service integrations."""
    
    def test_twilio_integration(self, app):
        """Test Twilio SMS service integration."""
        with app.app_context():
            from app.sms_helpers import send_sms
            
            with patch('app.sms_helpers.twilio_client') as mock_twilio:
                mock_twilio.messages.create.return_value = Mock(sid='TEST123')
                
                result = send_sms('+15551234567', 'Test message')
                
                assert result is True
                mock_twilio.messages.create.assert_called_once()
    
    def test_discord_api_integration(self, app):
        """Test Discord API integration."""
        with app.app_context():
            from app.discord_utils import send_discord_notification
            
            with patch('app.discord_utils.discord_client') as mock_discord:
                mock_discord.send_message.return_value = {'id': 'msg_123'}
                
                result = send_discord_notification(
                    channel_id='123456',
                    message='Test notification'
                )
                
                assert result is not None
                mock_discord.send_message.assert_called_once()
    
    def test_email_service_integration(self, app):
        """Test email service integration."""
        with app.app_context():
            from app.email import send_email
            
            with patch('app.email.mail.send') as mock_mail:
                mock_mail.return_value = True
                
                result = send_email(
                    to='test@example.com',
                    subject='Test Email',
                    body='This is a test email'
                )
                
                assert result is True
                mock_mail.assert_called_once()
    
    def test_image_processing_service(self, app):
        """Test image processing and optimization."""
        with app.app_context():
            from app.image_cache_service import optimize_image
            
            # Mock image data
            mock_image_data = b'fake_image_data'
            
            with patch('PIL.Image.open') as mock_pil:
                mock_image = Mock()
                mock_image.size = (1000, 800)
                mock_pil.return_value = mock_image
                
                result = optimize_image(mock_image_data, max_width=500)
                
                assert result is not None


@pytest.mark.integration
@pytest.mark.performance
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
        result = User.query.filter(User.approved == True).limit(50).all()
        
        query_time = time.time() - start_time
        
        assert len(result) <= 50
        assert query_time < 0.1  # Should complete in under 100ms
    
    def test_api_endpoint_performance(self, client, db):
        """Test API endpoint response times."""
        user = UserFactory()
        
        # Test login endpoint performance
        start_time = time.time()
        
        response = client.post('/api/auth/login', json={
            'username': user.username,
            'password': 'password123'
        })
        
        response_time = time.time() - start_time
        
        assert response.status_code in [200, 401]  # Valid response
        assert response_time < 0.5  # Under 500ms
    
    def test_concurrent_user_handling(self, app, db):
        """Test system handles concurrent users."""
        import threading
        import queue
        
        results = queue.Queue()
        
        def simulate_user_request():
            with app.test_client() as client:
                user = UserFactory()
                
                response = client.post('/auth/login', data={
                    'username': user.username,
                    'password': 'password123'
                })
                
                results.put(response.status_code)
        
        # Simulate 10 concurrent users
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=simulate_user_request)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Check all requests completed
        response_codes = []
        while not results.empty():
            response_codes.append(results.get())
        
        assert len(response_codes) == 10
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
        
        # Memory increase should be reasonable (under 50MB for this test)
        assert memory_increase < 50
    
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
            assert total_time < 1.0  # Under 1 second
    
    @pytest.mark.benchmark
    def test_rsvp_workflow_performance(self, benchmark, client, db):
        """Benchmark RSVP workflow performance."""
        user = UserFactory()
        match = MatchFactory()
        
        def rsvp_workflow():
            with client.session_transaction() as session:
                session['user_id'] = user.id
            
            return client.post('/api/availability', json={
                'match_id': match.id,
                'available': True
            })
        
        # Benchmark the workflow
        result = benchmark(rsvp_workflow)
        assert result.status_code == 200