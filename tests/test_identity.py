"""Tests for rule-based instrument resolution."""

from __future__ import annotations

import pytest

from quotestack import MarketData
from quotestack.errors import InvalidArgumentError
from quotestack.identity import resolve
from quotestack.models import AssetClass, Capability, Confidence, Market


@pytest.mark.parametrize(
    ("code", "asset_class", "market", "expected_aliases"),
    [
        ("600519", AssetClass.STOCK, Market.CN, {"eastmoney": "1.600519", "tencent": "sh600519"}),
        ("688001", AssetClass.STOCK, Market.CN, {"eastmoney": "1.688001", "tencent": "sh688001"}),
        ("000001", AssetClass.STOCK, Market.CN, {"eastmoney": "0.000001", "tencent": "sz000001"}),
        ("300001", AssetClass.STOCK, Market.CN, {"eastmoney": "0.300001", "tencent": "sz300001"}),
        ("920000", AssetClass.STOCK, Market.CN, {"eastmoney": "0.920000", "tencent": "bj920000"}),
        (
            "510010",
            AssetClass.FUND,
            Market.CN,
            {"tiantian": "510010", "eastmoney": "1.510010", "tencent": "sh510010"},
        ),
        (
            "160105",
            AssetClass.FUND,
            Market.CN,
            {"tiantian": "160105", "eastmoney": "0.160105", "tencent": "sz160105"},
        ),
        ("022430", AssetClass.FUND, Market.CN, {"tiantian": "022430"}),
        ("000001", AssetClass.FUND, Market.CN, {"tiantian": "000001"}),
    ],
)
def test_resolve_cn_aliases(
    code: str,
    asset_class: AssetClass,
    market: Market,
    expected_aliases: dict[str, str],
) -> None:
    """Mainland codes map to the expected per-source identifiers."""
    instrument = resolve(code, asset_class, market)

    assert dict(instrument.aliases) == expected_aliases
    assert instrument.id == f"{market.value}:{asset_class.value}:{code}"


def test_resolve_offexchange_fund_has_no_exchange_alias() -> None:
    """Open-end funds are not listed, so they expose no exchange identifier."""
    instrument = resolve("022430", AssetClass.FUND, Market.CN)

    assert "eastmoney" not in instrument.aliases
    assert Capability.NAV in instrument.capabilities
    assert Capability.HISTORY not in instrument.capabilities


def test_listed_fund_keeps_nav_capability() -> None:
    """A listed fund also has a NAV series, and its prefix is not proof of listing."""
    instrument = resolve("166002", AssetClass.FUND, Market.CN)

    assert Capability.NAV in instrument.capabilities
    assert Capability.QUOTE in instrument.capabilities
    assert instrument.confidence is Confidence.PARTIAL


def test_resolve_listed_capabilities() -> None:
    """Listed instruments expose quote and history."""
    instrument = resolve("600519", AssetClass.STOCK, Market.CN)

    assert Capability.QUOTE in instrument.capabilities
    assert Capability.HISTORY in instrument.capabilities


def test_resolve_us_uppercases_and_uses_tencent_alias() -> None:
    """US tickers are normalised to upper case."""
    instrument = resolve("aapl", AssetClass.STOCK, Market.US)

    assert instrument.code == "AAPL"
    assert instrument.aliases["tencent"] == "usAAPL"
    assert instrument.currency == "USD"


def test_resolve_crypto_builds_binance_symbol() -> None:
    """Crypto symbols expand to a Binance trading pair."""
    instrument = resolve("btc", AssetClass.CRYPTO, Market.CRYPTO)

    assert instrument.code == "BTC"
    assert instrument.aliases["binance"] == "BTCUSDT"


@pytest.mark.parametrize(
    ("code", "asset_class", "market"),
    [
        ("", AssetClass.STOCK, Market.CN),
        ("60051", AssetClass.STOCK, Market.CN),
        ("60051A", AssetClass.STOCK, Market.CN),
        ("ZZZZZZ", AssetClass.STOCK, Market.CN),
        ("AAPL1", AssetClass.STOCK, Market.US),
        ("BTC-X", AssetClass.CRYPTO, Market.CRYPTO),
    ],
)
def test_resolve_rejects_invalid_input(
    code: str,
    asset_class: AssetClass,
    market: Market,
) -> None:
    """Malformed codes raise InvalidArgumentError rather than guessing."""
    with pytest.raises(InvalidArgumentError):
        resolve(code, asset_class, market)


async def test_crypto_declares_only_what_a_source_can_serve() -> None:
    """Declaring QUOTE for crypto made resolve() promise an impossibility.

    Nothing routes crypto quotes, so the call failed with UNAVAILABLE, which
    tells a caller to retry something that can never succeed.
    """
    from quotestack.errors import UnsupportedError

    async with MarketData() as client:
        instrument = client.resolve("BTC", AssetClass.CRYPTO, Market.CRYPTO)
        assert {c.value for c in instrument.capabilities} == {"LIST"}

        with pytest.raises(UnsupportedError):
            await client.quote("BTC", AssetClass.CRYPTO, Market.CRYPTO)


async def test_crypto_symbol_is_not_suffixed_twice() -> None:
    """BTCUSDT already names the pair; appending another USDT breaks the alias."""
    async with MarketData() as client:
        for symbol in ("BTC", "BTCUSDT", "ETHBTC"):
            instrument = client.resolve(symbol, AssetClass.CRYPTO, Market.CRYPTO)
            assert instrument.aliases["binance"] in {"BTCUSDT", "ETHBTC"}
        assert client.resolve("BTC", AssetClass.CRYPTO, Market.CRYPTO).aliases["binance"] == (
            "BTCUSDT"
        )


def test_status_is_derived_from_the_observation_time() -> None:
    """`status` defaulted to REALTIME and no source ever set it.

    A quote from a three-month-old close therefore reported itself as live; the
    three-state cache is built on this distinction being true.
    """
    from datetime import UTC, datetime, timedelta

    from quotestack.models import QuoteStatus
    from quotestack.models.quote import status_for

    now = datetime(2026, 11, 10, 2, 0, tzinfo=UTC)

    assert status_for(now, now=now) is QuoteStatus.REALTIME
    assert status_for(now - timedelta(minutes=4), now=now) is QuoteStatus.REALTIME
    assert status_for(now - timedelta(minutes=6), now=now) is QuoteStatus.HISTORICAL
    assert status_for(now - timedelta(days=90), now=now) is QuoteStatus.HISTORICAL


def test_us_tickers_with_a_class_suffix_are_valid() -> None:
    """BRK.B and BF-B are real tickers; isalpha() rejected them."""
    for symbol in ("AAPL", "BRK.B", "BF-B", "bf.b"):
        instrument = resolve(symbol, AssetClass.STOCK, Market.US)
        assert instrument.code == symbol.upper()

    for bad in ("TOOLONGNAME", "AA BB", ""):
        with pytest.raises(InvalidArgumentError):
            resolve(bad, AssetClass.STOCK, Market.US)
