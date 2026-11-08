# 运行时模型

> quotestack 设计决议 · 第 13 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：✅ 限流、单飞、同步包装均已实现；服务端并发待 M6 验证

本文补上此前缺失的三件事：**异步模型、上游限流、并发安全**，外加性能目标。

---

## 1. async / sync

### 1.1 主体是异步的

库里所有 I/O 方法都是 `async def`：

```python
from quotestack import MarketData

async with MarketData() as client:
    inst = await client.resolve("600519", "STOCK", "CN")
    quote = await client.quote(inst)
```

理由：

- `httpx` 的异步客户端是首选形态
- `quote_many` 的并发扇出天然适合 `asyncio.gather`
- 服务端（FastAPI）本身就是异步的

### 1.2 提供同步包装（计划 M2）

同步用户不该被迫理解 `asyncio`：

```python
from quotestack.sync import SyncMarketData

with SyncMarketData() as client:
    quote = client.quote("600519", "STOCK", "CN")
```

> 状态：**尚未实现**，排在 M2-10。当前只有异步 API。

**实现方式很关键**：不能用 `asyncio.run()` 逐次包装——那样每次调用都会新建并销毁事件循环，内存缓存全部丢失，单飞也失效。

正确做法是**在后台线程里常驻一个事件循环**：

```
SyncMarketData.__init__
  └─ 启动 daemon 线程 → 线程内 asyncio.new_event_loop() 并 run_forever()
每个方法
  └─ asyncio.run_coroutine_threadsafe(coro, loop).result()
```

约 40 行，状态完整保留。

### 1.3 不做的事

- 不做"同一套代码同时支持两种调用方式"（双份测试，收益低）
- 不在库内部调用 `asyncio.run()`
- 不假设调用方的事件循环类型

### 1.4 事件循环边界

| 调用方 | 怎么用 |
|---|---|
| FastAPI | 直接 `await` |
| CLI | `asyncio.run(main())`，进程内跑一次 |
| 脚本 | `SyncMarketData` |
| Jupyter | 直接 `await`（已有运行中的 loop） |

---

## 2. 上游限流与礼貌策略

开源后会有多方同时使用，必须有主动节流——否则几百 QPS 打向同一个公开接口，既是对上游的滥用，也会导致 IP 被封。

### 2.1 令牌桶

**每个源一个独立的令牌桶**：

| 参数 | 默认值 |
|---|---|
| 速率 | 5 请求/秒 |
| 突发容量 | 10 |
| 排队上限 | 20 个等待者 |
| 排队超时 | 5 秒（超时抛 `RateLimited`） |

超限时**排队等待**而不是直接报错——对调用方更友好，也不浪费已完成的解析工作。

### 2.2 配置

```python
MarketData(
    rate_limit={"eastmoney": (5, 10), "binance": (10, 20)},
    rate_limit_disabled=False,     # 自测时可关
)
```

### 2.3 尊重 `Retry-After`

上游返回 429 且带 `Retry-After` 时：

1. 该源进入冷却（与第 8 节的失败冷却共用同一机制）
2. 冷却时长取 `Retry-After`，不取默认 30 秒

### 2.4 User-Agent

```
quotestack/0.1.0 (+https://github.com/<org>/quotestack)
```

固定带版本与仓库地址。这是被抓取方识别与联系的基本前提，也便于对方在异常时定位来源。

### 2.5 缓存优先

限流的另一半是**少发请求**：缓存命中就不该产生上游调用。`quote` 默认 30 秒 TTL，是主要的减负手段。

---

## 3. 并发与线程安全

### 3.1 库内部

在单个事件循环内，库是协程安全的：

- 共享状态只有缓存与单飞表
- 缓存的写入在 `asyncio.Lock` 内完成
- 单飞表用 `dict[Key, asyncio.Future]`，同一键只允许一个回源任务

### 3.2 `SqliteCache`

| 项 | 设置 |
|---|---|
| 日志模式 | `PRAGMA journal_mode=WAL` |
| 忙等超时 | `PRAGMA busy_timeout=5000` |
| 写操作 | 在 `asyncio.Lock` 内串行 |
| 读操作 | 不加锁（WAL 允许并发读） |

多进程场景下：WAL 允许并发读、写串行化。缓存本身是 **best-effort**，写冲突可容忍——最坏情况是缓存未命中多打一次上游，不影响正确性。

### 3.3 不保证的事

- 不保证多进程之间缓存一致
- 不保证 `MemoryCache` 跨进程可见（它本来就只在进程内）
- 不提供分布式锁

### 3.4 连接池

每个 `MarketData` 实例持有一个 `httpx.AsyncClient`：

| 参数 | 值 |
|---|---|
| `max_connections` | 20 |
| `max_keepalive_connections` | 10 |
| `keepalive_expiry` | 30s |

用 `async with` 管理生命周期，退出时关闭。

---

## 4. 性能目标

| 场景 | 目标（P95） | 说明 |
|---|---|---|
| 缓存命中（`quote`） | < 10 ms | 内存缓存应 < 1 ms |
| 缓存命中（`history`） | < 30 ms | 含反序列化 |
| 单源回源 | < 800 ms | 东财实测通常 100–300 ms |
| `quote_many(10)` | < 1 s | 一次批量上游请求 |
| `quote_many(200)` | < 3 s | 上限场景 |
| `import quotestack` | < 100 ms | 冷启动，不做重量级导入 |
| `holdings`（全年 4 季度） | < 1.5 s | 含 HTML 解析 |

**约束**：所有单项都远小于前端 15 秒超时，且满足链路 `单源 < 总超时 < Java 客户端 < 前端`。

---

## 5. 资源生命周期

```python
async with MarketData(cache=SqliteCache(path)) as client:
    ...
# 退出时：关闭 httpx 连接池、flush 缓存、关闭 SQLite 连接
```

不使用上下文管理器时会注册 `atexit` 兜底，但**推荐显式 `async with`**——否则连接泄漏。

---

← 上一篇：[日志与可观测性](12-observability.md) ｜ 下一篇：[测试策略](14-testing.md) →
