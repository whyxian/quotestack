# 04 基金

场外基金是这个库最有特色的部分。它没有交易所，所以数据形态和股票完全不同。

---

## 先分清两种基金

| | 场内（ETF / LOF） | 场外（开放式基金） |
|---|---|---|
| 有代码 | 6 位，如 `510010` | 6 位，如 `022430` |
| 有盘中价格 | ✅ | ❌ |
| 有 K 线 | ✅ | ❌ |
| 有每日净值 | ✅ | ✅ |
| **怎么买** | 股票账户 | 基金账户 / 第三方平台 |

**同一个库，两种用法**：

```python
# 场内：当股票用
await client.quote("510010", AssetClass.FUND, Market.CN)
await client.history("510010", AssetClass.FUND, Market.CN, limit=10)

# 场外：只能查净值
await client.nav("022430")      # ✅
await client.quote("022430")    # ❌ UnsupportedError
```

> 场外基金的代码前缀**不可靠**：`166002` 是场外基金但前缀是 `16`（通常意味着深市 LOF）。
> 库已经处理了这个情况——所有基金都给了 `NAV` 能力。

---

## 净值

```python
points = await client.nav("022430", limit=30)
```

| 字段 | 值（示例） |
|---|---|
| `date` | `2026-11-06` |
| `nav` | `'1.0690'`（字符串） |

按日期升序，最后一条是最新净值。

```python
latest = points[-1]
print(f"{latest.date} 净值 {latest.nav}")

# 算一段区间的收益
first, last = points[0], points[-1]
change = (float(last.nav) / float(first.nav) - 1) * 100
print(f"{change:+.2f}%")
```

**净值是 T-1 的**——今天查到的通常是昨天收盘后公布的净值。场外基金没有盘中实时净值。

---

## 画像

一次拿到基金的基本信息：

```python
profile = await client.profile("022430")
```

| 字段 | 值（示例） | 说明 |
|---|---|---|
| `fund_type` | `'指数型-股票'` | 源给的原始分类 |
| `fund_class` | `EQUITY` | 归一化的七分类，见下 |
| `tracking_index` | `'中证A500指数'` | 跟踪标的；主动基金为 `None` |
| `benchmark` | 见下 | 业绩比较基准（已解析成结构） |
| `company` | `'华夏基金'` | 管理人 |
| `manager` | `'李俊'` | 基金经理 |
| `custodian` | `'招商银行'` | 托管人 |
| `scale` | `'31.40亿元'` | 净资产规模 |
| `inception_date` | `2024-10-31` | 成立日 |
| `as_of` | `2026-09-30` | 规模对应的报告期 |
| `partial` | `False` | 是否有字段缺失 |
| `missing` | `()` | 缺了哪些 |

### 七分类

东财给 33 种原始标签，太细了没法做逻辑判断。归一化成七类：

| `fund_class` | 涵盖 | 含义 |
|---|---|---|
| `EQUITY` | 股票型、指数型-股票、混合型-偏股、QDII 股票 | 以股票为主 |
| `HYBRID` | 混合型-灵活/平衡/绝对收益 | **仓位浮动，要看实际持仓** |
| `BOND` | 债券型、指数型-固收、混合型-偏债 | 以债券为主 |
| `MONEY` | 货币型 | 净值恒为 1.0 |
| `FOF` | FOF | 投其他基金 |
| `REITS` | Reits | 不动产 |
| `OTHER` | 其他 / 未识别 | 保守处理 |

**未知标签一律归 `OTHER`，不猜。** 猜错分类会导致算错估值。

### 基准已经解析好了

```python
benchmark = profile.benchmark
print(benchmark.text)
# '中证A500指数收益率*95%+人民币活期存款税后利率*5%'

for component in benchmark.components:
    print(component.name, component.weight, component.kind)
# 中证A500指数收益率 95.0 EQUITY
# 人民币活期存款税后利率 5.0 NON_EQUITY

print(benchmark.coverage)   # 1.0，权重合计
```

`kind` 分三类：`EQUITY`（权益）、`NON_EQUITY`（债券/存款/现金）、`UNKNOWN`（没识别出来）。

**`coverage < 1` 说明基准权重没写全**，或者有解析不了的成分。

---

## 季度持仓

```python
quarters = await client.holdings("166002", limit=2)
```

```python
for quarter in quarters:
    print(quarter.quarter, quarter.as_of)
    for holding in quarter.holdings:
        print(f"  {holding.code} {holding.name} {holding.weight}%")
```

```
2026Q3 2026-09-30
  300308 中际旭创 4.66%
  600519 贵州茅台 3.87%
  ...
2026Q2 2026-06-30
  300308 中际旭创 8.45%
  ...
```

| 参数 | 说明 |
|---|---|
| `limit` | **季度数**，不是股票数。默认 4 |
| `before` | 排他游标，只返回更早的季度，如 `before="2025Q4"` |

翻页：

```python
page1 = await client.holdings("166002", limit=4)      # 2026Q3..2025Q4
page2 = await client.holdings(
    "166002", before=page1[-1].quarter, limit=4
)                                                      # 2025Q3..2024Q4
```

> **持仓是季报数据，有 1–3 个月延迟。** 现在是 11 月，最新能拿到的是 9 月 30 日的持仓。

`weight` 是**占净值比例**（百分数）。前十大合计通常只有 30–70%。

### 货币基金返回空

```python
await client.holdings("000198")   # []，货币基金不持有股票
```

这是合法的空答案，不是错误。

---

## 基准曲线

把业绩基准的各个成分指数按权重合成一条曲线：

```python
curve = await client.benchmark("110011", start=date(2026, 1, 1))
```

| 字段 | 说明 |
|---|---|
| `effective_start` | 所有可用成分都有数据的第一天 |
| `components_used` | 实际参与合成的成分 |
| `components_dropped` | **取不到数据的成分名** |
| `coverage` | 可用权重 / 100 |
| `series` | `[{date, value}]`，首日归一为 1 |

```python
print(curve.coverage, curve.components_dropped)
# 0.8 ['中债总指数收益率']
```

东财拿不到中债系列指数，所以 `110011` 的曲线只有 80% 的权重——**它被明确告诉你了**，
而不是悄悄按 0 填充把曲线拉低。

```python
for point in curve.series[-3:]:
    print(point.date, round(point.value, 4))
```

---

## 下一步

想算「今天这只基金大概涨多少」，看 [05 估值](05-estimate.md)。
