# 缓存

> quotestack 设计决议 · 第 4 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：🚧 三态、单飞、max_stale 已实现；SQLite 后端未做（M6 之后）


## 缓存

### 策略

服务自持缓存，能力粒度 TTL，初始化可配。

| 能力 | 默认 TTL | 最旧容忍 | 说明 |
|---|---|---|---|
| `RESOLVE` | 7 天 | 30 天 | 代码 → 各源标识，规则稳定 |
| `QUOTE` | 30 秒 | 1 天 | 盘中要新鲜，收盘后不必重取 |
| `HISTORY` | 1 小时 | 不限 | 含分钟线；返回的都是已完成 K 线 |
| `NAV` | 6 小时 | 7 天 | 每日公布一次 |
| `PROFILE` | 24 小时 | 7 天 | 静态信息 |
| `HOLDINGS` | 永久 | 不限 | 历史季度不可变 |
| `ESTIMATE` | 30 秒 | 5 分钟 | 跟着报价走，过期就无意义 |
| `FX` | 1 小时 | 7 天 | 汇率日内波动小 |
| `BENCHMARK` | **不缓存** | — | 每次由成分指数历史现算 |
| `LIST` | **不缓存** | — | 列表是流式消费，存了没有读者 |

「不缓存」是显式声明，不是遗漏——见 `cache/base.py` 的 `_CACHE_POLICY`，
每个能力恰好一行，`None` 表示不缓存并写明原因。

### 三态语义

```
命中且新鲜        → 返回
过期 + 回源成功   → 返回新值，写缓存
过期 + 回源失败   → 返回旧值 + stale=true + fetched_at
从未有过          → 抛 UpstreamError
```

`serve_stale_on_error` 默认开启。来源是旧项目 `QuoteCache` 的"过期不丢弃"设计——上游挂了页面还能显示历史价并标记，而不是整页报错。

### 其他

- **单飞**：并发请求同时发现过期时，只放 1 个回源
- **后端**：`MemoryCache`（默认）/ `SqliteCache`（跨进程）
- **单次覆盖**：`max_age` 参数

### 配置示例

```python
from quotestack import MarketData
from quotestack.cache import MemoryCache
from quotestack.models import Capability

client = MarketData(
    cache=MemoryCache(max_entries=20_000),      # 默认 10,000 条，LRU 淘汰
    ttl={Capability.QUOTE: 60, Capability.ESTIMATE: 15},
    max_stale={Capability.QUOTE: 3600},
)
```

**单飞和 stale 回退不是开关**——它们是取数路径的固有行为，没有关闭的选项。
配置项只有三个：缓存实现、TTL 覆盖、容忍期覆盖。

目前只有 `MemoryCache`，**没有持久化实现**：进程重启即冷启动。

**服务形态下**没有调用方写代码，TTL 由 `quotestack.toml` 的 `[ttl]` 段或 `QUOTESTACK_TTL_*` 环境变量提供，server 读取后转成上面的构造参数。详见 [部署与环境 § 配置](09-deployment.md#配置)。

库本身**不读环境变量、不读配置文件**——保持无隐藏输入。

---

## 缓存键

### 键的维度

| 能力 | 键组成 |
|---|---|
| `quote` | `(QUOTE, instrument)` |
| `history` | `(HISTORY, instrument, interval, adjust)` |
| `nav` | `(NAV, instrument)` |
| `profile` | `(PROFILE, instrument)` |
| `holdings` | `(HOLDINGS, instrument, year)` |
| `benchmark` | `(BENCHMARK, instrument, start, end)` |
| `estimate` | `(ESTIMATE, instrument)` |
| `fx` | `(FX, base, quote)` |

`adjust` 必须进键——同一只票的前复权与不复权是两套数字。默认值要**归一化后再进键**，否则 `None` 与 `"qfq"` 会生成两个键。

### `limit` 不进键

同一份数据的不同前缀，按需切片：

```
请求 limit ≤ 已缓存条数  → 切片返回
请求 limit > 已缓存条数  → 回源取更多，覆盖缓存
```

`holdings` 同理：键里放 `year`（一次请求返回整年 4 个季度），分页只是输出层形状。

### 负缓存

`NotFound` 结果缓存 **5 分钟**，避免错误输入反复打上游；新上市品种最多延迟 5 分钟可见。

`Ambiguous` **不缓存**——结果取决于传入的 `expected_name`，参数变了解析就变。

### 版本前缀

```
v1|quote|CN:STOCK:600519
v1|history|CN:STOCK:600519|1d|qfq
v1|holdings|CN:FUND:022430|2026
v1|fx|USD|CNY
```

`CACHE_VERSION` 常量进键。解析逻辑或输出结构变更时加一，整个命名空间自动切换，旧条目自然过期，**不需要写迁移脚本**。

分隔符 `|` 安全，因为 code 与币种都不含它；`instrument.id` 已规范化为 `CN:STOCK:600519`，直接复用。

### 值结构

```python
@dataclass
class CacheEntry:
    value: Any
    fetched_at: datetime
    source: str
```

**不存 `expire_at`**——新鲜度在读取时按当前 TTL 配置计算：

```
age = now - fetched_at
fresh = age < ttl[capability]
```

好处：改 TTL 立即生效；`max_age` 单次覆盖天然支持；少存一个字段。


---

← 上一篇：[数据源与覆盖率](03-sources.md) ｜ 下一篇：[接口与格式契约](05-api.md) →
