"""
Adversarial unit tests for Classic rating aggregation math and config parsing.

Pure-function coverage: value validation, weight normalization, composite
bounds, rounding. No DB required except where noted.
"""
from decimal import Decimal

import pytest

from app.services import classic_rating_service as svc
from app.models.admin_config import AdminConfig


def _patch_settings(monkeypatch, settings):
    monkeypatch.setattr(
        AdminConfig, 'get_setting',
        classmethod(lambda cls, key, default=None: settings.get(key, default)),
    )


class TestValidateMetricValue:
    def test_accepts_fractional_two_decimals(self):
        assert svc._validate_metric_value('2.75') == Decimal('2.75')
        assert svc._validate_metric_value(2.75) == Decimal('2.75')
        assert svc._validate_metric_value(3) == Decimal('3.00')

    def test_none_passes_through(self):
        assert svc._validate_metric_value(None) is None

    @pytest.mark.parametrize('bad', ['0.99', '5.01', '-3', 0, 5.001, '3.125'])
    def test_out_of_range_or_precision_rejected(self, bad):
        with pytest.raises(ValueError):
            svc._validate_metric_value(bad)

    @pytest.mark.parametrize('bad', ['abc', '', True, False, [], {}])
    def test_non_numeric_rejected(self, bad):
        with pytest.raises(ValueError):
            svc._validate_metric_value(bad)

    def test_boundaries_accepted(self):
        assert svc._validate_metric_value('1.00') == Decimal('1.00')
        assert svc._validate_metric_value('5.00') == Decimal('5.00')

    def test_decimal_exactness_no_float_drift(self):
        # 2.75 must round-trip exactly — float would give 2.74999...
        assert str(svc._validate_metric_value(2.75)) == '2.75'


class TestWeightNormalization:
    def test_defaults_when_unset(self, monkeypatch):
        _patch_settings(monkeypatch, {})
        weights = svc.get_rating_config()['weights']
        assert weights['intensity'] == Decimal(40)
        assert sum(weights.values()) == Decimal(100)

    def test_missummed_weights_normalized_to_100(self, monkeypatch):
        _patch_settings(monkeypatch, {'classic_rating_weights': {
            'intensity': 40, 'on_ball_skill': 30, 'spirit': 20, 'knowledge_movement': 20}})  # sums 110
        weights = svc.get_rating_config()['weights']
        assert abs(sum(weights.values()) - Decimal(100)) < Decimal('0.0001')
        # Relative order preserved
        assert weights['intensity'] > weights['on_ball_skill'] > weights['spirit']

    def test_undersummed_weights_normalized(self, monkeypatch):
        _patch_settings(monkeypatch, {'classic_rating_weights': {
            'intensity': 30, 'on_ball_skill': 30, 'spirit': 20, 'knowledge_movement': 10}})  # sums 90
        assert abs(sum(svc.get_rating_config()['weights'].values()) - Decimal(100)) < Decimal('0.0001')

    def test_garbage_weights_fall_back_to_defaults(self, monkeypatch):
        _patch_settings(monkeypatch, {'classic_rating_weights': {
            'intensity': 'lots', 'bogus_metric': 50}})
        weights = svc.get_rating_config()['weights']
        assert set(weights) == set(svc.METRICS)  # unknown keys dropped
        assert sum(weights.values()) == Decimal(100)

    def test_zero_sum_falls_back_to_defaults(self, monkeypatch):
        _patch_settings(monkeypatch, {'classic_rating_weights': {
            m: 0 for m in svc.METRICS}})
        weights = svc.get_rating_config()['weights']
        assert weights['intensity'] == Decimal(40)

    def test_suggestion_coefficients_parsed_with_defaults(self, monkeypatch):
        _patch_settings(monkeypatch, {'classic_draft_suggestion_coefficients': {
            'balance': 2, 'gender': 'oops'}})
        coeffs = svc.get_rating_config()['suggestion_coefficients']
        assert coeffs['balance'] == Decimal(2)
        assert coeffs['gender'] == Decimal('0.5')   # bad value -> default
        assert coeffs['need'] == Decimal('0.5')     # missing -> default


class TestComposite:
    WEIGHTS = {m: Decimal(w) for m, w in svc.DEFAULT_WEIGHTS.items()}

    def test_hand_computed_composite(self):
        finals = {'intensity': Decimal('4.00'), 'on_ball_skill': Decimal('3.00'),
                  'spirit': Decimal('2.00'), 'knowledge_movement': Decimal('5.00')}
        # Spirit inverts (6 - 2 = 4): 0.4*4 + 0.3*3 + 0.2*4 + 0.1*5
        #                          = 1.6 + 0.9 + 0.8 + 0.5 = 3.80
        assert svc.compute_composite(finals, self.WEIGHTS) == Decimal('3.80')

    def test_missing_metric_yields_none(self):
        finals = {'intensity': Decimal('4'), 'on_ball_skill': None,
                  'spirit': Decimal('2'), 'knowledge_movement': Decimal('5')}
        assert svc.compute_composite(finals, self.WEIGHTS) is None

    def test_composite_stays_in_scale_bounds(self):
        # Inverting spirit keeps its contribution on the same 1..5 scale, so the
        # composite still lands in [1, 5] for any valid ratings.
        finals = {'intensity': Decimal('1.25'), 'on_ball_skill': Decimal('4.75'),
                  'spirit': Decimal('5.00'), 'knowledge_movement': Decimal('2.50')}
        composite = svc.compute_composite(finals, self.WEIGHTS)
        assert Decimal('1.00') <= composite <= Decimal('5.00')

    def test_spirit_inversion_low_spirit_raises_composite(self):
        # Two players identical except spirit; the low-spirit one must score
        # HIGHER (needs addressing/picking earlier).
        base = {'intensity': Decimal('3.00'), 'on_ball_skill': Decimal('3.00'),
                'knowledge_movement': Decimal('3.00')}
        low = svc.compute_composite({**base, 'spirit': Decimal('1.00')}, self.WEIGHTS)
        high = svc.compute_composite({**base, 'spirit': Decimal('5.00')}, self.WEIGHTS)
        assert low > high

    def test_uniform_scores_reflect_spirit_inversion(self):
        # Uniform 3.25: three metrics contribute 3.25, spirit contributes
        # 6 - 3.25 = 2.75. 0.8*3.25 + 0.2*2.75 = 2.60 + 0.55 = 3.15.
        finals = {m: Decimal('3.25') for m in svc.METRICS}
        assert svc.compute_composite(finals, self.WEIGHTS) == Decimal('3.15')

    def test_rounding_half_up_at_boundary(self):
        assert svc.quantize2(Decimal('3.005')) == Decimal('3.01')
        assert svc.quantize2(Decimal('3.004')) == Decimal('3.00')
