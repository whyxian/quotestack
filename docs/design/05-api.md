# 接口与格式契约

> quotestack 设计决议 · 第 5 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：🚧 3/10 方法可用（resolve / quote / history）


## 接口清单（10 个）

> 以下方法均为 `async def`，调用需 `await`。同步场景用 `quotestack.sync.SyncMarketData`，详见 [运行时模型](13-runtime-model.md)。

所有方法的第一参数都是 `code`，配合 `asset_class` 与 `market`——调用方**永远不持有 instrument**（见 7.3 一跳原则）。

| # | 入口 | 状态 | 说明 |
|---|---|---|---|
| 1 | `resolve(code, asset_class, market)` | ✅ M1 | 身份解析（同步方法） |
| 2 | `quote(code, asset_class, market)` | ✅ M1 | 实时价 |
| 3 | `quote_many(items)` | M3 | 批量报价 |
| 4 | `history(code, asset_class, market, interval, adjust, limit)` | ✅ M1 | K 线 + 分钟线 |
| 5 | `nav(code, asset_class, market, limit)` | M4 | 净值序列 |
| 6 | `profile(code, asset_class, market)` | M4 | 静态画像 + 基准结构 |
| 7 | `holdings(code, asset_class, market, before, limit)` | M4 | 季度持仓分页 |
| 8 | `benchmark(code, asset_class, market, start, end)` | M4 | 基准加权曲线 |
| 9 | `estimate(code, asset_class, market)` | M5 | 估值（派生） |
| 10 | `fx(base, quote)` | M3 | 汇率 |

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

11 条路由对应 10 个库方法：`quote` / `quote_many` 共用两条路由，其余一一对应。

#### 参数约定

| 项 | 决议 |
|---|---|
| 批量路径 | `/v1/quotes/batch`（不用 `:batch` 冒号风格，兼容网关） |
| 批量上限 | 200 条，超出 422 |
| 分页 | `before` 游标（如 `2025Q4`）+ `limit`，响应带 `has_more` / `next_before` |
| `adjust` | `none` / `qfq` / `hfq`，默认 `qfq` |
| 健康检查 | `/healthz` 返回源状态、代理档位、近期 `schema_changes` |
| 错误体 | `{ code, message, detail }`，HTTP 状态码按第 9 节映射 |

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
