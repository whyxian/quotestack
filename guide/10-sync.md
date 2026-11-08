# 10 同步用法

不想写 async？有同步封装。

---

## 什么时候用

| 场景 | 建议 |
|---|---|
| Web 服务、并发抓多只 | **async**（`MarketData`） |
| 脚本、定时任务、Jupyter | 同步（`SyncMarketData`） |
| 已有同步代码不想改 | 同步 |

两者是**同一套实现**：同步封装内部起一个后台事件循环，把你的调用转过去等结果。

---

## 怎么用

```python
from quotestack.sync import SyncMarketData

with SyncMarketData() as client:
    quote = client.quote("600519")
    print(quote.price, quote.currency)      # 1453.00 CNY
```

**注意导入路径**：`SyncMarketData` 不在顶层，是 `quotestack.sync`。

> 为什么？顶层保持精简，只导出数据模型和异步客户端。同步封装是可选入口。

### 方法一一对应

| 异步 | 同步 |
|---|---|
| `await client.quote(...)` | `client.quote(...)` |
| `await client.nav(...)` | `client.nav(...)` |
| `await client.profile(...)` | `client.profile(...)` |
| `await client.holdings(...)` | `client.holdings(...)` |
| `await client.benchmark(...)` | `client.benchmark(...)` |
| `await client.estimate(...)` | `client.estimate(...)` |
| `await client.fx(...)` | `client.fx(...)` |
| `await client.quote_many(...)` | `client.quote_many(...)` |
| `await client.history(...)` | `client.history(...)` |
| `async for batch in client.iter_instruments(...)` | `for batch in client.iter_instruments(...)` |

**参数完全一样**，去掉 `await` 而已。

### 流式接口也是同步迭代

异步版是 `async for`，同步版是普通 `for`，每轮拿一批：

```python
from quotestack import AssetClass, Market
from quotestack.sync import SyncMarketData

with SyncMarketData() as client:
    seen = 0
    for batch in client.iter_instruments(AssetClass.STOCK, Market.CN):
        seen += len(batch)
    print(seen)      # 5927
```

内存占用一样是分批的——不会一次性拉全量。

---

## 完整例子

```python
from quotestack import AssetClass, Market
from quotestack.sync import SyncMarketData

with SyncMarketData() as client:
    # 行情
    quote = client.quote("600519")
    bars = client.history("600519", limit=20)

    # 基金
    profile = client.profile("022430")
    nav = client.nav("022430", limit=30)
    holdings = client.holdings("166002", limit=4)
    estimate = client.estimate("022430")

    print(f"{profile.fund_type}  {profile.scale}")
    print(f"净值 {nav[-1].nav}  估算 {estimate.change_pct:+.2f}%")

    # 汇率
    rate = client.fx("USD", "CNY")
```

---

## 必须用 `with`

```python
with SyncMarketData() as client:      # ✅ 用完自动关
    ...

client = SyncMarketData()             # ⚠️ 会泄漏后台线程
client.quote("600519")
```

**忘了 `with` 会留下一个后台线程和一条 httpx 连接池。** 长时间运行的脚本会累积。

非 `with` 用法要手动关：

```python
client = SyncMarketData()
try:
    quote = client.quote("600519")
finally:
    client.close()
```

---

## 不要混用

```python
# ❌ 在 async 函数里用同步封装
async def handler():
    with SyncMarketData() as client:
        return client.quote("600519")      # 会阻塞整个事件循环
```

同步封装内部起**自己的**事件循环。在 async 上下文里用它，会把当前循环卡住。

| 你在哪 | 用什么 |
|---|---|
| `async def` 里 | `MarketData` + `await` |
| 普通函数里 | `SyncMarketData` |

---

## 性能差别

同步版**没有并发优势**：一次调用一次往返。

```python
# 同步：三次往返，串行
for code in ("600519", "000001", "601398"):
    quotes.append(client.quote(code))
```

要并发就用异步：

```python
# 异步：可以同时发
results = await asyncio.gather(*(client.quote(c) for c in codes))
```

或者用批量接口，一次请求拿多只：

```python
results = client.quote_many([(c, AssetClass.STOCK, Market.CN) for c in codes])
```

**批量接口在两种模式下都比循环快**——它内部按 50 个一批，一次网络请求拿一批。
