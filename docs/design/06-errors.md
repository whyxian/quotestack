# 错误模型

> quotestack 设计决议 · 第 6 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：✅ 错误模型与 HTTP 映射均已实现


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
| `EmptyResponse` | ❌ | ✅ 立即 | 502 |
| `SchemaChanged` | ❌ | ✅ + 告警 | 502 |
| `Unauthorized` | ❌ | ✅ | 502 |
| `ClientBroken` | ❌ | — | 503 |
| `Internal` | ❌ | — | 500 |

**`EmptyResponse` 与 `Unavailable` 必须分开**：东财对 `560000` 返回 `{"rc":0,"data":null}`——HTTP 200、结构正常、就是没这只票。当 `Unavailable` 重试是白等。

### HTTP 响应形状

错误统一包在 `error` 字段里，与成功响应同形（详见 [05-api](05-api.md#74-统一响应结构)）：

```json
HTTP 404
{
  "data": null,
  "error": {
    "code": "NOT_FOUND",
    "message": "instrument not found",
    "detail": { "code": "999999", "market": "CN" }
  }
}
```

- `code`：稳定字符串，跨语言可用
- `message`：人读描述
- `detail`：结构化上下文（哪个源、第几次尝试、缺失哪些字段）

**HTTP 状态码仍按上表设置**，不改成 200——监控与网关依赖它。

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
