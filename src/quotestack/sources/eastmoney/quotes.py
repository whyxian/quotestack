"""Realtime quotes for one or many instruments."""

from __future__ import annotations

from collections.abc import Sequence

from quotestack.errors import EmptyResponseError, SchemaChangedError, UpstreamError
from quotestack.models import Instrument, Quote
from quotestack.sources.eastmoney.core import SOURCE_META, CoreMixin
from quotestack.sources.eastmoney.parsing import (
    PCT_DIVISOR,
    _as_float,
    _as_int,
    _as_timestamp,
    _scaled,
)

__all__ = ["MAX_BATCH", "QUOTE_FIELDS", "QUOTE_URL", "QuotesMixin"]

QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
QUOTE_FIELDS = "f1,f2,f3,f4,f12,f13,f14,f124"
MAX_BATCH = 50


class QuotesMixin(CoreMixin):
    """Quote endpoint."""

    meta = SOURCE_META

    async def _fetch_rows(self, secids: Sequence[str]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for start in range(0, len(secids), MAX_BATCH):
            chunk = secids[start : start + MAX_BATCH]
            rows.extend(await self._fetch_chunk(chunk))
        return rows

    async def _fetch_chunk(self, secids: Sequence[str]) -> list[dict[str, object]]:
        response = await self._client.get(
            QUOTE_URL,
            params={"secids": ",".join(secids), "fields": QUOTE_FIELDS},
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
                hint="eastmoney may have changed its response shape; compare with tests/fixtures/eastmoney",
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
                hint="eastmoney may have changed its response shape; compare with tests/fixtures/eastmoney",
            )
        return [row for row in data["diff"] if isinstance(row, dict)]

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
        secids = [await self._secid_for(instrument) for instrument in instruments]
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

        # f4 is scaled like the price; f3 is always percent x 100 regardless
        # of how many decimals the price carries (US quotes use 3).
        return Quote(
            instrument_id=instrument.id,
            price=price,
            currency=instrument.currency,
            source="eastmoney",
            ts=_as_timestamp(row.get("f124")),
            change=_scaled(row.get("f4"), scale),
            change_pct=_as_float(row.get("f3"), PCT_DIVISOR),
        )
