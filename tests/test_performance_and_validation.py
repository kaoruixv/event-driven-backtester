import pandas as pd
import pytest

from src.reporting.performance import max_drawdown, sharpe_ratio, sortino_ratio
from src.validation.walk_forward import LookAheadBiasChecker, generate_walk_forward_windows


def test_max_drawdown_on_simple_series():
    equity = pd.Series([100, 120, 90, 110])
    dd = max_drawdown(equity)
    assert dd == pytest.approx((90 - 120) / 120)


def test_sharpe_ratio_zero_when_no_variance():
    returns = pd.Series([0.0] * 10)
    assert sharpe_ratio(returns) == 0.0


def test_sortino_ratio_zero_when_no_downside():
    returns = pd.Series([0.01, 0.02, 0.03])
    assert sortino_ratio(returns) == 0.0


def test_walk_forward_windows_are_strictly_ordered_and_non_overlapping_in_test_periods():
    windows = generate_walk_forward_windows("2018-01-01", "2022-01-01", train_days=252, test_days=63)
    assert len(windows) > 0
    for w in windows:
        assert w.train_start < w.train_end < w.test_start < w.test_end
    for a, b in zip(windows, windows[1:]):
        assert b.test_start > a.test_start  # each window moves forward


def test_lookahead_checker_raises_on_future_access():
    checker = LookAheadBiasChecker()
    checker.observe(pd.Timestamp("2024-01-02"))
    checker.observe(pd.Timestamp("2024-01-03"))
    with pytest.raises(AssertionError):
        checker.assert_visible(pd.Timestamp("2024-01-10"), context="test")


def test_lookahead_checker_passes_for_already_dispatched_timestamp():
    checker = LookAheadBiasChecker()
    checker.observe(pd.Timestamp("2024-01-05"))
    checker.assert_visible(pd.Timestamp("2024-01-03"), context="test")  # should not raise
    assert checker.report()["clean"] is True
