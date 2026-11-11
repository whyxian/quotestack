# quotestack 代码审查复核（2026-11-11）

> 复核对象：[CR-2026-11-10](CR-2026-11-10.md)
> 复核范围：`src/quotestack/` 全部源码、测试、关键接口行为
> 方法：重跑 `ruff` / `mypy` / `pytest --cov`，逐项检查原发现，并用真实 `MarketData` + fake source 做接口级复现
> 结论：原 24 项里 **17 项已修、6 项部分修、1 项回归（CR-11）**；另新引入 **1 项 P0（CR-25）**

---

## 0. 结论

这一轮修复的质量比数量更好：缓存键、分页、批量隔离、估值降级、限流覆盖、时间戳、代理脱敏、同步生命周期都有对应代码和回归测试。测试从 298 个增加到 361 个，覆盖率从 91.34% 升到 92.22%。

但有一个**新引入的 P0**：`/v1/history` 在真实客户端下会 500，原因是 `source_for()` 的缓存键与 `history` 的缓存键不一致。原来的 CR-11 修了“硬编码 source”，却把 history 路由修坏了；现有测试用的是 fake client，没发现。

---

## 1. 复核表

| 原 ID | 状态 | 复核结果 |
|---|---|---|
| CR-01 `history` 缓存键 | ✅ 已修 | 键包含 `limit`；新增 `test_history_limit_changes_the_answer_not_the_cache` |
| CR-02 `/v1/instruments` `has_more` | ✅ 已修 | 多取一条判断；新增 `has_more` 测试 |
| CR-03 crypto 能力/路由 | ✅ 已修 | crypto 能力改为只有 `LIST`，指南同步；`quote("BTC")` 现在抛 `UNSUPPORTED` |
| CR-04 批量隔离/冷却 | ✅ 已修 | 源返回部分结果，缺失项换源；只对 retryable 错误冷却；新增 `test_batch.py` |
| CR-05 参数校验 | ✅ 已修 | `history` / `nav` / `iter_instruments` 均校验 `limit` / `page_size`；新增测试 |
| CR-06 估值抛异常 | ✅ 已修 | 整个推导包在 `try` 里；新增“估算中断”测试 |
| CR-07 限流覆盖 | 🟡 部分 | 主要路径已加 `_bucket.acquire()`；`_index_history` 仍是直连 |
| CR-08 缓存无界 | ✅ 已修 | `MemoryCache(max_entries=10_000)` + LRU；新增淘汰测试 |
| CR-09 `Quote.status` | 🟡 部分 | `status_for()` 已按时间区分 REALTIME / HISTORICAL；`UNAVAILABLE` 仍无产生路径 |
| CR-10 `CLIENT_BROKEN` | 🟡 部分 | 单条 `quote` 已实现；`quote_many` 仍把“全部 schema 变更”归为 UNAVAILABLE |
| CR-11 响应 `source` | ❌ 回归 | `/v1/nav` 正常；`/v1/history` 因键不匹配返回 500（见 CR-25） |
| CR-12 代理泄露 | ✅ 已修 | `_redact_proxy()` + 测试 |
| CR-13 时间戳伪造 | ✅ 已修 | Eastmoney / Tencent 解析失败改抛 `SchemaChangedError` |
| CR-14 指数/FX 缓存 | 🟡 部分 | 已加限流；`resolve_index` / `_index_history` / `fx` 仍无缓存 |
| CR-15 关闭竞态 | ✅ 已修 | `cancel_inflight` 改为 async 并 `gather`；新增测试 |
| CR-16 同步生命周期 | ✅ 已修 | 先构造 client、loop 异常处理、close 超时；新增测试 |
| CR-17 holdings `has_more` | ✅ 已修 | 多取一个季度判断；新增测试 |
| CR-18 `Retry-After` | ✅ 已修 | 解析秒/HTTP date，`cool_for()` 使用；新增测试 |
| CR-19 标识边界 | 🟡 部分 | `BRK.B` / `BTCUSDT` 已修；`166002` 仍获得 QUOTE 能力，测试仍固化该行为 |
| CR-20 测试缺口 | 🟡 部分 | 361 个用例、92.22%；server 85%、sync 74%；history source 仍用 fake client |
| CR-21 `as_of` / `stale_inputs` | ✅ 收敛 | `stale_inputs` 删除，`as_of` 文档改为“计算时刻” |
| CR-22 死配置/指标 | ✅ 已修 | `cache_dir`、`REQUEST_COUNTER` 删除；`_TTL_NAMES` 补 RESOLVE/LIST |
| CR-23 Profile/NAV/OHLC | ✅ 已修 | `missing` 补 company；`_format_nav`；`_to_bar` 加结构断言 |
| CR-24 文档漂移 | ✅ 基本 | crypto / status / 限流耗时 / 代理等已同步 |
| **CR-25** | **❌ 新 P0** | **`/v1/history` 在真实客户端下 500** |

---

## 2. 新 P0：`/v1/history` 在真实客户端下 500

### 现象

用真实 `MarketData` + fake source 调 `GET /v1/history`：

```text
ResponseValidationError: 1 validation error
  {'type': 'string_type', 'loc': ('response', 'data', 'source'),
   'msg': 'Input should be a valid string', 'input': None}
```

HTTP 层最终返回：

```text
500 {"data":null,"error":{"code":"INTERNAL","message":"internal error",...}}
```

也就是说，**所有 `/v1/history` 请求都会失败**，不是某只票的数据问题。

### 原因

`history` 的缓存键（`src/quotestack/client/__init__.py:388-402`）是：

```text
v1|history|<instrument>|<interval>|<adjust>|<limit>
```

但 `source_for()`（`src/quotestack/client/__init__.py:1007-1009`）只接受 `capability + instrument_id`，拼出来的键是：

```text
v1|history|<instrument>
```

两者永远不相等，`source_for()` 返回 `None`；`BarsPayload.source` 是 `str`，Pydantic 校验失败，路由抛 500。

用真实客户端可以直接验证：

```text
source_for(HISTORY, CN:STOCK:600519) -> None
cache keys: ['v1|history|CN:STOCK:600519|1d|qfq|3']
```

### 为什么测试没发现

`tests/test_server.py:523` 的 `test_history_reports_the_source_that_answered` 用的是 `_FakeClient`，它的 `source_for()` 固定返回 `"eastmoney"`（`:43`），没有走真实缓存键。

### 建议修法

1. 让 `MarketData.source_for()` / `FetchPolicy.source_for()` 接受额外的键片段，server 传入 `interval`、`adjust`、`limit`；或
2. 给 `Bar` 增加 `source`，由源在构造时写入；或
3. 把 `BarsPayload.source` 改为可空，`None` 时返回 `unknown`，但这是最后手段。

推荐 1 或 2；同时新增一个真实 `MarketData` + fake source 的 `/v1/history` 集成测试，而不是继续用 `_FakeClient`。

---

## 3. 仍然值得跟进的部分

### CR-07 / CR-14：`_index_history` 仍绕过令牌桶，且没有缓存

`src/quotestack/client/__init__.py:737-746` 直接调 `source.history_by_secid()`。`benchmark()` 每个基准成分都会走这里（`:675-684`），所以一次基准曲线可能连续打多个请求，不受 4/s 限制。`resolve_index` / `fx` 现在有限流但无缓存，重复调用仍会重复打上游。

建议：给 `_index_history` 补 `_bucket.acquire()`，并把指数名→secid、FX 报价纳入现有缓存（`Capability.RESOLVE` 的 TTL 已在表里）。

### CR-09：`UNAVAILABLE` 仍无产生路径

`status_for()` 只返回 `REALTIME` / `HISTORICAL`；`QuoteStatus.UNAVAILABLE` 仍然只出现在枚举和 `is_usable` 里。`guide/03-quotes.md:22` 仍列出 `UNAVAILABLE`。要么在“确实拿不到价格但需要返回占位 Quote”时设置它，要么把它从文档/枚举里删掉。

### CR-10：`quote_many` 的“全部 schema 变更”仍不是 CLIENT_BROKEN

`_fetch_group`（`src/quotestack/client/__init__.py:1069-1102`）对 `UpstreamError` 一视同仁，全部失败后统一返回 `UNAVAILABLE: no source served ...`。单条 `quote` 已经有 `ClientBrokenError` 分支（`fetch.py:228-242`），批量路径应复用同一判断，否则同一个错误模型在批量接口上是两套语义。

### CR-19：`166002` 仍被赋予 QUOTE

`_resolve_cn_fund()` 仍按前缀把 `16` 开头的基金归为 listed，`tests/test_identity.py:60-67` 也继续断言 `Capability.QUOTE in ...`。这可能是“前缀不可靠，先给能力、失败再降级”的取舍，但它会让 `quote("166002")` 走无意义的源。建议要么改为 `PARTIAL` 能力/运行时探测，要么在文档里明确这个已知误判。

### 其他小项

- `max_age` 仍没有库层校验；server 有 `ge=0`，但 `history(max_age=-1)` 会静默变成 EXPIRED。建议与 `limit` 一样统一校验。
- `pydantic` 仍在核心依赖里，但 `src/` 里只有 `server/schemas.py` 使用；可以移到 `server` extra（fastapi 会带进来）。
- `sync.py` 覆盖率 74%，`server/app.py` 85%；新增测试集中在修复点，生命周期/异常路径仍可补。
- `source_for()` 在缓存被 LRU 淘汰时也会返回 `None`；即使修好 history 键，响应层也应定义 `None` 的降级值，避免再次 500。

---

## 4. 测试与基线

```text
ruff check .                     通过
mypy src                         通过（53 files）
pytest -q                        361 collected（4 skipped）
pytest --cov=quotestack          92.22%
```

关键覆盖率：

| 模块 | 覆盖率 |
|---|---:|
| 全库 | 92.22% |
| `server/app.py` | 85% |
| `sync.py` | 74% |
| `sources/tiantian.py` | 81% |
| `sources/eastmoney/quotes.py` | 79% |

新增测试确实覆盖了大部分修复点：`test_batch.py`、`test_cache.py`、`test_client_edges.py`、`test_sync.py`、`test_transport.py`。但 `/v1/history` 的 source 测试仍是 fake client，这是本次回归漏掉的直接原因。

---

## 5. 建议顺序

1. **CR-25（P0）**：修 `source_for` 键或给 `Bar` 加 source，补真实客户端集成测试。
2. **CR-10 / CR-09**：统一批量 `ClientBroken` 语义；决定 `UNAVAILABLE` 是删还是实现。
3. **CR-07 / CR-14**：`_index_history` 限流 + 指数/FX 缓存。
4. **CR-19**：`166002` 的能力策略定案。
5. **P3**：`max_age` 校验、pydantic 依赖、覆盖率补强。

---

## 6. 一句话

**这轮修复把原来的 P0/P1 基本补上了，测试也明显变强；但 `source_for` 与 `history` 缓存键的错位是一个新引入的接口级 P0——修完它，再谈“可以发版”。**
