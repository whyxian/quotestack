"""Fake sources shared across the suite.

A test source is usually one of two shapes: it returns a fixed value, or it
raises. Both were written out by hand in every file that needed one, five lines
of ``SourceMeta`` boilerplate each time, until the same class was called
``_Source`` in four different modules.

Anything with behaviour beyond that - a source that returns a different answer
per call, or one that records arguments - stays local to its test, where the
behaviour is visible next to the assertion that needs it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from quotestack import AssetClass, Market
from quotestack.errors import UpstreamError
from quotestack.models import Capability, Quote
from quotestack.sources.base import SourceMeta

__all__ = ["DEFAULT_MARKETS", "FailingSource", "StaticQuoteSource", "make_meta"]

DEFAULT_MARKETS = frozenset({(AssetClass.STOCK, Market.CN)})


def make_meta(
    name: str,
    capabilities: set[Capability] | frozenset[Capability],
    markets: set[tuple[AssetClass, Market]] | frozenset[tuple[AssetClass, Market]] | None = None,
) -> SourceMeta:
    """Build a ``SourceMeta`` with the boilerplate filled in.

    Args:
        name: Source identifier, matching the key it is registered under.
        capabilities: What this fake can serve.
        markets: Pairs it covers; defaults to mainland stocks.

    Returns:
        A frozen ``SourceMeta``.
    """
    return SourceMeta(
        name=name,
        capabilities=frozenset(capabilities),
        markets=frozenset(markets) if markets is not None else DEFAULT_MARKETS,
    )


class FailingSource:
    """A source that fails every call, and remembers how many it got.

    The call count matters: tests assert that a cooled source is skipped rather
    than retried, which is only visible if the fake can tell.
    """

    def __init__(
        self,
        name: str = "fake",
        capabilities: set[Capability] | frozenset[Capability] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.meta = make_meta(name, capabilities or {Capability.QUOTE, Capability.HISTORY})
        self.calls = 0
        self.error = error or UpstreamError("boom", source=name)

    def _fail(self) -> None:
        self.calls += 1
        raise self.error

    async def quote(self, instruments: Any) -> Any:
        self._fail()

    async def history(self, *args: Any, **kwargs: Any) -> Any:
        self._fail()

    async def aclose(self) -> None:
        return None


class StaticQuoteSource:
    """A source that returns the same quote for every instrument it is asked."""

    def __init__(
        self,
        price: str = "100.00",
        name: str = "fake",
        capabilities: set[Capability] | frozenset[Capability] | None = None,
    ) -> None:
        self.meta = make_meta(name, capabilities or {Capability.QUOTE})
        self.price = price
        self.requested: list[str] = []

    async def quote(self, instruments: Any) -> list[Quote]:
        now = dt.datetime.now(dt.UTC)
        out = []
        for instrument in instruments:
            self.requested.append(instrument.id)
            out.append(
                Quote(
                    instrument_id=instrument.id,
                    price=self.price,
                    source=self.meta.name,
                    fetched_at=now,
                )
            )
        return out

    async def aclose(self) -> None:
        return None
