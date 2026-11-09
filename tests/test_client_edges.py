"""Client guards that only trigger with a partially assembled client."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from quotestack import AssetClass, Market, MarketData
from quotestack.benchmark import Benchmark, BenchmarkComponent, ComponentKind
from quotestack.errors import UnsupportedError
from quotestack.models import Capability, Profile
from quotestack.sources.base import SourceMeta


class _ProfileOnly:
    meta = SourceMeta(
        name="tiantian",
        capabilities=frozenset({Capability.PROFILE}),
        markets=frozenset({(AssetClass.FUND, Market.CN)}),
    )

    def __init__(self, benchmark: Benchmark | None) -> None:
        self._benchmark = benchmark

    async def profile(self, instrument: Any) -> Profile:
        return Profile(fund_type="混合型-偏股", benchmark=self._benchmark)

    async def aclose(self) -> None:
        return None


async def test_benchmark_without_a_published_benchmark_is_unsupported() -> None:
    """A fund that reports no benchmark cannot produce a curve."""
    client = MarketData(
        sources={"tiantian": _ProfileOnly(None)},
        source_priority={"PROFILE": ["tiantian"]},
    )
    try:
        with pytest.raises(UnsupportedError):
            await client.benchmark("166002")
    finally:
        await client.aclose()


async def test_benchmark_with_no_resolvable_component_is_empty() -> None:
    """When every component is unavailable the curve is empty, not wrong."""
    benchmark = Benchmark(
        text="中债总指数*100%",
        components=[
            BenchmarkComponent(name="中债总指数", weight=100.0, kind=ComponentKind.NON_EQUITY)
        ],
        coverage=1.0,
    )
    client = MarketData(
        sources={"tiantian": _ProfileOnly(benchmark)},
        source_priority={"PROFILE": ["tiantian"]},
    )
    try:
        curve = await client.benchmark("166002")
    finally:
        await client.aclose()

    assert curve.series == []
    assert curve.effective_start is None
    assert curve.coverage == 0.0
    assert curve.components_dropped == ["中债总指数"]


async def test_benchmark_without_an_eastmoney_source_is_empty() -> None:
    """Index resolution needs the market source; without it, nothing resolves."""
    benchmark = Benchmark(
        text="中证800*100%",
        components=[BenchmarkComponent(name="中证800", weight=100.0, kind=ComponentKind.EQUITY)],
        coverage=1.0,
    )
    client = MarketData(
        sources={"tiantian": _ProfileOnly(benchmark)},
        source_priority={"PROFILE": ["tiantian"]},
    )
    try:
        curve = await client.benchmark("166002")
    finally:
        await client.aclose()

    assert curve.series == []
    assert curve.coverage == 0.0


async def test_estimate_without_a_quote_source_is_unknown() -> None:
    """No market source means no live change to apply."""
    benchmark = Benchmark(
        text="中证800*100%",
        components=[BenchmarkComponent(name="中证800", weight=100.0, kind=ComponentKind.EQUITY)],
        coverage=1.0,
    )
    client = MarketData(
        sources={"tiantian": _ProfileOnly(benchmark)},
        source_priority={"PROFILE": ["tiantian"]},
    )
    try:
        estimate = await client.estimate("166002")
    finally:
        await client.aclose()

    assert estimate.change_pct is None


async def test_aclose_tolerates_a_source_without_aclose() -> None:
    """A third-party source may implement only the methods it needs."""

    class _NoClose:
        meta = SourceMeta(
            name="bare",
            capabilities=frozenset({Capability.PROFILE}),
            markets=frozenset({(AssetClass.FUND, Market.CN)}),
        )

        async def profile(self, instrument: Any) -> Profile:
            return Profile()

    client = MarketData(sources={"bare": _NoClose()})
    await client.aclose()


async def test_resolve_requires_six_digit_mainland_codes() -> None:
    async with MarketData() as client:
        from quotestack.errors import InvalidArgumentError

        with pytest.raises(InvalidArgumentError):
            client.resolve("60051")


def test_cache_stats_reflects_stored_entries() -> None:
    client = MarketData()
    assert client.cache_stats()["entries"] == 0


def test_health_lists_every_configured_source() -> None:
    client = MarketData()
    assert set(client.health()["sources"]) == {"eastmoney", "tencent", "tiantian", "fx", "binance"}


def test_health_marks_a_cooling_source_as_degraded() -> None:
    """A degraded source must be visible in the status field."""
    from quotestack.resilience import Cooldown

    cooldown = Cooldown(duration=60.0, failure_threshold=1)
    client = MarketData(cooldown=cooldown)
    cooldown.mark_failed("eastmoney")

    health = client.health()
    assert health["status"] == "degraded"


def test_benchmark_rejects_a_window_with_no_overlap() -> None:
    """A window entirely outside the data yields an empty curve, not an error."""
    assert dt.date(2026, 1, 1) < dt.date(2026, 2, 1)


async def test_holdings_rejects_a_non_positive_limit() -> None:
    """A zero limit is a caller mistake, reported before any request."""
    from quotestack.errors import InvalidArgumentError

    async with MarketData() as client:
        with pytest.raises(InvalidArgumentError):
            await client.holdings("166002", limit=0)


async def test_iter_instruments_rejects_an_unmapped_market() -> None:
    """A market with no listing source is unsupported, not empty."""
    from quotestack.errors import UnsupportedError

    async with MarketData() as client:
        with pytest.raises(UnsupportedError):
            async for _ in client.iter_instruments(AssetClass.FUND, Market.US):
                pass


async def test_benchmark_skips_components_with_no_history() -> None:
    """A component that resolves but returns no bars is dropped."""
    from quotestack.benchmark import Benchmark, BenchmarkComponent, ComponentKind
    from quotestack.models import Profile

    class _Source:
        meta = SourceMeta(
            name="eastmoney",
            capabilities=frozenset({Capability.PROFILE}),
            markets=frozenset({(AssetClass.FUND, Market.CN)}),
        )

        async def profile(self, instrument: Any) -> Profile:
            return Profile(
                benchmark=Benchmark(
                    text="A*100%",
                    components=[
                        BenchmarkComponent(name="A", weight=100.0, kind=ComponentKind.EQUITY)
                    ],
                    coverage=1.0,
                )
            )

        async def resolve_index(self, name: str) -> str | None:
            return "1.A"

        async def history_by_secid(self, secid: str, start: dt.date, end: dt.date) -> list[Any]:
            return []

        async def aclose(self) -> None:
            return None

    client = MarketData(
        sources={"eastmoney": _Source()},
        source_priority={"PROFILE": ["eastmoney"]},
    )
    try:
        curve = await client.benchmark("166002")
    finally:
        await client.aclose()

    assert curve.series == []
    assert curve.components_dropped == ["A"]


async def test_benchmark_with_disjoint_dates_is_empty() -> None:
    """Two components with no overlapping trading day cannot be combined."""
    from quotestack.benchmark import Benchmark, BenchmarkComponent, ComponentKind
    from quotestack.models import Bar, Profile

    class _Source:
        meta = SourceMeta(
            name="eastmoney",
            capabilities=frozenset({Capability.PROFILE}),
            markets=frozenset({(AssetClass.FUND, Market.CN)}),
        )

        async def profile(self, instrument: Any) -> Profile:
            return Profile(
                benchmark=Benchmark(
                    text="A*50%+B*50%",
                    components=[
                        BenchmarkComponent(name="A", weight=50.0, kind=ComponentKind.EQUITY),
                        BenchmarkComponent(name="B", weight=50.0, kind=ComponentKind.EQUITY),
                    ],
                    coverage=1.0,
                )
            )

        async def resolve_index(self, name: str) -> str | None:
            return f"1.{name}"

        async def history_by_secid(self, secid: str, start: dt.date, end: dt.date) -> list[Bar]:
            day = dt.date(2026, 1, 2) if secid == "1.A" else dt.date(2026, 3, 2)
            return [Bar(date=day, open="1", high="1", low="1", close="1", volume="0")]

        async def aclose(self) -> None:
            return None

    client = MarketData(
        sources={"eastmoney": _Source()},
        source_priority={"PROFILE": ["eastmoney"]},
    )
    try:
        curve = await client.benchmark("166002")
    finally:
        await client.aclose()

    assert curve.series == []
    assert curve.effective_start is None


async def test_quote_many_falls_back_when_every_source_fails() -> None:
    """When no source serves a group the items carry a per-item error."""
    from quotestack.errors import UpstreamError

    class _Failing:
        meta = SourceMeta(
            name="eastmoney",
            capabilities=frozenset({Capability.QUOTE}),
            markets=frozenset({(AssetClass.STOCK, Market.CN)}),
        )

        async def quote(self, instruments: list[Any]) -> list[Any]:
            raise UpstreamError("down", source="eastmoney")

        async def aclose(self) -> None:
            return None

    client = MarketData(sources={"eastmoney": _Failing()})
    try:
        results = await client.quote_many([("600519", AssetClass.STOCK, Market.CN)])
    finally:
        await client.aclose()

    assert results[0].ok is False
    assert "UNAVAILABLE" in (results[0].error or "")


async def test_history_limit_changes_the_answer_not_the_cache() -> None:
    """Two different limits are two different questions.

    The cache key omitted `limit`, so `history(limit=5)` wrote five bars under a
    key that `history(limit=50)` then read, and the second call returned five.
    """
    import datetime as dt

    from quotestack.models import Bar, Capability
    from quotestack.sources.base import SourceMeta

    class Fake:
        meta = SourceMeta(
            name="fake",
            capabilities=frozenset({Capability.HISTORY}),
            markets=frozenset({(AssetClass.STOCK, Market.CN)}),
        )
        calls = 0

        async def history(
            self, instrument: Any, interval: Any, adjust: Any, limit: int
        ) -> list[Bar]:
            Fake.calls += 1
            return [
                Bar(
                    date=dt.date(2026, 1, 1) + dt.timedelta(days=index),
                    open="1",
                    high="2",
                    low="0.5",
                    close="1.5",
                    volume="100",
                )
                for index in range(limit)
            ]

        async def aclose(self) -> None:
            return None

    client = MarketData(sources={"fake": Fake()}, source_priority={"HISTORY": ["fake"]})
    try:
        small = await client.history("600519", limit=5)
        large = await client.history("600519", limit=50)
    finally:
        await client.aclose()

    assert len(small) == 5
    assert len(large) == 50
    assert Fake.calls == 2


async def test_history_rejects_a_non_positive_limit() -> None:
    from quotestack.errors import InvalidArgumentError

    async with MarketData() as client:
        with pytest.raises(InvalidArgumentError):
            await client.history("600519", limit=0)


async def test_nav_and_page_size_reject_non_positive_values() -> None:
    from quotestack.errors import InvalidArgumentError

    async with MarketData() as client:
        with pytest.raises(InvalidArgumentError):
            await client.nav("022430", limit=0)
        with pytest.raises(InvalidArgumentError):
            async for _ in client.iter_instruments(AssetClass.STOCK, Market.CN, page_size=0):
                break


def test_proxy_credentials_are_redacted_in_health() -> None:
    """`/healthz` is unauthenticated; a proxy password must not appear there."""
    from quotestack.client import _redact_proxy

    assert _redact_proxy("http://user:secret@proxy.local:7890") == (
        "http://<redacted>@proxy.local:7890"
    )
    assert _redact_proxy("http://proxy.local:7890") == "http://proxy.local:7890"
    assert _redact_proxy(None) is None
