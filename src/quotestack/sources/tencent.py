"""Tencent adapter.

Used as the realtime fallback when Eastmoney has no data for a symbol, and as
a second opinion for US tickers. Tencent returns a ``GBK`` encoded, tilde
separated string per symbol::

    v_sh600519="1~贵州茅台~600519~1453.00~1452.00~1450.00~...";

The A-share and US layouts differ: the US payload uses flag ``200``, carries an
explicit currency field, and formats its timestamp differently.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from quotestack.errors import EmptyResponseError, SchemaChangedError, UpstreamError
from quotestack.models import AssetClass, Capability, Instrument, Market, Quote
from quotestack.sources.base import SourceMeta

__all__ = ["TencentSource"]

_QUOTE_URL = "https://qt.gtimg.cn/q="

# Shared positions in both layouts.
_IDX_NAME = 1
_IDX_CODE = 2
_IDX_PRICE = 3
_IDX_TIMESTAMP = 30
_IDX_CHANGE = 31
_IDX_CHANGE_PCT = 32
_IDX_HIGH = 33
_IDX_LOW = 34

# US-only positions.
_IDX_US_CURRENCY = 35

_US_FLAG = "200"
_MIN_FIELDS = 35

_CN_TZ = ZoneInfo("Asia/Shanghai")
_US_TZ = ZoneInfo("America/New_York")


class TencentSource:
    """Realtime quotes from Tencent."""

    meta = SourceMeta(
        name="tencent",
        capabilities=frozenset({Capability.QUOTE}),
        markets=frozenset(
            {
                (AssetClass.STOCK, Market.CN),
                (AssetClass.STOCK, Market.US),
                (AssetClass.FUND, Market.CN),
            }
        ),
        timeout=3.0,
    )

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

    async def aclose(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def quote(self, instruments: Sequence[Instrument]) -> list[Quote]:
        """Fetch realtime quotes.

        Args:
            instruments: Instruments carrying a ``tencent`` alias.

        Returns:
            One quote per instrument, in the same order.

        Raises:
            EmptyResponseError: The source returned no row for an instrument.
            SchemaChangedError: The payload no longer has the expected shape.
            UpstreamError: The request failed.
        """
        codes = [self._code_of(instrument) for instrument in instruments]
        rows = await self._fetch(codes)

        missing = [code for code in codes if code not in rows]
        if missing:
            raise EmptyResponseError(
                "tencent returned no data for some instruments",
                source=self.meta.name,
                missing=missing,
            )

        quotes: list[Quote] = []
        for instrument, code in zip(instruments, codes, strict=True):
            quotes.append(self._to_quote(instrument, rows[code]))
        return quotes

    async def _fetch(self, codes: Sequence[str]) -> dict[str, list[str]]:
        response = await self._client.get(_QUOTE_URL + ",".join(codes))
        if response.status_code >= 400:
            raise UpstreamError(
                f"tencent responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
            )

        # Tencent serves GBK regardless of the query.
        text = response.content.decode("gbk", errors="replace")
        return self._parse(text, response)

    def _parse(self, text: str, response: httpx.Response) -> dict[str, list[str]]:
        rows: dict[str, list[str]] = {}
        for chunk in text.split(";"):
            chunk = chunk.strip()
            if not chunk.startswith("v_") or '="' not in chunk:
                continue
            key, _, body = chunk.partition('="')
            body = body.rstrip('"')
            fields = body.split("~")
            if len(fields) < _MIN_FIELDS:
                raise SchemaChangedError(
                    "tencent quote row has too few fields",
                    source=self.meta.name,
                    capability="quote",
                    assertion=f"at least {_MIN_FIELDS} tilde separated fields",
                    sample=chunk[:200],
                    url=str(response.url),
                    hint="tencent may have changed its field layout; check the field index constants",
                )
            rows[key.removeprefix("v_")] = fields
        return rows

    @staticmethod
    def _code_of(instrument: Instrument) -> str:
        code = instrument.aliases.get("tencent")
        if code is None:
            raise UpstreamError(
                "instrument has no tencent alias",
                source="tencent",
                instrument=instrument.id,
            )
        return code

    @staticmethod
    def _to_quote(instrument: Instrument, fields: list[str]) -> Quote:
        price = fields[_IDX_PRICE]
        if not price:
            raise EmptyResponseError(
                "tencent row has no price",
                source="tencent",
                instrument=instrument.id,
            )

        is_us = fields[0] == _US_FLAG
        if is_us:
            currency = fields[_IDX_US_CURRENCY] or instrument.currency
            ts = _parse_us_timestamp(fields[_IDX_TIMESTAMP])
        else:
            currency = instrument.currency
            ts = _parse_cn_timestamp(fields[_IDX_TIMESTAMP])

        return Quote(
            instrument_id=instrument.id,
            price=price,
            currency=currency,
            source="tencent",
            ts=ts,
            change=fields[_IDX_CHANGE] or None,
            change_pct=_as_float(fields[_IDX_CHANGE_PCT]),
        )


def _as_float(raw: str) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_cn_timestamp(raw: str) -> datetime:
    """Parse Tencent's compact ``YYYYMMDDHHMMSS`` stamp as Shanghai time."""
    try:
        return datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=_CN_TZ)
    except ValueError:
        return datetime.now(_CN_TZ)


def _parse_us_timestamp(raw: str) -> datetime:
    """Parse Tencent's ``YYYY-MM-DD HH:MM:SS`` stamp as New York time."""
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_US_TZ)
    except ValueError:
        return datetime.now(_US_TZ)
