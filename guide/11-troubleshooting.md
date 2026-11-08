# 11 排障

数据不对、结果为空、卡住了——先看这里。

---

## 第一步：看数据是从哪来的

每份行情都带 `source` 和 `stale`：

```python
quote = client.quote("600519")
print(quote.source)    # 'eastmoney' 主源 / 'tencent' 兜底源
print(quote.stale)     # True 表示这是缓存值
```

| 现象 | 含义 | 下一步 |
|---|---|---|
| `source='tencent'` | 东财当时不可用，换源了 | 数据仍然可信，但可能延迟 |
| `stale=True` | 上游失败，用了容忍范围内的旧值 | 看下面「怎么知道缓存命中了」 |
| `status='HISTORICAL'` | 不在交易时段，拿到的是收盘数据 | 正常 |

---

## 怎么知道发生了什么

库**不配置日志 handler**——它只发事件，怎么输出由你决定。

### 打开日志

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
```

然后就能看到每次请求、每次缓存命中：

```
2026-11-08 12:30:01 quotestack DEBUG cache_lookup key=quote:CN:STOCK:600519 result=HIT
2026-11-08 12:30:02 quotestack DEBUG fetch key=quote:CN:STOCK:600519 source=eastmoney
2026-11-08 12:30:03 quotestack WARNING source_failed source=tencent reason=TIMEOUT
```

**只开你自己的 logger，别全局 DEBUG**：

```python
logging.getLogger("quotestack").setLevel(logging.DEBUG)
```

### 看健康状态

```python
print(client.health())
```

```python
{
    "status": "ok",                       # ok / degraded
    "sources": {
        "eastmoney": {
            "state": "ok",                 # ok / cooling
            "cooldown_remaining": 0.0,
            "timeout": 5.0,
            "capabilities": ["HISTORY", "LIST", "QUOTE"],
        },
        ...
    },
    "cache": {"entries": 128},
}
```

**`state='cooling'` 说明这个源刚失败过，正在冷却**——它会自动恢复，不用干预。

### 看缓存

```python
print(client.cache_stats())
# {'entries': 128}
```

只有**条目数**。想知道某次调用是缓存还是回源，看返回对象上的 `stale` 和 `source`：

```python
quote = client.quote("600519")
print(quote.stale, quote.source)      # False eastmoney
```

`stale=True` 就是用了缓存里的旧值。

---

## 常见症状

### 「查不到数据」但代码没错

先分清三种情况：

```python
from quotestack.errors import MarketDataError

try:
    quote = client.quote("560000")
except MarketDataError as exc:
    print(exc.code)
```

| `code` | 含义 | 怎么办 |
|---|---|---|
| `UNSUPPORTED` | 这个标的没这个能力 | 看 `exc.context["available"]` |
| `NOT_FOUND` | 代码不存在 | 检查代码 |
| `UNAVAILABLE` | 所有源都没给数据 | 看 `exc.context["attempts"]`，可能上游真没有 |

**场外基金查报价是最常见的误区**：

```python
client.quote("022430")     # ❌ 场外基金没有盘中价格
client.nav("022430")       # ✅ 只有每日净值
```

### 「估值是 None」

不是 bug，是**输入不够**。`explanation` 会说原因：

```python
estimate = client.estimate("166002")
print(estimate.explanation)
```

| 说明里的关键词 | 原因 |
|---|---|
| 输入不可用 | 画像或持仓拉取失败 |
| 资产配置 | 该基金没有资产配置数据 |
| 没有可用的指数行情 | 跟踪指数查不到 |
| 季度持仓 | 该基金没有季报数据 |

**`None` 表示未知，不是 0。** 别用 `or 0` 兜底。

### 「突然变慢了」

多半是触发了限流。看：

```python
print(client.health()["sources"]["eastmoney"])
```

`cooldown_remaining > 0` 就是在冷却。

**为什么会触发**：东财对基金页面限制 4 次/秒，库内部已限流到这个值。你自己再并发
调用多个客户端，就等于绕过了限流。

```python
# ❌ 开了 5 个客户端并发
clients = [MarketData() for _ in range(5)]

# ✅ 一个客户端，它自己会复用连接
client = MarketData()
```

### 「中文乱码」

腾讯源返回 GBK。库内部已经处理。如果你看到乱码，**说明你绕过了库直接请求了源**——
那不是这个库的问题。

### 「结果和官网不一致」

先确认三件事：

1. **是不是复权**。默认前复权，历史价格和官网的"不复权"数字不同
2. **是不是缓存**。传 `max_age=0` 强制刷新
3. **是不是延迟**。`quote.ts` 告诉你数据时刻，不是你的请求时刻

```python
quote = client.quote("600519", max_age=0)
print(quote.ts)      # 2026-11-06T16:11:39+08:00
```

### 「涨停/跌停价格不对」

A股的涨跌停是**交易所规则**，不是数据源给的。库不做这个计算——它只给成交价。

---

## 上报问题前

准备好这三样，能省一轮往返：

```python
import quotestack

print(quotestack.__version__)          # 版本

try:
    client.quote("600519")
except MarketDataError as exc:
    print(exc.code, exc.context)       # 错误码 + 结构化上下文
```

再加一段最小复现代码。**不要贴整个 traceback 却不贴入参。**
