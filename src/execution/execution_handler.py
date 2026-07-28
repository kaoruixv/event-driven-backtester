"""
execution_handler.py
---------------------
Converts OrderEvents into FillEvents the way a real broker/exchange would --
imperfectly. This is the heart of "realistic execution costs":

1. Latency model: a decision made on bar t doesn't fill instantly. We model
   a delay (ms), and if the delay is large enough to cross into the next
   bar, the fill price reflects the price *after* that delay, not the price
   at decision time. This captures the cost of being slow.

2. Slippage model: two additive components --
   - Spread cost: half (or full, for urgent orders) the bid-ask spread,
     estimated from a spread model when real quotes aren't available.
   - Market impact: a square-root impact model (Almgren-Chriss style),
     cost ~ sigma * sqrt(order_size / avg_volume), so bigger orders in
     thinner names cost more, which vectorized backtests almost always
     ignore.

3. Partial fill model: an order can't fully execute if its size exceeds a
   participation-rate cap of that bar's volume. The unfilled remainder is
   either carried to the next bar (default) or cancelled, depending on
   config.
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod

from src.engine.events import FillEvent, OrderEvent

logger = logging.getLogger(__name__)


class ExecutionHandler(ABC):
    @abstractmethod
    def execute_order(self, event: OrderEvent, bar) -> list[FillEvent]:
        raise NotImplementedError


class SimulatedExecutionHandler(ExecutionHandler):
    def __init__(
        self,
        commission_per_share: float = 0.005,
        min_commission: float = 1.0,
        base_spread_bps: float = 5.0,
        impact_coefficient: float = 0.1,
        max_participation_rate: float = 0.1,
        latency_mean_ms: float = 80.0,
        latency_std_ms: float = 30.0,
        carry_unfilled: bool = True,
        rng_seed: int | None = 42,
    ):
        self.commission_per_share = commission_per_share
        self.min_commission = min_commission
        self.base_spread_bps = base_spread_bps
        self.impact_coefficient = impact_coefficient
        self.max_participation_rate = max_participation_rate
        self.latency_mean_ms = latency_mean_ms
        self.latency_std_ms = latency_std_ms
        self.carry_unfilled = carry_unfilled
        self._rng = random.Random(rng_seed)

    # ---------- component models ----------

    def _simulate_latency(self) -> float:
        return max(0.0, self._rng.gauss(self.latency_mean_ms, self.latency_std_ms))

    def _spread_cost(self, price: float) -> float:
        """Half-spread cost per share, in dollars."""
        return price * (self.base_spread_bps / 1e4) / 2.0

    def _market_impact(self, quantity: float, bar_volume: float, price: float, daily_vol_pct: float = 0.02) -> float:
        """
        Square-root impact model: impact (in price terms) grows with the
        square root of participation, scaled by a volatility proxy. This is
        the standard first-order approximation used in execution-cost
        literature (Almgren-Chriss / Kyle-lambda family models).
        """
        if bar_volume <= 0:
            return price * 0.01  # thin/no volume -> punitive fallback cost
        participation = min(abs(quantity) / bar_volume, 1.0)
        impact_pct = self.impact_coefficient * daily_vol_pct * (participation ** 0.5)
        return price * impact_pct

    def _max_fillable(self, bar_volume: float) -> float:
        return bar_volume * self.max_participation_rate

    # ---------- main entry point ----------

    def execute_order(self, event: OrderEvent, bar) -> list[FillEvent]:
        """
        bar: a namedtuple/row-like object with .close, .volume, .high, .low
        for the bar the order arrives on (post-latency bar selection is
        handled by the backtest loop, which passes the correct bar in).
        """
        latency_ms = self._simulate_latency()
        arrival_price = bar.close
        requested_qty = event.quantity

        max_fillable = self._max_fillable(bar.volume)
        filled_qty = requested_qty
        remaining_qty = 0.0
        if abs(requested_qty) > max_fillable and max_fillable > 0:
            filled_qty = max_fillable if requested_qty > 0 else -max_fillable
            remaining_qty = requested_qty - filled_qty
            logger.info(
                "Partial fill: %s wanted %.0f, filled %.0f (participation cap), %.0f carried",
                event.symbol, requested_qty, filled_qty, remaining_qty,
            )

        spread = self._spread_cost(arrival_price)
        impact = self._market_impact(filled_qty, bar.volume, arrival_price)
        direction = 1 if filled_qty > 0 else -1

        # Buys pay the spread+impact above mid; sells receive below mid.
        fill_price = arrival_price + direction * (spread + impact)
        slippage_dollars = abs(fill_price - arrival_price) * abs(filled_qty)
        commission = max(self.min_commission, abs(filled_qty) * self.commission_per_share)

        fill = FillEvent(
            timestamp=event.timestamp,
            symbol=event.symbol,
            quantity=filled_qty,
            fill_price=fill_price,
            commission=commission,
            slippage=slippage_dollars,
            latency_ms=latency_ms,
            remaining_quantity=remaining_qty if self.carry_unfilled else 0.0,
        )
        return [fill]
