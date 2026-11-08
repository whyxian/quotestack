"""Estimate a fund's intraday change and show the reasoning.

Run with::

    uv run python examples/02_fund_estimate.py
"""

from __future__ import annotations

import asyncio

from quotestack import MarketData


async def main() -> None:
    async with MarketData() as client:
        profile = await client.profile("022430")
        print(f"{profile.fund_type}  {profile.scale}")
        if profile.benchmark:
            print(f"基准：{profile.benchmark.text}")

        estimate = await client.estimate("022430")
        if estimate.change_pct is None:
            print(f"\n算不出来：{estimate.explanation}")
        else:
            print(f"\n估算 {estimate.change_pct:+.2f}%  （basis={estimate.basis.value}）")
            print(f"  {estimate.explanation}")


if __name__ == "__main__":
    asyncio.run(main())
