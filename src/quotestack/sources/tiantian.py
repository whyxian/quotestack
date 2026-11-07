"""Tiantian Fund adapter.

Open-end mutual funds have no exchange listing, so they publish a daily NAV
instead of a quote. The data comes from a JavaScript asset that assigns global
variables::

    var fS_name = "中欧新蓝筹混合A";
    var Data_netWorthTrend = [{"x": 1216915200000, "y": 1.0}, ...];

``x`` is a millisecond timestamp, ``y`` is the NAV for that day.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from quotestack.errors import EmptyResponseError, SchemaChangedError, UpstreamError
from quotestack.models import (
    AssetClass,
    Capability,
    Instrument,
    InstrumentSummary,
    Market,
    NavPoint,
)
from quotestack.sources.base import SourceMeta

__all__ = ["TiantianSource"]

_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
_LIST_URL = "https://fund.eastmoney.com/js/fundcode_search.js"
_NAME_RE = re.compile(r'var fS_name\s*=\s*"([^"]*)"')
_NAV_RE = re.compile(r"var Data_netWorthTrend\s*=\s*(\[.*?\]);", re.S)
_LIST_RE = re.compile(r"var\s+r\s*=\s*(\[.*\]);", re.S)

_CN_TZ = ZoneInfo("Asia/Shanghai")


class TiantianSource:
    """Open-end fund NAV from Tiantian Fund (Eastmoney's fund site)."""

    meta = SourceMeta(
        name="tiantian",
        capabilities=frozenset({Capability.NAV, Capability.LIST}),
        markets=frozenset({(AssetClass.FUND, Market.CN)}),
        timeout=8.0,  # the payload can reach several hundred kilobytes
    )

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        proxy: str | None = None,
    ) -> None:
        """Create the adapter.

        Args:
            client: Optional shared HTTP client. When omitted the adapter owns
                one and closes it in :meth:`aclose`.
            proxy: Outbound proxy applied when the adapter owns the client.
        """
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=self.meta.timeout,
            proxy=proxy,
        )

    async def aclose(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def list_instruments(
        self,
        *,
        page_size: int = 500,
    ) -> AsyncIterator[list[InstrumentSummary]]:
        """Walk the full open-end fund universe.

        The whole list is a single JavaScript file, so it is fetched once and
        then sliced into batches for the caller.

        Args:
            page_size: Rows per yielded batch.

        Yields:
            Batches of fund summaries.

        Raises:
            SchemaChangedError: The list payload lost its shape.
            UpstreamError: The request failed.
        """
        response = await self._client.get(
            _LIST_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.status_code >= 400:
            raise UpstreamError(
                f"tiantian list responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
            )

        rows = self._parse_list(response.text, response)
        for start in range(0, len(rows), page_size):
            chunk = rows[start : start + page_size]
            if chunk:
                yield chunk

    def _parse_list(self, text: str, response: httpx.Response) -> list[InstrumentSummary]:
        match = _LIST_RE.search(text)
        if match is None:
            raise SchemaChangedError(
                "tiantian fund list has an unexpected shape",
                source=self.meta.name,
                capability="list",
                assertion="payload contains 'var r = [[...]]'",
                sample=text[:400],
                url=str(response.url),
                hint="the fund list script changed; check tests/fixtures/tiantian",
            )

        try:
            raw = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise SchemaChangedError(
                "tiantian fund list is not valid JSON",
                source=self.meta.name,
                capability="list",
                assertion="the r array parses as JSON",
                sample=match.group(1)[:300],
                url=str(response.url),
                hint="inspect the sample for unexpected syntax",
            ) from exc

        summaries: list[InstrumentSummary] = []
        for row in raw:
            # [code, pinyin, name, fund type, full pinyin]
            if not isinstance(row, list) or len(row) < 4:
                continue
            code, name, fund_type = row[0], row[2], row[3]
            if not isinstance(code, str) or not isinstance(name, str):
                continue
            summaries.append(
                InstrumentSummary(
                    code=code,
                    name=name,
                    asset_class=AssetClass.FUND,
                    market=Market.CN,
                    currency="CNY",
                    fund_type=fund_type if isinstance(fund_type, str) else None,
                )
            )
        return summaries

    async def nav(self, instrument: Instrument, limit: int | None = None) -> list[NavPoint]:
        """Fetch the NAV series.

        Args:
            instrument: An open-end fund carrying a ``tiantian`` alias.
            limit: Keep only the newest ``limit`` points. ``None`` keeps all.

        Returns:
            Points in ascending date order.

        Raises:
            EmptyResponseError: The fund has no published NAV.
            SchemaChangedError: The payload no longer has the expected shape.
            UpstreamError: The request failed.
        """
        code = instrument.aliases.get("tiantian")
        if code is None:
            raise UpstreamError(
                "instrument has no tiantian alias",
                source=self.meta.name,
                instrument=instrument.id,
            )

        response = await self._client.get(
            _URL.format(code=code),
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.status_code >= 400:
            raise UpstreamError(
                f"tiantian responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
            )

        points = self._parse(response.text, response)
        if not points:
            raise EmptyResponseError(
                "tiantian returned no NAV points",
                source=self.meta.name,
                instrument=instrument.id,
            )
        return points[-limit:] if limit else points

    def _parse(self, text: str, response: httpx.Response) -> list[NavPoint]:
        match = _NAV_RE.search(text)
        if match is None:
            raise SchemaChangedError(
                "tiantian payload has no Data_netWorthTrend",
                source=self.meta.name,
                capability="nav",
                assertion="payload contains 'var Data_netWorthTrend = [...]'",
                sample=text[:500],
                url=str(response.url),
                hint="the fund page layout may have changed; check tests/fixtures/tiantian",
            )

        try:
            raw = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise SchemaChangedError(
                "tiantian NAV array is not valid JSON",
                source=self.meta.name,
                capability="nav",
                assertion="Data_netWorthTrend is parseable JSON",
                sample=match.group(1)[:300],
                url=str(response.url),
                hint="inspect the sample for syntax the parser does not expect",
            ) from exc

        points: list[NavPoint] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            stamp = entry.get("x")
            value = entry.get("y")
            if not isinstance(stamp, (int, float)) or value is None:
                continue
            day = datetime.fromtimestamp(stamp / 1000, _CN_TZ)
            points.append(NavPoint(date=day.date(), nav=str(value)))
        return points
