"""Tests for the Binance adapter (quotes, batch quotes, klines and HTTP routes)."""

from __future__ import annotations

import datetime as dt
import json
from typing import cast

import httpx
import pytest
import respx
from tests.fixtures import load

from quotestack import MarketData
from quotestack.errors import (
    EmptyResponseError,
    RateLimitedError,
    SchemaChangedError,
    UnsupportedError,
    UpstreamError,
)
from quotestack.identity import resolve
from quotestack.models import Adjust, AssetClass, Capability, Interval, Market
from quotestack.server.app import create_app
from quotestack.sources import BinanceSource
from quotestack.sources.base import Historian, Quoter

_TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"
_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"

_BTC = resolve("BTC", AssetClass.CRYPTO, Market.CRYPTO)
_BTCUSDT = resolve("BTCUSDT", AssetClass.CRYPTO, Market.CRYPTO)
_ETH = resolve("ETH", AssetClass.CRYPTO, Market.CRYPTO)
_BAD = resolve("NOTACOIN", AssetClass.CRYPTO, Market.CRYPTO)
_STOCK = resolve("600519", AssetClass.STOCK, Market.CN)


def test_binance_implements_quoter_and_historian_protocols() -> None:
    """BinanceSource exposes LIST, QUOTE and HISTORY and satisfies both protocols."""
    source = BinanceSource()
    assert source.meta.capabilities == frozenset(
        {Capability.LIST, Capability.QUOTE, Capability.HISTORY}
    )
    assert isinstance(source, Quoter)
    assert isinstance(source, Historian)


@respx.mock
async def test_single_quote_parses_fixture_and_deduplicates_suffix() -> None:
    """Both BTC and BTCUSDT resolve to BTCUSDT and parse decimal fields cleanly."""
    route = respx.get(_TICKER_URL).mock(
        return_value=httpx.Response(200, content=load("binance/ticker_single.json"))
    )
    source = BinanceSource()
    try:
        q_short = (await source.quote([_BTC]))[0]
        q_pair = (await source.quote([_BTCUSDT]))[0]
    finally:
        await source.aclose()

    assert route.calls[0].request.url.params["symbol"] == "BTCUSDT"
    assert route.calls[1].request.url.params["symbol"] == "BTCUSDT"
    assert q_short.instrument_id == "CRYPTO:CRYPTO:BTC"
    assert q_pair.instrument_id == "CRYPTO:CRYPTO:BTCUSDT"
    assert q_short.price == "91100"
    assert q_short.change == "1250.5"
    assert q_short.change_pct == pytest.approx(1.392)
    assert q_short.currency == "USD"
    assert q_short.source == "binance"
    assert q_short.ts == dt.datetime(2024, 11, 12, 8, 0, tzinfo=dt.UTC)


@respx.mock
async def test_batch_quote_sends_compact_symbols_and_preserves_order() -> None:
    """Batch quotes request compact JSON symbols and return quotes in request order."""
    route = respx.get(_TICKER_URL).mock(
        return_value=httpx.Response(200, content=load("binance/ticker_batch.json"))
    )
    source = BinanceSource()
    try:
        quotes = await source.quote([_ETH, _BTC])
    finally:
        await source.aclose()

    assert route.calls[0].request.url.params["symbols"] == '["ETHUSDT","BTCUSDT"]'
    assert [q.instrument_id for q in quotes] == ["CRYPTO:CRYPTO:ETH", "CRYPTO:CRYPTO:BTC"]
    assert quotes[0].price == "3160"
    assert quotes[0].change == "-45.25"
    assert quotes[0].change_pct == pytest.approx(-1.412)
    assert quotes[1].price == "91100"


@respx.mock
async def test_batch_quote_deduplicates_same_binance_pair() -> None:
    """BTC and BTCUSDT map to one Binance symbol and still yield two Quotes."""
    route = respx.get(_TICKER_URL).mock(
        return_value=httpx.Response(200, content=load("binance/ticker_single.json"))
    )
    source = BinanceSource()
    try:
        quotes = await source.quote([_BTC, _BTCUSDT])
    finally:
        await source.aclose()

    assert route.call_count == 1
    assert route.calls[0].request.url.params["symbol"] == "BTCUSDT"
    assert [q.instrument_id for q in quotes] == ["CRYPTO:CRYPTO:BTC", "CRYPTO:CRYPTO:BTCUSDT"]


async def test_quote_empty_instruments_returns_empty_list() -> None:
    source = BinanceSource()
    try:
        assert await source.quote([]) == []
    finally:
        await source.aclose()


@respx.mock
async def test_batch_quote_tolerates_missing_row_in_response() -> None:
    """If Binance omits one symbol from the batch array, the rest still succeed."""
    single = json.loads(load("binance/ticker_single.json"))
    respx.get(_TICKER_URL).mock(return_value=httpx.Response(200, json=[single]))
    source = BinanceSource()
    try:
        quotes = await source.quote([_BTC, _ETH])
    finally:
        await source.aclose()

    assert [q.instrument_id for q in quotes] == ["CRYPTO:CRYPTO:BTC"]


@respx.mock
async def test_batch_quote_falls_back_individually_on_invalid_symbol_error() -> None:
    """Binance rejects the whole symbols=[...] batch on -1121; valid symbols still succeed."""
    btc_bytes = load("binance/ticker_single.json")
    invalid_bytes = load("binance/invalid_symbol.json")

    def responder(request: httpx.Request) -> httpx.Response:
        if "symbols" in request.url.params:
            return httpx.Response(400, content=invalid_bytes)
        if request.url.params.get("symbol") == "BTCUSDT":
            return httpx.Response(200, content=btc_bytes)
        return httpx.Response(400, content=invalid_bytes)

    respx.get(_TICKER_URL).mock(side_effect=responder)
    async with MarketData() as client:
        results = await client.quote_many(
            [
                ("BTC", AssetClass.CRYPTO, Market.CRYPTO),
                ("NOTACOIN", AssetClass.CRYPTO, Market.CRYPTO),
            ]
        )
        health = client.health()["sources"]["binance"]

    assert [r.ok for r in results] == [True, False]
    assert results[0].quote is not None
    assert results[0].quote.price == "91100"
    assert "UNAVAILABLE" in (results[1].error or "")
    assert health["state"] == "ok"


@respx.mock
async def test_single_quote_invalid_symbol_raises_empty_response() -> None:
    """HTTP 400 with Binance error code -1121 is EmptyResponseError, not retryable."""
    respx.get(_TICKER_URL).mock(
        return_value=httpx.Response(400, content=load("binance/invalid_symbol.json"))
    )
    source = BinanceSource()
    try:
        with pytest.raises(EmptyResponseError) as excinfo:
            await source.quote([_BAD])
    finally:
        await source.aclose()

    assert excinfo.value.context["missing"] == ["NOTACOINUSDT"]


@respx.mock
async def test_zero_price_row_is_treated_as_missing() -> None:
    """A zero lastPrice indicates no trading data and does not crash other batch items."""
    btc = json.loads(load("binance/ticker_single.json"))
    halted = {**btc, "symbol": "ETHUSDT", "lastPrice": "0.00000000"}

    respx.get(_TICKER_URL).mock(return_value=httpx.Response(200, json=[btc, halted]))
    source = BinanceSource()
    try:
        quotes = await source.quote([_BTC, _ETH])
    finally:
        await source.aclose()

    assert [q.instrument_id for q in quotes] == ["CRYPTO:CRYPTO:BTC"]

    respx.get(_TICKER_URL).mock(return_value=httpx.Response(200, json=halted))
    source2 = BinanceSource()
    try:
        with pytest.raises(EmptyResponseError):
            await source2.quote([_ETH])
    finally:
        await source2.aclose()


@respx.mock
async def test_quote_schema_changed_on_missing_or_malformed_fields() -> None:
    """Missing lastPrice, non-JSON, negative price, or bad batch shape raises SchemaChangedError."""
    bad_payloads = [
        httpx.Response(200, content=load("binance/bad_ticker_no_price.json")),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"symbol": "BTCUSDT", "lastPrice": "-1.0", "closeTime": 1}),
        httpx.Response(200, json={"symbol": "BTCUSDT", "lastPrice": "NaN", "closeTime": 1}),
        httpx.Response(200, json={"symbol": "BTCUSDT", "lastPrice": "10", "closeTime": "bad"}),
        httpx.Response(200, json=["not-a-dict"]),
    ]
    source = BinanceSource()
    try:
        for response in bad_payloads:
            respx.get(_TICKER_URL).mock(return_value=response)
            with pytest.raises(SchemaChangedError):
                await source.quote([_BTC])

        respx.get(_TICKER_URL).mock(return_value=httpx.Response(200, json={"not": "a list"}))
        with pytest.raises(SchemaChangedError):
            await source.quote([_BTC, _ETH])
    finally:
        await source.aclose()


@respx.mock
async def test_quote_upstream_and_rate_limit_errors() -> None:
    source = BinanceSource()
    try:
        respx.get(_TICKER_URL).mock(return_value=httpx.Response(429))
        with pytest.raises(RateLimitedError):
            await source.quote([_BTC])

        respx.get(_TICKER_URL).mock(return_value=httpx.Response(502))
        with pytest.raises(UpstreamError):
            await source.quote([_BTC])

        with pytest.raises(UpstreamError):
            await source.quote([_STOCK])
    finally:
        await source.aclose()


@respx.mock
async def test_history_daily_parses_fixture_in_ascending_order() -> None:
    """Daily klines parse OHLCV + quoteVolume as decimal strings with time=None."""
    rows = json.loads(load("binance/klines_1d.json"))
    # Reverse the fixture rows to confirm the adapter enforces ascending order.
    route = respx.get(_KLINES_URL).mock(return_value=httpx.Response(200, json=list(reversed(rows))))
    source = BinanceSource()
    try:
        bars = await source.history(_BTC, interval=Interval.D1, adjust=Adjust.NONE, limit=2000)
    finally:
        await source.aclose()

    params = route.calls[0].request.url.params
    assert params["symbol"] == "BTCUSDT"
    assert params["interval"] == "1d"
    assert params["limit"] == "1000"
    assert len(bars) == 2
    assert [bar.date for bar in bars] == [dt.date(2024, 11, 10), dt.date(2024, 11, 11)]
    assert bars[0].open == "88500"
    assert bars[0].high == "90200.5"
    assert bars[0].low == "87900.1"
    assert bars[0].close == "89849.5"
    assert bars[0].volume == "19876.54321"
    assert bars[0].amount == "1776543210.1234"
    assert bars[0].time is None


@respx.mock
async def test_history_intraday_maps_60m_to_1h_and_sets_time() -> None:
    """Interval.M60 maps to Binance's '1h' and populates HH:MM on each bar."""
    route = respx.get(_KLINES_URL).mock(
        return_value=httpx.Response(200, content=load("binance/klines_1h.json"))
    )
    source = BinanceSource()
    try:
        bars = await source.history(_BTCUSDT, interval=Interval.M60, adjust=Adjust.QFQ, limit=2)
    finally:
        await source.aclose()

    assert route.calls[0].request.url.params["interval"] == "1h"
    assert [bar.time for bar in bars] == ["00:00", "01:00"]
    assert bars[0].date == dt.date(2024, 11, 12)


async def test_history_rejects_unsupported_interval() -> None:
    source = BinanceSource()
    try:
        with pytest.raises(UnsupportedError):
            await source.history(_BTC, interval=cast("Interval", "4h"))
    finally:
        await source.aclose()


@respx.mock
async def test_history_empty_and_invalid_symbol_raise_empty_response() -> None:
    source = BinanceSource()
    try:
        respx.get(_KLINES_URL).mock(return_value=httpx.Response(200, json=[]))
        with pytest.raises(EmptyResponseError):
            await source.history(_BTC)

        respx.get(_KLINES_URL).mock(
            return_value=httpx.Response(400, content=load("binance/invalid_symbol.json"))
        )
        with pytest.raises(EmptyResponseError):
            await source.history(_BAD)
    finally:
        await source.aclose()


@respx.mock
async def test_history_schema_changed_guards() -> None:
    """Malformed kline payloads or OHLC violations raise SchemaChangedError."""
    bad_payloads = [
        httpx.Response(200, content=load("binance/bad_klines_shape.json")),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[[1731196800000, "1", "2"]]),
        # high < low violates OHLC
        httpx.Response(
            200,
            json=[[1731196800000, "10", "5", "12", "8", "100", 1731283199999, "800"]],
        ),
        httpx.Response(
            200,
            json=[[1731196800000, "oops", "12", "5", "8", "100", 1731283199999, "800"]],
        ),
    ]
    source = BinanceSource()
    try:
        for response in bad_payloads:
            respx.get(_KLINES_URL).mock(return_value=response)
            with pytest.raises(SchemaChangedError):
                await source.history(_BTC)
    finally:
        await source.aclose()


@respx.mock
async def test_http_endpoints_serve_crypto_quote_batch_and_history() -> None:
    """Exercise /v1/quote, /v1/quotes/batch and /v1/history end-to-end via FastAPI."""
    btc_bytes = load("binance/ticker_single.json")
    batch_bytes = load("binance/ticker_batch.json")
    klines_1d_bytes = load("binance/klines_1d.json")
    klines_1h_bytes = load("binance/klines_1h.json")
    invalid_bytes = load("binance/invalid_symbol.json")

    def ticker_responder(request: httpx.Request) -> httpx.Response:
        if "symbols" in request.url.params:
            requested = json.loads(request.url.params["symbols"])
            if "NOTACOINUSDT" in requested:
                return httpx.Response(400, content=invalid_bytes)
            return httpx.Response(200, content=batch_bytes)
        symbol = request.url.params.get("symbol")
        if symbol == "BTCUSDT":
            return httpx.Response(200, content=btc_bytes)
        if symbol == "ETHUSDT":
            eth = json.loads(batch_bytes)[1]
            return httpx.Response(200, json=eth)
        return httpx.Response(400, content=invalid_bytes)

    def klines_responder(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("interval") == "1h":
            return httpx.Response(200, content=klines_1h_bytes)
        return httpx.Response(200, content=klines_1d_bytes)

    respx.get(_TICKER_URL).mock(side_effect=ticker_responder)
    respx.get(_KLINES_URL).mock(side_effect=klines_responder)

    async with MarketData() as client:
        app = create_app(client=client)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as api:
            r_quote = await api.get(
                "/v1/quote",
                params={"code": "BTC", "asset_class": "CRYPTO", "market": "CRYPTO"},
            )
            r_pair = await api.get(
                "/v1/quote",
                params={"code": "BTCUSDT", "asset_class": "CRYPTO", "market": "CRYPTO"},
            )
            r_batch = await api.post(
                "/v1/quotes/batch",
                json={
                    "items": [
                        {"code": "BTC", "asset_class": "CRYPTO", "market": "CRYPTO"},
                        {"code": "ETHUSDT", "asset_class": "CRYPTO", "market": "CRYPTO"},
                        {"code": "NOTACOIN", "asset_class": "CRYPTO", "market": "CRYPTO"},
                    ]
                },
            )
            r_hist_d1 = await api.get(
                "/v1/history",
                params={
                    "code": "BTC",
                    "asset_class": "CRYPTO",
                    "market": "CRYPTO",
                    "interval": "1d",
                    "limit": 2,
                },
            )
            r_hist_1h = await api.get(
                "/v1/history",
                params={
                    "code": "BTCUSDT",
                    "asset_class": "CRYPTO",
                    "market": "CRYPTO",
                    "interval": "60m",
                    "limit": 2,
                },
            )

    assert r_quote.status_code == 200
    assert r_quote.json()["error"] is None
    assert r_quote.json()["data"]["price"] == "91100"
    assert r_quote.json()["data"]["source"] == "binance"

    assert r_pair.status_code == 200
    assert r_pair.json()["data"]["instrument_id"] == "CRYPTO:CRYPTO:BTCUSDT"
    assert r_pair.json()["data"]["price"] == "91100"

    assert r_batch.status_code == 200
    batch_results = r_batch.json()["data"]["results"]
    assert [item["ok"] for item in batch_results] == [True, True, False]
    assert batch_results[0]["quote"]["price"] == "91100"
    assert batch_results[1]["quote"]["price"] == "3160"
    assert "UNAVAILABLE" in batch_results[2]["error"]

    assert r_hist_d1.status_code == 200
    d1_data = r_hist_d1.json()["data"]
    assert d1_data["source"] == "binance"
    assert d1_data["interval"] == "1d"
    assert [bar["date"] for bar in d1_data["bars"]] == ["2024-11-10", "2024-11-11"]

    assert r_hist_1h.status_code == 200
    h1_data = r_hist_1h.json()["data"]
    assert h1_data["source"] == "binance"
    assert [bar["time"] for bar in h1_data["bars"]] == ["00:00", "01:00"]
