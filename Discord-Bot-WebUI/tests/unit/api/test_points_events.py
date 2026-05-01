"""
Mobile API points-events endpoint tests.

Covers:
- Event-types CRUD: list, create, name collision, get, update, archive.
- Award scan: success, unknown_member, type_archived, debounce.
- Award audit log: pagination + ordering.
- /me/points: own balance, strips audit metadata, 404 if no player.

JWT identity is set via flask_jwt_extended's create_access_token. Admin role
is granted by attaching a 'Pub League Admin' Role to the user. The Redis
client used by the debounce path is patched per-test via
app.mobile_api.points_events.get_safe_redis.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from flask_jwt_extended import create_access_token

from tests.factories import UserFactory, PlayerFactory


# ---------------------------------------------------------------------------
# Helpers / fixtures local to this file
# ---------------------------------------------------------------------------

def _grant_role(db, user, role_name: str):
    """Attach a named Role (creating it if needed) to a user."""
    from app.models import Role
    role = db.session.query(Role).filter_by(name=role_name).first()
    if not role:
        role = Role(name=role_name, description=role_name)
        db.session.add(role)
        db.session.flush()
    if role not in user.roles:
        user.roles.append(role)
    db.session.flush()
    return role


def _bearer(user_id) -> dict:
    token = create_access_token(identity=str(user_id))
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def admin_jwt_user(db):
    """User with Pub League Admin role; returns the user."""
    user = UserFactory(username='points_admin')
    _grant_role(db, user, 'Pub League Admin')
    db.session.commit()
    return user


@pytest.fixture
def regular_jwt_user(db):
    """User with no admin roles."""
    user = UserFactory(username='points_regular')
    db.session.commit()
    return user


@pytest.fixture
def make_event_type(db):
    """Factory function: create a PointsEventType with the given fields."""
    from app.models import PointsEventType

    def _make(*, name='Field Setup Help', default_points=5, description=None,
              is_archived=False, created_by_user_id=None):
        if created_by_user_id is None:
            u = UserFactory(username=f'creator_{name.lower().replace(" ", "_")}')
            db.session.flush()
            created_by_user_id = u.id
        t = PointsEventType(
            name=name,
            default_points=default_points,
            description=description,
            is_archived=is_archived,
            created_by_user_id=created_by_user_id,
        )
        db.session.add(t)
        db.session.flush()
        return t
    return _make


@pytest.fixture
def fake_safe_redis():
    """Patch get_safe_redis() to return a controllable MagicMock.

    Default: set(...) returns True (lock acquired), get(...) returns None.
    Tests override per case.
    """
    fake = MagicMock()
    fake.set.return_value = True
    fake.get.return_value = None
    with patch('app.mobile_api.points_events.get_safe_redis', return_value=fake):
        yield fake


# ---------------------------------------------------------------------------
# Event types CRUD
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.api
class TestEventTypesCRUD:

    def test_list_requires_jwt(self, client, app, db):
        with app.app_context():
            response = client.get('/api/v1/admin/events/types')
            assert response.status_code in (401, 422)

    def test_list_rejects_non_admin(self, client, app, db, regular_jwt_user):
        with app.app_context():
            r = client.get(
                '/api/v1/admin/events/types',
                headers=_bearer(regular_jwt_user.id),
            )
            assert r.status_code == 403

    def test_list_returns_active_only_by_default(
        self, client, app, db, admin_jwt_user, make_event_type
    ):
        with app.app_context():
            make_event_type(name='Field Setup Help')
            make_event_type(name='Old Type', is_archived=True)
            db.session.commit()

            r = client.get(
                '/api/v1/admin/events/types',
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            data = r.get_json()
            names = [t['name'] for t in data['types']]
            assert 'Field Setup Help' in names
            assert 'Old Type' not in names

    def test_list_includes_archived_when_requested(
        self, client, app, db, admin_jwt_user, make_event_type
    ):
        with app.app_context():
            make_event_type(name='Old Type', is_archived=True)
            db.session.commit()
            r = client.get(
                '/api/v1/admin/events/types?include_archived=true',
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            names = [t['name'] for t in r.get_json()['types']]
            assert 'Old Type' in names

    def test_create_happy_path(self, client, app, db, admin_jwt_user):
        with app.app_context():
            r = client.post(
                '/api/v1/admin/events/types',
                json={
                    'name': 'Field Setup Help',
                    'description': 'Volunteers who set up the pitch.',
                    'default_points': 5,
                },
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 201
            data = r.get_json()
            assert data['name'] == 'Field Setup Help'
            assert data['default_points'] == 5
            assert data['is_archived'] is False
            assert 'id' in data

    def test_create_rejects_duplicate_name_case_insensitive(
        self, client, app, db, admin_jwt_user, make_event_type
    ):
        with app.app_context():
            make_event_type(name='Field Setup Help')
            db.session.commit()
            r = client.post(
                '/api/v1/admin/events/types',
                json={'name': 'field setup help', 'default_points': 5},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 409

    def test_create_rejects_invalid_points(self, client, app, db, admin_jwt_user):
        with app.app_context():
            r = client.post(
                '/api/v1/admin/events/types',
                json={'name': 'X', 'default_points': 0},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 400

            r2 = client.post(
                '/api/v1/admin/events/types',
                json={'name': 'X', 'default_points': 999999},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r2.status_code == 400

    def test_create_rejects_long_name(self, client, app, db, admin_jwt_user):
        with app.app_context():
            r = client.post(
                '/api/v1/admin/events/types',
                json={'name': 'x' * 61, 'default_points': 5},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 400

    def test_get_one_returns_type(
        self, client, app, db, admin_jwt_user, make_event_type
    ):
        with app.app_context():
            t = make_event_type(name='Field Setup Help')
            db.session.commit()
            r = client.get(
                f'/api/v1/admin/events/types/{t.id}',
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            assert r.get_json()['id'] == t.id

    def test_get_one_404(self, client, app, db, admin_jwt_user):
        with app.app_context():
            r = client.get(
                '/api/v1/admin/events/types/99999',
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 404

    def test_update_partial(
        self, client, app, db, admin_jwt_user, make_event_type
    ):
        with app.app_context():
            t = make_event_type(name='Old', default_points=5)
            db.session.commit()
            r = client.put(
                f'/api/v1/admin/events/types/{t.id}',
                json={'default_points': 10},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            assert r.get_json()['default_points'] == 10
            assert r.get_json()['name'] == 'Old'

    def test_update_can_restore_archived(
        self, client, app, db, admin_jwt_user, make_event_type
    ):
        with app.app_context():
            t = make_event_type(name='Old', is_archived=True)
            db.session.commit()
            r = client.put(
                f'/api/v1/admin/events/types/{t.id}',
                json={'is_archived': False},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            assert r.get_json()['is_archived'] is False

    def test_archive_soft_deletes(
        self, client, app, db, admin_jwt_user, make_event_type
    ):
        with app.app_context():
            t = make_event_type(name='Bye')
            db.session.commit()
            r = client.delete(
                f'/api/v1/admin/events/types/{t.id}',
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200

            from app.models import PointsEventType
            db.session.expire_all()
            refreshed = db.session.query(PointsEventType).get(t.id)
            assert refreshed.is_archived is True


# ---------------------------------------------------------------------------
# Award scan
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.api
class TestAwardScan:

    def test_award_unknown_member_when_token_doesnt_resolve(
        self, client, app, db, admin_jwt_user, make_event_type, fake_safe_redis
    ):
        with app.app_context():
            t = make_event_type(name='Setup')
            db.session.commit()
            r = client.post(
                f'/api/v1/admin/events/types/{t.id}/award',
                json={'player_token': 'TOTALLY_BOGUS_TOKEN'},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            assert r.get_json()['status'] == 'unknown_member'

    def test_award_rejects_archived_type(
        self, client, app, db, admin_jwt_user, make_event_type, fake_safe_redis
    ):
        with app.app_context():
            t = make_event_type(name='Old', is_archived=True)
            db.session.commit()
            r = client.post(
                f'/api/v1/admin/events/types/{t.id}/award',
                json={'player_token': '12345'},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            assert r.get_json()['status'] == 'type_archived'

    def test_award_404_unknown_type(
        self, client, app, db, admin_jwt_user, fake_safe_redis
    ):
        with app.app_context():
            r = client.post(
                '/api/v1/admin/events/types/99999/award',
                json={'player_token': '12345'},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 404

    def test_award_success_with_player_id_token(
        self, client, app, db, admin_jwt_user, make_event_type, team,
        fake_safe_redis
    ):
        """resolve_player_id_or_token falls back to int Player.id on no
        WalletPass match — verify the success path with that fallback."""
        with app.app_context():
            t = make_event_type(name='Setup', default_points=5)
            target_user = UserFactory(username='target_player_user')
            target_player = PlayerFactory(
                name='Target Player', user=target_user, primary_team_id=team.id,
            )
            db.session.commit()

            r = client.post(
                f'/api/v1/admin/events/types/{t.id}/award',
                json={'player_token': str(target_player.id)},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            data = r.get_json()
            assert data['status'] == 'success'
            assert data['player_id'] == target_player.id
            assert data['points_awarded'] == 5
            assert data['new_total'] == 5
            assert data['match_id'] is None

    def test_award_uses_points_override(
        self, client, app, db, admin_jwt_user, make_event_type, team,
        fake_safe_redis
    ):
        with app.app_context():
            t = make_event_type(default_points=5)
            target_user = UserFactory(username='target_for_override')
            target_player = PlayerFactory(
                name='Override Target', user=target_user, primary_team_id=team.id,
            )
            db.session.commit()

            r = client.post(
                f'/api/v1/admin/events/types/{t.id}/award',
                json={
                    'player_token': str(target_player.id),
                    'points_override': 25,
                },
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            assert r.get_json()['points_awarded'] == 25

    def test_award_debounce_returns_already_awarded(
        self, client, app, db, admin_jwt_user, make_event_type, team,
        fake_safe_redis
    ):
        """When Redis SET NX returns False AND GET returns the prior award
        metadata, the endpoint returns 'already_awarded' with the stored
        award_id."""
        with app.app_context():
            t = make_event_type(default_points=5)
            target_user = UserFactory(username='dbnc_target')
            target_player = PlayerFactory(
                name='Debounce Target', user=target_user, primary_team_id=team.id,
            )
            db.session.commit()

            fake_safe_redis.set.return_value = False
            fake_safe_redis.get.return_value = json.dumps({
                'award_id': 12345, 'points_awarded': 5,
            })

            r = client.post(
                f'/api/v1/admin/events/types/{t.id}/award',
                json={'player_token': str(target_player.id)},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            data = r.get_json()
            assert data['status'] == 'already_awarded'
            assert data['award_id'] == 12345

    def test_award_redis_down_fails_open(
        self, client, app, db, admin_jwt_user, make_event_type, team,
        fake_safe_redis
    ):
        """Redis SET returns False AND GET returns None → fail open and
        proceed with the insert."""
        with app.app_context():
            t = make_event_type(default_points=7)
            target_user = UserFactory(username='ro_target')
            target_player = PlayerFactory(
                name='Redis Out', user=target_user, primary_team_id=team.id,
            )
            db.session.commit()

            fake_safe_redis.set.return_value = False
            fake_safe_redis.get.return_value = None  # Redis appears down

            r = client.post(
                f'/api/v1/admin/events/types/{t.id}/award',
                json={'player_token': str(target_player.id)},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            assert r.get_json()['status'] == 'success'

    def test_award_validates_payload(
        self, client, app, db, admin_jwt_user, make_event_type, fake_safe_redis
    ):
        with app.app_context():
            t = make_event_type()
            db.session.commit()
            r = client.post(
                f'/api/v1/admin/events/types/{t.id}/award',
                json={},
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 400


# ---------------------------------------------------------------------------
# Award audit list
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.api
class TestAwardAudit:

    def test_audit_list_returns_awards(
        self, client, app, db, admin_jwt_user, make_event_type, team
    ):
        with app.app_context():
            from app.models import PointsEventAward
            t = make_event_type()
            target_user = UserFactory(username='audit_player_user')
            target_player = PlayerFactory(
                name='Audit Player', user=target_user, primary_team_id=team.id,
            )
            db.session.flush()
            for pts in (1, 2, 3):
                db.session.add(PointsEventAward(
                    event_type_id=t.id,
                    player_id=target_player.id,
                    points_awarded=pts,
                    recorded_by_user_id=admin_jwt_user.id,
                ))
            db.session.commit()

            r = client.get(
                f'/api/v1/admin/events/types/{t.id}/awards',
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            data = r.get_json()
            assert data['type_id'] == t.id
            assert data['total_awards'] == 3
            assert len(data['awards']) == 3
            assert data['awards'][0]['player_id'] == target_player.id

    def test_audit_list_404_unknown_type(self, client, app, db, admin_jwt_user):
        with app.app_context():
            r = client.get(
                '/api/v1/admin/events/types/99999/awards',
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 404


# ---------------------------------------------------------------------------
# /me/points
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.api
class TestMyPoints:

    def test_404_when_no_player(self, client, app, db, regular_jwt_user):
        with app.app_context():
            r = client.get('/api/v1/me/points', headers=_bearer(regular_jwt_user.id))
            assert r.status_code == 404

    def test_returns_balance_for_self(
        self, client, app, db, admin_jwt_user, make_event_type, team
    ):
        with app.app_context():
            from app.models import PointsEventAward
            t = make_event_type()
            self_user = UserFactory(username='self_balance')
            self_player = PlayerFactory(
                name='Self', user=self_user, primary_team_id=team.id,
            )
            db.session.flush()

            db.session.add(PointsEventAward(
                event_type_id=t.id,
                player_id=self_player.id,
                points_awarded=8,
                recorded_by_user_id=admin_jwt_user.id,
                note='private admin note',
            ))
            db.session.commit()

            r = client.get(
                '/api/v1/me/points', headers=_bearer(self_user.id)
            )
            assert r.status_code == 200
            data = r.get_json()
            assert data['player_id'] == self_player.id
            assert data['total_points'] == 8
            assert len(data['awards']) == 1
            entry = data['awards'][0]

            # Audit metadata MUST be stripped on /me/points.
            assert 'award_id' not in entry
            assert 'note' not in entry
            assert 'recorded_by_user_id' not in entry
            # Visible fields are present.
            assert entry['type_name'] == t.name
            assert entry['points_awarded'] == 8


# ---------------------------------------------------------------------------
# Admin player view
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.api
class TestAdminPlayerView:

    def test_admin_view_includes_audit_metadata(
        self, client, app, db, admin_jwt_user, make_event_type, team
    ):
        with app.app_context():
            from app.models import PointsEventAward
            t = make_event_type()
            target_user = UserFactory(username='adminviewtarget')
            target_player = PlayerFactory(
                name='AdminView Target', user=target_user,
                primary_team_id=team.id,
            )
            db.session.flush()
            db.session.add(PointsEventAward(
                event_type_id=t.id,
                player_id=target_player.id,
                points_awarded=12,
                recorded_by_user_id=admin_jwt_user.id,
                note='private admin note',
            ))
            db.session.commit()

            r = client.get(
                f'/api/v1/admin/players/{target_player.id}/points',
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 200
            data = r.get_json()
            assert data['total_points'] == 12
            entry = data['awards'][0]
            # Admin view INCLUDES audit metadata.
            assert 'award_id' in entry
            assert entry['note'] == 'private admin note'

    def test_admin_view_404_unknown_player(self, client, app, db, admin_jwt_user):
        with app.app_context():
            r = client.get(
                '/api/v1/admin/players/99999/points',
                headers=_bearer(admin_jwt_user.id),
            )
            assert r.status_code == 404
