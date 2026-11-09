"""Transport failures must not escape as httpx exceptions.

They used to: a refused connection surfaced as httpx.ConnectError, so callers
could not catch MarketDataError, the HTTP layer answered 500 instead of 502,
and the scheduled live probe crashed rather than reporting that it could not
reach the source.
"""

from __future__ import annotations

import httpx
import pytest

from quotestack import AssetClass, Market, MarketData
from quotestack.errors import MarketDataError, TimeoutError, UpstreamError
from quotestack.sources.transport import send


async def test_refused_connection_becomes_upstream_error() -> None:
    transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused", request=request))
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(UpstreamError) as excinfo:
            await send(client, "GET", "https://example.test/x", source="eastmoney")

    assert excinfo.value.context["source"] == "eastmoney"
    assert isinstance(excinfo.value, MarketDataError)


async def test_timeout_becomes_timeout_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(TimeoutError):
            await send(client, "GET", "https://example.test/x", source="tencent")


async def test_status_code_is_left_to_the_caller() -> None:
    """A 500 is a valid response; only the adapter knows what it means."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ) as client:
        response = await send(client, "GET", "https://example.test/x", source="eastmoney")

    assert response.status_code == 500


async def test_client_surfaces_library_errors_not_httpx() -> None:
    """The whole point: a caller catching MarketDataError is enough."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with MarketData(
        sources={
            "eastmoney": _Unreachable(httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
        },
        source_priority={"QUOTE": ["eastmoney"]},
    ) as client:
        with pytest.raises(MarketDataError):
            await client.quote("600519", AssetClass.STOCK, Market.CN)


class _Unreachable:
    """A source whose every request fails at the transport layer."""

    from quotestack.models import Capability
    from quotestack.sources.base import SourceMeta

    meta = SourceMeta(
        name="eastmoney",
        capabilities=frozenset({Capability.QUOTE}),
        markets=frozenset({(AssetClass.STOCK, Market.CN)}),
    )

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def quote(self, instruments: object) -> None:
        from quotestack.sources.transport import send

        await send(self._client, "GET", "https://example.test/q", source="eastmoney")

    async def aclose(self) -> None:
        await self._client.aclose()
