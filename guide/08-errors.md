# 08 错误处理

出了错该不该重试、该不该换方案——这一篇说清楚。

---

## 所有错误都是同一个父类

```python
from quotestack.errors import MarketDataError

try:
    await client.quote("999999")
except MarketDataError as exc:
    print(exc.code)     # 'NOT_FOUND'
    print(exc.message)  # 'eastmoney returned no data for ...'
    print(exc.context)  # {'missing': ['1.999999']}
```

| 属性 | 稳定性 | 用途 |
|---|---|---|
| `code` | **稳定**，适合 `if`/`switch` | 程序判断 |
| `message` | 会改，人话 | 日志、给用户看 |
| `context` | 结构化 dict | 排查、上报 |

---

## 完整清单

| 错误 | `code` | 该重试吗 | 该换源吗 | 含义 |
|---|---|---|---|---|
| `InvalidArgumentError` | `INVALID_ARGUMENT` | ❌ | ❌ | 参数不对，重试也没用 |
| `NotFoundError` | `NOT_FOUND` | ❌ | ❌ | 代码不存在 |
| `AmbiguousError` | `AMBIGUOUS` | ❌ | ❌ | 多个候选，要你指定 |
| `DelistedError` | `DELISTED` | ❌ | ❌ | 已退市 |
| `UnsupportedError` | `UNSUPPORTED` | ❌ | ❌ | 该标的没这个能力 |
| `EmptyResponseError` | `EMPTY_RESPONSE` | ❌ | ✅ | 源有响应但没这条数据 |
| `SchemaChangedError` | `SCHEMA_CHANGED` | ❌ | ✅ | 源改了结构，**要告警** |
| `UnauthorizedError` | `UNAUTHORIZED` | ❌ | ✅ | 源要鉴权 |
| `RateLimitedError` | `RATE_LIMITED` | ⏳ | ✅ | 频率超了，**退避后重试** |
| `UnavailableError` | `UNAVAILABLE` | ✅ | — | 所有源都失败 |
| `TimeoutError` | `TIMEOUT` | ✅ | — | 超时 |
| `ClientBrokenError` | `CLIENT_BROKEN` | ❌ | — | 所有源结构都变了，**该升级库** |

> **换源这件事库已经做了。** 表里的"该换源"是给自定义源链路用的；
> 直接用 `MarketData` 的话，你只会看到最终的 `UnavailableError`。

---

## 实用的分类

```python
from quotestack.errors import MarketDataError

RETRYABLE = {"UNAVAILABLE", "TIMEOUT"}


async def fetch_with_retry(client, code, attempts: int = 3):
    for attempt in range(attempts):
        try:
            return await client.quote(code)
        except MarketDataError as exc:
            if exc.code not in RETRYABLE or attempt == attempts - 1:
                raise
            await asyncio.sleep(2**attempt)     # 1s, 2s, 4s
```

**`RATE_LIMITED` 单独处理**——它不是"挂了"，是"慢一点"：

```python
except MarketDataError as exc:
    if exc.code == "RATE_LIMITED":
        await asyncio.sleep(5)
        continue
```

---

## 四个最容易踩的

### 1. 把 `UnsupportedError` 当成故障

```python
# ❌ 重试 10 次也是同样的结果
for _ in range(10):
    try:
        await client.quote("022430", AssetClass.FUND, Market.CN)
    except MarketDataError:
        continue
```

场外基金**没有盘中价格**，这是定义。看它有什么能力：

```python
except UnsupportedError as exc:
    print(exc.context["available"])
    # ['BENCHMARK', 'ESTIMATE', 'HOLDINGS', 'NAV', 'PROFILE']
```

### 2. 把 `change_pct=None` 当成 0

```python
# ❌ 未知变成了"持平"
print(f"{estimate.change_pct or 0:+.2f}%")

# ✅
print("未知" if estimate.change_pct is None else f"{estimate.change_pct:+.2f}%")
```

### 3. 忽略 `stale`

```python
quote = await client.quote("600519")
if quote.stale:
    # 这个价格可能是几分钟前的
    log.warning("使用缓存价格，上游暂时不可用")
```

对高频场景，`stale=True` 的数据可能不适合做决策。

### 4. 对 `SchemaChangedError` 无动于衷

```python
except SchemaChangedError:
    # 这不是偶发故障，是上游改了接口
    # 库需要更新，应该报警而不是重试
    alert("quotestack 需要升级")
    raise
```

---

## 批量操作里怎么处理

`quote_many` **不抛异常**，逐条返回：

```python
results = await client.quote_many(items)

ok = [r for r in results if r.ok]
failed = [(r.instrument.code, r.error) for r in results if not r.ok]
```

```
失败: [('022430', 'UNSUPPORTED: CN:FUND:022430 has no quote data')]
```

**别用 try/except 包整个批量调用**——那样一条失败会丢掉全部结果。

---

## 日志里该记什么

```python
except MarketDataError as exc:
    logger.warning(
        "market data failed",
        extra={
            "code": exc.code,
            "instrument": exc.context.get("instrument"),
            "attempts": exc.context.get("attempts"),
        },
    )
```

**记 `code` 和 `context`，别记 `message`**——后者会变，聚合不了。

`UnavailableError` 的 `context["attempts"]` 会告诉你每个源为什么失败：

```python
print(exc.context["attempts"])
# [{'source': 'eastmoney', 'reason': 'EMPTY_RESPONSE'},
#  {'source': 'tencent', 'reason': 'cooldown', 'remaining': 21.4}]
```

---

## 上游限流：514

东财对基金页面有防爬：

```
4 次/秒  → 正常
5 次/秒  → HTTP 514，之后同连接持续被拒
```

库已经限流到 4/秒。**如果你自己并发调库，反而会触发**——不要套并发。

看到 `RATE_LIMITED` 说明你绕过了库的限流（比如自己起了多个客户端）。
