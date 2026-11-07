"""Time series and currency conversions."""

from __future__ import annotations

from typing import cast

from quotestack.cache import make_key
from quotestack.client.core import CoreMixin
from quotestack.client.flow import FlowMixin
from quotestack.models import (
    Adjust,
    AssetClass,
    Bar,
    Capability,
    Instrument,
    Interval,
    Market,
    NavPoint,
)

__all__ = ["SeriesMixin"]


class SeriesMixin(FlowMixin, CoreMixin):

    async def history(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.STOCK,
        market: Market = Market.CN,
        *,
        interval: Interval = Interval.D1,
        adjust: Adjust = Adjust.QFQ,
        limit: int = 250,
        max_age: float | None = None,
    ) -> list[Bar]:
        """Fetch historical bars for one instrument.

        Args:
            code: Raw code.
            asset_class: Business classification.
            market: Trading venue.
            interval: Bar interval.
            adjust: Price adjustment mode.
            limit: Maximum number of bars, counted from the newest bar.
            max_age: Accept cached data up to this many seconds old.

        Returns:
            Bars in ascending date order.

        Raises:
            UnsupportedError: The instrument has no historical bars.
            UpstreamError: The source failed and no usable cache exists.
        """
        instrument = self.resolve(code, asset_class, market)
        self._require(instrument, Capability.HISTORY)
        key = make_key(
            Capability.HISTORY,
            instrument.id,
            interval.value,
            adjust.value,
        )

        bars = await self._cached(
            key,
            Capability.HISTORY,
            instrument,
            fetch=lambda src: self._fetch_history(src, instrument, interval, adjust, limit),
            is_expected=lambda item: isinstance(item, list),
            max_age=max_age,
        )
        return cast("list[Bar]", bars)[-limit:]

    async def nav(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.FUND,
        market: Market = Market.CN,
        *,
        limit: int = 250,
        max_age: float | None = None,
    ) -> list[NavPoint]:
        """Fetch the NAV series of an open-end fund.

        Args:
            code: Fund code, e.g. ``022430``.
            asset_class: Defaults to ``FUND``.
            market: Defaults to ``CN``.
            limit: Maximum number of points, counted from the newest.
            max_age: Accept cached data up to this many seconds old.

        Returns:
            NAV points in ascending date order.

        Raises:
            UnsupportedError: The instrument is not an open-end fund.
            UpstreamError: The source failed and no usable cache exists.
        """
        instrument = self.resolve(code, asset_class, market)
        self._require(instrument, Capability.NAV)
        key = make_key(Capability.NAV, instrument.id)

        points = await self._cached(
            key,
            Capability.NAV,
            instrument,
            fetch=lambda src: self._fetch_nav(src, instrument),
            is_expected=lambda item: isinstance(item, list),
            max_age=max_age,
        )
        return cast("list[NavPoint]", points)[-limit:]


    async def _fetch_history(
        self,
        source: object,
        instrument: Instrument,
        interval: Interval,
        adjust: Adjust,
        limit: int,
    ) -> object:
        return await source.history(  # type: ignore[attr-defined]
            instrument, interval, adjust, limit
        )

    async def _fetch_nav(self, source: object, instrument: Instrument) -> object:
        return await source.nav(instrument)  # type: ignore[attr-defined]
