"""
Integration tests for match management workflows.
Tests complete match lifecycle from creation to completion.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from tests.factories import (
    UserFactory, TeamFactory, MatchFactory, 
    PlayerFactory, SeasonFactory
)
from tests.helpers import (
    TestDataBuilder, AuthTestHelper, 
    SMSTestHelper, assert_sms_sent
)


@pytest.mark.integration
class TestMatchManagementWorkflow:
    """Test complete match management journeys."""
    
    def test_admin_creates_match_and_notifies_teams(self, db, client):
        """Test match creation and notification flow."""
        # Setup: Admin user and two teams
        admin = UserFactory()
        admin.roles.append('Admin')
        
        season = SeasonFactory()
        home_team = TeamFactory(season=season)
        away_team = TeamFactory(season=season)
        
        # Create players for both teams
        home_players = [PlayerFactory(team=home_team) for _ in range(5)]
        away_players = [PlayerFactory(team=away_team) for _ in range(5)]
        
        sms_helper = SMSTestHelper()
        
        with AuthTestHelper.authenticated_request(client, admin):
            with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
                # Admin creates match
                response = client.post('/admin/matches/create', data={
                    'season_id': season.id,
                    'home_team_id': home_team.id,
                    'away_team_id': away_team.id,
                    'scheduled_date': (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d'),
                    'scheduled_time': '19:00',
                    'field_name': 'Main Field',
                    'send_notifications': 'true'
                }, follow_redirects=True)
                
                assert response.status_code == 200
                assert b'Match created successfully' in response.data
                
                # Verify: Match exists
                from app.models import Match
                match = Match.query.filter_by(
                    home_team_id=home_team.id,
                    away_team_id=away_team.id
                ).first()
                assert match is not None
                
                # Verify: Notifications sent to all players
                all_players = home_players + away_players
                for player in all_players:
                    messages = sms_helper.get_messages_for_user(player.user)
                    assert len(messages) >= 1
                    assert 'New match scheduled' in messages[0]['message']
    
    def test_match_day_workflow(self, db, client):
        """Test complete match day workflow."""
        # Setup: Match happening today
        match = TestDataBuilder.create_match_with_teams(
            home_team_size=11,
            away_team_size=11,
            scheduled_date=datetime.utcnow().date(),
            scheduled_time='14:00'
        )
        
        # Some players have RSVP'd
        home_players = match.home_team.players[:8]
        for player in home_players:
            MatchTestHelper.create_rsvp(player.user, match, available=True)
        
        # Step 1: Pre-match reminder (2 hours before)
        with patch('datetime.datetime') as mock_dt:
            match_time = datetime.combine(match.scheduled_date, 
                                        datetime.strptime('14:00', '%H:%M').time())
            mock_dt.utcnow.return_value = match_time - timedelta(hours=2)
            
            from app.tasks.tasks_match_updates import send_match_day_reminders
            send_match_day_reminders()
            
            # Players should receive reminder
            # (Test implementation details omitted for brevity)
        
        # Step 2: Match starts - enable live reporting
        captain = match.home_team.captain
        with AuthTestHelper.authenticated_request(client, captain):
            response = client.post(f'/matches/{match.id}/start-reporting')
            assert response.status_code == 200
            
            # Submit live updates
            response = client.post(f'/api/matches/{match.id}/events', json={
                'event_type': 'goal',
                'team_id': match.home_team.id,
                'player_id': home_players[0].id,
                'minute': 15,
                'description': 'Great strike from outside the box!'
            })
            assert response.status_code == 200
        
        # Step 3: Match completion
        with AuthTestHelper.authenticated_request(client, captain):
            response = client.post(f'/matches/{match.id}/complete', json={
                'home_score': 2,
                'away_score': 1,
                'notes': 'Great game, well played by both teams'
            })
            assert response.status_code == 200
            
            # Verify: Match marked as completed
            match = Match.query.get(match.id)
            assert match.status == 'completed'
            assert match.home_score == 2
            assert match.away_score == 1
    
    def test_match_cancellation_workflow(self, db):
        """Test match cancellation and notification."""
        # Setup: Upcoming match with RSVPs
        match = TestDataBuilder.create_match_with_teams()
        
        # Some players have RSVP'd
        responding_players = []
        for player in match.home_team.players[:5]:
            MatchTestHelper.create_rsvp(player.user, match, available=True)
            responding_players.append(player)
        
        sms_helper = SMSTestHelper()
        
        with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
            # Cancel match
            from app.services.match_service import cancel_match
            result = cancel_match(match.id, reason="Field flooded", notify_players=True)
            
            assert result.success
            
            # Verify: Match status updated
            assert match.status == 'cancelled'
            assert match.cancellation_reason == "Field flooded"
            
            # Verify: Players notified
            for player in responding_players:
                messages = sms_helper.get_messages_for_user(player.user)
                assert any('cancelled' in msg['message'].lower() for msg in messages)
                assert any('Field flooded' in msg['message'] for msg in messages)
    
    def test_match_verification_workflow(self, db, client):
        """Test post-match verification process."""
        # Setup: Completed match needing verification
        match = MatchFactory(status='completed', home_score=3, away_score=2)
        home_captain = match.home_team.captain
        away_captain = match.away_team.captain
        
        # Step 1: Home captain submits verification
        with AuthTestHelper.authenticated_request(client, home_captain):
            response = client.post(f'/matches/{match.id}/verify', json={
                'home_score': 3,
                'away_score': 2,
                'match_events': [
                    {'type': 'goal', 'team': 'home', 'minute': 10},
                    {'type': 'goal', 'team': 'home', 'minute': 25},
                    {'type': 'goal', 'team': 'away', 'minute': 30},
                    {'type': 'goal', 'team': 'home', 'minute': 60},
                    {'type': 'goal', 'team': 'away', 'minute': 75}
                ]
            })
            assert response.status_code == 200
        
        # Step 2: Away captain disputes
        with AuthTestHelper.authenticated_request(client, away_captain):
            response = client.post(f'/matches/{match.id}/dispute', json={
                'reason': 'Home team third goal was offside',
                'suggested_home_score': 2,
                'suggested_away_score': 2
            })
            assert response.status_code == 200
        
        # Verify: Match marked as disputed
        match = Match.query.get(match.id)
        assert match.verification_status == 'disputed'
        
        # Step 3: Admin resolves dispute
        admin = UserFactory()
        admin.roles.append('Admin')
        
        with AuthTestHelper.authenticated_request(client, admin):
            response = client.post(f'/matches/{match.id}/resolve-dispute', json={
                'final_home_score': 3,
                'final_away_score': 2,
                'resolution_notes': 'Video review confirms goal was valid'
            })
            assert response.status_code == 200
        
        # Verify: Match finalized
        match = Match.query.get(match.id)
        assert match.verification_status == 'verified'
        assert match.home_score == 3
        assert match.away_score == 2
    
    def test_recurring_match_creation(self, db, client):
        """Test creating recurring matches for a season."""
        # Setup: Admin creating season schedule
        admin = UserFactory()
        admin.roles.append('Admin')
        
        season = SeasonFactory()
        teams = [TeamFactory(season=season) for _ in range(4)]
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Create recurring matches
            response = client.post('/admin/matches/create-recurring', json={
                'season_id': season.id,
                'start_date': datetime.utcnow().strftime('%Y-%m-%d'),
                'frequency': 'weekly',
                'duration_weeks': 8,
                'time_slots': ['18:00', '20:00'],
                'field_name': 'Main Field',
                'team_ids': [team.id for team in teams]
            })
            
            assert response.status_code == 200
            data = response.get_json()
            assert data['matches_created'] == 16  # 4 teams, 8 weeks, rotating
            
            # Verify: Matches created with proper spacing
            from app.models import Match
            matches = Match.query.filter_by(season_id=season.id).all()
            assert len(matches) == 16
            
            # Check weekly spacing
            match_dates = sorted(set(m.scheduled_date for m in matches))
            for i in range(len(match_dates) - 1):
                delta = match_dates[i+1] - match_dates[i]
                assert delta.days == 7  # Weekly matches