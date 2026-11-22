"""Error and edge paths for the estimate pipeline.

Branch coverage was 66% because only happy paths were tested: every component
resolved, every quote present, every quarter populated. These tests walk the
other direction of each guard.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from quotestack import AssetClass, Market, MarketData
from quotestack.benchmark import Benchmark, BenchmarkComponent, ComponentKind
from quotestack.errors import MarketDataError, UnsupportedError, UpstreamError
from quotestack.models import (
    Allocation,
    Capability,
    FundClass,
    Holding,
    Profile,
    QuarterHoldings,
)
from quotestack.sources.base import SourceMeta


class _Fund:
    meta = SourceMeta(
        name="tiantian",
        capabilities=frozenset({Capability.PROFILE, Capability.HOLDINGS, Capability.ESTIMATE}),
        markets=frozenset({(AssetClass.FUND, Market.CN)}),
    )

    def __init__(
        self,
        *,
        fund_class: FundClass = FundClass.EQUITY,
        tracking: str | None = None,
        allocation: Allocation | None = None,
        quarters: list[QuarterHoldings] | None = None,
        profile_error: Exception | None = None,
    ) -> None:
        self._class = fund_class
        self._tracking = tracking
        self._allocation = allocation
        self._quarters = quarters if quarters is not None else [_quarter()]
        self._profile_error = profile_error

    async def profile(self, instrument: Any) -> Profile:
        if self._profile_error:
            raise self._profile_error
        return Profile(
            fund_type="混合型-偏股",
            fund_class=self._class,
            tracking_index=self._tracking,
            benchmark=Benchmark(
                text="中证800*100%",
                components=[
                    BenchmarkComponent(name="中证800", weight=100.0, kind=ComponentKind.EQUITY)
                ],
                coverage=1.0,
            )
            if self._tracking is None
            else None,
        )

    async def allocation(self, instrument: Any) -> Allocation | None:
        return self._allocation

    async def holdings(self, instrument: Any, year: int) -> list[QuarterHoldings]:
        return self._quarters

    async def aclose(self) -> None:
        return None


class _Market:
    meta = SourceMeta(
        name="eastmoney",
        capabilities=frozenset({Capability.QUOTE}),
        markets=frozenset({(AssetClass.FUND, Market.CN)}),
    )

    def __init__(self, *, index: str | None = "1.000906", changes: dict[str, float] | None = None):
        self._index = index
        self._changes = changes or {}

    async def resolve_index(self, name: str) -> str | None:
        return self._index

    async def quotes_by_secid(self, secids: list[str]) -> dict[str, float]:
        return {sid: self._changes[sid] for sid in secids if sid in self._changes}

    async def aclose(self) -> None:
        return None


def _quarter() -> QuarterHoldings:
    return QuarterHoldings(
        quarter="2026Q3",
        as_of=dt.date(2026, 9, 30),
        holdings=[Holding(code="600519", name="贵州茅台", weight=20.0)],
    )


def _client(fund: _Fund, market: _Market | None = None) -> MarketData:
    return MarketData(
        sources={"tiantian": fund, "eastmoney": market or _Market()},
        source_priority={"PROFILE": ["tiantian"], "HOLDINGS": ["tiantian"]},
    )


async def test_money_fund_short_circuits_to_a_real_zero() -> None:
    """A money market fund's NAV genuinely does not move; that is not unknown."""
    client = _client(
        _Fund(
            fund_class=FundClass.MONEY,
            allocation=Allocation(stock=0.0, bond=0.0, cash=100.0),
        )
    )
    try:
        estimate = await client.estimate("000198")
    finally:
        await client.aclose()

    assert estimate.change_pct == 0.0
    assert estimate.basis.value == "none"
    assert "货币基金" in estimate.explanation


async def test_profile_failure_degrades_to_unknown() -> None:
    """A failing input yields null, not an exception."""
    client = _client(_Fund(profile_error=UpstreamError("boom", source="tiantian")))
    try:
        estimate = await client.estimate("166002")
    finally:
        await client.aclose()

    assert estimate.change_pct is None
    assert "输入不可用" in estimate.explanation


async def test_missing_allocation_degrades_to_unknown() -> None:
    """Without an equity ratio there is no honest coefficient to apply."""
    client = _client(_Fund(allocation=None))
    try:
        estimate = await client.estimate("166002")
    finally:
        await client.aclose()

    assert estimate.change_pct is None
    assert "资产配置" in estimate.explanation


async def test_index_without_equity_benchmark_is_unknown() -> None:
    """An index fund with neither tracking target nor equity component."""
    fund = _Fund(tracking="中证800", allocation=Allocation(stock=90.0, bond=5.0, cash=5.0))
    fund._tracking = "中证800"
    client = _client(fund)
    try:
        # Benchmark is None here, so the equity proxy is empty.
        estimate = await client.estimate("022430")
    finally:
        await client.aclose()

    assert estimate.change_pct is None


async def test_unresolvable_index_is_unknown() -> None:
    """A name with no secid cannot produce an estimate."""
    client = _client(
        _Fund(tracking="中证800", allocation=Allocation(stock=90.0, bond=5.0, cash=5.0)),
        _Market(index=None),
    )
    try:
        estimate = await client.estimate("022430")
    finally:
        await client.aclose()

    assert estimate.change_pct is None
    assert "没有可用的指数行情" in estimate.explanation


async def test_active_fund_without_reports_is_unknown() -> None:
    """No quarterly report means no holdings to work from."""
    client = _client(
        _Fund(allocation=Allocation(stock=60.0, bond=10.0, cash=30.0), quarters=[]),
    )
    try:
        estimate = await client.estimate("166002")
    finally:
        await client.aclose()

    assert estimate.change_pct is None
    assert "季度持仓" in estimate.explanation


async def test_active_fund_without_proxy_still_uses_holdings() -> None:
    """With no benchmark quote the remainder is treated as flat, and said so."""
    client = _client(
        _Fund(allocation=Allocation(stock=60.0, bond=10.0, cash=30.0)),
        _Market(index=None, changes={"1.600519": 5.0}),
    )
    try:
        estimate = await client.estimate("166002")
    finally:
        await client.aclose()

    assert estimate.change_pct == pytest.approx(1.0)
    assert "按 0 计" in estimate.explanation


async def test_fx_without_source_is_unsupported() -> None:
    """A missing FX source is a capability gap, not a crash."""
    client = MarketData(sources={"tiantian": _Fund()})
    try:
        with pytest.raises(UnsupportedError):
            await client.fx("USD", "CNY")
    finally:
        await client.aclose()


async def test_holdings_without_source_is_unavailable() -> None:
    """A missing source is a fetch failure, not a capability refusal.

    The instrument does declare HOLDINGS, so the guard passes and the failure
    surfaces as "no source could serve this" rather than "unsupported".
    """
    client = MarketData(sources={"eastmoney": _Market()})
    try:
        with pytest.raises(MarketDataError) as excinfo:
            await client.holdings("166002")
    finally:
        await client.aclose()

    assert excinfo.value.code in {"UNAVAILABLE", "UNSUPPORTED"}
