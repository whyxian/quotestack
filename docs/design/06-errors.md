# 错误模型

> quotestack 设计决议 · 第 6 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：✅ 错误模型与 HTTP 映射均已实现


## 错误模型

```
MarketDataError                    基类，code = MARKETDATA_ERROR
├── InvalidArgumentError           参数不对，重试无用
├── NotFoundError                  代码不存在
├── AmbiguousError                 有多个候选
├── DelistedError                  已退市
├── UnsupportedError               该标的没这个能力
├── ClientBrokenError              所有源结构都变了（该升级库）
├── InternalError                  库或服务自身出错
└── UpstreamError                  上游失败的总类，retryable = True
    ├── TimeoutError
    ├── UnavailableError
    ├── RateLimitedError           asks for backoff，retryable = False
    ├── EmptyResponseError         源有响应但没这条数据
    ├── SchemaChangedError         载荷结构变了
    └── UnauthorizedError          源要鉴权
```

**没有 `InputError` / `IdentityError` / `CapabilityError` 这类中间层**——
只有 `UpstreamError` 一个中间类，因为它承载「可重试」这个共同语义。
其余错误直接挂在基类下。

### 处置策略

| 错误 | 重试 | 换源 | HTTP |
|---|---|---|---|
| `InvalidArgument` | ❌ | ❌ | 400 |
| `NotFound` | ❌ | ❌ | 404 |
| `Ambiguous` | ❌ | ❌ | 409 |
| `Delisted` | ❌ | ❌ | 410 |
| `Unsupported` | ❌ | ❌ | 422 |
| `Timeout` | ❌ 不重试同一个源 | ✅ 立即换 | 504 |
| `RateLimited` | 等 `retry_after` | ✅ | 429 |
| `Unavailable` | ✅ | ✅ | 502 |
| `EmptyResponse` | ❌ | ✅ 立即 | 502 |
| `SchemaChanged` | ❌ | ✅ + 告警 | 502 |
| `Unauthorized` | ❌ | ✅ | 502 |
| `ClientBroken` | ❌ | — | 503 |
| `Internal` | ❌ | — | 500 |

**任何错误都不重试同一个源**——失败即换下一个。重试同一源只会在它已经超时或
限流时再加一次压力，而换源的成本一样低。

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

**服务内部一次都不重试。**

- 有备用源 → 直接切下一个源
- 没有备用源 → 失败即返回，由调用方决定
- 限流 → 冷却该源，换下一个

理由：重试同一源在它刚超时或限流时只会加压力，而换源的成本一样低。
多层重试还会放大请求（3 层 × 3 次 = 9 次上游调用）。

调用方要重试时，看 `exc.retryable` 决定——那是**调用方**的策略，不是库的。

---

---

← 上一篇：[接口与格式契约](05-api.md) ｜ 下一篇：[基金能力](07-funds.md) →
