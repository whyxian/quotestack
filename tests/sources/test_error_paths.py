"""Error branches for the source adapters.

Every adapter has the same shape of guards: missing alias, wrong status, 514
throttle, unparseable payload, empty result. Happy-path tests never enter any
of them, so these do.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from quotestack.errors import (
    EmptyResponseError,
    NotFoundError,
    SchemaChangedError,
    UnsupportedError,
    UpstreamError,
)
from quotestack.identity import resolve
from quotestack.models import Adjust, AssetClass, Interval, Market
from quotestack.sources import (
    BinanceSource,
    EastMoneySource,
    FxSource,
    TencentSource,
    TiantianSource,
)

_FUND = resolve("166002", AssetClass.FUND, Market.CN)
_STOCK = resolve("600519", AssetClass.STOCK, Market.CN)
# A crypto instrument carries only a Binance alias, and it does not
# trigger the US search path either.
_NO_ALIAS = resolve("BTCUSDT", AssetClass.CRYPTO, Market.CRYPTO)

_NAV_URL = r"https://fund\.eastmoney\.com/pingzhongdata/.*\.js"
_PROFILE_URL = r"https://fundf10\.eastmoney\.com/jbgk_.*\.html"
_HOLDINGS_URL = r"https://fundf10\.eastmoney\.com/FundArchivesDatas\.aspx"
_LIST_URL = r"https://fund\.eastmoney\.com/js/fundcode_search\.js"
_BINANCE_URL = r"https://data-api\.binance\.vision/api/v3/exchangeInfo"


async def test_tiantian_rejects_a_fund_without_its_alias() -> None:
    """An instrument resolved for another source cannot be fetched here."""
    source = TiantianSource()
    try:
        with pytest.raises(UpstreamError):
            await source.nav(_NO_ALIAS)
        with pytest.raises(UpstreamError):
            await source.profile(_NO_ALIAS)
        with pytest.raises(UpstreamError):
            await source.holdings(_NO_ALIAS, 2026)
        with pytest.raises(UpstreamError):
            await source.allocation(_NO_ALIAS)
    finally:
        await source.aclose()


@respx.mock
async def test_tiantian_profile_404_is_not_found() -> None:
    """A missing page means no profile, not a broken source."""
    respx.get(url__regex=_PROFILE_URL).mock(return_value=httpx.Response(404))
    source = TiantianSource()
    try:
        with pytest.raises(NotFoundError):
            await source.profile(_FUND)
    finally:
        await source.aclose()


@respx.mock
async def test_tiantian_profile_server_error_is_upstream() -> None:
    respx.get(url__regex=_PROFILE_URL).mock(return_value=httpx.Response(500))
    source = TiantianSource()
    try:
        with pytest.raises(UpstreamError) as excinfo:
            await source.profile(_FUND)
    finally:
        await source.aclose()

    assert excinfo.value.context["status_code"] == 500


@respx.mock
async def test_tiantian_holdings_404_is_upstream() -> None:
    respx.get(url__regex=_HOLDINGS_URL).mock(return_value=httpx.Response(404))
    source = TiantianSource()
    try:
        with pytest.raises(UpstreamError):
            await source.holdings(_FUND, 2026)
    finally:
        await source.aclose()


@respx.mock
async def test_tiantian_holdings_without_envelope_is_a_schema_change() -> None:
    """A page that is not the expected envelope means the layout changed."""
    respx.get(url__regex=_HOLDINGS_URL).mock(
        return_value=httpx.Response(200, text="<html>404</html>")
    )
    source = TiantianSource()
    try:
        with pytest.raises(SchemaChangedError):
            await source.holdings(_FUND, 2026)
    finally:
        await source.aclose()


@respx.mock
async def test_tiantian_holdings_rows_without_weight_are_skipped() -> None:
    """A row whose ratio is not a percentage is noise, not a holding."""
    body = (
        'var apidata={ content:"<div>2026年3季度股票投资明细'
        "<table><tr><td>1</td><td>300308</td><td>中际旭创</td>"
        "<td>--</td><td>--</td><td>--</td></tr></table></div>"
        '",arryear:[2026],curyear:2026};'
    )
    respx.get(url__regex=_HOLDINGS_URL).mock(return_value=httpx.Response(200, text=body))
    source = TiantianSource()
    try:
        assert await source.holdings(_FUND, 2026) == []
    finally:
        await source.aclose()


@respx.mock
async def test_tiantian_nav_404_is_upstream() -> None:
    respx.get(url__regex=_NAV_URL).mock(return_value=httpx.Response(404))
    source = TiantianSource()
    try:
        with pytest.raises(UpstreamError):
            await source.nav(_FUND)
    finally:
        await source.aclose()


@respx.mock
async def test_tiantian_allocation_returns_none_without_the_variable() -> None:
    """A fund that publishes no allocation yields None, not an error."""
    respx.get(url__regex=_NAV_URL).mock(return_value=httpx.Response(200, text="var other = 1;"))
    source = TiantianSource()
    try:
        assert await source.allocation(_FUND) is None
    finally:
        await source.aclose()


@respx.mock
async def test_tiantian_list_rejects_a_broken_payload() -> None:
    respx.get(url__regex=_LIST_URL).mock(return_value=httpx.Response(200, text="not javascript"))
    source = TiantianSource()
    try:
        with pytest.raises(SchemaChangedError):
            async for _ in source.list_instruments():
                pass
    finally:
        await source.aclose()


async def test_eastmoney_rejects_an_instrument_without_its_alias() -> None:
    """A non-US instrument with no secid cannot be quoted."""
    source = EastMoneySource()
    try:
        with pytest.raises(UpstreamError):
            await source.quote([_NO_ALIAS])
    finally:
        await source.aclose()


@respx.mock
async def test_eastmoney_quote_server_error_is_upstream() -> None:
    respx.get(host="push2.eastmoney.com").mock(return_value=httpx.Response(503))
    source = EastMoneySource()
    try:
        with pytest.raises(UpstreamError):
            await source.quote([_STOCK])
    finally:
        await source.aclose()


@respx.mock
async def test_eastmoney_history_empty_payload_raises() -> None:
    """An empty kline list means the instrument has no data here."""
    respx.get(host="push2his.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"data": {"klines": []}})
    )
    source = EastMoneySource()
    try:
        with pytest.raises(EmptyResponseError):
            await source.history(_STOCK, Interval.D1, Adjust.QFQ, 10)
    finally:
        await source.aclose()


@respx.mock
async def test_eastmoney_listing_rejects_a_broken_payload() -> None:
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"data": {"diff": "not a list"}})
    )
    source = EastMoneySource()
    try:
        with pytest.raises(SchemaChangedError):
            async for _ in source.list_instruments(AssetClass.STOCK, Market.CN):
                pass
    finally:
        await source.aclose()


async def test_eastmoney_rejects_an_unknown_listing_market() -> None:
    source = EastMoneySource()
    try:
        with pytest.raises(UnsupportedError):
            async for _ in source.list_instruments(AssetClass.STOCK, Market.CRYPTO):
                pass
    finally:
        await source.aclose()


@respx.mock
async def test_eastmoney_index_search_failure_is_upstream() -> None:
    respx.get(url__startswith="https://searchapi.eastmoney.com").mock(
        return_value=httpx.Response(500)
    )
    source = EastMoneySource()
    try:
        with pytest.raises(UpstreamError):
            await source.resolve_index("表里没有的新指数")
    finally:
        await source.aclose()


@respx.mock
async def test_tencent_404_is_upstream() -> None:
    respx.get(url__startswith="https://qt.gtimg.cn/q=").mock(return_value=httpx.Response(404))
    source = TencentSource()
    try:
        with pytest.raises(UpstreamError):
            await source.quote([_STOCK])
    finally:
        await source.aclose()


async def test_tencent_rejects_an_instrument_without_its_alias() -> None:
    source = TencentSource()
    try:
        with pytest.raises(UpstreamError):
            await source.quote([_NO_ALIAS])
    finally:
        await source.aclose()


@respx.mock
async def test_binance_rejects_a_broken_payload() -> None:
    respx.get(url__regex=_BINANCE_URL).mock(return_value=httpx.Response(200, json={"nope": True}))
    source = BinanceSource()
    try:
        with pytest.raises(SchemaChangedError):
            async for _ in source.list_instruments():
                pass
    finally:
        await source.aclose()


@respx.mock
async def test_binance_http_error_is_upstream() -> None:
    respx.get(url__regex=_BINANCE_URL).mock(return_value=httpx.Response(451))
    source = BinanceSource()
    try:
        with pytest.raises(UpstreamError):
            async for _ in source.list_instruments():
                pass
    finally:
        await source.aclose()


@respx.mock
async def test_fx_http_error_is_upstream() -> None:
    respx.get(host="push2.eastmoney.com").mock(return_value=httpx.Response(500))
    source = FxSource()
    try:
        with pytest.raises(UpstreamError):
            await source.fx("USD", "CNY")
    finally:
        await source.aclose()


@respx.mock
async def test_fx_broken_payload_is_a_schema_change() -> None:
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"data": {"diff": "nope"}})
    )
    source = FxSource()
    try:
        with pytest.raises(SchemaChangedError):
            await source.fx("USD", "CNY")
    finally:
        await source.aclose()


@respx.mock
async def test_tiantian_profile_without_labels_yields_an_empty_profile() -> None:
    """A page with no label table produces an all-missing profile, not a crash."""
    respx.get(url__regex=_PROFILE_URL).mock(
        return_value=httpx.Response(200, text="<html><body>nothing</body></html>")
    )
    source = TiantianSource()
    try:
        profile = await source.profile(_FUND)
    finally:
        await source.aclose()

    assert profile.fund_type is None
    assert profile.partial is True


@respx.mock
async def test_tiantian_list_http_error_is_upstream() -> None:
    respx.get(url__regex=_LIST_URL).mock(return_value=httpx.Response(503))
    source = TiantianSource()
    try:
        with pytest.raises(UpstreamError):
            async for _ in source.list_instruments():
                pass
    finally:
        await source.aclose()


@respx.mock
async def test_tiantian_list_skips_malformed_rows() -> None:
    """A short or non-list row is dropped rather than failing the whole list."""
    body = 'var r = [["000001","HX","华夏成长","混合型"],["bad"],"not-a-row"];'
    respx.get(url__regex=_LIST_URL).mock(return_value=httpx.Response(200, text=body))
    source = TiantianSource()
    try:
        items = [item async for batch in source.list_instruments() for item in batch]
    finally:
        await source.aclose()

    assert [item.code for item in items] == ["000001"]


@respx.mock
async def test_tiantian_nav_skips_points_without_a_value() -> None:
    """A point missing its timestamp or NAV is noise."""
    body = (
        "var Data_netWorthTrend = ["
        '{"x":1762185600000,"y":1.0799},'
        '{"x":"bad","y":1.0},'
        '{"x":1762272000000,"y":null}'
        "];"
    )
    respx.get(url__regex=_NAV_URL).mock(return_value=httpx.Response(200, text=body))
    source = TiantianSource()
    try:
        points = await source.nav(_FUND)
    finally:
        await source.aclose()

    assert len(points) == 1


@respx.mock
async def test_tiantian_list_batches_skip_empty_chunks() -> None:
    """An empty payload yields no batch at all rather than an empty one."""
    respx.get(url__regex=_LIST_URL).mock(return_value=httpx.Response(200, text="var r = [];"))
    source = TiantianSource()
    try:
        batches = [batch async for batch in source.list_instruments()]
    finally:
        await source.aclose()

    assert batches == []


@respx.mock
async def test_eastmoney_quote_with_null_data_is_empty() -> None:
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    source = EastMoneySource()
    try:
        with pytest.raises(EmptyResponseError):
            await source.quote([_STOCK])
    finally:
        await source.aclose()
