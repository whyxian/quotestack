"""Kline guards and index-curve fetches."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from quotestack.errors import EmptyResponseError, SchemaChangedError, UpstreamError
from quotestack.identity import resolve
from quotestack.models import Adjust, AssetClass, Interval, Market
from quotestack.sources import EastMoneySource

_STOCK = resolve("600519", AssetClass.STOCK, Market.CN)
_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


@respx.mock
async def test_history_http_error_is_upstream() -> None:
    respx.get(host="push2his.eastmoney.com").mock(return_value=httpx.Response(502))
    source = EastMoneySource()
    try:
        with pytest.raises(UpstreamError):
            await source.history(_STOCK, Interval.D1, Adjust.QFQ, 10)
    finally:
        await source.aclose()


@respx.mock
async def test_history_payload_without_data_key_is_a_schema_change() -> None:
    respx.get(host="push2his.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"something": 1})
    )
    source = EastMoneySource()
    try:
        with pytest.raises(SchemaChangedError):
            await source.history(_STOCK, Interval.D1, Adjust.QFQ, 10)
    finally:
        await source.aclose()


@respx.mock
async def test_history_null_data_is_empty() -> None:
    """`data: null` is a known shape for delisted codes: missing, not broken."""
    respx.get(host="push2his.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    source = EastMoneySource()
    try:
        with pytest.raises(EmptyResponseError):
            await source.history(_STOCK, Interval.D1, Adjust.QFQ, 10)
    finally:
        await source.aclose()


@respx.mock
async def test_history_klines_not_a_list_is_a_schema_change() -> None:
    respx.get(host="push2his.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"data": {"klines": "nope"}})
    )
    source = EastMoneySource()
    try:
        with pytest.raises(SchemaChangedError):
            await source.history(_STOCK, Interval.D1, Adjust.QFQ, 10)
    finally:
        await source.aclose()


@respx.mock
async def test_index_history_skips_rows_that_are_not_strings() -> None:
    """The index path tolerates a row that is not a kline line."""
    respx.get(host="push2his.eastmoney.com").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "klines": [
                        {"unexpected": "object"},
                        "2026-11-06,1450.00,1453.00,1457.72,1436.00,42848",
                    ]
                }
            },
        )
    )
    source = EastMoneySource()
    try:
        bars = await source.history_by_secid("1.000906", dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    finally:
        await source.aclose()

    assert len(bars) == 1


@respx.mock
async def test_history_by_secid_http_error() -> None:
    respx.get(host="push2his.eastmoney.com").mock(return_value=httpx.Response(500))
    source = EastMoneySource()
    try:
        with pytest.raises(UpstreamError):
            await source.history_by_secid("1.000906", dt.date(2026, 1, 1), dt.date(2026, 2, 1))
    finally:
        await source.aclose()


@respx.mock
async def test_history_by_secid_null_data_returns_empty() -> None:
    respx.get(host="push2his.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    source = EastMoneySource()
    try:
        assert (
            await source.history_by_secid("1.000906", dt.date(2026, 1, 1), dt.date(2026, 2, 1))
            == []
        )
    finally:
        await source.aclose()


@respx.mock
async def test_history_by_secid_broken_payload() -> None:
    respx.get(host="push2his.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"data": {"klines": 1}})
    )
    source = EastMoneySource()
    try:
        with pytest.raises(SchemaChangedError):
            await source.history_by_secid("1.000906", dt.date(2026, 1, 1), dt.date(2026, 2, 1))
    finally:
        await source.aclose()
