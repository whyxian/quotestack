"""Live smoke tests.

These hit real sources, so they are skipped unless ``QUOTESTACK_LIVE=1``.
Run them before a release, not in CI::

    QUOTESTACK_LIVE=1 .venv/bin/pytest tests/test_smoke.py -q
"""

from __future__ import annotations

import os

import pytest

from quotestack import AssetClass, Interval, Market, MarketData

pytestmark = pytest.mark.skipif(
    not os.getenv("QUOTESTACK_LIVE"),
    reason="set QUOTESTACK_LIVE=1 to run against real sources",
)


async def test_live_quote_mainland_stock() -> None:
    """A mainland stock returns a usable quote."""
    async with MarketData() as client:
        quote = await client.quote("600519", AssetClass.STOCK, Market.CN)

    assert quote.price
    assert float(quote.price) > 0
    assert quote.currency == "CNY"
    assert quote.source == "eastmoney"


async def test_live_history_daily() -> None:
    """Daily bars come back in ascending order."""
    async with MarketData() as client:
        bars = await client.history("600519", limit=5)

    assert len(bars) == 5
    assert bars[0].date < bars[-1].date


async def test_live_history_intraday_keeps_clock() -> None:
    """Minute bars carry a time component."""
    async with MarketData() as client:
        bars = await client.history("600519", interval=Interval.M5, limit=3)

    assert bars
    assert bars[-1].time is not None
