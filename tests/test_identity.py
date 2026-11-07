"""Tests for rule-based instrument resolution."""

from __future__ import annotations

import pytest

from quotestack.errors import InvalidArgumentError
from quotestack.identity import resolve
from quotestack.models import AssetClass, Capability, Market


@pytest.mark.parametrize(
    ("code", "asset_class", "market", "expected_aliases"),
    [
        ("600519", AssetClass.STOCK, Market.CN, {"eastmoney": "1.600519", "tencent": "sh600519"}),
        ("688001", AssetClass.STOCK, Market.CN, {"eastmoney": "1.688001", "tencent": "sh688001"}),
        ("000001", AssetClass.STOCK, Market.CN, {"eastmoney": "0.000001", "tencent": "sz000001"}),
        ("300001", AssetClass.STOCK, Market.CN, {"eastmoney": "0.300001", "tencent": "sz300001"}),
        ("920000", AssetClass.STOCK, Market.CN, {"eastmoney": "0.920000", "tencent": "bj920000"}),
        ("510010", AssetClass.FUND, Market.CN, {"eastmoney": "1.510010", "tencent": "sh510010"}),
        ("160105", AssetClass.FUND, Market.CN, {"eastmoney": "0.160105", "tencent": "sz160105"}),
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
