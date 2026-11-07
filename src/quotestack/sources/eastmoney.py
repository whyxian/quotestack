"""Eastmoney adapter.

Eastmoney is the primary source: it covers mainland stocks, US stocks and
indices, and serves full history with three adjustment modes.

Realtime quotes come back as scaled integers. ``f1`` carries the number of
decimal places, so the real value is ``raw / 10 ** f1``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import httpx

from quotestack.errors import (
    EmptyResponseError,
    SchemaChangedError,
    UpstreamError,
)
from quotestack.models import (
    AssetClass,
    Capability,
    Instrument,
    Market,
    Quote,
)
from quotestack.sources.base import SourceMeta

__all__ = ["EastMoneySource"]

_BASE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
_FIELDS = "f1,f2,f3,f4,f12,f13,f14,f124"
_MAX_BATCH = 50
_CN_TZ = timezone(timedelta(hours=8))


class EastMoneySource:
    """Realtime quotes from Eastmoney."""

    meta = SourceMeta(
        name="eastmoney",
        capabilities=frozenset({Capability.QUOTE, Capability.HISTORY}),
        markets=frozenset(
            {
                (AssetClass.STOCK, Market.CN),
                (AssetClass.STOCK, Market.US),
                (AssetClass.FUND, Market.CN),
            }
        ),
        timeout=5.0,
    )

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        """Create the adapter.

        Args:
            client: Optional shared HTTP client. When omitted the adapter owns
                one and closes it in :meth:`aclose`.
        """
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self.meta.timeout)

    async def aclose(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def quote(self, instruments: Sequence[Instrument]) -> list[Quote]:
        """Fetch realtime quotes.

        Args:
            instruments: Instruments carrying an ``eastmoney`` alias.

        Returns:
            One quote per instrument, in the same order.

        Raises:
            EmptyResponseError: The source returned no row for an instrument.
            SchemaChangedError: The payload no longer has the expected shape.
            UpstreamError: The request failed.
        """
        secids = [self._secid_of(instrument) for instrument in instruments]
        rows = await self._fetch_rows(secids)

        by_code = {str(row.get("f12")): row for row in rows}
        quotes: list[Quote] = []
        missing: list[str] = []
        for instrument in instruments:
            row = by_code.get(instrument.code)
            if row is None:
                missing.append(instrument.code)
                continue
            quotes.append(self._to_quote(instrument, row))

        if missing:
            raise EmptyResponseError(
                "eastmoney returned no data for some instruments",
                source=self.meta.name,
                missing=missing,
            )
        return quotes

    async def _fetch_rows(self, secids: Sequence[str]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for start in range(0, len(secids), _MAX_BATCH):
            chunk = secids[start : start + _MAX_BATCH]
            rows.extend(await self._fetch_chunk(chunk))
        return rows

    async def _fetch_chunk(self, secids: Sequence[str]) -> list[dict[str, object]]:
        response = await self._client.get(
            _BASE_URL,
            params={"secids": ",".join(secids), "fields": _FIELDS},
        )
        if response.status_code >= 400:
            raise UpstreamError(
                f"eastmoney responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
            )

        payload = response.json()
        if not isinstance(payload, dict) or "data" not in payload:
            raise SchemaChangedError(
                "eastmoney response has no 'data' field",
                source=self.meta.name,
                assertion="payload contains 'data'",
                sample=response.text[:500],
                url=str(response.url),
            )

        data = payload["data"]
        if data is None:
            return []
        if not isinstance(data, dict) or not isinstance(data.get("diff"), list):
            raise SchemaChangedError(
                "eastmoney 'data.diff' is not a list",
                source=self.meta.name,
                assertion="data.diff is a list",
                sample=response.text[:500],
                url=str(response.url),
            )
        return [row for row in data["diff"] if isinstance(row, dict)]

    @staticmethod
    def _secid_of(instrument: Instrument) -> str:
        secid = instrument.aliases.get("eastmoney")
        if secid is None:
            raise UpstreamError(
                "instrument has no eastmoney alias",
                source="eastmoney",
                instrument=instrument.id,
            )
        return secid

    @staticmethod
    def _to_quote(instrument: Instrument, row: dict[str, object]) -> Quote:
        decimals = _as_int(row.get("f1"), default=2)
        scale = 10**decimals
        price = _scaled(row.get("f2"), scale)
        if price is None:
            raise EmptyResponseError(
                "eastmoney row has no price",
                source="eastmoney",
                instrument=instrument.id,
            )

        return Quote(
            instrument_id=instrument.id,
            price=price,
            currency=instrument.currency,
            source="eastmoney",
            ts=_as_timestamp(row.get("f124")),
            change=_scaled(row.get("f4"), scale),
            change_pct=_as_float(row.get("f3"), scale),
        )


def _as_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _as_float(value: object, scale: int) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) / scale


def _scaled(value: object, scale: int) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    decimals = len(str(scale)) - 1
    return f"{value / scale:.{decimals}f}"


def _as_timestamp(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return datetime.now(_CN_TZ)
    return datetime.fromtimestamp(float(value), _CN_TZ)
