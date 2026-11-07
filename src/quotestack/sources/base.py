"""Source contracts.

A source declares the capabilities and markets it serves, and implements only
the protocols it can honour. No abstract base class: sources are structurally
typed so a source without history support simply does not implement
``Historian``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from quotestack.models import (
    Adjust,
    AssetClass,
    Bar,
    Capability,
    Instrument,
    Interval,
    Market,
    Quote,
)

__all__ = ["Historian", "Quoter", "SourceMeta"]


@dataclass(frozen=True, slots=True)
class SourceMeta:
    """Declarative facts about a source.

    Args:
        name: Stable source identifier used in aliases and logs.
        capabilities: Capabilities this source can serve.
        markets: ``(asset_class, market)`` pairs this source covers.
        needs_proxy: Whether the source is unreachable without an outbound proxy.
        timeout: Per-request timeout in seconds.
    """

    name: str
    capabilities: frozenset[Capability]
    markets: frozenset[tuple[AssetClass, Market]]
    needs_proxy: bool = False
    timeout: float = 5.0

    def serves(self, asset_class: AssetClass, market: Market) -> bool:
        """Whether this source covers the given class and market."""
        return (asset_class, market) in self.markets


@runtime_checkable
class Quoter(Protocol):
    """A source that can return realtime quotes."""

    meta: SourceMeta

    async def quote(self, instruments: Sequence[Instrument]) -> list[Quote]:
        """Fetch quotes for the given instruments.

        Args:
            instruments: Resolved instruments. The caller guarantees each one
                carries an alias for this source.

        Returns:
            One quote per instrument, in the same order.

        Raises:
            EmptyResponseError: The source has no data for some instrument.
            SchemaChangedError: The response structure is no longer recognised.
            UpstreamError: The request failed.
        """
        ...


@runtime_checkable
class Historian(Protocol):
    """A source that can return historical bars."""

    meta: SourceMeta

    async def history(
        self,
        instrument: Instrument,
        interval: Interval = Interval.D1,
        adjust: Adjust = Adjust.QFQ,
        limit: int = 250,
    ) -> list[Bar]:
        """Fetch historical bars.

        Args:
            instrument: Resolved instrument with an alias for this source.
            interval: Bar interval.
            adjust: Price adjustment mode.
            limit: Maximum number of bars, counted from the newest bar.

        Returns:
            Bars in ascending date order.

        Raises:
            EmptyResponseError: The source has no data for this instrument.
            SchemaChangedError: The response structure is no longer recognised.
            UpstreamError: The request failed.
        """
        ...
