# 适配器组织

> quotestack 设计决议 · 第 8 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：✅ 路由表、降级链、冷却、限流均已实现


## 适配器组织

### 三个概念必须分开

| 概念 | 回答的问题 | 由谁决定 |
|---|---|---|
| **源的能力** | 这个数据源能干哪些事？ | 适配器自己声明 |
| **标的的能力** | 这个品种有哪些数据？ | 按规则推导 |
| **实际可用** | 这次能不能拿到？ | 两者交集 + 运行时 |

例：

```
022430（场外基金）
  源能力：东财能做 history        ✅
  标的能力：无交易所代码 → history ❌
  实际：UNSUPPORTED

BTC（加密）
  源能力：Binance 只做 list       ❌
  标的能力：只有 list             ✅
  实际：UNSUPPORTED（问 history 时）
```

把两者混为一谈，就会出现"场外基金去查 K 线"这类错误路由。

### 用 Protocol，不用 ABC

```python
class Quoter(Protocol):
    def quote(self, instruments: list[Instrument]) -> list[Quote]: ...

class Historian(Protocol):
    def history(self, inst, interval, adjust, limit) -> list[Bar]: ...
```

理由：源的能力天然不对称——天天基金没有 K 线，Binance 没有基金画像。用抽象基类会逼出大量 `raise NotImplementedError`，正是要避免的死代码。

**每个源只写自己能做的事。**

```python
class EastMoneySource:
    meta = SourceMeta(
        name="eastmoney",
        capabilities={QUOTE, HISTORY, LIST},
        markets={(STOCK, CN), (STOCK, US)},
        timeout=5.0,
    )

    async def quote(self, instruments): ...
    async def history(self, inst, interval, adjust, limit): ...

class TiantianSource:
    meta = SourceMeta(
        name="tiantian",
        capabilities={NAV, PROFILE, HOLDINGS, ESTIMATE, LIST},
        markets={(FUND, CN)},
        timeout=8.0,        # 大文件，给足时间
    )

class BinanceSource:
    meta = SourceMeta(
        name="binance",
        capabilities={LIST},      # 只有交易对枚举，报价与 K 线未接入
        markets={(CRYPTO, CRYPTO)},
        timeout=5.0,
    )
```

### 结构断言写在解析处

没有统一的结构断言辅助函数。每个解析器在**失败的那一刻**抛
`SchemaChangedError`，并把判断依据带上：

```python
raise SchemaChangedError(
    "eastmoney 'data.diff' is not a list",
    assertion="data.diff is a list",
    sample=response.text[:500],
    url=str(response.url),
)
```

`assertion` 说明期望的结构，`sample` 保留现场，告警时不需要再抓一次。

### 超时由适配器就地声明

各源在类上声明 `timeout`，一眼可见，不做全局配置表。约束：**单源超时 < 总超时 < Java 端超时 < 前端 15s**。

| 源 | 超时 |
|---|---|
| 东财 | 5s |
| 腾讯 | 3s |
| 天天基金 | 8s（614 KB 文件） |
| Binance | 5s |

### 路由表放代码里

```text
# sources/routing.py 的 _ROUTES（节选）
( STOCK, CN, QUOTE )    -> ["eastmoney", "tencent"]
( STOCK, CN, HISTORY )  -> ["eastmoney"]
( FUND,  CN, QUOTE )    -> ["eastmoney", "tencent"]   # 场内基金
( FUND,  CN, HISTORY )  -> ["eastmoney"]
( FUND,  CN, NAV )      -> ["tiantian"]
( FUND,  CN, PROFILE )  -> ["tiantian"]
( FUND,  CN, HOLDINGS ) -> ["tiantian"]
```

**没有 crypto 的 QUOTE / HISTORY 路由**——Binance 只提供交易对枚举，
加密报价尚未接入。`resolve()` 也因此只给 crypto 声明 `LIST`。
路由表由 `tests/test_routing.py` 与 `tests/test_docs.py` 双向校验。


**为什么放代码而不放配置**：路由是设计决策，改动应走 PR；配置化会导致"每个部署一套路由"，问题无法复现。

只允许一种运行时覆盖：

```python
MarketData(
    source_priority={"QUOTE": ["tencent", "eastmoney"]},   # 键是能力名
)
```

**没有 `disabled_sources`**——想去掉某个源，就在优先级列表里不写它。

### 失败兜底链

```
请求
 ├─ 缓存新鲜？            → 返回
 ├─ 源在冷却期？          → 跳过
 ├─ 有旧值且未超 max_stale？ → 回源（短超时）
 │    ├─ 成功             → 新值
 │    └─ 失败             → 返回旧值 + stale，并标记冷却
 └─ 无旧值                → 降级下一个源
      └─ 全部失败         → 抛 UpstreamError（带每个源的失败原因）
```

**三层兜底**

| 层 | 机制 |
|---|---|
| 缓存 stale | 回源失败回退旧值 |
| 多源降级 | 东财 → 腾讯（报价）；K 线只有东财 |
| 部分成功 | `quote_many` 中失败条目单独标记，其余照常 |

**冷却机制（极简熔断，约 15 行）**

```python
_cooldown: dict[str, float] = {}          # source → 解禁时间

def _available(source):
    return _cooldown.get(source, 0) < time.time()

def _mark_failed(source):
    _cooldown[source] = time.time() + 30   # 冷却 30 秒
```

没有状态机、没有 half-open 探测、冷却结束自动恢复。目的只有一个：源挂了之后，不要每次请求都白等一个超时。

**`max_stale` 安全阀**

| 能力 | 上限 |
|---|---|
| quote | 1 天 |
| history | 无限（历史数据无所谓多旧） |
| profile | 7 天 |

超过上限**不再返回旧值，直接抛错**。否则上游挂一周，页面会一直显示一周前的股价且看起来完全正常——这比白屏更危险。

---

---

← 上一篇：[基金能力](07-funds.md) ｜ 下一篇：[部署与环境](09-deployment.md) →
