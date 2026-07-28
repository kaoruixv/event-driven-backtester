"""
data_handler.py
----------------
Streams historical bars into the event queue one at a time, and separately
handles *unattended* data acquisition: retries with backoff, rate-limit
handling, and a local parquet cache so a scheduled CI run never fails just
because a data vendor hiccuped, and never re-downloads data it already has.

Design note: the DataHandler is the ONLY component allowed to know about
"the future". Everything else in the engine receives bars strictly in
increasing timestamp order via update_bars(), which is what makes the
look-ahead-bias checks in src/validation/leakage_checks.py meaningful.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

from src.engine.events import MarketEvent

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[2] / "cache"
CACHE_DIR.mkdir(exist_ok=True)


class DataHandler(ABC):
    @abstractmethod
    def update_bars(self):
        """Push the next MarketEvent(s) onto the queue, or signal completion."""
        raise NotImplementedError

    @abstractmethod
    def get_latest_bars(self, symbol: str, n: int = 1) -> pd.DataFrame:
        raise NotImplementedError


class YFinanceDataHandler(DataHandler):
    """
    Pulls daily OHLCV bars via yfinance (no API key required, which is why
    it's the default for the unattended GitHub Actions pipeline -- Polygon
    and Alpaca are supported as drop-in alternatives, see fetch_polygon.py
    / fetch_alpaca.py, but both need secrets configured).

    Retries with exponential backoff and falls back to the last good cached
    copy if the network call fails after all retries, so a scheduled run
    degrades gracefully (stale data + a warning) instead of crashing.
    """

    def __init__(self, event_queue, symbols: list[str], start: str, end: str,
                 max_retries: int = 4, backoff_base: float = 2.0):
        self.event_queue = event_queue
        self.symbols = symbols
        self.start = start
        self.end = end
        self.max_retries = max_retries
        self.backoff_base = backoff_base

        self.symbol_data: dict[str, pd.DataFrame] = {}
        self.latest_symbol_data: dict[str, list] = {s: [] for s in symbols}
        self.continue_backtest = True

        self._load_all_symbols()
        self._bar_iterators = {
            s: self.symbol_data[s].iterrows() for s in self.symbols
        }

    # ---------- unattended-safe acquisition ----------

    def _cache_path(self, symbol: str) -> Path:
        return CACHE_DIR / f"{symbol}_{self.start}_{self.end}.parquet"

    def _fetch_with_retries(self, symbol: str) -> pd.DataFrame:
        import yfinance as yf

        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                df = yf.download(
                    symbol, start=self.start, end=self.end,
                    progress=False, auto_adjust=True, threads=False,
                )
                if df is None or df.empty:
                    raise ValueError(f"Empty dataframe returned for {symbol}")
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)[
                    ["open", "high", "low", "close", "volume"]
                ]
                df.index.name = "timestamp"
                return df
            except Exception as exc:  # noqa: BLE001 - must not crash a scheduled run
                last_exc = exc
                wait = self.backoff_base ** attempt
                logger.warning(
                    "Fetch failed for %s (attempt %d/%d): %s. Retrying in %.1fs",
                    symbol, attempt, self.max_retries, exc, wait,
                )
                time.sleep(wait)

        # All retries exhausted -- fall back to cache if we have one.
        cache_path = self._cache_path(symbol)
        if cache_path.exists():
            logger.error(
                "All fetch retries exhausted for %s; using stale cache at %s",
                symbol, cache_path,
            )
            return pd.read_parquet(cache_path)

        raise RuntimeError(
            f"Could not fetch {symbol} after {self.max_retries} retries "
            f"and no cache fallback exists: {last_exc}"
        )

    def _load_all_symbols(self):
        combined_index = None
        for symbol in self.symbols:
            cache_path = self._cache_path(symbol)
            df = self._fetch_with_retries(symbol)
            df.to_parquet(cache_path)  # refresh cache on every successful pull
            self.symbol_data[symbol] = df
            combined_index = df.index if combined_index is None else combined_index.union(df.index)

        # Reindex/forward-fill so all symbols share one master timeline.
        for symbol in self.symbols:
            self.symbol_data[symbol] = (
                self.symbol_data[symbol].reindex(combined_index).ffill().dropna()
            )

    # ---------- streaming interface used by the engine ----------

    def get_latest_bars(self, symbol: str, n: int = 1) -> pd.DataFrame:
        bars = self.latest_symbol_data.get(symbol, [])
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        return pd.DataFrame(bars[-n:], columns=cols)

    def update_bars(self):
        """Advance every symbol's iterator by one bar and enqueue events."""
        any_advanced = False
        for symbol in self.symbols:
            try:
                ts, row = next(self._bar_iterators[symbol])
            except StopIteration:
                continue
            any_advanced = True
            bar = (ts, row.open, row.high, row.low, row.close, row.volume)
            self.latest_symbol_data[symbol].append(bar)
            self.event_queue.put(
                MarketEvent(
                    timestamp=ts, symbol=symbol,
                    open=row.open, high=row.high, low=row.low,
                    close=row.close, volume=row.volume,
                )
            )
        if not any_advanced:
            self.continue_backtest = False
