# 错误模型

> quotestack 设计决议 · 第 6 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)


## 错误模型

```
MarketDataError
├── InputError          → InvalidArgument
├── IdentityError       → NotFound / Ambiguous / Delisted
├── CapabilityError     → Unsupported
├── UpstreamError       → Timeout / RateLimited / Unavailable
│                         / EmptyResponse / SchemaChanged
└── ClientBroken        → 全部源结构都变了（该升级库了）
```

### 处置策略

| 错误 | 重试 | 换源 | HTTP |
|---|---|---|---|
| `InvalidArgument` | ❌ | ❌ | 400 |
| `NotFound` | ❌ | ❌ | 404 |
| `Ambiguous` | ❌ | ❌ | 409 |
| `Delisted` | ❌ | ❌ | 410 |
| `Unsupported` | ❌ | ❌ | 422 |
| `Timeout` | ✅ 1 次 | ✅ | 504 |
| `RateLimited` | 等 `retry_after` | ✅ | 429 |
| `Unavailable` | ✅ | ✅ | 502 |
| `EmptyResponse` | ❌ | ✅ 立即 | 404 |
| `SchemaChanged` | ❌ | ✅ + 告警 | 500 |

**`EmptyResponse` 与 `Unavailable` 必须分开**：东财对 `560000` 返回 `{"rc":0,"data":null}`——HTTP 200、结构正常、就是没这只票。当 `Unavailable` 重试是白等。

### `EmptyResponse` vs `SchemaChanged`

```
结构在，里面没数据      → EmptyResponse   （正常，换源）
结构本身不对/字段没了   → SchemaChanged   （异常，告警）
```

### `SchemaChanged` 处理

每个适配器声明最小结构断言：

| 源 | 断言 |
|---|---|
| 腾讯 | 含 `v_`，`~` 切分后 `len >= 53` |
| 东财 K线 | `data.klines` 是 list，元素 ≥ 7 字段 |
| 天天基金 | 存在 `Data_netWorthTrend = [` |
| Binance | 数组的数组，内层 `len >= 6` |

失败时：

1. 不重试，立即切下一个源
2. 记 ERROR 日志，带 `source` / `capability` / `instrument` / `assertion` / `sample`(≤500 字符) / `url`
3. 计入 `/healthz` 的 `recent_schema_changes`
4. 全部源都 SchemaChanged → 抛 `ClientBroken`

### 重试归属

服务内部只重试 **1 次**，且仅在没有备用源时。

- 有备用源 → 不重试，直接切
- 无备用源 → 重试 1 次
- 限流 → 不重试

避免每层重试导致请求放大（3×3=9 次上游调用）。

---

---

← 上一篇：[接口与格式契约](05-api.md) ｜ 下一篇：[基金能力](07-funds.md) →
