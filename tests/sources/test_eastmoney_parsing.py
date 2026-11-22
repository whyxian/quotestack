"""Unit tests for the shared Eastmoney parsing helpers.

These are small pure functions, but every one of them encodes a payload quirk
that would otherwise be discovered in production.
"""

from __future__ import annotations

import datetime as dt

import pytest

from quotestack.models import Market
from quotestack.sources.eastmoney.parsing import (
    PCT_DIVISOR,
    _as_date,
    _as_float,
    _as_int,
    _board_of,
    _has_price,
    _scaled,
)


def test_prices_scale_by_the_reported_divisor() -> None:
    """The divisor comes from f1: 100 for two decimals, 1000 for three."""
    assert _scaled(145300, 100) == "1453.00"
    assert _scaled(1760, 1000) == "1.760"


@pytest.mark.parametrize("value", [None, True, "1453"])
def test_scaling_rejects_non_numbers(value: object) -> None:
    """A string or boolean where a number belongs is a payload change."""
    assert _scaled(value, 100) is None
    assert _as_float(value, PCT_DIVISOR) is None


def test_percentage_uses_a_fixed_divisor() -> None:
    """f3 is hundredths of a percent regardless of the price scale."""
    assert _as_float(-52, PCT_DIVISOR) == pytest.approx(-0.52)


def test_integers_default_when_absent() -> None:
    assert _as_int(None, default=4) == 4
    assert _as_int(True, default=4) == 4
    assert _as_int("7", default=4) == 4
    assert _as_int(7, default=4) == 7


def test_listing_dates_parse_or_return_none() -> None:
    assert _as_date(20260901) == dt.date(2026, 9, 1)
    assert _as_date(0) is None
    assert _as_date("20260901") is None
    assert _as_date(20261301) is None  # month 13 is not a date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(1500.5, True), (0, False), (-1, False), ("-", False), (None, False)],
)
def test_price_presence_requires_a_positive_number(raw: object, expected: bool) -> None:
    """Missing prices arrive as the string "-", which is truthy."""
    assert _has_price(raw) is expected


def test_board_derivation_for_each_mainland_prefix() -> None:
    assert _board_of(1, "600519", Market.CN) == "沪主板"
    assert _board_of(1, "688981", Market.CN) == "科创板"
    assert _board_of(0, "300750", Market.CN) == "创业板"
    assert _board_of(0, "000001", Market.CN) == "深主板"
    assert _board_of(0, "920000", Market.CN) == "北交所"


def test_board_derivation_for_us_venues() -> None:
    assert _board_of(105, "AAPL", Market.US) == "NASDAQ"
    assert _board_of(106, "IBM", Market.US) == "NYSE"
    assert _board_of(107, "SPY", Market.US) == "AMEX"
    assert _board_of(999, "X", Market.US) is None
    assert _board_of("105", "X", Market.US) is None


def test_board_is_none_for_an_unknown_venue() -> None:
    assert _board_of(9, "600519", Market.CN) is None
