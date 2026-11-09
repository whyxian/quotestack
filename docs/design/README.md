# quotestack 设计决议

> 版本：v0.9 · 2026-11-07
> 状态：设计已收口；实现进度见各篇顶部的「实现状态」

> 实施进度见 [开发路线图](../ROADMAP.md)（M0–M8，逐项勾选）。

## 一句话

**面向 A股 / 美股 / 场外基金 / 加密 的多源适配层**——屏蔽源之间的差异、源的易变性、源的能力差异。

<!-- generated:begin -->
<!-- 由 scripts/sync_docs.py 生成，不要手改 -->

**当前事实**（版本 0.1.0，源码 53 文件 / 7,685 行）

| 项 | 数量 | 明细 |
|---|---|---|
| 公开取数方法 | 11 | `benchmark`, `estimate`, `fx`, `history`, `holdings`, `iter_instruments`, `nav`, `profile`, `quote`, `quote_many`, `resolve` |
| HTTP 路由 | 12 | `/v1/benchmark`, `/v1/estimate`, `/v1/fx`, `/v1/healthz`, `/v1/history`, `/v1/holdings`, `/v1/instruments`, `/v1/nav`, `/v1/profile`, `/v1/quote`, `/v1/quotes/batch`, `/v1/resolve` |
| 错误类型 | 13 | `AMBIGUOUS`, `CLIENT_BROKEN`, `DELISTED`, `EMPTY_RESPONSE`, `INTERNAL`, `INVALID_ARGUMENT`, `NOT_FOUND`, `RATE_LIMITED`, `SCHEMA_CHANGED`, `TIMEOUT`, `UNAUTHORIZED`, `UNAVAILABLE`, `UNSUPPORTED` |
| 错误基类 | 1 | `UPSTREAM_ERROR` |
| 数据源 | 5 | `binance`, `eastmoney`, `eastmoney-fx`, `tencent`, `tiantian` |
| 能力（Capability） | 10 | `RESOLVE`, `QUOTE`, `HISTORY`, `NAV`, `PROFILE`, `HOLDINGS`, `BENCHMARK`, `ESTIMATE`, `FX`, `LIST` |

<!-- generated:end -->

## 文档索引

| # | 主题 | 实现状态 | 内容 |
|---|---|---|---|
| [00](00-why.md) | **为什么做这个** | 📄 概念文档，无实现 | 与 akshare / tushare / yfinance 的差异，以及不该用的场景。 |
| [01](01-overview.md) | **定位与边界** | ✅ 公开方法全部可用 | 这个库是什么、不是什么，以及三层边界。 |
| [02](02-identity.md) | **标识解析** | ✅ 已实现（M1） | 怎么把 code+class+market 变成各源标识。 |
| [03](03-sources.md) | **数据源与覆盖率** | ✅ 五个源全部接入；OKX / CoinGecko 需代理，尚未实现 | 五个源怎么选出来的，各能覆盖多少。 |
| [04](04-cache.md) | **缓存** | 🚧 三态、单飞、max_stale 已实现；SQLite 后端未做（M6 之后） | TTL、三态语义、单飞。 |
| [05](05-api.md) | **接口与格式契约** | ✅ 11 / 11 方法可用 | 方法契约、HTTP 表面、数据格式。 |
| [06](06-errors.md) | **错误模型** | ✅ 错误模型与 HTTP 映射均已实现 | 错误分类、处置策略、重试与换源规则。 |
| [07](07-funds.md) | **基金能力** | ✅ 全部实现，回测相关性 0.958 / MAE 0.41pp（见实测证据） | 画像、持仓、基准、估值。 |
| [08](08-adapters.md) | **适配器组织** | ✅ 路由表、降级链、冷却、限流均已实现 | Protocol、路由表、兜底链。 |
| [09](09-deployment.md) | **部署与环境** | ✅ 库、CLI、HTTP 服务均可用；Docker 镜像已提供 | 部署形态、代理、开发环境。 |
| [10](10-open-source.md) | **开源与版本** | 🚧 发布前准备已完成（LICENSE / README / CONTRIBUTING / SECURITY / CHANGELOG / 模板 / 打包验证）；PyPI 待发 | 许可、包名、版本策略、CI。 |
| [11](11-evidence.md) | **实测证据** | 📄 实测记录，非代码 | 所有结论背后的探测记录。 |
| [12](12-observability.md) | **日志与可观测性** | ✅ 库侧事件、`/metrics`、启动快照均已实现 | 事件清单、字段规范、`hint` 约束、`/metrics`。 |
| [13](13-runtime-model.md) | **运行时模型** | ✅ 限流、单飞、同步包装、服务端并发均已实现 | async/sync、上游限流、并发安全、性能目标。 |
| [14](14-testing.md) | **测试策略** | ✅ 测试、fixture 目录、golden、坏样本、分层检查、CI 均已就位 | 四层测试、fixture 组织、覆盖率目标。 |
| [15](15-code-style.md) | **代码规范** | ✅ 已生效（ruff + mypy + pre-commit） | 工具链、结构硬指标、禁止/必须清单、命名。 |
| [16](16-glossary.md) | **术语表** | 📄 术语表，无实现 | MVP、TTL、复权、联接基金等缩写的解释。 |

## 阅读顺序建议

- **第一次读**：00 → 01 → 02 → 03 → 05，先看为什么，再看是什么
- **要实现**：04 → 06 → 08 → 13 → 14 → 15，缓存、错误、适配器、运行时、测试、规范是代码骨架
- **要部署**：09 → 10
- **要排查**：12 → 11

## 三条不可违背的原则

1. **一个字段只有一种类型**——禁止 `float | str` 这种联合类型
2. **难度只集中一次**——源差异全部关在适配器内，上层只见统一模型
3. **能给的旧数据就别抛错**——`stale` 优于白屏，但必须有 `max_stale` 上限

> 数字见上方「当前事实」表——那是从代码生成的，不手写。
> 覆盖率门槛见 [14-testing](14-testing.md)。
