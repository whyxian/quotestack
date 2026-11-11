# quotestack

**A股 / 美股 / 场外基金 / 加密** 的多源行情适配层。

> **状态：pre-alpha。** API 尚未稳定，请勿用于生产。

四类资产的数据源各不相同：返回结构不一样、失败方式不一样、缓存和兜底要各写一遍。
quotestack 把这些收敛成一套调用。

**完整使用文档见 [guide/](guide/README.md)**（中文，10 篇，自成一体）。

---

## 安装

```bash
git clone https://github.com/whyxian/quotestack.git && cd quotestack
uv sync --extra dev                  # 当库用
uv sync --extra dev --extra server   # 需要 HTTP 服务时
```

暂未发布到 PyPI。

---

## 快速开始

```python
import asyncio

from quotestack import AssetClass, Market, MarketData


async def main() -> None:
    async with MarketData() as client:
        quote = await client.quote("600519", AssetClass.STOCK, Market.CN)
        print(quote.price, quote.currency)      # 1453.00 CNY


asyncio.run(main())
```

基金才是这个库的重点：

```python
async with MarketData() as client:
    profile = await client.profile("022430")            # 类型、基准、经理、规模
    holdings = await client.holdings("166002", limit=4)  # 季度前十大
    estimate = await client.estimate("166002")           # 盘中估值

    if estimate.change_pct is None:                      # 算不出来，不是 0
        print(estimate.explanation)
```

---

## 覆盖范围

| | 支持 | 不支持 |
|---|---|---|
| **A股** | 股票与场内基金、完整历史、全市场列表 | 可转债、期货、期权 |
| **美股** | 报价与日线、全市场列表 | 长周期分钟线 |
| **场外基金** | 净值、画像、基准、季度持仓、盘中估值 | 需要交易账户的操作 |
| **加密** | Binance 现货交易对（仅列表） | 报价、K 线、衍生品 |

数据源：东方财富（主）、腾讯（实时兜底）、天天基金（场外基金）、
Binance Vision（加密）、东财外汇（汇率）。换源与降级自动完成。

---

## 作为服务运行

```bash
uv run quotestack-server
curl 'http://127.0.0.1:8000/v1/quote?code=600519'
```

所有接口统一 `{data, error}` 响应，Prometheus 指标在 `/metrics`。

---

## 文档

**想用它** → [guide/](guide/README.md)。自成一体，可单独托管，
不回头引用仓库里的其他文档。

**想改它** → 仓库里的 `docs/` 是工程文档：为什么这么设计、代码怎么组织、实测数据是什么。
写给维护者看的。

| 我想…… | 看这里 |
|---|---|
| 学会用它 | [guide/](guide/README.md) |
| 参与开发 | [CONTRIBUTING.md](CONTRIBUTING.md) |
| 版本变更 | [CHANGELOG.md](CHANGELOG.md) |

估值准确度不是宣称，是实测：主动基金相关系数 0.958、平均绝对误差 0.41pp；
ETF 联接基金 1.000 / 0.02pp。

---

## 许可

MIT
