# quotestack

Multi-source market data adapter for **A-shares, US stocks, mutual funds and crypto**.

> **Status: pre-alpha.** API is not stable yet. Do not use in production.

Getting consistent market data across four asset classes is repetitive work: every
source returns a different shape, fails differently, and needs its own caching,
fallback and rate limiting. quotestack collapses that into one set of calls.

`pip install` is not available yet — see [Install](#install).

## Install

```bash
git clone https://github.com/whyxian/quotestack.git && cd quotestack
uv sync --extra dev            # 作为库使用
uv sync --extra dev --extra server   # 需要 HTTP 服务时
```

## Usage

```python
import asyncio

from quotestack import AssetClass, Market, MarketData


async def main() -> None:
    async with MarketData() as client:
        quote = await client.quote("600519", AssetClass.STOCK, Market.CN)
        print(quote.price, quote.currency)          # 1453.00 CNY

        bars = await client.history("600519", limit=5)
        print(len(bars), "bars")


asyncio.run(main())
```

Funds carry the interesting capabilities:

```python
async with MarketData() as client:
    profile = await client.profile("022430")        # 类型、基准、经理、规模
    quarters = await client.holdings("166002", limit=4)   # 季度前十大
    estimate = await client.estimate("166002")      # 盘中估算

    if estimate.change_pct is None:                 # 算不出来，不是 0
        print(estimate.explanation)
```

A universe listing refreshes a local instrument table:

```python
async for batch in client.iter_instruments(AssetClass.STOCK, Market.CN):
    ...  # 库只给数据流；落库与 diff 由调用方负责
```

## What it covers

| | Supported | Not supported |
|---|---|---|
| **A-shares** | stocks and ETFs, full history, listings | convertible bonds, futures, options |
| **US stocks** | quotes and daily bars, listings | minute-level long history |
| **Mutual funds** | NAV, profile, benchmark, holdings, intraday estimate | anything requiring a trading account |
| **Crypto** | Binance spot universe | derivatives |

Five sources back this: Eastmoney (primary), Tencent (realtime fallback),
Tiantian Fund (open-end funds), Binance Vision (crypto), Eastmoney FX (rates).
Routing and fallback are automatic; see [03-sources](docs/design/03-sources.md).

## Run as a service

```bash
uv run quotestack-server            # 127.0.0.1:8000
curl 'http://127.0.0.1:8000/v1/quote?code=600519'
```

Twelve endpoints, unified `{data, error}` envelope, Prometheus metrics at `/metrics`.
The contract is generated from code: [`docs/api/openapi.yaml`](docs/api/openapi.yaml).

## Documentation

Two separate bodies of documentation, for two different readers.

### If you want to use it

Start at the [**guide**](guide/README.md) — 中文，十篇，自成一体，可单独托管。
It never links back into this repository, so it works as a standalone site.

| Topic | File |
|---|---|
| 安装、概念、行情、基金、估值、服务、错误、配方 | [guide/](guide/README.md) |
| Runnable examples | [examples/](examples/) |
| OpenAPI spec | [docs/api](docs/api/README.md) |

### If you want to change it

Everything under `docs/` is engineering documentation: why decisions were made,
how the code is laid out, what the measurements were. It is written for whoever
maintains this repository.

| Topic | File |
|---|---|
| Setup, workflow, conventions | [CONTRIBUTING](CONTRIBUTING.md) |
| Module structure and data flow | [ARCHITECTURE](docs/harness/ARCHITECTURE.md) |
| Commented code map (中文) | [CODE_MAP_ZH](docs/harness/CODE_MAP_ZH.md) |
| Design decisions and why | [docs/design](docs/design/README.md) |
| API surface and field semantics | [05-api](docs/design/05-api.md) |
| Measured evidence behind every claim | [11-evidence](docs/design/11-evidence.md) |

## Project status

Built in milestones, tracked in [docs/ROADMAP.md](docs/ROADMAP.md):

```
M0 scaffold    M1 MVP        M2 resilience   M3 multi-source
M4 funds       M5 estimate   M6 service      M7 quality     ✅
M8 release     M9 integration
```

Estimate accuracy is not a claim, it is measured — see
[11-evidence](docs/design/11-evidence.md#46-估值回测m5-6): correlation 0.958 and
mean absolute error 0.41pp on an active fund, 0.02pp on an ETF feeder.

## License

MIT
