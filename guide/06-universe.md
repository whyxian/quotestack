# 06 全市场列表

拉出「这个市场有哪些标的」，用来维护你自己的品种库。

---

## 为什么要这个

市场天天变：新股上市、基金清盘、币种上新。手工维护的品种表很快就会过期。

库提供**数据流**，你负责落库和比对：

```python
async for batch in client.iter_instruments(AssetClass.STOCK, Market.CN):
    for item in batch:
        ...   # 你的数据库
```

> **库不存数据、不做 diff**。它只负责"拿到最新的全量"。

---

## 实测规模

| 市场 | 数量 |
|---|---|
| A股（含北交所） | **5,927** |
| 场内基金（ETF/LOF） | **1,805** |
| 场外基金 | **28,305** |
| 美股（有价格的） | **12,826** |
| 加密（USDT 交易对） | **518** |
| **合计** | **~49,381** |

**耗时由限流决定，不是由数据量决定。** 每页 100 条、每页一个请求，而客户端限流
4 次/秒，所以全量约 `49,381 ÷ 100 ÷ 4 ≈ 2 分钟`。

实测 A股 5,927 只（60 页）用时 **15 秒**，与这个算式一致。


---

## 每个标的带什么

`InstrumentSummary`：

| 字段 | A股 | 场内基金 | 场外基金 | 美股 | 加密 |
|---|---|---|---|---|---|
| `code` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `name` | ✅ | ✅ | ✅ | ✅ | ✅（币种名） |
| `listing_date` | ✅ | ✅ | ❌ | ✅ | ❌ |
| `board` | ✅ | ✅ | ❌ | ✅ | ❌ |
| `industry` | ✅ | ⚠️ | ❌ | ✅ | ❌ |
| `fund_type` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `fund_class` | ❌ | ❌ | ✅ | ❌ | ❌ |

```python
async for batch in client.iter_instruments(AssetClass.STOCK, Market.CN):
    first = batch[0]
    print(first.code, first.name, first.board, first.listing_date)
    break
```

```
689009 九号公司-WD 沪主板 2020-10-29
```

**`board` 的值**：`沪主板` / `创业板` / `科创板` / `北交所` / `深主板` / `NASDAQ` / `NYSE` / `AMEX`。

**列表里没有价格、市值、市盈率**——那些属于行情，会过期。见
[02 概念](02-concepts.md)。

---

## 场外基金的特殊参数

场外基金和场内基金共用 `(FUND, CN)`，用 `listed` 区分：

```python
# 只场外
async for batch in client.iter_instruments(AssetClass.FUND, Market.CN, listed=False):
    ...

# 只场内
async for batch in client.iter_instruments(AssetClass.FUND, Market.CN, listed=True):
    ...

# 两者都要（会依次走东财和天天基金）
async for batch in client.iter_instruments(AssetClass.FUND, Market.CN):
    ...
```

**场外基金列表自带分类**，省掉逐只查询：

```python
async for batch in client.iter_instruments(AssetClass.FUND, Market.CN, listed=False):
    for fund in batch[:3]:
        print(fund.code, fund.name, fund.fund_type, fund.fund_class.value)
    break
```

```
000001 华夏成长混合 混合型-灵活 HYBRID
000002 华夏成长混合(后端) 混合型-灵活 HYBRID
000003 中海可转债债券A 债券型-混合二级 BOND
```

---

## 美股的两个开关

```python
async for batch in client.iter_instruments(
    AssetClass.STOCK, Market.US, tradable_only=True
):
    ...
```

`tradable_only=True`（默认）会跳过**没有价格**的标的——权证、优先股、停牌票。
美股全量 13,892 条，过滤后 12,826 条。

> 东财对无价格的标的返回字符串 `"-"` 而不是数字 0。库已经处理。

想拿全量（包括权证）：

```python
async for batch in client.iter_instruments(
    AssetClass.STOCK, Market.US, tradable_only=False
):
    ...
```

---

## 加密范围

默认只给 **USDT 计价且正在交易** 的 518 个交易对：

```python
async for batch in client.iter_instruments(AssetClass.CRYPTO, Market.CRYPTO):
    ...
```

要其他计价货币，直接用底层源（暂未暴露到 `iter_instruments` 参数）。

---

## 刷新自己的品种库

下面是**结构示意**——`upsert` / `stored_codes` / `mark_delisted` 是你的存储层，
库不提供，需要你自己实现：

```python
import asyncio
from quotestack import AssetClass, Market, MarketData


async def refresh() -> None:
    seen: set[str] = set()

    async with MarketData() as client:
        async for batch in client.iter_instruments(AssetClass.STOCK, Market.CN):
            for item in batch:
                upsert(item)
                seen.add(item.code)

    # 三个 diff
    inserted = seen - stored_codes()        # 新增
    delisted = stored_codes() - seen         # 退市
    # 改名：code 相同、name 不同

    mark_delisted(delisted)
    print(f"新增 {len(inserted)}，退市 {len(delisted)}")


async def main() -> None:
    await refresh()


asyncio.run(main())
```

### 三个判定

| 判定 | 方法 |
|---|---|
| **新增** | 列表有、库里没有 |
| **退市** | 库里有、列表没有 |
| **改名** | code 相同、name 不同 |

**列表只返回在市品种**，所以"库里多出来的"就是退市的——这是判定退市的唯一方式。

> **怎么处理退市品种是你的决定。** 直接删会丢失历史数据关联，
> 一般标 `delisted` 保留更安全。

---

## 性能建议

全量扫 5,927 只 A股 = 60 个分页请求。几个建议：

| 建议 | 原因 |
|---|---|
| 每天跑一次就够 | 品种变化不是分钟级的 |
| 用 `page_size=100` | 服务端上限就是 100，传更大也只会返回 100 |
| 不要并发多市场 | 共享同一个限流桶，并发只会互相等 |

库内部已经做了限流（4 次/秒），**不要自己再套一层并发**——反而更慢。
