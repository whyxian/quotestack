# 开源与版本

> quotestack 设计决议 · 第 10 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：🚧 发布前准备已完成（LICENSE / README / CONTRIBUTING / SECURITY / CHANGELOG / 模板 / 打包验证）；PyPI 待发


## 开源准备

| 项 | 决议 |
|---|---|
| 包名 | `quotestack`（PyPI 可用，npm 空） |
| 许可 | MIT |
| 仓库 | monorepo 内，零内部依赖 |
| 目录 | 见下 |

> ⚠️ 下面这棵树是**规划时的设想**，与实际仓库不一致：没有 `quotestack_server/`，
> 没有 okx/coingecko，HTTP 层在 `src/quotestack/server/`。
> 当前结构见 [ARCHITECTURE](../harness/ARCHITECTURE.md)。

```
quote-service/
├── pyproject.toml
├── README.md                 快速开始 + 支持矩阵 + 合规声明
├── LICENSE
├── src/quotestack/
│   ├── client.py             10 个入口
│   ├── identity/             resolve + 各市场规则
│   ├── sources/              东财/腾讯/天天基金/binance/okx/coingecko
│   ├── models/               Instrument/Quote/Bar/Profile
│   ├── cache/                Memory/SQLite + TTL + 单飞
│   └── errors.py
├── src/quotestack_server/    FastAPI 壳
└── tests/
    ├── fixtures/             录制的真实响应
    └── test_*.py
```

**依赖拆分**

```toml
[project]
dependencies = ["httpx>=0.27", "pydantic>=2.6"]

[project.optional-dependencies]
browser = ["playwright>=1.40"]
server  = ["fastapi>=0.115", "uvicorn>=0.30"]
cache   = ["aiosqlite"]
```

Playwright 必须 optional（带 150 MB Chromium）。

**合规声明**（README 必须写）：

> 本库仅用于个人学习与研究，从公开接口获取数据，不做缓存转售、不绕过任何付费限制。使用者应遵守数据提供方的服务条款，商业用途请购买官方授权。

---

## 构建与打包

| 项 | 决议 |
|---|---|
| 构建后端 | **hatchling**（src layout 零配置） |
| 布局 | `src/quotestack/`、`src/quotestack_server/` |
| 类型标记 | 附带 `py.typed`（PEP 561），否则 `mypy` 不认类型 |
| 元数据 | `classifiers` / `keywords` / `urls` 必须完整填写 |

关键字段：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "quotestack"
requires-python = ">=3.11"
license = { text = "MIT" }
keywords = ["market-data", "stock", "fund", "crypto", "finance"]
classifiers = [
  "Development Status :: 3 - Alpha",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3.11",
  "Typing :: Typed",
]

[project.urls]
Homepage = "..."
Repository = "..."
Changelog = "..."

[project.scripts]
quotestack = "quotestack.cli:main"
```

---

## 开源必备文件

| 文件 | 必要性 | 要求 |
|---|---|---|
| `LICENSE` | **必须** | MIT 全文，年份与作者 |
| `README.md` | **必须** | 英文；徽章、安装、30 秒示例、支持矩阵、合规声明 |
| `README.zh-CN.md` | 建议 | 中文版，内容与英文版同步 |
| `CONTRIBUTING.md` | **必须** | 开发环境、如何新增数据源、提交规范、测试要求 |
| `SECURITY.md` | **必须** | 漏洞上报渠道、响应时限 |
| `CHANGELOG.md` | **必须** | Keep a Changelog 格式 |
| `CODE_OF_CONDUCT.md` | 建议 | Contributor Covenant |
| `.gitignore` | **必须** | Python + macOS + 缓存产物 |
| `py.typed` | **必须** | 空文件即可 |
| `examples/` | **建议** | 至少 3 个可运行脚本 |
| `.github/workflows/ci.yml` | **必须** | 三段式 CI |
| `.github/ISSUE_TEMPLATE/` | 建议 | bug / feature 模板 |
| `.github/PULL_REQUEST_TEMPLATE.md` | 建议 | — |

### `examples/` 的内容

| 示例 | 演示什么 |
|---|---|
| `examples/quote.py` | 查单个标的最新价 |
| `examples/history.py` | 拉 K 线并画图（matplotlib 可选依赖） |
| `examples/fund_estimate.py` | 场外基金估值 + 基准对比 |

每个示例必须能独立运行，且不依赖未声明的依赖。

---

## 文档语言

| 文档 | 语言 | 理由 |
|---|---|---|
| `README.md` | **英文** | 开源项目门面，国际用户第一眼 |
| `README.zh-CN.md` | 中文 | 中文用户 |
| `CONTRIBUTING.md` | 英文 | 与 README 一致 |
| `docs/design/*` | 中文 | 内部设计记录，可接受 |

**规则**：英文 README 是权威版本，中文版跟随更新，不反向同步。

---

## 发布前检查

- [ ] 全文搜索个人路径（家目录前缀、主机名、用户名），零命中。由 `scripts/check_release.py` 自动检查
- [ ] 无调试代码、无 `print`、无注释掉的实验片段
- [ ] `LICENSE` 年份与作者正确
- [ ] `pyproject.toml` 元数据完整
- [ ] `README` 中的示例代码可直接运行
- [ ] `CHANGELOG` 有首个版本条目
- [ ] 仓库无 `.DS_Store`、无 `__pycache__`

---

## 关键决议一览

| # | 议题 | 决议 |
|---|---|---|
| 1 | Python 最低版本 | **`>=3.11`**，CI 跑 3.11 / 3.12 / 3.13 |
| 2 | PyPI 发布 | 尽快发 `0.0.1` 占名，README 标 pre-alpha |
| 3 | CI | 三段式：PR 离线 / 每日真实探测 / tag 发布 |
| 4 | 分钟线 | 合并进 `history(interval)`，不单独暴露 |
| 5 | 估值精度 | 写回测脚本出报告，不作 CI 门槛 |

### 版本策略

```
0.1.0   首个可用版本（数据源跑通、接口定型）

> **跳过了 0.0.1 占名版本。** 原计划是先发一个占名版本，但功能在发布时已经完整，
> 再发一个空壳只会让版本号说谎。若担心包名被占，应在实现之前先发。
0.x     迭代期，允许破坏性变更
1.0.0   API 冻结
```

`0.0.1` 发布后不可删除（只可 yank），内容必须干净：无内部路径、无调试代码。

先走 TestPyPI 验证打包，再发正式 PyPI。

### CI 三段式

| Job   | 触发        | 内容                                      | 失败影响            |
| ----- | --------- | --------------------------------------- | --------------- |
| PR CI | push / PR | `ruff` + `mypy` + `pytest`（全离线，fixture） | 阻塞合并            |
| 定时探测  | 每天        | 真实请求各源，验证结构断言                           | 开 issue，**不阻塞** |
| 发布    | tag       | 构建 → TestPyPI → PyPI                    | —               |

**必须有"定时探测"**：fixture 是历史快照，源改版后测试照样绿；只有真实探测能发现漂移，这正是 `SchemaChanged` 断言的用途。

### 定时探测

#### 它解决什么问题

```
2026-11 录下东财响应 → 存进仓库当 fixture

东财改了字段名
  ↓
跑单测 → 读旧 fixture → 解析成功 → 绿灯 ✅
  ↓
线上真实请求 → 结构变了 → 挂 ❌
```

单元测试测的是"我们能不能解析**过去**的响应"，探测测的是"上游**现在**还长这样吗"。两者不能互相替代。

#### 实现位置

GitHub Actions 的 `on.schedule`：

```yaml
name: live probe
on:
  schedule:
    - cron: "0 1 * * *"      # UTC 01:00 = 北京时间 09:00
  workflow_dispatch:          # 支持手动触发

jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --extra dev
      - run: uv run pytest tests/test_smoke.py -q
        env:
          QUOTESTACK_LIVE: "1"
```

本地等价命令：

```bash
QUOTESTACK_LIVE=1 .venv/bin/pytest tests/test_smoke.py -q
```

#### 探测范围

覆盖**每个源 × 每个能力**，不能只测一个源就以为全覆盖：

| 源 | 探测项 |
|---|---|
| 东财 | 报价、日线、周线、分钟线、搜索解析 |
| 腾讯 | 报价（A股 + 美股） |
| 天天基金 | 净值、画像、季度持仓 |
| Binance | 报价、K 线 |
| 汇率 | USD 基准表 |

#### 三个已知限制

| 限制 | 说明 | 应对 |
|---|---|---|
| **只在默认分支运行** | `schedule` 触发的是默认分支最新代码，PR 分支不生效 | 接受；探测针对的是上游，不是本次改动 |
| **60 天无提交会被自动禁用** | GitHub 对公开仓库的定时任务策略 | 接受；长期静默说明项目没人用。重新启用后立即恢复。<br>**不要误以为一直在监控**——长期无提交后需手动检查一次 |
| **cron 使用 UTC** | `0 1 * * *` 是北京时间 09:00 | 注释里标明换算后时间 |

#### 失败处理

**不阻塞任何 PR**——探测跑的是默认分支，与当前改动无关。

```
探测失败
  ↓ 连续 2 天
在固定的追踪 issue 下追加评论
  ↓ 恢复
同一 issue 下评论「已恢复」
```

用**固定 issue 当状态载体**，不是每次开新 issue。单次失败大概率是网络抖动（实测 GitHub 汇率源就曾返回一次 `000`，重试即恢复）。

#### 与 `/healthz` 的区别

| | `/healthz` | 定时探测 |
|---|---|---|
| 回答 | 「现在各源通不通」 | 「上游结构有没有变」 |
| 时机 | 运行时随时 | 每天一次 |
| 能否发现结构变更 | ❌ 只报告可达性 | ✅ 真解析一遍 |

两者互补，不能替代彼此。

fixture 刷新：

```bash
python scripts/record_fixtures.py --source eastmoney --capability history
```

跑完 `git diff` 即一次可审查的变更。

---

← 上一篇：[部署与环境](09-deployment.md) ｜ 下一篇：[实测证据](11-evidence.md) →
