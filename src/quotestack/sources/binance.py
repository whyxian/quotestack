"""Binance adapter.

Uses ``data-api.binance.vision`` rather than ``api.binance.com``: the main
domain is unreachable from mainland China while the data mirror is not, and it
serves the same public market data.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

from quotestack.errors import (
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
from quotestack.models.quote import status_for
from quotestack.sources.base import SourceMeta
from quotestack.sources.transport import check_status, send

__all__ = ["BinanceSource"]

_BASE = "https://data-api.binance.vision"
_EXCHANGE_INFO = f"{_BASE}/api/v3/exchangeInfo"
_TICKER_24HR = f"{_BASE}/api/v3/ticker/24hr"
_KLINES = f"{_BASE}/api/v3/klines"

# The full payload lists every pair on every quote asset; USDT covers what we
# care about and keeps the universe small.
_DEFAULT_QUOTE = "USDT"
_TRADING = "TRADING"

# Keep batch queries compact and under Binance's higher-weight threshold.
_MAX_BATCH = 50
# Binance rejects unknown trading pairs with HTTP 400 and error code -1121.
_INVALID_SYMBOL_CODE = -1121
# Binance caps /api/v3/klines at 1000 rows per call and names 60m as "1h".
_MAX_KLINE_LIMIT = 1000
_MIN_KLINE_FIELDS = 8

_INTERVALS: dict[Interval, str] = {
    Interval.M1: "1m",
    Interval.M5: "5m",
    Interval.M15: "15m",
    Interval.M30: "30m",
    Interval.M60: "1h",
    Interval.D1: "1d",
    Interval.W1: "1w",
    Interval.MO1: "1M",
}


class BinanceSource:
    """Crypto market data from Binance."""

    meta = SourceMeta(
        name="binance",
        capabilities=frozenset({Capability.LIST, Capability.QUOTE, Capability.HISTORY}),
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

    async def quote(self, instruments: Sequence[Instrument]) -> list[Quote]:
        """Fetch 24-hour spot quotes for one or more crypto pairs.

        Args:
            instruments: Resolved instruments carrying a ``binance`` alias.

        Returns:
            Quotes for the covered instruments, in request order. Missing or
            unknown symbols are omitted so one bad code does not fail a batch.

        Raises:
            EmptyResponseError: No instrument in the batch had a usable quote.
            SchemaChangedError: The response no longer has the expected shape.
            UpstreamError: The request failed or an instrument lacked an alias.
        """
        if not instruments:
            return []

        symbols = [self._symbol_of(instrument) for instrument in instruments]
        unique = list(dict.fromkeys(symbols))
        rows = await self._fetch_tickers(unique)

        quotes: list[Quote] = []
        missing: list[str] = []
        for instrument, symbol in zip(instruments, symbols, strict=True):
            row = rows.get(symbol)
            if row is None:
                missing.append(symbol)
                continue
            parsed = self._to_quote(instrument, row)
            if parsed is None:
                missing.append(symbol)
                continue
            quotes.append(parsed)

        if not quotes:
            raise EmptyResponseError(
                "binance returned no data for any instrument in the batch",
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
        """Fetch historical OHLCV bars for a crypto pair.

        Spot crypto has no splits or dividends, so ``adjust`` is accepted for
        protocol compatibility and ignored.

        Args:
            instrument: Resolved instrument carrying a ``binance`` alias.
            interval: Bar interval.
            adjust: Price adjustment mode (ignored for spot crypto).
            limit: Maximum number of bars, counted from the newest bar.

        Returns:
            Bars in ascending timestamp order.

        Raises:
            UnsupportedError: ``interval`` has no Binance mapping.
            EmptyResponseError: Binance returned no bars or rejected the symbol.
            SchemaChangedError: The payload lost its expected shape.
            UpstreamError: The request failed or the instrument lacked an alias.
        """
        del adjust  # spot crypto has no split/dividend adjustment semantics
        binance_interval = _INTERVALS.get(interval)
        if binance_interval is None:
            raise UnsupportedError(
                f"binance does not support interval {interval}",
                source=self.meta.name,
                instrument=instrument.id,
                interval=str(interval),
            )

        symbol = self._symbol_of(instrument)
        rows = await self._fetch_klines(instrument, symbol, binance_interval, limit)
        stamped = [self._to_bar(row, instrument, interval) for row in rows]
        stamped.sort(key=lambda item: item[0])
        return [bar for _, bar in stamped]

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

    async def _fetch_tickers(self, symbols: Sequence[str]) -> dict[str, dict[str, object]]:
        if len(symbols) == 1:
            return await self._fetch_one_ticker(symbols[0])
        rows: dict[str, dict[str, object]] = {}
        for start in range(0, len(symbols), _MAX_BATCH):
            chunk = symbols[start : start + _MAX_BATCH]
            if len(chunk) == 1:
                rows.update(await self._fetch_one_ticker(chunk[0]))
            else:
                rows.update(await self._fetch_ticker_batch(chunk))
        return rows

    async def _fetch_one_ticker(self, symbol: str) -> dict[str, dict[str, object]]:
        response = await send(
            self._client,
            "GET",
            _TICKER_24HR,
            source=self.meta.name,
            params={"symbol": symbol},
        )
        try:
            check_status(response, source=self.meta.name, what="binance")
        except UpstreamError as exc:
            if type(exc) is UpstreamError and _is_invalid_symbol(response):
                return {}
            raise

        payload = _parse_json(response, source=self.meta.name, capability="quote")
        if not isinstance(payload, dict) or not isinstance(payload.get("symbol"), str):
            raise SchemaChangedError(
                "binance ticker response is not a symbol object",
                source=self.meta.name,
                capability="quote",
                assertion="payload is a dict with string 'symbol'",
                sample=response.text[:400],
                url=str(response.url),
                hint="the ticker/24hr shape changed; check tests/fixtures/binance",
            )
        return {payload["symbol"]: payload}

    async def _fetch_ticker_batch(self, symbols: Sequence[str]) -> dict[str, dict[str, object]]:
        response = await send(
            self._client,
            "GET",
            _TICKER_24HR,
            source=self.meta.name,
            params={"symbols": json.dumps(list(symbols), separators=(",", ":"))},
        )
        try:
            check_status(response, source=self.meta.name, what="binance")
        except UpstreamError as exc:
            # Binance rejects the whole symbols=[...] batch if even one symbol
            # is unknown; fall back per symbol so valid entries still succeed.
            if type(exc) is UpstreamError and _is_invalid_symbol(response):
                return await self._fetch_tickers_individually(symbols)
            raise

        payload = _parse_json(response, source=self.meta.name, capability="quote")
        if not isinstance(payload, list):
            raise SchemaChangedError(
                "binance batch ticker response is not a list",
                source=self.meta.name,
                capability="quote",
                assertion="payload is a list of ticker objects",
                sample=response.text[:400],
                url=str(response.url),
                hint="the ticker/24hr batch shape changed; check tests/fixtures/binance",
            )

        rows: dict[str, dict[str, object]] = {}
        for row in payload:
            if not isinstance(row, dict) or not isinstance(row.get("symbol"), str):
                raise SchemaChangedError(
                    "binance batch ticker row is malformed",
                    source=self.meta.name,
                    capability="quote",
                    assertion="each ticker row is a dict with string 'symbol'",
                    sample=repr(row)[:200],
                    url=str(response.url),
                )
            rows[row["symbol"]] = row
        return rows

    async def _fetch_tickers_individually(
        self, symbols: Sequence[str]
    ) -> dict[str, dict[str, object]]:
        rows: dict[str, dict[str, object]] = {}
        for symbol in symbols:
            rows.update(await self._fetch_one_ticker(symbol))
        return rows

    async def _fetch_klines(
        self,
        instrument: Instrument,
        symbol: str,
        binance_interval: str,
        limit: int,
    ) -> list[object]:
        response = await send(
            self._client,
            "GET",
            _KLINES,
            source=self.meta.name,
            params={
                "symbol": symbol,
                "interval": binance_interval,
                "limit": str(min(limit, _MAX_KLINE_LIMIT)),
            },
        )
        try:
            check_status(response, source=self.meta.name, what="binance", instrument=instrument.id)
        except UpstreamError as exc:
            if type(exc) is UpstreamError and _is_invalid_symbol(response):
                raise EmptyResponseError(
                    "binance has no klines for this symbol",
                    source=self.meta.name,
                    capability="history",
                    instrument=instrument.id,
                    symbol=symbol,
                ) from exc
            raise

        payload = _parse_json(response, source=self.meta.name, capability="history")
        if not isinstance(payload, list):
            raise SchemaChangedError(
                "binance klines response is not a list",
                source=self.meta.name,
                capability="history",
                assertion="payload is a list of kline arrays",
                sample=response.text[:400],
                url=str(response.url),
                hint="the klines shape changed; check tests/fixtures/binance",
            )
        if not payload:
            raise EmptyResponseError(
                "binance returned an empty kline list",
                source=self.meta.name,
                capability="history",
                instrument=instrument.id,
            )
        return payload

    async def _fetch_symbols(self) -> list[dict[str, object]]:
        response = await send(self._client, "GET", _EXCHANGE_INFO, source=self.meta.name)
        check_status(response, source=self.meta.name, what="binance")

        payload = _parse_json(response, source=self.meta.name, capability="list")
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
    def _symbol_of(instrument: Instrument) -> str:
        symbol = instrument.aliases.get("binance")
        if not symbol:
            raise UpstreamError(
                "instrument has no binance alias",
                source="binance",
                instrument=instrument.id,
            )
        return symbol

    @staticmethod
    def _to_quote(instrument: Instrument, row: dict[str, object]) -> Quote | None:
        price_dec = _parse_decimal(row.get("lastPrice"), field="lastPrice", capability="quote")
        if price_dec < 0:
            raise SchemaChangedError(
                "binance ticker has negative lastPrice",
                source="binance",
                capability="quote",
                assertion="lastPrice >= 0",
                sample=repr(row)[:200],
                instrument=instrument.id,
            )
        if price_dec == 0:
            return None

        raw_change = row.get("priceChange")
        change = (
            None
            if raw_change is None
            else _format_decimal(
                _parse_decimal(raw_change, field="priceChange", capability="quote")
            )
        )

        raw_pct = row.get("priceChangePercent")
        change_pct = (
            None
            if raw_pct is None
            else float(_parse_decimal(raw_pct, field="priceChangePercent", capability="quote"))
        )

        close_ms = _parse_ms(row.get("closeTime"), field="closeTime", capability="quote")
        ts = datetime.fromtimestamp(close_ms / 1000, tz=UTC)
        return Quote(
            instrument_id=instrument.id,
            price=_format_decimal(price_dec),
            currency=instrument.currency,
            source="binance",
            ts=ts,
            change=change,
            change_pct=change_pct,
            status=status_for(ts),
        )

    @staticmethod
    def _to_bar(row: object, instrument: Instrument, interval: Interval) -> tuple[int, Bar]:
        if not isinstance(row, list) or len(row) < _MIN_KLINE_FIELDS:
            raise SchemaChangedError(
                "binance kline row has too few fields",
                source="binance",
                capability="history",
                assertion=f"each kline is a list with at least {_MIN_KLINE_FIELDS} items",
                sample=repr(row)[:200],
                instrument=instrument.id,
            )

        open_ms = _parse_ms(row[0], field="openTime", capability="history")
        open_dt = datetime.fromtimestamp(open_ms / 1000, tz=UTC)

        open_dec = _parse_decimal(row[1], field="open", capability="history")
        high_dec = _parse_decimal(row[2], field="high", capability="history")
        low_dec = _parse_decimal(row[3], field="low", capability="history")
        close_dec = _parse_decimal(row[4], field="close", capability="history")
        volume_dec = _parse_decimal(row[5], field="volume", capability="history")
        amount_dec = _parse_decimal(row[7], field="quoteVolume", capability="history")

        if min(open_dec, high_dec, low_dec, close_dec) < 0 or high_dec < low_dec:
            raise SchemaChangedError(
                "binance kline row violates OHLC",
                source="binance",
                capability="history",
                assertion="high >= low and no negative price",
                sample=repr(row)[:200],
                instrument=instrument.id,
            )

        return (
            open_ms,
            Bar(
                date=open_dt.date(),
                open=_format_decimal(open_dec),
                high=_format_decimal(high_dec),
                low=_format_decimal(low_dec),
                close=_format_decimal(close_dec),
                volume=_format_decimal(volume_dec),
                amount=_format_decimal(amount_dec),
                time=open_dt.strftime("%H:%M") if interval.is_intraday else None,
            ),
        )

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


def _parse_json(response: httpx.Response, *, source: str, capability: str) -> object:
    try:
        return response.json()
    except ValueError as exc:
        raise SchemaChangedError(
            f"{source} {capability} response is not valid JSON",
            source=source,
            capability=capability,
            assertion="response body is valid JSON",
            sample=response.text[:400],
            url=str(response.url),
        ) from exc


def _is_invalid_symbol(response: httpx.Response) -> bool:
    try:
        payload = response.json()
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("code") == _INVALID_SYMBOL_CODE


def _parse_decimal(raw: object, *, field: str, capability: str) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise SchemaChangedError(
            f"binance {field} is not a decimal string",
            source="binance",
            capability=capability,
            assertion=f"{field} is a finite decimal",
            sample=repr(raw)[:200],
        )
    text = raw.strip() if isinstance(raw, str) else str(raw)
    if not text:
        raise SchemaChangedError(
            f"binance {field} is empty",
            source="binance",
            capability=capability,
            assertion=f"{field} is a non-empty decimal",
            sample=repr(raw)[:200],
        )
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise SchemaChangedError(
            f"binance {field} is not a valid decimal",
            source="binance",
            capability=capability,
            assertion=f"{field} parses as Decimal",
            sample=repr(raw)[:200],
        ) from exc
    if not value.is_finite():
        raise SchemaChangedError(
            f"binance {field} is not finite",
            source="binance",
            capability=capability,
            assertion=f"{field} is finite",
            sample=repr(raw)[:200],
        )
    return value


def _format_decimal(value: Decimal) -> str:
    """Format a finite Decimal as a plain string without trailing zeros."""
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _parse_ms(raw: object, *, field: str, capability: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
        raise SchemaChangedError(
            f"binance {field} is not a millisecond timestamp",
            source="binance",
            capability=capability,
            assertion=f"{field} is a non-negative millisecond timestamp",
            sample=repr(raw)[:200],
            hint="the observation time cannot be inferred; do not substitute now()",
        )
    return int(raw)
