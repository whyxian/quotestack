"""Tests for market universe listings."""

from __future__ import annotations

import asyncio
import datetime as dt

import httpx
import pytest
import respx

from quotestack import AssetClass, Market
from quotestack.errors import UnsupportedError
from quotestack.sources import BinanceSource, EastMoneySource, TiantianSource


def _clist(rows: list[dict[str, object]], total: int) -> dict[str, object]:
    return {"data": {"total": total, "diff": rows}}


def _row(code: str, name: str, **extra: object) -> dict[str, object]:
    return {"f12": code, "f14": name, "f13": 0, "f26": 20200101, **extra}


async def _collect(source: object, *args: object, **kwargs: object) -> list[object]:
    out: list[object] = []
    async for batch in source.list_instruments(*args, **kwargs):  # type: ignore[attr-defined]
        out.extend(batch)
    return out


@respx.mock
async def test_eastmoney_maps_board_and_listing_date() -> None:
    """A row becomes a summary with a derived board and parsed date."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(
            200,
            json=_clist(
                [
                    _row("688981", "中芯国际", f13=1, f26=20200716, f100="半导体"),
                    _row("300750", "宁德时代", f13=0, f26=20180611),
                ],
                total=2,
            ),
        )
    )
    source = EastMoneySource()
    try:
        items = await _collect(source, AssetClass.STOCK, Market.CN, page_size=100)
    finally:
        await source.aclose()

    first = items[0]
    assert first.code == "688981"
    assert first.board == "科创板"
    assert first.listing_date == dt.date(2020, 7, 16)
    assert first.industry == "半导体"
    assert items[1].board == "创业板"


@respx.mock
async def test_eastmoney_clamps_oversized_pages() -> None:
    """The server caps rows per page, so a short page must not end the walk."""
    calls: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        page = request.url.params["pn"]
        calls.append(page)
        rows = [_row(f"60000{page}", f"股票{page}")]
        # Ask for 500 but only ever get one row back, with a total of 2.
        return httpx.Response(200, json=_clist(rows, total=2))

    respx.get(host="push2.eastmoney.com").mock(side_effect=responder)
    source = EastMoneySource()
    try:
        items = await _collect(source, AssetClass.STOCK, Market.CN, page_size=500)
    finally:
        await source.aclose()

    assert len(items) == 2
    assert calls == ["1", "2"]


@respx.mock
async def test_eastmoney_stops_on_short_page() -> None:
    """A page smaller than the requested size ends the walk."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(200, json=_clist([_row("600000", "浦发银行")], total=1))
    )
    source = EastMoneySource()
    try:
        items = await _collect(source, AssetClass.STOCK, Market.CN, page_size=100)
    finally:
        await source.aclose()

    assert len(items) == 1


@respx.mock
async def test_eastmoney_can_skip_zero_price() -> None:
    """Zero-priced rows are warrants, rights or suspended tickers."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(
            200,
            json=_clist(
                [
                    _row("AAPL", "苹果", f13=105, f2=342.37),
                    _row("XYZWW", "Some Wt", f13=105, f2="-"),
                    _row("ZEROW", "Zero", f13=105, f2=0),
                ],
                total=2,
            ),
        )
    )
    source = EastMoneySource()
    try:
        items = await _collect(
            source,
            AssetClass.STOCK,
            Market.US,
            page_size=100,
            skip_zero_price=True,
        )
    finally:
        await source.aclose()

    # Both "-" and 0 mean the row has no price.
    assert [item.code for item in items] == ["AAPL"]
    assert items[0].board == "NASDAQ"


async def test_eastmoney_rejects_unknown_market() -> None:
    """An unregistered pair is unsupported, not silently empty."""
    source = EastMoneySource()
    try:
        with pytest.raises(UnsupportedError):
            await _collect(source, AssetClass.CRYPTO, Market.CRYPTO)
    finally:
        await source.aclose()


_FUND_LIST = (
    'var r = [["000001","HXCZHH","华夏成长混合","混合型-灵活","HUAXIACHENGZHANGHUNHE"],'
    '["000003","ZHKZZZQA","中海可转债债券A","债券型-混合二级","ZHONGHAI"]];'
)


@respx.mock
async def test_tiantian_parses_fund_types() -> None:
    """The fund list carries the classification, which profile would need a call for."""
    respx.get(url__regex=r"https://fund\.eastmoney\.com/js/fundcode_search\.js").mock(
        return_value=httpx.Response(200, text=_FUND_LIST)
    )
    source = TiantianSource()
    try:
        items = await _collect(source)
    finally:
        await source.aclose()

    assert len(items) == 2
    assert items[0].fund_type == "混合型-灵活"
    assert items[1].fund_type == "债券型-混合二级"


@respx.mock
async def test_tiantian_batches_by_page_size() -> None:
    """The single payload is sliced into batches of the requested size."""
    respx.get(url__regex=r"https://fund\.eastmoney\.com/js/fundcode_search\.js").mock(
        return_value=httpx.Response(200, text=_FUND_LIST)
    )
    source = TiantianSource()
    try:
        sizes = []
        async for batch in source.list_instruments(page_size=1):
            sizes.append(len(batch))
    finally:
        await source.aclose()

    assert sizes == [1, 1]


_BINANCE = {
    "symbols": [
        {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING"},
        {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT", "status": "TRADING"},
        {"symbol": "DEADUSDT", "baseAsset": "DEAD", "quoteAsset": "USDT", "status": "BREAK"},
        {"symbol": "BTCBUSD", "baseAsset": "BTC", "quoteAsset": "BUSD", "status": "TRADING"},
    ]
}


@respx.mock
async def test_binance_keeps_only_trading_usdt_pairs() -> None:
    """Halted pairs and other quote assets are excluded by default."""
    respx.get(url__regex=r"https://data-api\.binance\.vision/api/v3/exchangeInfo").mock(
        return_value=httpx.Response(200, json=_BINANCE)
    )
    source = BinanceSource()
    try:
        items = await _collect(source)
    finally:
        await source.aclose()

    assert [item.code for item in items] == ["BTCUSDT", "ETHUSDT"]
    assert items[0].name == "BTC"
    assert items[0].currency == "USDT"


def test_listing_plan_covers_crypto() -> None:
    """Crypto listing is routed to Binance."""
    from quotestack.client import _LISTING_PLAN

    assert _LISTING_PLAN[(AssetClass.CRYPTO, Market.CRYPTO, None)] == ("binance",)


def test_blocking_iteration_is_not_required() -> None:
    """Listings are async generators, so they never block the loop."""
    source = TiantianSource()
    gen = source.list_instruments()
    assert hasattr(gen, "__aiter__")
    asyncio.run(_close(gen))


async def _close(gen: object) -> None:
    await gen.aclose()  # type: ignore[attr-defined]
