"""quotestack — multi-source market data adapter.

A unified adapter layer for A-shares, US stocks, mutual funds and crypto.
"""

from quotestack.client import MarketData
from quotestack.errors import (
    AmbiguousError,
    ClientBrokenError,
    EmptyResponseError,
    InvalidArgumentError,
    MarketDataError,
    NotFoundError,
    SchemaChangedError,
    UnauthorizedError,
    UnsupportedError,
    UpstreamError,
)
from quotestack.models import (
    Adjust,
    AssetClass,
    Bar,
    Capability,
    Instrument,
    Interval,
    Market,
    Quote,
    QuoteStatus,
)

__version__ = "0.1.0"

__all__ = [
    "Adjust",
    "AmbiguousError",
    "AssetClass",
    "Bar",
    "Capability",
    "ClientBrokenError",
    "EmptyResponseError",
    "Instrument",
    "Interval",
    "InvalidArgumentError",
    "Market",
    "MarketData",
    "MarketDataError",
    "NotFoundError",
    "Quote",
    "QuoteStatus",
    "SchemaChangedError",
    "UnauthorizedError",
    "UnsupportedError",
    "UpstreamError",
    "__version__",
]
