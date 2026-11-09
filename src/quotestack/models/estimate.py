"""Fund intraday estimate."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from quotestack.models.enums import EstimateBasis

__all__ = ["BenchmarkAssumption", "Estimate"]


@dataclass(frozen=True, slots=True)
class BenchmarkAssumption:
    """How the benchmark components were classified for the estimate.

    Exposing this is deliberate: when a component is misclassified the caller
    can see why the number looks wrong instead of guessing.

    Args:
        equity: Component names treated as equity exposure.
        non_equity: Component names treated as bonds, deposits or cash.
        unclassified: Names the rules did not recognise. A non-empty list means
            the keyword table should be extended.
    """

    equity: tuple[str, ...] = ()
    non_equity: tuple[str, ...] = ()
    unclassified: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Estimate:
    """Best-effort intraday change estimate.

    Args:
        change_pct: Estimated percent change, or ``None`` when it cannot be
            computed. ``None`` is not ``0``: one means unknown, the other means
            unchanged.
        basis: Which formula produced the number.
        coverage: Share of the fund the estimate explains, between 0 and 1.
        as_of: When the estimate was computed.
        explanation: A sentence describing the calculation, suitable for
            showing to a user.
        benchmark_assumption: Classification used for benchmark components.
    """

    change_pct: float | None
    basis: EstimateBasis
    coverage: float | None = None
    as_of: dt.datetime | None = None
    explanation: str = ""
    benchmark_assumption: BenchmarkAssumption | None = None
