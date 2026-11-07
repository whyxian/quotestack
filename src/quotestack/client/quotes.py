"""Single and batch quote operations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import cast

from quotestack.cache import make_key
from quotestack.client.core import CoreMixin
from quotestack.client.flow import FlowMixin
from quotestack.errors import MarketDataError, UnsupportedError, UpstreamError
from quotestack.logging import get_logger
from quotestack.models import (
    AssetClass,
    Capability,
    FxRate,
    Instrument,
    Market,
    Quote,
    QuoteResult,
)
from quotestack.sources.routing import route

__all__ = ["QuotesMixin"]

_log = get_logger("client")


class QuotesMixin(FlowMixin, CoreMixin):

    async def quote(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.STOCK,
        market: Market = Market.CN,
        *,
        max_age: float | None = None,
    ) -> Quote:
        """Fetch the latest quote for one instrument.

        Args:
            code: Raw code.
            asset_class: Business classification.
            market: Trading venue.
            max_age: Accept cached data up to this many seconds old. Overrides
                the configured TTL for this call only; ``0`` forces a fetch.

        Returns:
            The current quote. When the upstream fails and a cached value is
            within its ``max_stale`` window, that value is returned with
            ``stale`` set.

        Raises:
            UnsupportedError: The instrument has no realtime quote.
            UpstreamError: The source failed and no usable cache exists.
        """
        instrument = self.resolve(code, asset_class, market)
        self._require(instrument, Capability.QUOTE)
        key = make_key(Capability.QUOTE, instrument.id)

        value = await self._cached(
            key,
            Capability.QUOTE,
            instrument,
            fetch=lambda src: self._fetch_quote(src, instrument),
            is_expected=lambda item: isinstance(item, Quote),
            mark_stale=self._mark_quote_stale,
            max_age=max_age,
        )
        return cast("Quote", value)

    async def quote_many(
        self,
        items: Sequence[tuple[str, AssetClass, Market]],
    ) -> list[QuoteResult]:
        """Fetch quotes for several instruments in one call.

        Unlike :meth:`quote`, a failure in one item never fails the batch: the
        result list is the same length and order as ``items``, and each entry
        either carries a quote or an error string.

        Args:
            items: ``(code, asset_class, market)`` triples.

        Returns:
            One :class:`QuoteResult` per input item.
        """
        results: list[QuoteResult | None] = [None] * len(items)
        pending: list[tuple[int, Instrument]] = []

        for index, (code, asset_class, market) in enumerate(items):
            try:
                instrument = self.resolve(code, asset_class, market)
                self._require(instrument, Capability.QUOTE)
            except MarketDataError as exc:
                results[index] = QuoteResult(error=f"{exc.code}: {exc.message}")
                continue
            key = make_key(Capability.QUOTE, instrument.id)
            entry = self._fresh_entry(key, Capability.QUOTE)
            if entry is not None and isinstance(entry.value, Quote):
                results[index] = QuoteResult(instrument=instrument, quote=entry.value)
                continue
            pending.append((index, instrument))

        for group in self._group_by_market(pending):
            await self._fetch_group(group, results)

        return [
            result
            if result is not None
            else QuoteResult(error="UNAVAILABLE: no source served this item")
            for result in results
        ]

    @staticmethod
    def _group_by_market(
        pending: Sequence[tuple[int, Instrument]],
    ) -> list[list[tuple[int, Instrument]]]:
        groups: dict[tuple[AssetClass, Market], list[tuple[int, Instrument]]] = {}
        for index, instrument in pending:
            groups.setdefault((instrument.asset_class, instrument.market), []).append(
                (index, instrument)
            )
        return list(groups.values())

    async def _fetch_group(
        self,
        group: list[tuple[int, Instrument]],
        results: list[QuoteResult | None],
    ) -> None:
        instruments = [instrument for _, instrument in group]
        asset_class = instruments[0].asset_class
        market = instruments[0].market

        for name in self._priority.get(
            Capability.QUOTE.value,
            route(asset_class, market, Capability.QUOTE),
        ):
            source = self._sources.get(name)
            if source is None or self._cooldown.is_cooling(name):
                continue
            await self._bucket.acquire()
            try:
                quotes = await source.quote(instruments)  # type: ignore[attr-defined]
            except UpstreamError:
                self._cooldown.mark_failed(name)
                continue

            self._cooldown.mark_ok(name)
            for (index, instrument), quote in zip(group, quotes, strict=True):
                results[index] = QuoteResult(instrument=instrument, quote=quote)
                self._cache.set(make_key(Capability.QUOTE, instrument.id), quote, name)
            return

        for index, instrument in group:
            results[index] = QuoteResult(
                instrument=instrument,
                error=f"UNAVAILABLE: no source served {instrument.id}",
            )

    async def _fetch_quote(self, source: object, instrument: Instrument) -> object:
        quotes = await source.quote([instrument])  # type: ignore[attr-defined]
        return quotes[0]

    @staticmethod
    def _mark_quote_stale(value: object) -> object:
        if isinstance(value, Quote):
            return replace(value, stale=True)
        return value

    async def fx(self, base: str, quote: str) -> FxRate:
        """Convert between two currencies.

        Args:
            base: Source currency, e.g. ``USD``.
            quote: Target currency, e.g. ``CNY``.

        Returns:
            The rate. ``derived`` marks a cross calculation.

        Raises:
            UnsupportedError: No rate is available for the pair.
            UpstreamError: The source failed.
        """
        source = self._sources.get("fx")
        if source is None:
            raise UnsupportedError("no FX source configured", base=base, quote=quote)
        rate: FxRate = await source.fx(base, quote)  # type: ignore[attr-defined]
        return rate
