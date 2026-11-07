# 代码导读（中文）

> 代码注释是英文的（面向开源社区），这份文档负责让你**不用读注释也能看懂代码**。
> 每个文件一张表：职责 + 关键成员 + 容易踩的点。
> 更新于 2026-11-08，对应 M2 完成状态。

---

## 怎么用这份文档

1. **想知道某文件干什么** → 查对应小节
2. **想知道某个函数怎么用** → 查 `docs/design/05-api.md`
3. **想知道为什么这么设计** → 查 `docs/design/`
4. **想改某处** → 先看这里，再看 [ARCHITECTURE.md](ARCHITECTURE.md) 的依赖方向

---

## 整体结构

```
src/quotestack/
├── __init__.py        对外导出的 21 个符号
├── client.py          ★ 主入口 MarketData
├── cli.py             命令行
├── sync.py            同步包装
├── errors.py          14 个错误类
├── logging.py         结构化事件
├── resilience.py      冷却 + 限流
├── models/            数据模型（Instrument / Quote / Bar / 枚举）
├── identity/          代码 → 各源标识
├── cache/             缓存
└── sources/           数据源适配器
```

**依赖方向**（不能反向）：

```
models ← errors ← identity ← sources ← client ← cli / sync
                    ↑
                  cache
```

---

## `client.py` — 主入口（402 行）

**职责**：把解析、缓存、单飞、降级、限流串成一次调用。

| 方法 | 作用 | 说明 |
|---|---|---|
| `resolve(code, cls, market)` | 代码 → 各源标识 | **同步方法**，纯规则不联网 |
| `quote(code, cls, market, max_age=)` | 查实时价 | 先查缓存，未命中走回源 |
| `history(..., interval, adjust, limit)` | 查 K 线 | 同上，多两个参数进缓存键 |
| `health()` | 运行时状态 | 和将来的 `/healthz` 返回同一结构 |
| `cache_stats()` | 缓存条目数 | 调试用 |
| `aclose()` | 释放资源 | 取消在途任务 + 关闭 HTTP 客户端 |

**内部流程**（私有方法，按调用顺序）：

```
_cached()          查缓存 → 判三态 → 决定是否回源
  ↓ 需要回源
_single_flight()   同一 key 的并发请求共用一次回源
  ↓
_fetch_and_store() 检查冷却 → 申请令牌 → 调上游 → 写缓存
  ↓ 上游失败
_fallback()        缓存够新就返回旧值，否则抛 Unavailable
```

**容易踩的点**：

- `resolve` 是**同步**的，不要 `await`
- 构造参数用 `is not None` 判断，不能用 `or`（`MemoryCache` 有 `__len__`，空缓存是 falsy）

---

## `sources/eastmoney.py` — 东财适配器（363 行）

**职责**：唯一已实现的数据源，负责实时报价和 K 线。

| 成员 | 作用 | 说明 |
|---|---|---|
| `meta` | 能力声明 | 支持哪些市场、超时多少秒 |
| `quote(instruments)` | 批量报价 | 内部按 50 个一批切分 |
| `history(instrument, interval, adjust, limit)` | K 线 | 支持 8 种周期、3 种复权 |
| `_fetch_chunk(secids)` | 单次 HTTP | 结构断言都在这里 |
| `_secid_of(instrument)` | 取东财标识 | 从 `aliases["eastmoney"]` 拿 |
| `_to_quote(...)` | 行 → Quote | **价格 ÷ 10^f1** |
| `_to_bar(...)` | 行 → Bar | **注意是 O-C-H-L 顺序** |

**两个致命细节**（写错不报错，只是数据悄悄错）：

1. **价格是放大整数**：`f1` 是小数位，股票 2 位、ETF 3 位
2. **K 线是 O-C-H-L**：`date, open, close, high, low, volume, amount, pct`

---

## `identity/` — 标识解析

### `rules.py`（90 行）

纯函数，无网络。

| 函数 | 作用 |
|---|---|
| `cn_exchange(code)` | 6 位代码 → `sh` / `sz` / `bj` |
| `classify_cn_fund(code)` | 基金代码 → `sh` / `sz` / `offexchange` |
| `guess_currency(cls, market)` | 市场 → 币种 |

**注意**：`92` 开头的判断必须在 `9` 之前，否则北交所会被误判成上交所。

### `resolver.py`（165 行）

`resolve(code, asset_class, market)` → `Instrument`。

三种市场走三个分支：

| 市场 | 得到的 aliases |
|---|---|
| CN 股票/场内基金 | `{eastmoney: "1.600519", tencent: "sh600519"}` |
| CN 场外基金 | `{tiantian: "022430"}`（没有交易所标识） |
| US | `{tencent: "usAAPL"}`（缺东财，需后缀） |
| CRYPTO | `{binance: "BTCUSDT"}` |

---

## `models/` — 数据模型

| 文件 | 类 | 关键字段 |
|---|---|---|
| `instrument.py` | `Instrument` | `id`, `code`, `asset_class`, `market`, `aliases`, `capabilities` |
| `quote.py` | `Quote` | `price`(str), `change`, `change_pct`, `ts`, `status`, `stale` |
| `bar.py` | `Bar` | `date`, `time`(分钟线才有), `open/high/low/close/volume` |
| `enums.py` | 7 个枚举 | `AssetClass` / `Market` / `Capability` / `Interval` / `Adjust` / `Confidence` / `QuoteStatus` |

**铁律**：价格、金额、成交量**一律用 `str`**，不能用 float。

---

## `cache/` — 缓存

### `base.py`（182 行）

| 成员 | 作用 |
|---|---|
| `CacheState` | 三态：`FRESH` / `STALE` / `EXPIRED` |
| `classify(entry, ttl, max_stale)` | 判定三态（**核心函数**） |
| `make_key(capability, id, *parts)` | 拼 `v1\|quote\|CN:STOCK:600519` |
| `CacheEntry` | 值 + 抓取时间 + 来源 |

**三态怎么判**：

```
年龄 < TTL              → FRESH    直接用
TTL ≤ 年龄 < max_stale  → STALE    只在回源失败时用
年龄 ≥ max_stale        → EXPIRED  绝不使用
```

### `memory.py`（41 行）

进程内字典，**过期不删除**——留着当 stale 兜底。

---

## `resilience.py` — 冷却与限流（129 行）

| 类 | 作用 |
|---|---|
| `Cooldown` | 源失败后跳过 30 秒，避免每次白等超时 |
| `TokenBucket` | 令牌桶，默认 5 请求/秒、突发 10 |

`Cooldown` 可以注入 `_clock`，测试时用假时钟推进时间。

---

## `errors.py` — 14 个错误类（161 行）

三层结构：

```
MarketDataError                 基类，带 code / retryable / fallback
├── InvalidArgumentError        调用方参数错
├── NotFoundError               代码不存在
├── AmbiguousError              多候选
├── DelistedError               已退市
├── UnsupportedError            该标的没这个能力
├── UpstreamError               上游失败（可重试、可换源）
│   ├── TimeoutError
│   ├── EmptyResponseError      有结构但没数据（不重试，直接换源）
│   ├── SchemaChangedError      结构变了（要告警）
│   ├── UnauthorizedError
│   ├── RateLimitedError
│   └── UnavailableError
└── ClientBrokenError           所有源结构都变了（该升级库）
```

每个错误都有 `to_dict()`，供 HTTP 层序列化。

---

## `logging.py` — 结构化事件（64 行）

| 函数 | 作用 |
|---|---|
| `get_logger(name)` | 拿到 `quotestack.<name>` 的 logger，**不挂 handler** |
| `event(logger, level, name, **fields)` | 发一条带 `event` 字段的结构化日志 |

可用事件名在 `EVENTS` 里，写错会抛异常（防止拼写漂移）。

---

## `sync.py` — 同步包装（150 行）

`SyncMarketData` 给不写 async 的人用。

**关键实现**：后台线程跑一个常驻事件循环，所有调用用 `run_coroutine_threadsafe` 提交。

**不能**用 `asyncio.run()` 逐次包装——那样每次调用都重建事件循环，缓存和单飞全失效。

`close()` 是幂等的，重复调用不会阻塞。

---

## `cli.py` — 命令行（242 行）

4 个命令：`quote` / `history` / `resolve` / `health`。

`main(argv)` 返回退出码：成功 0，业务错误 1，Ctrl-C 130。

输出分两种：默认表格（给人看），`--json`（给程序用）。

---

## `sources/base.py` — 源契约（105 行）

| 成员 | 作用 |
|---|---|
| `SourceMeta` | 声明源的名字、能力、覆盖市场、超时、是否需要代理 |
| `Quoter` (Protocol) | `async quote(instruments) -> list[Quote]` |
| `Historian` (Protocol) | `async history(...) -> list[Bar]` |

用 Protocol 而不是抽象基类——源只实现自己能做的事，不需要写空方法。

---

## 快速定位表

| 我想改… | 去这个文件 |
|---|---|
| 加一个新的数据源 | `sources/` 新建文件 + `sources/__init__.py` 导出 |
| 改代码 → secid 的规则 | `identity/rules.py` |
| 改缓存时长 | `cache/base.py` 的 `_DEFAULT_TTL` |
| 改 stale 上限 | `cache/base.py` 的 `_DEFAULT_MAX_STALE` |
| 改错误语义 | `errors.py` |
| 改重试/换源策略 | `client.py` 的 `_fetch_and_store` |
| 改 CLI 输出 | `cli.py` 的 `_emit_*` |
| 加新的日志事件 | `logging.py` 的 `EVENTS` |

---

## 常见疑问

**Q：为什么 `resolve` 是同步的，`quote` 是异步的？**
A：`resolve` 只做字符串规则，不碰网络，没必要异步。

**Q：为什么价格用字符串？**
A：避免浮点误差。`0.1 + 0.2 != 0.3`，而金额不能有这种问题。

**Q：为什么缓存过期了还不删？**
A：上游挂了时可以返回旧值（标 `stale`），比直接报错好。但有 `max_stale` 兜底，不会永远返回古董。

**Q：为什么库不自己打日志？**
A：库挂了 handler 会污染调用方的日志配置。只发事件，怎么输出由调用方决定。
