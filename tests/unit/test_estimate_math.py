"""Tests for benchmark parsing and equity classification."""

from __future__ import annotations

import pytest

from quotestack.benchmark import (
    Benchmark,
    ComponentKind,
    classify_component,
    parse_benchmark,
)


def test_parses_three_weighted_terms() -> None:
    """The common shape: index + bond + deposit, weights explicit."""
    parsed = parse_benchmark(
        "中证800指数收益率*70%+上证国债指数收益率*25%+一年期定期存款基准利率*5%"
    )

    assert isinstance(parsed, Benchmark)
    assert [c.weight for c in parsed.components] == [70.0, 25.0, 5.0]
    assert [c.kind for c in parsed.components] == [
        ComponentKind.EQUITY,
        ComponentKind.NON_EQUITY,
        ComponentKind.NON_EQUITY,
    ]
    assert parsed.coverage == pytest.approx(1.0)


def test_accepts_multiplication_sign() -> None:
    """Some pages use the multiplication sign instead of an asterisk."""
    parsed = parse_benchmark("沪深300指数收益率×95%+银行活期存款利率(税后)×5%")

    assert parsed is not None
    assert [c.weight for c in parsed.components] == [95.0, 5.0]


def test_single_term_without_weight_becomes_100() -> None:
    """An index fund often publishes just the index name."""
    parsed = parse_benchmark("上证180公司治理指数")

    assert parsed is not None
    assert len(parsed.components) == 1
    assert parsed.components[0].weight == pytest.approx(100.0)
    assert parsed.coverage == pytest.approx(1.0)


def test_strips_label_prefix() -> None:
    """Some payloads include the label inside the value."""
    parsed = parse_benchmark("业绩比较基准：中证500指数收益率*80%+中债总指数收益率*20%")

    assert parsed is not None
    assert parsed.components[0].name.startswith("中证500")


@pytest.mark.parametrize("text", ["", "   ", "该基金无跟踪标的", "无", None])
def test_placeholder_is_not_a_benchmark(text: str | None) -> None:
    """A missing benchmark must not become an empty component list."""
    assert parse_benchmark(text) is None


def test_bond_index_is_not_equity() -> None:
    """中债总指数 contains 指数 but is a bond index; order of rules matters."""
    assert classify_component("中债总指数收益率") is ComponentKind.NON_EQUITY
    assert classify_component("上证国债指数收益率") is ComponentKind.NON_EQUITY
    assert classify_component("一年期定期存款基准利率") is ComponentKind.NON_EQUITY


def test_equity_indexes() -> None:
    """Equity indexes are recognised by the generic index rule."""
    assert classify_component("中证800指数收益率") is ComponentKind.EQUITY
    assert classify_component("中证新能源汽车指数收益率") is ComponentKind.EQUITY


def test_unknown_terms_are_not_assumed_equity() -> None:
    """Guessing equity would produce a wrong estimate instead of a missing one."""
    assert classify_component("某另类策略") is ComponentKind.UNKNOWN


def test_coverage_flags_incomplete_weights() -> None:
    """Weights that do not add up must be visible."""
    parsed = parse_benchmark("中证800指数收益率*70%+上证国债指数收益率*20%")

    assert parsed is not None
    assert parsed.coverage == pytest.approx(0.9)
