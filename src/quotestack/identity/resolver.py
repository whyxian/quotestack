"""Resolve a ``(code, asset_class, market)`` triple into an Instrument.

Rule-based only: no network calls. Cases that require a search request
(US exchange suffixes, ambiguous codes) are handled in a later milestone.
"""

from __future__ import annotations

import re

from quotestack.errors import InvalidArgumentError
from quotestack.identity.rules import classify_cn_fund, cn_exchange, guess_currency
from quotestack.models import (
    AssetClass,
    Capability,
    Confidence,
    Instrument,
    Market,
)

__all__ = ["resolve"]

_CN_OFFEXCHANGE = "offexchange"

# Eastmoney encodes the exchange as a numeric market id in its secid.
_EM_MARKET_ID = {"sh": "1", "sz": "0", "bj": "0"}

_CAPABILITIES_LISTED = frozenset({Capability.QUOTE, Capability.HISTORY})
# Crypto can be enumerated but not yet priced: Binance is wired only for the
# universe listing. Declaring QUOTE/HISTORY here made resolve() promise
# something no source serves, and the failure surfaced as UNAVAILABLE - which
# tells the caller to retry a call that can never succeed.
_CAPABILITIES_CRYPTO = frozenset({Capability.LIST})
# Every fund publishes NAV, a profile, quarterly holdings and a
# benchmark; only listed ones also trade intraday.
_CAPABILITIES_OFFEXCHANGE_FUND = frozenset(
    {
        Capability.NAV,
        Capability.PROFILE,
        Capability.HOLDINGS,
        Capability.BENCHMARK,
        Capability.ESTIMATE,
    }
)


def resolve(code: str, asset_class: AssetClass, market: Market) -> Instrument:
    """Resolve a code into an :class:`Instrument` using prefix rules.

    Args:
        code: Raw code, e.g. ``600519`` or ``AAPL``.
        asset_class: Business classification.
        market: Trading venue.

    Returns:
        An instrument whose ``aliases`` map source names to their identifiers.

    Raises:
        InvalidArgumentError: The code is empty or does not fit the market.
    """
    normalized = code.strip()
    if not normalized:
        raise InvalidArgumentError("code must not be empty", code=code)

    if market is Market.CN:
        return _resolve_cn(normalized, asset_class)
    if market is Market.US:
        return _resolve_us(normalized, asset_class)
    return _resolve_crypto(normalized, asset_class)


def _resolve_cn(code: str, asset_class: AssetClass) -> Instrument:
    if not (len(code) == 6 and code.isdigit()):
        raise InvalidArgumentError(
            "mainland codes must be six digits",
            code=code,
            market=Market.CN.value,
        )

    if asset_class is AssetClass.FUND:
        return _resolve_cn_fund(code)
    return _resolve_listed(code, asset_class)


def _resolve_cn_fund(code: str) -> Instrument:
    """Resolve a mainland fund.

    Fund code prefixes are not a reliable listing indicator: ``166002`` is an
    open-end fund despite the ``16`` prefix that usually means a Shenzhen LOF.
    So every fund gets a Tiantian alias and the NAV capability, and listed
    venues additionally get the exchange aliases plus quote/history.
    """
    venue = classify_cn_fund(code)
    aliases: dict[str, str] = {"tiantian": code}
    capabilities = set(_CAPABILITIES_OFFEXCHANGE_FUND)
    confidence = Confidence.EXACT

    if venue != _CN_OFFEXCHANGE:
        aliases.update(_exchange_aliases(code, venue))
        capabilities |= _CAPABILITIES_LISTED
        # Prefix alone cannot prove the fund is listed.
        confidence = Confidence.PARTIAL

    return Instrument(
        id=Instrument.make_id(code, AssetClass.FUND, Market.CN),
        code=code,
        asset_class=AssetClass.FUND,
        market=Market.CN,
        currency="CNY",
        confidence=confidence,
        aliases=aliases,
        capabilities=frozenset(capabilities),
    )


def _resolve_listed(code: str, asset_class: AssetClass) -> Instrument:
    venue = cn_exchange(code)

    return Instrument(
        id=Instrument.make_id(code, asset_class, Market.CN),
        code=code,
        asset_class=asset_class,
        market=Market.CN,
        currency=guess_currency(asset_class, Market.CN),
        confidence=Confidence.INFERRED,
        aliases=_exchange_aliases(code, venue),
        capabilities=_CAPABILITIES_LISTED,
    )


# US tickers are mostly letters, but share classes carry a separator:
# BRK.B, BF.B, and some preferreds use a dash. Rejecting those turned a valid
# ticker into "invalid argument", which reads like a caller mistake.
_US_TICKER = re.compile(r"^[A-Z]{1,6}(?:[.-][A-Z]{1,2})?$")


def _resolve_us(code: str, asset_class: AssetClass) -> Instrument:
    upper = code.upper()
    if not _US_TICKER.match(upper):
        raise InvalidArgumentError(
            "US tickers are 1-6 letters, optionally with a class suffix",
            code=code,
            market=Market.US.value,
        )

    # Tencent accepts a bare symbol for realtime quotes; Eastmoney needs an
    # exchange suffix that only the search API can supply, so it is omitted.
    return Instrument(
        id=Instrument.make_id(upper, asset_class, Market.US),
        code=upper,
        asset_class=asset_class,
        market=Market.US,
        currency=guess_currency(asset_class, Market.US),
        confidence=Confidence.INFERRED,
        aliases={"tencent": f"us{upper}"},
        capabilities=_CAPABILITIES_LISTED,
    )


_QUOTE_SUFFIXES = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BTC", "ETH")


def _binance_symbol(upper: str) -> str:
    """Return the Binance pair for a symbol, without appending twice.

    A caller who passes ``BTCUSDT`` already named the pair; appending another
    ``USDT`` produced ``BTCUSDTUSDT``, which Binance does not know.
    """
    if any(upper.endswith(suffix) and len(upper) > len(suffix) for suffix in _QUOTE_SUFFIXES):
        return upper
    return f"{upper}USDT"


def _resolve_crypto(code: str, asset_class: AssetClass) -> Instrument:
    upper = code.upper()
    if not upper.isalnum():
        raise InvalidArgumentError(
            "crypto symbols must be alphanumeric",
            code=code,
            market=Market.CRYPTO.value,
        )

    return Instrument(
        id=Instrument.make_id(upper, asset_class, Market.CRYPTO),
        code=upper,
        asset_class=asset_class,
        market=Market.CRYPTO,
        currency=guess_currency(asset_class, Market.CRYPTO),
        confidence=Confidence.INFERRED,
        aliases={"binance": _binance_symbol(upper)},
        capabilities=_CAPABILITIES_CRYPTO,
    )


def _exchange_aliases(code: str, venue: str) -> dict[str, str]:
    return {
        "eastmoney": f"{_EM_MARKET_ID[venue]}.{code}",
        "tencent": f"{venue}{code}",
    }
