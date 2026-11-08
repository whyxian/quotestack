"""Fund asset allocation."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

__all__ = ["Allocation"]


@dataclass(frozen=True, slots=True)
class Allocation:
    """Share of net assets by asset type, as published.

    The three ratios do not always sum to 100: a feeder fund parks most of its
    assets in the target ETF, which none of these columns show.

    Args:
        stock: Stock share of net assets, in percent.
        bond: Bond share, in percent.
        cash: Cash share, in percent.
        as_of: Reporting date.
    """

    stock: float
    bond: float
    cash: float
    as_of: dt.date | None = None

    @property
    def other(self) -> float:
        """Everything not reported as stock, bond or cash."""
        return max(0.0, 100.0 - self.stock - self.bond - self.cash)

    @property
    def equity_exposure(self) -> float:
        """Best guess at how much of the fund moves with equities.

        For a fund that holds stocks directly this is ``stock``. For a feeder
        fund it is ``stock + other``, because the target ETF sits in ``other``.
        """
        return min(100.0, self.stock + self.other)
