# 运行环境

> 这份文件回答一个问题：**在一个新机器上，从零到能改代码、能跑测试，需要什么。**
> 命令只写一遍；`CONTRIBUTING.md` 的环境准备指回这里，避免两处各写一套然后漂移。

---

## 1. 运行形态

这个项目有两种用法，**共用同一份代码**：

| 形态 | 入口 | 谁用 |
|---|---|---|
| 库 | `import quotestack` | Python 后端直接调用 |
| HTTP 服务 | `quotestack-server` | 非 Python 调用方（如 Java 后端） |

CLI `quotestack` 在进程内直接调库，不走 HTTP。

---

## 2. 技术栈

| 层 | 用什么 | 为什么是它 |
|---|---|---|
| 语言 | **Python 3.11+**（CI 与本地实测 3.12） | 需要 `TaskGroup` / `asyncio.timeout` 这类 3.11 才稳定的结构化并发 |
| HTTP 客户端 | **httpx** | 异步、连接池、`proxy=` 参数；是唯一的核心依赖 |
| HTTP 服务 | **FastAPI** + **uvicorn** | 从函数签名生成 OpenAPI，契约能由代码产出 |
| 指标 | **prometheus-client** | `/metrics` 暴露请求计数与耗时 |
| 并发 | 标准库 `asyncio` | 无第三方异步框架 |
| 缓存 | 标准库 `dict` + LRU（自实现） | 见 §4：刻意不引入缓存服务器 |

**没有的东西**（同样是技术决策，不是遗漏）：

| 没有 | 替代 | 理由 |
|---|---|---|
| 数据库 | 无 | 库是只读适配层，不持久化业务数据 |
| ORM | 无 | 同上 |
| 消息队列 / 定时任务框架 | GitHub Actions 手动触发探测 | 唯一需要的"后台任务"是结构探测 |
| Redis / Memcached | 进程内 `MemoryCache`（LRU，上限 10,000 条） | 见 §4 |
| 前端 | 无 | 服务只提供 JSON |
| 容器编排 | 单容器 `Dockerfile` | 没有需要编排的组件 |

---

## 3. 依赖

核心依赖**只有一行**，其余都在 extra 里：

```toml
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
server = ["fastapi>=0.115", "uvicorn>=0.30", "prometheus-client>=0.20"]
dev    = ["pytest>=8.0", "pytest-asyncio>=0.24", "pytest-cov>=5.0", "respx>=0.21",
          "ruff>=0.9", "mypy>=1.13", "pre-commit>=3.8", "pyyaml>=6.0", "types-pyyaml>=6.0"]
```

| extra | 装什么 | 不装会怎样 |
|---|---|---|
| （无） | `httpx` | 库本身可用；只当库用时够了 |
| `server` | `fastapi`、`uvicorn`、`prometheus-client` | `quotestack-server` 起不来 |
| `dev` | `pytest`、`respx`、`ruff`、`mypy`、`pre-commit` 等 | 测试与检查跑不了 |

具体版本由 `uv.lock` 锁定；`pyproject.toml` 里写的是下界。

**为什么只留一个核心依赖**：库会被嵌进别人的服务，每多一个依赖就多一份版本冲突。
pydantic 因此从核心依赖移到了 `server` extra——它只有 HTTP 层需要。

---

## 4. 中间件：没有，这是设计

> **没有数据库、没有缓存服务器、没有消息队列。** 部署就是单个进程或单个容器。

这不是"还没做"，是刻意换来的：

| 好处 | 代价 |
|---|---|
| 部署 = 拷贝 + 运行，没有 compose 文件 | 重启即冷启动，缓存清空 |
| 不会因为 Redis 不可用而整体不可用 | 多实例之间不共享缓存 |
| 测试不需要起任何外部服务，全离线 | 跨进程缓存要调用方自己做 |

**什么时候会改这个决定**：需要多实例共享缓存、或需要跨重启保留数据时。
届时引入的是"缓存服务器 + 可选的持久化"，不是 ORM 或队列。

其余外部依赖只有**数据源本身**（都是公开 HTTP 接口）：

| 源 | 域名 | 备注 |
|---|---|---|
| 东财 | `push2*.eastmoney.com`、`fund.eastmoney.com` | 主要来源 |
| 腾讯 | `qt.gtimg.cn` | 实时兜底 |
| 天天基金 | `fund.eastmoney.com/pingzhongdata/` | 场外基金 |
| Binance | `data-api.binance.vision` | 交易对列表 |
| 东财外汇 | `push2.eastmoney.com` | 汇率 |

其中部分域名在境内网络下不稳定，需要代理时用 `QUOTESTACK_PROXY_URL`（见 §6）。

---

## 5. 搭建开发环境

### 5.1 需要什么

| 必需 | 说明 |
|---|---|
| **git** | 克隆仓库 |
| **uv ≥ 0.5** | 装 Python、装依赖、跑命令；**不需要事先装 Python** |
| 网络 | 第一次 `uv sync` 要下载依赖；跑测试**不需要**外网 |

| 可选 | 用途 |
|---|---|
| Docker | 只想跑服务、不想配 Python 环境时 |
| 代理 | 访问部分数据源；单元测试不需要 |

### 5.2 三条命令

```bash
git clone https://github.com/whyxian/quotestack.git && cd quotestack
uv sync --extra dev --extra server
uv run pre-commit install
```

`uv sync` 会按 `.python-version` / `requires-python` 自动准备 Python，并创建 `.venv/`。

### 5.3 验证装好了

```bash
uv run pytest -q                     # 应全绿，391 个用例
uv run quotestack --help             # CLI 有 5 个子命令
uv run quotestack-server --dump-openapi | head -3
```

### 5.4 提交前钩子的缓存位置

钩子默认写 `~/.cache/pre-commit`。指向仓库内可以避免动家目录：

```bash
export PRE_COMMIT_HOME="$PWD/.pre-commit-home"     # 已在 .gitignore 里
```

钩子用的是**本仓库 venv 里的工具**，不是另下载的版本——否则两个 ruff 会对同一份代码
给出不同结论。

---

## 6. 常见环境问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `uv sync --extra server` 之后 pytest 不见了 | `uv sync` 让环境**严格匹配** extras | 两个 extra 一起写：`--extra dev --extra server` |
| `quotestack-server: command not found` | 没装 `server` extra | `uv sync --extra server` |
| 某些源超时 | 网络/地区问题 | 设 `QUOTESTACK_PROXY_URL`，或只跑离线测试 |
| 两个 ruff 结论不同 | 系统里另有一个 ruff | 用 `uv run ruff`，不要裸跑 `ruff` |
| CI 通过、本地不通过 | Python 小版本差异 | 本地 `uv run python --version` 应与 CI 的 3.12 一致 |

---

## 7. 这份文档和别处的关系

| 问题 | 看哪里 |
|---|---|
| 怎么改代码、有哪些红线 | [CONSTRAINTS](CONSTRAINTS.md) |
| 代码在哪、谁 import 谁 | [ARCHITECTURE](ARCHITECTURE.md) |
| 测试分几层、怎么加 | [14-testing](../design/14-testing.md) |
| 怎么部署、有哪些配置项 | [09-deployment](../design/09-deployment.md) |
| 使用者怎么装、怎么调 | [guide/](../../guide/README.md) |
