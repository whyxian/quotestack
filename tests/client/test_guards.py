"""Argument validation, done before any request is made."""

from __future__ import annotations

import pytest

from quotestack import AssetClass, Market, MarketData
from quotestack.errors import UnsupportedError


async def test_resolve_requires_six_digit_mainland_codes() -> None:
    async with MarketData() as client:
        from quotestack.errors import InvalidArgumentError

        with pytest.raises(InvalidArgumentError):
            client.resolve("60051")


async def test_holdings_rejects_a_non_positive_limit() -> None:
    """A zero limit is a caller mistake, reported before any request."""
    from quotestack.errors import InvalidArgumentError

    async with MarketData() as client:
        with pytest.raises(InvalidArgumentError):
            await client.holdings("166002", limit=0)


async def test_iter_instruments_rejects_an_unmapped_market() -> None:
    """A market with no listing source is unsupported, not empty."""

    async with MarketData() as client:
        with pytest.raises(UnsupportedError):
            async for _ in client.iter_instruments(AssetClass.FUND, Market.US):
                pass


async def test_history_rejects_a_non_positive_limit() -> None:
    from quotestack.errors import InvalidArgumentError

    async with MarketData() as client:
        with pytest.raises(InvalidArgumentError):
            await client.history("600519", limit=0)


async def test_nav_and_page_size_reject_non_positive_values() -> None:
    from quotestack.errors import InvalidArgumentError

    async with MarketData() as client:
        with pytest.raises(InvalidArgumentError):
            await client.nav("022430", limit=0)
        with pytest.raises(InvalidArgumentError):
            async for _ in client.iter_instruments(AssetClass.STOCK, Market.CN, page_size=0):
                break


async def test_negative_max_age_is_rejected() -> None:
    """A negative age means "expired"; silently honouring it is a trap."""
    from quotestack.errors import InvalidArgumentError

    async with MarketData() as client:
        for call in (
            client.quote("600519", max_age=-1),
            client.history("600519", max_age=-1),
            client.nav("022430", max_age=-1),
        ):
            with pytest.raises(InvalidArgumentError):
                await call
