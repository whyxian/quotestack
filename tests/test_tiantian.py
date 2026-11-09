"""Tests for the Tiantian Fund NAV adapter."""

from __future__ import annotations

import httpx
import pytest
import respx

from quotestack.errors import EmptyResponseError, RateLimitedError, SchemaChangedError
from quotestack.identity import resolve
from quotestack.models import AssetClass, FundClass, Market
from quotestack.sources import TiantianSource

_FUND = resolve("022430", AssetClass.FUND, Market.CN)

_FIXTURE = (
    'var fS_name = "华夏中证A500ETF联接A";'
    "var Data_netWorthTrend = ["
    '{"x":1762185600000,"y":1.0799,"equityReturn":0.5},'
    '{"x":1762272000000,"y":1.069,"equityReturn":-1.0}'
    "];"
    "var Data_assetAllocation = {};"
)


@respx.mock
async def test_nav_parses_js_globals() -> None:
    """NAV points come from a JavaScript variable, not JSON."""
    respx.get(url__regex=r"https://fund\.eastmoney\.com/pingzhongdata/.*\.js").mock(
        return_value=httpx.Response(200, text=_FIXTURE)
    )
    source = TiantianSource()
    try:
        points = await source.nav(_FUND)
    finally:
        await source.aclose()

    assert len(points) == 2
    assert points[0].nav == "1.0799"
    assert points[-1].nav == "1.0690"
    assert points[0].date < points[-1].date


@respx.mock
async def test_nav_respects_limit() -> None:
    """Only the newest N points are returned."""
    respx.get(url__regex=r"https://fund\.eastmoney\.com/pingzhongdata/.*\.js").mock(
        return_value=httpx.Response(200, text=_FIXTURE)
    )
    source = TiantianSource()
    try:
        points = await source.nav(_FUND, limit=1)
    finally:
        await source.aclose()

    assert len(points) == 1
    assert points[0].nav == "1.0690"


@respx.mock
async def test_missing_variable_is_a_schema_change() -> None:
    """A page without Data_netWorthTrend means the layout changed."""
    respx.get(url__regex=r"https://fund\.eastmoney\.com/pingzhongdata/.*\.js").mock(
        return_value=httpx.Response(200, text="var somethingElse = 1;")
    )
    source = TiantianSource()
    try:
        with pytest.raises(SchemaChangedError) as excinfo:
            await source.nav(_FUND)
    finally:
        await source.aclose()

    assert "hint" in excinfo.value.context


@respx.mock
async def test_empty_series_raises() -> None:
    """An empty NAV array is missing data, not a schema change."""
    respx.get(url__regex=r"https://fund\.eastmoney\.com/pingzhongdata/.*\.js").mock(
        return_value=httpx.Response(200, text="var Data_netWorthTrend = [];")
    )
    source = TiantianSource()
    try:
        with pytest.raises(EmptyResponseError):
            await source.nav(_FUND)
    finally:
        await source.aclose()


_HOLDINGS_HTML = (
    'var apidata={ content:"'
    "<div><h4 class='t'><label class='left'>某基金&nbsp;&nbsp;2026年3季度股票投资明细</label></h4>"
    "<table><tbody>"
    "<tr><th>序号</th><th>股票代码</th><th>股票名称</th><th>占净值比例</th></tr>"
    # Nine cells, as the newest quarter reports them.
    "<tr><td>1</td><td>300308</td><td>中际旭创</td><td></td><td></td>"
    "<td>变动详情</td><td>4.66%</td><td>66.35</td><td>53,641.53</td></tr>"
    "<tr><td>2</td><td>600519</td><td>贵州茅台</td><td></td><td></td>"
    "<td>变动详情</td><td>3.10%</td><td>12.00</td><td>9,000.00</td></tr>"
    "</tbody></table>"
    "<h4 class='t'><label class='left'>某基金&nbsp;&nbsp;2026年2季度股票投资明细</label></h4>"
    "<table><tbody>"
    # Seven cells: older quarters omit the price columns.
    "<tr><td>1</td><td>300308</td><td>中际旭创</td><td>股吧行情</td>"
    "<td>8.45%</td><td>83.61</td><td>106,184.70</td></tr>"
    '</tbody></table></div>",arryear:[2026],curyear:2026};'
)


@respx.mock
async def test_holdings_parses_quarters_and_variable_cells() -> None:
    """Cell counts differ per quarter, so columns are read from the end."""
    respx.get(url__regex=r"https://fundf10\.eastmoney\.com/FundArchivesDatas\.aspx").mock(
        return_value=httpx.Response(200, text=_HOLDINGS_HTML)
    )
    source = TiantianSource()
    try:
        quarters = await source.holdings(_FUND, 2026)
    finally:
        await source.aclose()

    assert [q.quarter for q in quarters] == ["2026Q3", "2026Q2"]
    assert quarters[0].as_of.isoformat() == "2026-09-30"
    assert [h.code for h in quarters[0].holdings] == ["300308", "600519"]
    assert quarters[0].holdings[0].weight == pytest.approx(4.66)
    # The second quarter's row has an extra cell before the ratio.
    assert quarters[1].holdings[0].weight == pytest.approx(8.45)


@respx.mock
async def test_holdings_sends_referer() -> None:
    """Without a Referer the endpoint answers 404."""
    route = respx.get(url__regex=r"https://fundf10\.eastmoney\.com/FundArchivesDatas\.aspx").mock(
        return_value=httpx.Response(200, text=_HOLDINGS_HTML)
    )
    source = TiantianSource()
    try:
        await source.holdings(_FUND, 2026)
    finally:
        await source.aclose()

    assert route.calls[0].request.headers["Referer"].endswith("ccmx_022430.html")


@respx.mock
async def test_holdings_empty_envelope_is_not_a_schema_change() -> None:
    """Money market funds return a valid envelope with no quarters."""
    respx.get(url__regex=r"https://fundf10\.eastmoney\.com/FundArchivesDatas\.aspx").mock(
        return_value=httpx.Response(200, text='var apidata={ content:"",arryear:[],curyear:2026};')
    )
    source = TiantianSource()
    try:
        assert await source.holdings(_FUND, 2026) == []
    finally:
        await source.aclose()


_PROFILE_HTML = """
<table><tbody>
<tr><th>基金全称</th><td>中欧新蓝筹灵活配置混合型证券投资基金</td><th>基金简称</th><td>中欧新蓝筹混合A</td></tr>
<tr><th>基金代码</th><td>166002（前端）<th>基金类型</th><td>混合型-偏股</td></tr>
<tr><th>成立日期/规模</th><td>2008年07月25日 / 3.252亿份</td><th>净资产规模</th><td>80.39亿元（截止至：2026年09月30日）</td></tr>
<tr><th>基金管理人</th><td>中欧基金</td><th>基金托管人</th><td>建设银行</td></tr>
<tr><th>基金经理人</th><td>周蔚文、冯炉丹</td><th>业绩比较基准</th><td>中证800指数收益率*70%+上证国债指数收益率*25%+一年期定期存款基准利率*5%</td></tr>
<tr><th>跟踪标的</th><td>该基金无跟踪标的</td><td></td><td></td></tr>
</tbody></table>
"""


@respx.mock
async def test_profile_parses_the_label_table() -> None:
    """The page omits a closing tag, which must not swallow the next pair."""
    respx.get(url__regex=r"https://fundf10\.eastmoney\.com/jbgk_.*\.html").mock(
        return_value=httpx.Response(200, text=_PROFILE_HTML)
    )
    source = TiantianSource()
    try:
        profile = await source.profile(_FUND)
    finally:
        await source.aclose()

    assert profile.fund_type == "混合型-偏股"
    assert profile.fund_class is FundClass.EQUITY
    assert profile.manager == "周蔚文、冯炉丹"
    assert profile.custodian == "建设银行"
    assert profile.scale == "80.39亿元"
    assert profile.as_of is not None
    assert profile.as_of.isoformat() == "2026-09-30"
    assert profile.inception_date is not None
    assert profile.inception_date.isoformat() == "2008-07-25"
    assert profile.tracking_index is None
    assert profile.benchmark is not None
    assert profile.benchmark.coverage == pytest.approx(1.0)
    assert profile.missing == ()


@respx.mock
async def test_profile_throttle_is_rate_limited_not_an_outage() -> None:
    """514 is Eastmoney's anti-scraping status; it must not cool the source."""
    respx.get(url__regex=r"https://fundf10\.eastmoney\.com/jbgk_.*\.html").mock(
        return_value=httpx.Response(514)
    )
    source = TiantianSource()
    try:
        with pytest.raises(RateLimitedError) as excinfo:
            await source.profile(_FUND)
    finally:
        await source.aclose()

    assert excinfo.value.retryable is False


def test_profile_counts_a_missing_company_as_partial() -> None:
    """`company` was omitted from the missing list, so partial was false."""
    from quotestack.sources.tiantian import TiantianSource

    source = TiantianSource()
    try:
        profile = source._parse_profile("<html></html>")
    finally:
        import asyncio

        asyncio.run(source.aclose())

    assert "company" in profile.missing
    assert profile.partial is True


def test_nav_keeps_four_decimals() -> None:
    """A JSON number loses the trailing zero the fund publishes."""
    from quotestack.sources.tiantian import _format_nav

    assert _format_nav(1.069) == "1.0690"
    assert _format_nav(1.0) == "1.0000"
    assert _format_nav(3.4567) == "3.4567"
