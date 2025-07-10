"""
Integration tests for admin workflows.
Tests user approval, season management, and system monitoring.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from tests.factories import UserFactory, SeasonFactory, LeagueFactory, TeamFactory
from tests.helpers import AuthTestHelper, SMSTestHelper, TestDataBuilder


@pytest.mark.integration
class TestAdminWorkflow:
    """Test complete admin management journeys."""
    
    def test_user_approval_workflow(self, db, client):
        """Test complete user approval process."""
        # Setup: Admin and pending users
        admin = UserFactory()
        admin.roles.append('Admin')
        
        # Create pending users
        pending_users = []
        for i in range(3):
            user = UserFactory(
                username=f'pending{i}',
                email=f'pending{i}@example.com',
                approved=False,
                phone_number=f'+155500{i:04d}'
            )
            pending_users.append(user)
        
        sms_helper = SMSTestHelper()
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Admin views pending approvals
            response = client.get('/admin/user-approvals')
            assert response.status_code == 200
            
            data = response.get_json()
            assert data['pending_count'] == 3
            
            with patch('app.sms_helpers.send_sms', side_effect=sms_helper.mock_send_sms):
                # Admin approves first user
                user_to_approve = pending_users[0]
                response = client.post(f'/admin/users/{user_to_approve.id}/approve', json={
                    'welcome_message': 'Welcome to ECS! Check your phone for next steps.',
                    'assign_roles': ['Player'],
                    'send_welcome_sms': True
                })
                assert response.status_code == 200
                
                # Verify: User approved
                user = User.query.get(user_to_approve.id)
                assert user.approved is True
                assert user.approved_date is not None
                
                # Verify: Welcome SMS sent
                messages = sms_helper.get_messages_for_user(user)
                assert len(messages) == 1
                assert 'Welcome to ECS' in messages[0]['message']
            
            # Admin rejects second user
            user_to_reject = pending_users[1]
            response = client.post(f'/admin/users/{user_to_reject.id}/reject', json={
                'reason': 'Incomplete registration information',
                'send_notification': True
            })
            assert response.status_code == 200
            
            # Verify: User marked as rejected
            user = User.query.get(user_to_reject.id)
            assert user.approved is False
            assert user.rejection_reason == 'Incomplete registration information'
    
    def test_season_management_workflow(self, db, client):
        """Test complete season lifecycle management."""
        # Setup: Admin managing seasons
        admin = UserFactory()
        admin.roles.append('Admin')
        
        league = LeagueFactory()
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Admin creates new season
            response = client.post('/admin/seasons/create', json={
                'name': 'Spring 2024',
                'league_id': league.id,
                'start_date': '2024-03-01',
                'end_date': '2024-05-31',
                'registration_deadline': '2024-02-15',
                'max_teams': 8,
                'season_type': 'regular'
            })
            assert response.status_code == 200
            
            season_id = response.get_json()['season_id']
            
            # Verify: Season created
            from app.models import Season
            season = Season.query.get(season_id)
            assert season is not None
            assert season.name == 'Spring 2024'
            assert season.max_teams == 8
            
            # Admin opens registration
            response = client.post(f'/admin/seasons/{season_id}/open-registration')
            assert response.status_code == 200
            
            # Verify: Registration opened
            season = Season.query.get(season_id)
            assert season.registration_open is True
            
            # Admin generates schedule
            # First create teams
            teams = []
            for i in range(6):
                team_response = client.post('/admin/teams/create', json={
                    'name': f'Team {i+1}',
                    'season_id': season_id,
                    'captain_id': UserFactory().id
                })
                teams.append(team_response.get_json()['team_id'])
            
            # Generate round-robin schedule
            response = client.post(f'/admin/seasons/{season_id}/generate-schedule', json={
                'schedule_type': 'round_robin',
                'start_date': '2024-03-08',
                'match_frequency': 'weekly',
                'time_slots': ['18:00', '20:00'],
                'fields': ['North Field', 'South Field']
            })
            assert response.status_code == 200
            
            schedule_data = response.get_json()
            assert schedule_data['matches_created'] > 0
            
            # Admin closes season
            response = client.post(f'/admin/seasons/{season_id}/close', json={
                'final_standings': True,
                'generate_awards': True,
                'archive_data': True
            })
            assert response.status_code == 200
            
            # Verify: Season closed properly
            season = Season.query.get(season_id)
            assert season.is_active is False
            assert season.archived is True
    
    def test_league_configuration_workflow(self, db, client):
        """Test league setup and configuration."""
        # Setup: Super admin creating league
        super_admin = UserFactory()
        super_admin.roles.append('Super Admin')
        
        with AuthTestHelper.authenticated_request(client, super_admin):
            # Create new league
            response = client.post('/admin/leagues/create', json={
                'name': 'Seattle Premier League',
                'description': 'Premier competitive league in Seattle area',
                'sport': 'soccer',
                'rules': {
                    'match_duration': 90,
                    'overtime_rules': 'sudden_death',
                    'substitution_limit': 5,
                    'roster_size_min': 15,
                    'roster_size_max': 22
                },
                'settings': {
                    'allow_guest_players': False,
                    'require_registration_fee': True,
                    'public_stats': True
                }
            })
            assert response.status_code == 200
            
            league_id = response.get_json()['league_id']
            
            # Configure league administrators
            league_admin = UserFactory()
            response = client.post(f'/admin/leagues/{league_id}/administrators', json={
                'user_id': league_admin.id,
                'permissions': ['manage_seasons', 'approve_users', 'view_reports']
            })
            assert response.status_code == 200
            
            # Verify: League admin has permissions
            from app.models import LeagueAdmin
            admin_role = LeagueAdmin.query.filter_by(
                league_id=league_id,
                user_id=league_admin.id
            ).first()
            assert admin_role is not None
            assert 'manage_seasons' in admin_role.permissions
    
    def test_system_monitoring_workflow(self, db, client):
        """Test system health monitoring and alerts."""
        # Setup: Admin monitoring system
        admin = UserFactory()
        admin.roles.append('Admin')
        
        with AuthTestHelper.authenticated_request(client, admin):
            # View system dashboard
            response = client.get('/admin/system/dashboard')
            assert response.status_code == 200
            
            data = response.get_json()
            dashboard = data['dashboard']
            
            # Verify: Key metrics present
            assert 'active_users' in dashboard
            assert 'database_health' in dashboard
            assert 'external_services' in dashboard
            assert 'recent_errors' in dashboard
            
            # Check database performance
            response = client.get('/admin/system/database-performance')
            assert response.status_code == 200
            
            perf_data = response.get_json()
            assert 'slow_queries' in perf_data
            assert 'connection_pool_status' in perf_data
            assert 'average_query_time' in perf_data
            
            # View error logs
            response = client.get('/admin/system/error-logs')
            assert response.status_code == 200
            
            # Test SMS service health
            response = client.get('/admin/system/sms-health')
            assert response.status_code == 200
            
            sms_health = response.get_json()
            assert 'twilio_status' in sms_health
            assert 'daily_sms_count' in sms_health
            assert 'rate_limit_status' in sms_health
    
    def test_report_generation_workflow(self, db, client):
        """Test admin report generation."""
        # Setup: Admin generating reports
        admin = UserFactory()
        admin.roles.append('Admin')
        
        # Create test data
        season = SeasonFactory()
        teams = [TeamFactory(season=season) for _ in range(4)]
        
        # Create matches with results
        from app.models import Match
        for i in range(10):
            match = Match(
                season=season,
                home_team=teams[i % 2],
                away_team=teams[(i + 1) % 2],
                scheduled_date=datetime.utcnow().date() - timedelta(days=i),
                status='completed',
                home_score=2,
                away_score=1
            )
            db.session.add(match)
        db.session.commit()
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Generate season summary report
            response = client.post('/admin/reports/season-summary', json={
                'season_id': season.id,
                'format': 'json',
                'include_sections': [
                    'standings',
                    'statistics',
                    'attendance',
                    'financial'
                ]
            })
            assert response.status_code == 200
            
            report_data = response.get_json()
            assert 'standings' in report_data
            assert 'statistics' in report_data
            
            # Generate user activity report
            response = client.post('/admin/reports/user-activity', json={
                'date_range': {
                    'start': (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'),
                    'end': datetime.utcnow().strftime('%Y-%m-%d')
                },
                'metrics': ['logins', 'rsvp_responses', 'messages_sent']
            })
            assert response.status_code == 200
            
            activity_report = response.get_json()
            assert 'total_logins' in activity_report
            assert 'rsvp_response_rate' in activity_report
            
            # Schedule recurring report
            response = client.post('/admin/reports/schedule', json={
                'report_type': 'weekly_summary',
                'frequency': 'weekly',
                'day_of_week': 'monday',
                'recipients': ['admin@example.com'],
                'format': 'pdf'
            })
            assert response.status_code == 200
            
            # Verify: Scheduled report created
            from app.models import ScheduledReport
            scheduled = ScheduledReport.query.filter_by(
                report_type='weekly_summary'
            ).first()
            assert scheduled is not None
            assert scheduled.frequency == 'weekly'
    
    def test_bulk_user_operations(self, db, client):
        """Test bulk user management operations."""
        # Setup: Admin with many users to manage
        admin = UserFactory()
        admin.roles.append('Admin')
        
        # Create users needing bulk operations
        inactive_users = [
            UserFactory(last_login=datetime.utcnow() - timedelta(days=365))
            for _ in range(10)
        ]
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Bulk deactivate inactive users
            response = client.post('/admin/users/bulk-deactivate', json={
                'criteria': {
                    'last_login_before': (datetime.utcnow() - timedelta(days=180)).strftime('%Y-%m-%d'),
                    'no_team_assignment': True
                },
                'dry_run': False,
                'send_notification': True
            })
            assert response.status_code == 200
            
            bulk_result = response.get_json()
            assert bulk_result['users_affected'] >= 10
            
            # Bulk role assignment
            active_players = [UserFactory() for _ in range(5)]
            
            response = client.post('/admin/users/bulk-assign-roles', json={
                'user_ids': [u.id for u in active_players],
                'roles_to_add': ['Player'],
                'roles_to_remove': []
            })
            assert response.status_code == 200
            
            # Verify: Roles assigned
            from app.models import User
            for user_id in [u.id for u in active_players]:
                user = User.query.get(user_id)
                assert user.has_role('Player')
    
    def test_data_export_import_workflow(self, db, client):
        """Test data export and import for backup/migration."""
        # Setup: Admin performing data operations
        admin = UserFactory()
        admin.roles.append('Super Admin')
        
        # Create sample data
        season = SeasonFactory()
        teams = [TeamFactory(season=season) for _ in range(2)]
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Export season data
            response = client.post('/admin/data/export', json={
                'export_type': 'season',
                'season_id': season.id,
                'include': ['teams', 'players', 'matches', 'statistics'],
                'format': 'json',
                'anonymize_personal_data': False
            })
            assert response.status_code == 200
            
            export_data = response.get_json()
            assert 'teams' in export_data
            assert len(export_data['teams']) == 2
            
            # Test data import validation
            response = client.post('/admin/data/validate-import', json={
                'data': export_data,
                'import_type': 'season',
                'target_league_id': season.league_id
            })
            assert response.status_code == 200
            
            validation_result = response.get_json()
            assert validation_result['valid'] is True
            assert validation_result['warnings'] == []
    
    def test_emergency_operations_workflow(self, db, client):
        """Test emergency admin operations."""
        # Setup: Admin handling emergency
        admin = UserFactory()
        admin.roles.append('Super Admin')
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Emergency: Cancel all matches due to weather
            response = client.post('/admin/emergency/cancel-matches', json={
                'date_range': {
                    'start': datetime.utcnow().strftime('%Y-%m-%d'),
                    'end': (datetime.utcnow() + timedelta(days=2)).strftime('%Y-%m-%d')
                },
                'reason': 'Severe weather warning - all fields closed',
                'notify_users': True,
                'reschedule_automatically': False
            })
            assert response.status_code == 200
            
            emergency_result = response.get_json()
            assert 'matches_cancelled' in emergency_result
            
            # Emergency: Disable SMS system
            response = client.post('/admin/emergency/disable-sms', json={
                'reason': 'Twilio service issues',
                'duration_hours': 24,
                'fallback_to_email': True
            })
            assert response.status_code == 200
            
            # Verify: SMS disabled
            from app.models import SystemSettings
            setting = SystemSettings.query.filter_by(
                key='sms_service_enabled'
            ).first()
            assert setting.value == 'false'
            
            # Emergency: Reset user passwords
            compromised_users = [UserFactory() for _ in range(3)]
            
            response = client.post('/admin/emergency/reset-passwords', json={
                'user_ids': [u.id for u in compromised_users],
                'reason': 'Security breach - precautionary reset',
                'require_password_change': True,
                'send_reset_links': True
            })
            assert response.status_code == 200
            
            reset_result = response.get_json()
            assert reset_result['passwords_reset'] == 3