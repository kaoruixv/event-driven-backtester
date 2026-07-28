"""
events.py
---------
Defines the Event hierarchy that flows through the central event queue.

The engine is event-driven (not vectorized): the simulation clock only
advances when a MarketEvent is popped from the queue, and every downstream
action (signal generation, order routing, fill simulation) happens in
response to an event rather than as a bulk array operation. This is what
prevents look-ahead bias by construction -- a strategy literally cannot see
a bar until the event for that bar has been dispatched.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EventType(Enum):
    MARKET = "MARKET"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"


@dataclass
class Event:
    type: EventType


@dataclass
class MarketEvent(Event):
    """New market data (a bar) is available for one or more symbols."""
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    type: EventType = field(default=EventType.MARKET, init=False)


@dataclass
class SignalEvent(Event):
    """A strategy has generated a directional opinion."""
    timestamp: datetime
    symbol: str
    direction: str          # "LONG", "SHORT", "EXIT"
    strength: float = 1.0   # 0-1, used for position sizing
    type: EventType = field(default=EventType.SIGNAL, init=False)


@dataclass
class OrderEvent(Event):
    """Portfolio has decided to send an order to the execution handler."""
    timestamp: datetime
    symbol: str
    order_type: str   # "MKT" or "LMT"
    quantity: float    # signed: positive = buy, negative = sell
    limit_price: float | None = None
    type: EventType = field(default=EventType.ORDER, init=False)


@dataclass
class FillEvent(Event):
    """Execution handler reports back what actually happened to an order."""
    timestamp: datetime
    symbol: str
    quantity: float          # signed, filled quantity (may be partial)
    fill_price: float        # realized average price including slippage
    commission: float
    slippage: float          # $ slippage vs. arrival/decision price
    latency_ms: float        # simulated latency between decision and fill
    remaining_quantity: float = 0.0   # unfilled portion (partial fill)
    type: EventType = field(default=EventType.FILL, init=False)
