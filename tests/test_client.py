"""Client-level tests for caching, cooldown and stale fallback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from quotestack import AssetClass, Market, MarketData
from quotestack.cache import CacheEntry, MemoryCache
from quotestack.errors import UnavailableError, UpstreamError
from quotestack.models import Capability, Quote, QuoteStatus
from quotestack.sources.base import SourceMeta


class FailingSource:
    """A source that always fails."""

    meta = SourceMeta(
        name="fake",
        capabilities=frozenset({Capability.QUOTE, Capability.HISTORY}),
        markets=frozenset({(AssetClass.STOCK, Market.CN)}),
    )

    def __init__(self) -> None:
        self.calls = 0

    async def quote(self, instruments: list[object]) -> list[Quote]:
        self.calls += 1
        raise UpstreamError("boom", source="fake")

    async def history(self, *args: object, **kwargs: object) -> list[object]:
        self.calls += 1
        raise UpstreamError("boom", source="fake")

    async def aclose(self) -> None:
        return None


class FixedCache(MemoryCache):
    """A cache that always returns one prepared entry."""

    def __init__(self, entry: CacheEntry) -> None:
        super().__init__()
        self._entry = entry

    def get(self, key: str) -> CacheEntry | None:
        return self._entry


def _stale_quote() -> Quote:
    return Quote(
        instrument_id="CN:STOCK:600519",
        price="1453.00",
        currency="CNY",
        source="fake",
        ts=datetime.now(UTC) - timedelta(hours=2),
        status=QuoteStatus.REALTIME,
    )


async def test_failure_opens_cooldown_and_fails_fast() -> None:
    """The second call is rejected by the cooldown without hitting the source."""
    source = FailingSource()
    async with MarketData(
        sources={"fake": source}, source_priority={"QUOTE": ["fake"], "HISTORY": ["fake"]}
    ) as client:  # type: ignore[arg-type]
        with pytest.raises(UpstreamError):
            await client.quote("600519")

        # Cooldown is now active: no second upstream attempt.
        with pytest.raises(UnavailableError):
            await client.quote("600519")

    assert source.calls == 1


async def test_stale_value_is_served_within_max_stale() -> None:
    """A failing upstream falls back to a cached value inside max_stale."""
    entry = CacheEntry(
        value=_stale_quote(),
        fetched_at=datetime.now(UTC) - timedelta(hours=2),
        source="fake",
    )
    source = FailingSource()
    async with MarketData(
        cache=FixedCache(entry), sources={"fake": source}, source_priority={"QUOTE": ["fake"]}
    ) as client:  # type: ignore[arg-type]
        quote = await client.quote("600519")

    assert quote.stale is True
    assert quote.price == "1453.00"


async def test_expired_value_is_not_served() -> None:
    """A value older than max_stale is rejected rather than served."""
    entry = CacheEntry(
        value=_stale_quote(),
        fetched_at=datetime.now(UTC) - timedelta(days=3),
        source="fake",
    )
    source = FailingSource()
    async with MarketData(
        cache=FixedCache(entry), sources={"fake": source}, source_priority={"QUOTE": ["fake"]}
    ) as client:  # type: ignore[arg-type]
        with pytest.raises(UnavailableError):
            await client.quote("600519")


async def test_offexchange_fund_quote_is_unsupported() -> None:
    """A fund without an exchange listing cannot produce a quote."""
    async with MarketData() as client:
        with pytest.raises(Exception, match="quote data"):
            await client.quote("022430", AssetClass.FUND, Market.CN)
