"""Parsing helpers shared across the Eastmoney endpoints.

Every one of these exists because the raw payload does something surprising:
prices are scaled integers, percentages use a fixed divisor, and the kline
columns are ordered O-C-H-L rather than OHLC.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from quotestack.errors import SchemaChangedError
from quotestack.models import Bar, Instrument, Market

__all__ = [
    "_as_date",
    "_as_float",
    "_as_int",
    "_as_timestamp",
    "_board_of",
    "_has_price",
    "_scaled",
    "_to_bar",
]

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


def _as_timestamp(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return datetime.now(_CN_TZ)
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
