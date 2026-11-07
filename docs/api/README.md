# HTTP 接口契约

> [openapi.yaml](openapi.yaml) 是本项目 HTTP 层的**唯一权威接口定义**。
> 更新于 2026-11-08。

---

## 这是什么

一份 OpenAPI 3.1 文档，描述 quotestack 服务化后的 12 个接口。

**现在还没实现**（M6 才写服务），所以它是**契约先行**，不是从代码生成的。
M6 完成后会改成由 FastAPI 生成，并用 CI 校验两者一致。

---

## 怎么查看

| 方式 | 做法 |
|---|---|
| **VSCode** | 装 [OpenAPI (Swagger) Editor](https://marketplace.visualstudio.com/items?itemName=42Crunch.vscode-openapi)，打开文件按 `Cmd+Shift+P` → `Preview OpenAPI` |
| **在线** | 把内容粘到 [editor.swagger.io](https://editor.swagger.io) |
| **纯文本** | 直接读 YAML，`description` 全是中文，信息比渲染页更全 |

---

## 12 个接口

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/v1/resolve` | 解析代码 | ✅ |
| GET | `/v1/quote` | 实时报价 | ✅ |
| POST | `/v1/quotes/batch` | 批量报价 | ✅ |
| GET | `/v1/history` | K 线 / 分钟线 | ✅ |
| GET | `/v1/nav` | 基金净值 | ✅ |
| GET | `/v1/fx` | 汇率 | ✅ |
| GET | `/v1/instruments` | 市场列表 | ✅ |
| GET | `/v1/healthz` | 运行状态 | ✅（命令行版已有） |
| GET | `/v1/profile` | 基金画像 | ⬜ M4 |
| GET | `/v1/holdings` | 季度持仓 | ⬜ M4 |
| GET | `/v1/benchmark` | 基准曲线 | ⬜ M4 |
| GET | `/v1/estimate` | 基金估值 | ⬜ M5 |

「✅」指**库层能力已实现**，HTTP 层仍要等 M6。

---

## 三个核心约定

### 1. 统一响应结构

```json
// 成功（HTTP 200）
{ "data": { ... }, "error": null }

// 失败（HTTP 4xx / 5xx）
{ "data": null, "error": { "code": "NOT_FOUND", "message": "...", "detail": {...} } }
```

成功和失败**形状一致**，调用方一条 `if (error != null)` 处理全部失败。

**但 HTTP 状态码仍然有效**——404 就是 404，不改成 200。监控、重试、网关限流都依赖它。

### 2. 金额一律字符串

```json
{ "price": "1453.00" }
```

不是 `1453.0`。原因：`0.1 + 0.2 != 0.3`，金额不能有浮点误差；JavaScript 也能安全处理。

### 3. 入参永远是 code + asset_class + market

调用方不需要持有内部 ID。同一个代码在不同市场含义不同：

```
000001 + STOCK + CN  → 平安银行
000001 + FUND  + CN  → 华夏成长混合
```

---

## 和 05-api 文档的关系

| 文档 | 面向 | 内容 |
|---|---|---|
| [05-api](../design/05-api.md) | **人** | 为什么这么设计、字段含义、取舍 |
| [openapi.yaml](openapi.yaml) | **机器** | 完整 schema、参数校验规则、示例 |

两者冲突时**以 openapi.yaml 为准**——它是可校验的；05-api 是解释性的。

---

## 怎么改

**新增接口**：

1. 先改 `openapi.yaml`（定契约）
2. 再改 `docs/design/05-api.md`（写理由）
3. 最后写代码

**改字段**：同上顺序。先改契约，再改实现——否则会变成"文档追代码"，这是我们想避免的。

---

## M6 之后

服务实现完成后：

```bash
uv run python -m quotestack.server --dump-openapi > docs/api/openapi.yaml
```

CI 会跑同一条命令并 `git diff --exit-code`，**任何接口改动没同步到文档都会让构建失败**。
