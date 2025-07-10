"""
End-to-end tests for complete player journey.
Tests the full experience from registration to playing matches.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from tests.helpers import SMSTestHelper, assert_sms_sent


@pytest.mark.e2e
@pytest.mark.slow
class TestPlayerJourney:
    """Test complete player journey from signup to match participation."""
    
    def test_new_player_complete_journey(self, client, db):
        """Test complete journey: Registration → Approval → Team Assignment → RSVP → Match."""
        sms_helper = SMSTestHelper()
        
        with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
            # Step 1: Player registers
            response = client.post('/auth/register', data={
                'username': 'newplayer',
                'email': 'player@example.com',
                'password': 'SecurePass123!',
                'password_confirm': 'SecurePass123!',
                'phone_number': '555-NEW-USER',
                'discord_username': 'NewPlayer#1234',
                'preferred_positions': 'Forward,Midfielder',
                'jersey_size': 'L'
            }, follow_redirects=True)
            
            assert b'Registration successful' in response.data
            assert b'administrator will review' in response.data
            
            # Step 2: Admin approves player
            from app.models import User, Role
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                admin = User(username='admin', email='admin@example.com')
                admin.set_password('admin123')
                admin_role = Role.query.filter_by(name='Admin').first()
                if not admin_role:
                    admin_role = Role(name='Admin')
                    db.session.add(admin_role)
                admin.roles.append(admin_role)
                db.session.add(admin)
                db.session.commit()
            
            # Login as admin
            client.post('/auth/login', data={
                'username': 'admin',
                'password': 'admin123'
            })
            
            # Approve the user
            new_user = User.query.filter_by(username='newplayer').first()
            response = client.post(f'/admin/users/{new_user.id}/approve')
            assert response.status_code in [200, 302]
            
            # Verify: Welcome SMS sent
            messages = sms_helper.get_messages_for_user(new_user)
            assert any('Welcome' in msg['message'] for msg in messages)
            
            # Step 3: Player joins team via draft
            from app.models import Season, League, Team
            league = League(name='Test League', is_active=True)
            db.session.add(league)
            
            season = Season(
                name='Test Season',
                league=league,
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow() + timedelta(days=90),
                is_active=True
            )
            db.session.add(season)
            
            team = Team(name='Eagles', season=season, captain_id=admin.id)
            db.session.add(team)
            db.session.commit()
            
            # Admin assigns player to team
            response = client.post(f'/admin/teams/{team.id}/add-player', json={
                'user_id': new_user.id,
                'jersey_number': 10
            })
            
            # Step 4: Player logs in
            client.get('/auth/logout')  # Logout admin
            response = client.post('/auth/login', data={
                'username': 'newplayer',
                'password': 'SecurePass123!'
            }, follow_redirects=True)
            
            assert b'Dashboard' in response.data
            assert b'Eagles' in response.data  # Shows team name
            
            # Step 5: Match scheduled - player receives notification
            from app.models import Match
            match = Match(
                season=season,
                home_team=team,
                away_team=team,  # Self scrimmage for simplicity
                scheduled_date=datetime.utcnow().date() + timedelta(days=5),
                scheduled_time='19:00',
                field_name='Main Field'
            )
            db.session.add(match)
            db.session.commit()
            
            # Clear previous messages
            sms_helper.clear_messages()
            
            # Send match notification
            from app.tasks.tasks_match_updates import send_new_match_notifications
            send_new_match_notifications(match.id)
            
            messages = sms_helper.get_messages_for_user(new_user)
            assert any('New match scheduled' in msg['message'] for msg in messages)
            
            # Step 6: Player RSVPs via web
            response = client.post('/api/availability', json={
                'match_id': match.id,
                'available': True,
                'notes': 'Looking forward to my first match!'
            })
            assert response.status_code == 200
            
            # Step 7: Match day - player receives reminder
            sms_helper.clear_messages()
            
            # Simulate match day
            with patch('datetime.datetime') as mock_dt:
                match_datetime = datetime.combine(
                    match.scheduled_date,
                    datetime.strptime('19:00', '%H:%M').time()
                )
                mock_dt.utcnow.return_value = match_datetime - timedelta(hours=2)
                mock_dt.now.return_value = mock_dt.utcnow.return_value
                
                from app.tasks.tasks_match_updates import send_match_day_reminders
                send_match_day_reminders()
                
                messages = sms_helper.get_messages_for_user(new_user)
                assert any('Match today' in msg['message'] for msg in messages)
            
            # Step 8: Post-match - player views stats
            # Mark match as completed
            match.status = 'completed'
            match.home_score = 2
            match.away_score = 1
            db.session.commit()
            
            # Create player stats
            from app.models import Player, PlayerMatchStats
            player = Player.query.filter_by(user_id=new_user.id).first()
            stats = PlayerMatchStats(
                player_id=player.id,
                match_id=match.id,
                goals=1,
                assists=0,
                minutes_played=90
            )
            db.session.add(stats)
            db.session.commit()
            
            # Player views their stats
            response = client.get('/players/stats')
            assert response.status_code == 200
            assert b'1 Goal' in response.data or b'1 goal' in response.data
            assert b'90 minutes' in response.data.lower()
    
    def test_player_season_progression(self, client, db):
        """Test player's progression through a full season."""
        # This would test:
        # - Multiple matches
        # - Accumulating stats
        # - Team standings updates
        # - End of season awards
        # - Moving to next season
        
        # Implementation would follow similar pattern
        # but test longer-term progression
        pass