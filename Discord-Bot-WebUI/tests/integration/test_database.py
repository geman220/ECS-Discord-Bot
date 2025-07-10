"""
Integration tests for database operations.
"""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import text
from app.models import User, Match, Team, Player, Availability
from app.core import db


@pytest.mark.integration
class TestDatabaseIntegration:
    """Test database operations and transactions."""
    
    def test_database_connection(self, app):
        """Test database connection is working."""
        with app.app_context():
            result = db.session.execute(text('SELECT 1')).scalar()
            assert result == 1
    
    def test_transaction_rollback(self, db):
        """Test transaction rollback on error."""
        initial_count = User.query.count()
        
        try:
            with db.session.begin():
                # Create a user
                user = User(username='rollback_test', email='rollback@test.com')
                db.session.add(user)
                db.session.flush()  # Flush to get ID
                
                # Force an error (duplicate username)
                duplicate = User(username='rollback_test', email='another@test.com')
                db.session.add(duplicate)
                db.session.commit()  # This should fail
        except Exception:
            pass  # Expected to fail
        
        # Verify rollback occurred
        assert User.query.count() == initial_count
    
    def test_concurrent_availability_updates(self, db, user, match):
        """Test concurrent availability updates."""
        # Create initial availability
        availability = Availability(
            user_id=user.id,
            match_id=match.id,
            available=True,
            response_date=datetime.utcnow()
        )
        db.session.add(availability)
        db.session.commit()
        
        # Simulate concurrent updates
        avail1 = Availability.query.filter_by(user_id=user.id, match_id=match.id).first()
        avail2 = Availability.query.filter_by(user_id=user.id, match_id=match.id).first()
        
        # Update from different "sessions"
        avail1.available = False
        avail1.notes = 'Updated by session 1'
        
        avail2.available = True
        avail2.notes = 'Updated by session 2'
        
        # Commit first update
        db.session.merge(avail1)
        db.session.commit()
        
        # Commit second update (should handle conflict)
        db.session.merge(avail2)
        db.session.commit()
        
        # Verify final state
        final_avail = Availability.query.filter_by(user_id=user.id, match_id=match.id).first()
        assert final_avail.notes == 'Updated by session 2'
    
    def test_complex_query_performance(self, db, season):
        """Test complex query performance."""
        # Create test data
        teams = []
        for i in range(10):
            team = Team(name=f'Team {i}', season_id=season.id)
            db.session.add(team)
            teams.append(team)
        
        matches = []
        for i in range(50):
            match = Match(
                season_id=season.id,
                home_team_id=teams[i % 5].id,
                away_team_id=teams[(i + 1) % 5].id,
                scheduled_date=datetime.utcnow() + timedelta(days=i),
                scheduled_time='19:00',
                field_name='Field 1'
            )
            db.session.add(match)
            matches.append(match)
        
        db.session.commit()
        
        # Test complex query
        query = db.session.query(Match).join(Team, Match.home_team_id == Team.id).filter(
            Match.season_id == season.id,
            Match.scheduled_date >= datetime.utcnow()
        ).order_by(Match.scheduled_date)
        
        # Execute query and measure
        import time
        start_time = time.time()
        results = query.all()
        end_time = time.time()
        
        assert len(results) > 0
        assert end_time - start_time < 1.0  # Should complete in under 1 second
    
    def test_foreign_key_constraints(self, db, user, team):
        """Test foreign key constraints are enforced."""
        # Create player
        player = Player(user_id=user.id, team_id=team.id)
        db.session.add(player)
        db.session.commit()
        
        # Try to delete referenced user (should fail)
        with pytest.raises(Exception):
            db.session.delete(user)
            db.session.commit()
        
        db.session.rollback()
        
        # Delete player first, then user (should work)
        db.session.delete(player)
        db.session.delete(user)
        db.session.commit()
        
        assert Player.query.filter_by(user_id=user.id).first() is None
        assert User.query.filter_by(id=user.id).first() is None
    
    def test_cascade_deletes(self, db, league, season, team):
        """Test cascade deletes work correctly."""
        # Create nested structure
        match = Match(
            season_id=season.id,
            home_team_id=team.id,
            away_team_id=team.id,
            scheduled_date=datetime.utcnow(),
            scheduled_time='19:00',
            field_name='Test Field'
        )
        db.session.add(match)
        db.session.commit()
        
        initial_match_count = Match.query.count()
        
        # Delete season (should cascade to matches)
        db.session.delete(season)
        db.session.commit()
        
        # Verify cascaded deletion
        assert Match.query.count() < initial_match_count
        assert Match.query.filter_by(season_id=season.id).count() == 0
    
    def test_index_usage(self, db, app):
        """Test database indexes are being used."""
        with app.app_context():
            # Test common queries use indexes
            queries = [
                "SELECT * FROM users WHERE username = 'test'",
                "SELECT * FROM matches WHERE season_id = 1",
                "SELECT * FROM availability WHERE user_id = 1 AND match_id = 1"
            ]
            
            for query in queries:
                # Execute EXPLAIN to check index usage
                result = db.session.execute(text(f"EXPLAIN {query}")).fetchall()
                # This is database-specific, but generally we want to avoid full table scans
                explain_text = str(result).lower()
                assert 'scan' not in explain_text or 'index' in explain_text
    
    def test_session_cleanup(self, db):
        """Test database sessions are properly cleaned up."""
        initial_connections = db.engine.pool.size()
        
        # Create multiple sessions
        for i in range(10):
            user = User(username=f'session_test_{i}', email=f'session{i}@test.com')
            db.session.add(user)
            db.session.commit()
        
        # Force cleanup
        db.session.remove()
        
        # Verify connection pool didn't grow excessively
        final_connections = db.engine.pool.size()
        assert final_connections <= initial_connections + 5  # Some growth is expected