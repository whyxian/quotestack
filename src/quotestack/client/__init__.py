"""Public client.

``MarketData`` owns three collaborators:

- a source registry, chosen by :func:`quotestack.sources.routing.candidates`
- a :class:`~quotestack.client.fetch.FetchPolicy` for cache, single-flight and
  fallback
- a per-capability TTL table

Everything user-facing lives here so one screen of scrolling answers "what can
this library do". The mechanisms it delegates to are separate because they are
independently testable.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
from types import TracebackType
from typing import Self, cast

from quotestack.benchmark import BenchmarkComponent
from quotestack.cache import MemoryCache, default_max_stale, make_key, merge_ttl
from quotestack.client.fetch import FetchPolicy
from quotestack.errors import (
    InvalidArgumentError,
    MarketDataError,
    UnavailableError,
    UnsupportedError,
    UpstreamError,
)
from quotestack.estimate import (
    assumption_of,
    describe_holdings,
    describe_index,
    equity_proxy,
    weighted_change,
)
from quotestack.identity import resolve as resolve_rules
from quotestack.identity.resolver import _EM_MARKET_ID
from quotestack.identity.rules import cn_exchange
from quotestack.logging import event, get_logger
from quotestack.models import (
    Adjust,
    Allocation,
    AssetClass,
    Bar,
    BenchmarkAssumption,
    BenchmarkCurve,
    BenchmarkPoint,
    Capability,
    Estimate,
    EstimateBasis,
    FundClass,
    FxRate,
    Instrument,
    InstrumentSummary,
    Interval,
    Market,
    NavPoint,
    Profile,
    QuarterHoldings,
    Quote,
    QuoteResult,
)
from quotestack.resilience import Cooldown, TokenBucket
from quotestack.sources import (
    BinanceSource,
    EastMoneySource,
    FxSource,
    TencentSource,
    TiantianSource,
)
from quotestack.sources.routing import route

__all__ = ["MarketData"]

_log = get_logger("client")

_QUARTER_LABEL = re.compile(r"^\d{4}Q[1-4]$")

# No fund published quarterly holdings before this year.
_EARLIEST_HOLDINGS_YEAR = 2004

# Which sources can enumerate a market. ``listed`` separates exchange-traded
# funds from the open-end universe, which share (FUND, CN).
_LISTING_PLAN: dict[tuple[AssetClass, Market, bool | None], tuple[str, ...]] = {
    (AssetClass.STOCK, Market.CN, None): ("eastmoney",),
    (AssetClass.STOCK, Market.CN, True): ("eastmoney",),
    (AssetClass.STOCK, Market.US, None): ("eastmoney",),
    (AssetClass.FUND, Market.CN, None): ("eastmoney", "tiantian"),
    (AssetClass.FUND, Market.CN, True): ("eastmoney",),
    (AssetClass.FUND, Market.CN, False): ("tiantian",),
    (AssetClass.CRYPTO, Market.CRYPTO, None): ("binance",),
}


def default_sources(proxy: str | None = None) -> dict[str, object]:
    """Build the built-in source registry."""
    return {
        "eastmoney": EastMoneySource(proxy=proxy),
        "tencent": TencentSource(proxy=proxy),
        "tiantian": TiantianSource(proxy=proxy),
        "fx": FxSource(proxy=proxy),
        "binance": BinanceSource(proxy=proxy),
    }


class MarketData:
    """
    Args:
        cache: Cache implementation. Defaults to an in-memory cache.
        ttl: Per-capability TTL overrides in seconds.
        max_stale: Per-capability stale limits in seconds.
        sources: Source registry keyed by name. Defaults to the built-ins.
        proxy: Outbound proxy passed to the default sources.
        source_priority: Overrides the routing order per capability.
        cooldown: Cooldown policy. Defaults to 30s after one failure.
        bucket: Rate limiter. Defaults to 5 req/s with a burst of 10.

    Example:
        >>> async with MarketData() as client:
        ...     quote = await client.quote("600519")
    """

    def __init__(
        self,
        *,
        cache: MemoryCache | None = None,
        ttl: Mapping[Capability, float] | None = None,
        max_stale: Mapping[Capability, float] | None = None,
        sources: Mapping[str, object] | None = None,
        proxy: str | None = None,
        source_priority: Mapping[str, Sequence[str]] | None = None,
        cooldown: Cooldown | None = None,
        bucket: TokenBucket | None = None,
    ) -> None:
        """Create a client."""
        self._cache = cache if cache is not None else MemoryCache()
        self._ttl = merge_ttl(ttl)
        self._max_stale = {**default_max_stale(), **(max_stale or {})}
        self._sources: dict[str, object] = (
            dict(sources) if sources is not None else default_sources(proxy)
        )
        self._priority: dict[str, list[str]] = {
            key: list(value) for key, value in (source_priority or {}).items()
        }
        self._cooldown: Cooldown = cooldown if cooldown is not None else Cooldown()
        self._bucket: TokenBucket = bucket if bucket is not None else TokenBucket()
        self._fetch = FetchPolicy(
            cache=self._cache,
            ttl=self._ttl,
            max_stale=self._max_stale,
            sources=self._sources,
            priority=self._priority,
            cooldown=self._cooldown,
            bucket=self._bucket,
        )

    async def __aenter__(self) -> Self:
        """Enter the async context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the client on context exit."""
        await self.aclose()

    async def aclose(self) -> None:
        """Release resources held by the underlying source."""
        self._fetch.cancel_inflight()
        for source in self._sources.values():
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()

    def resolve(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.STOCK,
        market: Market = Market.CN,
    ) -> Instrument:
        """Resolve a code into an instrument using prefix rules.

        Args:
            code: Raw code, e.g. ``600519``.
            asset_class: Business classification.
            market: Trading venue.

        Returns:
            The resolved instrument.

        Raises:
            InvalidArgumentError: The code does not fit the market.
        """
        instrument = resolve_rules(code, asset_class, market)
        event(
            _log,
            logging.DEBUG,
            "resolve",
            code=code,
            market=market.value,
            asset_class=asset_class.value,
            instrument=instrument.id,
            confidence=instrument.confidence.value,
            aliases=dict(instrument.aliases),
        )
        return instrument

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

        value = await self._fetch.get(
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
            entry = self._fetch.fresh_entry(key, Capability.QUOTE)
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

        bars = await self._fetch.get(
            key,
            Capability.HISTORY,
            instrument,
            fetch=lambda src: self._fetch_history(src, instrument, interval, adjust, limit),
            is_expected=lambda item: isinstance(item, list),
            max_age=max_age,
        )
        return cast("list[Bar]", bars)[-limit:]

    async def estimate(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.FUND,
        market: Market = Market.CN,
    ) -> Estimate:
        """Estimate the fund's intraday change.

        Two formulas are used, chosen from the fund type:

        - index funds and ETFs: tracking index change times equity exposure
        - active funds: top holdings plus a benchmark proxy for the remainder

        Inputs that are missing or stale degrade to ``basis="none"`` with
        ``change_pct=None`` rather than raising: an estimate is a best-effort
        reference, and "cannot compute" is a legitimate answer.

        Args:
            code: Fund code.
            asset_class: Defaults to ``FUND``.
            market: Defaults to ``CN``.

        Returns:
            The estimate with its basis, coverage and explanation.

        Raises:
            UnsupportedError: The instrument is not a fund.
            UpstreamError: A required request failed.
        """
        instrument = self.resolve(code, asset_class, market)
        self._require(instrument, Capability.ESTIMATE)

        try:
            profile = await self.profile(code, asset_class, market)
            allocation = await self._allocation(instrument)
        except UpstreamError as exc:
            return Estimate(
                change_pct=None,
                basis=EstimateBasis.NONE,
                explanation=f"输入不可用：{exc.message}",
            )

        assumption = assumption_of(profile.benchmark)
        if profile.fund_class is FundClass.MONEY:
            return Estimate(
                change_pct=0.0,
                basis=EstimateBasis.NONE,
                coverage=1.0,
                explanation="货币基金净值固定为 1.0，不做估值",
                benchmark_assumption=assumption,
            )

        if allocation is None:
            return Estimate(
                change_pct=None,
                basis=EstimateBasis.NONE,
                explanation="没有资产配置数据，无法确定权益仓位",
                benchmark_assumption=assumption,
            )

        if profile.tracking_index or (profile.fund_type or "").startswith("指数型"):
            return await self._estimate_by_index(profile, allocation, assumption)
        return await self._estimate_by_holdings(instrument, profile, allocation, assumption)

    async def _estimate_by_index(
        self,
        profile: Profile,
        allocation: Allocation,
        assumption: BenchmarkAssumption,
    ) -> Estimate:
        name = profile.tracking_index
        if not name:
            for component, _ in equity_proxy(profile.benchmark):
                name = component.name
                break
        if not name:
            return Estimate(
                change_pct=None,
                basis=EstimateBasis.NONE,
                explanation="指数型基金既无跟踪标的也无权益基准",
                benchmark_assumption=assumption,
            )

        secid = await self._resolve_index(name)
        if secid is None:
            return Estimate(
                change_pct=None,
                basis=EstimateBasis.NONE,
                explanation=f"跟踪标的「{name}」没有可用的指数行情",
                benchmark_assumption=assumption,
            )

        changes = await self._quotes_by_secid([secid])
        index_change = changes.get(secid)
        if index_change is None:
            return Estimate(
                change_pct=None,
                basis=EstimateBasis.NONE,
                explanation=f"跟踪标的「{name}」今日无行情",
                benchmark_assumption=assumption,
            )

        exposure = allocation.equity_exposure / 100
        result = index_change * exposure
        return Estimate(
            change_pct=round(result, 2),
            basis=EstimateBasis.INDEX,
            coverage=round(exposure, 4),
            as_of=datetime.now().astimezone(),
            explanation=describe_index(name, index_change, exposure, result),
            benchmark_assumption=assumption,
        )

    async def _estimate_by_holdings(
        self,
        instrument: Instrument,
        profile: Profile,
        allocation: Allocation,
        assumption: BenchmarkAssumption,
    ) -> Estimate:
        quarters = await self.holdings(
            instrument.code,
            instrument.asset_class,
            instrument.market,
            limit=1,
        )
        if not quarters:
            return Estimate(
                change_pct=None,
                basis=EstimateBasis.NONE,
                explanation="没有季度持仓，无法按持股估算",
                benchmark_assumption=assumption,
            )

        latest = quarters[0]
        stock_secids: list[tuple[str, float]] = []
        for holding in latest.holdings:
            try:
                venue = cn_exchange(holding.code)
            except ValueError:
                continue
            stock_secids.append((f"{_EM_MARKET_ID[venue]}.{holding.code}", holding.weight))

        stock_changes = await self._quotes_by_secid([sid for sid, _ in stock_secids])
        top = weighted_change(stock_secids, stock_changes)
        top_change = top[0] if top else 0.0
        top_weight = sum(weight for _, weight in stock_secids)

        proxies: list[tuple[str, float]] = []
        names: dict[str, str] = {}
        for component, weight in equity_proxy(profile.benchmark):
            secid = await self._resolve_index(component.name)
            if secid is None:
                continue
            proxies.append((secid, weight))
            names[secid] = component.name

        proxy_changes = await self._quotes_by_secid([sid for sid, _ in proxies]) if proxies else {}
        proxy = weighted_change(proxies, proxy_changes)
        proxy_change = proxy[0] if proxy else None

        remainder = max(0.0, allocation.stock - top_weight)
        result = top_weight / 100 * top_change
        if proxy_change is not None:
            result += remainder / 100 * proxy_change

        coverage = min(1.0, (top_weight + (remainder if proxy_change is not None else 0)) / 100)
        return Estimate(
            change_pct=round(result, 2),
            basis=EstimateBasis.HOLDINGS,
            coverage=round(coverage, 4),
            as_of=datetime.now().astimezone(),
            explanation=describe_holdings(
                top_weight,
                top_change,
                remainder,
                proxy_change,
                result,
            ),
            benchmark_assumption=assumption,
        )

    async def _allocation(self, instrument: Instrument) -> Allocation | None:
        source = self._sources.get("tiantian")
        method = getattr(source, "allocation", None)
        if method is None:
            return None
        allocation: Allocation | None = await method(instrument)
        return allocation

    async def _quotes_by_secid(self, secids: Sequence[str]) -> dict[str, float]:
        source = self._sources.get("eastmoney")
        method = getattr(source, "quotes_by_secid", None)
        if method is None or not secids:
            return {}
        changes: dict[str, float] = await method(list(secids))
        return changes

    async def benchmark(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.FUND,
        market: Market = Market.CN,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> BenchmarkCurve:
        """Build a weighted curve from the fund's performance benchmark.

        Components whose history cannot be fetched, such as the China bond
        indexes, are dropped and reported; the remaining weights are re-based
        so the curve stays comparable.

        Args:
            code: Fund code.
            asset_class: Defaults to ``FUND``.
            market: Defaults to ``CN``.
            start: First day, defaults to one year before ``end``.
            end: Last day, defaults to today.

        Returns:
            The curve with its coverage and dropped components.

        Raises:
            UnsupportedError: The fund publishes no benchmark.
            UpstreamError: A required request failed.
        """
        profile = await self.profile(code, asset_class, market)
        parsed = profile.benchmark
        if parsed is None or not parsed.components:
            raise UnsupportedError(
                "fund has no published benchmark",
                instrument=Instrument.make_id(code, asset_class, market),
            )

        last_day = end or dt.date.today()
        first_day = start or last_day - timedelta(days=365)

        used: list[BenchmarkComponent] = []
        dropped: list[str] = []
        series_by_component: list[tuple[BenchmarkComponent, dict[dt.date, str]]] = []

        for component in parsed.components:
            secid = await self._resolve_index(component.name)
            if secid is None:
                dropped.append(component.name)
                continue
            bars = await self._index_history(secid, first_day, last_day)
            if not bars:
                dropped.append(component.name)
                continue
            used.append(component)
            series_by_component.append((component, {bar.date: bar.close for bar in bars}))

        if not series_by_component:
            return BenchmarkCurve(
                effective_start=None,
                components_used=[],
                components_dropped=dropped,
                coverage=0.0,
                series=[],
            )

        common = set.intersection(*(set(values) for _, values in series_by_component))
        if not common:
            return BenchmarkCurve(
                effective_start=None,
                components_used=used,
                components_dropped=dropped,
                coverage=0.0,
                series=[],
            )

        dates = sorted(common)
        weight_total = sum(component.weight for component in used) / 100
        points: list[BenchmarkPoint] = []
        for day in dates:
            value = 0.0
            for component, values in series_by_component:
                base = values[dates[0]]
                if float(base) == 0:
                    continue
                value += (component.weight / 100) * (float(values[day]) / float(base))
            # Re-base so a partial benchmark still starts at 1.
            points.append(
                BenchmarkPoint(date=day, value=value / weight_total if weight_total else 0.0)
            )

        return BenchmarkCurve(
            effective_start=dates[0],
            components_used=used,
            components_dropped=dropped,
            coverage=round(weight_total, 4),
            series=points,
        )

    async def _resolve_index(self, name: str) -> str | None:
        source = self._sources.get("eastmoney")
        method = getattr(source, "resolve_index", None)
        if method is None:
            return None
        secid: str | None = await method(name)
        return secid

    async def _index_history(
        self,
        secid: str,
        start: dt.date,
        end: dt.date,
    ) -> list[Bar]:
        source = self._sources.get("eastmoney")
        if source is None:
            return []
        bars: list[Bar] = await source.history_by_secid(secid, start, end)  # type: ignore[attr-defined]
        return bars

    async def profile(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.FUND,
        market: Market = Market.CN,
        *,
        max_age: float | None = None,
    ) -> Profile:
        """Fetch a fund's static profile.

        Args:
            code: Fund code.
            asset_class: Defaults to ``FUND``.
            market: Defaults to ``CN``.
            max_age: Accept cached data up to this many seconds old.

        Returns:
            The profile, including the parsed benchmark.

        Raises:
            UnsupportedError: The instrument has no profile.
            UpstreamError: The source failed and no usable cache exists.
        """
        instrument = self.resolve(code, asset_class, market)
        self._require(instrument, Capability.PROFILE)
        key = make_key(Capability.PROFILE, instrument.id)

        value = await self._fetch.get(
            key,
            Capability.PROFILE,
            instrument,
            fetch=partial(self._fetch_profile, instrument),
            is_expected=lambda item: isinstance(item, Profile),
            max_age=max_age,
        )
        return cast("Profile", value)

    async def holdings(
        self,
        code: str,
        asset_class: AssetClass = AssetClass.FUND,
        market: Market = Market.CN,
        *,
        before: str | None = None,
        limit: int = 4,
    ) -> list[QuarterHoldings]:
        """Fetch quarterly top-holdings reports.

        Args:
            code: Fund code.
            asset_class: Defaults to ``FUND``.
            market: Defaults to ``CN``.
            before: Exclusive cursor such as ``2025Q4``; only earlier quarters
                are returned.
            limit: Number of quarters, not number of stocks.

        Returns:
            Quarters in descending order, newest first.

        Raises:
            InvalidArgumentError: ``before`` is not a quarter label.
            UnsupportedError: The instrument has no holdings reports.
            UpstreamError: The source failed.
        """
        if before is not None and not _QUARTER_LABEL.match(before):
            raise InvalidArgumentError(
                "before must look like 2025Q4",
                before=before,
            )

        instrument = self.resolve(code, asset_class, market)
        self._require(instrument, Capability.HOLDINGS)
        if limit < 1:
            raise InvalidArgumentError("limit must be positive", limit=limit)

        collected: list[QuarterHoldings] = []
        year = int(before[:4]) if before else datetime.now().year
        while year >= _EARLIEST_HOLDINGS_YEAR:
            # Filter before counting: a year can contribute zero usable
            # quarters when the cursor sits at its first quarter.
            usable = [q for q in collected if before is None or q.quarter < before]
            if len(usable) >= limit:
                break
            key = make_key(Capability.HOLDINGS, instrument.id, str(year))
            try:
                quarters = await self._fetch.get(
                    key,
                    Capability.HOLDINGS,
                    instrument,
                    fetch=partial(self._fetch_holdings, instrument, year),
                    is_expected=lambda value: isinstance(value, list),
                )
            except UnavailableError:
                # A single missing year must not fail the call, but a failure
                # before anything was collected means no source is serving this
                # instrument at all, which the caller needs to see.
                if not collected:
                    raise
                break

            batch = cast("list[QuarterHoldings]", quarters)
            if not batch and not collected:
                # Money market funds publish no stock positions at all. Stop
                # instead of walking back to the earliest supported year.
                return []
            collected.extend(batch)
            year -= 1

        usable = [q for q in collected if before is None or q.quarter < before]
        usable.sort(key=lambda q: q.quarter, reverse=True)
        return usable[:limit]

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

        points = await self._fetch.get(
            key,
            Capability.NAV,
            instrument,
            fetch=lambda src: self._fetch_nav(src, instrument),
            is_expected=lambda item: isinstance(item, list),
            max_age=max_age,
        )
        return cast("list[NavPoint]", points)[-limit:]

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
        method = getattr(source, "fx", None)
        if method is None:
            raise UnsupportedError("no FX source configured", base=base, quote=quote)
        rate: FxRate = await method(base, quote)
        return rate

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

    def cache_stats(self) -> dict[str, int]:
        """Return a snapshot of cache occupancy."""
        return {"entries": len(self._cache)}

    def health(self) -> dict[str, object]:
        """Return the current runtime state.

        Mirrors the shape of the HTTP ``/healthz`` payload so the CLI and the
        service report the same information.
        """
        sources: dict[str, object] = {}
        degraded = False
        for name, source in self._sources.items():
            meta = source.meta  # type: ignore[attr-defined]
            cooling = self._cooldown.is_cooling(name)
            degraded = degraded or cooling
            sources[name] = {
                "state": "cooling" if cooling else "ok",
                "cooldown_remaining": round(self._cooldown.remaining(name), 1),
                "timeout": meta.timeout,
                "capabilities": sorted(c.value for c in meta.capabilities),
            }

        return {
            "status": "degraded" if degraded else "ok",
            "proxy": os.environ.get("QUOTESTACK_PROXY_URL")
            or os.environ.get("HTTPS_PROXY")
            or None,
            "sources": sources,
            "cache": self.cache_stats(),
        }

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

    async def _fetch_profile(self, instrument: Instrument, source: object) -> object:
        return await source.profile(instrument)  # type: ignore[attr-defined]

    async def _fetch_holdings(
        self,
        instrument: Instrument,
        year: int,
        source: object,
    ) -> object:
        return await source.holdings(instrument, year)  # type: ignore[attr-defined]

    async def _fetch_nav(self, source: object, instrument: Instrument) -> object:
        return await source.nav(instrument)  # type: ignore[attr-defined]

    async def _fetch_quote(self, source: object, instrument: Instrument) -> object:
        quotes = await source.quote([instrument])  # type: ignore[attr-defined]
        return quotes[0]

    @staticmethod
    def _mark_quote_stale(value: object) -> object:
        if isinstance(value, Quote):
            return replace(value, stale=True)
        return value

    def _require(self, instrument: Instrument, capability: Capability) -> None:
        if not instrument.supports(capability):
            raise UnsupportedError(
                f"{instrument.id} has no {capability.value.lower()} data",
                instrument=instrument.id,
                capability=capability.value,
                available=sorted(c.value for c in instrument.capabilities),
            )
