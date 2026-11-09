"""Market universe listings."""

from __future__ import annotations

from collections.abc import AsyncIterator

from quotestack.errors import SchemaChangedError, UnsupportedError, UpstreamError
from quotestack.models import AssetClass, InstrumentSummary, Market
from quotestack.sources.eastmoney.core import SOURCE_META, CoreMixin
from quotestack.sources.eastmoney.parsing import _as_date, _board_of, _has_price
from quotestack.sources.transport import send

__all__ = ["LIST_FIELDS", "LIST_FILTERS", "LIST_URL", "MAX_PAGE", "ListingsMixin"]

LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
LIST_FIELDS = "f2,f12,f13,f14,f26,f100"
MAX_PAGE = 100

# Shenzhen main board, ChiNext, Shanghai main board, STAR, Beijing.
# MK0020 is FX rather than a fund, so it stays out.
LIST_FILTERS: dict[tuple[AssetClass, Market], str] = {
    (AssetClass.STOCK, Market.CN): "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
    (AssetClass.FUND, Market.CN): (
        "b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0025,b:MK0026,b:MK0027,b:MK0028"
    ),
    (AssetClass.STOCK, Market.US): "m:105,m:106,m:107",
}


class ListingsMixin(CoreMixin):
    """Listing endpoint."""

    meta = SOURCE_META

    async def list_instruments(
        self,
        asset_class: AssetClass,
        market: Market,
        *,
        page_size: int = 100,
        skip_zero_price: bool = False,
    ) -> AsyncIterator[list[InstrumentSummary]]:
        """Walk the market listing page by page.

        Args:
            asset_class: Business classification.
            market: Trading venue.
            page_size: Rows requested per call.
            skip_zero_price: Drop rows whose price is zero, which filters out
                warrants and suspended tickers on the US feed.

        Yields:
            Batches of summaries in the source's own order.

        Raises:
            UnsupportedError: The pair has no listing feed.
            SchemaChangedError: The payload lost its shape.
            UpstreamError: The request failed.
        """
        selector = LIST_FILTERS.get((asset_class, market))
        if selector is None:
            raise UnsupportedError(
                f"no listing feed for {asset_class.value}/{market.value}",
                asset_class=asset_class.value,
                market=market.value,
            )

        size = max(1, min(page_size, MAX_PAGE))
        seen = 0
        page = 1
        while True:
            rows, total = await self._list_page(selector, page, size)
            if not rows:
                return
            batch = [
                summary
                for row in rows
                if (summary := self._to_summary(row, asset_class, market)) is not None
                and not (skip_zero_price and not _has_price(row.get("f2")))
            ]
            if batch:
                yield batch
            seen += len(rows)
            # Terminate on the reported total, not on a short page: the server
            # caps rows per page, so a short page is not proof of the last one.
            if total is not None and seen >= total:
                return
            page += 1

    async def _list_page(
        self,
        selector: str,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, object]], int | None]:
        response = await send(
            self._client,
            "GET",
            LIST_URL,
            source=self.meta.name,
            params={
                "pn": str(page),
                "pz": str(page_size),
                "po": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "fid": "f12",
                "fs": selector,
                "fields": LIST_FIELDS,
            },
        )
        if response.status_code >= 400:
            raise UpstreamError(
                f"eastmoney listing responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
            )

        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("diff") if isinstance(data, dict) else None
        total = data.get("total") if isinstance(data, dict) else None
        if rows is None:
            return [], None if not isinstance(total, int) else total
        if not isinstance(rows, list):
            raise SchemaChangedError(
                "eastmoney listing has an unexpected shape",
                source=self.meta.name,
                capability="list",
                assertion="data.diff is a list",
                sample=response.text[:400],
                url=str(response.url),
                hint="the listing endpoint changed shape; check tests/fixtures/eastmoney",
            )
        return (
            [row for row in rows if isinstance(row, dict)],
            total if isinstance(total, int) else None,
        )

    @staticmethod
    def _to_summary(
        row: dict[str, object],
        asset_class: AssetClass,
        market: Market,
    ) -> InstrumentSummary | None:
        code = row.get("f12")
        name = row.get("f14")
        if not isinstance(code, str) or not isinstance(name, str) or not code:
            return None
        venue = row.get("f13")
        industry = row.get("f100")
        return InstrumentSummary(
            code=code,
            name=name,
            asset_class=asset_class,
            market=market,
            currency="USD" if market is Market.US else "CNY",
            listing_date=_as_date(row.get("f26")),
            board=_board_of(venue, code, market),
            industry=industry if isinstance(industry, str) and industry != "-" else None,
        )
