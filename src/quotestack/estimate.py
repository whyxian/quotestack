"""Pure helpers for the intraday estimate.

The client does the I/O; everything here is arithmetic and wording so it can
be tested without a network.
"""

from __future__ import annotations

from quotestack.benchmark import Benchmark, BenchmarkComponent, ComponentKind
from quotestack.models import BenchmarkAssumption

__all__ = [
    "assumption_of",
    "describe_holdings",
    "describe_index",
    "equity_proxy",
    "weighted_change",
]


def assumption_of(benchmark: Benchmark | None) -> BenchmarkAssumption:
    """Group benchmark components by how they were classified.

    Args:
        benchmark: Parsed benchmark, or ``None``.

    Returns:
        The three groups, exposed so a caller can see which names drove the
        estimate and which were not recognised.
    """
    if benchmark is None:
        return BenchmarkAssumption()

    equity: list[str] = []
    non_equity: list[str] = []
    unclassified: list[str] = []
    for component in benchmark.components:
        if component.kind is ComponentKind.EQUITY:
            equity.append(component.name)
        elif component.kind is ComponentKind.NON_EQUITY:
            non_equity.append(component.name)
        else:
            unclassified.append(component.name)
    return BenchmarkAssumption(
        equity=tuple(equity),
        non_equity=tuple(non_equity),
        unclassified=tuple(unclassified),
    )


def equity_proxy(benchmark: Benchmark | None) -> list[tuple[BenchmarkComponent, float]]:
    """Return equity components with their weights renormalised to 100%.

    The remainder of a fund's equity exposure is proxied by the equity part of
    its benchmark only; bond and deposit components say nothing about how
    stocks moved.

    Args:
        benchmark: Parsed benchmark, or ``None``.

    Returns:
        ``(component, weight)`` pairs where the weights sum to 100. Empty when
        the benchmark has no equity component.

    Example:
        >>> # 中证800x70% + 中债x30% -> [(中证800, 100.0)]
    """
    if benchmark is None:
        return []
    equity = [
        component for component in benchmark.components if component.kind is ComponentKind.EQUITY
    ]
    total = sum(component.weight for component in equity)
    if total <= 0:
        return []
    return [(component, component.weight / total * 100) for component in equity]


def weighted_change(
    weights: list[tuple[str, float]],
    changes: dict[str, float],
) -> tuple[float, float] | None:
    """Combine component changes by weight.

    Args:
        weights: ``(secid, weight_percent)`` pairs.
        changes: Percent change per secid.

    Returns:
        ``(weighted_change, used_weight)``, or ``None`` when nothing matched.
    """
    total = 0.0
    used = 0.0
    for secid, weight in weights:
        change = changes.get(secid)
        if change is None:
            continue
        total += change * weight
        used += weight
    if used <= 0:
        return None
    return total / used, used


def describe_index(name: str, index_change: float, exposure: float, result: float) -> str:
    """Explain an index-based estimate in one sentence."""
    return (
        f"指数型：跟踪「{name}」实时涨跌 {index_change:+.2f}%"
        f" × 权益仓位 {exposure:.1%} = {result:+.2f}%"
    )


def describe_holdings(
    top_weight: float,
    top_change: float,
    remainder: float,
    proxy_change: float | None,
    result: float,
) -> str:
    """Explain a holdings-based estimate in one sentence."""
    parts = [f"前十大合计 {top_weight:.1f}%，贡献 {top_change:+.2f}%"]
    if proxy_change is None:
        parts.append(f"剩余 {remainder:.1f}% 无基准成分可用，按 0 计")
    else:
        parts.append(
            f"剩余 {remainder:.1f}% 按权益基准 {proxy_change:+.2f}% 补"
            f"（{remainder / 100 * proxy_change:+.2f}%）"
        )
    parts.append(f"合计 {result:+.2f}%")
    return "；".join(parts)
