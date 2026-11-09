"""Pure prefix rules that map a code to per-source identifiers.

No network access here. Ambiguous cases that need a search request are
handled by the resolver in a later milestone.
"""

from __future__ import annotations

from quotestack.errors import InvalidArgumentError
from quotestack.models import AssetClass, Market

__all__ = [
    "classify_cn_fund",
    "cn_exchange",
    "guess_currency",
]

# Shanghai: main board 60x, STAR 688, plus funds and B-shares.
_CN_SH_PREFIXES = ("5", "6", "9")
# Shenzhen: main board 00x, ChiNext 30x.
_CN_SZ_PREFIXES = ("0", "3")
# Beijing Stock Exchange: 43x / 83x / 87x, and the newer 92x range.
_CN_BJ_PREFIXES = ("4", "8", "92")

# Exchange-traded funds: 50x/51x/52x/56x/58x on Shanghai, 15x/16x/18x on Shenzhen.
_FUND_SH_PREFIXES = ("50", "51", "52", "56", "58")
_FUND_SZ_PREFIXES = ("15", "16", "18")

_CURRENCY_BY_MARKET = {
    Market.CN: "CNY",
    Market.US: "USD",
    Market.CRYPTO: "USD",
}


def cn_exchange(code: str) -> str:
    """Return ``sh``, ``sz`` or ``bj`` for a mainland China code.

    Args:
        code: Six-digit mainland code.

    Returns:
        Exchange short name.

    Raises:
        ValueError: The code does not match any known exchange prefix.
    """
    # 92x must be checked before the broader single-digit 9 prefix.
    if code.startswith("92"):
        return "bj"
    if code.startswith(_CN_BJ_PREFIXES):
        return "bj"
    if code.startswith(_CN_SH_PREFIXES):
        return "sh"
    if code.startswith(_CN_SZ_PREFIXES):
        return "sz"
    raise InvalidArgumentError(
        "unrecognised mainland code prefix",
        code=code,
        market="CN",
    )


def classify_cn_fund(code: str) -> str:
    """Return ``sh``, ``sz`` or ``offexchange`` for a mainland fund code.

    Off-exchange funds (open-end mutual funds) have no exchange listing, so
    they only exist in the fund company's own namespace.

    Args:
        code: Six-digit fund code.

    Returns:
        ``sh`` / ``sz`` for listed funds, ``offexchange`` otherwise.
    """
    if code.startswith(_FUND_SH_PREFIXES):
        return "sh"
    if code.startswith(_FUND_SZ_PREFIXES):
        return "sz"
    return "offexchange"


def guess_currency(asset_class: AssetClass, market: Market) -> str:
    """Return the expected denomination currency.

    Args:
        asset_class: Business classification.
        market: Trading venue.

    Returns:
        ISO currency code. Crypto is quoted in USD for display purposes.
    """
    del asset_class  # currency depends on the venue only, for now
    return _CURRENCY_BY_MARKET[market]
