"""Eastmoney adapter: shared state, lifecycle and secid resolution."""

from __future__ import annotations

import httpx

from quotestack.errors import (
    AmbiguousError,
    EmptyResponseError,
    SchemaChangedError,
    UpstreamError,
)
from quotestack.models import AssetClass, Capability, Instrument, Market
from quotestack.sources.base import SourceMeta

__all__ = ["SEARCH_TOKEN", "SEARCH_URL", "SOURCE_META", "CoreMixin"]

SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
SEARCH_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"

SOURCE_META = SourceMeta(
    name="eastmoney",
    capabilities=frozenset({Capability.QUOTE, Capability.HISTORY}),
    markets=frozenset(
        {
            (AssetClass.STOCK, Market.CN),
            (AssetClass.FUND, Market.CN),
            (AssetClass.STOCK, Market.US),
        }
    ),
    timeout=5.0,
)


class CoreMixin:
    """Owns the HTTP client, its lifetime and secid resolution."""

    meta = SOURCE_META

    _client: httpx.AsyncClient
    _owns_client: bool
    _secids: dict[str, str]

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        proxy: str | None = None,
    ) -> None:
        """Create the adapter.

        Args:
            client: Optional shared HTTP client. When omitted the adapter owns
                one and closes it in :meth:`aclose`.
            proxy: Outbound proxy applied when the adapter owns the client.
        """
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=self.meta.timeout,
            proxy=proxy,
        )
        self._secids: dict[str, str] = {}

    async def aclose(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def _secid_for(self, instrument: Instrument) -> str:
        """Return the Eastmoney secid, looking US tickers up when needed.

        Mainland codes carry their secid in ``aliases``. US tickers need an
        exchange suffix (``105.AAPL`` for NASDAQ, ``107.SPY`` for NYSE Arca)
        that only the search endpoint can supply, so it is resolved lazily and
        memoised for the lifetime of the adapter.
        """
        secid = instrument.aliases.get("eastmoney")
        if secid is not None:
            return secid

        cached = self._secids.get(instrument.code)
        if cached is not None:
            return cached

        if instrument.market is not Market.US:
            raise UpstreamError(
                "instrument has no eastmoney alias",
                source=self.meta.name,
                instrument=instrument.id,
            )

        resolved = await self._search_us(instrument)
        self._secids[instrument.code] = resolved
        return resolved

    async def _search_us(self, instrument: Instrument) -> str:
        """Resolve a US ticker to a secid via the search endpoint."""
        response = await self._client.get(
            SEARCH_URL,
            params={
                "input": instrument.code,
                "type": "14",
                "token": SEARCH_TOKEN,
                "count": "10",
            },
        )
        if response.status_code >= 400:
            raise UpstreamError(
                f"eastmoney search responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
            )

        payload = response.json()
        table = payload.get("QuotationCodeTable") if isinstance(payload, dict) else None
        rows = table.get("Data") if isinstance(table, dict) else None
        if not isinstance(rows, list):
            raise SchemaChangedError(
                "eastmoney search response has no data",
                source=self.meta.name,
                capability="resolve",
                assertion="QuotationCodeTable.Data is a list",
                sample=response.text[:500],
                url=str(response.url),
                hint="the search endpoint changed shape; check tests/fixtures/eastmoney",
            )

        candidates = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("Code") == instrument.code
            and row.get("SecurityTypeName") == "美股"
        ]
        if not candidates:
            raise EmptyResponseError(
                "eastmoney search found no US match",
                source=self.meta.name,
                instrument=instrument.id,
            )
        if len(candidates) > 1:
            raise AmbiguousError(
                "eastmoney search returned several US matches",
                instrument=instrument.id,
                candidates=[row.get("QuoteID") for row in candidates],
                hint="pass expected_name to disambiguate",
            )

        secid = candidates[0].get("QuoteID")
        if not isinstance(secid, str) or not secid:
            raise SchemaChangedError(
                "eastmoney search row has no QuoteID",
                source=self.meta.name,
                capability="resolve",
                assertion="candidate has a QuoteID",
                sample=str(candidates[0])[:300],
                url=str(response.url),
                hint="QuoteID is the secid format; check the search payload",
            )
        return secid
