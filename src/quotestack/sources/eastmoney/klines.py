"""Historical bars, daily and intraday."""

from __future__ import annotations

import datetime as dt

from quotestack.errors import EmptyResponseError, SchemaChangedError
from quotestack.models import Adjust, AssetClass, Bar, Capability, Instrument, Interval, Market
from quotestack.sources.eastmoney.core import SOURCE_META, CoreMixin
from quotestack.sources.eastmoney.parsing import _to_bar
from quotestack.sources.transport import check_status, send

__all__ = ["HISTORY_FIELDS1", "HISTORY_FIELDS2", "HISTORY_URL", "KlinesMixin"]

HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
HISTORY_FIELDS1 = "f1,f2,f3"
HISTORY_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58"

# Eastmoney interval codes.
KLT: dict[Interval, str] = {
    Interval.M1: "1",
    Interval.M5: "5",
    Interval.M15: "15",
    Interval.M30: "30",
    Interval.M60: "60",
    Interval.D1: "101",
    Interval.W1: "102",
    Interval.MO1: "103",
}

# fqt: 0 unadjusted, 1 forward adjusted, 2 backward adjusted.
FQT: dict[Adjust, str] = {
    Adjust.NONE: "0",
    Adjust.QFQ: "1",
    Adjust.HFQ: "2",
}


class KlinesMixin(CoreMixin):
    """Kline endpoint."""

    meta = SOURCE_META

    async def history(
        self,
        instrument: Instrument,
        interval: Interval = Interval.D1,
        adjust: Adjust = Adjust.QFQ,
        limit: int = 250,
    ) -> list[Bar]:
        """Fetch historical bars.

        Eastmoney rows are comma separated and ordered ``date, open, close,
        high, low, volume, amount, change_pct`` -- note it is O-C-H-L, not the
        usual OHLC.

        Args:
            instrument: Instrument carrying an ``eastmoney`` alias.
            interval: Bar interval.
            adjust: Price adjustment mode.
            limit: Maximum number of bars, newest last.

        Returns:
            Bars in ascending date order.

        Raises:
            EmptyResponseError: The source returned no bars.
            SchemaChangedError: The payload no longer has the expected shape.
            UpstreamError: The request failed.
        """
        response = await send(
            self._client,
            "GET",
            HISTORY_URL,
            source=self.meta.name,
            params={
                "secid": await self._secid_for(instrument),
                "fields1": HISTORY_FIELDS1,
                "fields2": HISTORY_FIELDS2,
                "klt": KLT[interval],
                "fqt": FQT[adjust],
                "lmt": str(limit),
                "end": "20500101",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            },
        )
        check_status(response, source=self.meta.name, what="eastmoney")

        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or "data" not in payload:
            raise SchemaChangedError(
                "eastmoney history response has no 'data' field",
                source=self.meta.name,
                capability="history",
                assertion="payload contains 'data'",
                sample=response.text[:500],
                url=str(response.url),
                hint="eastmoney may have changed its response shape; compare with tests/fixtures/eastmoney",
            )
        if data is None:
            raise EmptyResponseError(
                "eastmoney has no history for this instrument",
                source=self.meta.name,
                instrument=instrument.id,
            )

        klines = data.get("klines") if isinstance(data, dict) else None
        if not isinstance(klines, list):
            raise SchemaChangedError(
                "eastmoney 'data.klines' is not a list",
                source=self.meta.name,
                capability="history",
                assertion="data.klines is a list",
                sample=response.text[:500],
                url=str(response.url),
                hint="eastmoney may have changed its response shape; compare with tests/fixtures/eastmoney",
            )
        if not klines:
            # Structure is intact, there is simply no data for this range.
            raise EmptyResponseError(
                "eastmoney returned an empty bar list",
                source=self.meta.name,
                capability="history",
                instrument=instrument.id,
            )

        return [_to_bar(str(row), instrument) for row in klines]

    async def history_by_secid(
        self,
        secid: str,
        start: dt.date,
        end: dt.date,
        limit: int = 5000,
    ) -> list[Bar]:
        """Fetch daily bars for a raw secid, used for index curves.

        Args:
            secid: Eastmoney identifier such as ``1.000906``.
            start: First day to include.
            end: Last day to include.
            limit: Safety cap on returned bars.

        Returns:
            Bars in ascending date order.

        Raises:
            UpstreamError: The request failed.
            SchemaChangedError: The payload lost its shape.
        """
        response = await send(
            self._client,
            "GET",
            HISTORY_URL,
            source=self.meta.name,
            params={
                "secid": secid,
                "fields1": HISTORY_FIELDS1,
                "fields2": HISTORY_FIELDS2,
                "klt": KLT[Interval.D1],
                "fqt": FQT[Adjust.NONE],
                "beg": start.strftime("%Y%m%d"),
                "end": end.strftime("%Y%m%d"),
                "lmt": str(limit),
            },
        )
        check_status(response, source=self.meta.name, what="eastmoney")

        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return []
        klines = data.get("klines")
        if not isinstance(klines, list):
            raise SchemaChangedError(
                "eastmoney kline payload has no klines array",
                source=self.meta.name,
                capability="history",
                assertion="data.klines is a list",
                sample=response.text[:400],
                url=str(response.url),
                hint="the kline endpoint changed shape; check tests/fixtures/eastmoney",
            )

        instrument = Instrument(
            id=f"INDEX:{secid}",
            code=secid,
            asset_class=AssetClass.STOCK,
            market=Market.CN,
            currency="CNY",
            aliases={"eastmoney": secid},
            capabilities=frozenset({Capability.HISTORY}),
        )
        bars: list[Bar] = []
        for row in klines:
            if isinstance(row, str):
                parsed = _to_bar(row, instrument)
                if parsed is not None:
                    bars.append(parsed)
        return bars
