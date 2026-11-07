"""Lightweight instrument metadata used by universe listings.

A listing returns *static* metadata only: prices and market caps belong to
``Quote`` and change far faster than the daily refresh cadence of a listing.
Mixing them would give one object two very different expiry times.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from quotestack.models.enums import AssetClass, Market

__all__ = ["InstrumentSummary"]


@dataclass(frozen=True, slots=True)
class InstrumentSummary:
    """One entry of a market listing.

    Optional fields are ``None`` when the source does not publish them; a
    consumer must not assume they are populated.

    Args:
        code: Source-facing code, e.g. ``600519``, ``AAPL`` or ``BTCUSDT``.
        name: Display name. Crypto pairs carry the base asset only.
        asset_class: Business classification.
        market: Trading venue.
        currency: Currency the instrument is priced in.
        listing_date: First trading day, when the source publishes it.
        board: Trading board, e.g. ``主板``, ``创业板``, ``NASDAQ``.
        industry: Sector label. Reference only; sources revise these.
        fund_type: Fund classification, e.g. ``混合型-灵活``.
    """

    code: str
    name: str
    asset_class: AssetClass
    market: Market
    currency: str
    listing_date: dt.date | None = None
    board: str | None = None
    industry: str | None = None
    fund_type: str | None = None
