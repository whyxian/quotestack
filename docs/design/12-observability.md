# 日志与可观测性

> quotestack 设计决议 · 第 12 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：✅ 库侧事件、`/metrics`、启动快照均已实现

目标不是"日志别太吵"，而是**出事时一次给全**——日志的主要读者是排查问题的人和 AI。

---

## 1. 库不配置日志（硬约束）

库只声明 logger、只发事件，**不配置 handler、不设 level、不写文件**。

```python
logger = logging.getLogger("quotestack.eastmoney")
logger.info("batch", extra={...})
```

在库里调 `logging.basicConfig()` 或往 root logger 挂 handler，会污染宿主程序，属于明确禁止。

HTTP 壳是应用，由它配置输出格式与级别。

## 2. 事件清单

不要到处写自由文本，用固定事件名，便于 grep 与聚合。

| 事件 | 级别 | 字段 |
|---|---|---|
| `startup` | INFO | `sources` |
| `resolve` | DEBUG | `code`, `market`, `asset_class`, `instrument`, `confidence`, `aliases` |
| `cache_lookup` | DEBUG | `key`, `state`, `capability` |
| `stale_served` | WARNING | `capability`, `key`, `source` |
| `cooldown` | WARNING | `source`, `action`, `duration` |
| `fallback` | DEBUG | `capability`, `from_source`, `to_source` |
| `upstream_request` | DEBUG | `source`, `method`, `url` |
| `batch` | DEBUG | `count` |
| `schema_changed` | ERROR | `capability`, `source`, `assertion` |
| `all_sources_failed` | ERROR | `capability`, `key`, `reason`, `attempts` |

所有事件都额外带一个 `hint` 字段，说明"看到这个之后该做什么"。

`state` 的取值是 `fresh` / `stale` / `expired`。

**已实现的事件写在 `logging.EVENTS` 里**，拼错名字会直接抛 `ValueError`，防止事件名漂移。

### 级别取舍：为什么 `upstream_request` 是 DEBUG

假设持仓页 10 只票、30 秒轮询一次：

| 策略 | 日志量/天 |
|---|---|
| 每个 instrument 一条 INFO | 约 28,800 条 |
| 每次调用一条 INFO（`batch`） | 约 2,880 条 |
| 仅异常时 INFO | 几十条 |

因此：**批次级 INFO、单条级 DEBUG**。日常安静，排查时开 DEBUG 看全量。

## 3. 字段规范

结构化字段一律走 `extra=`，不拼进 message：

```python
logger.info("batch", extra={
    "event": "batch",
    "capability": "quote",
    "count": 10,
    "elapsed_ms": 245,
    "ok": 9,
    "failed": 1,
})
```

每条日志固定带 `ts` / `level` / `event` / `module` / `func` / `line`，由 formatter 补齐。

## 4. 失败事件必须自包含

一条日志就应当能定位问题，不需要复现或翻其他日志。

```json
{
  "ts": "2026-11-07T20:00:00.123+08:00",
  "level": "ERROR",
  "event": "schema_changed",
  "module": "quotestack.sources.eastmoney",
  "func": "_parse_kline",
  "line": 214,
  "source": "eastmoney",
  "capability": "history",
  "instrument": "CN:STOCK:600519",
  "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600519&...",
  "assertion": "data.klines 是 list 且每项 >= 7 字段",
  "sample": "{\"rc\":0,\"data\":{\"klines\":null}}",
  "elapsed_ms": 132,
  "attempt": 1,
  "hint": "东财可能改了 klines 字段名或结构；对比 fixture 与 sample 定位差异"
}
```

| 字段 | 作用 |
|---|---|
| `module` / `func` / `line` | 直接定位到代码行 |
| `url` | 可立即复现请求 |
| `assertion` | 说明期望的结构 |
| `sample` | 说明实际返回了什么 |
| `hint` | **下一步该查什么** |

## 5. `hint` 是硬约束

**所有 ERROR 与 WARNING 事件必须带 `hint`。**

| 事件 | hint 示例 |
|---|---|
| `schema_changed` | 上游可能改了字段结构，对比 fixture 与 sample |
| `stale_served` | 上游不可用，返回 {age}s 前的数据；查 `/healthz` 的源状态 |
| `cooldown` | `{source}` 连续失败，30 秒内跳过；查该源连通性 |
| `all_sources_failed` | 所有源失败，先看 attempts 里每个源的错误类型 |

## 6. 诊断模式

```bash
QUOTESTACK_LOG_LEVEL=DEBUG
```

DEBUG 额外记录：

- 每次 `cache_lookup` 的完整键
- 每个 `upstream_request` 的耗时与状态
- 解析过程中的中间结构（截断后输出）

## 7. 启动快照

启动时打一条环境快照，用于排除版本、配置、路径类问题：

```json
{"event":"startup","version":"0.1.0","python":"3.11.9",
 "proxy":null,"sources":["eastmoney","tencent","tiantian","binance"],
 "cache":"sqlite:~/.cache/quotestack.db","ttl":{}}
```

## 8. 脱敏

任何 URL 或配置进日志前必须过 `_redact()`：

```
http://user:pass@127.0.0.1:7890  →  http://***:***@127.0.0.1:7890
```

写日志不能成为泄密途径。

## 9. `/metrics`

用 `prometheus_client`，放在 `[server]` extra，**不进入核心依赖**。

| 指标 | 类型 | 标签 |
|---|---|---|
| `quotestack_upstream_requests_total` | Counter | `source`, `capability`, `status` |
| `quotestack_upstream_duration_seconds` | Histogram | `source`, `capability` |
| `quotestack_cache_requests_total` | Counter | `capability`, `state` |
| `quotestack_cache_entries` | Gauge | `capability` |
| `quotestack_source_up` | Gauge | `source` |
| `quotestack_schema_changes_total` | Counter | `source` |

暴露于 `GET /metrics`（Prometheus 文本格式）。

### 库与 server 的边界

库**不导入** `prometheus_client`，只暴露事件钩子：

```python
client.on("upstream_request", metrics.record)
```

这样核心依赖保持精简，server 想接什么接什么。

## 10. `/healthz`

```json
{
  "status": "degraded",
  "proxy": null,
  "sources": {
    "eastmoney": "ok", "tencent": "ok", "binance": "ok",
    "okx": "unreachable", "coingecko": "unreachable"
  },
  "cache": {"quote": {"entries": 12}, "history": {"entries": 340}},
  "recent_schema_changes": [
    {"source": "eastmoney", "at": "2026-11-07T12:00:00+08:00"}
  ]
}
```

---

← 上一篇：[实测证据](11-evidence.md) ｜ 下一篇：[运行时模型](13-runtime-model.md) →
