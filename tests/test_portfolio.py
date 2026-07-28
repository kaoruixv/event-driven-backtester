import pytest

from src.engine.events import FillEvent, SignalEvent
from src.engine.portfolio import Portfolio


def test_no_order_generated_before_any_price_seen():
    p = Portfolio(symbols=["AAPL"], initial_capital=100_000)
    signal = SignalEvent(timestamp="2024-01-02", symbol="AAPL", direction="LONG")
    order = p.update_signal(signal)
    assert order is None


def test_long_signal_sizes_position_by_pct_of_capital():
    p = Portfolio(symbols=["AAPL"], initial_capital=100_000, position_size_pct=0.10)
    p.update_market_price("AAPL", 100.0, "2024-01-02")
    order = p.update_signal(SignalEvent(timestamp="2024-01-02", symbol="AAPL", direction="LONG"))
    assert order is not None
    assert order.quantity == pytest.approx(100.0)  # 10% of 100k / $100 = 100 shares


def test_exit_signal_flattens_position():
    p = Portfolio(symbols=["AAPL"], initial_capital=100_000, position_size_pct=0.10)
    p.update_market_price("AAPL", 100.0, "2024-01-02")
    p.positions["AAPL"] = 50
    order = p.update_signal(SignalEvent(timestamp="2024-01-02", symbol="AAPL", direction="EXIT"))
    assert order.quantity == pytest.approx(-50.0)


def test_fill_updates_cash_and_positions():
    p = Portfolio(symbols=["AAPL"], initial_capital=100_000)
    fill = FillEvent(
        timestamp="2024-01-02", symbol="AAPL", quantity=100, fill_price=100.5,
        commission=1.0, slippage=5.0, latency_ms=50.0,
    )
    p.update_fill(fill)
    assert p.positions["AAPL"] == 100
    assert p.cash == pytest.approx(100_000 - 100 * 100.5 - 1.0)


def test_equity_curve_reflects_marked_to_market_value():
    p = Portfolio(symbols=["AAPL"], initial_capital=100_000)
    fill = FillEvent(
        timestamp="2024-01-02", symbol="AAPL", quantity=100, fill_price=100.0,
        commission=0.0, slippage=0.0, latency_ms=0.0,
    )
    p.update_fill(fill)
    p.update_market_price("AAPL", 110.0, "2024-01-03")
    df = p.equity_dataframe()
    assert df["equity"].iloc[-1] == pytest.approx(100_000 - 10_000 + 100 * 110.0)
