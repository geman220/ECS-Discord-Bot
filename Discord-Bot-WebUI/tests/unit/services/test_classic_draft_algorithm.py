"""
Adversarial unit tests for the balanced-draft math: totals, gaps, projections,
and the suggestion algorithm's invariants (hard partition, determinism,
gap-non-worsening, gender/position terms). Pure functions — no DB.
"""
import random
from decimal import Decimal

import pytest

from app.services import classic_draft_service as svc
from app.services.classic_rating_service import DEFAULT_WEIGHTS, METRICS


def make_config(**overrides):
    config = {
        'weights': {m: Decimal(w) for m, w in DEFAULT_WEIGHTS.items()},
        'max_metric_gap': Decimal('3'),
        'unrated_default': Decimal('3.0'),
        'suggestion_count': 10,
        'gender_balance_enabled': True,
        'suggestion_coefficients': {
            'balance': Decimal('1.0'), 'need': Decimal('0.5'),
            'gender': Decimal('0.5'), 'position': Decimal('0.35'),
        },
    }
    config.update(overrides)
    return config


def player(pid, scores=None, *, coach=False, pronouns=None, gender=None,
           favorite=None, others=None, gk=''):
    ratings = None
    if scores is not None:
        ratings = {
            'is_rated': all(scores.get(m) is not None for m in METRICS),
            'composite': None,
            'metrics': {m: scores.get(m) for m in METRICS},
        }
        present = [Decimal(str(scores[m])) for m in METRICS if scores.get(m) is not None]
        if len(present) == 4:
            weights = {m: Decimal(w) for m, w in DEFAULT_WEIGHTS.items()}
            ratings['composite'] = float(sum(
                weights[m] * Decimal(str(scores[m])) for m in METRICS) / Decimal(100))
    return {
        'id': pid, 'name': f'Player {pid}', 'is_coach': coach,
        'pronouns': pronouns, 'balance_gender': gender,
        'favorite_position': favorite, 'other_positions': others or [],
        'positions_not_to_play': [], 'gk_willingness': gk,
        'wants_gk': 'goalkeeper' == (favorite or '').lower(),
        'ratings': ratings,
    }


def flat(pid, value):
    return player(pid, {m: value for m in METRICS})


class TestGenderDerivation:
    def test_pronoun_heuristics(self):
        # Binary male / not-male: only he/him reads as M, everything else is N.
        assert svc.derive_gender(player(1, pronouns='he/him')) == 'M'
        assert svc.derive_gender(player(2, pronouns='she/her')) == 'N'
        assert svc.derive_gender(player(3, pronouns='they/them')) == 'N'
        assert svc.derive_gender(player(4, pronouns=None)) == 'N'

    def test_override_beats_pronouns(self):
        assert svc.derive_gender(player(1, pronouns='he/him', gender='N')) == 'N'
        assert svc.derive_gender(player(2, pronouns='she/her', gender='M')) == 'M'


class TestTotalsAndGaps:
    def test_totals_exclude_coaches_and_impute_unrated(self):
        config = make_config()
        rosters = {
            1: [flat(1, 4), player(2, None), player(3, None, coach=True)],
            2: [flat(4, 2)],
        }
        totals = svc.compute_team_totals(rosters, config)
        # Team 1: rated 4.00 + unrated imputed 3.00 = 7.00 (coach excluded)
        assert totals[1]['metrics']['intensity']['total'] == Decimal('7.00')
        assert totals[1]['size'] == 2 and totals[1]['coach_count'] == 1
        assert totals[1]['unrated_count'] == 1
        # Average over RATED players only
        assert totals[1]['metrics']['intensity']['avg'] == Decimal('4')
        assert totals[2]['metrics']['intensity']['total'] == Decimal('2.00')

    def test_all_unrated_team_total_is_n_times_default(self):
        config = make_config()
        rosters = {1: [player(i, None) for i in range(5)]}
        totals = svc.compute_team_totals(rosters, config)
        assert totals[1]['metrics']['spirit']['total'] == Decimal('15.0')
        assert totals[1]['metrics']['spirit']['avg'] is None

    def test_gap_and_limit(self):
        config = make_config(max_metric_gap=Decimal('3'))
        rosters = {1: [flat(1, 5), flat(2, 5)], 2: [flat(3, 3)], 3: []}
        totals = svc.compute_team_totals(rosters, config)
        gaps = svc.compute_gaps(totals, config)
        # totals: 10 / 3 / 0 -> gap 10, over the limit
        assert gaps['intensity']['gap'] == Decimal('10.00')
        assert gaps['intensity']['max_team_id'] == 1
        assert gaps['intensity']['min_team_id'] == 3
        assert not gaps['intensity']['within_limit']

    def test_single_team_and_empty(self):
        config = make_config()
        gaps = svc.compute_gaps(svc.compute_team_totals({1: [flat(1, 4)]}, config), config)
        assert gaps['intensity']['gap'] == Decimal(0)
        assert gaps['intensity']['within_limit']
        gaps = svc.compute_gaps({}, config)
        assert gaps['intensity']['within_limit']


class TestProjection:
    def test_projection_does_not_mutate(self):
        config = make_config()
        rosters = {1: [flat(1, 3)], 2: [flat(2, 3)]}
        totals = svc.compute_team_totals(rosters, config)
        before = totals[1]['metrics']['intensity']['total']
        projection = svc.project_assignment(totals, flat(9, 5), 1, config)
        assert totals[1]['metrics']['intensity']['total'] == before
        assert projection['totals'][1]['metrics']['intensity']['total'] == before + Decimal(5)
        assert projection['deltas']['intensity'] == Decimal(5)

    def test_projection_flags_violation(self):
        config = make_config(max_metric_gap=Decimal('1'))
        rosters = {1: [flat(1, 3)], 2: [flat(2, 3)]}
        totals = svc.compute_team_totals(rosters, config)
        projection = svc.project_assignment(totals, flat(9, 5), 1, config)
        assert projection['violates_gap']

    def test_unknown_team_raises(self):
        config = make_config()
        with pytest.raises(ValueError):
            svc.project_assignment({}, flat(1, 3), 99, config)


class TestSuggestions:
    def test_hard_partition_non_violators_first(self):
        config = make_config(max_metric_gap=Decimal('2'), suggestion_count=10)
        # Team 2 trails badly; assigning a strong player to team 1 violates.
        rosters = {1: [flat(1, 4)], 2: []}
        pool = [flat(10, 5), flat(11, 1), flat(12, 2)]
        suggestions = svc.suggest_players(pool, rosters, 1, config)
        flags = [s['violates_gap'] for s in suggestions]
        assert flags == sorted(flags)  # False (non-violators) strictly first

    def test_top_pick_reduces_weighted_gap_when_possible(self):
        config = make_config(suggestion_count=10)
        rosters = {1: [flat(1, 5), flat(2, 5)], 2: [flat(3, 1)]}
        pool = [flat(10, 5), flat(11, 3), flat(12, 1)]
        # Suggest for the TRAILING team 2: best pick should close the gap most.
        suggestions = svc.suggest_players(pool, rosters, 2, config)
        best = suggestions[0]
        assert best['player_id'] == 10  # the 5.0 player closes an 8-point gap fastest
        for m in METRICS:
            assert best['projection'][m]['gap_after'] <= best['projection'][m]['gap_before']

    def test_determinism_under_shuffled_input(self):
        config = make_config(suggestion_count=10)
        rosters = {1: [flat(1, 4)], 2: [flat(2, 2)]}
        pool = [flat(pid, 1 + (pid % 5)) for pid in range(10, 30)]
        baseline = [s['player_id'] for s in svc.suggest_players(pool, rosters, 2, config)]
        for seed in range(3):
            shuffled = pool[:]
            random.Random(seed).shuffle(shuffled)
            result = [s['player_id'] for s in svc.suggest_players(shuffled, rosters, 2, config)]
            assert result == baseline

    def test_tie_broken_by_player_id(self):
        config = make_config(suggestion_count=5)
        rosters = {1: [], 2: []}
        pool = [flat(7, 3), flat(3, 3), flat(5, 3)]  # identical players
        suggestions = svc.suggest_players(pool, rosters, 1, config)
        assert [s['player_id'] for s in suggestions] == [3, 5, 7]

    def test_gender_term_prefers_underrepresented(self):
        config = make_config(suggestion_count=10)
        # League is 50/50; team 1 is all-M -> N candidates get the +1 term.
        rosters = {1: [flat(1, 3) | {'pronouns': 'he/him'},
                       flat(2, 3) | {'pronouns': 'he/him'}],
                   2: [flat(3, 3) | {'pronouns': 'she/her'},
                       flat(4, 3) | {'pronouns': 'she/her'}]}
        pool = [flat(10, 3) | {'pronouns': 'he/him'},
                flat(11, 3) | {'pronouns': 'she/her'}]
        suggestions = svc.suggest_players(pool, rosters, 1, config)
        by_id = {s['player_id']: s for s in suggestions}
        assert by_id[11]['components']['gender'] > by_id[10]['components']['gender']
        assert suggestions[0]['player_id'] == 11

    def test_gender_term_disabled(self):
        config = make_config(gender_balance_enabled=False, suggestion_count=10)
        rosters = {1: [flat(1, 3) | {'pronouns': 'he/him'}], 2: []}
        pool = [flat(11, 3) | {'pronouns': 'she/her'}]
        suggestions = svc.suggest_players(pool, rosters, 1, config)
        assert suggestions[0]['components']['gender'] == 0

    def test_balance_gender_override_wins_in_scoring(self):
        config = make_config(suggestion_count=10)
        rosters = {1: [flat(1, 3) | {'pronouns': 'he/him'}],
                   2: [flat(2, 3) | {'pronouns': 'she/her'}]}
        # Pronouns say he/him but the admin flagged N.
        pool = [flat(11, 3) | {'pronouns': 'he/him', 'balance_gender': 'N'}]
        suggestions = svc.suggest_players(pool, rosters, 1, config)
        assert suggestions[0]['gender'] == 'N'
        assert suggestions[0]['components']['gender'] == 1.0

    def test_gk_bonus_when_team_lacks_gk(self):
        config = make_config(suggestion_count=10)
        rosters = {1: [flat(1, 3)], 2: []}
        pool = [flat(10, 3) | {'gk_willingness': 'Yes please', 'wants_gk': True},
                flat(11, 3)]
        suggestions = svc.suggest_players(pool, rosters, 1, config)
        by_id = {s['player_id']: s for s in suggestions}
        assert by_id[10]['components']['position'] > by_id[11]['components']['position']

    def test_unrated_candidates_included_and_flagged(self):
        config = make_config(suggestion_count=10)
        rosters = {1: [flat(1, 3)], 2: []}
        pool = [player(10, None)]
        suggestions = svc.suggest_players(pool, rosters, 1, config)
        assert len(suggestions) == 1
        assert suggestions[0]['is_rated'] is False

    def test_coaches_never_suggested(self):
        config = make_config(suggestion_count=10)
        rosters = {1: [], 2: []}
        pool = [player(10, None, coach=True), flat(11, 3)]
        suggestions = svc.suggest_players(pool, rosters, 1, config)
        assert [s['player_id'] for s in suggestions] == [11]

    def test_empty_pool(self):
        config = make_config()
        assert svc.suggest_players([], {1: [], 2: []}, 1, config) == []

    def test_suggestion_count_respected(self):
        config = make_config(suggestion_count=3)
        pool = [flat(pid, 3) for pid in range(10, 30)]
        suggestions = svc.suggest_players(pool, {1: [], 2: []}, 1, config)
        assert len(suggestions) == 3
