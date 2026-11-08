"""Golden tests driven by recorded payloads.

These assert that the parsers still understand bytes captured from the real
endpoints. A fixture changing shape should break a test here, not production.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from tests.fixtures import load

from quotestack.errors import SchemaChangedError
from quotestack.identity import resolve
from quotestack.models import AssetClass, Market
from quotestack.sources import EastMoneySource, TiantianSource

_STOCK = resolve("600519", AssetClass.STOCK, Market.CN)
_FUND = resolve("166002", AssetClass.FUND, Market.CN)


def test_loader_returns_raw_bytes() -> None:
    """Bytes, not text: an adapter must do its own decoding."""
    payload = load("bad/eastmoney_quote_no_envelope.json")

    assert isinstance(payload, bytes)
    assert payload.startswith(b"{")


def test_loader_reports_a_missing_fixture() -> None:
    """A typo in a fixture name is a test bug and should be loud."""
    with pytest.raises(FileNotFoundError):
        load("eastmoney/does_not_exist.json")


@respx.mock
async def test_eastmoney_rejects_a_payload_without_data() -> None:
    """The recorded bad sample must trip the structural assertion."""
    respx.get(host="push2.eastmoney.com").mock(
        return_value=httpx.Response(200, content=load("bad/eastmoney_quote_no_envelope.json"))
    )
    source = EastMoneySource()
    try:
        with pytest.raises(SchemaChangedError) as excinfo:
            await source.quote([_STOCK])
    finally:
        await source.aclose()

    assert "data" in excinfo.value.message


@respx.mock
async def test_tiantian_treats_an_empty_envelope_as_no_holdings() -> None:
    """A valid envelope with no quarters is an empty answer, not a break."""
    respx.get(url__regex=r"https://fundf10\.eastmoney\.com/FundArchivesDatas\.aspx").mock(
        return_value=httpx.Response(200, content=load("bad/tiantian_holdings_no_quarters.html"))
    )
    source = TiantianSource()
    try:
        assert await source.holdings(_FUND, 2026) == []
    finally:
        await source.aclose()
