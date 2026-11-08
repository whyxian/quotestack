"""Benchmark parsing and equity classification.

A fund's benchmark is published as one Chinese sentence::

    中证800指数收益率*70%+上证国债指数收益率*25%+一年期定期存款基准利率*5%

To weight an index curve we need it broken into components, and to know how
much of the fund is equity we need each component classified.

The classification is deliberately conservative: an unrecognised component is
``UNKNOWN`` rather than assumed to be equity, because guessing wrong produces a
wrong estimate instead of a missing one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "Benchmark",
    "BenchmarkComponent",
    "ComponentKind",
    "classify_component",
    "parse_benchmark",
]


class ComponentKind(StrEnum):
    """What a benchmark component tracks."""

    EQUITY = "EQUITY"
    NON_EQUITY = "NON_EQUITY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class BenchmarkComponent:
    """One term of a benchmark.

    Args:
        name: Component name as published, e.g. ``中证800指数收益率``.
        weight: Percent of the benchmark, ``70`` meaning 70%.
        kind: Equity classification used by the estimator.
    """

    name: str
    weight: float
    kind: ComponentKind


@dataclass(frozen=True, slots=True)
class Benchmark:
    """A parsed benchmark.

    Args:
        text: The original sentence, kept for display.
        components: Parsed terms in published order.
        coverage: Summed weight divided by 100. Below 1 means the sentence did
            not publish weights, or they do not add up.
    """

    text: str
    components: list[BenchmarkComponent]
    coverage: float


# A term ends either with an explicit weight (``*70%``) or with nothing.
# The multiplication sign is part of the published text, not a typo.
_TERM = re.compile(r"^(?P<name>.+?)(?:[*×xX]\s*(?P<weight>\d+(?:\.\d+)?)\s*%)?$")

# Order matters: the first match wins, so bonds are checked before the generic
# index rule that would otherwise claim 中债指数.
_NON_EQUITY = (
    "债",
    "存款",
    "利率",
    "货币",
    "现金",
    "同业存单",
    "理财",
    "票据",
    "回购",
)

# Full-width plus appears in some published benchmarks.
_SPLIT = re.compile(r"[+＋]")


def parse_benchmark(text: str) -> Benchmark | None:
    """Split a benchmark sentence into weighted components.

    Args:
        text: Published benchmark, possibly empty or a placeholder.

    Returns:
        The parsed benchmark, or ``None`` when the text carries no benchmark
        (for example ``该基金无跟踪标的`` or an empty string).

    Example:
        >>> parsed = parse_benchmark("中证800指数收益率*70%+上证国债指数收益率*30%")
        >>> [(c.name, c.weight) for c in parsed.components]
        [('中证800指数收益率', 70.0), ('上证国债指数收益率', 30.0)]
    """
    cleaned = _clean(text)
    if not cleaned:
        return None

    terms = [term.strip() for term in _SPLIT.split(cleaned) if term.strip()]
    components: list[BenchmarkComponent] = []
    for term in terms:
        match = _TERM.match(term)
        if match is None:
            continue
        name = match.group("name").strip()
        if not name:
            continue
        raw_weight = match.group("weight")
        weight = float(raw_weight) if raw_weight is not None else None
        components.append(
            BenchmarkComponent(
                name=name,
                weight=weight if weight is not None else 0.0,
                kind=classify_component(name),
            )
        )

    if not components:
        return None

    # A sentence with no published weights is a single 100% component.
    if all(component.weight == 0.0 for component in components):
        components = [
            BenchmarkComponent(name=c.name, weight=100.0 / len(components), kind=c.kind)
            for c in components
        ]

    total = sum(component.weight for component in components)
    return Benchmark(text=text.strip(), components=components, coverage=round(total / 100, 4))


def classify_component(name: str) -> ComponentKind:
    """Classify a component by its name.

    Args:
        name: Component text, e.g. ``上证国债指数收益率``.

    Returns:
        ``NON_EQUITY`` for bonds, deposits and money market terms,
        ``EQUITY`` for equity indexes, and ``UNKNOWN`` otherwise.
    """
    folded = name.strip()
    if any(keyword in folded for keyword in _NON_EQUITY):
        return ComponentKind.NON_EQUITY
    if "指数" in folded or "股票" in folded or "权益" in folded:
        return ComponentKind.EQUITY
    return ComponentKind.UNKNOWN


def _clean(text: str | None) -> str | None:
    """Strip placeholders and filler that appear in the published sentence."""
    if text is None:
        return None
    cleaned = text.strip().replace("\u00a0", " ")
    for placeholder in (
        "该基金无跟踪标的",
        "该基金暂未披露业绩比较基准",
        "暂未披露业绩比较基准",
        "无",
        "暂无",
        "--",
        "-",
    ):
        if cleaned == placeholder:
            return None
    # Some pages prefix the sentence with the label itself.
    cleaned = re.sub(r"^业绩比较基准[:：]?", "", cleaned)
    return cleaned.strip() or None
