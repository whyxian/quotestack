"""Batch quoting must isolate failures per instrument.

The contract says a failure in one item never fails the batch. It did: a source
that could not price one code raised for the whole request, so a delisted or
suspended instrument took every other quote down with it, and the client cooled
the entire source for thirty seconds.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from quotestack import AssetClass, Market, MarketData
from quotestack.errors import EmptyResponseError
from quotestack.models import Capability, Quote
from quotestack.sources.base import SourceMeta

_TS = dt.datetime(2026, 11, 10, tzinfo=dt.UTC)


def _quote(instrument_id: str, price: str, source: str) -> Quote:
    return Quote(
        instrument_id=instrument_id,
        price=price,
        currency="CNY",
        change="0.00",
        change_pct=0.0,
        source=source,
        ts=_TS,
        status="REALTIME",
        stale=False,
    )


class _Partial:
    """Prices one of the two codes and omits the other, as a real source does."""

    meta = SourceMeta(
        name="eastmoney",
        capabilities=frozenset({Capability.QUOTE}),
        markets=frozenset({(AssetClass.STOCK, Market.CN)}),
    )

    def __init__(self, code: str) -> None:
        self._code = code

    async def quote(self, instruments: list[Any]) -> list[Quote]:
        return [
            _quote(instrument.id, "1453.00", "eastmoney")
            for instrument in instruments
            if instrument.code == self._code
        ]

    async def aclose(self) -> None:
        return None


class _Backup:
    meta = SourceMeta(
        name="tencent",
        capabilities=frozenset({Capability.QUOTE}),
        markets=frozenset({(AssetClass.STOCK, Market.CN)}),
    )

    async def quote(self, instruments: list[Any]) -> list[Quote]:
        return [_quote(instrument.id, "11.00", "tencent") for instrument in instruments]

    async def aclose(self) -> None:
        return None


async def test_missing_instrument_fails_over_instead_of_failing_the_batch() -> None:
    """The priced instrument succeeds; the other is retried on the next source."""
    client = MarketData(
        sources={"eastmoney": _Partial("600519"), "tencent": _Backup()},
        source_priority={"QUOTE": ["eastmoney", "tencent"]},
    )
    try:
        results = await client.quote_many(
            [("600519", AssetClass.STOCK, Market.CN), ("000001", AssetClass.STOCK, Market.CN)]
        )
    finally:
        await client.aclose()

    assert [result.ok for result in results] == [True, True]
    assert results[0].quote is not None
    assert results[0].quote.source == "eastmoney"
    assert results[1].quote is not None
    assert results[1].quote.source == "tencent"


async def test_a_missing_row_does_not_cool_the_source() -> None:
    """Absent data for one code says nothing about the source's health.

    EmptyResponseError is not retryable, yet the batch path cooled the source
    anyway, so grabbing one suspended code disabled it for everything else.
    """
    client = MarketData(
        sources={"eastmoney": _Partial("600519")},
        source_priority={"QUOTE": ["eastmoney"]},
    )
    try:
        for _ in range(3):
            await client.quote_many([("999998", AssetClass.STOCK, Market.CN)])
        state = client.health()["sources"]["eastmoney"]["state"]
    finally:
        await client.aclose()

    assert state == "ok"


async def test_a_total_miss_still_reports_unavailable() -> None:
    """When no source prices anything, every item says so individually."""

    class _Nothing:
        meta = SourceMeta(
            name="eastmoney",
            capabilities=frozenset({Capability.QUOTE}),
            markets=frozenset({(AssetClass.STOCK, Market.CN)}),
        )

        async def quote(self, instruments: list[Any]) -> list[Quote]:
            raise EmptyResponseError("no rows at all", source="eastmoney")

        async def aclose(self) -> None:
            return None

    client = MarketData(sources={"eastmoney": _Nothing()}, source_priority={"QUOTE": ["eastmoney"]})
    try:
        results = await client.quote_many([("600519", AssetClass.STOCK, Market.CN)])
    finally:
        await client.aclose()

    assert results[0].ok is False
    assert "UNAVAILABLE" in (results[0].error or "")


async def test_every_source_changing_shape_is_client_broken() -> None:
    """All sources unparseable is not an outage; retrying cannot help."""
    from quotestack.errors import ClientBrokenError, SchemaChangedError

    class Moved:
        def __init__(self, name: str) -> None:
            self.meta = SourceMeta(
                name=name,
                capabilities=frozenset({Capability.QUOTE}),
                markets=frozenset({(AssetClass.STOCK, Market.CN)}),
            )

        async def quote(self, instruments: list[Any]) -> list[Quote]:
            raise SchemaChangedError(
                "payload moved",
                source=self.meta.name,
                capability="quote",
                assertion="data.diff is a list",
                sample="{}",
            )

        async def aclose(self) -> None:
            return None

    client = MarketData(
        sources={"eastmoney": Moved("eastmoney"), "tencent": Moved("tencent")},
        source_priority={"QUOTE": ["eastmoney", "tencent"]},
    )
    try:
        with pytest.raises(ClientBrokenError):
            await client.quote("600519", AssetClass.STOCK, Market.CN)
    finally:
        await client.aclose()


async def test_one_source_moving_is_not_client_broken() -> None:
    """A single source changing shape is what the fallback chain is for."""

    class Moved:
        meta = SourceMeta(
            name="eastmoney",
            capabilities=frozenset({Capability.QUOTE}),
            markets=frozenset({(AssetClass.STOCK, Market.CN)}),
        )

        async def quote(self, instruments: list[Any]) -> list[Quote]:
            from quotestack.errors import SchemaChangedError

            raise SchemaChangedError(
                "payload moved",
                source="eastmoney",
                capability="quote",
                assertion="a",
                sample="b",
            )

        async def aclose(self) -> None:
            return None

    client = MarketData(
        sources={"eastmoney": Moved(), "tencent": _Backup()},
        source_priority={"QUOTE": ["eastmoney", "tencent"]},
    )
    try:
        quote = await client.quote("600519", AssetClass.STOCK, Market.CN)
    finally:
        await client.aclose()

    assert quote.source == "tencent"


async def test_a_batch_where_every_source_moved_reports_client_broken() -> None:
    """The batch path must name the same condition as the single path.

    It reported UNAVAILABLE, which tells a caller to retry something that will
    fail identically until the parser is updated.
    """
    from quotestack.errors import SchemaChangedError

    class Moved:
        def __init__(self, name: str) -> None:
            self.meta = SourceMeta(
                name=name,
                capabilities=frozenset({Capability.QUOTE}),
                markets=frozenset({(AssetClass.STOCK, Market.CN)}),
            )

        async def quote(self, instruments: list[Any]) -> list[Quote]:
            raise SchemaChangedError(
                "payload moved",
                source=self.meta.name,
                capability="quote",
                assertion="data.diff is a list",
                sample="{}",
            )

        async def aclose(self) -> None:
            return None

    client = MarketData(
        sources={"eastmoney": Moved("eastmoney"), "tencent": Moved("tencent")},
        source_priority={"QUOTE": ["eastmoney", "tencent"]},
    )
    try:
        results = await client.quote_many([("600519", AssetClass.STOCK, Market.CN)])
    finally:
        await client.aclose()

    assert results[0].ok is False
    assert "CLIENT_BROKEN" in (results[0].error or "")


async def test_a_batch_with_a_transient_failure_is_unavailable() -> None:
    """A timeout is not a schema change."""

    class Down:
        meta = SourceMeta(
            name="eastmoney",
            capabilities=frozenset({Capability.QUOTE}),
            markets=frozenset({(AssetClass.STOCK, Market.CN)}),
        )

        async def quote(self, instruments: list[Any]) -> list[Quote]:
            from quotestack.errors import TimeoutError

            raise TimeoutError("slow", source="eastmoney")

        async def aclose(self) -> None:
            return None

    client = MarketData(sources={"eastmoney": Down()}, source_priority={"QUOTE": ["eastmoney"]})
    try:
        results = await client.quote_many([("600519", AssetClass.STOCK, Market.CN)])
    finally:
        await client.aclose()

    assert "UNAVAILABLE" in (results[0].error or "")
