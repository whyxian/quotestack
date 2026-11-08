# quotestack 使用指南

> **pre-alpha：API 仍可能变动。** 生产使用前请锁定版本。

面向**使用这个库的人**：想拿行情、查基金、算估值，或者把数据接到自己的服务里。

> **本指南自成一体**——不依赖仓库里的其他文档，可以单独托管成一站点。
>
> 文中代码分两种：**`examples/` 下的三个脚本可直接运行**；正文里的片段是示意，
> REPL 风格（`await client.quote(...)` 直接写在顶层），需要放进 `async def` 里。
> 所有输出都是实际跑出来的，日期标注在文中。

---

## 这是什么

用一套调用方式，取 **A股 / 美股 / 场外基金 / 加密** 的数据。

```python
from quotestack import AssetClass, Market, MarketData

async with MarketData() as client:
    quote = await client.quote("600519", AssetClass.STOCK, Market.CN)
    print(quote.price)        # 1453.00
```

同一个 `quote`，四类资产通用：

```python
await client.quote("600519", AssetClass.STOCK, Market.CN)      # 贵州茅台
await client.quote("AAPL",   AssetClass.STOCK, Market.US)      # 苹果
await client.quote("510010", AssetClass.FUND,  Market.CN)      # 场内 ETF
```

行情源挂了会自动换源，数据过期会往缓存退，频率超了会限流——**这些都不用你写**。

---

## 五分钟上手

### 1. 安装

```bash
git clone https://github.com/whyxian/quotestack.git && cd quotestack
uv sync --extra dev
```

> 还没发到 PyPI，暂时从源码装。

### 2. 第一条查询

```python
import asyncio
from quotestack import AssetClass, Market, MarketData


async def main() -> None:
    async with MarketData() as client:
        quote = await client.quote("600519", AssetClass.STOCK, Market.CN)
        print(quote.price, quote.currency, f"{quote.change_pct:+.2f}%")


asyncio.run(main())
```

输出：

```
1453.00 CNY +0.07%
```

### 3. 换个资产试试

```python
# 场外基金没有价格，只有每日净值
points = await client.nav("022430", limit=5)

# 但基金能算盘中估值
estimate = await client.estimate("022430")
print(estimate.change_pct)   # -1.66
```

---

## 指南目录

按你手上的任务找：

| 我想…… | 看这篇 |
|---|---|
| 装好、跑起来 | [01 安装](01-install.md) |
| 搞懂 Instrument、Capability 这些词 | [02 核心概念](02-concepts.md) |
| 取报价、K 线、批量行情、汇率 | [03 行情](03-quotes.md) |
| 查基金净值、类型、持仓 | [04 基金](04-funds.md) |
| **算基金盘中估值** | [05 估值](05-estimate.md) |
| 拉全市场品种列表、维护自己的品种库 | [06 全市场列表](06-universe.md) |
| 起一个 HTTP 服务给别的系统调 | [07 服务化](07-service.md) |
| 出错了怎么处理、怎么重试 | [08 错误处理](08-errors.md) |
| 常见场景的完整写法 | [09 实战配方](09-recipes.md) |

---

## 不做什么

说清楚边界，省得你找了半天：

| 不做 | 原因 |
|---|---|
| 交易下单 | 只读数据，不碰账户 |
| 可转债、期货、期权 | 数据源覆盖不稳定 |
| 存储、回测框架、组合管理 | 库只提供数据流，你的业务你自己定 |
| 港股 | 暂未接入 |

---

## 关于语言

本指南用中文，因为这个库面向的市场是 A股和场外基金，读者主要是中文开发者。
代码注释和变量名仍是英文——那是给编译器和其他语言使用者看的。
