"""Enumerations shared across the package."""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "Adjust",
    "AssetClass",
    "Capability",
    "Confidence",
    "Interval",
    "Market",
    "QuoteStatus",
]


class AssetClass(StrEnum):
    """Business classification of a tradable object.

    Orthogonal to :class:`Market`: a US-listed ETF is ``FUND`` + ``US``.
    """

    STOCK = "STOCK"
    FUND = "FUND"
    CRYPTO = "CRYPTO"


class Market(StrEnum):
    """Where the instrument is traded."""

    CN = "CN"
    US = "US"
    CRYPTO = "CRYPTO"


class Capability(StrEnum):
    """A data capability an instrument or a source may provide."""

    RESOLVE = "RESOLVE"
    QUOTE = "QUOTE"
    HISTORY = "HISTORY"
    NAV = "NAV"
    PROFILE = "PROFILE"
    HOLDINGS = "HOLDINGS"
    BENCHMARK = "BENCHMARK"
    ESTIMATE = "ESTIMATE"
    FX = "FX"
    LIST = "LIST"


class Interval(StrEnum):
    """Bar interval.

    Minute intervals only reach back about one month on most sources;
    the one-minute interval is limited to the current trading day.
    """

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    M60 = "60m"
    D1 = "1d"
    W1 = "1w"
    MO1 = "1M"

    @property
    def is_intraday(self) -> bool:
        """Whether this interval is intraday (minute level)."""
        return self in _INTRADAY


_INTRADAY = frozenset({Interval.M1, Interval.M5, Interval.M15, Interval.M30, Interval.M60})


class Adjust(StrEnum):
    """Price adjustment mode.

    Use ``NONE`` for money math and ``QFQ`` for charting.
    """

    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


class Confidence(StrEnum):
    """How much to trust a resolved identifier."""

    EXACT = "exact"
    INFERRED = "inferred"
    PARTIAL = "partial"


class QuoteStatus(StrEnum):
    """Freshness of a quote."""

    REALTIME = "REALTIME"
    HISTORICAL = "HISTORICAL"
    UNAVAILABLE = "UNAVAILABLE"
