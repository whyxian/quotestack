"""Quote: a single point-in-time price."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from quotestack.models.enums import QuoteStatus

__all__ = ["Quote"]


@dataclass(frozen=True, slots=True)
class Quote:
    """A realtime or historical price for one instrument.

    Price fields are strings on purpose: they carry exact decimals across
    JSON and language boundaries without float rounding.

    Args:
        instrument_id: Canonical instrument identifier.
        price: Latest price, as a decimal string.
        currency: Denomination currency.
        source: Name of the source that produced this quote.
        ts: Instant the price was observed, timezone-aware.
        change: Absolute change, as a decimal string.
        change_pct: Percentage change, e.g. ``-1.76`` means -1.76%.
        status: Whether the price is realtime, from history, or unavailable.
        stale: True when served from cache after the upstream failed.
    """

    instrument_id: str
    price: str
    currency: str
    source: str
    ts: datetime
    change: str | None = None
    change_pct: float | None = None
    status: QuoteStatus = QuoteStatus.REALTIME
    stale: bool = False

    @property
    def is_usable(self) -> bool:
        """Whether the quote carries an actual price."""
        return self.status is not QuoteStatus.UNAVAILABLE
