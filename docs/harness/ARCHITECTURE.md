# 架构（as-built）

> 反映 **M5 完成时**的真实代码，不是设计意图。
> 设计理由见 `docs/design/`；本文件只描述"代码现在长什么样"。
> 逐文件、逐函数的中文说明见 [CODE_MAP_ZH](../CODE_MAP_ZH.md)（人类文档，不在 harness 下）。
> 更新于 2026-11-08。

---

## 1. 目录结构

```
src/quotestack/
├── __init__.py            对外导出 24 个符号
├── client/
│   ├── __init__.py        ★ MarketData：全部公开方法
│   └── fetch.py           FetchPolicy：三态缓存、单飞、降级、限流
├── cli.py                 命令行 5 个命令
├── sync.py                同步包装
├── errors.py              14 个错误类
├── logging.py             结构化事件
├── resilience.py          冷却 + 令牌桶
├── funds.py               基金类型 → FundClass
├── benchmark.py           基准文本解析 + 权益判定
├── indexes.py             指数名称 → secid
├── estimate.py            估值算式与措辞
├── models/                数据模型（13 个文件）
│   ├── enums.py           8 个枚举
│   ├── instrument.py      Instrument
│   ├── quote.py           Quote
│   ├── bar.py             Bar
│   ├── nav.py             NavPoint
│   ├── summary.py         InstrumentSummary
│   ├── result.py          QuoteResult
│   ├── fx.py              FxRate
│   ├── holdings.py        Holding / QuarterHoldings
│   ├── profile.py         Profile
│   ├── allocation.py      Allocation
│   ├── curve.py           BenchmarkCurve
│   └── estimate.py        Estimate
├── identity/              代码 → 各源标识
├── cache/                 三态缓存
└── sources/               五个数据源
    ├── base.py            SourceMeta / Quoter / Historian
    ├── routing.py         路由表 + candidates()
    ├── eastmoney/         core / quotes / klines / listings / parsing
    ├── tencent.py         实时兜底
    ├── tiantian.py        净值 + 列表 + 持仓 + 画像 + 配置
    ├── binance.py         交易对列表
    └── fx.py              汇率
```

## 2. 依赖方向

```
models ← errors ← identity ← cache
                    ↑
                 sources ← routing
                    ↑
                 client ← sync / cli
                    ↑
                  funds
```

**规则**：

| 禁止 | 原因 |
| --- | --- |
| `sources` import `client` | 源不该知道编排逻辑 |
| `models` import 任何上层 | 模型必须是最底层 |
| `identity` 发起网络请求 | 解析必须是纯函数 |

`funds.py` 只依赖 `models.enums`，被 `sources/tiantian.py` 使用。

---

## 3. 一次 `quote()` 的完整路径

```
client.quote("600519")
  │
  ├─ resolve()                        identity/resolver.py
  │    └─ Instrument(aliases={eastmoney: "1.600519", ...})
  │
  ├─ _require(QUOTE)                  能力检查，缺则 Unsupported
  │
  ├─ _cached()                        cache/base.py
  │    ├─ classify() → FRESH?  → 直接返回
  │    └─ STALE / EXPIRED → 继续
  │
  ├─ _single_flight()                 同 key 并发只回源一次
  │
  └─ _fetch_and_store()
       ├─ _candidates()               sources/routing.py 决定顺序
       │    └─ ["eastmoney", "tencent"]
       ├─ cooldown.is_cooling()       冷却中的源跳过
       ├─ bucket.acquire()            令牌桶限流
       ├─ source.quote([inst])        实际 HTTP
       │    └─ eastmoney._to_quote()  价格 ÷10^f1，涨跌幅 ÷100
       ├─ 成功 → cache.set() → 返回
       └─ 失败 → 下一个源
            └─ 全失败 → _fallback()
                 ├─ 有 stale 值 → 标 stale=true 返回
                 └─ 否则 → Unavailable(attempts=[...])
```

---

## 3.5 一次 `estimate()` 的路径

```
client.estimate("166002")
  ├─ profile()            → fund_class / benchmark / tracking_index
  ├─ _allocation()        → 股票/债券/现金占净比
  ├─ 货币型？             → change_pct=0.0, basis=none（结束）
  ├─ 有跟踪标的？
  │    ├─ resolve_index() → secid
  │    ├─ quotes_by_secid → 当日涨跌
  │    └─ 涨跌 × 权益敞口 → basis=index
  └─ 否则按持仓
       ├─ holdings(limit=1)        → 最新季报前十大
       ├─ quotes_by_secid(个股)    → 加权贡献
       ├─ equity_proxy(基准)       → 权益组件归一权重
       ├─ quotes_by_secid(指数)    → 剩余仓位按基准补
       └─ basis=holdings
```

**算不出来时 `change_pct=None`，不是 0**；货币基金例外，它的 0 是真实的。

## 4. 一次 `iter_instruments()` 的路径

```
client.iter_instruments(STOCK, CN)
  │
  ├─ _LISTING_PLAN[(STOCK, CN, None)] → ("eastmoney",)
  │
  └─ source.list_instruments()
       ├─ 东财：_list_page() 翻页，用 data.total 判断结束
       │    └─ _to_summary() 解析板块、上市日、行业
       ├─ 天天：一次拿 3.1MB，本地切片
       └─ Binance：一次拿 17MB，过滤 TRADING + USDT
```

**分页不能用"这页不满"判断结束**——东财 `pz` 最大 100，传 500 会被静默截断。

---

## 5. 四个实现层面的坑

| 坑 | 位置 | 后果 |
| --- | --- | --- |
| 东财价格是小数字放大 | `eastmoney._to_quote` | 用错小数位，ETF 差 10 倍 |
| 东财涨跌幅单位固定 0.01% | `_PCT_DIVISOR` | 按 `10^f1` 缩放，美股错 10 倍 |
| 东财 K 线是 O-C-H-L | `_to_bar` | high/low 互换，不报错 |
| 腾讯返回 GBK | `tencent._parse` | 中文乱码 |

**共同点：全是"不报错但数据错"，靠测试和断言很难发现。**

---

## 6. 缓存键

```
v1|quote|CN:STOCK:600519
v1|history|CN:STOCK:600519|1d|qfq
v1|nav|CN:FUND:166002
```

格式：`v1|capability|instrument_id[|interval|adjust]`

版本前缀 `v1` 用于整体失效——改了序列化格式时递增即可。

---

## 7. 文件规模现状

> 各文件行数见本节末尾的生成表——那是从代码统计的，不手写。
**不设行数上限。** 拆分只看一个标准：**拆出来的东西有没有自己的名字和职责**。

| 拆开 | 理由 |
| --- | --- |
| `client/fetch.py` | 缓存三态 + 单飞 + 降级是**可独立测试的机制**，不属于公开 API |
| `benchmark.py` / `indexes.py` / `estimate.py` | 纯函数，无状态，可离线测试 |
| `sources/eastmoney/*` | 三个端点族各有载荷怪癖，解析层可共用 |
| `candidates()` 在 `routing.py` | 它决定"试哪些源"，属于路由 |

| 不拆 | 理由 |
| --- | --- |
| `client/__init__.py` | `MarketData` 是唯一的公开入口，拆开会让读者跳多个文件 |
| `sources/tiantian.py` | 五个方法都打同一个域名、同一套 GBK/JS 解析习惯 |

**已知观察**：`client/__init__.py` 从 M3.6 的 550 行增长到 1028 行，主要是
M4/M5 新增的 `profile` / `holdings` / `benchmark` / `estimate`。若继续增长，
可把基金分析流程抽成模块级函数（如 `fund_ops.py(estimate(client, ...))`），
让类方法只做委托。**现在还没到那个程度。**

<!-- generated:begin -->
<!-- 由 scripts/sync_docs.py 生成，不要手改 -->

| 文件 | 行数 |
|---|---|
| `quotestack/client/__init__.py` | 1051 |
| `quotestack/sources/tiantian.py` | 634 |
| `quotestack/server/app.py` | 613 |
| `quotestack/server/schemas.py` | 312 |
| `quotestack/cli.py` | 298 |
| 其余 48 个文件 | < 263 |

**合计**：7,685 行 / 53 文件。

<!-- generated:end -->

## 8. 测试布局

```
tests/
├── test_identity.py      解析规则
├── test_eastmoney.py     行情解析 + 缩放
├── test_tencent.py       GBK + 双布局
├── test_tiantian.py      JS 变量解析
├── test_fx.py            汇率交叉
├── test_listing.py       三个源的列表
├── test_funds.py         基金分类
├── test_routing.py       路由与批量
├── test_resilience.py    冷却与限流
├── test_client.py        缓存三态与降级
├── test_cli_sync.py      CLI 与同步包装
└── test_smoke.py         真实请求（默认跳过）
```

测试全离线（respx 拦截 HTTP），少量 live 用例需 `QUOTESTACK_LIVE=1` 才跑，回测脚本在 `benchmarks/`。

---

## 9. 快速定位

| 我要改… | 去这里 |
| --- | --- |
| 新增数据源 | `sources/` + `sources/routing.py` 登记 |
| 改代码 → secid 规则 | `identity/rules.py` |
| 改 TTL / max_stale | `cache/base.py` 的 `_DEFAULT_TTL` / `_DEFAULT_MAX_STALE` |
| 改错误语义 | `errors.py` |
| 改降级顺序 | `sources/routing.py` 的 `_ROUTES` |
| 改基金分类 | `funds.py` 的 `_RULES` |
| 加日志事件 | `logging.py` 的 `EVENTS`（先注册再发） |
| 改估值公式 | `estimate.py`（算式与措辞）+ `client.estimate` |
| 改指数名称映射 | `indexes.py` 的 `KNOWN_INDEXES` |
| 改基准判定规则 | `benchmark.py` 的 `_NON_EQUITY` |
| 改 CLI 输出 | `cli.py` 的 `_emit_*` |
