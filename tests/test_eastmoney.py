"""Tests for the Eastmoney adapter using recorded response shapes."""

from __future__ import annotations

import httpx
import pytest
import respx

from quotestack.errors import EmptyResponseError, SchemaChangedError
from quotestack.identity import resolve
from quotestack.models import AssetClass, Market
from quotestack.sources import EastMoneySource

_HOST = "https://push2.eastmoney.com"

_STOCK = resolve("600519", AssetClass.STOCK, Market.CN)
_ETF = resolve("510010", AssetClass.FUND, Market.CN)


def _payload(*rows: dict[str, object]) -> dict[str, object]:
    return {"rc": 0, "data": {"total": len(rows), "diff": list(rows)}}


@respx.mock
async def test_quote_parses_scaled_integers() -> None:
    """Prices arrive as scaled integers; f1 carries the decimal places."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(
            200,
            json=_payload(
                {"f1": 2, "f2": 145300, "f3": 7, "f4": 100, "f12": "600519", "f124": 1793952699},
            ),
        )
    )
    source = EastMoneySource()
    try:
        quotes = await source.quote([_STOCK])
    finally:
        await source.aclose()

    assert quotes[0].price == "1453.00"
    assert quotes[0].change == "1.00"
    assert quotes[0].change_pct == pytest.approx(0.07)
    assert quotes[0].currency == "CNY"


@respx.mock
async def test_quote_honours_per_instrument_decimals() -> None:
    """ETFs quote with three decimals, unlike two-decimal stocks."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(
            200,
            json=_payload({"f1": 3, "f2": 1760, "f3": 0, "f4": 0, "f12": "510010", "f124": 0}),
        )
    )
    source = EastMoneySource()
    try:
        quotes = await source.quote([_ETF])
    finally:
        await source.aclose()

    assert quotes[0].price == "1.760"


@respx.mock
async def test_quote_raises_when_row_missing() -> None:
    """A requested instrument absent from the payload is reported, not ignored."""
    respx.get(host="push2.eastmoney.com").mock(return_value=httpx.Response(200, json=_payload()))
    source = EastMoneySource()
    try:
        with pytest.raises(EmptyResponseError) as excinfo:
            await source.quote([_STOCK])
    finally:
        await source.aclose()

    assert excinfo.value.context["missing"] == ["600519"]


@respx.mock
async def test_quote_raises_on_missing_data_field() -> None:
    """A payload without 'data' means the upstream schema changed."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"rc": 0, "result": {}})
    )
    source = EastMoneySource()
    try:
        with pytest.raises(SchemaChangedError) as excinfo:
            await source.quote([_STOCK])
    finally:
        await source.aclose()

    assert "sample" in excinfo.value.context


@respx.mock
async def test_quote_raises_on_malformed_diff() -> None:
    """A non-list 'diff' also counts as a schema change."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"rc": 0, "data": {"diff": None}})
    )
    source = EastMoneySource()
    try:
        with pytest.raises(SchemaChangedError):
            await source.quote([_STOCK])
    finally:
        await source.aclose()
