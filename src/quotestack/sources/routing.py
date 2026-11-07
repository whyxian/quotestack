"""Source routing table.

Maps ``(asset_class, market, capability)`` to an ordered list of source names.
The client walks the list until one succeeds.

Kept in code rather than configuration: routing is a design decision that
should change through review, not at runtime. Deployments may override the
order via ``MarketData(source_priority=...)``.
"""

from __future__ import annotations

from quotestack.models import AssetClass, Capability, Market

__all__ = ["ROUTES", "route"]

_ROUTES: dict[tuple[AssetClass, Market, Capability], tuple[str, ...]] = {
    # Mainland stocks and listed funds: Eastmoney first, Tencent as backup.
    (AssetClass.STOCK, Market.CN, Capability.QUOTE): ("eastmoney", "tencent"),
    (AssetClass.STOCK, Market.CN, Capability.HISTORY): ("eastmoney",),
    (AssetClass.FUND, Market.CN, Capability.QUOTE): ("eastmoney", "tencent"),
    (AssetClass.FUND, Market.CN, Capability.HISTORY): ("eastmoney",),
    # US: Eastmoney covers most tickers, Tencent fills the gaps.
    (AssetClass.STOCK, Market.US, Capability.QUOTE): ("eastmoney", "tencent"),
    (AssetClass.STOCK, Market.US, Capability.HISTORY): ("eastmoney",),
    (AssetClass.FUND, Market.US, Capability.QUOTE): ("eastmoney", "tencent"),
    (AssetClass.FUND, Market.US, Capability.HISTORY): ("eastmoney",),
    # Open-end funds publish NAV only; Tiantian is the sole provider.
    (AssetClass.FUND, Market.CN, Capability.NAV): ("tiantian",),
}


def route(asset_class: AssetClass, market: Market, capability: Capability) -> tuple[str, ...]:
    """Return the ordered source names for a capability.

    Args:
        asset_class: Business classification.
        market: Trading venue.
        capability: What the caller needs.

    Returns:
        Source names in priority order. Empty when nothing covers the pair.
    """
    return _ROUTES.get((asset_class, market, capability), ())


# Exposed for inspection and tests; treat as read-only.
ROUTES = _ROUTES
