"""Tests for the Tiantian Fund NAV adapter."""

from __future__ import annotations

import httpx
import pytest
import respx

from quotestack.errors import EmptyResponseError, SchemaChangedError
from quotestack.identity import resolve
from quotestack.models import AssetClass, Market
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
    assert points[-1].nav == "1.069"
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
    assert points[0].nav == "1.069"


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
