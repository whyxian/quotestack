# 07 服务化

把库跑成一个 HTTP 服务，给其他语言（比如 Java、Node）调用。

---

## 启动

```bash
uv sync --extra dev --extra server
uv run quotestack-server
```

默认 `127.0.0.1:8000`。

```bash
uv run quotestack-server --host 0.0.0.0 --port 9000
```

---

## 验证

```bash
curl 'http://127.0.0.1:8000/v1/quote?code=600519'
```

```json
{
  "data": {
    "instrument_id": "CN:STOCK:600519",
    "price": "1453.00",
    "currency": "CNY",
    "change": "1.00",
    "change_pct": 0.07,
    "source": "eastmoney",
    "ts": "2026-11-06T16:11:39+08:00",
    "status": "REALTIME",
    "stale": false
  },
  "error": null
}
```

---

## 响应结构

**成功和失败形状一致**，调用方一条判断搞定：

```json
{ "data": { ... }, "error": null }
```

```json
{
  "data": null,
  "error": {
    "code": "UNSUPPORTED",
    "message": "CN:FUND:022430 has no quote data",
    "detail": { "instrument": "CN:FUND:022430", "capability": "QUOTE", "available": ["NAV", "PROFILE"] }
  }
}
```

**HTTP 状态码仍然有效**：

| 状态 | 错误码 | 含义 |
|---|---|---|
| 400 | `INVALID_ARGUMENT` | 参数不合法（含校验失败，不是 FastAPI 默认的 422） |
| 404 | `NOT_FOUND` | 代码不存在 |
| 409 | `AMBIGUOUS` | 有多个候选，需指定 `asset_class` |
| 410 | `DELISTED` | 已退市 |
| 422 | `UNSUPPORTED` | 该标的没这个能力 |
| 429 | `RATE_LIMITED` | 触发上游限流 |
| 502 | `UNAVAILABLE` / `SCHEMA_CHANGED` / `EMPTY_RESPONSE` | 上游失败 |
| 500 | `INTERNAL` | 服务内部错误，重试无效 |
| 503 | `CLIENT_BROKEN` | 所有源结构都变了，需升级库 |
| 504 | `TIMEOUT` | 上游超时 |

> **不要只看 `error` 字段。** 监控、重试、网关限流都依赖状态码。
> 但业务判断请用 `error.code`——它比状态码更精确，多个错误可能映射到同一个状态。

---

## 接口清单

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/v1/resolve` | 解析代码 |
| GET | `/v1/quote` | 单个报价 |
| POST | `/v1/quotes/batch` | 批量报价 |
| GET | `/v1/history` | K 线 |
| GET | `/v1/nav` | 基金净值 |
| GET | `/v1/profile` | 基金画像 |
| GET | `/v1/holdings` | 季度持仓 |
| GET | `/v1/benchmark` | 基准曲线 |
| GET | `/v1/estimate` | 基金估值 |
| GET | `/v1/fx` | 汇率 |
| GET | `/v1/instruments` | 市场列表 |
| GET | `/v1/healthz` | 运行状态 |

### 拿到完整字段定义

契约由代码生成，不会和实现不一致。导出成 OpenAPI 文件：

```bash
uv run quotestack-server --dump-openapi > spec.yaml
```

得到的 `spec.yaml` 可以直接导入 Postman、Apifox、Swagger UI，或者用来生成
Java / TypeScript 客户端。

下面列出每个接口的**核心字段**，够你判断怎么调；完整定义以导出的文件为准。

### 各接口的核心字段

**`/v1/resolve`** → `id` `code` `asset_class` `market` `currency` `confidence` `aliases` `capabilities`

**`/v1/quote`** → `instrument_id` `price` `currency` `change` `change_pct` `source` `ts` `status` `stale`

**`/v1/quotes/batch`** → `results[]`（每项 `ok` `instrument` `quote` `error`）、`fetched_at`

**`/v1/history`** → `bars[]`（`date` `time` `open` `high` `low` `close` `volume` `amount`）、`interval` `adjust` `source`

**`/v1/nav`** → `points[]`（`date` `nav`）、`latest`、`source`

**`/v1/profile`** → `fund_type` `fund_class` `tracking_index` `benchmark` `company` `manager` `custodian` `scale` `inception_date` `as_of` `partial` `missing`

**`/v1/holdings`** → `quarters[]`（`quarter` `as_of` `holdings[]`）、`has_more` `next_before`

**`/v1/benchmark`** → `effective_start` `components_used` `components_dropped` `coverage` `series[]`

**`/v1/estimate`** → `change_pct` `basis` `coverage` `as_of` `explanation` `benchmark_assumption`

**`/v1/fx`** → `base` `quote` `rate` `source` `as_of` `derived`

**`/v1/instruments`** → `items[]`（`code` `name` `asset_class` `market` `currency` `listing_date` `board` `industry` `fund_type` `fund_class`）、`page` `page_size` `has_more` `next_page`

**`/v1/healthz`** → `status` `config` `sources` `cache`

每个字段的详细含义，对应本指南的
[03 行情](03-quotes.md)、[04 基金](04-funds.md)、[05 估值](05-estimate.md)、
[06 全市场列表](06-universe.md)——**同一个字段在库里和 HTTP 里是一回事**。

### 几个例子

```bash
# 批量报价
curl -X POST 'http://127.0.0.1:8000/v1/quotes/batch' \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"code":"600519"},{"code":"AAPL","market":"US"}]}'

# 基金估值
curl 'http://127.0.0.1:8000/v1/estimate?code=022430'

# 季度持仓，翻页
curl 'http://127.0.0.1:8000/v1/holdings?code=166002&limit=4'
curl 'http://127.0.0.1:8000/v1/holdings?code=166002&before=2025Q4'

# 全市场列表
curl 'http://127.0.0.1:8000/v1/instruments?asset_class=STOCK&market=CN&page=1&page_size=100'
```

---

## 配置

### 方式一：配置文件

`quotestack.toml`（放工作目录，或用 `--config` 指定）：

```toml
[server]
host = "0.0.0.0"
port = 8000

[proxy]
url = "http://127.0.0.1:7890"

[ttl]
quote    = 30
history  = 3600
holdings = "never"    # 历史季度不变，永久缓存
```

### 方式二：环境变量

覆盖配置文件：

```bash
QUOTESTACK_SERVER_PORT=9000
QUOTESTACK_PROXY_URL=http://host.docker.internal:7890
QUOTESTACK_TTL_QUOTE=60
```

优先级：**默认值 → 配置文件 → 环境变量 → 命令行参数**。

### 非法配置会拒绝启动

```bash
$ QUOTESTACK_SERVER_PORT=70000 quotestack-server
config error: server.port must be between 1 and 65535
```

**不做静默降级**——配置错了就停下，比跑一个行为诡异的服务好。

---

## 健康检查与监控

```bash
curl 'http://127.0.0.1:8000/v1/healthz'
```

```json
{
  "data": {
    "status": "ok",
    "config": { "ttl": { "quote": 30, "holdings": "never" } },
    "sources": {
      "eastmoney": { "state": "ok", "cooldown_remaining": 0, "timeout": 5.0 },
      "tencent": { "state": "ok", ... }
    },
    "cache": { "entries": 128 }
  },
  "error": null
}
```

**`config` 是当前生效的配置**——改了 TOML 没生效时，先看这里。

```bash
curl 'http://127.0.0.1:8000/metrics'
```

```
quotestack_events_total{event="cache_lookup",level="DEBUG"} 42.0
quotestack_events_total{event="resolve",level="DEBUG"} 18.0
```

---

## Docker

```bash
docker build -t quotestack:0.1.0 .
docker run -d --name quotestack -p 8000:8000 \
  -v quotestack-cache:/data quotestack:0.1.0
```

**容器不继承宿主机的代理**。要访问境外源得显式传：

```bash
docker run -d -p 8000:8000 \
  -e QUOTESTACK_PROXY_URL=http://host.docker.internal:7890 \
  quotestack:0.1.0
```

`host.docker.internal` 在 Mac/Windows 指向宿主机；Linux 需要：

```bash
--add-host=host.docker.internal:host-gateway
```

---

## Java 调用示例

```java
// Spring RestClient
public record ApiResponse<T>(T data, ApiError error) {}
public record ApiError(String code, String message, Map<String, Object> detail) {}

ApiResponse<Quote> response = restClient.get()
    .uri("http://localhost:8000/v1/quote?code={code}&asset_class=STOCK&market=CN", "600519")
    .retrieve()
    .body(new ParameterizedTypeReference<ApiResponse<Quote>>() {});

if (response.error() != null) {
    // 分支判断用 error.code，比状态码更精确
}
```

**金额字段是 `String`**，不是 `BigDecimal` 或 `double`——反序列化成 `String` 再转
`BigDecimal`，精度不丢。
