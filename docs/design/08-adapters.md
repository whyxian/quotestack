# 适配器组织

> quotestack 设计决议 · 第 8 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)


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

USDG（加密）
  源能力：OKX 能做 history        ✅
  标的能力：有 K 线               ✅
  实际：看运行时（OKX 需代理）
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
    name = "eastmoney"
    capabilities = {QUOTE, HISTORY, RESOLVE, FX}
    markets = {(STOCK, CN), (STOCK, US), (FUND, CN)}
    needs_proxy = False
    timeout = 5.0

    def quote(self, instruments): ...
    def history(self, inst, interval, adjust, limit): ...
    def _assert_schema(self, data, capability): ...   # 就地断言

class TiantianSource:
    name = "tiantian"
    capabilities = {NAV, PROFILE, HOLDINGS}
    markets = {(FUND, CN)}
    needs_proxy = False
    timeout = 8.0        # 大文件，给足时间

class BinanceSource:
    name = "binance"
    capabilities = {QUOTE, HISTORY}
    markets = {(CRYPTO, CRYPTO)}
    needs_proxy = False  # data-api.binance.vision 国内可达
    timeout = 5.0
```

### 结构断言放在适配器内部

`_assert_schema` 是"这个源的知识"，与解析代码放在一起，失败即抛 `SchemaChanged`。不做集中式断言表。

### 超时由适配器就地声明

各源在类上声明 `timeout`，一眼可见，不做全局配置表。约束：**单源超时 < 总超时 < Java 端超时 < 前端 15s**。

| 源 | 超时 |
|---|---|
| 东财 | 5s |
| 腾讯 | 3s |
| 天天基金 | 8s（614 KB 文件） |
| Binance | 5s |
| CoinGecko | 5s |

### 路由表放代码里

```python
ROUTES = {
    (STOCK, CN,  QUOTE):     ["eastmoney", "tencent"],
    (STOCK, CN,  HISTORY):   ["eastmoney"],
    (STOCK, US,  QUOTE):     ["eastmoney", "tencent"],
    (STOCK, US,  HISTORY):   ["eastmoney", "tencent"],
    (FUND,  CN,  NAV):       ["tiantian"],
    (FUND,  CN,  PROFILE):   ["tiantian"],
    (CRYPTO, CRYPTO, QUOTE): ["binance", "okx", "coingecko"],
    (CRYPTO, CRYPTO, HISTORY):["binance", "okx", "coingecko"],
}
```

**为什么放代码而不放配置**：路由是设计决策，改动应走 PR；配置化会导致"每个部署一套路由"，问题无法复现。

只允许两种运行时覆盖：

```python
MarketData(
    source_priority={"crypto": ["coingecko", "binance"]},
    disabled_sources={"okx"},
)
```

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
| 多源降级 | 东财 → 腾讯；Binance → OKX |
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
