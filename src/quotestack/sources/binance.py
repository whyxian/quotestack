"""Binance adapter.

Uses ``data-api.binance.vision`` rather than ``api.binance.com``: the main
domain is unreachable from mainland China while the data mirror is not, and it
serves the same public market data.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx

from quotestack.errors import SchemaChangedError, UpstreamError
from quotestack.models import AssetClass, Capability, InstrumentSummary, Market
from quotestack.sources.base import SourceMeta
from quotestack.sources.transport import send

__all__ = ["BinanceSource"]

_BASE = "https://data-api.binance.vision"
_EXCHANGE_INFO = f"{_BASE}/api/v3/exchangeInfo"

# The full payload lists every pair on every quote asset; USDT covers what we
# care about and keeps the universe small.
_DEFAULT_QUOTE = "USDT"
_TRADING = "TRADING"


class BinanceSource:
    """Crypto market data from Binance."""

    meta = SourceMeta(
        name="binance",
        capabilities=frozenset({Capability.LIST}),
        markets=frozenset({(AssetClass.CRYPTO, Market.CRYPTO)}),
        timeout=20.0,  # exchangeInfo is a few megabytes
    )

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        proxy: str | None = None,
    ) -> None:
        """Create the adapter."""
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self.meta.timeout, proxy=proxy)

    async def aclose(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def list_instruments(
        self,
        *,
        quote_asset: str = _DEFAULT_QUOTE,
        page_size: int = 500,
    ) -> AsyncIterator[list[InstrumentSummary]]:
        """Walk the tradable spot universe.

        Args:
            quote_asset: Only return pairs quoted in this asset.
            page_size: Rows per yielded batch.

        Yields:
            Batches of crypto pair summaries.

        Raises:
            SchemaChangedError: The payload lost its shape.
            UpstreamError: The request failed.
        """
        rows = await self._fetch_symbols()
        summaries = self._to_summaries(rows, quote_asset.upper())

        for start in range(0, len(summaries), page_size):
            chunk = summaries[start : start + page_size]
            if chunk:
                yield chunk

    async def _fetch_symbols(self) -> list[dict[str, object]]:
        response = await send(self._client, "GET", _EXCHANGE_INFO, source=self.meta.name)
        if response.status_code >= 400:
            raise UpstreamError(
                f"binance responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
            )

        payload = response.json()
        symbols = payload.get("symbols") if isinstance(payload, dict) else None
        if not isinstance(symbols, list):
            raise SchemaChangedError(
                "binance exchangeInfo has no symbols array",
                source=self.meta.name,
                capability="list",
                assertion="payload.symbols is a list",
                sample=response.text[:400],
                url=str(response.url),
                hint="the exchangeInfo shape changed; check tests/fixtures/binance",
            )
        return [row for row in symbols if isinstance(row, dict)]

    @staticmethod
    def _to_summaries(
        rows: Sequence[dict[str, object]],
        quote_asset: str,
    ) -> list[InstrumentSummary]:
        summaries: list[InstrumentSummary] = []
        for row in rows:
            if row.get("status") != _TRADING:
                continue
            if row.get("quoteAsset") != quote_asset:
                continue
            symbol = row.get("symbol")
            base = row.get("baseAsset")
            if not isinstance(symbol, str) or not isinstance(base, str):
                continue
            summaries.append(
                InstrumentSummary(
                    code=symbol,
                    name=base,
                    asset_class=AssetClass.CRYPTO,
                    market=Market.CRYPTO,
                    currency=quote_asset,
                )
            )
        return summaries
