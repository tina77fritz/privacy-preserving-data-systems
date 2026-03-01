import math
import pytest
from ppds.types import PolicyThresholds, Boundary, Granularity

_BOUNDARY = {Boundary.LOCAL: 0.9, Boundary.SHUFFLE: 0.7, Boundary.CENTRAL: 0.55}
_GRANULARITY = {Granularity.ITEM: 0.45, Granularity.CLUSTER: 0.6, Granularity.AGGREGATE: 0.75}


def _make(**overrides) -> PolicyThresholds:
    defaults = dict(
        tau_boundary=_BOUNDARY,
        tau_granularity=_GRANULARITY,
        k_min=100,
        alpha_L=0.30,
        alpha_U=0.35,
        alpha_I=0.25,
        alpha_R=0.10,
    )
    defaults.update(overrides)
    return PolicyThresholds(**defaults)


def test_valid_weights_accepted():
    th = _make()
    assert math.isclose(th.alpha_L + th.alpha_U + th.alpha_I + th.alpha_R, 1.0)


def test_weights_not_summing_to_one_raises():
    with pytest.raises(ValueError, match="must sum to 1.0"):
        _make(alpha_L=0.5, alpha_U=0.5, alpha_I=0.5, alpha_R=0.5)


def test_negative_weight_raises():
    with pytest.raises(ValueError, match="non-negative"):
        _make(alpha_L=-0.10, alpha_U=0.45, alpha_I=0.35, alpha_R=0.30)


def test_k_min_zero_raises():
    with pytest.raises(ValueError, match="k_min must be >= 1"):
        _make(k_min=0)


def test_k_min_negative_raises():
    with pytest.raises(ValueError, match="k_min must be >= 1"):
        _make(k_min=-5)


def test_weights_within_float_tolerance_accepted():
    # Floating-point arithmetic can produce sums like 0.9999999999999999
    th = _make(alpha_L=0.1, alpha_U=0.2, alpha_I=0.3, alpha_R=0.4)
    assert math.isclose(th.alpha_L + th.alpha_U + th.alpha_I + th.alpha_R, 1.0)
