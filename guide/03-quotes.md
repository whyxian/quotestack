# 03 行情

报价、K 线、批量、汇率。

---

## 单个报价

```python
quote = await client.quote("600519", AssetClass.STOCK, Market.CN)
```

| 字段 | 值（示例） | 说明 |
|---|---|---|
| `instrument_id` | `'CN:STOCK:600519'` | 定位到的标的 |
| `price` | `'1453.00'` | **字符串**，见[概念](02-concepts.md#3-价格是字符串不是数字) |
| `currency` | `'CNY'` | 计价货币 |
| `change` | `'1.00'` | 涨跌额，字符串 |
| `change_pct` | `0.07` | 涨跌幅百分数（`0.07` = 0.07%） |
| `source` | `'eastmoney'` | 实际给你数据的源 |
| `ts` | `2026-11-06T16:11:39+08:00` | 带时区的观测时刻 |
| `status` | `'REALTIME'` | `REALTIME` / `HISTORICAL` / `UNAVAILABLE` |
| `stale` | `False` | 是否来自过期缓存 |

**`source` 值得看**：它告诉你这次是主源还是兜底源给的。做数据质量统计时有用。

### 美股

```python
quote = await client.quote("AAPL", AssetClass.STOCK, Market.US)
# price='342.370'  currency='USD'
```

注意价格是 3 位小数——美股和 ETF 都是 3 位，A股是 2 位。**库已经处理好了**，
你拿到的字符串直接可用。

---

## K 线

```python
bars = await client.history("600519", limit=20)
```

| 字段 | 值（示例） |
|---|---|
| `date` | `2026-11-06` |
| `time` | `None`（日线）/ `'14:55'`（分钟线） |
| `open` `high` `low` `close` | `'1450.00'` 等，字符串 |
| `volume` | `'42848'` |
| `amount` | `'6199528289'` 或 `None` |

**按日期升序返回**，最后一根是最新的。

### 周期与复权

```python
from quotestack import Adjust, Interval

# 分钟线
bars = await client.history("600519", interval=Interval.M5, limit=48)

# 周线、月线
await client.history("600519", interval=Interval.W1)
await client.history("600519", interval=Interval.MO1)

# 不复权（默认是前复权）
await client.history("600519", adjust=Adjust.NONE)
```

| `Interval` | 含义 |
|---|---|
| `M1` `M5` `M15` `M30` `M60` | 1/5/15/30/60 分钟 |
| `D1` | 日线（默认） |
| `W1` `MO1` | 周线、月线 |

| `Adjust` | 含义 |
|---|---|
| `QFQ` | 前复权（默认），当前价格真实，历史价格调整 |
| `HFQ` | 后复权 |
| `NONE` | 不复权，历史价格是当时的实际成交价 |

> **做回测用 `QFQ`**，否则除权日会出现假的跳空。

### 历史能取多深

东财给的深度，实测：

| 市场 | 深度 |
|---|---|
| A股 | 6,000+ 根日线（2001 年起） |
| 美股 | 10,000 根（1987 年起） |

`limit` 只是截取最近 N 根，不限制能取多远。

---

## 批量报价

一次问多只票，**一次网络请求**（内部按 50 个一批）：

```python
from quotestack import AssetClass, Market

items = [
    ("600519", AssetClass.STOCK, Market.CN),
    ("000001", AssetClass.STOCK, Market.CN),
    ("AAPL", AssetClass.STOCK, Market.US),
    ("022430", AssetClass.FUND, Market.CN),   # 这个会失败
]

results = await client.quote_many(items)
```

**返回列表和请求等长同序**，逐条判断：

```python
for item, result in zip(items, results):
    if result.ok:
        print(item[0], result.quote.price)
    else:
        print(item[0], "失败:", result.error)
```

```
600519 1453.00
000001 11.24
AAPL 342.370
022430 失败: UNSUPPORTED: CN:FUND:022430 has no quote data
```

> **一条失败不会拖垮整批。** 别用 try/except 包整个 `quote_many`，
> 要么全成功要么全失败的设计早就被否掉了。

---

## 汇率

```python
rate = await client.fx("USD", "CNY")
```

| 字段 | 值（示例） | 说明 |
|---|---|---|
| `base` | `'USD'` | 源货币 |
| `quote` | `'CNY'` | 目标货币 |
| `rate` | `'6.6738'` | **字符串**，1 USD 兑多少 CNY |
| `derived` | `True` | 是否为交叉换算得出 |

支持的货币：`USD` `CNY` `HKD` `EUR` `JPY` `GBP`。`CNY` 实际按离岸人民币（CNH）报价。

```python
await client.fx("CNY", "USD")    # '0.14983967'
await client.fx("USD", "JPY")    # '158.4895'
await client.fx("USD", "USD")    # '1'，不请求网络
```

换算金额时，自己用 `Decimal` 算：

```python
from decimal import Decimal

usd = Decimal("100")
cny = usd * Decimal(rate.rate)
```

---

## 什么时候会失败

| 情况 | 异常 | 怎么办 |
|---|---|---|
| 代码不存在 | `NotFoundError` | 检查代码 |
| 该标的没这个能力 | `UnsupportedError` | 看 `exc.context["available"]` |
| 所有源都挂了 | `UnavailableError` | 重试，或看 `exc.context["attempts"]` |
| 频率超限 | `RateLimitedError` | 退避后重试 |

完整清单见 [08 错误处理](08-errors.md)。
