"""Tiantian Fund adapter.

Open-end mutual funds have no exchange listing, so they publish a daily NAV
instead of a quote. The data comes from a JavaScript asset that assigns global
variables::

    var fS_name = "中欧新蓝筹混合A";
    var Data_netWorthTrend = [{"x": 1216915200000, "y": 1.0}, ...];

``x`` is a millisecond timestamp, ``y`` is the NAV for that day.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from quotestack.benchmark import parse_benchmark
from quotestack.errors import (
    EmptyResponseError,
    NotFoundError,
    RateLimitedError,
    SchemaChangedError,
    UpstreamError,
)
from quotestack.funds import classify_fund_type
from quotestack.models import (
    Allocation,
    AssetClass,
    Capability,
    Holding,
    Instrument,
    InstrumentSummary,
    Market,
    NavPoint,
    Profile,
    QuarterHoldings,
)
from quotestack.sources.base import SourceMeta
from quotestack.sources.transport import send

__all__ = ["TiantianSource"]

_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
_LIST_URL = "https://fund.eastmoney.com/js/fundcode_search.js"
_HOLDINGS_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
_PROFILE_URL = "https://fundf10.eastmoney.com/jbgk_{code}.html"
_NAME_RE = re.compile(r'var fS_name\s*=\s*"([^"]*)"')
_NAV_RE = re.compile(r"var Data_netWorthTrend\s*=\s*(\[.*?\]);", re.S)
_LIST_RE = re.compile(r"var\s+r\s*=\s*(\[.*\]);", re.S)
_QUARTER_RE = re.compile(r"(\d{4})年(\d)季度")
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ASSET_RE = re.compile(r"var Data_assetAllocation\s*=\s*(\{.*?\});", re.S)
_PAIR_RE = re.compile(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.S)
_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")

_CN_TZ = ZoneInfo("Asia/Shanghai")

# Eastmoney's anti-scraping status: not a standard HTTP code.
_BLOCKED_STATUS = 514


class TiantianSource:
    """Open-end fund NAV from Tiantian Fund (Eastmoney's fund site)."""

    meta = SourceMeta(
        name="tiantian",
        capabilities=frozenset(
            {
                Capability.NAV,
                Capability.LIST,
                Capability.HOLDINGS,
                Capability.PROFILE,
                Capability.ESTIMATE,
            }
        ),
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

    async def profile(self, instrument: Instrument) -> Profile:
        """Fetch the fund's static profile page.

        Args:
            instrument: Fund with a ``tiantian`` alias.

        Returns:
            The profile; fields the page omits are listed in ``missing``.

        Raises:
            UpstreamError: The request failed.
        """
        code = instrument.aliases.get("tiantian")
        if code is None:
            raise UpstreamError(
                "instrument has no tiantian alias",
                source=self.meta.name,
                instrument=instrument.id,
            )

        response = await send(
            self._client,
            "GET",
            _PROFILE_URL.format(code=code),
            source=self.meta.name,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": f"https://fundf10.eastmoney.com/ccmx_{code}.html",
            },
        )
        if response.status_code == 404:
            raise NotFoundError(
                "tiantian has no profile page for this fund",
                instrument=instrument.id,
            )
        if response.status_code == _BLOCKED_STATUS:
            raise RateLimitedError(
                "tiantian answered 514, which is its anti-scraping throttle",
                source=self.meta.name,
                instrument=instrument.id,
                hint="slow the request rate down; the source blocks bursts",
            )
        if response.status_code >= 400:
            raise UpstreamError(
                f"tiantian profile responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
                instrument=instrument.id,
            )
        return self._parse_profile(response.text)

    @staticmethod
    def _value(raw: str | None) -> str | None:
        """Treat the page's placeholder strings as absent.

        The source writes ``---`` and ``--`` for fields it has no value for,
        which is not the same as a field holding three dashes.
        """
        if raw is None:
            return None
        cleaned = raw.strip()
        if cleaned in {"", "-", "--", "---", "—", "N/A"}:
            return None
        return cleaned

    def _parse_profile(self, html: str) -> Profile:
        # The page omits the closing tag of the fund-code cell, so a naive
        # <th>..</th><td>..</td> match swallows the following pair. Closing it
        # before parsing keeps the label/value pairing intact.
        html = re.sub(r"(<td\b[^>]*>[^<]*)<th\b", r"\1</td><th", html)

        labels = {
            _TAG_RE.sub("", key).strip(): _TAG_RE.sub("", value).strip()
            for key, value in _PAIR_RE.findall(html)
        }

        fund_type = self._value(labels.get("基金类型"))
        benchmark_text = self._value(labels.get("业绩比较基准"))
        tracking = self._value(labels.get("跟踪标的"))
        scale, as_of = _split_scale(labels.get("净资产规模", ""))
        inception, _ = _split_date(labels.get("成立日期/规模", ""))

        missing = tuple(
            field
            for field, value in (
                ("fund_type", fund_type),
                ("benchmark", benchmark_text),
                ("manager", labels.get("基金经理人")),
                ("custodian", labels.get("基金托管人")),
                ("scale", scale),
                ("inception_date", inception),
            )
            if not value
        )

        return Profile(
            fund_type=fund_type,
            fund_class=classify_fund_type(fund_type),
            tracking_index=tracking if tracking and "无" not in tracking else None,
            benchmark=parse_benchmark(benchmark_text) if benchmark_text else None,
            company=self._value(labels.get("基金管理人")),
            manager=self._value(labels.get("基金经理人")),
            custodian=self._value(labels.get("基金托管人")),
            scale=scale,
            inception_date=inception,
            as_of=as_of,
            missing=missing,
        )

    async def holdings(self, instrument: Instrument, year: int) -> list[QuarterHoldings]:
        """Fetch every quarterly report published for one year.

        The endpoint answers 404 without a ``Referer`` header, so one is sent
        that names the holdings page for this fund.

        Args:
            instrument: Fund with a ``tiantian`` alias.
            year: Calendar year to fetch.

        Returns:
            Quarters in descending order; empty when the fund did not report.

        Raises:
            SchemaChangedError: The payload has no quarter sections.
            UpstreamError: The request failed.
        """
        code = instrument.aliases.get("tiantian")
        if code is None:
            raise UpstreamError(
                "instrument has no tiantian alias",
                source=self.meta.name,
                instrument=instrument.id,
            )

        response = await send(
            self._client,
            "GET",
            _HOLDINGS_URL,
            source=self.meta.name,
            params={"type": "jjcc", "code": code, "topline": "10", "year": str(year)},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": f"https://fundf10.eastmoney.com/ccmx_{code}.html",
            },
        )
        if response.status_code == _BLOCKED_STATUS:
            raise RateLimitedError(
                "tiantian answered 514, which is its anti-scraping throttle",
                source=self.meta.name,
                instrument=instrument.id,
                hint="slow the request rate down; the source blocks bursts",
            )
        if response.status_code >= 400:
            raise UpstreamError(
                f"tiantian holdings responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
                instrument=instrument.id,
            )

        # A money market fund reports no stock positions: the envelope is
        # valid but carries no quarter sections, which is an empty answer
        # rather than a schema change.
        if "apidata" not in response.text:
            quarters = None
        else:
            quarters = self._parse_holdings(response.text, response, year) or []

        if quarters is None:
            raise SchemaChangedError(
                "tiantian holdings payload has no quarter sections",
                source=self.meta.name,
                capability="holdings",
                assertion="payload contains 'YYYY年N季度'",
                sample=response.text[:400],
                url=str(response.url),
                hint="the holdings page layout changed; check tests/fixtures/tiantian",
            )
        return quarters

    def _parse_holdings(
        self,
        text: str,
        response: httpx.Response,
        year: int,
    ) -> list[QuarterHoldings] | None:
        parts = _QUARTER_RE.split(text)
        # split() yields [head, year, quarter, body, year, quarter, body, ...]
        if len(parts) < 4:
            return None

        quarters: list[QuarterHoldings] = []
        for index in range(1, len(parts) - 2, 3):
            label = f"{parts[index]}Q{parts[index + 1]}"
            holdings = self._parse_rows(parts[index + 2])
            if holdings:
                quarters.append(
                    QuarterHoldings(
                        quarter=label,
                        as_of=_quarter_end(parts[index], parts[index + 1]),
                        holdings=holdings,
                    )
                )
        return quarters

    @staticmethod
    def _parse_rows(body: str) -> list[Holding]:
        holdings: list[Holding] = []
        for row in _ROW_RE.findall(body):
            cells = [_TAG_RE.sub("", cell).strip() for cell in _CELL_RE.findall(row)]
            # Cells vary by quarter: the ratio, shares and value always sit at
            # the end, while the leading columns are stable.
            if len(cells) < 6 or not cells[1].isdigit() or len(cells[1]) != 6:
                continue
            weight = _as_percent(cells[-3])
            if weight is None:
                continue
            holdings.append(Holding(code=cells[1], name=cells[2], weight=weight))
        return holdings

    async def allocation(self, instrument: Instrument) -> Allocation | None:
        """Fetch the published asset allocation.

        Args:
            instrument: Fund with a ``tiantian`` alias.

        Returns:
            The newest allocation, or ``None`` when the fund does not publish
            one (money market funds report no stock ratio).

        Raises:
            UpstreamError: The request failed.
        """
        code = instrument.aliases.get("tiantian")
        if code is None:
            raise UpstreamError(
                "instrument has no tiantian alias",
                source=self.meta.name,
                instrument=instrument.id,
            )

        response = await send(
            self._client,
            "GET",
            _URL.format(code=code),
            source=self.meta.name,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.status_code >= 400:
            raise UpstreamError(
                f"tiantian responded with {response.status_code}",
                source=self.meta.name,
                status_code=response.status_code,
                instrument=instrument.id,
            )

        match = _ASSET_RE.search(response.text)
        if match is None:
            return None
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        return _to_allocation(payload)

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
        response = await send(
            self._client,
            "GET",
            _LIST_URL,
            source=self.meta.name,
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
                    fund_class=classify_fund_type(
                        fund_type if isinstance(fund_type, str) else None
                    ),
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

        response = await send(
            self._client,
            "GET",
            _URL.format(code=code),
            source=self.meta.name,
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


def _as_percent(raw: str) -> float | None:
    """Parse ``4.66%`` into ``4.66``."""
    try:
        return float(raw.rstrip("%").strip())
    except (AttributeError, ValueError):
        return None


def _quarter_end(year: str, quarter: str) -> dt.date:
    """Map a quarter label to its closing date."""
    month = int(quarter) * 3
    day = 31 if month in (3, 12) else 30
    return dt.date(int(year), month, day)


def _split_date(raw: str) -> tuple[dt.date | None, str | None]:
    """Split ``2008年07月25日 / 3.252亿份`` into a date and the rest."""
    match = _DATE_RE.search(raw)
    if match is None:
        return None, raw or None
    year, month, day = (int(part) for part in match.groups())
    try:
        found = dt.date(year, month, day)
    except ValueError:
        return None, raw or None
    rest = raw[match.end() :].lstrip(" /").strip()
    return found, rest or None


def _split_scale(raw: str) -> tuple[str | None, dt.date | None]:
    """Split ``80.39亿元（截止至：2026年09月30日）`` into a scale and a date."""
    if not raw or raw.strip() in {"-", "--", "---", "—", "N/A"}:
        return None, None
    candidate = raw.split("（")[0].strip()
    scale: str | None = None if candidate in {"", "-", "--", "---", "—", "N/A"} else candidate
    _, _, as_of_text = raw.partition("截止至：")
    as_of, _ = _split_date(as_of_text) if as_of_text else (None, None)
    return scale, as_of


def _to_allocation(payload: dict[str, object]) -> Allocation | None:
    """Read the newest point of each allocation series."""
    series = payload.get("series")
    categories = payload.get("categories")
    if not isinstance(series, list):
        return None

    latest: dict[str, float] = {}
    for entry in series:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        data = entry.get("data")
        if not isinstance(name, str) or not isinstance(data, list) or not data:
            continue
        value = data[-1]
        if isinstance(value, (int, float)):
            latest[name] = float(value)

    stock = latest.get("股票占净比")
    bond = latest.get("债券占净比")
    cash = latest.get("现金占净比")
    if stock is None and bond is None and cash is None:
        return None

    as_of = _parse_iso_date(categories[-1]) if isinstance(categories, list) and categories else None
    return Allocation(
        stock=stock or 0.0,
        bond=bond or 0.0,
        cash=cash or 0.0,
        as_of=as_of,
    )


def _parse_iso_date(raw: object) -> dt.date | None:
    """Parse the ``YYYY-MM-DD`` labels used by the allocation categories."""
    if not isinstance(raw, str):
        return None
    try:
        return dt.date.fromisoformat(raw.strip())
    except ValueError:
        found, _ = _split_date(raw)
        return found
