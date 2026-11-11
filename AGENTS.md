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

## 4. 不可协商（违反即不可合并）

细节和理由在 [harness/CONSTRAINTS](docs/harness/CONSTRAINTS.md)。**这张表是从那里生成的**，
改条款请改 CONSTRAINTS。

<!-- generated:begin -->
<!-- 由 scripts/sync_docs.py 从 docs/harness/CONSTRAINTS.md 生成，不要手改 -->

| ID | 不可协商 | 反例 |
|---|---|---|
| R1 | 价格、金额、成交量、净值一律 `str` | `price: float` |
| R2 | 库不得配置 logging handler | `src/` 里出现 `logging.basicConfig()` |
| R3 | 源差异只能关在 `sources/` 内 | `client.py` 里判断"东财返回 f2 字段" |
| R4 | 缓存超过 `max_stale` 必须抛错 | 忽略容忍期直接返回旧值 |
| R5 | 一个字段只能有一种类型 | `price: float \| str` |
| R6 | 装软件、写家目录、起常驻进程前必须先问 | 直接 `brew install` |
| R7 | 对外可见且难撤回的操作先问（打 tag、发版、推远程） | 不打招呼就 `git push --tags` |
| R8 | 不许为了让测试通过而放宽断言 | 把 `assert x == 5` 改成 `assert x` |
| R9 | 不许改坏样本让测试通过 | 把 fixture 改小让它不再触发分支 |
| R10 | 数字只写在生成块里，正文不写数字 | 手写"11 个方法"，之后不再更新 |

<!-- generated:end -->

---

## 5. 读什么

### 动手改代码之前

| 顺序 | 文件 | 内容 |
|---|---|---|
| 1 | [harness/CONSTRAINTS](docs/harness/CONSTRAINTS.md) | 红线、编码风格、测试与提交约束 |
| 2 | [harness/ARCHITECTURE](docs/harness/ARCHITECTURE.md) | 代码在哪、谁能 import 谁、调用路径 |
| 3 | [harness/PITFALLS](docs/harness/PITFALLS.md) | 不报错但会算错的地方 |
| 4 | [harness/WORKFLOWS](docs/harness/WORKFLOWS.md) | 加源 / 修 bug / 改接口的步骤 |
| 5 | [harness/BOUNDARY](docs/harness/BOUNDARY.md) | 哪些操作必须先问人，以及**申请权限的标准格式** |

### 需要设计背景时

**从 [design/README](docs/design/README.md) 的索引进入**，不要直接跳具体章节——
那份索引按主题组织，能一次看全 17 篇的定位与实现状态。

`design/` 记录的是当时的判断，可能已被实现修正；`harness/` 描述的是现在。

### 给人看的代码导读

[docs/CODE_MAP_ZH.md](docs/CODE_MAP_ZH.md)（中文，逐文件逐函数）。**不在 harness 下**，
因为它是人读的，不是 AI 读的。

---

## 6. 四类文档的边界

| 目录 / 文件 | 读者 | 回答 |
|---|---|---|
| `docs/harness/` + `AGENTS.md` | **AI** | 怎么写代码、有什么约束 |
| `docs/design/` | **人** | 为什么这么设计 |
| `docs/CODE_MAP_ZH.md` | **人** | 代码现在长什么样 |
| `guide/` | **使用者** | 怎么用这个库 |

**`guide/` 与仓库内文档完全隔离**：它不引用 `docs/` 下任何文件，可以单独托管。

---

## 7. 缺什么就补什么

`harness/` 跟代码一起长。踩到新坑、发现自己违反了没写下来的规矩、走了三步才搞明白
的流程——**直接补进对应文件**，不要只在对话里说。
