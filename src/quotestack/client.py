"""Public client.

The client owns resolution, caching and the source. Callers pass a code,
an asset class and a market -- never a source-specific identifier.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import TracebackType

from quotestack.cache import CacheEntry, MemoryCache, is_fresh, make_key, merge_ttl
from quotestack.errors import UnsupportedError, UpstreamError
from quotestack.identity import resolve as resolve_rules
from quotestack.models import (
    Adjust,
    AssetClass,
    Bar,
    Capability,
    Instrument,
    Interval,
    Market,
    Quote,
)
from quotestack.sources import EastMoneySource

__all__ = ["MarketData"]


class MarketData:
    """Entry point for every quotestack call.

    Args:
        cache: Cache implementation. Defaults to an in-memory cache.
        ttl: Per-capability TTL overrides in seconds.
        source: Source adapter. Defaults to :class:`EastMoneySource`.

    Example:
        >>> async with MarketData() as client:
        ...     quote = await client.quote("600519", AssetClass.STOCK, Market.CN)
    """

    def __init__(
        self,
        *,
        cache: MemoryCache | None = None,
        ttl: Mapping[Capability, float] | None = None,
        source: EastMoneySource | None = None,
    ) -> None:
        """Create a client."""
        self._cache = cache or MemoryCache()
        self._ttl = merge_ttl(ttl)
        self._source = source or EastMoneySource()

    async def __aenter__(self) -> MarketData:
        """Enter the async context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the client on context exit."""
        await self.aclose()

    async def aclose(self) -> None:
        """Release resources held by the underlying source."""
        await self._source.aclose()

    def resolve(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.STOCK,
        market: Market = Market.CN,
    ) -> Instrument:
        """Resolve a code into an instrument using prefix rules.

        Args:
            code: Raw code, e.g. ``600519``.
            asset_class: Business classification.
            market: Trading venue.

        Returns:
            The resolved instrument.

        Raises:
            InvalidArgumentError: The code does not fit the market.
        """
        return resolve_rules(code, asset_class, market)

    async def quote(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.STOCK,
        market: Market = Market.CN,
    ) -> Quote:
        """Fetch the latest quote for one instrument.

        Args:
            code: Raw code.
            asset_class: Business classification.
            market: Trading venue.

        Returns:
            The current quote. When the upstream fails and a cached value
            exists, that value is returned with ``stale`` set.

        Raises:
            UnsupportedError: The instrument has no realtime quote.
            UpstreamError: The source failed and nothing was cached.
        """
        instrument = self.resolve(code, asset_class, market)
        self._require(instrument, Capability.QUOTE)

        key = make_key(Capability.QUOTE, instrument.id)
        entry = self._fresh_entry(key, Capability.QUOTE)
        if entry is not None and isinstance(entry.value, Quote):
            return entry.value

        try:
            quotes = await self._source.quote([instrument])
        except UpstreamError:
            stale = self._cache.get(key)
            if stale is not None and isinstance(stale.value, Quote):
                return replace(stale.value, stale=True)
            raise

        quote = quotes[0]
        self._cache.set(key, quote, quote.source)
        return quote

    async def history(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.STOCK,
        market: Market = Market.CN,
        *,
        interval: Interval = Interval.D1,
        adjust: Adjust = Adjust.QFQ,
        limit: int = 250,
    ) -> list[Bar]:
        """Fetch historical bars for one instrument.

        Args:
            code: Raw code.
            asset_class: Business classification.
            market: Trading venue.
            interval: Bar interval.
            adjust: Price adjustment mode.
            limit: Maximum number of bars, counted from the newest bar.

        Returns:
            Bars in ascending date order.

        Raises:
            UnsupportedError: The instrument has no historical bars.
            UpstreamError: The source failed.
        """
        instrument = self.resolve(code, asset_class, market)
        self._require(instrument, Capability.HISTORY)

        key = make_key(
            Capability.HISTORY,
            instrument.id,
            interval.value,
            adjust.value,
        )
        entry = self._fresh_entry(key, Capability.HISTORY)
        if entry is not None and isinstance(entry.value, list):
            cached: list[Bar] = entry.value
            return cached[-limit:]

        bars = await self._source.history(instrument, interval, adjust, limit)
        self._cache.set(key, bars, self._source.meta.name)
        return bars

    def _fresh_entry(self, key: str, capability: Capability) -> CacheEntry | None:
        entry = self._cache.get(key)
        if entry is None or not is_fresh(entry, self._ttl[capability]):
            return None
        return entry

    def _require(self, instrument: Instrument, capability: Capability) -> None:
        if not instrument.supports(capability):
            raise UnsupportedError(
                f"{instrument.id} has no {capability.value.lower()} data",
                instrument=instrument.id,
                capability=capability.value,
                available=sorted(c.value for c in instrument.capabilities),
            )

    def cache_stats(self) -> dict[str, int]:
        """Return a snapshot of cache occupancy."""
        return {"entries": len(self._cache)}
