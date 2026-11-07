# 部署与环境

> quotestack 设计决议 · 第 9 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)


## 部署

| 场景 | 方式 |
|---|---|
| 开发 | `uv run`（热重载） |
| 交付 | `docker-compose`（仅 quote-service；本项目不需要数据库服务） |
| **不做** | Java 拉起 Python 子进程 |

**关于数据库**：quotestack 不依赖任何数据库服务。

- 缓存用 `MemoryCache`（进程内）或 `SqliteCache`（单个文件，无需服务端）
- 业务数据（持仓、交易、品种库）属于调用方，不在本库职责内

PostgreSQL 是 AssetPilot 后端的选择，与本库无关。

**Java 侧集成**

| 项 | 决议 |
|---|---|
| HTTP 客户端 | Spring `RestClient` |
| 并发 | JDK 21 虚拟线程 |
| 连接超时 | 1s |
| 读超时 | 5s |
| 重试 | **不重试**（服务内部已重试一次） |
| 熔断 | 手写约 30 行，不引 Resilience4j |

Java 启动时探测 `/healthz`，**不通也照常启动**；行情调用失败走三态降级（REALTIME / HISTORICAL / UNAVAILABLE）。

---

## 代理配置

```python
client = MarketData(
    proxy="http://127.0.0.1:7890",
    proxy_bypass=["eastmoney.com", "qq.com"],
)
```

| 档位 | 可用源 | 加密覆盖 |
|---|---|---|
| 无 proxy | 东财 / 腾讯 / 天天基金 / Binance-Vision / 东财外汇 | 11/15 |
| 有 proxy | 上述 + OKX + CoinGecko + GitHub 汇率 | 14/15 |

无代理时对不可达源**快速失败**并给具体提示，不傻等超时：

```json
{
  "code": "SOURCE_UNREACHABLE",
  "message": "OKX 需要代理才能访问，当前未配置 proxy",
  "hint": "配置 proxy 后可查询 USDG、MEW、MOODENG 等 4 个品种"
}
```

`/healthz` 暴露当前档位。

---

## 开发环境准备

目标：**从一台什么都没装的机器，到能跑通三条命令**。每一步都给出验证方式，出问题能自查。

### 工具清单

| 工具 | 版本 | 用途 | 何时需要 |
|---|---|---|---|
| git | 任意 | 版本控制 | 始终 |
| uv | ≥ 0.5 | Python 版本与依赖管理 | 始终 |
| Python | 3.11 / 3.12 / 3.13 | 运行时（由 uv 安装） | 始终 |
| sqlite3 | 任意 | 查看缓存内容 | 调试时 |
| Docker | 任意 | 跑 HTTP 服务、集成测试 | 可选 |

> JDK 与 Maven **不在本库的开发需求内**——那是调用方（AssetPilot 后端）的事。

### 步骤 1：安装 uv

**为什么**：统一管理 Python 版本与虚拟环境，避免污染系统 Python。

```bash
brew install uv
# 或万能安装脚本
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**验证**：

```bash
uv --version
# 期望：uv 0.5.x 或更高
```

若无输出或提示 `command not found`，见下方故障表。

### 步骤 2：安装 Python 3.11

**为什么**：系统 Python 的版本可能与依赖的 wheel 不匹配。用 uv 装独立版本，与系统 Python 互不干扰。

```bash
uv python install 3.11
uv python list
# 期望：列表中出现 cpython-3.11.x
```

### 步骤 3：创建虚拟环境

```bash
cd quote-service
uv venv --python 3.11
source .venv/bin/activate
```

**验证**：`python -V` 输出 `Python 3.11.x`。

### 步骤 4：安装项目依赖

```bash
uv pip install -e ".[server,cache]"
```

只有需要 Playwright 数据源时（约 150 MB Chromium）：

```bash
uv pip install -e ".[browser]"
playwright install chromium
```

### 步骤 5：端到端验证

```bash
uv run python -c "import quotestack; print(quotestack.__version__)"
quotestack health
```

两条都成功，环境即就绪。

---

## 常见故障与修复

| 症状 | 原因 | 修复 |
|---|---|---|
| `brew install` 报无权写入 `/opt/homebrew` | Homebrew 目录属主不对 | `sudo chown -R $(whoami) /opt/homebrew` |
| `uv: command not found` | `~/.local/bin` 不在 PATH | 在 shell rc 里追加 `export PATH="$HOME/.local/bin:$PATH"`，再 `source` 它 |
| `uv python install` 卡住或失败 | 网络无法访问 Python 构建源 | 配置代理，或设置 `UV_PYTHON_INSTALL_MIRROR` |
| `pip install` 编译失败 | 没有 Xcode 命令行工具 | `xcode-select --install` |
| `playwright install` 失败 | 同上，或缺系统依赖 | 先装 CLT；Linux 下需 `playwright install-deps` |
| 配了代理仍连不上境外源 | 只设了 `HTTP_PROXY`，没设 `HTTPS_PROXY` | 两个都要设，或直接用 `proxy=` 参数 |
| `sqlite3.OperationalError: database is locked` | 多进程并发写缓存 | 确认 WAL 已开启（见 [13-runtime-model](13-runtime-model.md)） |
| `uv pip install` 卡住或超时 | PyPI 官方源在国内不稳定 | 配镜像：`export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` |
| 镜像里版本比官网旧 | 镜像同步有延迟 | 正常现象，锁版本时以镜像为准 |
| 导入慢（> 1s） | 误装了 `[browser]` 等重依赖 | 只装需要的 extra |

---

## 一键自检

供参考的检查清单，正式脚本在 `scripts/check-env.sh`：

```bash
#!/usr/bin/env bash
set -u
ok=0; fail=0
check() {
  local name="$1" cmd="$2" hint="$3"
  if eval "$cmd" >/dev/null 2>&1; then
    printf '  ✅ %s\n' "$name"; ok=$((ok+1))
  else
    printf '  ❌ %s\n     → %s\n' "$name" "$hint"; fail=$((fail+1))
  fi
}

echo "检查开发环境..."
check "git"              "git --version"                 "安装 Xcode 命令行工具或 git"
check "uv"               "uv --version"                  "brew install uv"
check "python 3.11"      "uv python find 3.11"           "uv python install 3.11"
check "虚拟环境"          "test -d .venv"                 "uv venv --python 3.11"
check "依赖已装"          "uv run python -c 'import quotestack'" "uv pip install -e \".[server,cache]\""
check "Docker（可选）"    "docker --version"              "安装 Docker Desktop"

echo "通过 $ok 项，失败 $fail 项"
[ "$fail" -eq 0 ]
```

---

## 最小可运行验证

装完环境后，三条命令必须全部成功：

```bash
quotestack quote 600519
quotestack history 600519 --limit 5
quotestack health
```

分别验证：**实时行情链路、K 线链路、源健康状态**。三条都通，说明标识解析、缓存、适配器、错误映射全部就位。

---

## 关于 AI 辅助开发

若使用 AI 编码助手，其文件沙箱通常只允许写入当前工作区。此时：

| 操作 | 谁来做 |
|---|---|
| `brew install` 等系统级安装 | **本人执行**，agent 无权写 `/opt/homebrew` |
| 工作区内的文件读写 | agent 可代劳 |
| 需要 agent 代跑系统安装 | 需显式放宽其权限 |

> 常见误判：`brew install` 报权限错误时，先确认是不是被执行环境限制了，而不是系统真的坏了。

← 上一篇：[适配器组织](08-adapters.md) ｜ 下一篇：[开源与版本](10-open-source.md) →
