"""Tests for source routing and batch quotes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from quotestack import AssetClass, Market, MarketData
from quotestack.errors import UpstreamError
from quotestack.models import Capability, Quote, QuoteStatus
from quotestack.sources.base import SourceMeta
from quotestack.sources.routing import route


class _Source:
    """A fake quoter with a configurable failure mode."""

    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.meta = SourceMeta(
            name=name,
            capabilities=frozenset({Capability.QUOTE}),
            markets=frozenset({(AssetClass.STOCK, Market.CN)}),
        )
        self._fail = fail
        self.calls: list[str] = []

    def _quote(self, instrument: Any, price: str) -> Quote:
        return Quote(
            instrument_id=instrument.id,
            price=price,
            currency=instrument.currency,
            source=self.meta.name,
            ts=datetime.now(UTC),
            status=QuoteStatus.REALTIME,
        )

    async def quote(self, instruments: list[Any]) -> list[Quote]:
        self.calls.append(self.meta.name)
        if self._fail:
            raise UpstreamError("down", source=self.meta.name)
        return [self._quote(item, "1.00") for item in instruments]

    async def aclose(self) -> None:
        return None


def test_route_prefers_eastmoney_for_mainland() -> None:
    """Mainland quotes try Eastmoney before Tencent."""
    assert route(AssetClass.STOCK, Market.CN, Capability.QUOTE) == ("eastmoney", "tencent")


def test_route_unknown_pair_is_empty() -> None:
    """An unregistered combination has no candidates."""
    assert route(AssetClass.CRYPTO, Market.CRYPTO, Capability.QUOTE) == ()


async def test_batch_uses_fallback_source() -> None:
    """When the first source fails, the next one serves the whole group."""
    primary = _Source("eastmoney", fail=True)
    backup = _Source("tencent")
    client = MarketData(
        sources={"eastmoney": primary, "tencent": backup},
        source_priority={"QUOTE": ["eastmoney", "tencent"]},
    )
    try:
        results = await client.quote_many(
            [
                ("600519", AssetClass.STOCK, Market.CN),
                ("000001", AssetClass.STOCK, Market.CN),
            ]
        )
    finally:
        await client.aclose()

    assert all(result.ok for result in results)
    assert {result.quote.source for result in results if result.quote} == {"tencent"}
    assert primary.calls == ["eastmoney"]
    assert backup.calls == ["tencent"]


async def test_batch_keeps_length_and_order_on_partial_failure() -> None:
    """Items that cannot be served are reported, others still succeed."""
    client = MarketData(
        sources={"eastmoney": _Source("eastmoney")},
        source_priority={"QUOTE": ["eastmoney"]},
    )
    try:
        results = await client.quote_many(
            [
                ("600519", AssetClass.STOCK, Market.CN),
                ("022430", AssetClass.FUND, Market.CN),  # off-exchange, no quote
                ("000001", AssetClass.STOCK, Market.CN),
            ]
        )
    finally:
        await client.aclose()

    assert len(results) == 3
    assert [result.ok for result in results] == [True, False, True]
    assert "UNSUPPORTED" in (results[1].error or "")


async def test_batch_reports_invalid_codes() -> None:
    """An unparsable code becomes a per-item error, not an exception."""
    client = MarketData(
        sources={"eastmoney": _Source("eastmoney")},
        source_priority={"QUOTE": ["eastmoney"]},
    )
    try:
        results = await client.quote_many([("ABC", AssetClass.STOCK, Market.CN)])
    finally:
        await client.aclose()

    assert results[0].ok is False
    assert "INVALID_ARGUMENT" in (results[0].error or "")


async def test_batch_of_one_matches_quote() -> None:
    """A single-item batch behaves like a normal quote."""
    client = MarketData(
        sources={"eastmoney": _Source("eastmoney")},
        source_priority={"QUOTE": ["eastmoney"]},
    )
    try:
        batch = await client.quote_many([("600519", AssetClass.STOCK, Market.CN)])
        single = await client.quote("600519")
    finally:
        await client.aclose()

    assert batch[0].ok
    assert batch[0].quote is not None
    assert batch[0].quote.price == single.price


@pytest.mark.parametrize("count", [2, 5])
async def test_batch_preserves_count(count: int) -> None:
    """Every requested item produces exactly one result."""
    client = MarketData(
        sources={"eastmoney": _Source("eastmoney")},
        source_priority={"QUOTE": ["eastmoney"]},
    )
    items = [("600519", AssetClass.STOCK, Market.CN)] * count
    try:
        results = await client.quote_many(items)
    finally:
        await client.aclose()

    assert len(results) == count
