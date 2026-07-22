"""
audience_service unit tests.

Covers the composer's "who + how reachable" logic:
- resolve_user_ids: all_active vs the new active_this_season segment
- channel_reach: per-channel opt-in gating, and the force-delivery override
  that pushes push/email/discord past a member's opt-out (SMS never forced).
"""
import pytest

from app.services import audience_service
from tests.factories import UserFactory, PlayerFactory


def _player_for(db, user, **kwargs):
    """Attach a Player to an existing user (PlayerFactory would make its own)."""
    from app.models import Player
    p = Player(name=f'P{user.id}', user_id=user.id, **kwargs)
    db.session.add(p)
    db.session.flush()
    return p


class TestResolveActiveThisSeason:
    def test_excludes_non_current_players_and_userless_accounts(self, db):
        playing = UserFactory()
        _player_for(db, playing, is_current_player=True)

        alumni = UserFactory()
        _player_for(db, alumni, is_current_player=False)

        staff = UserFactory()  # no Player row at all (e.g. an admin)

        db.session.flush()

        all_active = audience_service.resolve_user_ids(db.session, 'all_active', [])
        this_season = audience_service.resolve_user_ids(db.session, 'active_this_season', [])

        assert set(all_active) >= {playing.id, alumni.id, staff.id}
        assert playing.id in this_season
        assert alumni.id not in this_season
        assert staff.id not in this_season

    def test_active_this_season_needs_no_ids(self, db):
        assert 'active_this_season' in audience_service.NO_ID_AUDIENCE_TYPES
        # Resolving with empty ids must not error or short-circuit to [].
        u = UserFactory()
        _player_for(db, u, is_current_player=True)
        db.session.flush()
        assert u.id in audience_service.resolve_user_ids(db.session, 'active_this_season', [])


class TestChannelReachForce:
    def test_email_optout_respected_without_force(self, db):
        u = UserFactory(email='opt@x.com', email_notifications=False)
        db.session.flush()
        reach = audience_service.channel_reach(db.session, [u.id])
        assert reach['email'] == 0

    def test_force_email_overrides_optout(self, db):
        u = UserFactory(email='opt@x.com', email_notifications=False)
        db.session.flush()
        reach = audience_service.channel_reach(db.session, [u.id], force_channels={'email'})
        assert reach['email'] == 1

    def test_force_email_still_needs_an_address(self, db):
        u = UserFactory(email=None, email_notifications=False)
        db.session.flush()
        reach = audience_service.channel_reach(db.session, [u.id], force_channels={'email'})
        assert reach['email'] == 0

    def test_sms_is_never_forceable(self, db):
        # SMS is excluded from FORCEABLE_CHANNELS; even if passed, an unverified,
        # non-consented number must not count.
        assert 'sms' not in audience_service.FORCEABLE_CHANNELS
        u = UserFactory(sms_notifications=False)
        _player_for(db, u, is_phone_verified=False, sms_consent_given=False)
        db.session.flush()
        reach = audience_service.channel_reach(db.session, [u.id], force_channels={'sms'})
        assert reach['sms'] == 0
