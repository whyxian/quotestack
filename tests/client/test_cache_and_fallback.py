"""Cache freshness, staleness and cooldown, plus the one capability with its own TTL."""

from __future__ import annotations

import datetime as dt
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from tests.support.fakes import make_meta

from quotestack import AssetClass, Market, MarketData
from quotestack.cache import CacheEntry, MemoryCache
from quotestack.errors import UnavailableError, UpstreamError
from quotestack.models import Capability, Quote, QuoteStatus


class FailingSource:
    """A source that always fails."""

    meta = make_meta(
        "fake", {Capability.QUOTE, Capability.HISTORY}, {(AssetClass.STOCK, Market.CN)}
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
    """After two consecutive failures the source is skipped entirely."""
    source = FailingSource()
    client = MarketData(
        sources={"fake": source},
        source_priority={"QUOTE": ["fake"]},
    )
    try:
        # Two failures reach the source: a single blip must not cool it.
        for _ in range(2):
            with pytest.raises(UnavailableError):
                await client.quote("600519")

        # Cooldown is now active, so the third call never reaches the source.
        with pytest.raises(UnavailableError) as excinfo:
            await client.quote("600519")
    finally:
        await client.aclose()

    assert source.calls == 2
    assert excinfo.value.context["attempts"][0]["reason"] == "cooldown"


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


async def test_history_limit_changes_the_answer_not_the_cache() -> None:
    """Two different limits are two different questions.

    The cache key omitted `limit`, so `history(limit=5)` wrote five bars under a
    key that `history(limit=50)` then read, and the second call returned five.
    """

    from quotestack.models import Bar, Capability

    class Fake:
        meta = make_meta("fake", {Capability.HISTORY}, {(AssetClass.STOCK, Market.CN)})
        calls = 0

        async def history(
            self, instrument: Any, interval: Any, adjust: Any, limit: int
        ) -> list[Bar]:
            Fake.calls += 1
            return [
                Bar(
                    date=dt.date(2026, 1, 1) + dt.timedelta(days=index),
                    open="1",
                    high="2",
                    low="0.5",
                    close="1.5",
                    volume="100",
                )
                for index in range(limit)
            ]

        async def aclose(self) -> None:
            return None

    client = MarketData(sources={"fake": Fake()}, source_priority={"HISTORY": ["fake"]})
    try:
        small = await client.history("600519", limit=5)
        large = await client.history("600519", limit=50)
    finally:
        await client.aclose()

    assert len(small) == 5
    assert len(large) == 50
    assert Fake.calls == 2


async def test_fx_rates_are_cached_for_the_configured_ttl() -> None:
    """A page with ten dollar holdings asked for the same pair ten times."""

    from quotestack.models import Capability, FxRate

    class Rates:
        meta = make_meta("fx", {Capability.FX}, frozenset())

        calls = 0

        async def fx(self, base: str, quote: str) -> FxRate:
            Rates.calls += 1
            return FxRate(
                base=base,
                quote=quote,
                rate="6.6738",
                source="fx",
                as_of=dt.datetime.now(dt.UTC),
                derived=False,
            )

        async def aclose(self) -> None:
            return None

    client = MarketData(sources={"fx": Rates()})
    try:
        first = await client.fx("USD", "CNY")
        second = await client.fx("USD", "CNY")
        third = await client.fx("CNY", "USD")
    finally:
        await client.aclose()

    assert first.rate == second.rate == "6.6738"
    assert Rates.calls == 2, f"asked upstream {Rates.calls} times, expected 2"
    assert third.base == "CNY"


async def test_fx_cache_ignores_case() -> None:

    from quotestack.models import Capability, FxRate

    class Rates:
        meta = make_meta("fx", {Capability.FX}, frozenset())
        calls = 0

        async def fx(self, base: str, quote: str) -> FxRate:
            Rates.calls += 1
            return FxRate(
                base=base,
                quote=quote,
                rate="1",
                source="fx",
                as_of=dt.datetime.now(dt.UTC),
                derived=False,
            )

        async def aclose(self) -> None:
            return None

    client = MarketData(sources={"fx": Rates()})
    try:
        await client.fx("usd", "cny")
        await client.fx("USD", "CNY")
    finally:
        await client.aclose()

    assert Rates.calls == 1
