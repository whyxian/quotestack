"""Fund quarterly holdings."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

__all__ = ["Holding", "QuarterHoldings"]


@dataclass(frozen=True, slots=True)
class Holding:
    """One stock position within a quarterly report.

    Args:
        code: Stock code as published, e.g. ``600519``.
        name: Stock name.
        weight: Share of net assets, in percent. ``4.66`` means 4.66%.
    """

    code: str
    name: str
    weight: float


@dataclass(frozen=True, slots=True)
class QuarterHoldings:
    """Top holdings for one quarter.

    Args:
        quarter: Quarter label such as ``2026Q3``.
        as_of: Quarter end date, derived from the label.
        holdings: Positions ordered by weight, largest first.
    """

    quarter: str
    as_of: dt.date
    holdings: list[Holding]
