# quotestack 代码审查复核（2026-11-11）

> 复核对象：[CR-2026-11-10](CR-2026-11-10.md)
> 复核范围：`src/quotestack/` 全部源码、测试、关键接口行为
> 方法：重跑 `ruff` / `mypy` / `pytest --cov`，逐项检查原发现，并用真实 `MarketData` + fake source 做接口级复现
> 结论：原 24 项里 **20 项已修、4 项部分修**；CR-25（`/v1/history` 500）已修，当前没有新的 P0

---

## 0. 结论

这一轮把上一份复核里唯一的新 P0 也修掉了：`/v1/history` 现在在真实 `MarketData` 下返回 200，`source` 是实际应答的源。

当前基线：

```text
ruff check .                     通过
mypy src                         通过（53 files）
pytest -q                        367 collected（4 skipped）
pytest --cov=quotestack          92.51%
```

剩下的都是 P2/P3：`fx` / 基准历史没有缓存、`UNAVAILABLE` 状态没有产生路径、`166002` 的报价能力取舍，以及测试覆盖的最后一公里。

---

## 1. 复核表

| 原 ID | 状态 | 复核结果 |
|---|---|---|
| CR-01 `history` 缓存键 | ✅ 已修 | 键包含 `limit`；回归测试存在 |
| CR-02 `/v1/instruments` `has_more` | ✅ 已修 | 多取一条判断；分页测试覆盖 |
| CR-03 crypto 能力/路由 | ✅ 已修 | crypto 能力改为只有 `LIST`；`quote("BTC")` 抛 `UNSUPPORTED` |
| CR-04 批量隔离/冷却 | ✅ 已修 | 部分结果 + 换源；只对 retryable 错误冷却 |
| CR-05 参数校验 | ✅ 已修 | `limit` / `page_size` / `max_age` 均有校验 |
| CR-06 估值抛异常 | ✅ 已修 | 整个推导包在 `try` 里；有“估算中断”测试 |
| CR-07 限流覆盖 | ✅ 已修 | `fx` / 估值内部 / `iter_instruments` / `_index_history` 都过令牌桶 |
| CR-08 缓存无界 | ✅ 已修 | `MemoryCache(max_entries=10_000)` + LRU |
| CR-09 `Quote.status` | 🟡 部分 | `status_for()` 区分 REALTIME / HISTORICAL；`UNAVAILABLE` 仍无产生路径 |
| CR-10 `CLIENT_BROKEN` | ✅ 已修 | 单条与批量路径都区分“全部 schema 变更” |
| CR-11 响应 `source` | ✅ 已修 | `source_for()` 接受额外键片段；`/v1/history` 真实客户端返回 200 |
| CR-12 代理泄露 | ✅ 已修 | `_redact_proxy()` + 测试 |
| CR-13 时间戳伪造 | ✅ 已修 | 解析失败抛 `SchemaChangedError` |
| CR-14 指数/FX 缓存 | 🟡 部分 | `resolve_index` 已缓存；`fx` 与基准历史仍无缓存 |
| CR-15 关闭竞态 | ✅ 已修 | `cancel_inflight` 改为 async 并等待 |
| CR-16 同步生命周期 | ✅ 已修 | 构造顺序、loop 异常处理、close 超时 |
| CR-17 holdings `has_more` | ✅ 已修 | 多取一个季度判断 |
| CR-18 `Retry-After` | ✅ 已修 | 解析秒/HTTP date，`cool_for()` 使用 |
| CR-19 标识边界 | 🟡 部分 | `BRK.B` / `BTCUSDT` 已修；`166002` 仍获得 QUOTE 能力 |
| CR-20 测试缺口 | 🟡 部分 | 367 用例、92.51%；server 85%、sync 74%；history source 仍用 fake client |
| CR-21 `as_of` / `stale_inputs` | ✅ 收敛 | `stale_inputs` 删除，`as_of` 文档改为“计算时刻” |
| CR-22 死配置/指标/依赖 | ✅ 已修 | `cache_dir`、`REQUEST_COUNTER` 删除；核心依赖只剩 httpx |
| CR-23 Profile/NAV/OHLC | ✅ 已修 | `missing` 补 company；`_format_nav`；`_to_bar` 加结构断言 |
| CR-24 文档漂移 | ✅ 基本 | crypto / status / 限流耗时 / 代理等已同步 |
| **CR-25** `/v1/history` 500 | ✅ 已修 | 键片段补齐，真实客户端验证返回 200 |

---

## 2. 已验证的 CR-25 修复

用真实 `MarketData` + fake source 调 `/v1/history`：

```text
200
{"bars":[...],"interval":"1d","adjust":"qfq","source":"fake","fetched_at":"..."}
```

`source_for()` 现在接受 `interval/adjust/limit` 三个额外片段，server 传入的值与 `history` 写缓存时一致；`BarsPayload.source` 也改为可空，缓存被 LRU 淘汰时不会再把 `None` 变成 500。

**唯一的小遗憾**：`tests/test_server.py:523` 的 history source 测试仍用 `_FakeClient.source_for()` 固定返回 `"eastmoney"`，没有覆盖真实缓存键。建议补一个真实 `MarketData` + fake source 的集成用例，否则同类键错位还可能再发生。

---

## 3. 仍然值得跟进的部分

### CR-14：`fx` 与基准历史没有缓存

- `resolve_index` 现在有 `Capability.RESOLVE` 缓存（7 天 TTL），这是对的。
- `fx` 仍然每次全量拉取 FX 报价；`benchmark` 的 `_index_history` 每个成分每次重新拉取。两者都有限流，但重复调用会稳定地打上游。
- 建议把 FX 纳入 `Capability.FX`（已有 1 小时 TTL），把基准历史按 `(secid, start, end)` 缓存；后者要注意区间组合会膨胀，最好按“最近 N 天”归一。

### CR-09：`UNAVAILABLE` 仍没有产生路径

`status_for()` 只返回 `REALTIME` / `HISTORICAL`；`QuoteStatus.UNAVAILABLE` 仍只出现在枚举、`is_usable` 和 server schema 的 Literal 里。指南已经不再把它当作 quote 状态承诺，所以这不是用户可见的错误；但既然枚举还在，建议二选一：

- 在“确实拿不到价格、又必须返回 Quote 占位”时设置它；或
- 从枚举、`is_usable`、schema Literal 里删掉，避免下一个人以为它可用。

### CR-19：`166002` 的报价能力仍是取舍

`_resolve_cn_fund()` 仍按前缀把 `16` 开头的基金归为 listed，`tests/test_identity.py:60-67` 也继续断言 `Capability.QUOTE in ...`。如果这是“前缀不可靠，先给能力、失败再降级”的有意选择，建议在文档或注释里明确；否则 `quote("166002")` 会走无意义的源。

### 批量路径的两个边缘

- `quote_many` 仍只接受**新鲜**缓存；如果缓存是 stale、所有源又失败，它会返回 `UNAVAILABLE`，而单条 `quote` 会返回 stale。两者语义不同，建议在文档里说明，或让批量也走 stale 回退。
- `_fetch_group` 的 `broken` 判断是“所有错误都是 SCHEMA_CHANGED”。如果源 A 返回了部分结果、源 B 才 schema 变更，剩余条目会被标成 `CLIENT_BROKEN`，尽管 A 是健康的。更稳的判断是“没有任何源成功返回过数据，且所有尝试都是 schema 变更”。

### 测试的最后一公里

- `server/app.py` 85%、`sync.py` 74%；`sync` 的大部分方法仍没有专门用例。
- history source 测试仍是 fake client（见上）。
- `quote_many` stale 回退、批量 `CLIENT_BROKEN` 的混合场景没有用例。
- 覆盖率 92.51% 已经不低，但这些缺口恰好是“契约语义”而不是“行覆盖”。

---

## 4. 建议顺序

1. 补真实 `MarketData` 的 `/v1/history` 集成测试（防止 CR-25 复发）。
2. `fx` / 基准历史缓存（CR-14）。
3. 决定 `UNAVAILABLE` 的去留，统一 `quote_many` 的 stale 语义。
4. 给 `166002` 的能力策略定案。
5. 补 `sync` 与批量边缘的测试。

---

## 5. 一句话

**CR-25 已修，当前没有新的 P0；剩下的都是性能、语义一致性和测试覆盖的收尾，可以按普通 issue 处理，不必再阻塞发版。**
