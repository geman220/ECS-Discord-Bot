# tests/unit/services/test_template_commentary.py

"""
Unit tests for the template ("mad-lib") commentary engine.

Focus: the Sounders-perspective for/against mapping and slot-filling correctness
(the design's flagged highest-risk item), plus the no-hollow-line refusal that
preserves the no-silent-mock contract.
"""

import pytest

from app.utils.template_commentary import (
    TemplateCommentaryEngine,
    detect_rivalry,
)


@pytest.fixture
def engine():
    return TemplateCommentaryEngine()


def _ctx(**over):
    base = {
        'event_type': 'goal',
        'is_our_event': True,
        'player': 'Morris',
        'team': 'Seattle Sounders FC',
        'minute': "23'",
        'score': '2-1',
        'score_state': 'us_ahead',
        'rivalry': None,
        'assist': 'Rusnák',
        'player_on': '',
        'player_off': '',
        'match_id': 'm1',
    }
    base.update(over)
    return base


def _render_many(engine, ctx, n=60):
    return [engine.render(dict(ctx)) for _ in range(n)]


class TestSlotFilling:
    def test_no_unfilled_braces_ever(self, engine):
        # Across all event types and both sides, never emit a literal {slot}.
        types = ['goal', 'penalty_goal', 'own_goal', 'penalty_missed',
                 'penalty_saved', 'yellow_card', 'red_card', 'substitution']
        for et in types:
            for is_our in (True, False):
                ctx = _ctx(event_type=et, is_our_event=is_our,
                           player_on='Roldan', player_off='Lodeiro')
                for out in _render_many(engine, ctx, 30):
                    if out is not None:
                        assert '{' not in out and '}' not in out, f"{et}/{is_our}: {out!r}"

    def test_goal_for_includes_real_data(self, engine):
        outs = [o for o in _render_many(engine, _ctx()) if o]
        assert outs
        # At least one rendered line carries the player or the score (real ESPN data)
        assert any(('Morris' in o or '2-1' in o) for o in outs)

    def test_minute_apostrophe_not_doubled(self, engine):
        # minute comes in as "23'"; templates add their own apostrophe.
        outs = [o for o in _render_many(engine, _ctx(minute="45'")) if o]
        assert not any("45''" in o for o in outs)

    def test_substitution_uses_on_off(self, engine):
        ctx = _ctx(event_type='substitution', is_our_event=True,
                   player='', player_on='Roldan', player_off='Lodeiro')
        outs = [o for o in _render_many(engine, ctx) if o]
        assert outs
        assert any('Roldan' in o for o in outs)


class TestPerspective:
    def test_for_vs_against_differ(self, engine):
        for_outs = set(o for o in _render_many(engine, _ctx(is_our_event=True, match_id='a')) if o)
        against_outs = set(o for o in _render_many(engine, _ctx(is_our_event=False, match_id='b')) if o)
        # The two pools must not overlap — a "for" line must never ship on an "against" event.
        assert for_outs and against_outs
        assert for_outs.isdisjoint(against_outs)

    def test_against_goal_names_opponent_team(self, engine):
        ctx = _ctx(is_our_event=False, team='Portland Timbers', score='1-2', score_state='behind')
        outs = [o for o in _render_many(engine, ctx) if o]
        assert any('Portland Timbers' in o for o in outs)

    def test_own_goal_is_neutral_and_safe(self, engine):
        # Own goal must render regardless of is_our_event (neutral side) and
        # never crash or leak braces.
        for is_our in (True, False):
            outs = [o for o in _render_many(engine, _ctx(event_type='own_goal', is_our_event=is_our)) if o]
            assert outs
            assert all('{' not in o for o in outs)


class TestRefusal:
    def test_goal_without_player_or_score_refuses(self, engine):
        # No player AND no score -> None so the caller uses the ESPN description.
        ctx = _ctx(player='', score='')
        assert all(engine.render(dict(ctx)) is None for _ in range(10))

    def test_goal_with_score_only_still_renders(self, engine):
        ctx = _ctx(player='', score='2-1')
        assert any(engine.render(dict(ctx)) for _ in range(10))

    def test_unknown_event_type_refuses(self, engine):
        assert engine.render(_ctx(event_type='corner')) is None


class TestVarietyAndRivalry:
    def test_anti_repetition_produces_variety(self, engine):
        outs = set(o for o in _render_many(engine, _ctx(), n=80) if o)
        assert len(outs) > 1  # not the same line every time

    def test_detect_rivalry(self):
        assert detect_rivalry('Portland Timbers') == 'portland'
        assert detect_rivalry('Vancouver Whitecaps FC') == 'vancouver'
        assert detect_rivalry('Houston Dynamo FC') is None
        assert detect_rivalry('') is None
        assert detect_rivalry(None) is None

    def test_rivalry_pool_reachable(self, engine):
        # With a rivalry set, the rivalry-specific lines should appear over many draws.
        ctx = _ctx(is_our_event=False, team='Portland Timbers', rivalry='portland',
                   score='1-2', score_state='behind')
        outs = [o for o in _render_many(engine, ctx, n=120) if o]
        assert any('shithousing' in o.lower() or 'hate it here' in o.lower() for o in outs)
