# quotestack AI 开发上下文

> **这是入口，不是手册。** 详细规则在 `docs/harness/`，这里只保留
> 「在哪、怎么跑、现在到哪一步」。

---

## 1. 项目一句话

**面向 A股 / 美股 / 场外基金 / 加密 的多源适配层**——把四类资产的数据源差异
收敛成一套一致的调用方式。

---

## 2. 当前阶段

**M8 进行中**（发布前准备已完成，等发版）。核心能力全部可用。

进度见 [docs/ROADMAP.md](docs/ROADMAP.md)。**做任何任务前先确认阶段，不要跳阶段实现。**

---

## 3. 快速命令

```bash
uv sync --extra dev --extra server   # 依赖；服务端需要 server extra
uv run pytest -q                     # 测试，全离线
uv run ruff check . && uv run mypy src
uv run python scripts/sync_docs.py   # 改了文档或结构后同步事实
uv run quotestack-server --dump-openapi > docs/api/openapi.yaml
```

提交前钩子已启用（ruff + format + mypy），不要用 `--no-verify` 绕过。

---

## 4. 读什么

### 动手改代码之前

| 顺序 | 文件 | 内容 |
|---|---|---|
| 1 | [harness/CONSTRAINTS](docs/harness/CONSTRAINTS.md) | 红线、编码风格、测试与提交约束 |
| 2 | [harness/ARCHITECTURE](docs/harness/ARCHITECTURE.md) | 代码在哪、谁能 import 谁、调用路径 |
| 3 | [harness/PITFALLS](docs/harness/PITFALLS.md) | 不报错但会算错的地方 |
| 4 | [harness/WORKFLOWS](docs/harness/WORKFLOWS.md) | 加源 / 修 bug / 改接口的步骤 |
| 5 | [harness/BOUNDARY](docs/harness/BOUNDARY.md) | 哪些操作必须先问人 |

### 需要设计背景时

**从 [design/README](docs/design/README.md) 的索引进入**，不要直接跳具体章节——
那份索引按主题组织，能一次看全 17 篇的定位与实现状态。

`design/` 记录的是当时的判断，可能已被实现修正；`harness/` 描述的是现在。

### 给人看的代码导读

[docs/CODE_MAP_ZH.md](docs/CODE_MAP_ZH.md)（中文，逐文件逐函数）。**不在 harness 下**，
因为它是人读的，不是 AI 读的。

---

## 5. 三类文档的边界

| 目录 / 文件 | 读者 | 回答 |
|---|---|---|
| `docs/harness/` + `AGENTS.md` | **AI** | 怎么写代码、有什么约束 |
| `docs/design/` | **人** | 为什么这么设计 |
| `docs/CODE_MAP_ZH.md` | **人** | 代码现在长什么样 |
| `guide/` | **使用者** | 怎么用这个库 |

**`guide/` 与仓库内文档完全隔离**：它不引用 `docs/` 下任何文件，可以单独托管。

---

## 6. 缺什么就补什么

`harness/` 跟代码一起长。踩到新坑、发现自己违反了没写下来的规矩、走了三步才搞明白
的流程——**直接补进对应文件**，不要只在对话里说。
