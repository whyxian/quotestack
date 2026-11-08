# 12 速查

默认值、参数、缓存策略、字段类型。写代码时对着查。

---

## 缓存默认值

| 能力 | 默认 TTL | 最旧容忍（max_stale） |
|---|---|---|
| `QUOTE` 报价 | **30 秒** | 1 天 |
| `ESTIMATE` 估值 | **30 秒** | 5 分钟 |
| `HISTORY` K 线 | 1 小时 | 不限 |
| `FX` 汇率 | 1 小时 | 7 天 |
| `NAV` 净值 | 6 小时 | 7 天 |
| `BENCHMARK` 基准曲线 | 6 小时 | 7 天 |
| `PROFILE` 画像 | 1 天 | 7 天 |
| `HOLDINGS` 持仓 | **永不过期** | 不限 |
| `RESOLVE` 标识解析 | 7 天 | 30 天 |

`HOLDINGS` 永不过期是因为**季报是历史数据，不会变**。

**最旧容忍**指上游挂掉时还能拿多旧的缓存。超过就报错，不会拿一个月前的价格冒充现价。

### 改默认值

```python
from quotestack import MarketData
from quotestack.models import Capability

client = MarketData(ttl={Capability.QUOTE: 60, Capability.ESTIMATE: 15})
```

key 是 `Capability` 枚举，不是字符串。

### 单次覆盖

```python
client.quote("600519", max_age=0)      # 强制回源
client.quote("600519", max_age=300)    # 5 分钟内的缓存都行
```

---

## 方法参数

### `quote`

```text
quote(code, asset_class=STOCK, market=CN, *, max_age=None) -> Quote
```

### `quote_many`

```text
quote_many(items: list[tuple[str, AssetClass, Market]]) -> list[QuoteResult]
```

返回**等长同序**，逐条判断 `result.ok`。

### `history`

```text
history(code, asset_class=STOCK, market=CN, *,
        interval=Interval.D1, adjust=Adjust.QFQ,
        limit=250, max_age=None) -> list[Bar]
```

| 参数 | 可选值 |
|---|---|
| `interval` | `M1` `M5` `M15` `M30` `M60` `D1` `W1` `MO1` |
| `adjust` | `QFQ`（默认）`HFQ` `NONE` |

### `nav`

```text
nav(code, asset_class=FUND, market=CN, *, limit=250, max_age=None) -> list[NavPoint]
```

### `profile`

```text
profile(code, asset_class=FUND, market=CN, *, max_age=None) -> Profile
```

### `holdings`

```text
holdings(code, asset_class=FUND, market=CN, *,
         before=None, limit=4) -> list[QuarterHoldings]
```

| 参数 | 说明 |
|---|---|
| `limit` | **季度数**，不是股票数 |
| `before` | 排他游标，如 `"2025Q4"` |

### `benchmark`

```text
benchmark(code, asset_class=FUND, market=CN, *,
          start=None, end=None) -> BenchmarkCurve
```

### `estimate`

```text
estimate(code, asset_class=FUND, market=CN) -> Estimate
```

### `fx`

```text
fx(base: str, quote: str) -> FxRate
```

支持：`USD` `CNY` `HKD` `EUR` `JPY` `GBP`。

### `iter_instruments`

```text
iter_instruments(asset_class, market, *,
                 listed=None, page_size=100,
                 tradable_only=True) -> AsyncIterator[list[InstrumentSummary]]
```

| 参数 | 说明 |
|---|---|
| `listed` | `True` 只场内 / `False` 只场外 / `None` 两者 |
| `page_size` | 上限 100，传更大也只会返回 100 |
| `tradable_only` | 美股跳过无价格的权证、优先股 |

---

## 字段类型

| 字段 | 类型 | 说明 |
|---|---|---|
| `price` `change` `open` `high` `low` `close` | `str` | 金额一律字符串 |
| `volume` `amount` | `str` | 同上 |
| `nav` `rate` | `str` | 同上 |
| `change_pct` | `float \| None` | 百分数，`0.07` = 0.07% |
| `coverage` | `float` | 0–1 |
| `date` | `date` | 交易日，无时区 |
| `time` | `str \| None` | `'14:55'`，日线为 `None` |
| `ts` | `datetime` | 带时区 |
| `stale` | `bool` | 是否来自过期缓存 |

---

## 枚举值

**`AssetClass`**：`STOCK` `FUND` `CRYPTO`

**`Market`**：`CN` `US` `CRYPTO`

**`Capability`**（10 个）：`RESOLVE` `QUOTE` `HISTORY` `NAV` `PROFILE`
`HOLDINGS` `BENCHMARK` `ESTIMATE` `FX` `LIST`

**`FundClass`**（7 个）：`EQUITY` `HYBRID` `BOND` `MONEY` `FOF` `REITS` `OTHER`

**`EstimateBasis`**（值是小写）：`index` `holdings` `none`

**`ComponentKind`**：`EQUITY` `NON_EQUITY` `UNKNOWN`

---

## 错误码

| `code` | HTTP | 重试 |
|---|---|---|
| `INVALID_ARGUMENT` | 400 | ❌ |
| `NOT_FOUND` | 404 | ❌ |
| `AMBIGUOUS` | 409 | ❌ |
| `DELISTED` | 410 | ❌ |
| `UNSUPPORTED` | 422 | ❌ |
| `RATE_LIMITED` | 429 | ⏳ 退避 |
| `UNAVAILABLE` | 502 | ✅ |
| `EMPTY_RESPONSE` | 502 | ❌ |
| `SCHEMA_CHANGED` | 502 | ❌ 该告警 |
| `UNAUTHORIZED` | 502 | ❌ |
| `TIMEOUT` | 504 | ✅ |
| `CLIENT_BROKEN` | 503 | ❌ 该升级 |

另有 `UPSTREAM_ERROR` 作为基类，一般不单独出现。

---

## 能力对照

| 能力 | 东财 | 腾讯 | 天天基金 | Binance | 东财外汇 |
|---|---|---|---|---|---|
| `QUOTE` | ✅ | ✅ | — | — | — |
| `HISTORY` | ✅ | — | — | — | — |
| `NAV` | — | — | ✅ | — | — |
| `PROFILE` | — | — | ✅ | — | — |
| `HOLDINGS` | — | — | ✅ | — | — |
| `BENCHMARK` | — | — | — | — | — |
| `ESTIMATE` | — | — | ✅ | — | — |
| `FX` | — | — | — | — | ✅ |
| `LIST` | ✅ | — | ✅ | ✅ | — |

`RESOLVE` 由规则引擎完成，不依赖任何源。
`BENCHMARK` 也是**没有任何源声明**的能力——曲线由客户端按成分合成，不是某个源直接给的。
