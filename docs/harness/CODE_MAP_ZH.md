# 代码导读（中文）

> 代码注释是英文的（面向开源社区），这份文档负责让你**不用读注释也能看懂代码**。
> 每个文件一张表：职责 + 关键成员 + 容易踩的点。
> 更新于 2026-11-08，对应 M5 完成状态（45 个文件 / 6,000 行）。

---

## 怎么用这份文档

1. **想知道某文件干什么** → 查对应小节
2. **想知道某个函数怎么用** → [05-api](../design/05-api.md)
3. **想知道 HTTP 长什么样** → [openapi.yaml](../api/openapi.yaml)
4. **想改某处** → 先看这里，再看 [ARCHITECTURE.md](ARCHITECTURE.md) 的依赖方向

---

## 整体结构

```
src/quotestack/
├── client/            ★ 主入口 MarketData（5 个 mixin）
├── cli.py             命令行
├── sync.py            同步包装
├── errors.py          14 个错误类
├── logging.py         结构化事件
├── resilience.py      冷却 + 限流
├── funds.py           基金分类
├── benchmark.py       基准解析 + 权益判定
├── indexes.py         指数名称 → secid
├── estimate.py        估值算式与措辞
├── models/            Instrument / Quote / Bar / NavPoint / Summary / Result /
│                     FxRate / Holding / Profile / Allocation / Curve / Estimate / 枚举
├── identity/          代码 → 各源标识
├── cache/             三态缓存
└── sources/           五个数据源 + 路由表
```

**依赖方向**（不能反向）：

```
models ← errors ← identity ← cache
                    ↑
                 sources ← routing
                    ↑
                 client ← sync / cli
```

---

## `client/` — 主入口（2 个文件）

**职责**：把解析、缓存、单飞、降级、限流、路由串成一次调用。

| 方法 | 作用 | 说明 |
|---|---|---|
| `resolve(code, cls, market)` | 代码 → 各源标识 | **同步**，纯规则不联网 |
| `quote(...)` | 查实时价 | 缓存 → 单飞 → 降级 |
| `quote_many(items)` | 批量报价 | 按市场分组，一组一次请求 |
| `history(...)` | K 线 | 多 interval/adjust 进缓存键 |
| `nav(...)` | 基金净值 | 走天天基金 |
| `fx(base, quote)` | 汇率 | 走 `eastmoney-fx` |
| `iter_instruments(...)` | 全市场列表 | 异步迭代器，分页 |
| `health()` | 运行时状态 | 与 `/healthz` 同结构 |
| `profile(code)` | 基金画像 | 类型、基准、经理、规模 |
| `holdings(code, before=, limit=)` | 季度持仓 | `limit` 是季度数，`before` 是排他游标 |
| `benchmark(code, start=, end=)` | 基准加权曲线 | 剔除不可还原组件并降 coverage |
| `estimate(code)` | 盘中估值 | 指数型走公式 A，主动型走公式 B |
| `cache_stats()` | 缓存条目数 | 调试用 |

**内部流程**（按调用顺序）：

```
_cached()          查缓存 → 判三态
  ↓ 需要回源
_single_flight()   同 key 并发共用一次
  ↓
_fetch_and_store() 按路由表逐个源尝试
  │                 ├─ 冷却中 → 跳过
  │                 ├─ 令牌桶 → 限流
  │                 └─ 失败 → 下一个源
  ↓ 全失败
_fallback()        有 stale 值就返回，否则抛 Unavailable
```

**容易踩的点**：

- `resolve` 是**同步**的，不要 `await`
- 构造参数用 `is not None` 判断，不能用 `or`（`MemoryCache` 有 `__len__`，空缓存是 falsy）

**两个文件**：

| 文件 | 职责 |
|---|---|
| `__init__.py` | `MarketData`：全部公开方法 |
| `fetch.py` | `FetchPolicy`：缓存三态、单飞、降级、限流、冷却 |

`MarketData` 在 `__init__.py` 里组合它们，对外仍是同一个类。

---

## `sources/eastmoney/` — 东财（5 个文件）

**职责**：主数据源，行情 + K 线 + 全市场列表 + 美股 secid 解析。

| 成员 | 作用 | 说明 |
|---|---|---|
| `quote(instruments)` | 批量报价 | 内部按 50 个一批 |
| `history(...)` | K 线 | 8 种周期、3 种复权 |
| `list_instruments(...)` | 全市场列表 | A股 / 场内基金 / 美股 |
| `_secid_for(instrument)` | 取 secid | 美股需搜索，结果缓存 |
| `_search_us(...)` | 搜索美股 | 多候选抛 `Ambiguous` |
| `_to_quote(...)` | 行 → Quote | 价格 ÷10^f1，**涨跌幅 ÷100** |
| `_to_bar(...)` | 行 → Bar | **O-C-H-L 顺序** |
| `_to_summary(...)` | 行 → Summary | 板块、上市日、行业 |

**四个致命细节**：

1. 价格是放大整数，小数位在 `f1`（股票 2、ETF/美股 3）
2. **涨跌幅 `f3` 固定 1/100**，与 `f1` 无关
3. K 线顺序是 `date, open, close, high, low`，不是 OHLC
4. 列表分页 `pz` 最大 100，用 `data.total` 判断结束

---

## `sources/tencent.py` — 腾讯（214 行）

**职责**：实时报价兜底，补东财缺失的美股。

| 项 | 说明 |
|---|---|
| 编码 | **GBK**，必须显式转码 |
| A股布局 | 标志 `1`，时间 `20261106161458`，币种隐含 |
| 美股布局 | 标志 `200`，时间 `2026-11-06 16:00:01`，币种在 `[35]` |
| 美股时区 | **America/New_York**，不是东八区 |

---

## `sources/tiantian.py` — 天天基金（245 行）

**职责**：场外基金净值 + 全量基金列表。

| 方法 | 数据源 | 说明 |
|---|---|---|
| `nav(instrument)` | `pingzhongdata/{code}.js` | 正则抠 `Data_netWorthTrend` |
| `list_instruments()` | `fundcode_search.js` | 3.1MB，28,305 只，带基金类型 |

**坑**：文件带 BOM（用 `utf-8-sig`）；`var r` 是 JS 不是 JSON，要先正则提取。

---

## `sources/binance.py` — 加密（128 行）

**职责**：交易对列表。用 `data-api.binance.vision`（国内可达）。

默认只返回 `status=TRADING` 且 `quoteAsset=USDT` 的 518 个交易对。

**注意**：17MB 的 `exchangeInfo`，超时设 20 秒；连通性不稳定，需代理时通过 `proxy` 参数。

---

## `sources/fx.py` — 汇率（185 行）

**职责**：USD 基准表 + 交叉换算。

```
USD/CNH  直接
EUR/USD  取倒数
USD/HKD  = USDCNH ÷ HKDCNH
```

**坑**：接口回显的代码带尾缀（`HKDCNYC`），必须用 `_BY_CODE` 归一化。

---

## `sources/routing.py` — 路由表（48 行）

`(asset_class, market, capability)` → 源名列表，按优先级排列。

```python
(STOCK, CN, QUOTE) → ("eastmoney", "tencent")
(FUND,  CN, NAV)   → ("tiantian",)
```

**不放配置**：路由是设计决策，改动应该走 review。

---

## `identity/` — 标识解析

### `rules.py`（90 行）

| 函数 | 作用 |
|---|---|
| `cn_exchange(code)` | 6 位代码 → `sh` / `sz` / `bj` |
| `classify_cn_fund(code)` | 基金代码 → 场内/场外 |
| `guess_currency(cls, market)` | 市场 → 币种 |

**注意**：`92` 开头必须在 `9` 之前判断，否则北交所被误判成上交所。

### `resolver.py`（169 行）

`resolve()` → `Instrument`。**基金分类不可靠**：`166002` 是场外基金但前缀是 `16`，
所以所有基金都给 `NAV` 能力，前缀像场内的再加 `QUOTE`/`HISTORY`，并标 `confidence=partial`。

---

## `cache/` — 缓存

### `base.py`（182 行）

| 成员 | 作用 |
|---|---|
| `CacheState` | `FRESH` / `STALE` / `EXPIRED` |
| `classify(entry, ttl, max_stale)` | **核心函数**，判三态 |
| `make_key(...)` | `v1\|quote\|CN:STOCK:600519` |
| `_DEFAULT_MAX_STALE` | 每能力的陈旧上限（quote 1 天，history ∞） |

### `memory.py`（41 行）

进程内字典，**过期不删**——留着当 stale 兜底。

---

## `resilience.py` — 冷却与限流（129 行）

| 类 | 作用 |
|---|---|
| `Cooldown` | 源失败后 30 秒内跳过 |
| `TokenBucket` | 5 req/s，突发 10，排队超时 5 秒 |

`Cooldown` 支持注入 `_clock`，测试时用假时钟。

---

## `funds.py` — 基金分类（56 行）

`classify_fund_type("混合型-偏股")` → `FundClass.EQUITY`

33 种原始标签 → 7 类。**未知标签一律 `OTHER`，绝不猜成 `EQUITY`**——猜错分类等于算错估值。

实测分布：EQUITY 13,413 / BOND 9,690 / HYBRID 2,504 / FOF 1,409 / MONEY 977 / REITS 103 / OTHER 209。

---

## `benchmark.py` — 基准解析（约 170 行）

把一句中文基准拆成带权重的组件：

```
中证800指数收益率*70%+上证国债指数收益率*25%+存款*5%
→ [(中证800, 70, EQUITY), (上证国债, 25, NON_EQUITY), (存款, 5, NON_EQUITY)]
```

| 成员 | 作用 |
|---|---|
| `parse_benchmark(text)` | 拆项、取权重、算 coverage |
| `classify_component(name)` | 权益 / 非权益 / 未识别 |
| `Benchmark` | 原文 + 组件 + coverage |

**判定顺序是关键**：先判非权益（`债`/`存款`/`利率`），再判「含指数」。
否则 `中债总指数` 会被当成权益。

---

## `indexes.py` — 指数名称解析（约 90 行）

| 成员 | 作用 |
|---|---|
| `normalize_index_name("中证800指数收益率")` | → `中证800` |
| `candidate_names(...)` | 全名失败时去掉「上证/中证」前缀重试 |
| `KNOWN_INDEXES` | 搜索接口查不到的（债券指数）走兜底表 |

---

## `estimate.py` — 估值算式（约 140 行）

纯函数，无网络，可完全离线测试。

| 函数 | 作用 |
|---|---|
| `assumption_of(benchmark)` | 分组成 equity / non_equity / unclassified |
| `equity_proxy(benchmark)` | 权益组件权重归一化到 100 |
| `weighted_change(weights, changes)` | 缺失组件自动剔除并重新归一 |
| `describe_index/holdings(...)` | 生成人话解释 |

**`change_pct=None` 与 `0` 的区别贯穿此处**：「算不出来」返回 `None`。

---

## `errors.py` — 14 个错误类（161 行）

```
MarketDataError                 基类，带 code / retryable / fallback
├── InvalidArgumentError        参数错（400）
├── NotFoundError               不存在（404）
├── AmbiguousError              多候选（409）
├── DelistedError               已退市（410）
├── UnsupportedError            没这个能力（422）
├── UpstreamError               上游失败
│   ├── TimeoutError
│   ├── EmptyResponseError      有结构没数据（不重试，直接换源）
│   ├── SchemaChangedError      结构变了（要告警）
│   ├── UnauthorizedError
│   ├── RateLimitedError
│   └── UnavailableError        全部源失败 / 冷却中
└── ClientBrokenError           所有源结构都变了（该升级库）
```

---

## `logging.py` — 结构化事件（64 行）

| 函数 | 作用 |
|---|---|
| `get_logger(name)` | 拿 `quotestack.<name>`，**不挂 handler** |
| `event(logger, level, name, **fields)` | 发结构化日志 |

事件名必须先注册到 `EVENTS`，写错直接抛 `ValueError`。

---

## `sync.py` — 同步包装（150 行）

后台线程跑常驻事件循环，调用通过 `run_coroutine_threadsafe` 提交。

**不能用 `asyncio.run()`**——每次重建循环，缓存和单飞全失效。

`close()` 幂等，重复调用不会阻塞。

---

## `cli.py` — 命令行（242 行）

4 个命令：`quote` / `history` / `resolve` / `health`，都支持 `--json`。

`main(argv)` 返回退出码：成功 0，业务错误 1，Ctrl-C 130。

---

## `models/` — 数据模型

| 文件 | 类 | 关键点 |
|---|---|---|
| `enums.py` | 7 个枚举 | `FundClass` 是基金专用分类 |
| `instrument.py` | `Instrument` | `aliases` 存各源标识；`supports()` 查能力 |
| `quote.py` | `Quote` | `price` 是 **str** |
| `bar.py` | `Bar` | `time` 只有分钟线才有 |
| `nav.py` | `NavPoint` | `nav` 是 **str** |
| `summary.py` | `InstrumentSummary` | **不含行情字段** |
| `result.py` | `QuoteResult` | 批量结果，`instrument` 可空 |
| `fx.py` | `FxRate` | `derived` 标记是否交叉算出 |
| `holdings.py` | `Holding` / `QuarterHoldings` | `weight` 是占净值百分比 |
| `profile.py` | `Profile` | `benchmark` 是解析后的结构，不是字符串 |
| `allocation.py` | `Allocation` | `equity_exposure` = 股票 + 其他（联接基金靠这个） |
| `curve.py` | `BenchmarkCurve` | `coverage` < 1 说明只用了部分组件 |
| `estimate.py` | `Estimate` | `change_pct=None` 表示未知 |

**铁律**：价格、金额、成交量、净值一律用 `str`。

---

## 快速定位表

| 我想改… | 去这里 |
|---|---|
| 加数据源 | `sources/` 新建 + `routing.py` 登记 |
| 改 secid 规则 | `identity/rules.py` |
| 改缓存时长 | `cache/base.py` 的 `_DEFAULT_TTL` |
| 改 stale 上限 | `cache/base.py` 的 `_DEFAULT_MAX_STALE` |
| 改降级顺序 | `sources/routing.py` 的 `_ROUTES` |
| 改基金分类 | `funds.py` 的 `_RULES` |
| 改基准判定 | `benchmark.py` 的 `_NON_EQUITY` |
| 加指数映射 | `indexes.py` 的 `KNOWN_INDEXES` |
| 改估值公式 | `estimate.py` |
| 加日志事件 | `logging.py` 的 `EVENTS` |
| 改错误语义 | `errors.py` |
| 改 CLI 输出 | `cli.py` 的 `_emit_*` |
| 改列表板块 | `sources/eastmoney.py` 的 `_LIST_FILTERS` |

---

## 常见疑问

**Q：为什么 `resolve` 是同步的？**
A：纯字符串规则，不碰网络，没必要异步。

**Q：为什么价格用字符串？**
A：`0.1 + 0.2 != 0.3`。金额不能有浮点误差。

**Q：为什么缓存过期了还不删？**
A：上游挂了可以返回旧值（标 `stale`），比直接报错好。但 `max_stale` 兜底，不会永远返回古董。

**Q：为什么列表不带价格？**
A：列表缓存 24 小时、价格 30 秒过期，一个对象两种时间尺度会误导人。

**Q：为什么基金都要给 NAV 能力？**
A：代码前缀不能证明是否场内（`166002` 就是反例）。宁可多给能力，失败时明确报错。

**Q：为什么不把 `MarketData` 拆成几个类？**
A：试过。用 mixin 拆成 5 个文件后有 7 层继承链，读一次 `quote` 要跳 4 个文件。
后来组装回一个类，只把「取数策略」抽成 `FetchPolicy`——它能独立测试，这才是拆的理由。
