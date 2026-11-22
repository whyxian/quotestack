"""Tests for Eastmoney secid and index resolution.

Both paths exist because the identifier a quote needs is not the identifier a
caller has: US tickers need an exchange suffix, and benchmark components need
an index code.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from quotestack.errors import AmbiguousError, EmptyResponseError, SchemaChangedError
from quotestack.identity import resolve
from quotestack.models import AssetClass, Market
from quotestack.sources import EastMoneySource

_US = resolve("AAPL", AssetClass.STOCK, Market.US)


def _search(rows: list[dict[str, object]]) -> dict[str, object]:
    return {"QuotationCodeTable": {"Data": rows}}


@respx.mock
async def test_us_ticker_resolves_through_search() -> None:
    """A bare US ticker has no secid until the search endpoint supplies one."""
    respx.get(url__startswith="https://searchapi.eastmoney.com").mock(
        return_value=httpx.Response(
            200,
            json=_search(
                [
                    {"Code": "AAPL22", "SecurityTypeName": "美股", "QuoteID": "105.AAPL22"},
                    {"Code": "AAPL", "SecurityTypeName": "美股", "QuoteID": "105.AAPL"},
                ]
            ),
        )
    )
    source = EastMoneySource()
    try:
        assert await source._secid_for(_US) == "105.AAPL"
        # Second call must hit the memo, not the network.
        assert await source._secid_for(_US) == "105.AAPL"
    finally:
        await source.aclose()


@respx.mock
async def test_us_lookup_is_memoised() -> None:
    """The search endpoint is called once per ticker."""
    route = respx.get(url__startswith="https://searchapi.eastmoney.com").mock(
        return_value=httpx.Response(
            200,
            json=_search([{"Code": "AAPL", "SecurityTypeName": "美股", "QuoteID": "105.AAPL"}]),
        )
    )
    source = EastMoneySource()
    try:
        await source._secid_for(_US)
        await source._secid_for(_US)
    finally:
        await source.aclose()

    assert route.call_count == 1


@respx.mock
async def test_missing_us_symbol_is_an_empty_response() -> None:
    """Nothing found is missing data, not a broken upstream."""
    respx.get(url__startswith="https://searchapi.eastmoney.com").mock(
        return_value=httpx.Response(200, json=_search([]))
    )
    source = EastMoneySource()
    try:
        with pytest.raises(EmptyResponseError):
            await source._secid_for(_US)
    finally:
        await source.aclose()


@respx.mock
async def test_ambiguous_us_symbol_reports_candidates() -> None:
    """Two rows with the same code must not be resolved silently."""
    respx.get(url__startswith="https://searchapi.eastmoney.com").mock(
        return_value=httpx.Response(
            200,
            json=_search(
                [
                    {"Code": "AAPL", "SecurityTypeName": "美股", "QuoteID": "105.AAPL"},
                    {"Code": "AAPL", "SecurityTypeName": "美股", "QuoteID": "106.AAPL"},
                ]
            ),
        )
    )
    source = EastMoneySource()
    try:
        with pytest.raises(AmbiguousError):
            await source._secid_for(_US)
    finally:
        await source.aclose()


@respx.mock
async def test_search_payload_without_table_is_a_schema_change() -> None:
    """A missing envelope means the endpoint changed, not that nothing matched."""
    respx.get(url__startswith="https://searchapi.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"unexpected": True})
    )
    source = EastMoneySource()
    try:
        with pytest.raises(SchemaChangedError):
            await source._secid_for(_US)
    finally:
        await source.aclose()


@respx.mock
async def test_known_index_short_circuits_the_search() -> None:
    """Names in the fallback table never touch the network."""
    route = respx.get(url__startswith="https://searchapi.eastmoney.com").mock(
        return_value=httpx.Response(200, json=_search([]))
    )
    source = EastMoneySource()
    try:
        assert await source.resolve_index("上证国债指数收益率") == "1.000012"
    finally:
        await source.aclose()

    assert route.call_count == 0


@respx.mock
async def test_unknown_index_is_searched_by_name() -> None:
    """A name outside the table falls back to the search endpoint."""
    respx.get(url__startswith="https://searchapi.eastmoney.com").mock(
        return_value=httpx.Response(
            200,
            json=_search([{"Code": "000001", "SecurityTypeName": "指数", "QuoteID": "1.000001"}]),
        )
    )
    source = EastMoneySource()
    try:
        assert await source.resolve_index("某新指数收益率") == "1.000001"
    finally:
        await source.aclose()


@respx.mock
async def test_index_not_found_returns_none() -> None:
    """An unresolvable component is reported, not guessed."""
    respx.get(url__startswith="https://searchapi.eastmoney.com").mock(
        return_value=httpx.Response(200, json=_search([{"Code": "X", "SecurityTypeName": "基金"}]))
    )
    source = EastMoneySource()
    try:
        assert await source.resolve_index("不存在指数") is None
    finally:
        await source.aclose()
