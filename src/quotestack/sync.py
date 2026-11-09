"""Synchronous wrapper around the async client.

``asyncio.run()`` per call would create and destroy an event loop every time,
losing the in-process cache and defeating single-flight. Instead a daemon
thread owns one loop for the lifetime of the wrapper.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import threading
from collections.abc import Coroutine, Iterator, Mapping, Sequence
from concurrent.futures import TimeoutError as FuturesTimeoutError
from types import TracebackType
from typing import Any, TypeVar, cast

from quotestack.client import MarketData
from quotestack.logging import get_logger
from quotestack.models import (
    Adjust,
    AssetClass,
    Bar,
    BenchmarkCurve,
    Capability,
    Estimate,
    FxRate,
    Instrument,
    InstrumentSummary,
    Interval,
    Market,
    NavPoint,
    Profile,
    QuarterHoldings,
    Quote,
    QuoteResult,
)

__all__ = ["SyncMarketData"]

# A source that hangs on close must not keep the process alive forever.
_CLOSE_TIMEOUT = 10.0

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
        """Build the async client, then start the loop that will run it.

        The order matters: starting the thread first meant a client that failed
        to construct left a daemon loop running with nobody to stop it.
        """
        # Construction happens before the thread exists, so a failure here
        # leaves nothing behind.
        self._client = MarketData(ttl=ttl, max_stale=max_stale, **kwargs)
        self._loop = asyncio.new_event_loop()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run_loop,
            name="quotestack-loop",
            daemon=True,
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.set_exception_handler(self._on_loop_error)
        self._loop.run_forever()

    @staticmethod
    def _on_loop_error(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        """Report an unhandled loop exception instead of dropping it silently.

        Without a handler, an exception raised by a task nobody awaits vanishes
        and the thread keeps running as if nothing happened.
        """
        get_logger("sync").error(
            "event loop error: %s",
            context.get("message"),
            extra={"event": "loop_error", **{"exception": context.get("exception")}},
        )

    def _call(self, coro: Coroutine[Any, Any, T], *, timeout: float | None = None) -> T:
        """Run a coroutine on the background loop and wait for it.

        Args:
            coro: Work to run.
            timeout: Seconds to wait. ``None`` waits forever, which is the right
                default for data calls but not for shutdown, where a hung source
                would keep the process alive.

        Returns:
            The coroutine's result.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout)

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
            # A source that will not close must not hold the process open; the
            # loop is stopped either way.
            self._call(self._client.aclose(), timeout=_CLOSE_TIMEOUT)
        except FuturesTimeoutError:
            get_logger("sync").warning(
                "client did not close within %ss",
                _CLOSE_TIMEOUT,
                extra={"event": "close_timeout"},
            )
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5.0)
            if not self._thread.is_alive():
                self._loop.close()

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

    def quote_many(
        self,
        items: Sequence[tuple[str, AssetClass, Market]],
    ) -> list[QuoteResult]:
        """Fetch several quotes, blocking until done."""
        return self._call(self._client.quote_many(items))

    def nav(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.FUND,
        market: Market = Market.CN,
        *,
        limit: int = 250,
        max_age: float | None = None,
    ) -> list[NavPoint]:
        """Fetch a fund's NAV series, blocking until done."""
        return self._call(self._client.nav(code, asset_class, market, limit=limit, max_age=max_age))

    def profile(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.FUND,
        market: Market = Market.CN,
        *,
        max_age: float | None = None,
    ) -> Profile:
        """Fetch a fund profile, blocking until done."""
        return self._call(self._client.profile(code, asset_class, market, max_age=max_age))

    def holdings(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.FUND,
        market: Market = Market.CN,
        *,
        before: str | None = None,
        limit: int = 4,
    ) -> list[QuarterHoldings]:
        """Fetch quarterly holdings, blocking until done."""
        return self._call(
            self._client.holdings(code, asset_class, market, before=before, limit=limit)
        )

    def benchmark(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.FUND,
        market: Market = Market.CN,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> BenchmarkCurve:
        """Build the weighted benchmark curve, blocking until done."""
        return self._call(self._client.benchmark(code, asset_class, market, start=start, end=end))

    def estimate(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.FUND,
        market: Market = Market.CN,
    ) -> Estimate:
        """Estimate a fund's intraday change, blocking until done."""
        return self._call(self._client.estimate(code, asset_class, market))

    def fx(self, base: str, quote: str) -> FxRate:
        """Convert between two currencies, blocking until done."""
        return self._call(self._client.fx(base, quote))

    def iter_instruments(
        self,
        asset_class: AssetClass,
        market: Market,
        *,
        listed: bool | None = None,
        page_size: int = 100,
        tradable_only: bool = True,
    ) -> Iterator[list[InstrumentSummary]]:
        """Walk a market listing batch by batch, blocking for each batch.

        The async client yields batches lazily. Here each batch is fetched and
        returned in turn, so memory stays bounded the same way.

        Yields:
            Batches of instrument summaries.
        """
        # A synchronous iterator cannot await, so the async generator is
        # drained one batch at a time through the background loop.
        stream = self._client.iter_instruments(
            asset_class,
            market,
            listed=listed,
            page_size=page_size,
            tradable_only=tradable_only,
        )
        while True:
            try:
                batch: list[InstrumentSummary] = self._call(
                    cast(Coroutine[Any, Any, list[InstrumentSummary]], stream.__anext__())
                )
            except StopAsyncIteration:
                return
            yield batch

    def cache_stats(self) -> dict[str, int]:
        """Return cache occupancy."""
        return self._client.cache_stats()
