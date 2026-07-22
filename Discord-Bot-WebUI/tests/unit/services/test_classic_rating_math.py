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
        # 0.4*4 + 0.3*3 + 0.2*2 + 0.1*5 = 1.6 + 0.9 + 0.4 + 0.5 = 3.40
        assert svc.compute_composite(finals, self.WEIGHTS) == Decimal('3.40')

    def test_missing_metric_yields_none(self):
        finals = {'intensity': Decimal('4'), 'on_ball_skill': None,
                  'spirit': Decimal('2'), 'knowledge_movement': Decimal('5')}
        assert svc.compute_composite(finals, self.WEIGHTS) is None

    def test_composite_within_min_max_bounds(self):
        finals = {'intensity': Decimal('1.25'), 'on_ball_skill': Decimal('4.75'),
                  'spirit': Decimal('3.00'), 'knowledge_movement': Decimal('2.50')}
        composite = svc.compute_composite(finals, self.WEIGHTS)
        assert min(finals.values()) <= composite <= max(finals.values())

    def test_uniform_scores_identity(self):
        finals = {m: Decimal('3.25') for m in svc.METRICS}
        assert svc.compute_composite(finals, self.WEIGHTS) == Decimal('3.25')

    def test_rounding_half_up_at_boundary(self):
        assert svc.quantize2(Decimal('3.005')) == Decimal('3.01')
        assert svc.quantize2(Decimal('3.004')) == Decimal('3.00')
