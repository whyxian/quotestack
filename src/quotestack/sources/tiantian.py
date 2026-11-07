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
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from quotestack.errors import EmptyResponseError, SchemaChangedError, UpstreamError
from quotestack.models import AssetClass, Capability, Instrument, Market, NavPoint
from quotestack.sources.base import SourceMeta

__all__ = ["TiantianSource"]

_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
_NAME_RE = re.compile(r'var fS_name\s*=\s*"([^"]*)"')
_NAV_RE = re.compile(r"var Data_netWorthTrend\s*=\s*(\[.*?\]);", re.S)

_CN_TZ = ZoneInfo("Asia/Shanghai")


class TiantianSource:
    """Open-end fund NAV from Tiantian Fund (Eastmoney's fund site)."""

    meta = SourceMeta(
        name="tiantian",
        capabilities=frozenset({Capability.NAV}),
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
