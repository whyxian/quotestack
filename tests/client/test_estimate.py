"""Tests for the estimate arithmetic and wording."""

from __future__ import annotations

import pytest

from quotestack.benchmark import (
    Benchmark,
    BenchmarkComponent,
    ComponentKind,
    parse_benchmark,
)
from quotestack.estimate import (
    assumption_of,
    describe_holdings,
    equity_proxy,
    weighted_change,
)
from quotestack.models import Allocation


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
