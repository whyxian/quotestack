"""Tests for the Tencent adapter using mocked GBK payloads."""

from __future__ import annotations

import httpx
import pytest
import respx

from quotestack.errors import EmptyResponseError, SchemaChangedError
from quotestack.identity import resolve
from quotestack.models import AssetClass, Market
from quotestack.sources import TencentSource

_STOCK = resolve("600519", AssetClass.STOCK, Market.CN)
_US = resolve("AAPL", AssetClass.STOCK, Market.US)


def _row(code: str, **over: str) -> str:
    """Build a 40-field A-share style row."""
    fields = ["1", "贵州茅台", code, "1453.00", "1452.00", "1450.00", "42848"]
    fields += ["0"] * 23
    fields += ["20261106161458", "1.00", "0.07", "1457.72", "1436.00", "0"]
    fields += ["0"] * 4
    for index, value in over.items():
        fields[int(index[1:])] = value
    return "v_" + code + '="' + "~".join(fields) + '";'


# Captured verbatim from qt.gtimg.cn on 2026-11-07 (decoded to str for readability).
_REAL_CN_ROW = 'v_sh600519="1~贵州茅台~600519~1453.00~1452.00~1450.00~42848~23139~19709~1452.00~2~1451.60~1~1451.33~1~1451.01~1~1451.00~5~1453.00~2~1453.01~2~1453.06~1~1453.07~8~1453.19~1~~20261106161458~1.00~0.07~1457.72~1436.00~1453.00/42848/6199528289~42848~619953~0.34~22.11~~1457.72~1436.00~1.50~18163.69~18163.69~6.70~1597.20~1306.80~0.65~-4~1446.87~21.13~22.06~~~-0.02~619952.8289~232.4800~16~   A~GP-A~7.70~4.38~3.58~30.29~26.74~1539.98~1151.01~8.84~15.04~11.04~1250081601~1250081601~-16.67~-2.94~1250081601~~~5.05~0.21~~CNY~0~___D__F__N~1450.04~3~";'
_REAL_US_ROW = 'v_usAAPL="200~苹果~AAPL.OQ~342.37~344.17~338.73~44703806~0~0~342.65~480~0~0~0~0~0~0~0~0~342.82~80~0~0~0~0~0~0~0~0~~2026-11-06 16:00:01~-1.80~-0.52~345.79~338.30~USD~44703806~15326963640~0.31~38.13~~38.13~~2.18~49722.77471~49753.83151~Apple Inc.~8.98~355.38~242.76~400~44.39~0.31~49753.83151~26.28~-0.66~GP~142.26~34.61~-1.54~1.70~12.16~14532182000~14523110878~0.62~38.13~1.07~342.86~~~~~";'


def _payload(*rows: str) -> bytes:
    return "\n".join(rows).encode("gbk")


@respx.mock
async def test_quote_parses_gbk_payload() -> None:
    """The response is GBK, not UTF-8."""
    respx.get(url__startswith="https://qt.gtimg.cn/q=").mock(
        return_value=httpx.Response(200, content=_payload(_REAL_CN_ROW))
    )
    source = TencentSource()
    try:
        quotes = await source.quote([_STOCK])
    finally:
        await source.aclose()

    assert quotes[0].price == "1453.00"
    assert quotes[0].currency == "CNY"
    assert quotes[0].change_pct == pytest.approx(0.07)
    assert quotes[0].ts.tzinfo is not None


@respx.mock
async def test_quote_uses_us_currency_and_timezone() -> None:
    """US rows carry an explicit currency and are stamped in New York time."""
    respx.get(url__startswith="https://qt.gtimg.cn/q=").mock(
        return_value=httpx.Response(200, content=_payload(_REAL_US_ROW))
    )
    source = TencentSource()
    try:
        quotes = await source.quote([_US])
    finally:
        await source.aclose()

    quote = quotes[0]
    assert quote.currency == "USD"
    assert quote.price == "342.37"
    assert quote.change_pct == pytest.approx(-0.52)
    assert quote.ts.utcoffset() is not None
    assert quote.ts.hour == 16


@respx.mock
async def test_quote_reports_missing_symbol() -> None:
    """A symbol absent from the payload is reported, not silently dropped."""
    respx.get(url__startswith="https://qt.gtimg.cn/q=").mock(
        return_value=httpx.Response(200, content=b"")
    )
    source = TencentSource()
    try:
        with pytest.raises(EmptyResponseError) as excinfo:
            await source.quote([_STOCK])
    finally:
        await source.aclose()

    assert excinfo.value.context["missing"] == ["sh600519"]


@respx.mock
async def test_quote_rejects_short_row() -> None:
    """A row with too few fields means the layout changed."""
    respx.get(url__startswith="https://qt.gtimg.cn/q=").mock(
        return_value=httpx.Response(200, content=_payload('v_sh600519="1~贵州茅台";'))
    )
    source = TencentSource()
    try:
        with pytest.raises(SchemaChangedError):
            await source.quote([_STOCK])
    finally:
        await source.aclose()


def test_a_row_with_no_trades_is_not_a_price() -> None:
    """Tencent answers for codes it has no data for, with a placeholder row.

    `sz166002` is an open-end fund with no listing; the source returned
    price=1.000, change=0.000, volume=0, amount=0, and the library reported that
    as a real quote - a fabricated price the caller could not tell from a real
    one. A real ETF has volume in the tens of millions.
    """
    from quotestack.errors import EmptyResponseError
    from quotestack.identity import resolve
    from quotestack.sources.tencent import TencentSource

    instrument = resolve("166002", AssetClass.FUND, Market.CN)
    fields = [
        "51",
        "中欧蓝筹",
        "166002",
        "1.000",
        "1.000",
        "0.000",
        "0",
        "0",
        "0",
        "0.000",
        "0",
        "0.000",
        "0",
        "0.000",
        "0",
        "0.000",
        "0",
        "0.000",
        "0",
        "0.000",
        "0",
        "0.000",
        "0",
        "0.000",
        "0",
        "0.000",
        "0",
        "0.000",
        "0",
        "",
        "20261111090000",
        "0.000",
        "0.00",
        "0.000",
        "0.000",
        "1.000/0/0",
        "0",
        "0",
        "",
        "",
        "",
        "0.000",
        "0.000",
        "0.00",
        "",
        "",
        "0.00",
        "-1",
        "-1",
        "0.00",
        "0",
        "1.000",
        "",
        "",
        "",
        "",
        "",
        "0.0000",
        "0.0000",
        "0",
        "",
    ]

    with pytest.raises(EmptyResponseError):
        TencentSource._to_quote(instrument, fields)


def test_a_row_with_volume_is_a_price() -> None:
    from quotestack.identity import resolve
    from quotestack.sources.tencent import TencentSource

    instrument = resolve("159915", AssetClass.FUND, Market.CN)
    fields = [
        "51",
        "创业板ETF",
        "159915",
        "2.590",
        "2.509",
        "2.500",
        "44596299",
        "23789364",
        "20806935",
        "2.590",
        "43875",
        "2.589",
        "115098",
        "2.588",
        "13024",
        "2.587",
        "22381",
        "2.586",
        "20358",
        "2.591",
        "19146",
        "2.592",
        "19467",
        "2.593",
        "12862",
        "2.594",
        "12861",
        "2.595",
        "44324",
        "",
        "20261111161436",
        "0.081",
        "3.23",
        "2.597",
        "2.500",
        "2.590/44596299/11386149158",
        "44596299",
        "1138615",
        "9.80",
        "",
        "",
        "",
    ]

    quote = TencentSource._to_quote(instrument, fields)

    assert quote.price == "2.590"
    assert quote.change_pct == 3.23
