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

```bash
pip install quotestack
```

## Usage

```python
from quotestack import MarketData

async with MarketData() as client:
    instrument = await client.resolve("600519", "STOCK", "CN")
    quote = await client.quote(instrument)
    print(quote.price, quote.currency)
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
