"""
walk_forward.py
----------------
Two things live here:

1. generate_walk_forward_windows(): splits the full date range into rolling
   train/test windows so a strategy is always evaluated only on data that
   comes strictly after the window it was "tuned" on (even though this
   demo strategy has no fitted parameters, the harness is what matters for
   a real strategy dropped into this engine).

2. LookAheadBiasChecker: a lightweight runtime assertion layer. It hooks
   the MarketEvent stream and fails loudly if a strategy or execution
   component is ever handed a timestamp that hasn't been seen yet in the
   dispatched sequence -- this is what actually enforces "no look-ahead"
   rather than just hoping the event loop was written correctly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd


@dataclass
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def generate_walk_forward_windows(
    start: str, end: str, train_days: int = 252, test_days: int = 63, step_days: int | None = None,
) -> list[WalkForwardWindow]:
    step_days = step_days or test_days
    dates = pd.date_range(start=start, end=end, freq="B")
    windows = []
    i = 0
    while True:
        train_start_idx = i
        train_end_idx = train_start_idx + train_days
        test_end_idx = train_end_idx + test_days
        if test_end_idx >= len(dates):
            break
        windows.append(
            WalkForwardWindow(
                train_start=dates[train_start_idx],
                train_end=dates[train_end_idx - 1],
                test_start=dates[train_end_idx],
                test_end=dates[test_end_idx - 1],
            )
        )
        i += step_days
    return windows


class LookAheadBiasChecker:
    """
    Attach to the backtest's event queue consumption. Call `.observe(ts)`
    every time a MarketEvent is dispatched, and `.assert_visible(ts)` any
    time a component reads a timestamp -- e.g. from a cached bar -- to
    confirm it isn't reading ahead of the dispatch clock.
    """

    def __init__(self):
        self.max_dispatched_ts: datetime | None = None
        self.violations: list[str] = []

    def observe(self, ts: datetime):
        if self.max_dispatched_ts is None or ts > self.max_dispatched_ts:
            self.max_dispatched_ts = ts

    def assert_visible(self, ts: datetime, context: str = ""):
        if self.max_dispatched_ts is not None and ts > self.max_dispatched_ts:
            msg = f"Look-ahead bias detected: accessed {ts} before it was dispatched ({context})"
            self.violations.append(msg)
            raise AssertionError(msg)

    def report(self) -> dict:
        return {"violations": self.violations, "clean": len(self.violations) == 0}
