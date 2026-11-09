# 接口与格式契约

> quotestack 设计决议 · 第 5 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：✅ 方法全部可用


## 接口清单

> 除 `resolve` 外均为 `async def`，调用需 `await`。`resolve` 只做字符串规则，是同步方法。
> 不写 async 的场景用 `from quotestack.sync import SyncMarketData`，详见 [运行时模型](13-runtime-model.md)。

凡是以标的为对象的方法，入参都是 `code` + `asset_class` + `market`——调用方**永远不持有 instrument**（见 7.3 一跳原则）。
> 例外：`quote_many` 收三元组列表，`fx` 收两个货币码，`iter_instruments` 收市场而非标的。

| # | 入口 | 状态 | 说明 |
|---|---|---|---|
| 1 | `resolve(code, asset_class, market)` | 🚧 M1 | 规则解析可用；`expected_name` 校验待做（M6 的 HTTP 参数） |
| 2 | `quote(code, asset_class, market)` | ✅ M1 | 实时价 |
| 3 | `quote_many(items)` | ✅ M3 | 批量报价，等长同序 |
| 4 | `history(code, asset_class, market, interval, adjust, limit)` | ✅ M1 | K 线 + 分钟线 |
| 5 | `nav(code, asset_class, market, limit)` | ✅ M3 | 净值序列 |
| 6 | `profile(code, asset_class, market)` | ✅ M4 | 静态画像 + 基准结构 |
| 7 | `holdings(code, asset_class, market, before, limit)` | ✅ M4 | 季度持仓分页 |
| 8 | `benchmark(code, asset_class, market, start, end)` | ✅ M4 | 基准加权曲线 |
| 9 | `estimate(code, asset_class, market)` | ✅ M5 | 估值（派生） |
| 10 | `fx(base, quote)` | ✅ M3 | 汇率 |
| 11 | `iter_instruments(asset_class, market, listed=None)` | ✅ M3.5 | 全市场列表 |

### 为什么没有独立的 minute 接口

`history` 的 `interval` 覆盖全部周期：

| interval | 含义 | TTL | 可回溯深度 |
|---|---|---|---|
| `1m` / `5m` / `15m` / `30m` / `60m` | 分钟线 | 60 秒 | 约 1 个月（1m 仅当天） |
| `1d` / `1w` / `1M` | 日 / 周 / 月 | 1 小时 | 全历史 |

底层是同一个东财接口（仅 `klt` 参数不同），拆成两个入口属于重复。TTL 差异在内部按 interval 归类，不体现在接口表面积上。

### `fx` 的币种与换算

**基准与交叉**

东财提供的是**货币对**报价（如 `133.USDCNH` = 美元兑离岸人民币），不是 USD 基准表。

```
1. 先构建 USD 基准表：USD→CNY、USD→HKD、USD→EUR …
2. 任意 base→quote 通过 USD 交叉：
   EUR→CNY = (USD→CNY) / (USD→EUR)
3. USD→X 直接使用源报价，不做交叉
```

**初始支持的币种**

| 币种 | 说明 |
|---|---|
| USD | 基准货币 |
| CNY | 在岸/离岸，取离岸 CNH 作为代理 |
| HKD | |
| EUR | |
| JPY | |
| GBP | |

**查不到时**

- 不猜、不近似、不返回 1
- 抛 `Unsupported`，message 指明缺哪个币种

**返回结构**

```json
{
  "base": "USD", "quote": "CNY", "rate": "7.1234",
  "source": "eastmoney", "as_of": "2026-11-07",
  "derived": false, "stale": false
}
```

| 字段 | 说明 |
|---|---|
| `rate` | 字符串，保留源精度 |
| `as_of` | 汇率日期，不是抓取时间 |
| `derived` | `true` 表示由 USD 交叉计算得出，非源直接报价 |

---

### `quote_many` 契约

```json
POST /v1/quotes:many
{ "items": [ { "code": "600519", "asset_class": "STOCK", "market": "CN" } ] }
```

返回**等长、同序、不丢项**：

```json
{
  "results": [
    { "ok": true,  "instrument": {}, "quote": {} },
    { "ok": false, "instrument": {}, "error": { "code": "UNSUPPORTED" } }
  ],
  "fetched_at": "2026-11-07T14:30:00+08:00"
}
```

规则：

1. 单条失败不拖垮整批
2. 内部按源分组，一次上游请求
3. 去重但保持等长
4. 上限 200 条，超出 422

#### 源在冷却期时的表达

冷却中的源直接跳过、自动试下一个。若全部源不可用，该条目返回 `ok: false`，**不新增错误类型**：

```json
{
  "ok": false,
  "instrument": { "id": "CN:STOCK:600519" },
  "error": {
    "code": "UNAVAILABLE",
    "message": "all sources unavailable",
    "detail": {
      "attempts": [
        { "source": "eastmoney", "reason": "cooldown", "until": "2026-11-07T20:45:10+08:00" },
        { "source": "tencent", "reason": "timeout", "elapsed_ms": 3000 }
      ]
    }
  }
}
```

冷却只是「暂时不可用」的一种原因，调用方处置方式相同（等待或降级），不必多一个类型。

### 为什么 holdings 与 profile 分开

| | `profile` | `holdings` |
|---|---|---|
| 数据形态 | 快照 | 时间序列 |
| 变化频率 | 季度 | 永不变 |
| 缓存 | 24h | 永久 |
| 分页 | 无 | 有 |

分页契约（排他游标 + 季度数）：

```json
{ "quarters": [...], "has_more": true, "next_before": "2026Q1" }
```

不传 `before` 返回最新 `limit` 个季度；`before` 为排他游标；`limit` 是**季度数**不是行数；到底时 `has_more=false`、`next_before=null`。排序固定倒序。详见 [基金能力](07-funds.md#51-分页契约)。

### HTTP 表面

#### 一跳原则

调用方**永远只传 `code + asset_class + market`**，解析在服务内部完成。

`instrument.id` 只出现在**响应**里，从不作为输入参数。理由：

1. `id` 只是 `code:class:market` 拼接的字符串，没有额外信息量
2. 服务端已缓存 resolve 结果，内部解析成本约等于一次字典查找
3. 少一个概念——调用方永远不需要知道 `CN:STOCK:000001` 这种东西存在

#### 为什么不用路径参数

代码存在跨类歧义：

```
000001 → 平安银行（STOCK）  或  华夏成长混合（FUND）
```

放在路径里（如 `/funds/000001/...`）服务无法判断意图。因此**统一用查询参数**，每次请求都带全三个字段。语义无歧义优先于 URL 美观。

#### 路由表

```
GET  /v1/resolve?code=&asset_class=&market=&expected_name=
GET  /v1/quote?code=&asset_class=&market=
POST /v1/quotes/batch
GET  /v1/history?code=&asset_class=&market=&interval=&adjust=&limit=
GET  /v1/nav?code=&asset_class=&market=&limit=
GET  /v1/profile?code=&asset_class=&market=
GET  /v1/holdings?code=&asset_class=&market=&before=&limit=
GET  /v1/benchmark?code=&asset_class=&market=&start=&end=
GET  /v1/estimate?code=&asset_class=&market=
GET  /v1/fx?base=&quote=
GET  /v1/healthz
```

路由与库方法基本一一对应；`quote` / `quote_many` 共用同一份取数逻辑。
> 具体数量见 [design/README](README.md) 的生成事实表。

#### 参数约定

| 项 | 决议 |
|---|---|
| 批量路径 | `/v1/quotes/batch`（不用 `:batch` 冒号风格，兼容网关） |
| 批量上限 | 200 条，超出 422 |
| 分页 | `before` 游标（如 `2025Q4`）+ `limit`，响应带 `has_more` / `next_before` |
| `adjust` | `none` / `qfq` / `hfq`，默认 `qfq` |
| 健康检查 | `/healthz` 返回源状态、代理档位、近期 `schema_changes` |
| 错误体 | 包在 `error` 字段内：`{ data: null, error: { code, message, detail } }` |

### 7.4 统一响应结构

成功与失败**形状一致**，调用方只需一条解析路径：

```json
// 成功（HTTP 200）
{ "data": { ... }, "error": null }

// 失败（HTTP 4xx / 5xx）
{
  "data": null,
  "error": {
    "code": "NOT_FOUND",
    "message": "instrument not found",
    "detail": { "code": "999999", "market": "CN" }
  }
}
```

**为什么保留 HTTP 状态码**：监控、重试、网关限流都依赖它。全部返回 200 会让这些能力失效——旧项目踩过这个坑。

**为什么还要 `error` 字段**：前端/Java 客户端用一个 `if (error != null)` 就能处理全部失败，不用同时判状态码和响应体。

### 7.5 全市场列表

列表不是"针对某个标的取数"，而是"给我一批标的"，因此单独一个入口：

```python
async for batch in client.iter_instruments(AssetClass.FUND, Market.CN, listed=False):
    ...  # batch: list[InstrumentSummary]
```

| 参数 | 说明 |
|---|---|
| `listed` | 基金专用：`True` 场内 / `False` 场外 / `None` 两者都要 |
| `page_size` | 每批条数 |
| `tradable_only` | 跳过无价格标的（过滤美股权证、停牌） |

`InstrumentSummary` 字段：

| 字段 | 必有 | 说明 |
|---|---|---|
| `code` `name` `asset_class` `market` `currency` | ✅ | 基础标识 |
| `listing_date` | ❌ | A股/美股有，基金/加密无 |
| `board` | ❌ | 主板/创业板/科创板/北交所/NASDAQ |
| `industry` | ❌ | 仅供参考，源会修订 |
| `fund_type` | ❌ | 场外基金原始分类，如 `混合型-灵活` |
| `fund_class` | ❌ | 由 `fund_type` 归一化的七分类 |

**列表不含行情字段**（价格、市值、市盈率），原因：

1. 列表缓存 24 小时，价格 30 秒就过期，一个对象两种时间尺度
2. 调用方看到 `price` 会误以为是最新的
3. 要价格应该调 `quote_many`

#### 基金分类（`FundClass`）

东财的 33 种原始标签折叠成七类，**逻辑判断用 `fund_class`，展示用 `fund_type`**：

| `FundClass` | 含义 | 估值处理 | 实测数量 |
|---|---|---|---|
| `EQUITY` | 股票型、指数型-股票、混合型-偏股、QDII 股票 | 走指数/持仓 | 13,413 |
| `HYBRID` | 混合型-灵活/平衡/绝对收益 | **需实测股票仓位** | 2,504 |
| `BOND` | 债券型、指数型-固收、混合型-偏债 | `basis="none"` | 9,690 |
| `MONEY` | 货币型 | 无可估值内容 | 977 |
| `FOF` | FOF | 暂不支持（M4 标 unsupported） | 1,409 |
| `REITS` | Reits | 暂不支持 | 103 |
| `OTHER` | 未知/其他 | 保守，不猜 | 209 |

**用户不需要提供这个字段**：列表里批量带回，单只基金查询时由基础信息接口返回（约 1 KB，与 `profile` 同一次请求）。

**这省掉了 10,667 次请求**——债券和货币基金本来就算不出股票指数估值。

**库只提供数据流，不负责落库**。增量与退市判定由调用方做：

| 判定 | 方法 |
|---|---|
| 新增 | 列表有、库里没有 |
| 退市 | 库里有、列表没有 |
| 改名 | code 相同、name 不同 |

### 7.6 接口明细

每个接口统一按下面三段写，顺序固定：

1. **参数**——公共参数见 7.5，这里只列额外的；没有额外参数时写「无」
2. **响应 `data`**——字段表，嵌套对象紧跟一张小表
3. **错误**——稳定错误码 + HTTP 状态

#### `GET /v1/resolve`

**参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `expected_name` | string | ❌ | — | 用于校验解析结果，名称差异过大则换候选（M6 实现） |

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 内部标识，`CN:STOCK:600519` |
| `code` | string | 规范化后的代码 |
| `asset_class` | enum | `STOCK` / `FUND` / `CRYPTO` |
| `market` | enum | `CN` / `US` / `CRYPTO` |
| `currency` | string | 计价货币 |
| `source_name` | string \| null | 源返回的名称，**非权威** |
| `confidence` | enum | `exact` / `inferred` / `partial` |
| `aliases` | object | 各源标识，`{"eastmoney":"1.600519"}` |
| `capabilities` | string[] | 该标的可用的能力 |

**错误**：`INVALID_ARGUMENT`(400)、`AMBIGUOUS`(409)、`NOT_FOUND`(404)

#### `GET /v1/quote`

**参数**：无。

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `instrument_id` | string | 内部标识 |
| `price` | string | 十进制字符串 |
| `currency` | string | 计价货币 |
| `change` | string \| null | 涨跌额 |
| `change_pct` | number \| null | 百分数，`-1.76` 表示 -1.76% |
| `source` | string | 实际提供数据的源 |
| `ts` | string | RFC3339 带偏移 |
| `status` | enum | `REALTIME` / `HISTORICAL` / `UNAVAILABLE` |
| `stale` | boolean | 是否来自过期缓存 |

**错误**：`UNSUPPORTED`(422)、`NOT_FOUND`(404)、`UPSTREAM_*`(502/504)

#### `POST /v1/quotes/batch`

**参数**：无，批量项放在请求体。

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `items` | array | ✅ | 上限 200 项 |
| `items[].code` | string | ✅ | 标的代码 |
| `items[].asset_class` | enum | ❌ | 默认 `STOCK` |
| `items[].market` | enum | ❌ | 默认 `CN` |

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `results` | array | **等长同序**，与请求一一对应 |
| `fetched_at` | string | 整批的抓取时刻 |

`results[]` 每项：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | boolean | 该项是否成功 |
| `instrument` | object \| null | 解析失败时为 `null` |
| `quote` | object \| null | 成功时存在 |
| `error` | string \| null | 失败原因，形如 `UNSUPPORTED: …` |

**错误**：`INVALID_ARGUMENT`(400，超过 200 项)

#### `GET /v1/history`

**参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `interval` | enum | ❌ | `1d` | `1m`–`60m` / `1d` / `1w` / `1M` |
| `adjust` | enum | ❌ | `qfq` | `none` / `qfq` / `hfq` |
| `limit` | int | ❌ | 250 | 从最新往前数 |

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `bars` | array | 按日期升序 |
| `interval` | enum | 回显实际使用的周期 |
| `adjust` | enum | 回显实际使用的复权 |
| `source` | string | 实际提供数据的源 |
| `fetched_at` | string | 抓取时刻 |

`bars[]` 每根：

| 字段 | 类型 | 说明 |
|---|---|---|
| `date` | string | 交易日，无时区 |
| `time` | string \| null | 分钟线为 `HH:MM`，日线为 `null` |
| `open` `high` `low` `close` | string | 价格，十进制字符串 |
| `volume` | string | 成交量 |
| `amount` | string \| null | 成交额 |

**错误**：`UNSUPPORTED`(422，场外基金无 K 线)、`EMPTY_RESPONSE`(404)

#### `GET /v1/nav`

**参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | int | ❌ | 250 | 返回点数，从最新往前数 |

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `points` | array | 净值序列，按日期升序 |
| `latest` | object | 最新一个点 |
| `source` | string | 实际提供数据的源 |
| `fetched_at` | string | 抓取时刻 |

`points[]` 与 `latest` 结构相同：

| 字段 | 类型 | 说明 |
|---|---|---|
| `date` | string | 净值日期 |
| `nav` | string | 单位净值，十进制字符串 |

**错误**：`UNSUPPORTED`(422，非基金标的)

#### `GET /v1/profile`

**参数**：无。

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `fund_type` | string \| null | 源分类，如 `混合型-偏股` |
| `fund_class` | enum \| null | 归一化分类，见 7.5 |
| `tracking_index` | string \| null | 跟踪标的，非指数基金为 `null` |
| `benchmark` | object \| null | 业绩比较基准，见下表 |
| `company` | string \| null | 基金管理人 |
| `manager` | string \| null | 基金经理 |
| `custodian` | string \| null | 托管人 |
| `scale` | string \| null | 净资产规模，如 `80.39亿元` |
| `inception_date` | string \| null | 成立日期 |
| `as_of` | string \| null | 规模与持仓的报告期 |
| `partial` | boolean | 是否有字段缺失 |
| `missing` | string[] | 缺失字段名 |

`benchmark` 内部：

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | string | 原始基准字符串 |
| `components` | array | `[{name, weight, kind}]`，`weight` 是百分数 |
| `coverage` | number | 权重合计 / 100，小于 1 说明权重不全 |

**错误**：`UNSUPPORTED`(422)

#### `GET /v1/holdings`

**参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `before` | string | ❌ | — | 排他游标，如 `2025Q4`，只返回更早的季度 |
| `limit` | int | ❌ | 4 | **季度数**，不是股票数 |

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `quarters` | array | 按季度倒序 |
| `has_more` | boolean | 是否还有更早的季度 |
| `next_before` | string \| null | 下一页游标，没有更多时为 `null` |

`quarters[]` 每个季度：

| 字段 | 类型 | 说明 |
|---|---|---|
| `quarter` | string | 如 `2026Q3` |
| `as_of` | string | 季度末日期 |
| `holdings` | array | `[{code, name, weight}]`，`weight` 是占净值百分数 |

**错误**：`UNSUPPORTED`(422)

#### `GET /v1/benchmark`

**参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `start` | string | ❌ | 一年前 | `YYYY-MM-DD` |
| `end` | string | ❌ | 今天 | `YYYY-MM-DD` |

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `effective_start` | string \| null | 所有可用成分都有数据的第一天 |
| `components_used` | array | 参与合成的成分，`[{name, weight, kind}]` |
| `components_dropped` | string[] | 取不到历史的成分名，如中债系列 |
| `coverage` | number | 可用权重 / 100 |
| `series` | array | `[{date, value}]`，首日归一为 1 |

**错误**：`UNSUPPORTED`(422，无基准)、`NOT_FOUND`(404)

#### `GET /v1/estimate`

**参数**：无。

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `change_pct` | number \| null | 估算涨跌；`basis=none` 时为 `null`，货币基金为 `0` |
| `basis` | enum | `index` / `holdings` / `none` |
| `coverage` | number \| null | 估算覆盖的仓位比例 |
| `as_of` | string \| null | 行情观测时刻 |
| `explanation` | string | 说明这次怎么算的 |
| `benchmark_assumption` | object \| null | `{equity, non_equity, unclassified}`，各为成分名数组 |

**输入过期或缺失时返回 `basis="none"` 与 `change_pct=null`，仍是 HTTP 200。**

**错误**：`UNSUPPORTED`(422，非基金)

#### `GET /v1/fx`

**参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `base` | string | ✅ | — | 源货币，ISO 代码 |
| `quote` | string | ✅ | — | 目标货币，ISO 代码 |

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `base` | string | 源货币 |
| `quote` | string | 目标货币 |
| `rate` | string | 汇率，十进制字符串 |
| `source` | string | 实际提供数据的源 |
| `as_of` | string | 观测时刻 |
| `derived` | boolean | 是否由交叉换算得到 |

**错误**：`UNSUPPORTED`(422，不支持的币种)

#### `GET /v1/instruments`

**参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `asset_class` | enum | ✅ | — | 要枚举的市场类别 |
| `market` | enum | ✅ | — | 交易场所 |
| `listed` | boolean | ❌ | — | 基金专用：`true` 场内 / `false` 场外 / 不传两者都要 |
| `page` | int | ❌ | 1 | 页码，从 1 开始 |
| `page_size` | int | ❌ | 100 | 每页条数，上限 500 |
| `tradable_only` | boolean | ❌ | `true` | 跳过无价格标的（美股权证、停牌） |

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `items` | array | 本页条目 |
| `page` | int | 回显当前页 |
| `page_size` | int | 回显每页条数 |
| `has_more` | boolean | 是否还有下一页 |
| `next_page` | int \| null | 下一页页码，没有更多时为 `null` |

`items[]` 的字段见 [7.5](#75-全市场列表) 的 `InstrumentSummary` 表——与库方法
返回的是同一个结构，不重复描述。

**列表不含行情字段**（价格、市值），理由见 7.5。

**错误**：`UNSUPPORTED`(422，该市场无列表源)

#### `GET /v1/healthz`

**参数**：无。

**响应 `data`**

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | enum | `ok` / `degraded` |
| `config` | object | 当前生效的 ttl 与 proxy |
| `sources` | object | 各源状态、冷却剩余、超时 |
| `cache` | object | 各能力的条目数 |
| `recent_schema_changes` | string[] | 近期结构变更的源 |

**错误**：无（永远返回 200）

**完整 schema 见 [openapi.yaml](../api/openapi.yaml)**，它由代码生成：

```bash
quotestack-server --dump-openapi > docs/api/openapi.yaml
```

本文只解释**为什么**这么设计；字段的权威定义在生成物里。改接口的正确顺序是
「改代码 → 重新生成 → 提交」，`tests/test_server.py` 会拦住忘记重新生成的情况。

---

## 数据格式契约

| 项 | 决议 | 理由 |
|---|---|---|
| 价格 / 金额 | **string** | 避免 float 精度问题；直通 Java `BigDecimal` |
| 交易日 | `YYYY-MM-DD` | 日历概念，无时区 |
| 瞬时时刻 | RFC3339 带偏移 | 禁止 naive datetime |
| 空值 | `null` | 0 是有意义的值 |
| 成交量单位 | 股 / 币（最小单位） | 腾讯给"手"，适配器 ×100 |
| 涨跌幅 | 百分比数值 + `_pct` 后缀 | `-1.76` 表示 -1.76% |
| 精度 | 保留源精度，附 `precision` | 不统一 scale |
| 命名 | snake_case + 行业词 | `open/high/low/close/volume` |
| 联合类型 | **禁止** | 旧项目 `float \| str` 的教训 |
| `volume_unit` | 不返回 | 全系统单一口径，返回即冗余 |

每个响应必带 `source` + `fetched_at` + `stale`。

### 示例

```json
{
  "instrument": {
    "id": "CN:STOCK:600519",
    "asset_class": "STOCK",
    "market": "CN",
    "code": "600519",
    "currency": "CNY",
    "source_name": "贵州茅台",
    "confidence": "exact"
  },
  "bars": [
    { "date": "2026-11-05", "open": "1446.70", "high": "1466.00",
      "low": "1430.00", "close": "1452.00", "volume": "46712",
      "amount": "6752970915.00" }
  ],
  "interval": "1d",
  "adjust": "qfq",
  "source": "eastmoney",
  "fetched_at": "2026-11-07T14:30:00+08:00",
  "stale": false
}
```

---

## CLI

命令行入口由 `[project.scripts]` 注册，**进程内直接调用库**，不依赖 HTTP 服务，也不引入额外依赖（纯 `argparse` + ANSI 转义）。

### 命令集（4 个）

| 命令 | 状态 | 作用 | 示例 |
|---|---|---|---|
| `quote` | ✅ M1 | 查实时价 | `quotestack quote 600519` |
| `history` | ✅ M1 | 查 K 线 / 分钟线 | `quotestack history 600519 --limit 20` |
| `resolve` | M2 | 调试标识解析 | `quotestack resolve 000001 --asset-class FUND` |
| `health` | M2 | 查看源状态 | `quotestack health` |

**不做** `profile` / `holdings` / `benchmark` / `estimate` / `fx`——它们没有清晰的终端呈现方式（结构复杂、需要分页、需要画图）。

### 输出

默认人类可读：

```
$ quotestack quote 600519
贵州茅台  600519  CN/STOCK
─────────────────────────────
现价      1453.00 CNY    +0.07%
涨跌      +1.00
来源      eastmoney
获取时间  2026-11-07 14:30:00
```

`--json` 输出机器可读（管道友好）：

```json
{"code":"600519","price":"1453.00","change":"1.00","change_pct":0.07,"source":"eastmoney"}
```

### 全局参数

| 参数 | 作用 |
|---|---|
| `--proxy URL` | 覆盖代理 |
| `--no-cache` | 禁用缓存（调试用） |
| `--cache-path PATH` | 指定缓存文件 |
| `--source NAME` | 强制走某个源，跳过降级链 |
| `--json` | 机器可读输出 |

`--source` 用于定位问题：能直接判断是东财的问题还是腾讯的问题。

### 为什么不用 typer / click

四个命令、十来个参数，`argparse` 完全够用；彩色输出用 ANSI 转义手写约 20 行。CLI 是最容易被过度工程化的地方，保持零依赖。


---

← 上一篇：[缓存](04-cache.md) ｜ 下一篇：[错误模型](06-errors.md) →
