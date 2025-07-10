"""
Performance benchmark tests.
Tests system performance under various loads.
"""
import pytest
import time
from datetime import datetime, timedelta

from tests.factories import UserFactory, MatchFactory, TeamFactory
from tests.helpers import TestDataBuilder


@pytest.mark.performance
@pytest.mark.slow
class TestPerformanceBenchmarks:
    """Performance benchmark tests for critical operations."""
    
    def test_user_authentication_benchmark(self, benchmark, client, db):
        """Benchmark user authentication performance."""
        user = UserFactory(username='benchmark_user')
        
        def login_operation():
            return client.post('/auth/login', data={
                'username': 'benchmark_user',
                'password': 'password123'
            })
        
        result = benchmark(login_operation)
        assert result.status_code in [200, 302]
        
        # Should complete in under 100ms
        assert benchmark.stats['mean'] < 0.1
    
    def test_match_list_query_benchmark(self, benchmark, client, db):
        """Benchmark match listing performance with large dataset."""
        # Create large dataset
        teams = [TeamFactory() for _ in range(20)]
        matches = []
        
        for i in range(500):  # 500 matches
            match = MatchFactory(
                home_team=teams[i % 10],
                away_team=teams[(i + 1) % 10],
                scheduled_date=datetime.utcnow().date() + timedelta(days=i % 30)
            )
            matches.append(match)
        
        user = UserFactory()
        
        def query_matches():
            with client.session_transaction() as session:
                session['user_id'] = user.id
            
            return client.get('/api/matches?page=1&per_page=20')
        
        result = benchmark(query_matches)
        assert result.status_code == 200
        
        # Should complete in under 200ms even with 500 matches
        assert benchmark.stats['mean'] < 0.2
    
    def test_rsvp_submission_benchmark(self, benchmark, client, db):
        """Benchmark RSVP submission performance."""
        user = UserFactory()
        match = MatchFactory()
        
        def submit_rsvp():
            with client.session_transaction() as session:
                session['user_id'] = user.id
            
            return client.post('/api/availability', json={
                'match_id': match.id,
                'available': True,
                'notes': 'Looking forward to the match!'
            })
        
        result = benchmark(submit_rsvp)
        assert result.status_code == 200
        
        # Should complete in under 50ms
        assert benchmark.stats['mean'] < 0.05
    
    def test_team_statistics_calculation_benchmark(self, benchmark, db):
        """Benchmark team statistics calculation performance."""
        # Create team with extensive match history
        team = TestDataBuilder.create_team_with_match_history(num_matches=100)
        
        def calculate_stats():
            from app.services.statistics_service import calculate_team_stats
            return calculate_team_stats(team.id)
        
        result = benchmark(calculate_stats)
        assert result is not None
        
        # Should complete in under 500ms even with 100 matches
        assert benchmark.stats['mean'] < 0.5
    
    def test_bulk_notification_benchmark(self, benchmark, db):
        """Benchmark bulk notification performance."""
        # Create many users
        users = [UserFactory(phone_number=f'+155500{i:04d}') for i in range(100)]
        
        def send_bulk_notifications():
            from app.services.notification_service import send_bulk_sms
            return send_bulk_sms(
                user_ids=[u.id for u in users],
                message='Test bulk message'
            )
        
        # Mock SMS sending to avoid actual API calls
        from unittest.mock import patch
        with patch('app.sms_helpers.send_sms', return_value=True):
            result = benchmark(send_bulk_notifications)
            
        assert result['sent_count'] == 100
        
        # Should complete in under 2 seconds for 100 users
        assert benchmark.stats['mean'] < 2.0
    
    def test_database_migration_benchmark(self, benchmark, app):
        """Benchmark database migration performance."""
        with app.app_context():
            def run_migration():
                from flask_migrate import upgrade
                upgrade()
                return True
            
            # This would test migration performance
            # In practice, you'd test with a copy of production data
            result = benchmark.pedantic(run_migration, rounds=1, iterations=1)
            assert result is True
    
    def test_image_processing_benchmark(self, benchmark):
        """Benchmark image processing performance."""
        # Mock image data
        mock_image_data = b'fake_image_data' * 1000  # Simulate larger image
        
        def process_image():
            from app.image_cache_service import optimize_image
            from unittest.mock import Mock, patch
            
            with patch('PIL.Image.open') as mock_pil:
                mock_image = Mock()
                mock_image.size = (2000, 1500)  # Large image
                mock_image.resize.return_value = mock_image
                mock_image.save = Mock()
                mock_pil.return_value = mock_image
                
                return optimize_image(mock_image_data, max_width=800)
        
        result = benchmark(process_image)
        assert result is not None
        
        # Should complete in under 100ms
        assert benchmark.stats['mean'] < 0.1


@pytest.mark.performance
@pytest.mark.slow  
class TestLoadTesting:
    """Load testing for system under stress."""
    
    def test_concurrent_login_load(self, app, db):
        """Test system under concurrent login load."""
        import threading
        import queue
        
        results = queue.Queue()
        errors = queue.Queue()
        
        def simulate_login():
            try:
                with app.test_client() as client:
                    user = UserFactory()
                    
                    start_time = time.time()
                    response = client.post('/auth/login', data={
                        'username': user.username,
                        'password': 'password123'
                    })
                    end_time = time.time()
                    
                    results.put({
                        'status_code': response.status_code,
                        'response_time': end_time - start_time
                    })
            except Exception as e:
                errors.put(str(e))
        
        # Simulate 50 concurrent logins
        threads = []
        for _ in range(50):
            thread = threading.Thread(target=simulate_login)
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Analyze results
        response_times = []
        status_codes = []
        
        while not results.empty():
            result = results.get()
            response_times.append(result['response_time'])
            status_codes.append(result['status_code'])
        
        # Verify no errors
        assert errors.empty(), f"Errors occurred: {list(errors.queue)}"
        
        # Verify acceptable performance
        assert len(response_times) == 50
        assert max(response_times) < 2.0  # No request over 2 seconds
        assert sum(response_times) / len(response_times) < 0.5  # Average under 500ms
    
    def test_database_connection_under_load(self, app, db):
        """Test database connection pool under load."""
        import threading
        import queue
        
        results = queue.Queue()
        
        def database_operation():
            try:
                with app.app_context():
                    from app.models import User
                    
                    start_time = time.time()
                    count = User.query.count()
                    end_time = time.time()
                    
                    results.put({
                        'count': count,
                        'time': end_time - start_time
                    })
            except Exception as e:
                results.put({'error': str(e)})
        
        # Run 100 concurrent database operations
        threads = []
        for _ in range(100):
            thread = threading.Thread(target=database_operation)
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Check results
        query_times = []
        errors = []
        
        while not results.empty():
            result = results.get()
            if 'error' in result:
                errors.append(result['error'])
            else:
                query_times.append(result['time'])
        
        # Should handle all queries without errors
        assert len(errors) == 0, f"Database errors: {errors}"
        assert len(query_times) == 100
        
        # All queries should complete reasonably fast
        assert max(query_times) < 1.0
    
    def test_memory_usage_under_load(self, app):
        """Test memory usage stays stable under load."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Simulate heavy load
        with app.app_context():
            for batch in range(10):  # 10 batches
                users = []
                for _ in range(100):  # 100 users per batch
                    user = UserFactory()
                    users.append(user)
                
                # Simulate processing
                for user in users:
                    # Simulate some operations
                    _ = user.username.upper()
                
                # Clear batch to simulate cleanup
                del users
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be reasonable (under 100MB)
        assert memory_increase < 100, f"Memory increased by {memory_increase}MB"