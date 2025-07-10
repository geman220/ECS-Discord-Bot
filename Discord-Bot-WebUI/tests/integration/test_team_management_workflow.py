"""
Integration tests for team management workflows.
Tests team creation, player assignments, and roster management.
"""
import pytest
from datetime import datetime, timedelta

from tests.factories import UserFactory, TeamFactory, PlayerFactory, SeasonFactory
from tests.helpers import AuthTestHelper, TestDataBuilder


@pytest.mark.integration
class TestTeamManagementWorkflow:
    """Test complete team management journeys."""
    
    def test_admin_creates_team_and_assigns_captain(self, db, client):
        """Test team creation and captain assignment workflow."""
        # Setup: Admin and potential captain
        admin = UserFactory()
        admin.roles.append('Admin')
        
        captain = UserFactory(username='captain')
        season = SeasonFactory()
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Admin creates team
            response = client.post('/admin/teams/create', data={
                'name': 'Thunder Bolts',
                'season_id': season.id,
                'captain_id': captain.id,
                'primary_color': '#FF0000',
                'secondary_color': '#FFFFFF'
            }, follow_redirects=True)
            
            assert response.status_code == 200
            assert b'Team created successfully' in response.data
            
            # Verify: Team exists with captain
            from app.models import Team
            team = Team.query.filter_by(name='Thunder Bolts').first()
            assert team is not None
            assert team.captain_id == captain.id
            assert team.season_id == season.id
    
    def test_captain_manages_team_roster(self, db, client):
        """Test captain adding and removing players from roster."""
        # Setup: Captain with team
        captain = UserFactory()
        team = TeamFactory(captain=captain)
        
        # Create available players
        available_players = [UserFactory() for _ in range(5)]
        
        with AuthTestHelper.authenticated_request(client, captain):
            # Captain adds players to team
            for i, player_user in enumerate(available_players):
                response = client.post(f'/teams/{team.id}/add-player', json={
                    'user_id': player_user.id,
                    'jersey_number': i + 1,
                    'positions': 'Forward,Midfielder'
                })
                assert response.status_code == 200
            
            # Verify: Players added
            from app.models import Player
            team_players = Player.query.filter_by(team_id=team.id).all()
            assert len(team_players) == 5
            
            # Captain removes a player
            player_to_remove = team_players[0]
            response = client.delete(f'/teams/{team.id}/players/{player_to_remove.id}')
            assert response.status_code == 200
            
            # Verify: Player removed
            remaining_players = Player.query.filter_by(team_id=team.id).all()
            assert len(remaining_players) == 4
    
    def test_team_formation_and_lineup_management(self, db, client):
        """Test captain setting team formation and lineups."""
        # Setup: Team with full roster
        captain = UserFactory()
        team = TestDataBuilder.create_team_with_full_roster(captain=captain)
        
        with AuthTestHelper.authenticated_request(client, captain):
            # Captain sets preferred formation
            response = client.post(f'/teams/{team.id}/formation', json={
                'formation': '4-4-2',
                'preferred_lineup': {
                    'GK': [team.players[0].id],
                    'DEF': [p.id for p in team.players[1:5]],
                    'MID': [p.id for p in team.players[5:9]],
                    'FWD': [p.id for p in team.players[9:11]]
                }
            })
            assert response.status_code == 200
            
            # Verify: Formation saved
            from app.models import TeamFormation
            formation = TeamFormation.query.filter_by(team_id=team.id).first()
            assert formation is not None
            assert formation.formation_name == '4-4-2'
    
    def test_player_requests_to_join_team(self, db, client):
        """Test player requesting to join a team."""
        # Setup: Player and team
        player_user = UserFactory()
        captain = UserFactory()
        team = TeamFactory(captain=captain)
        
        with AuthTestHelper.authenticated_request(client, player_user):
            # Player requests to join team
            response = client.post(f'/teams/{team.id}/request-to-join', json={
                'positions': 'Midfielder,Forward',
                'message': 'I would love to play for this team!'
            })
            assert response.status_code == 200
            
            # Verify: Request created
            from app.models import TeamJoinRequest
            request = TeamJoinRequest.query.filter_by(
                team_id=team.id,
                user_id=player_user.id
            ).first()
            assert request is not None
            assert request.status == 'pending'
        
        # Captain reviews and approves request
        with AuthTestHelper.authenticated_request(client, captain):
            response = client.post(f'/teams/{team.id}/join-requests/{request.id}/approve', json={
                'jersey_number': 15
            })
            assert response.status_code == 200
            
            # Verify: Player added to team
            from app.models import Player
            player = Player.query.filter_by(
                team_id=team.id,
                user_id=player_user.id
            ).first()
            assert player is not None
            assert player.jersey_number == 15
    
    def test_team_statistics_calculation(self, db, client):
        """Test team statistics are calculated correctly."""
        # Setup: Team with match history
        team = TestDataBuilder.create_team_with_match_history()
        captain = team.captain
        
        with AuthTestHelper.authenticated_request(client, captain):
            # View team statistics
            response = client.get(f'/teams/{team.id}/stats')
            assert response.status_code == 200
            
            data = response.get_json()
            stats = data['stats']
            
            # Verify: Statistics calculated
            assert 'wins' in stats
            assert 'losses' in stats
            assert 'draws' in stats
            assert 'goals_for' in stats
            assert 'goals_against' in stats
            assert 'goal_difference' in stats
            assert stats['matches_played'] > 0
    
    def test_captain_delegates_permissions(self, db, client):
        """Test captain delegating permissions to assistant captain."""
        # Setup: Captain and potential assistant
        captain = UserFactory()
        assistant = UserFactory()
        team = TeamFactory(captain=captain)
        PlayerFactory(team=team, user=assistant)
        
        with AuthTestHelper.authenticated_request(client, captain):
            # Captain assigns assistant captain role
            response = client.post(f'/teams/{team.id}/assign-assistant', json={
                'user_id': assistant.id,
                'permissions': ['manage_lineup', 'view_rsvps', 'send_messages']
            })
            assert response.status_code == 200
            
            # Verify: Assistant has permissions
            from app.models import TeamRole
            role = TeamRole.query.filter_by(
                team_id=team.id,
                user_id=assistant.id,
                role_name='assistant_captain'
            ).first()
            assert role is not None
            assert 'manage_lineup' in role.permissions
        
        # Assistant can now perform delegated actions
        with AuthTestHelper.authenticated_request(client, assistant):
            response = client.post(f'/teams/{team.id}/lineup', json={
                'formation': '4-3-3',
                'starting_eleven': [p.id for p in team.players[:11]]
            })
            assert response.status_code == 200
    
    def test_team_communication_channel(self, db, client):
        """Test team communication and announcements."""
        # Setup: Team with players
        captain = UserFactory()
        team = TestDataBuilder.create_team_with_players(captain=captain, player_count=15)
        
        with AuthTestHelper.authenticated_request(client, captain):
            # Captain sends team announcement
            response = client.post(f'/teams/{team.id}/announcements', json={
                'title': 'Practice Schedule Update',
                'message': 'Practice moved to Wednesday 7 PM this week.',
                'priority': 'high',
                'notify_via': ['sms', 'email']
            })
            assert response.status_code == 200
            
            # Verify: Announcement created
            from app.models import TeamAnnouncement
            announcement = TeamAnnouncement.query.filter_by(
                team_id=team.id,
                title='Practice Schedule Update'
            ).first()
            assert announcement is not None
            assert announcement.priority == 'high'
    
    def test_team_season_transition(self, db, client):
        """Test moving team to new season."""
        # Setup: Team in completed season
        old_season = SeasonFactory(is_active=False)
        new_season = SeasonFactory(is_active=True)
        
        admin = UserFactory()
        admin.roles.append('Admin')
        
        old_team = TestDataBuilder.create_team_with_players(
            season=old_season,
            player_count=12
        )
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Admin creates new team for new season
            response = client.post('/admin/teams/transition', json={
                'old_team_id': old_team.id,
                'new_season_id': new_season.id,
                'retain_players': True,
                'retain_captain': True,
                'new_team_name': f"{old_team.name} (2024)"
            })
            assert response.status_code == 200
            
            # Verify: New team created
            from app.models import Team, Player
            new_team = Team.query.filter_by(
                season_id=new_season.id,
                name=f"{old_team.name} (2024)"
            ).first()
            assert new_team is not None
            
            # Verify: Players transitioned
            new_players = Player.query.filter_by(team_id=new_team.id).all()
            old_players = Player.query.filter_by(team_id=old_team.id).all()
            assert len(new_players) == len(old_players)
    
    def test_team_draft_system(self, db, client):
        """Test team creation via draft system."""
        # Setup: Admin conducting draft
        admin = UserFactory()
        admin.roles.append('Admin')
        
        season = SeasonFactory()
        
        # Create pool of available players
        available_players = [UserFactory() for _ in range(40)]
        
        # Create captains
        captains = [UserFactory() for _ in range(4)]
        
        with AuthTestHelper.authenticated_request(client, admin):
            # Start draft
            response = client.post('/admin/draft/start', json={
                'season_id': season.id,
                'captain_ids': [c.id for c in captains],
                'draft_type': 'snake',
                'rounds': 10
            })
            assert response.status_code == 200
            
            draft_id = response.get_json()['draft_id']
            
            # Simulate draft picks
            for round_num in range(1, 4):  # Test first 3 rounds
                for pick_order, captain in enumerate(captains):
                    player_to_pick = available_players.pop(0)
                    
                    response = client.post(f'/admin/draft/{draft_id}/pick', json={
                        'captain_id': captain.id,
                        'player_id': player_to_pick.id,
                        'round': round_num,
                        'pick': pick_order + 1
                    })
                    assert response.status_code == 200
            
            # Complete draft
            response = client.post(f'/admin/draft/{draft_id}/complete')
            assert response.status_code == 200
            
            # Verify: Teams created with drafted players
            from app.models import Team, Player
            teams = Team.query.filter_by(season_id=season.id).all()
            assert len(teams) == 4
            
            for team in teams:
                players = Player.query.filter_by(team_id=team.id).all()
                assert len(players) == 3  # 3 rounds completed