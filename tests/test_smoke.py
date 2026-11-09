"""Live probe against real sources.

Skipped unless ``QUOTESTACK_LIVE=1``. The scheduled workflow runs it to notice
when an upstream changes shape, which fixtures never will.

**The distinction this file makes**: a *transport* failure (no route, timeout,
the source refusing a datacenter IP) is an environment problem and skips. A
*structural* failure (a payload that no longer parses) is the signal the probe
exists to catch, and fails.

Asserting which source answered would be wrong: fallback is the feature, so the
probe would fail precisely when the library works as designed.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from quotestack import AssetClass, Interval, Market, MarketData
from quotestack.errors import (
    EmptyResponseError,
    RateLimitedError,
    SchemaChangedError,
    TimeoutError,
    UnavailableError,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("QUOTESTACK_LIVE"),
    reason="set QUOTESTACK_LIVE=1 to run against real sources",
)

# Transport problems: the runner could not reach the source at all.
TRANSPORT = (UnavailableError, TimeoutError, RateLimitedError)
# Structural problems: the source answered, but not in the shape we expect.
STRUCTURAL = (SchemaChangedError, EmptyResponseError)


async def resolve_or_skip(awaitable: Any) -> Any:
    """Await a live call, converting an environment problem into a skip.

    Kept separate so the policy can be tested without a network: a structural
    change must fail, a transport problem must not.
    """
    try:
        return await awaitable
    except STRUCTURAL:
        raise
    except TRANSPORT as exc:
        pytest.skip(f"cannot reach the source from this runner: {exc.code}")


async def test_live_quote_mainland_stock() -> None:
    """A mainland stock returns a usable, fresh quote from some source."""
    async with MarketData() as client:
        quote = await resolve_or_skip(client.quote("600519", AssetClass.STOCK, Market.CN))

    print(f"\nanswered by {quote.source}, stale={quote.stale}")
    assert quote.price and quote.price != "-"
    assert float(quote.price) > 0
    assert quote.currency == "CNY"
    assert quote.instrument_id == "CN:STOCK:600519"


async def test_live_history_daily() -> None:
    """Daily bars come back in ascending order, from the only source that has them."""
    async with MarketData() as client:
        bars = await resolve_or_skip(client.history("600519", limit=5))

    assert len(bars) == 5
    assert bars[0].date < bars[-1].date
    assert all(bar.close and bar.close != "-" for bar in bars)


async def test_live_history_intraday_keeps_clock() -> None:
    """Minute bars carry a time component."""
    async with MarketData() as client:
        bars = await resolve_or_skip(client.history("600519", interval=Interval.M5, limit=3))

    assert bars
    assert bars[-1].time is not None


async def test_live_fund_nav_still_parses() -> None:
    """The fund NAV payload is the most fragile one we parse."""
    async with MarketData() as client:
        points = await resolve_or_skip(client.nav("022430", limit=5))

    assert points
    assert all(point.nav and point.nav != "-" for point in points)
