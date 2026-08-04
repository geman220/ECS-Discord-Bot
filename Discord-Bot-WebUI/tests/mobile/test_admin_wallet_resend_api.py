"""
Mobile contract tests for POST /api/v1/admin/wallet/pass/resend.

The gate lookup (GET /admin/wallet/pass) has always answered a download_count of
0 with "Resend the download link rather than reissuing" — and there was no
endpoint to do it, so the app printed an instruction it could not follow.

The distinction these tests pin is the whole point of the endpoint:

  resend  = re-DELIVER. Same pass, same token, same barcode. Fixes "it never
            reached my phone", which is what download_count == 0 means.
  reissue = REBUILD the Apple/Google artifacts and push a refresh. Fixes "it
            arrived and renders wrong". Does nothing at all for a pass that
            never arrived, because there is no registered device to push to.

Reaching for the wrong one looks like it worked and changes nothing the person
can see, which is why `suggested_action` is machine-readable rather than a
sentence the client has to parse.
"""
from datetime import datetime, timedelta

import pytest
from flask_jwt_extended import create_access_token

from app.models import Role
from app.models.wallet import WalletPass, WalletPassType
from tests.factories import PlayerFactory, UserFactory


@pytest.fixture
def admin(db):
    role = db.session.query(Role).filter_by(name='Global Admin').first()
    if role is None:
        role = Role(name='Global Admin')
        db.session.add(role)
        db.session.flush()
    u = UserFactory()
    u.roles.append(role)
    db.session.flush()
    return u


def _auth(app, user):
    with app.app_context():
        token = create_access_token(identity=str(user.id),
                                    additional_claims={'approved': True})
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def pass_type(db):
    """Get-or-create, NOT create.

    `code` is UNIQUE and the per-test cleanup does not truncate
    wallet_pass_type, so a plain insert passes for the first test in the file
    and then fails every one after it with an IntegrityError in SETUP — which
    reads as nine broken tests rather than one leaked row. See
    reference_test_suite_collection_gaps.
    """
    wpt = db.session.query(WalletPassType).filter_by(code='pub_league').first()
    if wpt is None:
        wpt = WalletPassType(code='pub_league', name='Pub League Pass',
                             template_name='pub_league', validity_type='season')
        db.session.add(wpt)
        db.session.flush()
    return wpt


def _issue_pass(db, pass_type, player, *, downloads=0, status='active',
                email='holder@example.com'):
    wp = WalletPass(
        serial_number=WalletPass.generate_serial_number(),
        pass_type_id=pass_type.id,
        player_id=player.id,
        user_id=player.user_id,
        member_name=player.name,
        member_email=email,
        download_token=WalletPass.generate_download_token(),
        authentication_token=WalletPass.generate_token(),
        barcode_data='ECSFC-PUB-TEST',
        valid_from=datetime.utcnow() - timedelta(days=1),
        valid_until=datetime.utcnow() + timedelta(days=30),
        status=status,
        download_count=downloads,
    )
    db.session.add(wp)
    db.session.flush()
    return wp


@pytest.fixture
def sent(monkeypatch):
    """Capture what would have gone out; never touch the Gmail API in a test."""
    calls = []

    def _fake(to, subject, body):
        calls.append({'to': to, 'subject': subject, 'body': body})
        return {'id': 'fake'}

    monkeypatch.setattr('app.pub_league.email_helpers.send_email', _fake)
    return calls


class TestResend:
    def test_sends_the_existing_token_and_changes_nothing(
            self, client, db, app, admin, pass_type, sent):
        u = UserFactory(email='holder@example.com')
        player = PlayerFactory(user=u, name='Dana Reyes')
        db.session.flush()
        wp = _issue_pass(db, pass_type, player)
        pid, token, wpid = player.id, wp.download_token, wp.id
        db.session.commit()

        r = client.post('/api/v1/admin/wallet/pass/resend',
                        json={'player_id': pid}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body['success'] is True
        assert body['pass_id'] == wpid
        assert body['pass_changed'] is False
        assert body['previously_downloaded'] is False

        # The SAME token — a new one would invalidate a copy already on a phone.
        assert len(sent) == 1
        assert token in sent[0]['body']
        # `&platform=`, not `?platform=`: download_url already carries ?token=,
        # and a second `?` folds the platform into the token value and 404s.
        assert f'{token}&platform=apple' in sent[0]['body']

        db.session.expire_all()
        after = db.session.get(WalletPass, wpid)
        # Delivery is not a download. download_count must stay 0 so it remains a
        # truthful signal of whether the link was ever actually opened.
        assert after.download_count == 0
        assert after.download_token == token
        assert after.barcode_data == 'ECSFC-PUB-TEST'

    def test_recipient_is_masked_and_its_source_named(
            self, client, db, app, admin, pass_type, sent):
        u = UserFactory(email='gecourville@gmail.com')
        player = PlayerFactory(user=u)
        db.session.flush()
        _issue_pass(db, pass_type, player, email='stale@old.example')
        pid = player.id
        db.session.commit()

        r = client.post('/api/v1/admin/wallet/pass/resend',
                        json={'player_id': pid}, headers=_auth(app, admin))
        body = r.get_json()
        # The account address wins over the one stamped on the pass.
        assert sent[0]['to'] == 'gecourville@gmail.com'
        assert body['sent_to_source'] == 'account'
        # Masked: enough to confirm WHICH inbox, without putting a full address
        # in a response body.
        assert body['sent_to'] == 'g**********e@gmail.com'
        assert 'gecourville' not in body['sent_to']

    def test_falls_back_to_the_address_on_the_pass(
            self, client, db, app, admin, pass_type, sent):
        # A guest checkout that was never linked to an account has no email on
        # the User row; the pass still carries the address it was minted for.
        u = UserFactory()
        u.email = None
        player = PlayerFactory(user=u, name='Guest Buyer')
        db.session.flush()
        _issue_pass(db, pass_type, player, email='guest@example.com')
        pid = player.id
        db.session.commit()

        r = client.post('/api/v1/admin/wallet/pass/resend',
                        json={'player_id': pid}, headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['sent_to_source'] == 'pass'
        assert sent[0]['to'] == 'guest@example.com'

    def test_a_second_send_is_allowed(self, client, db, app, admin, pass_type, sent):
        """"I still didn't get it" is the normal second call.

        A cooldown that silently swallowed the retry would look exactly like the
        original delivery failure.
        """
        u = UserFactory(email='holder@example.com')
        player = PlayerFactory(user=u)
        db.session.flush()
        _issue_pass(db, pass_type, player)
        pid = player.id
        db.session.commit()
        h = _auth(app, admin)

        assert client.post('/api/v1/admin/wallet/pass/resend',
                           json={'player_id': pid}, headers=h).status_code == 200
        assert client.post('/api/v1/admin/wallet/pass/resend',
                           json={'player_id': pid}, headers=h).status_code == 200
        assert len(sent) == 2

    def test_an_already_downloaded_pass_says_so(
            self, client, db, app, admin, pass_type, sent):
        u = UserFactory(email='holder@example.com')
        player = PlayerFactory(user=u)
        db.session.flush()
        _issue_pass(db, pass_type, player, downloads=3)
        pid = player.id
        db.session.commit()

        r = client.post('/api/v1/admin/wallet/pass/resend',
                        json={'player_id': pid}, headers=_auth(app, admin))
        assert r.status_code == 200
        # Still sent — losing an email is a real reason to ask again — but the
        # admin is told this one HAS landed before, which changes the diagnosis.
        assert r.get_json()['previously_downloaded'] is True
        assert r.get_json()['download_count'] == 3
        assert len(sent) == 1


class TestResendRefusals:
    def test_no_active_pass_is_409_pointing_at_the_order_desk(
            self, client, db, app, admin, pass_type, sent):
        u = UserFactory(email='holder@example.com')
        player = PlayerFactory(user=u, name='Unpaid Person')
        db.session.flush()
        _issue_pass(db, pass_type, player, status='voided')
        pid = player.id
        db.session.commit()

        r = client.post('/api/v1/admin/wallet/pass/resend',
                        json={'player_id': pid}, headers=_auth(app, admin))
        assert r.status_code == 409
        # Issuing a pass is a paid-entitlement decision; a gate button must not
        # manufacture one.
        assert 'order desk' in r.get_json()['error']
        assert sent == []

    def test_no_address_anywhere_is_a_stated_dead_end(
            self, client, db, app, admin, pass_type, sent):
        u = UserFactory()
        u.email = None
        player = PlayerFactory(user=u, name='No Contact')
        db.session.flush()
        _issue_pass(db, pass_type, player, email=None)
        pid = player.id
        db.session.commit()

        r = client.post('/api/v1/admin/wallet/pass/resend',
                        json={'player_id': pid}, headers=_auth(app, admin))
        assert r.status_code == 409
        assert 'No email address' in r.get_json()['error']
        assert sent == []

    def test_a_mail_failure_is_502_not_a_false_success(
            self, client, db, app, admin, pass_type, monkeypatch):
        u = UserFactory(email='holder@example.com')
        player = PlayerFactory(user=u)
        db.session.flush()
        _issue_pass(db, pass_type, player)
        pid = player.id
        db.session.commit()
        monkeypatch.setattr('app.pub_league.email_helpers.send_email',
                            lambda *a, **k: None)

        r = client.post('/api/v1/admin/wallet/pass/resend',
                        json={'player_id': pid}, headers=_auth(app, admin))
        assert r.status_code == 502
        assert r.get_json()['success'] is False
        # Says which half failed: the pass is fine, the delivery is not.
        assert 'delivery failure' in r.get_json()['error']

    def test_unknown_player_is_404_with_a_body(self, client, db, app, admin):
        db.session.commit()
        r = client.post('/api/v1/admin/wallet/pass/resend',
                        json={'player_id': 98765432}, headers=_auth(app, admin))
        assert r.status_code == 404
        # A bodyless 404 is read by the client's feature-availability helper as
        # "endpoint not deployed", which hides the section instead of the error.
        assert r.get_json()['error']

    def test_missing_player_id_is_400(self, client, db, app, admin):
        db.session.commit()
        r = client.post('/api/v1/admin/wallet/pass/resend', json={},
                        headers=_auth(app, admin))
        assert r.status_code == 400

    def test_non_admin_is_refused(self, client, db, app):
        plain = UserFactory()
        db.session.flush()
        db.session.commit()
        r = client.post('/api/v1/admin/wallet/pass/resend', json={'player_id': 1},
                        headers=_auth(app, plain))
        assert r.status_code == 403


class TestLookupAdvertisesTheAction:
    def test_undownloaded_pass_carries_a_machine_readable_action(
            self, client, db, app, admin, pass_type):
        u = UserFactory(email='holder@example.com')
        player = PlayerFactory(user=u)
        db.session.flush()
        _issue_pass(db, pass_type, player, downloads=0)
        pid = player.id
        db.session.commit()

        r = client.get(f'/api/v1/admin/wallet/pass?player_id={pid}',
                       headers=_auth(app, admin))
        assert r.status_code == 200, r.get_json()
        item = r.get_json()['active_pass']
        assert 'Resend the download link' in item['diagnosis']
        # The client must not have to parse that sentence to offer the button.
        assert item['suggested_action'] == 'resend'

    def test_a_downloaded_pass_suggests_nothing(
            self, client, db, app, admin, pass_type):
        u = UserFactory(email='holder@example.com')
        player = PlayerFactory(user=u)
        db.session.flush()
        _issue_pass(db, pass_type, player, downloads=2)
        pid = player.id
        db.session.commit()

        r = client.get(f'/api/v1/admin/wallet/pass?player_id={pid}',
                       headers=_auth(app, admin))
        item = r.get_json()['active_pass']
        assert 'diagnosis' not in item
        assert 'suggested_action' not in item
