"""Bar: one OHLCV candle."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

__all__ = ["Bar"]


@dataclass(frozen=True, slots=True)
class Bar:
    """A single OHLCV candle.

    ``date`` is a trading day (calendar concept, no timezone). ``volume`` is
    expressed in the smallest unit: shares for equities, coins for crypto.
    Sources that report lots must convert before constructing a Bar.

    Args:
        date: Trading day this candle covers.
        open: Opening price, decimal string.
        high: Highest price, decimal string.
        low: Lowest price, decimal string.
        close: Closing price, decimal string.
        volume: Traded volume in the smallest unit.
        amount: Traded turnover, when the source provides it.
    """

    date: dt.date
    open: str
    high: str
    low: str
    close: str
    volume: str
    amount: str | None = None
