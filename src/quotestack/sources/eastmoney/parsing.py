"""Parsing helpers shared across the Eastmoney endpoints.

Names are prefixed with an underscore because they are internal to this
package; only :class:`EastMoneySource` is public.

Every one of these exists because the raw payload does something surprising:
prices are scaled integers, percentages use a fixed divisor, and the kline
columns are ordered O-C-H-L rather than OHLC.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from quotestack.errors import SchemaChangedError
from quotestack.models import Bar, Instrument, Market

# Percentages are always hundredths of a percent, regardless of price scale.
PCT_DIVISOR = 100
_CN_TZ = timezone(timedelta(hours=8))


def _as_float(value: object, scale: int) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) / scale


def _scaled(value: object, scale: int) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    decimals = len(str(scale)) - 1
    return f"{value / scale:.{decimals}f}"


def _as_timestamp(value: object, *, source: str = "eastmoney") -> datetime:
    """Parse the observation time, or report that the payload changed.

    This used to fall back to ``now()``, which turned an unparseable stamp into
    a claim that the data was just observed. A quote that is three years old
    would have looked realtime, and nothing downstream could tell.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaChangedError(
            "eastmoney timestamp is not a number",
            source=source,
            capability="quote",
            assertion="f124 is a unix timestamp",
            sample=repr(value)[:200],
            hint="the observation time cannot be inferred; do not substitute now()",
        )
    return datetime.fromtimestamp(float(value), _CN_TZ)


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

    # The column order is not documented anywhere; it was established by
    # observation. If the source reorders them, the numbers still parse and the
    # bars are silently wrong, so the invariant is asserted instead.
    try:
        numbers = [float(value) for value in (open_price, close_price, high, low)]
    except ValueError as exc:
        raise SchemaChangedError(
            "eastmoney kline row has a non-numeric price",
            source="eastmoney",
            capability="history",
            assertion="open, close, high and low are numbers",
            sample=row[:200],
            instrument=instrument.id,
        ) from exc
    if min(numbers) < 0 or numbers[2] < numbers[3]:
        raise SchemaChangedError(
            "eastmoney kline row violates OHLC",
            source="eastmoney",
            capability="history",
            assertion="high >= low and no negative price",
            sample=row[:200],
            instrument=instrument.id,
            hint="the column order may have changed; check against the fixture",
        )

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
