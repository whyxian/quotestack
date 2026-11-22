"""Tests for the estimate arithmetic and wording."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from tests.support.fakes import make_meta

from quotestack import AssetClass, Market, MarketData
from quotestack.benchmark import (
    Benchmark,
    BenchmarkComponent,
    ComponentKind,
    parse_benchmark,
)
from quotestack.errors import MarketDataError, UnsupportedError, UpstreamError
from quotestack.estimate import (
    assumption_of,
    describe_holdings,
    equity_proxy,
    weighted_change,
)
from quotestack.models import (
    Allocation,
    Capability,
    FundClass,
    Holding,
    Profile,
    QuarterHoldings,
)


def _component(name: str, weight: float, kind: ComponentKind) -> BenchmarkComponent:
    return BenchmarkComponent(name=name, weight=weight, kind=kind)


def test_assumption_groups_components_by_kind() -> None:
    """The three groups must be visible so a bad classification is noticeable."""
    benchmark = parse_benchmark("中证800指数收益率*70%+上证国债指数收益率*25%+某策略*5%")

    assumption = assumption_of(benchmark)

    assert assumption.equity == ("中证800指数收益率",)
    assert assumption.non_equity == ("上证国债指数收益率",)
    assert assumption.unclassified == ("某策略",)


def test_equity_proxy_renormalises_to_100() -> None:
    """The remainder is proxied by equity components only, so weights rescale."""
    benchmark = Benchmark(
        text="",
        components=[
            _component("A", 50.0, ComponentKind.EQUITY),
            _component("B", 30.0, ComponentKind.EQUITY),
            _component("C", 20.0, ComponentKind.NON_EQUITY),
        ],
        coverage=1.0,
    )

    proxy = equity_proxy(benchmark)

    assert [component.name for component, _ in proxy] == ["A", "B"]
    assert [weight for _, weight in proxy] == pytest.approx([62.5, 37.5])


def test_equity_proxy_is_empty_without_equity() -> None:
    """A pure bond benchmark cannot proxy equity exposure."""
    benchmark = parse_benchmark("中证全债指数收益率")

    assert equity_proxy(benchmark) == []


def test_weighted_change_ignores_missing_quotes() -> None:
    """Missing components drop out and the rest renormalise."""
    result = weighted_change([("1.A", 60.0), ("1.B", 40.0)], {"1.A": -2.0})

    assert result is not None
    change, used = result
    assert change == pytest.approx(-2.0)
    assert used == pytest.approx(60.0)


def test_weighted_change_returns_none_when_nothing_matches() -> None:
    """No data at all is not a zero change."""
    assert weighted_change([("1.A", 100.0)], {}) is None


def test_allocation_separates_equity_exposure() -> None:
    """A feeder fund's exposure lives in ``other``, not in ``stock``."""
    feeder = Allocation(stock=2.67, bond=1.88, cash=3.75)
    active = Allocation(stock=69.69, bond=7.18, cash=23.27)

    assert feeder.other == pytest.approx(91.7)
    assert feeder.equity_exposure == pytest.approx(94.37)
    assert active.equity_exposure == pytest.approx(69.69 + 0.0)


def test_holdings_explanation_mentions_the_proxy() -> None:
    """The wording must say how the unknown remainder was filled."""
    text = describe_holdings(35.6, -4.97, 34.1, -1.62, -2.32)

    assert "前十大合计 35.6%" in text
    assert "权益基准" in text
    assert "-2.32%" in text


def test_holdings_explanation_when_no_proxy() -> None:
    """With no usable benchmark component the remainder is reported as zero."""
    text = describe_holdings(30.0, -1.0, 20.0, None, -1.0)

    assert "按 0 计" in text


class _Fund:
    meta = make_meta(
        "tiantian",
        {Capability.PROFILE, Capability.HOLDINGS, Capability.ESTIMATE},
        {(AssetClass.FUND, Market.CN)},
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
    meta = make_meta("eastmoney", {Capability.QUOTE}, {(AssetClass.FUND, Market.CN)})

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


_FUND = "166002"


class _FundSource:
    """Stands in for Tiantian: profile, allocation and holdings."""

    meta = make_meta(
        "tiantian",
        {Capability.PROFILE, Capability.HOLDINGS, Capability.ESTIMATE},
        {(AssetClass.FUND, Market.CN)},
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

    meta = make_meta(
        "eastmoney", {Capability.QUOTE, Capability.HISTORY}, {(AssetClass.FUND, Market.CN)}
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


def _client_paths(fund: _FundSource, market: _MarketSource) -> MarketData:
    return MarketData(
        sources={"tiantian": fund, "eastmoney": market},
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


async def test_index_formula_multiplies_by_exposure() -> None:
    """A tracking fund moves with its index scaled by equity exposure."""
    fund = _FundSource(tracking="中证800", stock=90.0)
    market = _MarketSource({"1.000906": -2.0})
    client = _client_paths(fund, market)
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
    client = _client_paths(fund, market)
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
    client = _client_paths(fund, market)
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
    client = _client_paths(fund, market)
    try:
        estimate = await client.estimate(_FUND)
    finally:
        await client.aclose()

    assert estimate.benchmark_assumption is not None
    assert estimate.benchmark_assumption.equity == ("中证800",)
    assert estimate.benchmark_assumption.non_equity == ("中证全债",)


async def test_estimate_degrades_when_the_index_lookup_fails() -> None:
    """The contract says an estimate never raises on an upstream failure.

    It did: a failing index lookup escaped as UnavailableError, so a watchlist
    rendering ten funds lost all ten because one source was down.
    """
    from quotestack import AssetClass, Market, MarketData
    from quotestack.benchmark import Benchmark, BenchmarkComponent, ComponentKind
    from quotestack.errors import UnavailableError
    from quotestack.models import Allocation, Capability, Profile

    class Fund:
        meta = make_meta(
            "tiantian", {Capability.PROFILE, Capability.ESTIMATE}, {(AssetClass.FUND, Market.CN)}
        )

        async def profile(self, instrument: Any) -> Profile:
            return Profile(
                fund_type="指数型-股票",
                tracking_index="中证A500指数",
                benchmark=Benchmark(
                    text="中证A500*100%",
                    components=[
                        BenchmarkComponent(name="中证A500", weight=100.0, kind=ComponentKind.EQUITY)
                    ],
                    coverage=1.0,
                ),
            )

        async def allocation(self, instrument: Any) -> Allocation:
            return Allocation(stock=94.0, bond=0.0, cash=6.0)

        async def aclose(self) -> None:
            return None

    class Down:
        meta = make_meta("eastmoney", {Capability.QUOTE}, {(AssetClass.FUND, Market.CN)})

        async def resolve_index(self, name: str) -> str:
            raise UnavailableError("down", attempts=[])

        async def aclose(self) -> None:
            return None

    client = MarketData(
        sources={"tiantian": Fund(), "eastmoney": Down()},
        source_priority={"PROFILE": ["tiantian"]},
    )
    try:
        estimate = await client.estimate("022430")
    finally:
        await client.aclose()

    assert estimate.change_pct is None
    assert estimate.basis.value == "none"
    assert "估算中断" in estimate.explanation


class _ProfileOnly:
    meta = make_meta("tiantian", {Capability.PROFILE}, {(AssetClass.FUND, Market.CN)})

    def __init__(self, benchmark: Benchmark | None) -> None:
        self._benchmark = benchmark

    async def profile(self, instrument: Any) -> Profile:
        return Profile(fund_type="混合型-偏股", benchmark=self._benchmark)

    async def aclose(self) -> None:
        return None


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
