"""
portfolio.py
------------
Turns SignalEvents into OrderEvents (position sizing), and turns FillEvents
into updated cash/positions/equity. Also tracks an "idealized" parallel P&L
(zero-cost, instant fill at the signal-bar close) purely for comparison, so
the tearsheet can show realistic-vs-idealized P&L side by side.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.engine.events import FillEvent, OrderEvent, SignalEvent


class Portfolio:
    def __init__(self, symbols: list[str], initial_capital: float = 100_000.0,
                 position_size_pct: float = 0.10):
        self.symbols = symbols
        self.initial_capital = initial_capital
        self.position_size_pct = position_size_pct

        self.cash = initial_capital
        self.positions = {s: 0.0 for s in symbols}
        self.holdings_value = {s: 0.0 for s in symbols}
        self.latest_price = {s: None for s in symbols}

        # idealized (frictionless) shadow portfolio for comparison
        self.ideal_cash = initial_capital
        self.ideal_positions = {s: 0.0 for s in symbols}

        self.equity_curve: list[dict] = []
        self.ideal_equity_curve: list[dict] = []
        self.fills: list[FillEvent] = []

    # ---------- signal -> order ----------

    def update_signal(self, event: SignalEvent) -> OrderEvent | None:
        price = self.latest_price[event.symbol]
        if price is None or price <= 0:
            return None

        target_dollar_exposure = self.initial_capital * self.position_size_pct * event.strength
        target_shares = target_dollar_exposure / price

        current = self.positions[event.symbol]
        if event.direction == "LONG":
            delta = target_shares - current
        elif event.direction == "SHORT":
            delta = -target_shares - current
        elif event.direction == "EXIT":
            delta = -current
        else:
            return None

        if abs(delta) < 1e-6:
            return None

        # Track the idealized fill immediately at current price, no cost.
        self.ideal_cash -= delta * price
        self.ideal_positions[event.symbol] += delta

        return OrderEvent(
            timestamp=event.timestamp, symbol=event.symbol,
            order_type="MKT", quantity=delta,
        )

    # ---------- fill -> portfolio state ----------

    def update_fill(self, event: FillEvent):
        self.fills.append(event)
        cost = event.quantity * event.fill_price
        self.cash -= cost
        self.cash -= event.commission
        self.positions[event.symbol] += event.quantity

    def update_market_price(self, symbol: str, price: float, timestamp: datetime):
        self.latest_price[symbol] = price
        self.holdings_value[symbol] = self.positions[symbol] * price

        total_equity = self.cash + sum(self.holdings_value.values())
        self.equity_curve.append({"timestamp": timestamp, "equity": total_equity})

        ideal_holdings = sum(self.ideal_positions[s] * (self.latest_price[s] or 0) for s in self.symbols)
        ideal_equity = self.ideal_cash + ideal_holdings
        self.ideal_equity_curve.append({"timestamp": timestamp, "equity": ideal_equity})

    def equity_dataframe(self) -> pd.DataFrame:
        df = pd.DataFrame(self.equity_curve).drop_duplicates(subset="timestamp", keep="last")
        df = df.set_index("timestamp")
        df["returns"] = df["equity"].pct_change().fillna(0.0)
        return df

    def ideal_equity_dataframe(self) -> pd.DataFrame:
        df = pd.DataFrame(self.ideal_equity_curve).drop_duplicates(subset="timestamp", keep="last")
        df = df.set_index("timestamp")
        df["returns"] = df["equity"].pct_change().fillna(0.0)
        return df

    def fills_dataframe(self) -> pd.DataFrame:
        if not self.fills:
            return pd.DataFrame()
        return pd.DataFrame([f.__dict__ for f in self.fills])
