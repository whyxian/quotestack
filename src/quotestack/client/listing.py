"""Market universe listings."""

from __future__ import annotations

from collections.abc import AsyncIterator

from quotestack.client.core import CoreMixin
from quotestack.errors import UnsupportedError
from quotestack.models import AssetClass, InstrumentSummary, Market

__all__ = ["ListingMixin"]

_LISTING_PLAN: dict[tuple[AssetClass, Market, bool | None], tuple[str, ...]] = {
    (AssetClass.STOCK, Market.CN, None): ("eastmoney",),
    (AssetClass.STOCK, Market.CN, True): ("eastmoney",),
    (AssetClass.STOCK, Market.US, None): ("eastmoney",),
    (AssetClass.FUND, Market.CN, None): ("eastmoney", "tiantian"),
    (AssetClass.FUND, Market.CN, True): ("eastmoney",),
    (AssetClass.FUND, Market.CN, False): ("tiantian",),
    (AssetClass.CRYPTO, Market.CRYPTO, None): ("binance",),
}


class ListingMixin(CoreMixin):
    _sources: dict[str, object]

    async def iter_instruments(
        self,
        asset_class: AssetClass,
        market: Market,
        *,
        listed: bool | None = None,
        page_size: int = 100,
        tradable_only: bool = True,
    ) -> AsyncIterator[list[InstrumentSummary]]:
        """Walk the full listing of a market.

        The library only *delivers* the listing; persisting it and diffing it
        against a previous snapshot is the caller's job.

        Args:
            asset_class: Business classification.
            market: Trading venue.
            listed: For funds, ``True`` gives exchange-traded funds and
                ``False`` the open-end universe. ``None`` yields both.
            page_size: Rows per batch.
            tradable_only: Skip rows without a price, which drops warrants and
                suspended tickers from the US feed.

        Yields:
            Batches of :class:`InstrumentSummary`, never empty.

        Raises:
            UnsupportedError: No source can enumerate this market.
        """
        names = _LISTING_PLAN.get((asset_class, market, listed))
        if not names:
            raise UnsupportedError(
                f"no listing source for {asset_class.value}/{market.value}",
                asset_class=asset_class.value,
                market=market.value,
                listed=listed,
            )

        for name in names:
            source = self._sources.get(name)
            if source is None:
                continue
            async for batch in self._listing_of(
                name,
                source,
                asset_class,
                market,
                page_size,
                tradable_only,
            ):
                yield batch

    async def _listing_of(
        self,
        name: str,
        source: object,
        asset_class: AssetClass,
        market: Market,
        page_size: int,
        tradable_only: bool,
    ) -> AsyncIterator[list[InstrumentSummary]]:
        if name == "eastmoney":
            stream = source.list_instruments(  # type: ignore[attr-defined]
                asset_class,
                market,
                page_size=page_size,
                skip_zero_price=tradable_only and market is Market.US,
            )
        else:
            stream = source.list_instruments(page_size=page_size)  # type: ignore[attr-defined]

        async for batch in stream:
            yield batch
