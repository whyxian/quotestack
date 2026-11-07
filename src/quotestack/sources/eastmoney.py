"""Eastmoney adapter.

Eastmoney is the primary source: it covers mainland stocks, US stocks and
indices, and serves full history with three adjustment modes.

Realtime quotes come back as scaled integers. ``f1`` carries the number of
decimal places, so the real value is ``raw / 10 ** f1``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime, timedelta, timezone

import httpx

from quotestack.errors import (
    AmbiguousError,
    EmptyResponseError,
    SchemaChangedError,
    UnsupportedError,
    UpstreamError,
)
from quotestack.models import (
    Adjust,
    AssetClass,
    Bar,
    Capability,
    Instrument,
    InstrumentSummary,
    Interval,
    Market,
    Quote,
)
from quotestack.sources.base import SourceMeta

__all__ = ["EastMoneySource"]

_QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
_QUOTE_FIELDS = "f1,f2,f3,f4,f12,f13,f14,f124"
_HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
_SEARCH_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"

# Board selectors for the listing endpoint.
_LIST_FILTERS: dict[tuple[AssetClass, Market], str] = {
    (AssetClass.STOCK, Market.CN): "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
    (AssetClass.FUND, Market.CN): "b:MK0021,b:MK0022,b:MK0023,b:MK0024",
    (AssetClass.STOCK, Market.US): "m:105,m:106,m:107",
}
_LIST_FIELDS = "f2,f12,f13,f14,f26,f100"
# The server caps rows per page regardless of what we ask for.
_MAX_PAGE = 100
_HISTORY_FIELDS1 = "f1,f2,f3"
_HISTORY_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58"
_MAX_BATCH = 50
# Eastmoney always expresses percentages in hundredths of a percent.
_PCT_DIVISOR = 100
_CN_TZ = timezone(timedelta(hours=8))

# Eastmoney encodes the bar interval as an integer.
_KLT: dict[Interval, str] = {
    Interval.M1: "1",
    Interval.M5: "5",
    Interval.M15: "15",
    Interval.M30: "30",
    Interval.M60: "60",
    Interval.D1: "101",
    Interval.W1: "102",
    Interval.MO1: "103",
}

# 0 = unadjusted, 1 = forward adjusted, 2 = backward adjusted.
_FQT: dict[Adjust, str] = {
    Adjust.NONE: "0",
    Adjust.QFQ: "1",
    Adjust.HFQ: "2",
}


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

    async def history(
        self,
        instrument: Instrument,
        interval: Interval = Interval.D1,
        adjust: Adjust = Adjust.QFQ,
        limit: int = 250,
    ) -> list[Bar]:
        """Fetch historical bars.

        Eastmoney rows are comma separated and ordered ``date, open, close,
        high, low, volume, amount, change_pct`` -- note it is O-C-H-L, not the
        usual OHLC.

        Args:
            instrument: Instrument carrying an ``eastmoney`` alias.
            interval: Bar interval.
            adjust: Price adjustment mode.
            limit: Maximum number of bars, newest last.

        Returns:
            Bars in ascending date order.

        Raises:
            EmptyResponseError: The source returned no bars.
            SchemaChangedError: The payload no longer has the expected shape.
            UpstreamError: The request failed.
        """
        response = await self._client.get(
            _HISTORY_URL,
            params={
                "secid": await self._secid_for(instrument),
                "fields1": _HISTORY_FIELDS1,
                "fields2": _HISTORY_FIELDS2,
                "klt": _KLT[interval],
                "fqt": _FQT[adjust],
                "lmt": str(limit),
                "end": "20500101",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            },
        )
        if response.status_code >= 400:
            raise UpstreamError(
                f"eastmoney responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
            )

        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or "data" not in payload:
            raise SchemaChangedError(
                "eastmoney history response has no 'data' field",
                source=self.meta.name,
                capability="history",
                assertion="payload contains 'data'",
                sample=response.text[:500],
                url=str(response.url),
                hint="eastmoney may have changed its response shape; compare with tests/fixtures/eastmoney",
            )
        if data is None:
            raise EmptyResponseError(
                "eastmoney has no history for this instrument",
                source=self.meta.name,
                instrument=instrument.id,
            )

        klines = data.get("klines") if isinstance(data, dict) else None
        if not isinstance(klines, list):
            raise SchemaChangedError(
                "eastmoney 'data.klines' is not a list",
                source=self.meta.name,
                capability="history",
                assertion="data.klines is a list",
                sample=response.text[:500],
                url=str(response.url),
                hint="eastmoney may have changed its response shape; compare with tests/fixtures/eastmoney",
            )
        if not klines:
            # Structure is intact, there is simply no data for this range.
            raise EmptyResponseError(
                "eastmoney returned an empty bar list",
                source=self.meta.name,
                capability="history",
                instrument=instrument.id,
            )

        return [_to_bar(str(row), instrument) for row in klines]

    async def _fetch_rows(self, secids: Sequence[str]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for start in range(0, len(secids), _MAX_BATCH):
            chunk = secids[start : start + _MAX_BATCH]
            rows.extend(await self._fetch_chunk(chunk))
        return rows

    async def _fetch_chunk(self, secids: Sequence[str]) -> list[dict[str, object]]:
        response = await self._client.get(
            _QUOTE_URL,
            params={"secids": ",".join(secids), "fields": _QUOTE_FIELDS},
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

    async def list_instruments(
        self,
        asset_class: AssetClass,
        market: Market,
        *,
        page_size: int = 100,
        skip_zero_price: bool = False,
    ) -> AsyncIterator[list[InstrumentSummary]]:
        """Walk the market listing page by page.

        Args:
            asset_class: Business classification.
            market: Trading venue.
            page_size: Rows requested per call.
            skip_zero_price: Drop rows whose price is zero, which filters out
                warrants and suspended tickers on the US feed.

        Yields:
            Batches of summaries in the source's own order.

        Raises:
            UnsupportedError: The pair has no listing feed.
            SchemaChangedError: The payload lost its shape.
            UpstreamError: The request failed.
        """
        selector = _LIST_FILTERS.get((asset_class, market))
        if selector is None:
            raise UnsupportedError(
                f"no listing feed for {asset_class.value}/{market.value}",
                asset_class=asset_class.value,
                market=market.value,
            )

        size = max(1, min(page_size, _MAX_PAGE))
        seen = 0
        page = 1
        while True:
            rows, total = await self._list_page(selector, page, size)
            if not rows:
                return
            batch = [
                summary
                for row in rows
                if (summary := self._to_summary(row, asset_class, market)) is not None
                and not (skip_zero_price and not _has_price(row.get("f2")))
            ]
            if batch:
                yield batch
            seen += len(rows)
            # Terminate on the reported total, not on a short page: the server
            # caps rows per page, so a short page is not proof of the last one.
            if total is not None and seen >= total:
                return
            page += 1

    async def _list_page(
        self,
        selector: str,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, object]], int | None]:
        response = await self._client.get(
            _LIST_URL,
            params={
                "pn": str(page),
                "pz": str(page_size),
                "po": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "fid": "f12",
                "fs": selector,
                "fields": _LIST_FIELDS,
            },
        )
        if response.status_code >= 400:
            raise UpstreamError(
                f"eastmoney listing responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
            )

        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("diff") if isinstance(data, dict) else None
        total = data.get("total") if isinstance(data, dict) else None
        if rows is None:
            return [], None if not isinstance(total, int) else total
        if not isinstance(rows, list):
            raise SchemaChangedError(
                "eastmoney listing has an unexpected shape",
                source=self.meta.name,
                capability="list",
                assertion="data.diff is a list",
                sample=response.text[:400],
                url=str(response.url),
                hint="the listing endpoint changed shape; check tests/fixtures/eastmoney",
            )
        return (
            [row for row in rows if isinstance(row, dict)],
            total if isinstance(total, int) else None,
        )

    @staticmethod
    def _to_summary(
        row: dict[str, object],
        asset_class: AssetClass,
        market: Market,
    ) -> InstrumentSummary | None:
        code = row.get("f12")
        name = row.get("f14")
        if not isinstance(code, str) or not isinstance(name, str) or not code:
            return None
        venue = row.get("f13")
        industry = row.get("f100")
        return InstrumentSummary(
            code=code,
            name=name,
            asset_class=asset_class,
            market=market,
            currency="USD" if market is Market.US else "CNY",
            listing_date=_as_date(row.get("f26")),
            board=_board_of(venue, code, market),
            industry=industry if isinstance(industry, str) and industry != "-" else None,
        )

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
            _SEARCH_URL,
            params={
                "input": instrument.code,
                "type": "14",
                "token": _SEARCH_TOKEN,
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
            change_pct=_as_float(row.get("f3"), _PCT_DIVISOR),
        )


def _to_bar(row: str, instrument: Instrument) -> Bar:
    parts = row.split(",")
    if len(parts) < 6:
        raise SchemaChangedError(
            "eastmoney kline row has too few fields",
            source="eastmoney",
            capability="history",
            assertion="row has at least 6 comma separated fields",
            sample=row[:200],
            instrument=instrument.id,
        )

    try:
        # Minute bars carry a trailing time; the trading day is the date part.
        day = date.fromisoformat(parts[0][:10])
    except ValueError as exc:
        raise SchemaChangedError(
            "eastmoney kline row has an unparsable date",
            source="eastmoney",
            capability="history",
            assertion="first field is YYYY-MM-DD",
            sample=row[:200],
            instrument=instrument.id,
        ) from exc

    _, open_price, close_price, high, low, volume, *rest = parts
    # Intraday rows look like "2026-11-06 09:35"; daily rows have no time part.
    stamp = parts[0]
    clock = stamp[11:16] if len(stamp) >= 16 else None
    return Bar(
        date=day,
        open=open_price,
        high=high,
        low=low,
        close=close_price,
        volume=volume,
        amount=rest[0] if rest else None,
        time=clock,
    )


def _as_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _has_price(raw: object) -> bool:
    """Whether a listing row carries a usable price.

    Eastmoney emits ``"-"`` rather than zero for warrants and suspended
    tickers, so a truthiness check is not enough.
    """
    return isinstance(raw, (int, float)) and raw > 0


def _as_date(raw: object) -> date | None:
    """Parse Eastmoney's ``YYYYMMDD`` integer date."""
    if not isinstance(raw, int) or raw < 19000101:
        return None
    try:
        return date(raw // 10000, raw // 100 % 100, raw % 100)
    except ValueError:
        return None


def _board_of(venue: object, code: str, market: Market) -> str | None:
    """Map a market id plus code prefix to a human readable board."""
    if market is Market.US:
        if not isinstance(venue, int):
            return None
        return {105: "NASDAQ", 106: "NYSE", 107: "AMEX"}.get(venue)

    if venue == 1:
        return "科创板" if code.startswith("688") else "沪主板"
    if venue == 0:
        if code.startswith(("300", "301")):
            return "创业板"
        if code.startswith(("8", "4", "920")):
            return "北交所"
        return "深主板"
    return None


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
