"""Synchronous wrapper: lifecycle, ordering and shutdown."""

from __future__ import annotations

import pytest

from quotestack.cache import default_max_stale, default_ttl
from quotestack.cache.memory import MemoryCache
from quotestack.resilience import Cooldown, TokenBucket


def test_a_failed_construction_leaves_no_thread_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """The thread used to start before the client was built.

    A constructor that raised left a daemon loop running with nobody holding a
    reference to stop it.
    """
    import threading

    from quotestack.sync import SyncMarketData

    before = {t.name for t in threading.enumerate()}

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("construction failed")

    with monkeypatch.context() as patch:
        patch.setattr("quotestack.sync.MarketData", boom)
        with pytest.raises(RuntimeError):
            SyncMarketData()

    leaked = {t.name for t in threading.enumerate()} - before
    assert "quotestack-loop" not in leaked


def test_close_is_bounded_and_idempotent() -> None:
    """A source that never finishes closing must not hold the process open."""
    from quotestack.sync import SyncMarketData

    client = SyncMarketData()
    client.close()
    client.close()


def test_cancel_inflight_waits_for_the_task_to_stop() -> None:
    """Cancelling is asynchronous; closing the source before it unwound raced."""
    import asyncio

    from quotestack.client.fetch import FetchPolicy

    async def scenario() -> None:
        policy = FetchPolicy(
            cache=MemoryCache(),
            ttl=default_ttl(),
            max_stale=default_max_stale(),
            sources={},
            priority={},
            cooldown=Cooldown(),
            bucket=TokenBucket(rate=1000),
        )
        stopped = asyncio.Event()

        async def linger() -> None:
            try:
                await asyncio.sleep(30)
            finally:
                stopped.set()

        task = asyncio.create_task(linger())
        policy._inflight["k"] = task
        await asyncio.sleep(0)
        await policy.cancel_inflight()

        assert stopped.is_set(), "cancel_inflight returned before the task finished"

    asyncio.run(scenario())


async def test_every_sync_method_delegates() -> None:
    """The sync facade is only useful if each method reaches the async one.

    Coverage here was 74%: the delegation methods were exercised only through
    the live probe, which skips by default.
    """
    import datetime as dt
    from typing import Any

    from quotestack import AssetClass, Market
    from quotestack.models import (
        Allocation,
        Bar,
        Capability,
        Estimate,
        EstimateBasis,
        FxRate,
        InstrumentSummary,
        NavPoint,
        Profile,
        QuarterHoldings,
        Quote,
    )
    from quotestack.sources.base import SourceMeta
    from quotestack.sync import SyncMarketData

    class All:
        meta = SourceMeta(
            name="fake",
            capabilities=frozenset(
                {
                    Capability.QUOTE,
                    Capability.HISTORY,
                    Capability.NAV,
                    Capability.PROFILE,
                    Capability.HOLDINGS,
                    Capability.ESTIMATE,
                    Capability.FX,
                    Capability.LIST,
                }
            ),
            markets=frozenset({(AssetClass.STOCK, Market.CN)}),
        )

        async def quote(self, instruments: Any) -> list[Quote]:
            return [
                Quote(
                    instrument_id=i.id,
                    price="1.00",
                    currency="CNY",
                    source="fake",
                    ts=dt.datetime.now(dt.UTC),
                )
                for i in instruments
            ]

        async def history(self, *args: Any, **kwargs: Any) -> list[Bar]:
            return [
                Bar(
                    date=dt.date(2026, 11, 10), open="1", high="2", low="1", close="1.5", volume="1"
                )
            ]

        async def nav(self, *args: Any, **kwargs: Any) -> list[NavPoint]:
            return [NavPoint(date=dt.date(2026, 11, 10), nav="1.0000")]

        async def profile(self, *args: Any, **kwargs: Any) -> Profile:
            return Profile(fund_type="指数型-股票")

        async def holdings(self, *args: Any, **kwargs: Any) -> list[QuarterHoldings]:
            return []

        async def allocation(self, *args: Any, **kwargs: Any) -> Allocation | None:
            return None

        async def fx(self, base: str, quote: str) -> FxRate:
            return FxRate(
                base=base,
                quote=quote,
                rate="1",
                source="fake",
                as_of=dt.datetime.now(dt.UTC),
                derived=False,
            )

        async def list_instruments(self, *args: Any, **kwargs: Any) -> Any:
            yield [
                InstrumentSummary(
                    code="600519",
                    name="A",
                    asset_class=AssetClass.STOCK,
                    market=Market.CN,
                    currency="CNY",
                )
            ]

        async def aclose(self) -> None:
            return None

    def estimate() -> Estimate:
        return Estimate(change_pct=None, basis=EstimateBasis.NONE, explanation="x")

    client = SyncMarketData(
        sources={"eastmoney": All(), "fx": All()},
        source_priority={
            "QUOTE": ["eastmoney"],
            "HISTORY": ["eastmoney"],
            "NAV": ["eastmoney"],
            "PROFILE": ["eastmoney"],
            "HOLDINGS": ["eastmoney"],
            "LIST": ["eastmoney"],
        },
    )
    try:
        assert client.quote("600519").price == "1.00"
        assert len(client.history("600519", limit=1)) == 1
        assert client.nav("022430", limit=1)[0].nav == "1.0000"
        assert client.profile("022430").fund_type == "指数型-股票"
        assert client.holdings("166002", limit=1) == []
        assert client.fx("USD", "CNY").rate == "1"
        assert [len(batch) for batch in client.iter_instruments(AssetClass.STOCK, Market.CN)] == [1]
        assert client.cache_stats()["entries"] >= 0
    finally:
        client.close()
