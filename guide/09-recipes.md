# 09 实战配方

常见场景的完整写法。

> 标注「示意」的片段里有 `upsert`、`load_codes_from_db` 这类**你自己的存储层函数**——
> 库不碰数据库，这些要你自己实现。其余的可以直接跑。

---

## 1. 每天刷新品种库（存储层需自备）

```python
import asyncio
from dataclasses import dataclass

from quotestack import AssetClass, Market, MarketData


@dataclass
class Change:
    inserted: set[str]
    delisted: set[str]


async def diff_universe(
    client: MarketData,
    stored: set[str],
) -> Change:
    """对比线上列表与本地库，返回差异。"""
    seen: set[str] = set()
    async for batch in client.iter_instruments(AssetClass.STOCK, Market.CN):
        for item in batch:
            seen.add(item.code)
            upsert(item)

    return Change(inserted=seen - stored, delisted=stored - seen)


async def main() -> None:
    stored = load_codes_from_db()
    async with MarketData() as client:
        change = await diff_universe(client, stored)

    print(f"新增 {len(change.inserted)}，退市 {len(change.delisted)}")
    # 退市品种建议标记而不是删除——历史持仓还引用着它
    mark_delisted(change.delisted)
```

---

## 2. 盯一批自选，失败不影响整体

```python
import asyncio
from quotestack import AssetClass, Market, MarketData

WATCHLIST = [
    ("600519", AssetClass.STOCK, Market.CN),
    ("000001", AssetClass.STOCK, Market.CN),
    ("AAPL", AssetClass.STOCK, Market.US),
    ("510010", AssetClass.FUND, Market.CN),
]


async def poll(client: MarketData) -> None:
    results = await client.quote_many(WATCHLIST)

    for result in results:
        if result.ok:
            q = result.quote
            print(f"{q.instrument_id:<20} {q.price:>10} {q.currency} {q.change_pct:+.2f}%")
        else:
            print(f"{'?':<20} 失败: {result.error}")


async def main() -> None:
    async with MarketData() as client:
        while True:
            await poll(client)
            await asyncio.sleep(30)
```

**每 50 只一批、每个市场一批**，30 秒轮询毫无压力。

---

## 3. 基金自选：净值 + 估值 + 持仓

```python
async def fund_dashboard(client: MarketData, code: str) -> None:
    profile = await client.profile(code)
    nav = await client.nav(code, limit=2)
    estimate = await client.estimate(code)

    print(f"{code}  {profile.fund_type}  {profile.scale}")

    if len(nav) >= 2:
        latest, previous = nav[-1], nav[-2]
        change = (float(latest.nav) / float(previous.nav) - 1) * 100
        print(f"  昨日净值 {latest.nav}（{change:+.2f}%）")

    if estimate.change_pct is None:
        print(f"  今日估算：算不出来（{estimate.explanation}）")
    else:
        print(f"  今日估算 {estimate.change_pct:+.2f}%")

    holdings = await client.holdings(code, limit=1)
    if holdings:
        top = holdings[0]
        print(f"  {top.quarter} 前三大：")
        for holding in top.holdings[:3]:
            print(f"    {holding.name} {holding.weight}%")
```

---

## 4. 校验估值是否可信再展示

```python
async def safe_estimate(client: MarketData, code: str) -> float | None:
    estimate = await client.estimate(code)

    # 没有数字
    if estimate.change_pct is None:
        return None

    # 覆盖太低，说明大半仓位没算进去
    if estimate.coverage is None or estimate.coverage < 0.5:
        return None

    # 基准里有认不出的成分，说明公式可能套错了
    assumption = estimate.benchmark_assumption
    if assumption and assumption.unclassified:
        return None

    return estimate.change_pct
```

三个门槛：**有数字 / 覆盖够 / 成分认得全**。

---

## 5. 计算组合市值

```python
from decimal import Decimal

async def portfolio_value(
    client: MarketData,
    positions: list[tuple[str, Decimal]],   # (代码, 份额)
) -> Decimal:
    items = [(code, AssetClass.STOCK, Market.CN) for code, _ in positions]
    results = await client.quote_many(items)

    total = Decimal(0)
    for (code, shares), result in zip(positions, results):
        if not result.ok:
            print(f"{code} 取价失败，跳过")
            continue
        total += shares * Decimal(result.quote.price)

    return total
```

**全程 `Decimal`**——用 `float` 累加几百只票，误差会肉眼可见。

---

## 6. 服务端：调长 TTL 而不是自己写缓存

库自带缓存，但如果你要做跨进程共享：

```python
from fastapi import FastAPI, Request

app = FastAPI()


@app.on_event("startup")
async def startup() -> None:
    app.state.client = MarketData(ttl={"QUOTE": 60})   # 报价缓存 60 秒


@app.get("/quote/{code}")
async def quote(code: str, request: Request) -> dict:
    client = request.app.state.client
    q = await client.quote(code)
    return {"code": code, "price": q.price, "pct": q.change_pct}
```

**把 TTL 调长，比自己写缓存简单**——库内部已经处理了刷新、降级、单飞。

---

## 7. 多市场组合：A股 + 美股（按汇率折算）

```python
from decimal import Decimal

async def total_in_cny(client: MarketData, holdings: dict[str, Decimal]) -> Decimal:
    fx = await client.fx("USD", "CNY")
    usd_rate = Decimal(fx.rate)

    total = Decimal(0)
    for code, market, shares in [
        ("600519", Market.CN, holdings.get("600519", Decimal(0))),
        ("AAPL", Market.US, holdings.get("AAPL", Decimal(0))),
    ]:
        quote = await client.quote(code, AssetClass.STOCK, market)
        value = shares * Decimal(quote.price)
        if market is Market.US:
            value *= usd_rate
        total += value

    return total
```

---

## 8. 定时任务：每天 9 点刷新

```python
import asyncio
from datetime import datetime, time


async def daily_at(target: time, job) -> None:
    while True:
        now = datetime.now()
        run_at = datetime.combine(now.date(), target)
        if run_at <= now:
            run_at = run_at.replace(day=now.day) + __import__("datetime").timedelta(days=1)
        await asyncio.sleep((run_at - now).total_seconds())
        await job()
```

或者直接用系统 cron：

```cron
0 9 * * * cd /path/to/quotestack && .venv/bin/python scripts/refresh.py
```

---

## 别这么写

| 反例 | 问题 |
|---|---|
| `float(quote.price) * shares` | 金额用浮点，累计误差 |
| `estimate.change_pct or 0` | 未知变持平 |
| `for _ in range(10): retry(quote)` | `NOT_FOUND` 重试也没用 |
| 自己 `asyncio.gather` 并发 100 个 | 绕不过令牌桶，只是把等待排成队 |
| 忽略 `quote.stale` | 拿旧价做高频决策 |
| `try/except` 包整个 `quote_many` | 一条失败丢掉整批结果 |
