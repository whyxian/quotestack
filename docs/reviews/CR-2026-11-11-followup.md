# quotestack 代码审查复核（2026-11-11）

> 复核对象：[CR-2026-11-10](CR-2026-11-10.md)
> 复核范围：`src/quotestack/` 全部源码、测试、关键接口行为
> 方法：重跑 `ruff` / `mypy` / `pytest --cov`，逐项检查原发现，并用真实 `MarketData` + fake source 做接口级复现
> 结论：原 24 项里 **21 项已修、3 项部分修**；CR-25（`/v1/history` 500）已修，当前没有新的 P0

---

## 0. 当前基线

```text
ruff check .                     通过
mypy src                         通过（53 files）
pytest -q                        372 collected（4 skipped）
pytest --cov=quotestack          93.26%
```

`/v1/history` 用真实 `MarketData` + fake source 验证：

```text
200
{"bars":[...],"interval":"1d","adjust":"qfq","source":"fake","fetched_at":"..."}
```

---

## 1. 复核表

| 原 ID | 状态 | 复核结果 |
|---|---|---|
| CR-01 `history` 缓存键 | ✅ 已修 | 键包含 `limit`；回归测试存在 |
| CR-02 `/v1/instruments` `has_more` | ✅ 已修 | 多取一条判断；分页测试覆盖 |
| CR-03 crypto 能力/路由 | ✅ 已修 | crypto 能力只有 `LIST`；`quote("BTC")` 抛 `UNSUPPORTED` |
| CR-04 批量隔离/冷却 | ✅ 已修 | 部分结果 + 换源；只对 retryable 错误冷却 |
| CR-05 参数校验 | ✅ 已修 | `limit` / `page_size` / `max_age` 均有校验 |
| CR-06 估值抛异常 | ✅ 已修 | 整个推导包在 `try` 里；有“估算中断”测试 |
| CR-07 限流覆盖 | ✅ 已修 | `fx` / 估值内部 / `iter_instruments` / `_index_history` 都过令牌桶 |
| CR-08 缓存无界 | ✅ 已修 | `MemoryCache(max_entries=10_000)` + LRU |
| CR-09 `Quote.status` | ✅ 已修 | `UNAVAILABLE` 已从枚举和 schema 删除，只保留 REALTIME / HISTORICAL |
| CR-10 `CLIENT_BROKEN` | ✅ 已修 | 单条与批量路径都区分“全部 schema 变更” |
| CR-11 响应 `source` | ✅ 已修 | `source_for()` 接受额外键片段；真实 `/v1/history` 返回 200 |
| CR-12 代理泄露 | ✅ 已修 | `_redact_proxy()` + 测试 |
| CR-13 时间戳伪造 | ✅ 已修 | 解析失败抛 `SchemaChangedError` |
| CR-14 指数/FX 缓存 | 🟡 部分 | `resolve_index` 与 FX 已缓存；基准历史仍无缓存；FX 无 single-flight |
| CR-15 关闭竞态 | ✅ 已修 | `cancel_inflight` 改为 async 并等待 |
| CR-16 同步生命周期 | ✅ 已修 | 构造顺序、loop 异常处理、close 超时 |
| CR-17 holdings `has_more` | ✅ 已修 | 多取一个季度判断 |
| CR-18 `Retry-After` | ✅ 已修 | 解析秒/HTTP date，`cool_for()` 使用 |
| CR-19 标识边界 | 🟡 部分 | `BRK.B` / `BTCUSDT` 已修；`166002` 仍获得 QUOTE 能力 |
| CR-20 测试缺口 | 🟡 部分 | 372 用例、93.26%；server 85%、sync 92%；仍有批量语义用例缺口 |
| CR-21 `as_of` / `stale_inputs` | ✅ 收敛 | `stale_inputs` 删除，`as_of` 文档改为“计算时刻” |
| CR-22 死配置/指标/依赖 | ✅ 已修 | `cache_dir`、`REQUEST_COUNTER` 删除；核心依赖只剩 httpx |
| CR-23 Profile/NAV/OHLC | ✅ 已修 | `missing` 补 company；`_format_nav`；`_to_bar` 加结构断言 |
| CR-24 文档漂移 | ✅ 基本 | crypto / status / 限流耗时 / 代理等已同步 |
| **CR-25** `/v1/history` 500 | ✅ 已修 | 键片段补齐；真实客户端用例已补 |

---

## 2. CR-25 与测试

`source_for()` 现在接受 `interval/adjust/limit`，server 传入的值与 `history` 写缓存时一致；`BarsPayload.source` 也改为可空，缓存被 LRU 淘汰时不会再把 `None` 变成 500。

真实客户端用例在 `tests/test_server.py:551`（`test_history_route_works_with_a_real_client`），旧的 fake 版本已删除。

---

## 3. 仍然值得跟进的部分

### CR-14：基准历史还没有缓存

- `resolve_index` 已有 `Capability.RESOLVE` 缓存（7 天 TTL）。
- FX 已接 `Capability.FX` 缓存（1 小时 TTL），并有大小写不敏感的用例。
- **但 FX 缓存没有 single-flight**：顺序重复调用会命中缓存，同时发起的 10 个 `fx("USD","CNY")` 仍可能全部 miss、全部打上游。页面如果并发渲染多个美元资产，缓存不一定能挡住。
- `benchmark` 的 `_index_history` 每次仍重新拉取。缓存键要包含 `(secid, start, end)`，不同区间会产生组合爆炸；建议按“最近 N 天”或按月切分归一，留作独立 issue 更合适。

### CR-19：`166002` 的报价能力仍是取舍

`_resolve_cn_fund()` 按前缀把 `16` 开头的基金归为 listed，`tests/test_identity.py:60-67` 也继续断言 `Capability.QUOTE in ...`。`resolve()` 是纯离线规则，无法知道它实际是场外；`PARTIAL` + 指南警告是合理取舍。建议在注释/文档里明确“这是已知误判，失败后降级”，不要为了它加网络探测。

### 批量路径：`CLIENT_BROKEN` 的剩余边角

你举的场景（源 A 部分成功、源 B schema）已经修好：当前判断是 `attempted == schema_failures`，源 A 计入 `attempted` 但不在 `schema_failures`，结果为 false。

还剩一个更窄的边角：`attempted` 不包含冷却中/未配置的源。如果源 A schema、源 B 正在冷却（之前是超时），`attempted={A}`、`schema_failures={A}`，仍会报 `CLIENT_BROKEN`，尽管 B 并没有“结构变更”。如果要严格，条件应改成“所有 eligible 候选源都抛了 `SchemaChanged`”：

```text
eligible = {name for name in candidates if name in self._sources}
broken = bool(eligible) and schema_failures == eligible
```

这会把冷却中的源算作“未证明结构变更”，从而回退到 `UNAVAILABLE`。

### 批量 stale：设计取舍，但建议写清楚

`quote_many` 仍只接受新鲜缓存；stale 且所有源失败时返回 `UNAVAILABLE`，而单条 `quote` 会返回 `stale=True` 的旧值。这个取舍可以接受，但应在 `quote_many` docstring 或指南里明确，否则调用方会以为两者一致。

### 测试的最后一公里

- `server/app.py` 85%、`sync.py` 92%；`sync` 已有 `test_every_sync_method_delegates`，比之前好很多。
- 仍缺：`quote_many` 的 stale 回退、批量 `CLIENT_BROKEN` 的混合场景、FX 并发 single-flight。
- 覆盖率 93.26% 已经不低，这些缺口是“契约语义”，不是行覆盖。

---

## 4. 建议顺序

1. FX single-flight（如果页面会并发取汇率）。
2. 基准历史缓存（按区间归一，留 issue）。
3. `CLIENT_BROKEN` 的冷却源边角。
4. `quote_many` stale 语义写清楚。
5. `166002` 的已知限制写进注释/文档。

---

## 5. 一句话

**21 项已修、3 项部分修，CR-25 已修，当前没有 P0；剩下的是 FX 并发去重、基准历史缓存和两处语义边角，按普通 issue 收尾即可。**
