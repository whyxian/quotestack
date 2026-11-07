"""Public client.

The client owns resolution, caching, single-flight and the source. Callers pass
a code, an asset class and a market -- never a source-specific identifier.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
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
from quotestack.errors import (
    MarketDataError,
    UnavailableError,
    UnsupportedError,
    UpstreamError,
)
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
    QuoteResult,
)
from quotestack.resilience import Cooldown, TokenBucket
from quotestack.sources import EastMoneySource, TencentSource
from quotestack.sources.routing import route

__all__ = ["MarketData"]

_log = get_logger("client")


def _default_sources() -> dict[str, object]:
    """Build the built-in source registry."""
    return {
        "eastmoney": EastMoneySource(),
        "tencent": TencentSource(),
    }


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
        sources: Mapping[str, object] | None = None,
        source_priority: Mapping[str, Sequence[str]] | None = None,
        cooldown: Cooldown | None = None,
        bucket: TokenBucket | None = None,
    ) -> None:
        """Create a client."""
        self._cache = cache if cache is not None else MemoryCache()
        self._ttl = merge_ttl(ttl)
        self._max_stale = {**default_max_stale(), **(max_stale or {})}
        self._sources: dict[str, object] = (
            dict(sources) if sources is not None else _default_sources()
        )
        self._priority = dict(source_priority or {})
        self._cooldown = cooldown if cooldown is not None else Cooldown()
        self._bucket = bucket if bucket is not None else TokenBucket()
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
        for source in self._sources.values():
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()

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
        *,
        max_age: float | None = None,
    ) -> Quote:
        """Fetch the latest quote for one instrument.

        Args:
            code: Raw code.
            asset_class: Business classification.
            market: Trading venue.
            max_age: Accept cached data up to this many seconds old. Overrides
                the configured TTL for this call only; ``0`` forces a fetch.

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
            instrument,
            fetch=lambda src: self._fetch_quote(src, instrument),
            is_expected=lambda item: isinstance(item, Quote),
            mark_stale=self._mark_quote_stale,
            max_age=max_age,
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
        max_age: float | None = None,
    ) -> list[Bar]:
        """Fetch historical bars for one instrument.

        Args:
            code: Raw code.
            asset_class: Business classification.
            market: Trading venue.
            interval: Bar interval.
            adjust: Price adjustment mode.
            limit: Maximum number of bars, counted from the newest bar.
            max_age: Accept cached data up to this many seconds old.

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
            instrument,
            fetch=lambda src: self._fetch_history(src, instrument, interval, adjust, limit),
            is_expected=lambda item: isinstance(item, list),
            max_age=max_age,
        )
        return cast("list[Bar]", bars)[-limit:]

    async def _cached(
        self,
        key: str,
        capability: Capability,
        instrument: Instrument,
        *,
        fetch: Callable[[object], Awaitable[object]],
        is_expected: Callable[[object], bool],
        mark_stale: Callable[[object], object] | None = None,
        max_age: float | None = None,
    ) -> object:
        entry = self._cache.get(key)
        ttl = self._ttl[capability] if max_age is None else max_age
        state = classify(entry, ttl, self._max_stale[capability])
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
            instrument,
            fetch,
            mark_stale,
        )

    async def _single_flight(
        self,
        key: str,
        capability: Capability,
        state: CacheState,
        entry: CacheEntry | None,
        instrument: Instrument,
        fetch: Callable[[object], Awaitable[object]],
        mark_stale: Callable[[object], object] | None,
    ) -> object:
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(
                self._fetch_and_store(key, capability, state, entry, instrument, fetch, mark_stale)
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
        instrument: Instrument,
        fetch: Callable[[object], Awaitable[object]],
        mark_stale: Callable[[object], object] | None,
    ) -> object:
        attempts: list[dict[str, object]] = []
        for name in self._candidates(instrument, capability):
            source = self._sources.get(name)
            if source is None:
                continue
            if self._cooldown.is_cooling(name):
                attempts.append(
                    {
                        "source": name,
                        "reason": "cooldown",
                        "remaining": round(self._cooldown.remaining(name), 1),
                    }
                )
                continue

            await self._bucket.acquire()
            try:
                value = await fetch(source)
            except UpstreamError as exc:
                if self._cooldown.mark_failed(name):
                    event(
                        _log,
                        logging.WARNING,
                        "cooldown",
                        source=name,
                        action="mark",
                        duration=self._cooldown.duration,
                        hint=f"{name} failed with {exc.code}; skipping it briefly",
                    )
                attempts.append({"source": name, "reason": exc.code})
                continue

            self._cooldown.mark_ok(name)
            self._cache.set(key, value, name)
            return value

        reason = "all sources failed"
        return self._fallback(
            key,
            capability,
            state,
            entry,
            mark_stale,
            reason=reason,
            attempts=attempts,
        )

    async def quote_many(
        self,
        items: Sequence[tuple[str, AssetClass, Market]],
    ) -> list[QuoteResult]:
        """Fetch quotes for several instruments in one call.

        Unlike :meth:`quote`, a failure in one item never fails the batch: the
        result list is the same length and order as ``items``, and each entry
        either carries a quote or an error string.

        Args:
            items: ``(code, asset_class, market)`` triples.

        Returns:
            One :class:`QuoteResult` per input item.
        """
        results: list[QuoteResult | None] = [None] * len(items)
        pending: list[tuple[int, Instrument]] = []

        for index, (code, asset_class, market) in enumerate(items):
            try:
                instrument = self.resolve(code, asset_class, market)
                self._require(instrument, Capability.QUOTE)
            except MarketDataError as exc:
                results[index] = QuoteResult(error=f"{exc.code}: {exc.message}")
                continue
            key = make_key(Capability.QUOTE, instrument.id)
            entry = self._fresh_entry(key, Capability.QUOTE)
            if entry is not None and isinstance(entry.value, Quote):
                results[index] = QuoteResult(instrument=instrument, quote=entry.value)
                continue
            pending.append((index, instrument))

        for group in self._group_by_market(pending):
            await self._fetch_group(group, results)

        return [
            result
            if result is not None
            else QuoteResult(error="UNAVAILABLE: no source served this item")
            for result in results
        ]

    @staticmethod
    def _group_by_market(
        pending: Sequence[tuple[int, Instrument]],
    ) -> list[list[tuple[int, Instrument]]]:
        groups: dict[tuple[AssetClass, Market], list[tuple[int, Instrument]]] = {}
        for index, instrument in pending:
            groups.setdefault((instrument.asset_class, instrument.market), []).append(
                (index, instrument)
            )
        return list(groups.values())

    async def _fetch_group(
        self,
        group: list[tuple[int, Instrument]],
        results: list[QuoteResult | None],
    ) -> None:
        instruments = [instrument for _, instrument in group]
        asset_class = instruments[0].asset_class
        market = instruments[0].market

        for name in self._priority.get(
            Capability.QUOTE.value,
            route(asset_class, market, Capability.QUOTE),
        ):
            source = self._sources.get(name)
            if source is None or self._cooldown.is_cooling(name):
                continue
            await self._bucket.acquire()
            try:
                quotes = await source.quote(instruments)  # type: ignore[attr-defined]
            except UpstreamError:
                self._cooldown.mark_failed(name)
                continue

            self._cooldown.mark_ok(name)
            for (index, instrument), quote in zip(group, quotes, strict=True):
                results[index] = QuoteResult(instrument=instrument, quote=quote)
                self._cache.set(make_key(Capability.QUOTE, instrument.id), quote, name)
            return

        for index, instrument in group:
            results[index] = QuoteResult(
                instrument=instrument,
                error=f"UNAVAILABLE: no source served {instrument.id}",
            )

    def _candidates(self, instrument: Instrument, capability: Capability) -> list[str]:
        """Ordered source names to try for this instrument.

        A source that cannot handle the instrument raises ``UpstreamError``,
        which simply moves the attempt to the next one. Filtering here by alias
        would silently skip custom sources that use their own naming.
        """
        ordered = list(self._priority.get(capability.value, ()))
        if not ordered:
            ordered = list(route(instrument.asset_class, instrument.market, capability))
        return ordered

    def _fallback(
        self,
        key: str,
        capability: Capability,
        state: CacheState,
        entry: CacheEntry | None,
        mark_stale: Callable[[object], object] | None,
        *,
        reason: str,
        attempts: list[dict[str, object]] | None = None,
    ) -> object:
        if state is CacheState.STALE and entry is not None:
            stale_value = mark_stale(entry.value) if mark_stale else entry.value
            event(
                _log,
                logging.WARNING,
                "stale_served",
                capability=capability.value,
                key=key,
                source=entry.source,
                hint=f"serving cached value because {reason}",
            )
            return stale_value
        raise UnavailableError(reason, attempts=attempts or [])

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

    def health(self) -> dict[str, object]:
        """Return the current runtime state.

        Mirrors the shape of the HTTP ``/healthz`` payload so the CLI and the
        service report the same information.
        """
        sources: dict[str, object] = {}
        degraded = False
        for name, source in self._sources.items():
            meta = source.meta  # type: ignore[attr-defined]
            cooling = self._cooldown.is_cooling(name)
            degraded = degraded or cooling
            sources[name] = {
                "state": "cooling" if cooling else "ok",
                "cooldown_remaining": round(self._cooldown.remaining(name), 1),
                "timeout": meta.timeout,
                "capabilities": sorted(c.value for c in meta.capabilities),
            }

        return {
            "status": "degraded" if degraded else "ok",
            "proxy": os.environ.get("QUOTESTACK_PROXY_URL")
            or os.environ.get("HTTPS_PROXY")
            or None,
            "sources": sources,
            "cache": self.cache_stats(),
        }

    async def _fetch_quote(self, source: object, instrument: Instrument) -> object:
        quotes = await source.quote([instrument])  # type: ignore[attr-defined]
        return quotes[0]

    async def _fetch_history(
        self,
        source: object,
        instrument: Instrument,
        interval: Interval,
        adjust: Adjust,
        limit: int,
    ) -> object:
        return await source.history(  # type: ignore[attr-defined]
            instrument, interval, adjust, limit
        )

    @staticmethod
    def _mark_quote_stale(value: object) -> object:
        if isinstance(value, Quote):
            return replace(value, stale=True)
        return value
