"""
Integration tests for substitute system workflows.
Tests sub pool management, requests, and assignments.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from tests.factories import UserFactory, TeamFactory, PlayerFactory, MatchFactory
from tests.helpers import AuthTestHelper, SMSTestHelper, TestDataBuilder


@pytest.mark.integration
class TestSubstituteSystemWorkflow:
    """Test complete substitute system journeys."""
    
    def test_player_joins_substitute_pool(self, db, client):
        """Test player joining and managing substitute pool preferences."""
        # Setup: Player not on a team
        player_user = UserFactory()
        
        with AuthTestHelper.authenticated_request(client, player_user):
            # Player joins substitute pool
            response = client.post('/substitute-pool/join', json={
                'preferred_positions': ['Midfielder', 'Forward'],
                'max_matches_per_week': 2,
                'preferred_locations': ['North Field', 'Main Field'],
                'max_travel_distance': 25,
                'notification_preferences': {
                    'sms': True,
                    'email': True,
                    'discord': False
                }
            })
            assert response.status_code == 200
            
            # Verify: Player added to pool
            from app.models import SubstitutePool
            sub_entry = SubstitutePool.query.filter_by(
                player_id=player_user.id
            ).first()
            assert sub_entry is not None
            assert sub_entry.is_active is True
            assert 'Midfielder' in sub_entry.preferred_positions
            assert sub_entry.max_matches_per_week == 2
    
    def test_captain_creates_substitute_request(self, db, client):
        """Test captain creating a substitute request."""
        # Setup: Captain with upcoming match
        captain = UserFactory()
        team = TeamFactory(captain=captain)
        match = MatchFactory(
            home_team=team,
            scheduled_date=datetime.utcnow().date() + timedelta(days=3)
        )
        
        with AuthTestHelper.authenticated_request(client, captain):
            # Captain creates substitute request
            response = client.post('/substitute-requests/create', json={
                'match_id': match.id,
                'positions_needed': ['Defender', 'Midfielder'],
                'substitutes_needed': 2,
                'requirements': 'Experienced players preferred',
                'gender_preference': 'any',
                'deadline': (datetime.utcnow() + timedelta(days=2)).isoformat()
            })
            assert response.status_code == 200
            
            # Verify: Request created
            from app.models import SubstituteRequest
            request = SubstituteRequest.query.filter_by(
                match_id=match.id,
                team_id=team.id
            ).first()
            assert request is not None
            assert request.status == 'open'
            assert request.substitutes_needed == 2
    
    def test_substitute_notification_workflow(self, db):
        """Test substitute request notifications sent to eligible players."""
        # Setup: Match needing subs and available substitutes
        match = MatchFactory(
            scheduled_date=datetime.utcnow().date() + timedelta(days=3)
        )
        
        # Create substitutes with different preferences
        midfielder_sub = UserFactory(phone_number='+15551111111')
        defender_sub = UserFactory(phone_number='+15552222222')
        unavailable_sub = UserFactory(phone_number='+15553333333')
        
        from app.models import SubstitutePool
        # Active substitutes
        for user, positions in [(midfielder_sub, 'Midfielder'), (defender_sub, 'Defender')]:
            sub_entry = SubstitutePool(
                player_id=user.id,
                is_active=True,
                preferred_positions=positions,
                sms_for_sub_requests=True
            )
            db.session.add(sub_entry)
        
        # Inactive substitute
        inactive_sub = SubstitutePool(
            player_id=unavailable_sub.id,
            is_active=False,
            preferred_positions='Midfielder'
        )
        db.session.add(inactive_sub)
        db.session.commit()
        
        # Create substitute request
        from app.models import SubstituteRequest
        request = SubstituteRequest(
            match_id=match.id,
            team_id=match.home_team_id,
            positions_needed='Midfielder,Defender',
            substitutes_needed=2,
            status='open'
        )
        db.session.add(request)
        db.session.commit()
        
        sms_helper = SMSTestHelper()
        
        with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
            # Send notifications to eligible substitutes
            from app.tasks.tasks_substitute_pools import notify_eligible_substitutes
            notify_eligible_substitutes(request.id)
            
            # Verify: Active substitutes notified
            midfielder_messages = sms_helper.get_messages_for_user(midfielder_sub)
            defender_messages = sms_helper.get_messages_for_user(defender_sub)
            unavailable_messages = sms_helper.get_messages_for_user(unavailable_sub)
            
            assert len(midfielder_messages) == 1
            assert len(defender_messages) == 1
            assert len(unavailable_messages) == 0  # Inactive, not notified
            
            assert 'substitute needed' in midfielder_messages[0]['message'].lower()
    
    def test_substitute_responds_to_request(self, db, client):
        """Test substitute responding to a request."""
        # Setup: Substitute request and available player
        substitute_user = UserFactory()
        match = MatchFactory()
        
        from app.models import SubstituteRequest, SubstitutePool
        # Add user to sub pool
        sub_pool = SubstitutePool(
            player_id=substitute_user.id,
            is_active=True,
            preferred_positions='Midfielder'
        )
        db.session.add(sub_pool)
        
        # Create request
        request = SubstituteRequest(
            match_id=match.id,
            team_id=match.home_team_id,
            positions_needed='Midfielder',
            status='open'
        )
        db.session.add(request)
        db.session.commit()
        
        with AuthTestHelper.authenticated_request(client, substitute_user):
            # Substitute responds positively
            response = client.post(f'/substitute-requests/{request.id}/respond', json={
                'available': True,
                'message': 'I can play! Looking forward to helping out.',
                'preferred_position': 'Midfielder'
            })
            assert response.status_code == 200
            
            # Verify: Response recorded
            from app.models import SubstituteResponse
            response_record = SubstituteResponse.query.filter_by(
                request_id=request.id,
                player_id=substitute_user.id
            ).first()
            assert response_record is not None
            assert response_record.is_available is True
            assert 'Looking forward' in response_record.response_text
    
    def test_captain_assigns_substitute(self, db, client):
        """Test captain selecting and assigning a substitute."""
        # Setup: Request with multiple responses
        captain = UserFactory()
        team = TeamFactory(captain=captain)
        match = MatchFactory(home_team=team)
        
        # Create substitutes who responded
        available_subs = [UserFactory() for _ in range(3)]
        
        from app.models import SubstituteRequest, SubstituteResponse
        request = SubstituteRequest(
            match_id=match.id,
            team_id=team.id,
            positions_needed='Midfielder',
            status='open'
        )
        db.session.add(request)
        db.session.commit()
        
        # Create responses
        for sub_user in available_subs:
            response = SubstituteResponse(
                request_id=request.id,
                player_id=sub_user.id,
                is_available=True,
                response_method='web'
            )
            db.session.add(response)
        db.session.commit()
        
        chosen_sub = available_subs[0]
        
        with AuthTestHelper.authenticated_request(client, captain):
            # Captain assigns substitute
            response = client.post(f'/substitute-requests/{request.id}/assign', json={
                'player_id': chosen_sub.id,
                'position_assigned': 'Midfielder',
                'jersey_number': 99,
                'notes': 'Welcome to the team!'
            })
            assert response.status_code == 200
            
            # Verify: Assignment created
            from app.models import SubstituteAssignment
            assignment = SubstituteAssignment.query.filter_by(
                request_id=request.id,
                player_id=chosen_sub.id
            ).first()
            assert assignment is not None
            assert assignment.position_assigned == 'Midfielder'
            assert assignment.jersey_number == 99
            
            # Verify: Request status updated
            request = SubstituteRequest.query.get(request.id)
            assert request.status == 'filled'
    
    def test_substitute_match_day_workflow(self, db, client):
        """Test complete substitute workflow on match day."""
        # Setup: Assigned substitute and match
        substitute_user = UserFactory(phone_number='+15551234567')
        captain = UserFactory()
        team = TeamFactory(captain=captain)
        match = MatchFactory(
            home_team=team,
            scheduled_date=datetime.utcnow().date(),
            scheduled_time='19:00'
        )
        
        # Create assignment
        from app.models import SubstituteRequest, SubstituteAssignment
        request = SubstituteRequest(
            match_id=match.id,
            team_id=team.id,
            status='filled'
        )
        db.session.add(request)
        db.session.commit()
        
        assignment = SubstituteAssignment(
            request_id=request.id,
            player_id=substitute_user.id,
            position_assigned='Midfielder',
            jersey_number=99
        )
        db.session.add(assignment)
        db.session.commit()
        
        sms_helper = SMSTestHelper()
        
        with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
            # Send match day reminder to substitute
            from app.tasks.tasks_substitute_pools import send_substitute_match_reminders
            send_substitute_match_reminders()
            
            # Verify: Reminder sent
            messages = sms_helper.get_messages_for_user(substitute_user)
            assert len(messages) >= 1
            assert 'match today' in messages[-1]['message'].lower()
            assert 'jersey #99' in messages[-1]['message']
        
        # Post-match: Captain rates substitute
        with AuthTestHelper.authenticated_request(client, captain):
            response = client.post(f'/substitute-assignments/{assignment.id}/rate', json={
                'rating': 5,
                'feedback': 'Excellent player, would definitely invite back!',
                'performance_notes': 'Scored 1 goal, great teamwork'
            })
            assert response.status_code == 200
            
            # Verify: Rating recorded
            assignment = SubstituteAssignment.query.get(assignment.id)
            assert assignment.rating == 5
            assert 'Excellent player' in assignment.feedback
    
    def test_ecs_fc_substitute_system(self, db, client):
        """Test ECS FC specific substitute system."""
        # Setup: ECS FC match and substitute pool
        from app.models import ECSFCMatch, ECSFCSubPool, ECSFCSubRequest
        
        admin = UserFactory()
        admin.roles.append('ECS FC Admin')
        
        # Create ECS FC match
        ecs_match = ECSFCMatch(
            match_date=datetime.utcnow().date() + timedelta(days=2),
            match_time='20:00',
            location='Starfire Sports Complex',
            division='Premier'
        )
        db.session.add(ecs_match)
        
        # Create ECS FC substitutes
        ecs_subs = [UserFactory(phone_number=f'+155500{i:04d}') for i in range(5)]
        for sub_user in ecs_subs:
            ecs_pool_entry = ECSFCSubPool(
                player_id=sub_user.id,
                is_active=True,
                preferred_positions='Any',
                max_matches_per_week=1
            )
            db.session.add(ecs_pool_entry)
        
        db.session.commit()
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Create ECS FC substitute request
            response = client.post('/ecs-fc/substitute-requests', json={
                'match_id': ecs_match.id,
                'positions_needed': 'Forward,Midfielder',
                'substitutes_needed': 2,
                'notes': 'Premier division match, experienced players preferred'
            })
            assert response.status_code == 200
            
            request_id = response.get_json()['request_id']
            
            # Verify: Request created
            request = ECSFCSubRequest.query.get(request_id)
            assert request is not None
            assert request.status == 'open'
    
    def test_substitute_pool_analytics(self, db, client):
        """Test substitute pool management and analytics."""
        # Setup: Admin viewing substitute pool analytics
        admin = UserFactory()
        admin.roles.append('Admin')
        
        # Create historical data
        active_subs = [UserFactory() for _ in range(15)]
        inactive_subs = [UserFactory() for _ in range(5)]
        
        from app.models import SubstitutePool, SubstituteResponse, SubstituteAssignment
        
        # Create pool entries
        for user in active_subs:
            pool_entry = SubstitutePool(
                player_id=user.id,
                is_active=True,
                requests_received=5,
                requests_accepted=3,
                matches_played=2
            )
            db.session.add(pool_entry)
        
        for user in inactive_subs:
            pool_entry = SubstitutePool(
                player_id=user.id,
                is_active=False,
                requests_received=2,
                requests_accepted=0,
                matches_played=0
            )
            db.session.add(pool_entry)
        
        db.session.commit()
        
        with AuthTestHelper.authenticated_request(client, admin):
            # View substitute pool analytics
            response = client.get('/admin/substitute-pool/analytics')
            assert response.status_code == 200
            
            data = response.get_json()
            analytics = data['analytics']
            
            # Verify: Correct statistics
            assert analytics['total_active_subs'] == 15
            assert analytics['total_inactive_subs'] == 5
            assert analytics['average_acceptance_rate'] > 0
            assert analytics['total_matches_covered'] == 30  # 15 subs * 2 matches each
    
    def test_substitute_availability_calendar(self, db, client):
        """Test substitute managing their availability calendar."""
        # Setup: Substitute with calendar preferences
        substitute_user = UserFactory()
        
        from app.models import SubstitutePool
        pool_entry = SubstitutePool(
            player_id=substitute_user.id,
            is_active=True
        )
        db.session.add(pool_entry)
        db.session.commit()
        
        with AuthTestHelper.authenticated_request(client, substitute_user):
            # Set availability for specific dates
            response = client.post('/substitute-pool/availability', json={
                'unavailable_dates': [
                    (datetime.utcnow() + timedelta(days=5)).strftime('%Y-%m-%d'),
                    (datetime.utcnow() + timedelta(days=12)).strftime('%Y-%m-%d')
                ],
                'recurring_unavailable': {
                    'day_of_week': 'Tuesday',  # Always unavailable Tuesdays
                    'reason': 'Regular work commitment'
                }
            })
            assert response.status_code == 200
            
            # Verify: Availability preferences saved
            from app.models import SubstituteAvailability
            unavailable_dates = SubstituteAvailability.query.filter_by(
                player_id=substitute_user.id,
                available=False
            ).all()
            assert len(unavailable_dates) >= 2