"""
Mobile contract tests for the member-lifecycle admin API
(/api/v1/admin/members/*, /api/v1/admin/quick-profiles/<id>/preapprove).

These endpoints are thin shells over app/services/member_lifecycle_service.py,
which the WEB member hub calls too — so a regression here is a regression on both
surfaces. Response shapes are the contract in docs/flutter/member-hub-admin-api.md.
"""
import pytest
from flask_jwt_extended import create_access_token

from app.models import Role, User
from app.models.substitutes import SubstitutePool
from tests.factories import LeagueFactory, PlayerFactory, SeasonFactory, TeamFactory, UserFactory


ROLE_NAMES = (
    'Global Admin', 'Pub League Admin',
    'pl-unverified', 'pl-waitlist', 'pl-classic', 'pl-premier', 'pl-ecs-fc',
    'Classic Sub', 'Premier Sub', 'ECS FC Sub',
)


def _role(session, name):
    role = session.query(Role).filter_by(name=name).first()
    if role is None:
        role = Role(name=name)
        session.add(role)
        session.flush()
    return role


@pytest.fixture
def roles(db):
    return {n: _role(db.session, n) for n in ROLE_NAMES}


@pytest.fixture
def leagues(db):
    """A current Pub League season with Classic + Premier divisions."""
    season = SeasonFactory(league_type='Pub League', is_current=True)
    classic = LeagueFactory(name='Classic', season=season)
    premier = LeagueFactory(name='Premier', season=season)
    db.session.flush()
    return {'season': season, 'classic': classic, 'premier': premier}


@pytest.fixture
def admin(db, roles):
    u = UserFactory()
    u.roles.append(roles['Global Admin'])
    db.session.flush()
    return u


def _auth(app, user):
    with app.app_context():
        token = create_access_token(identity=str(user.id),
                                    additional_claims={'approved': True})
    return {'Authorization': f'Bearer {token}'}


def _pending(db, roles, **kw):
    """A pending applicant with a player record."""
    u = UserFactory(is_approved=False, approval_status='pending', **kw)
    u.roles.append(roles['pl-unverified'])
    PlayerFactory(user=u)
    db.session.flush()
    return u


def _reload(db, user_id):
    db.session.expire_all()
    return db.session.query(User).get(user_id)


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------

class TestAuthGate:
    def test_non_admin_is_refused(self, client, db, app, roles):
        plain = UserFactory()
        db.session.flush()
        db.session.commit()
        r = client.post(f'/api/v1/admin/members/{plain.id}/approve',
                        json={'league_type': 'classic'}, headers=_auth(app, plain))
        assert r.status_code == 403

    def test_missing_jwt_is_401(self, client, db):
        r = client.get('/api/v1/admin/members')
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# hostile input (adversarial review, 2026-08-02)
# ---------------------------------------------------------------------------

class TestHostileInput:
    """A malformed body must produce a 400, never a 500.

    Every one of these was a real 500 found by red-teaming: the handlers did
    `(value or '').strip()` on JSON that can legitimately carry a list or a dict.
    """

    @pytest.mark.parametrize('junk', [['classic'], {'x': 1}, True])
    def test_non_string_league_type_is_400(self, client, db, app, admin, roles, leagues, junk):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        h = _auth(app, admin)
        for path in ('approve', 'sub-assign', 'sub-remove', 'sub-active'):
            r = client.post(f'/api/v1/admin/members/{uid}/{path}',
                            json={'league_type': junk}, headers=h)
            assert r.status_code == 400, f'{path} with {junk!r} -> {r.status_code}'
        # nothing was written
        after = _reload(db, uid)
        assert after.approval_status == 'pending'

    def test_non_string_notes_and_action_are_rejected_not_crashed(
            self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        h = _auth(app, admin)

        # notes is free text — a malformed one is dropped, the action still works
        r = client.post(f'/api/v1/admin/members/{uid}/deny',
                        json={'notes': ['a', 'b']}, headers=h)
        assert r.status_code == 200, r.get_json()
        assert _reload(db, uid).approval_status == 'denied'

        # action selects a MUTATION, so a malformed one must 400, never fall
        # back to the default 'add'
        r = client.post(f'/api/v1/admin/members/{uid}/place',
                        json={'action': ['add'], 'team_id': 1}, headers=h)
        assert r.status_code == 400
        assert 'Invalid action' in r.get_json()['message']

    def test_non_string_preapprove_does_not_silently_clear(
            self, client, db, app, admin, roles, leagues):
        """'' clears a pre-approval — a list must not collapse into that."""
        from datetime import datetime, timedelta
        from app.models import QuickProfile
        qp = QuickProfile(player_name='Walk In', created_by_user_id=admin.id,
                          claim_code=QuickProfile.generate_claim_code(),
                          expires_at=datetime.utcnow() + timedelta(days=30),
                          pre_approved_league='premier')
        db.session.add(qp)
        db.session.flush()
        qid = qp.id
        db.session.commit()

        r = client.post(f'/api/v1/admin/quick-profiles/{qid}/preapprove',
                        json={'league_type': {'x': 1}}, headers=_auth(app, admin))
        assert r.status_code == 400
        db.session.expire_all()
        assert db.session.get(QuickProfile, qid).pre_approved_league == 'premier'


class TestUnknownMemberIsNotFound:
    """404, not 500 — a client must be able to tell a stale id from a broken server."""

    @pytest.mark.parametrize('method,path,body', [
        ('post', 'activate', None),
        ('post', 'deactivate', {}),
        ('post', 'approve', {'league_type': 'classic'}),
        ('post', 'deny', {}),
        ('post', 'undeny', {}),
        ('post', 'place', {'action': 'add', 'team_id': 1}),
        ('delete', 'waitlist', {}),
    ])
    def test_unknown_user_id(self, client, db, app, admin, roles, leagues, method, path, body):
        db.session.commit()
        r = client.open(f'/api/v1/admin/members/98765432/{path}',
                        method=method.upper(), json=body, headers=_auth(app, admin))
        assert r.status_code == 404, f'{path} -> {r.status_code} {r.get_data(as_text=True)[:200]}'
        assert r.get_json()['success'] is False


# ---------------------------------------------------------------------------
# §3 vocabularies
# ---------------------------------------------------------------------------

class TestOptions:
    def test_shape(self, client, db, app, admin, leagues):
        db.session.commit()
        r = client.get('/api/v1/admin/members/options', headers=_auth(app, admin))
        assert r.status_code == 200
        body = r.get_json()
        assert body['success'] is True
        # approve vocabularies are registry-driven, and the three genuinely differ
        assert 'classic' in body['approve']['league']
        assert 'sub-classic' in body['approve']['sub']
        assert 'waitlist-classic' in body['approve']['waitlist']
        assert any(p['value'] == 'classic' for p in body['approve']['programs'])
        # sub lanes report EVERY accepted spelling
        ecs = next(l for l in body['sub_lanes'] if l['lane'] == 'ecs_fc')
        assert set(ecs['accepts']) >= {'ECS FC', 'ecs_fc', 'ecs-fc'}
        # priority is a vocabulary, not a rank number
        assert body['waitlist_priorities'] == ['high', 'medium', 'normal', 'auto']
        assert body['worklist']['per_page_cap'] == 100

    def test_advertised_sub_spellings_all_round_trip(
            self, client, db, app, admin, roles, leagues):
        """Every spelling in accepts must actually be accepted by the endpoints.

        An options endpoint that advertises a value the validator rejects is
        worse than no options endpoint.
        """
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        h = _auth(app, admin)
        opts = client.get('/api/v1/admin/members/options', headers=h).get_json()

        for entry in opts['sub_lanes']:
            for spelling in entry['accepts']:
                r = client.post(f'/api/v1/admin/members/{uid}/sub-assign',
                                json={'league_type': spelling}, headers=h)
                assert r.status_code == 200, f'{spelling!r} -> {r.status_code}'
                assert r.get_json()['lane'] == entry['lane']
                client.post(f'/api/v1/admin/members/{uid}/sub-remove',
                            json={'league_type': spelling}, headers=h)

    def test_worklist_filter_vocabularies_are_published(
            self, client, db, app, admin, roles, leagues):
        """The worklist filters are closed sets that nothing validates — a wrong
        value is silently "no filter" or silently "no rows", never a 400. So the
        spellings have to be discoverable or a client is guessing."""
        db.session.commit()
        f = client.get('/api/v1/admin/members/options',
                       headers=_auth(app, admin)).get_json()['worklist']['filters']
        assert f['approval'] == ['approved', 'pending', 'denied', 'all']
        assert f['active'] == ['true', 'false']
        assert f['season'] == ['active', 'inactive']
        assert f['sub_status'] == ['active', 'resting']
        assert 'all' in f['qp_status'] and 'pending' in f['qp_status']
        # lane= takes UNDERSCORE lanes here, not the sub-mutation aliases
        assert 'ecs_fc' in f['lane'] and 'undecided' in f['lane']
        assert 'ECS FC' not in f['lane'] and 'ecs-fc' not in f['lane']


# ---------------------------------------------------------------------------
# §1.1 approval lifecycle
# ---------------------------------------------------------------------------

class TestApprovalLifecycle:
    def test_approve_grants_role_and_clears_waitlist(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        u.waitlist_league = 'classic'
        from datetime import datetime
        u.waitlist_joined_at = datetime.utcnow()
        u.roles.append(roles['pl-waitlist'])
        uid = u.id
        db.session.commit()

        r = client.post(f'/api/v1/admin/members/{uid}/approve',
                        json={'league_type': 'classic', 'notes': 'ok'},
                        headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body['success'] is True
        assert body['waitlisted'] is False
        assert body['league_type'] == 'classic'
        assert 'discord_sync_queued' in body

        after = _reload(db, uid)
        assert after.approval_status == 'approved'
        assert after.is_approved is True
        assert after.approval_league == 'classic'
        names = {r.name for r in after.roles}
        assert 'pl-classic' in names
        assert 'pl-unverified' not in names
        assert 'pl-waitlist' not in names
        # approval is a spot — the holding lane must be cleared
        assert after.waitlist_joined_at is None
        assert after.waitlist_league is None

    def test_approve_rejects_unknown_league_and_names_the_valid_set(
            self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        r = client.post(f'/api/v1/admin/members/{uid}/approve',
                        json={'league_type': 'not-a-program'}, headers=_auth(app, admin))
        assert r.status_code == 400
        body = r.get_json()
        assert body['success'] is False
        assert 'classic' in body['valid_league_types']

    def test_waitlist_outcome_parks_without_approving(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        r = client.post(f'/api/v1/admin/members/{uid}/approve',
                        json={'league_type': 'waitlist-classic'}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['waitlisted'] is True

        after = _reload(db, uid)
        # Deliberately still 'pending' — the whole waitlist system keys off the ROLE.
        assert after.approval_status == 'pending'
        assert after.is_approved is False
        assert 'pl-waitlist' in {x.name for x in after.roles}
        assert after.waitlist_joined_at is not None

    def test_deny_then_undeny_returns_to_queue(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()

        r = client.post(f'/api/v1/admin/members/{uid}/deny',
                        json={'notes': 'no thanks'}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        after = _reload(db, uid)
        assert after.approval_status == 'denied'
        # denial must actually block access, not just relabel
        assert after.is_approved is False

        r = client.post(f'/api/v1/admin/members/{uid}/undeny',
                        json={'notes': 'my mistake'}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        after = _reload(db, uid)
        assert after.approval_status == 'pending'
        assert after.is_approved is False          # undeny is NOT an approval
        assert after.approval_league is None
        assert 'pl-unverified' in {x.name for x in after.roles}
        assert 'no thanks' in (after.approval_notes or '') or 'Denial reversed' in (after.approval_notes or '')

    def test_deny_requires_pending(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        u.approval_status = 'approved'
        u.is_approved = True
        uid = u.id
        db.session.commit()
        r = client.post(f'/api/v1/admin/members/{uid}/deny', json={}, headers=_auth(app, admin))
        assert r.status_code == 400

    def test_approve_can_reverse_a_denial(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        client.post(f'/api/v1/admin/members/{uid}/deny', json={}, headers=_auth(app, admin))
        r = client.post(f'/api/v1/admin/members/{uid}/approve',
                        json={'league_type': 'classic'}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        assert _reload(db, uid).approval_status == 'approved'


# ---------------------------------------------------------------------------
# §1.2 activation
# ---------------------------------------------------------------------------

class TestActivation:
    def test_deactivate_then_activate(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()

        r = client.post(f'/api/v1/admin/members/{uid}/deactivate',
                        json={'reason': 'moved away'}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['is_active'] is False
        after = _reload(db, uid)
        assert after.is_active is False
        assert after.player.is_current_player is False

        r = client.post(f'/api/v1/admin/members/{uid}/activate', headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        after = _reload(db, uid)
        assert after.is_active is True
        assert after.player.is_current_player is True


# ---------------------------------------------------------------------------
# §1.3 placement
# ---------------------------------------------------------------------------

class TestPlacement:
    def test_add_primary_remove(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        team = TeamFactory(name='Buzzards', league=leagues['classic'])
        other = TeamFactory(name='Ravens', league=leagues['classic'])
        db.session.flush()
        tid, oid = team.id, other.id
        db.session.commit()

        r = client.post(f'/api/v1/admin/members/{uid}/place',
                        json={'action': 'add', 'team_id': tid, 'is_coach': True},
                        headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        after = _reload(db, uid)
        assert tid in [t.id for t in after.player.teams]
        assert after.player.primary_team_id == tid

        # double-rostering the same non-ECS-FC league is blocked
        r = client.post(f'/api/v1/admin/members/{uid}/place',
                        json={'action': 'add', 'team_id': oid}, headers=_auth(app, admin))
        assert r.status_code == 400
        assert 'already on' in r.get_json()['message']

        r = client.post(f'/api/v1/admin/members/{uid}/place',
                        json={'action': 'remove', 'team_id': tid}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        after = _reload(db, uid)
        assert tid not in [t.id for t in after.player.teams]
        assert after.player.primary_team_id is None

    def test_primary_requires_being_rostered(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        team = TeamFactory(name='Kestrels', league=leagues['classic'])
        db.session.flush()
        tid = team.id
        db.session.commit()
        r = client.post(f'/api/v1/admin/members/{uid}/place',
                        json={'action': 'primary', 'team_id': tid}, headers=_auth(app, admin))
        assert r.status_code == 400
        assert 'place them there first' in r.get_json()['message']

    def test_bad_payloads(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        h = _auth(app, admin)
        assert client.post(f'/api/v1/admin/members/{uid}/place',
                           json={'action': 'teleport', 'team_id': 1}, headers=h).status_code == 400
        assert client.post(f'/api/v1/admin/members/{uid}/place',
                           json={'action': 'add'}, headers=h).status_code == 400
        assert client.post(f'/api/v1/admin/members/{uid}/place',
                           json={'action': 'add', 'team_id': 999999}, headers=h).status_code == 404


# ---------------------------------------------------------------------------
# §1.4 substitute pools
# ---------------------------------------------------------------------------

class TestSubPools:
    @pytest.mark.parametrize('spelling', ['Classic', 'classic'])
    def test_assign_accepts_label_and_lane(self, client, db, app, admin, roles, leagues, spelling):
        u = _pending(db, roles)
        uid, pid = u.id, u.player.id
        db.session.commit()

        r = client.post(f'/api/v1/admin/members/{uid}/sub-assign',
                        json={'league_type': spelling, 'active': True},
                        headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body['lane'] == 'classic'
        # always normalised to the League display name actually stored in the pool
        assert body['league_type'] == 'Classic'

        db.session.expire_all()
        row = db.session.query(SubstitutePool).filter_by(player_id=pid).one()
        assert row.league_type == 'Classic'
        assert row.is_active is True
        assert row.approved_at is not None
        assert 'Classic Sub' in {x.name for x in _reload(db, uid).roles}

    def test_rest_wake_and_remove(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid, pid = u.id, u.player.id
        db.session.commit()
        h = _auth(app, admin)

        client.post(f'/api/v1/admin/members/{uid}/sub-assign',
                    json={'league_type': 'premier'}, headers=h)

        r = client.post(f'/api/v1/admin/members/{uid}/sub-active',
                        json={'league_type': 'premier', 'active': False}, headers=h)
        assert r.status_code == 200, r.get_json()
        db.session.expire_all()
        assert db.session.query(SubstitutePool).filter_by(player_id=pid).one().is_active is False

        r = client.post(f'/api/v1/admin/members/{uid}/sub-remove',
                        json={'league_type': 'premier'}, headers=h)
        assert r.status_code == 200, r.get_json()
        db.session.expire_all()
        assert db.session.query(SubstitutePool).filter_by(player_id=pid).first() is None
        assert 'Premier Sub' not in {x.name for x in _reload(db, uid).roles}

    def test_form_encoded_false_means_false(self, client, db, app, admin, roles, leagues):
        """A form body carries strings, and bool('false') is True.

        Uncoerced, `active=false` would have WOKEN a resting sub and
        `is_coach=false` would have made someone a coach.
        """
        u = _pending(db, roles)
        uid, pid = u.id, u.player.id
        db.session.commit()
        h = _auth(app, admin)

        client.post(f'/api/v1/admin/members/{uid}/sub-assign',
                    json={'league_type': 'classic'}, headers=h)
        r = client.post(f'/api/v1/admin/members/{uid}/sub-active',
                        data={'league_type': 'classic', 'active': 'false'}, headers=h)
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['active'] is False
        db.session.expire_all()
        assert db.session.query(SubstitutePool).filter_by(player_id=pid).one().is_active is False

        team = TeamFactory(name='Falcons', league=leagues['classic'])
        db.session.flush()
        tid = team.id
        db.session.commit()
        r = client.post(f'/api/v1/admin/members/{uid}/place',
                        data={'action': 'add', 'team_id': str(tid), 'is_coach': 'false'},
                        headers=h)
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['is_coach'] is False

    def test_set_active_on_a_lane_they_are_not_in_is_404(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        r = client.post(f'/api/v1/admin/members/{uid}/sub-active',
                        json={'league_type': 'classic', 'active': False},
                        headers=_auth(app, admin))
        assert r.status_code == 404

    def test_reject_only_touches_pending_signups(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid, pid = u.id, u.player.id
        # a PENDING self-signup: approved_at IS NULL
        db.session.add(SubstitutePool(player_id=pid, league_type='Classic',
                                      is_active=True, approved_at=None))
        db.session.commit()
        h = _auth(app, admin)

        r = client.post(f'/api/v1/admin/members/{uid}/sub-reject',
                        json={'league_type': 'classic'}, headers=h)
        assert r.status_code == 200, r.get_json()
        db.session.expire_all()
        assert db.session.query(SubstitutePool).filter_by(player_id=pid).first() is None

        # nothing pending left -> 404, and an APPROVED row is never touched by reject
        client.post(f'/api/v1/admin/members/{uid}/sub-assign',
                    json={'league_type': 'classic'}, headers=h)
        r = client.post(f'/api/v1/admin/members/{uid}/sub-reject',
                        json={'league_type': 'classic'}, headers=h)
        assert r.status_code == 404
        db.session.expire_all()
        assert db.session.query(SubstitutePool).filter_by(player_id=pid).first() is not None

    def test_reject_does_not_delete_a_neighbouring_programs_signup(
            self, client, db, app, admin, roles, leagues):
        """Rejecting one lane must not take an unrelated pending row with it.

        _norm_league_type is substring-tolerant, so a 'Premier Reserve' row from
        a program the registry cannot resolve normalised to 'premier' and was
        deleted by a plain `sub-reject {"league_type": "premier"}` — while the
        response named only 'Premier'.
        """
        u = _pending(db, roles)
        uid, pid = u.id, u.player.id
        db.session.add(SubstitutePool(player_id=pid, league_type='Premier',
                                      is_active=True, approved_at=None))
        db.session.add(SubstitutePool(player_id=pid, league_type='Premier Reserve',
                                      is_active=True, approved_at=None))
        db.session.commit()

        r = client.post(f'/api/v1/admin/members/{uid}/sub-reject',
                        json={'league_type': 'premier'}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['rejected'] == 1

        db.session.expire_all()
        left = {row.league_type for row in
                db.session.query(SubstitutePool).filter_by(player_id=pid).all()}
        assert left == {'Premier Reserve'}

    def test_reject_does_not_strip_a_role_an_approved_row_still_earns(
            self, client, db, app, admin, roles, leagues):
        """"Pending-only" must describe the SIDE EFFECTS, not just the SELECT.

        A player can hold an approved 'Classic' row AND a pending 'classic' one
        — /substitutes/pool/join stores league_type verbatim and matches by
        exact string, so the two coexist under uq(player_id, league_type).
        Rejecting the pending one used to strip the Classic Sub role outright,
        costing them the role their APPROVED membership still earns (and the
        Discord -SUB role with it, via the queued reconcile).
        """
        from datetime import datetime
        u = _pending(db, roles)
        uid, pid = u.id, u.player.id
        db.session.add(SubstitutePool(player_id=pid, league_type='Classic',
                                      is_active=True, approved_at=datetime.utcnow(),
                                      approved_by=admin.id))
        db.session.add(SubstitutePool(player_id=pid, league_type='classic',
                                      is_active=True, approved_at=None))
        u.roles.append(roles['Classic Sub'])
        db.session.commit()

        r = client.post(f'/api/v1/admin/members/{uid}/sub-reject',
                        json={'league_type': 'classic'}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()

        db.session.expire_all()
        after = _reload(db, uid)
        left = db.session.query(SubstitutePool).filter_by(player_id=pid).all()
        assert [(x.league_type, x.approved_at is not None) for x in left] == [('Classic', True)]
        assert 'Classic Sub' in {x.name for x in after.roles}
        assert after.player.is_sub is True

    def test_reject_still_reaches_a_drifted_stored_value(
            self, client, db, app, admin, roles, leagues):
        """The normalized fallback is what makes a non-canonical row rejectable."""
        u = _pending(db, roles)
        uid, pid = u.id, u.player.id
        db.session.add(SubstitutePool(player_id=pid, league_type='pub_league_classic',
                                      is_active=True, approved_at=None))
        db.session.commit()

        r = client.post(f'/api/v1/admin/members/{uid}/sub-reject',
                        json={'league_type': 'classic'}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        db.session.expire_all()
        assert db.session.query(SubstitutePool).filter_by(player_id=pid).first() is None

    def test_unknown_lane_is_400_with_the_valid_set(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        r = client.post(f'/api/v1/admin/members/{uid}/sub-assign',
                        json={'league_type': 'nonsense'}, headers=_auth(app, admin))
        assert r.status_code == 400
        assert any(o['lane'] == 'classic' for o in r.get_json()['valid'])

    @pytest.mark.parametrize('typo', ['specs', 'ecs fc league', 'classical', 'Premier League'])
    def test_lane_matching_is_exact_not_substring(self, client, db, app, admin,
                                                  roles, leagues, typo):
        """A near-miss must 400, not silently mutate a neighbouring pool.

        league_membership_sync._norm_league_type is a SUBSTRING matcher, right for
        reading drifted stored values and wrong for validating admin input --
        'specs' contains 'ecs'. Using it here would make a typo'd sub-remove delete
        the wrong pool row.
        """
        u = _pending(db, roles)
        uid, pid = u.id, u.player.id
        db.session.commit()
        h = _auth(app, admin)
        assert client.post(f'/api/v1/admin/members/{uid}/sub-assign',
                           json={'league_type': typo}, headers=h).status_code == 400
        assert client.post(f'/api/v1/admin/members/{uid}/sub-remove',
                           json={'league_type': typo}, headers=h).status_code == 400
        db.session.expire_all()
        assert db.session.query(SubstitutePool).filter_by(player_id=pid).first() is None


# ---------------------------------------------------------------------------
# §1.5 waitlist
# ---------------------------------------------------------------------------

class TestWaitlist:
    def test_priority_vocabulary(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        h = _auth(app, admin)

        r = client.post(f'/api/v1/admin/members/{uid}/waitlist/priority',
                        json={'priority': 'high'}, headers=h)
        assert r.status_code == 200, r.get_json()
        assert _reload(db, uid).waitlist_priority == 'high'

        # 'auto' means "no manual override" -> NULL
        r = client.post(f'/api/v1/admin/members/{uid}/waitlist/priority',
                        json={'priority': 'auto'}, headers=h)
        assert r.status_code == 200
        assert _reload(db, uid).waitlist_priority is None

        # the spec's {"priority": 1} is NOT valid — say so, with the real vocabulary
        r = client.post(f'/api/v1/admin/members/{uid}/waitlist/priority',
                        json={'priority': 1}, headers=h)
        assert r.status_code == 400
        assert r.get_json()['valid_priorities'] == ['high', 'medium', 'normal', 'auto']

    def test_explicitly_empty_priority_is_rejected_not_coerced(
            self, client, db, app, admin, roles, leagues):
        """Matches the web handler: only an ABSENT key defaults to 'auto'.

        Coercing a falsy value would silently clear a manual priority the admin
        never meant to touch.
        """
        u = _pending(db, roles)
        u.waitlist_priority = 'high'
        uid = u.id
        db.session.commit()
        h = _auth(app, admin)

        for bad in ('', None, 0):
            r = client.post(f'/api/v1/admin/members/{uid}/waitlist/priority',
                            json={'priority': bad}, headers=h)
            assert r.status_code == 400, f'{bad!r} should be rejected'
        assert _reload(db, uid).waitlist_priority == 'high'

        # an absent key still means "no manual priority"
        r = client.post(f'/api/v1/admin/members/{uid}/waitlist/priority',
                        json={}, headers=h)
        assert r.status_code == 200
        assert _reload(db, uid).waitlist_priority is None

    def test_remove_from_waitlist(self, client, db, app, admin, roles, leagues):
        from datetime import datetime
        u = _pending(db, roles)
        u.roles.append(roles['pl-waitlist'])
        u.waitlist_joined_at = datetime.utcnow()
        u.waitlist_league = 'classic'
        uid = u.id
        db.session.commit()

        r = client.delete(f'/api/v1/admin/members/{uid}/waitlist',
                          json={'reason': 'spot opened'}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        after = _reload(db, uid)
        names = {x.name for x in after.roles}
        assert 'pl-waitlist' not in names
        # not role-less: an unapproved leaver lands back as an ordinary pending user
        assert 'pl-unverified' in names
        assert after.waitlist_joined_at is None
        assert after.waitlist_league is None

    def test_remove_when_not_waitlisted_is_400(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        r = client.delete(f'/api/v1/admin/members/{uid}/waitlist',
                          json={}, headers=_auth(app, admin))
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# §1.7 worklist
# ---------------------------------------------------------------------------

class TestWorklist:
    def test_denied_hidden_by_default_but_counted(self, client, db, app, admin, roles, leagues):
        keep = _pending(db, roles)
        gone = _pending(db, roles)
        gone.approval_status = 'denied'
        gone.is_approved = False
        db.session.commit()
        h = _auth(app, admin)

        r = client.get('/api/v1/admin/members?tab=all&per_page=100', headers=h)
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        ids = {i['user_id'] for i in body['items']}
        assert keep.id in ids
        assert gone.id not in ids
        # the default must never hide people silently
        assert body['hidden_denied'] >= 1
        assert body['per_page_cap'] == 100

        r = client.get('/api/v1/admin/members?tab=all&approval=denied&per_page=100', headers=h)
        assert gone.id in {i['user_id'] for i in r.get_json()['items']}

    def test_pending_tab_and_counts(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        db.session.commit()
        r = client.get('/api/v1/admin/members?tab=pending', headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body['tab'] == 'pending'
        assert u.id in {i['user_id'] for i in body['items']}
        assert body['counts']['pending'] >= 1
        item = next(i for i in body['items'] if i['user_id'] == u.id)
        for field in ('username', 'player_id', 'name', 'approval_status', 'is_approved',
                      'is_active', 'roles', 'has_discord', 'teams', 'sub_lanes'):
            assert field in item

    def test_waitlist_lane_filter_works_for_a_newer_program(
            self, client, db, app, admin, roles, leagues):
        """A lane outside the original three must still narrow the list.

        The web page's hardcoded matcher returned None for these, which turned
        the filter into "no filter"; a naive replacement that strips separators
        ('pl_third' -> '%plthird%') is worse still — it matches nothing, so the
        program reads as empty.
        """
        from datetime import datetime
        third = _pending(db, roles)
        third.roles.append(roles['pl-waitlist'])
        third.waitlist_joined_at = datetime.utcnow()
        third.waitlist_league = 'pl-third'      # what waitlist_league_map() stores
        other = _pending(db, roles)
        other.roles.append(roles['pl-waitlist'])
        other.waitlist_joined_at = datetime.utcnow()
        other.waitlist_league = 'classic'
        db.session.commit()

        r = client.get('/api/v1/admin/members?tab=waitlist&lane=pl_third',
                       headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        ids = {i['user_id'] for i in r.get_json()['items']}
        assert third.id in ids
        assert other.id not in ids

    def test_unrecognised_lane_is_no_filter_not_no_rows(
            self, client, db, app, admin, roles, leagues):
        """Parity with the web page: an unknown lane must not empty the list.

        The hardcoded matcher this replaced returned None for anything outside
        classic/premier/ecs_fc, and every call site guards on None — so the
        filter simply did not apply. Returning a pattern instead would flip
        "all pending" to "nobody", which reads as a program with no members.
        """
        u = _pending(db, roles)
        db.session.commit()
        r = client.get('/api/v1/admin/members?tab=pending&lane=undecided',
                       headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        assert u.id in {i['user_id'] for i in r.get_json()['items']}

    def test_per_page_is_capped_server_side(self, client, db, app, admin, roles, leagues):
        db.session.commit()
        r = client.get('/api/v1/admin/members?tab=all&per_page=5000', headers=_auth(app, admin))
        assert r.status_code == 200
        assert r.get_json()['per_page'] == 100

    def test_subs_tab_lists_pool_members(self, client, db, app, admin, roles, leagues):
        u = _pending(db, roles)
        uid = u.id
        db.session.commit()
        h = _auth(app, admin)
        client.post(f'/api/v1/admin/members/{uid}/sub-assign',
                    json={'league_type': 'classic'}, headers=h)

        r = client.get('/api/v1/admin/members?tab=subs', headers=h)
        assert r.status_code == 200, r.get_json()
        item = next(i for i in r.get_json()['items'] if i['user_id'] == uid)
        assert item['sub_lanes'] == [{'lane': 'classic', 'label': 'Classic', 'status': 'active'}]


# ---------------------------------------------------------------------------
# §1.6 quick-profile pre-approval
# ---------------------------------------------------------------------------

class TestQuickProfilePreapproval:
    def _profile(self, db, admin):
        from datetime import datetime, timedelta
        from app.models import QuickProfile
        qp = QuickProfile(player_name='Walk In', created_by_user_id=admin.id,
                          claim_code=QuickProfile.generate_claim_code(),
                          expires_at=datetime.utcnow() + timedelta(days=30))
        db.session.add(qp)
        db.session.flush()
        return qp

    def test_set_and_clear(self, client, db, app, admin, roles, leagues):
        qp = self._profile(db, admin)
        qid = qp.id
        db.session.commit()
        h = _auth(app, admin)

        r = client.post(f'/api/v1/admin/quick-profiles/{qid}/preapprove',
                        json={'league_type': 'premier'}, headers=h)
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['pre_approved_league'] == 'premier'

        r = client.post(f'/api/v1/admin/quick-profiles/{qid}/preapprove',
                        json={'league_type': ''}, headers=h)
        assert r.status_code == 200
        assert r.get_json()['pre_approved_league'] is None

    def test_rejects_a_league_the_picker_never_offered(self, client, db, app, admin, roles, leagues):
        qp = self._profile(db, admin)
        qid = qp.id
        db.session.commit()
        r = client.post(f'/api/v1/admin/quick-profiles/{qid}/preapprove',
                        json={'league_type': 'atlantis'}, headers=_auth(app, admin))
        assert r.status_code == 400
        assert 'atlantis' in r.get_json()['message']
        assert 'valid_league_types' in r.get_json()
