"""Public client.

Composed from small mixins so no single module grows past the size limit:

- :class:`CoreMixin` owns state and lifecycle
- :class:`FlowMixin` owns cache lookup, single-flight and fallback
- :class:`QuotesMixin` and :class:`SeriesMixin` own data operations
- :class:`ListingMixin` owns universe listings
"""

from __future__ import annotations

from quotestack.client.core import CoreMixin
from quotestack.client.flow import FlowMixin
from quotestack.client.listing import ListingMixin
from quotestack.client.quotes import QuotesMixin
from quotestack.client.series import SeriesMixin

__all__ = ["MarketData"]


class MarketData(QuotesMixin, SeriesMixin, ListingMixin, FlowMixin, CoreMixin):
    """Entry point for every quotestack call.

    Args:
        cache: Cache implementation. Defaults to an in-memory cache.
        ttl: Per-capability TTL overrides in seconds.
        max_stale: Per-capability stale limits in seconds.
        sources: Source registry keyed by name. Defaults to the built-ins.
        proxy: Outbound proxy passed to the default sources.
        source_priority: Overrides the routing order per capability.
        cooldown: Cooldown policy. Defaults to 30s after one failure.
        bucket: Rate limiter. Defaults to 5 req/s with a burst of 10.

    Example:
        >>> async with MarketData() as client:
        ...     quote = await client.quote("600519")
    """
