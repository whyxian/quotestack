"""Backtest the estimate against realised NAV changes.

For every trading day in the window the script rebuilds the estimate using
only data that would have been available *that day*, then compares it with the
fund's published NAV change.

Two sources of optimism are controlled:

- **Publication lag.** Quarterly holdings are published weeks after the quarter
  ends, so a report is not used until ``--lag-days`` after its period end. The
  default of 20 days is conservative rather than optimistic.
- **Survivorship.** Holdings come from the reports the fund actually published,
  so a quarter with no report simply carries the previous one forward.

Usage::

    uv run python benchmarks/estimate_accuracy.py --fund 166002 --days 120
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import itertools
import math
import statistics
from dataclasses import dataclass
from typing import cast

from quotestack import MarketData
from quotestack.estimate import equity_proxy
from quotestack.identity.resolver import _EM_MARKET_ID
from quotestack.identity.rules import cn_exchange
from quotestack.models import AssetClass, Holding, Market
from quotestack.sources import EastMoneySource


@dataclass(frozen=True, slots=True)
class Day:
    """One observed trading day."""

    date: dt.date
    estimate: float
    actual: float


def _quarter_available(quarter: str, lag_days: int) -> dt.date:
    """Date by which a quarter's report should have been published."""
    year, q = int(quarter[:4]), int(quarter[5])
    month = q * 3
    end = dt.date(year, month, 31 if month in (3, 12) else 30)
    return end + dt.timedelta(days=lag_days)


def _holdings_for(
    day: dt.date, reports: list[tuple[str, list[Holding]]], lag: int
) -> list[Holding]:
    """Return the newest report that would have been public on ``day``."""
    usable = [
        (quarter, holdings)
        for quarter, holdings in reports
        if _quarter_available(quarter, lag) <= day
    ]
    if not usable:
        return []
    usable.sort(key=lambda item: item[0])
    return usable[-1][1]


def _returns(series: dict[dt.date, float]) -> dict[dt.date, float]:
    """Percent change from the previous available day."""
    dates = sorted(series)
    out: dict[dt.date, float] = {}
    for previous, current in itertools.pairwise(dates):
        base = series[previous]
        if base == 0:
            continue
        out[current] = (series[current] / base - 1) * 100
    return out


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / math.sqrt(var_x * var_y)


async def _run(args: argparse.Namespace) -> int:
    end = dt.date.today()
    start = end - dt.timedelta(days=args.days)

    async with MarketData() as client:
        profile = await client.profile(args.fund)
        nav_points = await client.nav(args.fund, limit=4000)
        nav = {point.date: float(point.nav) for point in nav_points if start <= point.date <= end}
        if len(nav) < 10:
            print(f"not enough NAV history between {start} and {end}")
            return 1

        reports: list[tuple[str, list[Holding]]] = []
        quarters = await client.holdings(args.fund, limit=args.quarters)
        for quarter in quarters:
            reports.append((quarter.quarter, quarter.holdings))

        eastmoney = cast(EastMoneySource, client._sources["eastmoney"])
        instrument = client.resolve(args.fund, AssetClass.FUND, Market.CN)
        allocation = await client._allocation(instrument)
        local_ratio = args.stock_ratio
        if local_ratio is None:
            local_ratio = allocation.equity_exposure if allocation else 70.0
        print(f"stock ratio {local_ratio:.1f}%")

        # Stock histories for every code that appears in a usable report.
        codes = {holding.code for _, holdings in reports for holding in holdings}
        stock_series: dict[str, dict[dt.date, float]] = {}
        for code in sorted(codes):
            try:
                secid = f"{_EM_MARKET_ID[cn_exchange(code)]}.{code}"
            except ValueError:
                continue
            bars = await eastmoney.history_by_secid(secid, start, end)
            if bars:
                stock_series[code] = {bar.date: float(bar.close) for bar in bars}

        # Index histories for the equity components of the benchmark.
        index_series: list[tuple[float, dict[dt.date, float]]] = []
        if profile.benchmark is not None:
            for component, weight in equity_proxy(profile.benchmark):
                index_secid = await eastmoney.resolve_index(component.name)
                if index_secid is None:
                    continue
                bars = await eastmoney.history_by_secid(index_secid, start, end)
                if bars:
                    index_series.append((weight, {bar.date: float(bar.close) for bar in bars}))

    stock_returns = {code: _returns(series) for code, series in stock_series.items()}
    index_returns = [(weight, _returns(series)) for weight, series in index_series]
    nav_returns = _returns(nav)

    stock_ratio = local_ratio
    days: list[Day] = []
    for trading_day in sorted(nav_returns):
        holdings = _holdings_for(trading_day, reports, args.lag_days)
        if not holdings:
            continue

        top_weight = 0.0
        contribution = 0.0
        for holding in holdings:
            change = stock_returns.get(holding.code, {}).get(trading_day)
            if change is None:
                continue
            top_weight += holding.weight
            contribution += holding.weight / 100 * change

        remainder = max(0.0, stock_ratio - top_weight)
        proxy_total = 0.0
        proxy_used = 0.0
        for weight, returns in index_returns:
            change = returns.get(trading_day)
            if change is None:
                continue
            proxy_total += change * weight
            proxy_used += weight
        if proxy_used > 0 and remainder > 0:
            contribution += remainder / 100 * (proxy_total / proxy_used)

        days.append(Day(date=trading_day, estimate=contribution, actual=nav_returns[trading_day]))

    if not days:
        print("no overlapping days; try a wider window")
        return 1

    estimates = [day.estimate for day in days]
    actuals = [day.actual for day in days]
    correlation = _correlation(estimates, actuals)
    mae = statistics.fmean(abs(day.estimate - day.actual) for day in days)
    bias = statistics.fmean(day.estimate - day.actual for day in days)

    print(f"fund        {args.fund}")
    print(f"window      {days[0].date} .. {days[-1].date}  ({len(days)} days)")
    print(f"holdings    {len(reports)} reports, lag {args.lag_days} days")
    print(f"correlation {correlation:.3f}" if correlation is not None else "correlation n/a")
    print(f"MAE         {mae:.3f} pp")
    print(f"bias        {bias:+.3f} pp")
    print()
    print(f"{'date':<12}{'estimate':>10}{'actual':>10}{'error':>10}")
    for day in days[-10:]:
        print(
            f"{day.date.isoformat():<12}"
            f"{day.estimate:>9.2f}%{day.actual:>9.2f}%"
            f"{day.estimate - day.actual:>9.2f}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fund", default="166002", help="fund code to backtest")
    parser.add_argument("--days", type=int, default=120, help="calendar days to cover")
    parser.add_argument("--quarters", type=int, default=8, help="how many reports to load")
    parser.add_argument("--lag-days", type=int, default=20, help="publication lag allowance")
    parser.add_argument(
        "--stock-ratio",
        type=float,
        default=None,
        help="stock share of net assets; read from the fund when omitted",
    )
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
