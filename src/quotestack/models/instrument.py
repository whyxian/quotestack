"""Instrument: a tradable object identified across sources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from quotestack.models.enums import AssetClass, Capability, Confidence, Market

__all__ = ["Instrument"]


@dataclass(frozen=True, slots=True)
class Instrument:
    """A tradable object, resolved to per-source identifiers.

    Identity is always the triple ``(asset_class, market, code)``. The same
    code can mean different things across classes: ``000001`` is both a bank
    stock and a mutual fund.

    Args:
        id: Canonical identifier, e.g. ``CN:STOCK:600519``.
        code: Raw code as given by the caller.
        asset_class: Business classification.
        market: Trading venue.
        currency: Denomination currency.
        source_name: Name reported by the source. Not authoritative; the
            application's own catalogue is.
        confidence: How much to trust this resolution.
        aliases: Per-source identifiers, e.g. ``{"eastmoney": "1.600519"}``.
        capabilities: What data is available for this instrument.
    """

    id: str
    code: str
    asset_class: AssetClass
    market: Market
    currency: str
    source_name: str | None = None
    confidence: Confidence = Confidence.INFERRED
    aliases: Mapping[str, str] = field(default_factory=dict)
    capabilities: frozenset[Capability] = field(default_factory=frozenset)

    @staticmethod
    def make_id(code: str, asset_class: AssetClass, market: Market) -> str:
        """Build the canonical identifier for a triple."""
        return f"{market.value}:{asset_class.value}:{code}"

    def supports(self, capability: Capability) -> bool:
        """Whether this instrument can serve the given capability."""
        return capability in self.capabilities
