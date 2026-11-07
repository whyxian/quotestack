# quotestack

Multi-source market data adapter for **A-shares, US stocks, mutual funds and crypto**.

> **Status: pre-alpha.** API is not stable yet. Do not use in production.

## Why

Getting consistent market data across asset classes is repetitive work: every source
returns a different shape, fails differently, and needs its own caching and fallback.
quotestack collapses that into one set of calls.

See [docs/design/00-why.md](docs/design/00-why.md) for the full rationale and a
comparison with akshare / tushare / yfinance.

## Install

> Not yet published to PyPI. Until M8 completes, install from source.

```bash
git clone <repo> && cd quotestack
uv sync --extra dev
```

## Usage

```python
import asyncio

from quotestack import AssetClass, Market, MarketData


async def main() -> None:
    async with MarketData() as client:
        quote = await client.quote("600519", AssetClass.STOCK, Market.CN)
        print(quote.price, quote.currency)

        bars = await client.history("600519", limit=5)
        print(len(bars), "bars")


asyncio.run(main())
```

## Scope

| Supported | Not supported |
|---|---|
| A-share stocks and ETFs | Convertible bonds, futures, options |
| US stocks | Minute-level long history |
| Open-end mutual funds (NAV, profile, holdings, estimate) | Trading / order placement |
| Crypto (spot) | Data warehousing |

## Documentation

- [Roadmap](docs/ROADMAP.md)
- [Design decisions](docs/design/README.md)
- [Glossary](docs/design/16-glossary.md)

## License

MIT
