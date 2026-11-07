"""Public client.

The client owns resolution, caching, single-flight and the source. Callers pass
a code, an asset class and a market -- never a source-specific identifier.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from types import TracebackType
from typing import cast

from quotestack.cache import (
    CacheEntry,
    CacheState,
    MemoryCache,
    classify,
    default_max_stale,
    is_fresh,
    make_key,
    merge_ttl,
)
from quotestack.errors import UnsupportedError, UpstreamError
from quotestack.identity import resolve as resolve_rules
from quotestack.logging import event, get_logger
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

_log = get_logger("client")


class MarketData:
    """Entry point for every quotestack call.

    Args:
        cache: Cache implementation. Defaults to an in-memory cache.
        ttl: Per-capability TTL overrides in seconds.
        max_stale: Per-capability stale limits in seconds.
        source: Source adapter. Defaults to :class:`EastMoneySource`.
    """

    def __init__(
        self,
        *,
        cache: MemoryCache | None = None,
        ttl: Mapping[Capability, float] | None = None,
        max_stale: Mapping[Capability, float] | None = None,
        source: EastMoneySource | None = None,
    ) -> None:
        """Create a client."""
        self._cache = cache or MemoryCache()
        self._ttl = merge_ttl(ttl)
        self._max_stale = {**default_max_stale(), **(max_stale or {})}
        self._source = source or EastMoneySource()
        self._inflight: dict[str, asyncio.Task[object]] = {}

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
        for task in self._inflight.values():
            task.cancel()
        self._inflight.clear()
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
        instrument = resolve_rules(code, asset_class, market)
        event(
            _log,
            logging.DEBUG,
            "resolve",
            code=code,
            market=market.value,
            asset_class=asset_class.value,
            instrument=instrument.id,
            confidence=instrument.confidence.value,
            aliases=dict(instrument.aliases),
        )
        return instrument

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
            The current quote. When the upstream fails and a cached value is
            within its ``max_stale`` window, that value is returned with
            ``stale`` set.

        Raises:
            UnsupportedError: The instrument has no realtime quote.
            UpstreamError: The source failed and no usable cache exists.
        """
        instrument = self.resolve(code, asset_class, market)
        self._require(instrument, Capability.QUOTE)
        key = make_key(Capability.QUOTE, instrument.id)

        value = await self._cached(
            key,
            Capability.QUOTE,
            fetch=lambda: self._fetch_quote(instrument),
            is_expected=lambda item: isinstance(item, Quote),
            mark_stale=self._mark_quote_stale,
        )
        return cast("Quote", value)

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
            UpstreamError: The source failed and no usable cache exists.
        """
        instrument = self.resolve(code, asset_class, market)
        self._require(instrument, Capability.HISTORY)
        key = make_key(
            Capability.HISTORY,
            instrument.id,
            interval.value,
            adjust.value,
        )

        bars = await self._cached(
            key,
            Capability.HISTORY,
            fetch=lambda: self._fetch_history(instrument, interval, adjust, limit),
            is_expected=lambda item: isinstance(item, list),
        )
        return cast("list[Bar]", bars)[-limit:]

    async def _cached(
        self,
        key: str,
        capability: Capability,
        *,
        fetch: Callable[[], Awaitable[object]],
        is_expected: Callable[[object], bool],
        mark_stale: Callable[[object], object] | None = None,
    ) -> object:
        entry = self._cache.get(key)
        state = classify(entry, self._ttl[capability], self._max_stale[capability])
        event(
            _log,
            logging.DEBUG,
            "cache_lookup",
            key=key,
            state=state.value,
            capability=capability.value,
        )

        if state is CacheState.FRESH and entry is not None and is_expected(entry.value):
            return entry.value

        return await self._single_flight(
            key,
            capability,
            state,
            entry,
            fetch,
            mark_stale,
        )

    async def _single_flight(
        self,
        key: str,
        capability: Capability,
        state: CacheState,
        entry: CacheEntry | None,
        fetch: Callable[[], Awaitable[object]],
        mark_stale: Callable[[object], object] | None,
    ) -> object:
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(
                self._fetch_and_store(key, capability, state, entry, fetch, mark_stale)
            )
            self._inflight[key] = task
            task.add_done_callback(lambda _: self._inflight.pop(key, None))
        return await asyncio.shield(task)

    async def _fetch_and_store(
        self,
        key: str,
        capability: Capability,
        state: CacheState,
        entry: CacheEntry | None,
        fetch: Callable[[], Awaitable[object]],
        mark_stale: Callable[[object], object] | None,
    ) -> object:
        try:
            value = await fetch()
        except UpstreamError as exc:
            if state is CacheState.STALE and entry is not None:
                stale_value = mark_stale(entry.value) if mark_stale else entry.value
                event(
                    _log,
                    logging.WARNING,
                    "stale_served",
                    capability=capability.value,
                    key=key,
                    source=entry.source,
                    hint=f"upstream failed ({exc.code}), serving cached value",
                )
                return stale_value
            raise

        self._cache.set(key, value, self._source.meta.name)
        return value

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

    async def _fetch_quote(self, instrument: Instrument) -> object:
        quotes = await self._source.quote([instrument])
        return quotes[0]

    async def _fetch_history(
        self,
        instrument: Instrument,
        interval: Interval,
        adjust: Adjust,
        limit: int,
    ) -> object:
        return await self._source.history(instrument, interval, adjust, limit)

    @staticmethod
    def _mark_quote_stale(value: object) -> object:
        if isinstance(value, Quote):
            return replace(value, stale=True)
        return value
