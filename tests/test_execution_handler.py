from collections import namedtuple

import pytest

from src.engine.events import OrderEvent
from src.execution.execution_handler import SimulatedExecutionHandler

Bar = namedtuple("Bar", ["close", "volume", "high", "low"])


def make_order(qty):
    return OrderEvent(timestamp="2024-01-02", symbol="AAPL", order_type="MKT", quantity=qty)


def test_full_fill_when_within_participation_cap():
    handler = SimulatedExecutionHandler(max_participation_rate=0.5, rng_seed=1)
    bar = Bar(close=100.0, volume=10_000, high=101, low=99)
    fills = handler.execute_order(make_order(100), bar)
    assert len(fills) == 1
    assert fills[0].quantity == pytest.approx(100)
    assert fills[0].remaining_quantity == 0.0


def test_partial_fill_when_order_exceeds_participation_cap():
    handler = SimulatedExecutionHandler(max_participation_rate=0.01, rng_seed=1)
    bar = Bar(close=100.0, volume=1_000, high=101, low=99)  # cap = 10 shares
    fills = handler.execute_order(make_order(500), bar)
    fill = fills[0]
    assert abs(fill.quantity) == pytest.approx(10.0)
    assert fill.remaining_quantity == pytest.approx(490.0)


def test_buy_slippage_is_positive_cost_above_arrival_price():
    handler = SimulatedExecutionHandler(base_spread_bps=10, impact_coefficient=0.1, rng_seed=1)
    bar = Bar(close=50.0, volume=100_000, high=51, low=49)
    fill = handler.execute_order(make_order(1000), bar)[0]
    assert fill.fill_price > 50.0  # buys pay above arrival price
    assert fill.slippage > 0


def test_sell_slippage_is_negative_relative_to_arrival_price():
    handler = SimulatedExecutionHandler(base_spread_bps=10, impact_coefficient=0.1, rng_seed=1)
    bar = Bar(close=50.0, volume=100_000, high=51, low=49)
    fill = handler.execute_order(make_order(-1000), bar)[0]
    assert fill.fill_price < 50.0  # sells receive below arrival price
    assert fill.slippage > 0  # cost magnitude is still positive


def test_commission_respects_minimum():
    handler = SimulatedExecutionHandler(commission_per_share=0.005, min_commission=2.5, rng_seed=1)
    bar = Bar(close=50.0, volume=100_000, high=51, low=49)
    fill = handler.execute_order(make_order(1), bar)[0]
    assert fill.commission == pytest.approx(2.5)


def test_larger_orders_incur_more_market_impact():
    handler = SimulatedExecutionHandler(base_spread_bps=0, impact_coefficient=0.2, rng_seed=1)
    bar = Bar(close=100.0, volume=100_000, high=101, low=99)
    small = handler.execute_order(make_order(100), bar)[0]
    large = handler.execute_order(make_order(10_000), bar)[0]
    small_cost_per_share = small.slippage / abs(small.quantity)
    large_cost_per_share = large.slippage / abs(large.quantity)
    assert large_cost_per_share > small_cost_per_share
