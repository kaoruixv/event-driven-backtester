"""
backtest.py
-----------
The event queue loop. This is the actual "engine" -- everything else is a
plug-in. On every iteration we pop ONE event and dispatch it:

    MARKET -> strategy.calculate_signals() -> may enqueue SIGNAL
    SIGNAL -> portfolio.update_signal()     -> may enqueue ORDER
    ORDER  -> execution.execute_order()     -> enqueues FILL
    FILL   -> portfolio.update_fill()

Because everything is driven by this queue rather than by vectorized array
ops over the whole dataset at once, a strategy or execution model literally
cannot reference a bar that hasn't been dispatched yet -- look-ahead bias
has to be introduced deliberately (e.g. by indexing into a stored future
bar), not accidentally via a misaligned pandas shift().
"""

from __future__ import annotations

import logging
import queue
import time

from src.engine.events import EventType
from src.engine.portfolio import Portfolio
from src.execution.execution_handler import SimulatedExecutionHandler

logger = logging.getLogger(__name__)


class Backtest:
    def __init__(self, data_handler, strategy_cls, strategy_kwargs: dict,
                 symbols: list[str], initial_capital: float = 100_000.0,
                 execution_handler: SimulatedExecutionHandler | None = None,
                 position_size_pct: float = 0.10):
        self.event_queue: queue.Queue = queue.Queue()
        self.symbols = symbols

        self.data_handler = data_handler
        self.data_handler.event_queue = self.event_queue

        self.strategy = strategy_cls(self.event_queue, symbols, **strategy_kwargs)
        self.portfolio = Portfolio(symbols, initial_capital, position_size_pct)
        self.execution = execution_handler or SimulatedExecutionHandler()

        self._latest_bar_by_symbol: dict[str, object] = {}

    def _run_event_loop(self):
        while True:
            try:
                event = self.event_queue.get(block=False)
            except queue.Empty:
                break

            if event.type == EventType.MARKET:
                self._latest_bar_by_symbol[event.symbol] = event
                self.portfolio.update_market_price(event.symbol, event.close, event.timestamp)
                self.strategy.calculate_signals(event)

            elif event.type == EventType.SIGNAL:
                order = self.portfolio.update_signal(event)
                if order is not None:
                    self.event_queue.put(order)

            elif event.type == EventType.ORDER:
                bar = self._latest_bar_by_symbol.get(event.symbol)
                if bar is None:
                    continue
                fills = self.execution.execute_order(event, bar)
                for fill in fills:
                    self.event_queue.put(fill)

            elif event.type == EventType.FILL:
                self.portfolio.update_fill(event)

    def run(self):
        start = time.time()
        while self.data_handler.continue_backtest:
            self.data_handler.update_bars()
            self._run_event_loop()
        elapsed = time.time() - start
        logger.info("Backtest complete in %.2fs. %d fills generated.", elapsed, len(self.portfolio.fills))
        return self.portfolio
