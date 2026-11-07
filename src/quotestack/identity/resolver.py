"""Resolve a ``(code, asset_class, market)`` triple into an Instrument.

Rule-based only: no network calls. Cases that require a search request
(US exchange suffixes, ambiguous codes) are handled in a later milestone.
"""

from __future__ import annotations

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
_CAPABILITIES_OFFEXCHANGE_FUND = frozenset({Capability.NAV, Capability.PROFILE})


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
    venue = classify_cn_fund(code)
    if venue == _CN_OFFEXCHANGE:
        return Instrument(
            id=Instrument.make_id(code, AssetClass.FUND, Market.CN),
            code=code,
            asset_class=AssetClass.FUND,
            market=Market.CN,
            currency="CNY",
            confidence=Confidence.EXACT,
            aliases={"tiantian": code},
            capabilities=_CAPABILITIES_OFFEXCHANGE_FUND,
        )

    aliases = _exchange_aliases(code, venue)
    return Instrument(
        id=Instrument.make_id(code, AssetClass.FUND, Market.CN),
        code=code,
        asset_class=AssetClass.FUND,
        market=Market.CN,
        currency="CNY",
        confidence=Confidence.EXACT,
        aliases=aliases,
        capabilities=_CAPABILITIES_LISTED,
    )


def _resolve_listed(code: str, asset_class: AssetClass) -> Instrument:
    try:
        venue = cn_exchange(code)
    except ValueError as exc:
        raise InvalidArgumentError(
            "unrecognised mainland code prefix",
            code=code,
            market=Market.CN.value,
        ) from exc

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


def _resolve_us(code: str, asset_class: AssetClass) -> Instrument:
    upper = code.upper()
    if not upper.isalpha():
        raise InvalidArgumentError(
            "US tickers must be alphabetic",
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
        aliases={"binance": f"{upper}USDT"},
        capabilities=_CAPABILITIES_LISTED,
    )


def _exchange_aliases(code: str, venue: str) -> dict[str, str]:
    return {
        "eastmoney": f"{_EM_MARKET_ID[venue]}.{code}",
        "tencent": f"{venue}{code}",
    }
