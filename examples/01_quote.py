"""Fetch a quote and a short price history.

Run with::

    uv run python examples/01_quote.py
"""

from __future__ import annotations

import asyncio

from quotestack import AssetClass, Market, MarketData


async def main() -> None:
    async with MarketData() as client:
        quote = await client.quote("600519", AssetClass.STOCK, Market.CN)
        print(f"{quote.instrument_id}  {quote.price} {quote.currency}  {quote.change_pct:+.2f}%")

        bars = await client.history("600519", limit=5)
        print(f"\n最近 {len(bars)} 个交易日:")
        for bar in bars:
            print(f"  {bar.date}  close {bar.close}")


if __name__ == "__main__":
    asyncio.run(main())
