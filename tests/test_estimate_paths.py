"""Exercise both estimate formulas end to end with fake sources."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from quotestack import AssetClass, Market, MarketData
from quotestack.benchmark import Benchmark, BenchmarkComponent, ComponentKind
from quotestack.models import Allocation, Capability, FundClass, Holding, Profile, QuarterHoldings
from quotestack.sources.base import SourceMeta

_FUND = "166002"


class _FundSource:
    """Stands in for Tiantian: profile, allocation and holdings."""

    meta = SourceMeta(
        name="tiantian",
        capabilities=frozenset({Capability.PROFILE, Capability.HOLDINGS, Capability.ESTIMATE}),
        markets=frozenset({(AssetClass.FUND, Market.CN)}),
    )

    def __init__(self, *, tracking: str | None, stock: float = 60.0) -> None:
        self._tracking = tracking
        self._stock = stock

    async def profile(self, instrument: Any) -> Profile:
        return Profile(
            fund_type="指数型-股票" if self._tracking else "混合型-偏股",
            fund_class=FundClass.EQUITY,
            tracking_index=self._tracking,
            benchmark=Benchmark(
                text="中证800*70%+中证全债*30%",
                components=[
                    BenchmarkComponent(name="中证800", weight=70.0, kind=ComponentKind.EQUITY),
                    BenchmarkComponent(name="中证全债", weight=30.0, kind=ComponentKind.NON_EQUITY),
                ],
                coverage=1.0,
            ),
        )

    async def allocation(self, instrument: Any) -> Allocation:
        return Allocation(stock=self._stock, bond=10.0, cash=100.0 - self._stock - 10.0)

    async def holdings(self, instrument: Any, year: int) -> list[QuarterHoldings]:
        if year != dt.date.today().year:
            return []
        return [
            QuarterHoldings(
                quarter=f"{year}Q3",
                as_of=dt.date(year, 9, 30),
                holdings=[Holding(code="600519", name="贵州茅台", weight=20.0)],
            )
        ]

    async def aclose(self) -> None:
        return None


class _MarketSource:
    """Stands in for Eastmoney: index codes and live changes."""

    meta = SourceMeta(
        name="eastmoney",
        capabilities=frozenset({Capability.QUOTE, Capability.HISTORY}),
        markets=frozenset({(AssetClass.FUND, Market.CN)}),
    )

    def __init__(self, changes: dict[str, float]) -> None:
        self._changes = changes
        self.asked: list[list[str]] = []

    async def resolve_index(self, name: str) -> str | None:
        return {"中证800": "1.000906", "中证全债": "1.H11001"}.get(name)

    async def quotes_by_secid(self, secids: list[str]) -> dict[str, float]:
        self.asked.append(list(secids))
        return {sid: self._changes[sid] for sid in secids if sid in self._changes}

    async def aclose(self) -> None:
        return None


def _client(fund: _FundSource, market: _MarketSource) -> MarketData:
    return MarketData(
        sources={"tiantian": fund, "eastmoney": market},
        source_priority={"PROFILE": ["tiantian"], "HOLDINGS": ["tiantian"]},
    )


async def test_index_formula_multiplies_by_exposure() -> None:
    """A tracking fund moves with its index scaled by equity exposure."""
    fund = _FundSource(tracking="中证800", stock=90.0)
    market = _MarketSource({"1.000906": -2.0})
    client = _client(fund, market)
    try:
        estimate = await client.estimate(_FUND)
    finally:
        await client.aclose()

    assert estimate.basis.value == "index"
    assert estimate.change_pct == pytest.approx(-1.8)
    assert estimate.coverage == pytest.approx(0.9)
    assert "中证800" in estimate.explanation


async def test_active_formula_combines_holdings_and_proxy() -> None:
    """Top holdings plus the remainder proxied by the equity benchmark."""
    fund = _FundSource(tracking=None, stock=60.0)
    market = _MarketSource({"1.600519": 5.0, "1.000906": -2.0})
    client = _client(fund, market)
    try:
        estimate = await client.estimate(_FUND)
    finally:
        await client.aclose()

    # 20% x +5% + (60-20)% x -2% = 1.0 - 0.8 = 0.2
    assert estimate.basis.value == "holdings"
    assert estimate.change_pct == pytest.approx(0.2)
    assert estimate.coverage == pytest.approx(0.6)


async def test_missing_index_quote_yields_unknown_not_zero() -> None:
    """No quote means the estimate is unknown, never a fabricated zero."""
    fund = _FundSource(tracking="中证800", stock=90.0)
    market = _MarketSource({})
    client = _client(fund, market)
    try:
        estimate = await client.estimate(_FUND)
    finally:
        await client.aclose()

    assert estimate.change_pct is None
    assert estimate.basis.value == "none"


async def test_estimate_reports_the_benchmark_assumption() -> None:
    """The classification is exposed so a wrong guess is visible."""
    fund = _FundSource(tracking=None, stock=60.0)
    market = _MarketSource({"1.600519": 1.0, "1.000906": 1.0})
    client = _client(fund, market)
    try:
        estimate = await client.estimate(_FUND)
    finally:
        await client.aclose()

    assert estimate.benchmark_assumption is not None
    assert estimate.benchmark_assumption.equity == ("中证800",)
    assert estimate.benchmark_assumption.non_equity == ("中证全债",)
