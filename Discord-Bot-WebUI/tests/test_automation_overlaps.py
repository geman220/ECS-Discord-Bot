"""Guard the automation duplication-warning surface.

TRIGGER_OVERLAPS is a hand-maintained inventory of what the rest of the app
already sends. It cannot be derived from code, so the one thing a test CAN
enforce is that it stays complete: every trigger an admin can pick must carry an
entry, even if that entry says "nothing else covers this".

The failure mode this prevents is specific and was real — a partly populated map
renders as silence in the editor, and an admin reads silence as "checked, no
overlap" when it actually means nobody looked at that trigger yet.
"""
import pytest

from app.models.automation import (
    TRIGGER_TYPES, TRIGGER_OVERLAPS, TRIGGER_CATALOG, VALID_OVERLAP_CHANNELS,
    overlap_warning, channel_clashes, find_rule_conflicts,
)


@pytest.mark.parametrize('trigger', sorted(TRIGGER_TYPES))
def test_every_trigger_has_an_overlap_entry(trigger):
    assert overlap_warning(trigger) is not None, (
        f"{trigger} has no TRIGGER_OVERLAPS entry. Add one — including the "
        f"'nothing_else': True form when nothing else sends on this event. An "
        f"absent entry renders as silence, which admins read as 'no overlap'."
    )


@pytest.mark.parametrize('trigger,meta', sorted(TRIGGER_OVERLAPS.items()))
def test_overlap_entries_are_well_formed(trigger, meta):
    assert trigger in TRIGGER_TYPES, f"{trigger} is not a real trigger type"
    assert meta.get('text'), f"{trigger} overlap note has no text"
    assert meta.get('where'), f"{trigger} overlap note does not say where it is configured"

    bad = set(meta.get('avoid_channels') or []) - set(VALID_OVERLAP_CHANNELS)
    assert not bad, (
        f"{trigger} lists avoid_channels {sorted(bad)} that are not real "
        f"channels — a typo here silently disables the double-notify warning."
    )

    # "Nothing else sends" and "avoid these channels because something already
    # sends on them" are contradictory claims.
    if meta.get('nothing_else'):
        assert not meta.get('avoid_channels'), (
            f"{trigger} claims nothing_else but also lists avoid_channels"
        )


def test_catalog_and_overlaps_cover_the_same_triggers():
    assert set(TRIGGER_CATALOG) == set(TRIGGER_TYPES)
    assert set(TRIGGER_OVERLAPS) == set(TRIGGER_TYPES)


class _FakeRule:
    """Minimal stand-in — find_rule_conflicts only reads these five attributes."""

    def __init__(self, rule_id, trigger, audience, channels, enabled=True, steps=None):
        self.id = rule_id
        self.name = f'Rule {rule_id}'
        self.trigger_type = trigger
        self.audience_type = audience
        self.channels = channels
        self.enabled = enabled
        self.steps = steps

    def action_steps(self):
        if isinstance(self.steps, list) and self.steps:
            return self.steps
        return [{'channels': self.channels}]


def test_conflict_detected_for_same_trigger_audience_and_channel():
    rules = [
        _FakeRule(1, 'user_approved', 'the_subject', ['email']),
        _FakeRule(2, 'user_approved', 'the_subject', ['email', 'push']),
    ]
    conflicts = find_rule_conflicts(rules)
    assert set(conflicts) == {1, 2}
    assert conflicts[1][0]['other_id'] == 2


def test_no_conflict_when_channels_are_split():
    """Same event and audience but no shared channel is a deliberate split."""
    rules = [
        _FakeRule(1, 'user_approved', 'the_subject', ['email']),
        _FakeRule(2, 'user_approved', 'the_subject', ['push']),
    ]
    assert find_rule_conflicts(rules) == {}


def test_disabled_rules_are_ignored():
    rules = [
        _FakeRule(1, 'user_approved', 'the_subject', ['email']),
        _FakeRule(2, 'user_approved', 'the_subject', ['email'], enabled=False),
    ]
    assert find_rule_conflicts(rules) == {}


def test_different_trigger_or_audience_is_not_a_conflict():
    rules = [
        _FakeRule(1, 'user_approved', 'the_subject', ['email']),
        _FakeRule(2, 'waitlist_stuck', 'the_subject', ['email']),
        _FakeRule(3, 'user_approved', 'current_season_players', ['email']),
    ]
    assert find_rule_conflicts(rules) == {}


def test_follow_up_step_channels_count_toward_a_conflict():
    """A ladder that adds push at step 2 still collides with a push rule."""
    ladder = _FakeRule(1, 'user_approved', 'the_subject', ['email'], steps=[
        {'channels': ['email']},
        {'channels': ['push']},
    ])
    rules = [ladder, _FakeRule(2, 'user_approved', 'the_subject', ['push'])]
    conflicts = find_rule_conflicts(rules)
    assert set(conflicts) == {1, 2}, (
        'step channels were ignored, so a multi-step rule can double-notify undetected'
    )


def test_channel_clashes_only_flags_configured_channels():
    assert channel_clashes('user_approved', ['email']) == []
    assert channel_clashes('user_approved', ['email', 'push']) == ['push']
    # A trigger nothing else covers can never clash.
    assert channel_clashes('profile_stale', ['email', 'push', 'discord']) == []
