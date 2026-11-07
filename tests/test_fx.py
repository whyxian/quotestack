"""Tests for currency rates."""

from __future__ import annotations

import httpx
import pytest
import respx

from quotestack.errors import UnsupportedError
from quotestack.sources import FxSource


def _fx_payload(**values: int) -> dict[str, object]:
    names = {
        "EURUSD": "EURUSD",
        "USDJPY": "USDJPY",
        "GBPUSD": "GBPUSD",
        "USDCNH": "USDCNH",
        "HKDCNH": "HKDCNYC",
        "EURCNH": "EURCNYC",
    }
    return {
        "data": {
            "diff": [{"f1": 4, "f2": value, "f12": names[key]} for key, value in values.items()]
        }
    }


@respx.mock
async def test_usd_to_cny_uses_the_quoted_pair() -> None:
    """USD/CNY comes straight from USDCNH."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(200, json=_fx_payload(USDCNH=66738))
    )
    source = FxSource()
    try:
        rate = await source.fx("USD", "CNY")
    finally:
        await source.aclose()

    assert rate.rate == "6.6738"
    assert rate.quote == "CNY"


@respx.mock
async def test_inverse_pair_is_reciprocal() -> None:
    """CNY/USD inverts the quoted pair."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(200, json=_fx_payload(USDCNH=66738))
    )
    source = FxSource()
    try:
        rate = await source.fx("CNY", "USD")
    finally:
        await source.aclose()

    assert float(rate.rate) == pytest.approx(1 / 6.6738, abs=1e-6)


@respx.mock
async def test_cross_rate_through_usd() -> None:
    """USD/HKD is derived from USD/CNH and HKD/CNH."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(200, json=_fx_payload(USDCNH=66738, HKDCNH=8571, EURUSD=10800))
    )
    source = FxSource()
    try:
        rate = await source.fx("USD", "HKD")
    finally:
        await source.aclose()

    # 6.6738 / 0.8571
    assert float(rate.rate) == pytest.approx(7.7864, abs=1e-3)


@respx.mock
async def test_same_currency_needs_no_request() -> None:
    """Converting a currency to itself is a no-op; no HTTP call is made."""
    source = FxSource()
    try:
        rate = await source.fx("USD", "USD")
    finally:
        await source.aclose()

    assert rate.rate == "1"
    assert rate.derived is False


@respx.mock
async def test_unknown_currency_is_unsupported() -> None:
    """A currency with no quoted pair raises instead of guessing."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(200, json=_fx_payload(USDCNH=66738))
    )
    source = FxSource()
    try:
        with pytest.raises(UnsupportedError) as excinfo:
            await source.fx("USD", "XYZ")
    finally:
        await source.aclose()

    assert excinfo.value.context["quote"] == "XYZ"
