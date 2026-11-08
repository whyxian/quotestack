"""Walk a market listing and report what a local database would need to change.

The library only streams; persisting and diffing stay with the caller. This
script shows the shape of that job without touching a database.

Run with::

    uv run python examples/03_refresh_universe.py
"""

from __future__ import annotations

import asyncio
import datetime as dt

from quotestack import AssetClass, Market, MarketData


async def main() -> None:
    seen: set[str] = set()
    newest: list[tuple[str, str, dt.date]] = []

    async with MarketData() as client:
        async for batch in client.iter_instruments(AssetClass.STOCK, Market.CN):
            for item in batch:
                seen.add(item.code)
                if item.listing_date is not None:
                    newest.append((item.code, item.name, item.listing_date))
            if len(seen) >= 600:  # keep the example short
                break

    print(f"扫到 {len(seen)} 只")
    newest.sort(key=lambda row: row[2], reverse=True)
    print("最近上市的 5 只:")
    for code, name, listed in newest[:5]:
        print(f"  {code}  {name}  {listed}")

    # A real job would compare `seen` against its own table here:
    #   inserted = seen - stored
    #   delisted = stored - seen


if __name__ == "__main__":
    asyncio.run(main())
