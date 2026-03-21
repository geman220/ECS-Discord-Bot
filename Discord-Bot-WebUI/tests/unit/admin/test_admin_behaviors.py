"""
Behavior-focused tests for admin panel routes.

These tests verify admin behaviors at the outcome level:
- "When admin does X, system does Y"

Focus areas:
1. User management - approve/reject users, assign roles
2. Team management - create/edit teams
3. Season management - create seasons, set current season
4. Match management - schedule matches, update scores
"""

import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import patch, MagicMock

from app.models import User, Role, Team, League, Season, Match, Player
from app.models.matches import Schedule
from app.models.admin_config import AdminAuditLog


# =============================================================================
# FIXTURES FOR ADMIN TESTS
# =============================================================================

@pytest.fixture
def global_admin_role(db):
    """Create the Global Admin role."""
    role = Role.query.filter_by(name='Global Admin').first()
    if not role:
        role = Role(name='Global Admin', description='Full system access')
        db.session.add(role)
        db.session.flush()
    return role


@pytest.fixture
def pub_league_admin_role(db):
    """Create the Pub League Admin role."""
    role = Role.query.filter_by(name='Pub League Admin').first()
    if not role:
        role = Role(name='Pub League Admin', description='Pub League Administrator')
        db.session.add(role)
        db.session.flush()
    return role



@pytest.fixture
def global_admin_user(db, global_admin_role):
    """Create a user with Global Admin role."""
    admin = User(
        username='globaladmin',
        email='globaladmin@example.com',
        is_approved=True,
        approval_status='approved'
    )
    admin.set_password('admin123')
    admin.roles.append(global_admin_role)
    db.session.add(admin)
    db.session.flush()
    yield admin

@pytest.fixture
def global_admin_client(client, global_admin_user, db):
    """Create a test client authenticated as Global Admin."""
    # Just get the ID from the object - this should trigger a lazy load if not expired
    user_id = global_admin_user.id
    
    with client.session_transaction() as session:
        session['_user_id'] = user_id
        session['_fresh'] = True
    return client


# =============================================================================
# USER MANAGEMENT BEHAVIORS
# =============================================================================

class TestUserApprovalBehaviors:
    """Test behaviors around user approval workflow."""

    def test_when_admin_approves_pending_user_then_user_becomes_approved(
        self, global_admin_client, db, global_admin_user
    ):
        """When admin approves a pending user, the user should become approved."""
        # Ensure admin is attached
        if global_admin_user not in db.session:
            global_admin_user = db.session.merge(global_admin_user)
            
        # Create a pending user
        pending_user = User(
            username='pendinguser',
            email='pending@example.com',
            approval_status='pending',
            is_approved=False
        )
        pending_user.set_password('password123')
        db.session.add(pending_user)

        # Create required roles
        pl_classic_role = Role(name='pl-classic', description='Classic league player')
        db.session.add(pl_classic_role)

        # CRITICAL: Commit to ensure it's visible to the API request
        db.session.commit()
        user_id = pending_user.id
        # Admin approves the user with mocked Discord task
        with patch('app.admin_panel.routes.user_management.approvals.assign_roles_to_player_task'):
            response = global_admin_client.post(
                f'/admin-panel/users/approvals/approve/{user_id}',
                data={'league_type': 'classic', 'notes': 'Approved for testing'}
            )

        # Verify the outcome
        assert response.status_code == 200
        
        # Use get_by_id to ensure session integrity
        updated_user = User.get_by_id(user_id)
        assert updated_user.approval_status == 'approved'
        assert updated_user.is_approved is True
        assert updated_user.approval_league == 'classic'
        
        # Access admin ID through fresh query if needed
        fresh_admin = User.get_by_id(global_admin_user.id)
        assert updated_user.approved_by == fresh_admin.id

    def test_when_admin_denies_pending_user_then_user_becomes_denied(
        self, global_admin_client, db, global_admin_user
    ):
        """When admin denies a pending user, the user should become denied."""
        # Ensure admin is attached
        if global_admin_user not in db.session:
            global_admin_user = db.session.merge(global_admin_user)
            
        # Create a pending user
        pending_user = User(
            username='denieduser',
            email='denied@example.com',
            approval_status='pending',
            is_approved=False
        )
        pending_user.set_password('password123')
        db.session.add(pending_user)
        db.session.commit()
        user_id = pending_user.id

        # Admin denies the user with mocked Discord task
        with patch('app.admin_panel.routes.user_management.approvals.remove_player_roles_task'):
            response = global_admin_client.post(
                f'/admin-panel/users/approvals/deny/{user_id}',
                data={'notes': 'Denied for testing'}
            )

        # Verify the outcome
        assert response.status_code == 200
        updated_user = db.session.query(User).get(pending_user.id)
        assert updated_user.approval_status == 'denied'
        assert updated_user.approval_notes == 'Denied for testing'

    def test_when_admin_approves_user_then_audit_log_is_created(
        self, global_admin_client, db, global_admin_user
    ):
        """When admin approves a user, an audit log entry should be created."""
        # Create a pending user
        pending_user = User(
            username='audituser',
            email='audit@example.com',
            approval_status='pending',
            is_approved=False
        )
        pending_user.set_password('password123')
        db.session.add(pending_user)

        # Use correct role name expected by the route
        pl_classic_role = db.session.query(Role).filter_by(name='pl-classic').first()
        if not pl_classic_role:
            pl_classic_role = Role(name='pl-classic', description='Classic league player')
            db.session.add(pl_classic_role)

        # CRITICAL: Commit to ensure it's visible to the API request
        db.session.commit()

        user_id = pending_user.id
        initial_audit_count = db.session.query(AdminAuditLog).filter_by(
            action='approve_user'
        ).count()

        with patch('app.admin_panel.routes.user_management.approvals.assign_roles_to_player_task'):
            response = global_admin_client.post(
                f'/admin-panel/users/approvals/approve/{user_id}',
                data={'league_type': 'classic'}
            )

        assert response.status_code == 200, f"Approval failed with {response.status_code}: {response.data}"

        # Ensure we see the changes committed by the route
        db.session.expire_all()

        # Verify audit log was created
        new_audit_count = db.session.query(AdminAuditLog).filter_by(
            action='approve_user'
        ).count()
        assert new_audit_count == initial_audit_count + 1

    def test_when_admin_approves_user_then_role_is_assigned(
        self, global_admin_client, db, global_admin_user
    ):
        """When admin approves a user for a league, the corresponding role is assigned."""
        pending_user = User(
            username='roleuser',
            email='role@example.com',
            approval_status='pending',
            is_approved=False
        )
        pending_user.set_password('password123')
        db.session.add(pending_user)
        
        premier_role = db.session.query(Role).filter_by(name='pl-premier').first()
        if not premier_role:
            premier_role = Role(name='pl-premier', description='Premier league player')
            db.session.add(premier_role)
        
        db.session.commit()
        user_id = pending_user.id

        with patch('app.admin_panel.routes.user_management.approvals.assign_roles_to_player_task'):
            global_admin_client.post(
                f'/admin-panel/users/approvals/approve/{user_id}',
                data={'league_type': 'premier'}
            )

        # Verify role was assigned
        updated_user = db.session.query(User).get(user_id)
        # Check by name to avoid identity issues
        assert any(r.name == 'pl-premier' for r in updated_user.roles)

    def test_when_approving_nonexistent_user_then_returns_404(
        self, global_admin_client, db
    ):
        """When admin tries to approve a non-existent user, system returns 404."""
        with patch('app.admin_panel.routes.user_management.approvals.assign_roles_to_player_task'):
            # Use an ID that won't exist (negative or extremely large)
            response = global_admin_client.post(
                '/admin-panel/users/approvals/approve/123456789',
                data={'league_type': 'classic'}
            )

        assert response.status_code == 404

    def test_when_approving_already_approved_user_then_returns_400(
        self, global_admin_client, db, global_admin_role
    ):
        """When admin tries to approve an already approved user, system returns 400."""
        approved_user = User(
            username='alreadyapproved',
            email='approved@example.com',
            approval_status='approved',
            is_approved=True
        )
        approved_user.set_password('password123')
        db.session.add(approved_user)
        db.session.flush()
        user_id = approved_user.id

        with patch('app.admin_panel.routes.user_management.approvals.assign_roles_to_player_task'):
            response = global_admin_client.post(
                f'/admin-panel/users/approvals/approve/{user_id}',
                data={'league_type': 'classic'}
            )

        assert response.status_code == 400


class TestRoleManagementBehaviors:
    """Test behaviors around role management."""

    def test_when_admin_assigns_role_to_user_then_user_has_role(
        self, global_admin_client, db, global_admin_user, user_role
    ):
        """When admin assigns a role to a user, that user should have the role."""
        target_user = User(
            username='targetuser',
            email='target@example.com',
            is_approved=True,
            approval_status='approved'
        )
        target_user.set_password('password123')
        db.session.add(target_user)

        new_role = Role(name='TestRole', description='Test role for assignment')
        db.session.add(new_role)
        db.session.flush()
        
        user_id = target_user.id
        role_id = new_role.id

        with patch('app.admin_panel.routes.user_management.roles.assign_roles_to_player_task'), \
             patch('app.admin_panel.routes.user_management.roles.sync_role_assignment'), \
             patch('app.admin_panel.routes.user_management.roles.sync_role_removal'):
            response = global_admin_client.post(
                '/admin-panel/users/assign-role',
                data={
                    'user_id': user_id,
                    'role_id': role_id,
                    'action': 'add'
                }
            )

        assert response.status_code == 200
        # Fetch fresh instance through model method
        updated_user = User.get_by_id(user_id)
        assert any(r.id == role_id for r in updated_user.roles)

    def test_when_admin_removes_role_from_user_then_user_loses_role(
        self, global_admin_client, db, global_admin_user
    ):
        """When admin removes a role from a user, that user should no longer have it."""
        target_user = User(
            username='roleremoveuser',
            email='roleremove@example.com',
            is_approved=True,
            approval_status='approved'
        )
        target_user.set_password('password123')

        role_to_remove = Role(name='RemovableRole', description='Role to be removed')
        db.session.add(target_user)
        db.session.add(role_to_remove)
        db.session.flush()

        target_user.roles.append(role_to_remove)
        db.session.flush()
        
        user_id = target_user.id
        role_id = role_to_remove.id

        assert any(r.id == role_id for r in target_user.roles)

        with patch('app.admin_panel.routes.user_management.roles.assign_roles_to_player_task'), \
             patch('app.admin_panel.routes.user_management.roles.sync_role_assignment'), \
             patch('app.admin_panel.routes.user_management.roles.sync_role_removal'):
            response = global_admin_client.post(
                '/admin-panel/users/assign-role',
                data={
                    'user_id': user_id,
                    'role_id': role_id,
                    'action': 'remove'
                }
            )

        assert response.status_code == 200
        # Fetch fresh instance through model method
        updated_user = User.get_by_id(user_id)
        assert not any(r.id == role_id for r in updated_user.roles)

    def test_when_admin_assigns_duplicate_role_then_returns_error(
        self, global_admin_client, db, global_admin_user
    ):
        """When admin tries to assign a role the user already has, returns error."""
        target_user = User(
            username='duplicateroleuser',
            email='duplicaterole@example.com',
            is_approved=True,
            approval_status='approved'
        )
        target_user.set_password('password123')

        existing_role = Role(name='ExistingRole', description='Already assigned')
        db.session.add(target_user)
        db.session.add(existing_role)
        db.session.flush()

        target_user.roles.append(existing_role)
        db.session.flush()
        
        user_id = target_user.id
        role_id = existing_role.id

        with patch('app.admin_panel.routes.user_management.roles.assign_roles_to_player_task'), \
             patch('app.admin_panel.routes.user_management.roles.sync_role_assignment'), \
             patch('app.admin_panel.routes.user_management.roles.sync_role_removal'):
            response = global_admin_client.post(
                '/admin-panel/users/assign-role',
                data={
                    'user_id': user_id,
                    'role_id': role_id,
                    'action': 'add'
                }
            )

        data = response.get_json()
        assert response.status_code == 400
        assert data['success'] is False
        assert 'already has this role' in data['message']


# =============================================================================
# TEAM MANAGEMENT BEHAVIORS
# =============================================================================

class TestTeamManagementBehaviors:
    """Test behaviors around team management."""

    def test_when_admin_creates_team_then_team_exists_in_database(
        self, global_admin_client, db, global_admin_user, league
    ):
        """When admin creates a team, it should exist in the database."""
        # Refresh league object
        if league not in db.session:
            league = db.session.merge(league)
            
        with patch('app.admin_panel.routes.match_operations.teams.create_team_discord_resources_task'):
            response = global_admin_client.post(
                '/admin-panel/match-operations/teams/create',
                data={
                    'name': 'New Test Team',
                    'league_id': league.id
                }
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        # Verify team exists in database
        new_team = Team.query.filter_by(name='New Test Team').first()
        assert new_team is not None
        assert new_team.league_id == league.id

    def test_when_admin_creates_team_then_audit_log_is_created(
        self, global_admin_client, db, global_admin_user, league
    ):
        """When admin creates a team, an audit log entry should be created."""
        # Refresh league object
        if league not in db.session:
            league = db.session.merge(league)
            
        initial_audit_count = db.session.query(AdminAuditLog).filter_by(
            action='create_team'
        ).count()

        with patch('app.admin_panel.routes.match_operations.teams.create_team_discord_resources_task'):
            global_admin_client.post(
                '/admin-panel/match-operations/teams/create',
                data={
                    'name': 'Audit Test Team',
                    'league_id': league.id
                }
            )

        new_audit_count = db.session.query(AdminAuditLog).filter_by(
            action='create_team'
        ).count()
        assert new_audit_count == initial_audit_count + 1

    def test_when_admin_updates_team_then_name_changes(
        self, global_admin_client, db, global_admin_user, team
    ):
        """When admin updates a team name, the name should change."""
        # Refresh team object
        if team not in db.session:
            team = db.session.merge(team)
            
        old_name = team.name

        with patch('app.admin_panel.routes.match_operations.teams.update_team_discord_resources_task'):
            response = global_admin_client.post(
                f'/admin-panel/match-operations/teams/{team.id}/update',
                data={
                    'name': 'Updated Team Name',
                    'league_id': team.league_id
                }
            )

        assert response.status_code == 200
        updated_team = db.session.query(Team).get(team.id)
        assert updated_team.name == 'Updated Team Name'
        assert updated_team.name != old_name

    def test_when_admin_deletes_team_without_players_then_team_is_deleted(
        self, global_admin_client, db, global_admin_user, league
    ):
        """When admin deletes a team without players, the team should be deleted."""
        # Ensure league is in session
        if league not in db.session:
            league = db.session.merge(league)
            
        # Create a team with no players
        team_to_delete = Team(name='DeleteMe Team', league_id=league.id)
        db.session.add(team_to_delete)
        db.session.flush()
        team_id = team_to_delete.id

        response = global_admin_client.post(
            f'/admin-panel/match-operations/teams/{team_id}/delete'
        )

        assert response.status_code == 200
        
        # Ensure session sees the deletion
        db.session.expire_all()
        
        # Use query directly to avoid detached session issues
        deleted_team = db.session.query(Team).get(team_id)
        assert deleted_team is None

    def test_when_admin_deletes_team_with_players_then_returns_error(
        self, global_admin_client, db, global_admin_user, team, user
    ):
        """When admin tries to delete a team with players, system returns error."""
        # Ensure objects are in session
        if team not in db.session:
            team = db.session.merge(team)
        if user not in db.session:
            user = db.session.merge(user)

        # Add a player to the team
        player = Player(
            name='Team Player',
            user_id=user.id,
            discord_id='discord123',
            jersey_number=99
        )
        db.session.add(player)
        db.session.flush()

        player.teams.append(team)
        db.session.flush()

        response = global_admin_client.post(
            f'/admin-panel/match-operations/teams/{team.id}/delete'
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Cannot delete team with' in data['message']

    def test_when_admin_creates_team_without_name_then_returns_error(
        self, global_admin_client, db, global_admin_user, league
    ):
        """When admin creates a team without a name, system returns error."""
        response = global_admin_client.post(
            '/admin-panel/match-operations/teams/create',
            data={
                'name': '',
                'league_id': league.id
            }
        )

        assert response.status_code == 400

    def test_when_admin_gets_team_details_then_returns_team_info(
        self, global_admin_client, db, global_admin_role, team
    ):
        """When admin requests team details, system returns team information."""
        response = global_admin_client.get(
            f'/admin-panel/match-operations/teams/{team.id}/details'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        # Fetch fresh
        fresh_team = db.session.query(Team).get(team.id)
        assert data['team']['id'] == fresh_team.id
        assert data['team']['name'] == fresh_team.name


# =============================================================================
# SEASON MANAGEMENT BEHAVIORS
# =============================================================================

class TestSeasonManagementBehaviors:
    """Test behaviors around season management."""

    def test_when_admin_creates_season_then_season_exists(
        self, global_admin_client, db, global_admin_user
    ):
        """When admin creates a season, it should exist in the database."""
        response = global_admin_client.post(
            '/admin-panel/match-operations/seasons/create',
            data={
                'name': 'Test Season 2025',
                'start_date': '2025-01-01',
                'end_date': '2025-06-30',
                'is_current': 'false'
            }
        )

        assert response.status_code == 200
        new_season = db.session.query(Season).filter_by(name='Test Season 2025').first()
        assert new_season is not None

    def test_when_admin_sets_season_as_current_then_other_seasons_become_not_current(
        self, global_admin_client, db, global_admin_user
    ):
        """When admin sets a season as current, other seasons should become not current."""
        # Create two seasons, one current
        season1 = Season(name='Old Current Season', league_type='CLASSIC', is_current=True)
        season2 = Season(name='New Current Season', league_type='CLASSIC', is_current=False)
        db.session.add_all([season1, season2])
        db.session.flush()

        assert season1.is_current is True
        assert season2.is_current is False

        # Set season2 as current
        response = global_admin_client.post(
            '/admin-panel/match-operations/season/set-current',
            data={'season_id': season2.id}
        )

        assert response.status_code == 200
        assert season1.is_current is False
        assert season2.is_current is True

    def test_when_admin_updates_season_then_changes_are_persisted(
        self, global_admin_client, db, global_admin_user
    ):
        """When admin updates a season, changes should be saved."""
        test_season = Season(
            name='Updatable Season',
            league_type='CLASSIC',
            is_current=False
        )
        db.session.add(test_season)
        db.session.flush()

        response = global_admin_client.post(
            f'/admin-panel/match-operations/seasons/{test_season.id}/update',
            data={
                'name': 'Updated Season Name',
                'start_date': '2025-02-01',
                'end_date': '2025-07-31',
                'is_current': 'false'
            }
        )

        assert response.status_code == 200
        updated_season = db.session.query(Season).get(test_season.id)
        assert updated_season.name == 'Updated Season Name'

    def test_when_admin_deletes_empty_season_then_season_is_deleted(
        self, global_admin_client, db, global_admin_user
    ):
        """When admin deletes a season with no matches, it should be deleted."""
        season_to_delete = Season(
            name='Deletable Season',
            league_type='CLASSIC',
            is_current=False
        )
        db.session.add(season_to_delete)
        db.session.flush()
        season_id = season_to_delete.id

        response = global_admin_client.post(
            f'/admin-panel/match-operations/seasons/{season_id}/delete'
        )

        assert response.status_code == 200
        
        # Ensure session sees the deletion
        db.session.expire_all()
        
        # Use query directly to avoid detached session issues
        deleted_season = db.session.query(Season).get(season_id)
        assert deleted_season is None

    def test_when_admin_gets_season_details_then_returns_season_info(
        self, global_admin_client, db, global_admin_role, season
    ):
        """When admin requests season details, system returns season information."""
        response = global_admin_client.get(
            f'/admin-panel/match-operations/seasons/{season.id}/details'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        # Fetch fresh to avoid detached
        fresh_season = db.session.query(Season).get(season.id)
        assert data['season']['id'] == fresh_season.id
        assert data['season']['name'] == fresh_season.name

    def test_when_admin_creates_current_season_then_becomes_current(
        self, global_admin_client, db, global_admin_user
    ):
        """When admin creates a season marked as current, it should be current."""
        response = global_admin_client.post(
            '/admin-panel/match-operations/seasons/create',
            data={
                'name': 'New Current Season',
                'start_date': '2025-03-01',
                'end_date': '2025-08-31',
                'is_current': 'true'
            }
        )

        assert response.status_code == 200
        new_season = db.session.query(Season).filter_by(name='New Current Season').first()
        assert new_season is not None
        assert new_season.is_current is True


# =============================================================================
# MATCH MANAGEMENT BEHAVIORS
# =============================================================================

class TestMatchSchedulingBehaviors:
    """Test behaviors around match scheduling."""

    def test_when_admin_creates_match_then_match_exists(
        self, global_admin_client, db, global_admin_user, team, opponent_team, schedule
    ):
        """When admin creates a match, it should exist in the database."""
        if team not in db.session:
            team = db.session.merge(team)
        if opponent_team not in db.session:
            opponent_team = db.session.merge(opponent_team)
        if schedule not in db.session:
            schedule = db.session.merge(schedule)
            
        home_id = team.id
        away_id = opponent_team.id
        sched_id = schedule.id

        response = global_admin_client.post(
            '/admin-panel/match-operations/create-match',
            json={
                'home_team_id': home_id,
                'away_team_id': away_id,
                'date': '2025-03-15',
                'time': '14:00',
                'location': 'Test Field',
                'schedule_id': sched_id
            },
            content_type='application/json'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        new_match = Match.query.filter_by(
            home_team_id=team.id,
            away_team_id=opponent_team.id
        ).first()
        assert new_match is not None

    def test_when_admin_creates_match_same_team_vs_itself_then_returns_error(
        self, global_admin_client, db, global_admin_user, team
    ):
        """When admin tries to create a match with same home and away team, returns error."""
        response = global_admin_client.post(
            '/admin-panel/match-operations/create-match',
            json={
                'home_team_id': team.id,
                'away_team_id': team.id,
                'date': '2025-03-15',
                'time': '14:00'
            },
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'must be different' in data['message']

    def test_when_admin_creates_match_different_leagues_then_returns_error(
        self, global_admin_client, db, global_admin_user, season
    ):
        """When admin creates match with teams from different leagues, returns error."""
        # Create two teams in different leagues
        league1 = League(name='League 1', season_id=season.id)
        league2 = League(name='League 2', season_id=season.id)
        db.session.add_all([league1, league2])
        db.session.flush()

        team1 = Team(name='Team League 1', league_id=league1.id)
        team2 = Team(name='Team League 2', league_id=league2.id)
        db.session.add_all([team1, team2])
        db.session.flush()

        response = global_admin_client.post(
            '/admin-panel/match-operations/create-match',
            json={
                'home_team_id': team1.id,
                'away_team_id': team2.id,
                'date': '2025-03-15',
                'time': '14:00',
                'location': 'Test Field',
                'schedule_id': 1 # Use any ID for validation error test
            },
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'same league' in data['message']

    def test_when_admin_updates_match_time_then_time_changes(
        self, global_admin_client, db, global_admin_user, match
    ):
        """When admin updates a match time, the time should change."""
        match_id = match.id
        
        response = global_admin_client.post(
            '/admin-panel/match-operations/update-match-time',
            json={
                'match_id': match_id,
                'date': '2025-04-01',
                'time': '16:30'
            },
            content_type='application/json'
        )

        assert response.status_code == 200
        updated_match = db.session.query(Match).get(match_id)
        assert updated_match.date == date(2025, 4, 1)
        assert updated_match.time == time(16, 30)

    def test_when_admin_auto_schedules_matches_then_matches_are_created(
        self, global_admin_client, db, global_admin_user, league
    ):
        """When admin auto-schedules a league, matches should be created."""
        # Create multiple teams in the league
        team1 = Team(name='Auto Team 1', league_id=league.id)
        team2 = Team(name='Auto Team 2', league_id=league.id)
        team3 = Team(name='Auto Team 3', league_id=league.id)
        db.session.add_all([team1, team2, team3])
        db.session.flush()

        initial_match_count = db.session.query(Match).count()

        response = global_admin_client.post(
            '/admin-panel/match-operations/auto-schedule',
            json={
                'league_id': league.id,
                'start_date': '2025-05-01',
                'weeks_between': 1
            },
            content_type='application/json'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        # Should have created matches
        new_match_count = db.session.query(Match).count()
        assert new_match_count > initial_match_count

    def test_when_admin_views_matches_then_returns_match_list(
        self, global_admin_client, db, global_admin_role, match
    ):
        """When admin views matches, system returns list of matches."""
        # Refresh match
        if match not in db.session:
            match = db.session.merge(match)
            
        response = global_admin_client.get('/admin-panel/match-operations/matches')

        assert response.status_code == 200

    def test_when_admin_gets_match_details_then_returns_match_info(
        self, global_admin_client, db, global_admin_role, match
    ):
        """When admin requests match details, system returns match information."""
        # Refresh match
        if match not in db.session:
            match = db.session.merge(match)
            
        response = global_admin_client.get(
            f'/admin-panel/match-operations/match/details?match_id={match.id}'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True


# =============================================================================
# ACCESS CONTROL BEHAVIORS
# =============================================================================

class TestAdminAccessControlBehaviors:
    """Test that admin routes require proper authentication."""

    def test_when_unauthenticated_user_accesses_admin_then_redirects_to_login(
        self, client, db
    ):
        """Unauthenticated users should be redirected to login."""
        response = client.get('/admin-panel/users', follow_redirects=False)

        # Should redirect (302) or return 401
        assert response.status_code in [302, 401, 403]

    def test_when_regular_user_accesses_admin_then_returns_forbidden(
        self, authenticated_client, db
    ):
        """Regular users should not access admin routes."""
        # The app uses role_required which redirects to home or aborts
        response = authenticated_client.get(
            '/admin-panel/users',
            follow_redirects=True
        )

        # Standard behavior: 200 after redirect to home OR 403
        assert response.status_code in [200, 403]
        # If redirected to home (200), it shouldn't contain admin content
        if response.status_code == 200:
            assert b'Admin' not in response.data or b'User Management' not in response.data

    def test_when_admin_accesses_user_management_then_returns_success(
        self, global_admin_client, db, global_admin_role
    ):
        """Admin users should be able to access user management."""
        response = global_admin_client.get('/admin-panel/users')

        # Should succeed with 200
        assert response.status_code == 200

    def test_when_admin_accesses_match_operations_then_returns_success(
        self, global_admin_client, db, global_admin_role
    ):
        """Admin users should be able to access match operations."""
        response = global_admin_client.get('/admin-panel/match-operations/teams')

        assert response.status_code == 200


# =============================================================================
# AUDIT LOGGING BEHAVIORS
# =============================================================================

class TestAuditLoggingBehaviors:
    """Test that admin actions are properly logged."""

    def test_when_team_is_renamed_then_audit_log_captures_change(
        self, global_admin_client, db, global_admin_user, team
    ):
        """When a team is renamed, audit log should capture old and new values."""
        # Refresh objects to ensure they are attached to session
        if global_admin_user not in db.session:
            global_admin_user = db.session.merge(global_admin_user)
        if team not in db.session:
            team = db.session.merge(team)
            
        old_name = team.name
        new_name = 'Renamed Team'
        admin_id = global_admin_user.id

        initial_logs = db.session.query(AdminAuditLog).filter_by(
            resource_type='match_operations',
            action='rename_team'
        ).all()

        with patch('app.admin_panel.routes.match_operations.ajax.update_team_discord_resources_task'):
            global_admin_client.post(
                '/admin-panel/match-operations/teams/rename',
                data={
                    'team_id': team.id,
                    'new_name': new_name
                }
            )

        db.session.expire_all()

        audit_log = db.session.query(AdminAuditLog).filter_by(
            resource_type='match_operations',
            action='rename_team',
            resource_id=str(team.id)
        ).order_by(AdminAuditLog.timestamp.desc()).first()

        assert audit_log is not None
        assert audit_log.old_value == old_name
        assert audit_log.new_value == new_name
        assert audit_log.user_id == admin_id

    def test_when_season_is_set_current_then_audit_log_is_created(
        self, global_admin_client, db, global_admin_user
    ):
        """When a season is set as current, audit log should be created."""
        if global_admin_user not in db.session:
            global_admin_user = db.session.merge(global_admin_user)
            
        admin_id = global_admin_user.id
        
        test_season = Season(
            name='Audit Season',
            league_type='CLASSIC',
            is_current=False
        )
        db.session.add(test_season)
        db.session.commit()

        global_admin_client.post(
            '/admin-panel/match-operations/season/set-current',
            data={'season_id': test_season.id}
        )

        db.session.expire_all()

        audit_log = db.session.query(AdminAuditLog).filter_by(
            action='set_current_season',
            resource_id=str(test_season.id)
        ).first()

        assert audit_log is not None
        assert audit_log.user_id == admin_id


# =============================================================================
# USER DETAILS BEHAVIORS
# =============================================================================

class TestUserDetailsBehaviors:
    """Test behaviors around fetching user details."""

    def test_when_admin_gets_user_details_then_returns_user_info(
        self, global_admin_client, db, global_admin_role, user
    ):
        """When admin requests user details, system returns user information."""
        response = global_admin_client.get(
            f'/admin-panel/api/users/{user.id}/details'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['user']['id'] == user.id
        assert data['user']['username'] == user.username

    def test_when_admin_gets_nonexistent_user_details_then_returns_404(
        self, global_admin_client, db, global_admin_role
    ):
        """When admin requests details for non-existent user, returns 404."""
        response = global_admin_client.get('/admin-panel/api/users/99999/details')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
