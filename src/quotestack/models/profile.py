"""Fund profile."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from quotestack.benchmark import Benchmark
from quotestack.models.enums import FundClass

__all__ = ["Profile"]


@dataclass(frozen=True, slots=True)
class Profile:
    """Static description of a fund.

    Every field is optional because the source publishes them unevenly; a
    consumer must check ``partial`` before treating a missing field as "none".

    Args:
        fund_type: Raw source label, e.g. ``混合型-偏股``.
        fund_class: Normalised category derived from ``fund_type``.
        tracking_index: Index the fund tracks, when it is an index fund.
        benchmark: Parsed performance benchmark.
        company: Fund management company.
        manager: Individual managers, as published.
        custodian: Custodian bank.
        scale: Net assets with unit, e.g. ``80.39亿元``.
        inception_date: Fund inception date.
        as_of: Reporting date the scale and holdings refer to.
        missing: Names of fields the source did not publish.
    """

    fund_type: str | None = None
    fund_class: FundClass | None = None
    tracking_index: str | None = None
    benchmark: Benchmark | None = None
    company: str | None = None
    manager: str | None = None
    custodian: str | None = None
    scale: str | None = None
    inception_date: dt.date | None = None
    as_of: dt.date | None = None
    missing: tuple[str, ...] = ()

    @property
    def partial(self) -> bool:
        """Whether any field was missing from the source."""
        return bool(self.missing)
