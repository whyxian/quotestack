"""Command line interface.

Four commands, standard library only. Runs the async client in-process.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from quotestack.client import MarketData
from quotestack.errors import MarketDataError
from quotestack.models import (
    Adjust,
    AssetClass,
    Bar,
    Estimate,
    Instrument,
    Interval,
    Market,
    Quote,
)

__all__ = ["main"]

_SEPARATOR = "-" * 29


def main(argv: list[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments to parse. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_dispatch(args))
    except MarketDataError as exc:
        _write_error(exc)
        return 1
    except KeyboardInterrupt:
        return 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quotestack",
        description="Multi-source market data on the command line.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    quote = sub.add_parser("quote", help="show the latest price")
    _add_instrument_args(quote)

    resolve_cmd = sub.add_parser("resolve", help="resolve a code to source identifiers")
    _add_instrument_args(resolve_cmd)

    health = sub.add_parser("health", help="show source and cache state")
    health.add_argument("--json", action="store_true", dest="as_json")

    estimate = sub.add_parser("estimate", help="estimate a fund's intraday change")
    _add_instrument_args(estimate, default_class=AssetClass.FUND)

    history = sub.add_parser("history", help="show historical bars")
    _add_instrument_args(history)
    history.add_argument(
        "--interval", default=Interval.D1.value, choices=[i.value for i in Interval]
    )
    history.add_argument("--adjust", default=Adjust.QFQ.value, choices=[a.value for a in Adjust])
    history.add_argument("--limit", type=int, default=10)

    return parser


def _add_instrument_args(
    parser: argparse.ArgumentParser,
    *,
    default_class: AssetClass = AssetClass.STOCK,
) -> None:
    parser.add_argument("code", help="instrument code, e.g. 600519")
    parser.add_argument(
        "--asset-class",
        default=default_class.value,
        choices=[a.value for a in AssetClass],
        dest="asset_class",
    )
    parser.add_argument(
        "--market",
        default=Market.CN.value,
        choices=[m.value for m in Market],
    )
    parser.add_argument("--json", action="store_true", dest="as_json")


async def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "health":
        async with MarketData() as client:
            _emit_health(client.health(), as_json=getattr(args, "as_json", False))
        return 0

    async with MarketData() as client:
        if args.command == "estimate":
            result = await client.estimate(
                args.code,
                AssetClass(args.asset_class),
                Market(args.market),
            )
            _emit_estimate(result, as_json=args.as_json)
            return 0

        if args.command == "resolve":
            instrument = client.resolve(
                args.code,
                AssetClass(args.asset_class),
                Market(args.market),
            )
            _emit_instrument(instrument, as_json=args.as_json)
            return 0

        if args.command == "quote":
            quote = await client.quote(
                args.code,
                AssetClass(args.asset_class),
                Market(args.market),
            )
            _emit_quote(quote, as_json=args.as_json)
            return 0

        bars = await client.history(
            args.code,
            AssetClass(args.asset_class),
            Market(args.market),
            interval=Interval(args.interval),
            adjust=Adjust(args.adjust),
            limit=args.limit,
        )
        _emit_history(bars, args.code, as_json=args.as_json)
        return 0


def _emit_instrument(instrument: Instrument, *, as_json: bool) -> None:
    if as_json:
        _write_json(
            {
                "id": instrument.id,
                "code": instrument.code,
                "asset_class": instrument.asset_class.value,
                "market": instrument.market.value,
                "currency": instrument.currency,
                "source_name": instrument.source_name,
                "confidence": instrument.confidence.value,
                "aliases": dict(instrument.aliases),
                "capabilities": sorted(c.value for c in instrument.capabilities),
            }
        )
        return

    aliases = ", ".join(f"{k}={v}" for k, v in instrument.aliases.items()) or "-"
    caps = ", ".join(sorted(c.value for c in instrument.capabilities)) or "-"
    print(instrument.id)
    print(_SEPARATOR)
    print(f"  code        {instrument.code}")
    print(f"  class       {instrument.asset_class.value}")
    print(f"  market      {instrument.market.value}")
    print(f"  currency    {instrument.currency}")
    print(f"  confidence  {instrument.confidence.value}")
    print(f"  aliases     {aliases}")
    print(f"  abilities   {caps}")


def _emit_estimate(estimate: Estimate, *, as_json: bool) -> None:
    if as_json:
        _write_json(
            {
                "change_pct": estimate.change_pct,
                "basis": estimate.basis.value,
                "coverage": estimate.coverage,
                "as_of": estimate.as_of.isoformat() if estimate.as_of else None,
                "explanation": estimate.explanation,
                "benchmark_assumption": (
                    {
                        "equity": list(estimate.benchmark_assumption.equity),
                        "non_equity": list(estimate.benchmark_assumption.non_equity),
                        "unclassified": list(estimate.benchmark_assumption.unclassified),
                    }
                    if estimate.benchmark_assumption
                    else None
                ),
            }
        )
        return

    change = "算不出来" if estimate.change_pct is None else f"{estimate.change_pct:+.2f}%"
    coverage = "-" if estimate.coverage is None else f"{estimate.coverage:.1%}"
    print(f"estimate  {change}")
    print(_SEPARATOR)
    print(f"  basis     {estimate.basis.value}")
    print(f"  coverage  {coverage}")
    print(f"  reason    {estimate.explanation}")


def _emit_health(payload: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        _write_json(payload)
        return

    print(f"status   {payload.get('status')}")
    print(f"proxy    {payload.get('proxy') or 'none'}")
    print(_SEPARATOR)

    sources = payload.get("sources")
    if isinstance(sources, dict):
        for name, info in sources.items():
            state = info.get("state") if isinstance(info, dict) else info
            print(f"source   {name}  {state}")

    cache = payload.get("cache")
    entries = cache.get("entries", 0) if isinstance(cache, dict) else 0
    print(f"cache    {entries} entries")


def _emit_quote(quote: Quote, *, as_json: bool) -> None:
    if as_json:
        _write_json(_quote_to_dict(quote))
        return

    stamp = quote.ts.strftime("%Y-%m-%d %H:%M:%S")
    change = quote.change if quote.change is not None else "-"
    pct = f"{quote.change_pct:+.2f}%" if quote.change_pct is not None else "-"
    flag = "  [stale]" if quote.stale else ""
    print(quote.instrument_id)
    print(_SEPARATOR)
    print(f"  price   {quote.price} {quote.currency}   {pct}")
    print(f"  change  {change}")
    print(f"  source  {quote.source}")
    print(f"  time    {stamp}{flag}")


def _emit_history(bars: list[Bar], code: str, *, as_json: bool) -> None:
    if as_json:
        _write_json([_bar_to_dict(bar) for bar in bars])
        return

    print(f"{code}  {len(bars)} bars")
    print(_SEPARATOR)
    print(f"  {'date':<12}{'open':>10}{'high':>10}{'low':>10}{'close':>10}")
    for bar in bars:
        label = f"{bar.date} {bar.time}" if bar.time else str(bar.date)
        print(f"  {label:<12}{bar.open:>10}{bar.high:>10}{bar.low:>10}{bar.close:>10}")


def _quote_to_dict(quote: Quote) -> dict[str, Any]:
    return {
        "instrument_id": quote.instrument_id,
        "price": quote.price,
        "currency": quote.currency,
        "change": quote.change,
        "change_pct": quote.change_pct,
        "source": quote.source,
        "ts": quote.ts.isoformat(),
        "stale": quote.stale,
    }


def _bar_to_dict(bar: Bar) -> dict[str, Any]:
    return {
        "date": bar.date.isoformat(),
        "time": bar.time,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "amount": bar.amount,
    }


def _write_json(payload: object) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


def _write_error(exc: MarketDataError) -> None:
    sys.stderr.write(f"error [{exc.code}]: {exc.message}\n")
    details = {k: v for k, v in exc.context.items() if v is not None}
    if details:
        sys.stderr.write(f"  {json.dumps(details, ensure_ascii=False, default=str)}\n")


if __name__ == "__main__":
    raise SystemExit(main())
