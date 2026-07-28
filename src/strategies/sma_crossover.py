"""
sma_crossover.py
-----------------
A deliberately simple example strategy so the project's value is legible
as "execution simulation infrastructure" rather than "alpha discovery".
Swap this module out for any real signal generator -- everything downstream
(portfolio sizing, execution simulation, validation, reporting) is
signal-agnostic.
"""

from __future__ import annotations

from collections import deque

from src.engine.events import MarketEvent, SignalEvent


class SMACrossoverStrategy:
    def __init__(self, event_queue, symbols: list[str], short_window: int = 20, long_window: int = 50):
        self.event_queue = event_queue
        self.symbols = symbols
        self.short_window = short_window
        self.long_window = long_window
        self._prices = {s: deque(maxlen=long_window) for s in symbols}
        self._invested = {s: False for s in symbols}

    def calculate_signals(self, event: MarketEvent):
        if event.symbol not in self.symbols:
            return
        prices = self._prices[event.symbol]
        prices.append(event.close)
        if len(prices) < self.long_window:
            return

        short_ma = sum(list(prices)[-self.short_window:]) / self.short_window
        long_ma = sum(prices) / self.long_window

        if short_ma > long_ma and not self._invested[event.symbol]:
            self._invested[event.symbol] = True
            self.event_queue.put(
                SignalEvent(timestamp=event.timestamp, symbol=event.symbol, direction="LONG")
            )
        elif short_ma < long_ma and self._invested[event.symbol]:
            self._invested[event.symbol] = False
            self.event_queue.put(
                SignalEvent(timestamp=event.timestamp, symbol=event.symbol, direction="EXIT")
            )
