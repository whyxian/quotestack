"""Synchronous wrapper around the async client.

``asyncio.run()`` per call would create and destroy an event loop every time,
losing the in-process cache and defeating single-flight. Instead a daemon
thread owns one loop for the lifetime of the wrapper.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine, Mapping
from types import TracebackType
from typing import Any, TypeVar

from quotestack.client import MarketData
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

__all__ = ["SyncMarketData"]

T = TypeVar("T")


class SyncMarketData:
    """Blocking facade over :class:`MarketData`.

    Use this from scripts and synchronous code. Every call is executed on a
    dedicated background thread so module-level state survives between calls.

    Args:
        ttl: Per-capability TTL overrides in seconds.
        max_stale: Per-capability stale limits in seconds.
        **kwargs: Forwarded to :class:`MarketData`.

    Example:
        >>> with SyncMarketData() as client:
        ...     quote = client.quote("600519")
    """

    def __init__(
        self,
        *,
        ttl: Mapping[Capability, float] | None = None,
        max_stale: Mapping[Capability, float] | None = None,
        **kwargs: Any,
    ) -> None:
        """Start the background loop and build the async client."""
        self._loop = asyncio.new_event_loop()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run_loop,
            name="quotestack-loop",
            daemon=True,
        )
        self._thread.start()
        self._client = MarketData(ttl=ttl, max_stale=max_stale, **kwargs)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro: Coroutine[Any, Any, T]) -> T:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def __enter__(self) -> SyncMarketData:
        """Enter the context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Stop the loop on context exit."""
        self.close()

    def close(self) -> None:
        """Close the client and stop the background loop.

        Safe to call more than once: the second call is a no-op. Without the
        guard it would schedule work on an already stopped loop and block
        forever.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._call(self._client.aclose())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5.0)

    def resolve(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.STOCK,
        market: Market = Market.CN,
    ) -> Instrument:
        """Resolve a code into an instrument."""
        return self._client.resolve(code, asset_class, market)

    def quote(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.STOCK,
        market: Market = Market.CN,
        *,
        max_age: float | None = None,
    ) -> Quote:
        """Fetch the latest quote, blocking until done."""
        return self._call(self._client.quote(code, asset_class, market, max_age=max_age))

    def history(
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
        """Fetch historical bars, blocking until done."""
        return self._call(
            self._client.history(
                code,
                asset_class,
                market,
                interval=interval,
                adjust=adjust,
                limit=limit,
                max_age=max_age,
            )
        )

    def cache_stats(self) -> dict[str, int]:
        """Return cache occupancy."""
        return self._client.cache_stats()
