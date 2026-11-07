"""Composed benchmark curves."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from quotestack.benchmark import BenchmarkComponent

__all__ = ["BenchmarkCurve", "BenchmarkPoint"]


@dataclass(frozen=True, slots=True)
class BenchmarkPoint:
    """One point on a weighted benchmark curve.

    Args:
        date: Trading day.
        value: Cumulative value with the first day normalised to 1.
    """

    date: dt.date
    value: float


@dataclass(frozen=True, slots=True)
class BenchmarkCurve:
    """Weighted curve built from a fund's benchmark components.

    Args:
        effective_start: First day every used component has data for.
        components_used: Components that contributed to the curve.
        components_dropped: Component names with no available history, such as
            the China bond indexes.
        coverage: Used weight divided by 100. Below 1 means the curve is built
            from a subset of the benchmark.
        series: Points in ascending date order.
    """

    effective_start: dt.date | None
    components_used: list[BenchmarkComponent]
    components_dropped: list[str]
    coverage: float
    series: list[BenchmarkPoint]
