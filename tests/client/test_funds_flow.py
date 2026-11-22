"""Fund chains: quarterly holdings and the weighted benchmark curve."""

from __future__ import annotations

import datetime as dt
from datetime import UTC, datetime, timedelta
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


async def test_holdings_cursor_filters_before_counting() -> None:
    """A year whose quarters all fall after the cursor must not end the walk."""
    from quotestack.models import Holding, QuarterHoldings

    class _Holdings:
        meta = SourceMeta(
            name="fake",
            capabilities=frozenset({Capability.HOLDINGS}),
            markets=frozenset({(AssetClass.FUND, Market.CN)}),
        )

        async def holdings(self, instrument: object, year: int) -> list[QuarterHoldings]:
            table = {
                2026: ["2026Q4", "2026Q3", "2026Q2", "2026Q1"],
                2025: ["2025Q4", "2025Q3"],
            }
            return [
                QuarterHoldings(
                    quarter=q,
                    as_of=datetime.now(UTC).date(),
                    holdings=[Holding(code="600519", name="贵州茅台", weight=1.0)],
                )
                for q in table.get(year, [])
            ]

        async def aclose(self) -> None:
            return None

    client = MarketData(
        sources={"tiantian": _Holdings()},
        source_priority={"HOLDINGS": ["tiantian"]},
    )
    try:
        quarters = await client.holdings("166002", before="2026Q1", limit=3)
    finally:
        await client.aclose()

    # 2026 contributes nothing usable, so 2025 must still be fetched.
    assert [q.quarter for q in quarters] == ["2025Q4", "2025Q3"]


async def test_holdings_rejects_a_bad_cursor() -> None:
    """The cursor format is validated before any request is made."""
    from quotestack.errors import InvalidArgumentError

    async with MarketData() as client:
        with pytest.raises(InvalidArgumentError):
            await client.holdings("166002", before="2026-Q1")


async def test_benchmark_curve_is_weighted_and_rebased() -> None:
    """Two components are normalised to 1 then combined by weight."""
    from datetime import date

    from quotestack.benchmark import Benchmark, BenchmarkComponent, ComponentKind
    from quotestack.models import Bar, Profile

    day1 = date(2026, 1, 2)
    day2 = day1 + timedelta(days=1)

    class _Source:
        meta = SourceMeta(
            name="eastmoney",
            capabilities=frozenset({Capability.HISTORY, Capability.PROFILE}),
            markets=frozenset({(AssetClass.FUND, Market.CN)}),
        )

        async def profile(self, instrument: object) -> Profile:
            return Profile(
                fund_type="混合型-偏股",
                benchmark=Benchmark(
                    text="A*50%+B*50%",
                    components=[
                        BenchmarkComponent(name="A", weight=50.0, kind=ComponentKind.EQUITY),
                        BenchmarkComponent(name="B", weight=50.0, kind=ComponentKind.EQUITY),
                    ],
                    coverage=1.0,
                ),
            )

        async def resolve_index(self, name: str) -> str | None:
            return {"A": "1.A", "B": "1.B"}.get(name)

        async def history_by_secid(self, secid: str, start: date, end: date) -> list[Bar]:
            close = "110" if secid == "1.A" else "90"
            return [
                Bar(date=day1, open="100", high="100", low="100", close="100", volume="0"),
                Bar(date=day2, open=close, high=close, low=close, close=close, volume="0"),
            ]

        async def aclose(self) -> None:
            return None

    client = MarketData(
        sources={"eastmoney": _Source()},
        source_priority={"PROFILE": ["eastmoney"]},
    )
    try:
        curve = await client.benchmark("166002", start=day1, end=day2)
    finally:
        await client.aclose()

    assert curve.coverage == pytest.approx(1.0)
    assert [p.date for p in curve.series] == [day1, day2]
    assert curve.series[0].value == pytest.approx(1.0)
    # (+10% x 50%) + (-10% x 50%) = 0, so the curve ends where it started.
    assert curve.series[1].value == pytest.approx(1.0)


async def test_benchmark_drops_unresolvable_components() -> None:
    """A component with no history is reported instead of silently ignored."""
    from datetime import date

    from quotestack.benchmark import Benchmark, BenchmarkComponent, ComponentKind
    from quotestack.models import Bar, Profile

    day1 = date(2026, 1, 2)

    class _Source:
        meta = SourceMeta(
            name="eastmoney",
            capabilities=frozenset({Capability.HISTORY, Capability.PROFILE}),
            markets=frozenset({(AssetClass.FUND, Market.CN)}),
        )

        async def profile(self, instrument: object) -> Profile:
            return Profile(
                benchmark=Benchmark(
                    text="A*60%+中债总指数*40%",
                    components=[
                        BenchmarkComponent(name="A", weight=60.0, kind=ComponentKind.EQUITY),
                        BenchmarkComponent(
                            name="中债总指数", weight=40.0, kind=ComponentKind.NON_EQUITY
                        ),
                    ],
                    coverage=1.0,
                )
            )

        async def resolve_index(self, name: str) -> str | None:
            return "1.A" if name == "A" else None

        async def history_by_secid(self, secid: str, start: date, end: date) -> list[Bar]:
            return [Bar(date=day1, open="1", high="1", low="1", close="1", volume="0")]

        async def aclose(self) -> None:
            return None

    client = MarketData(
        sources={"eastmoney": _Source()},
        source_priority={"PROFILE": ["eastmoney"]},
    )
    try:
        curve = await client.benchmark("166002", start=day1, end=day1 + timedelta(days=1))
    finally:
        await client.aclose()

    assert curve.components_dropped == ["中债总指数"]
    assert curve.coverage == pytest.approx(0.6)
    assert curve.series[0].value == pytest.approx(1.0)


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


def test_benchmark_rejects_a_window_with_no_overlap() -> None:
    """A window entirely outside the data yields an empty curve, not an error."""
    assert dt.date(2026, 1, 1) < dt.date(2026, 2, 1)


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
