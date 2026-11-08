# 部署与环境

> quotestack 设计决议 · 第 9 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：✅ 库、CLI、HTTP 服务均可用；Docker 镜像已提供


## 部署

quotestack 有两种交付形态：**作为库被导入**，或**作为 HTTP 服务运行**。

| 形态  | 适用场景                    | 交付物             |
| --- | ----------------------- | --------------- |
| 库   | Python 项目直接调用           | PyPI 包          |
| 服务  | 非 Python 调用方（如 Java 后端） | 单进程 / Docker 镜像 |

---

### 形态一：作为库

```bash
pip install quotestack
```

```python
from quotestack import AssetClass, Market, MarketData

async with MarketData() as client:
    quote = await client.quote("600519", AssetClass.STOCK, Market.CN)
```

这是最轻的形态——没有服务、没有端口、没有额外进程。

---

### 形态二：本地进程

```bash
uv run quotestack-server --host 127.0.0.1 --port 8000
```

适合本机开发和调试。进程退出即停止，不安装任何系统服务。

---

### 形态三：Docker

服务端无外部依赖（无数据库、无消息队列），因此**单个容器即可完整运行**。

#### Dockerfile

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    QUOTESTACK_CACHE_DIR=/data \
    QUOTESTACK_PORT=8000

WORKDIR /app

# 先装依赖，利用层缓存：改代码不必重装依赖
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[server,cache]"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

CMD ["quotestack-server", "--host", "0.0.0.0", "--port", "8000"]
```

#### 构建

```bash
docker build -t quotestack:0.1.0 .
```

#### 运行

```bash
docker run -d \
  --name quotestack \
  -p 8000:8000 \
  -v quotestack-cache:/data \
  --restart unless-stopped \
  quotestack:0.1.0
```

| 参数 | 作用 |
|---|---|
| `-p 8000:8000` | 暴露 HTTP 端口 |
| `-v quotestack-cache:/data` | 缓存持久化，容器重建不丢 |
| `--restart unless-stopped` | 宿主重启后自动拉起 |

#### 联网与代理

容器**不继承宿主机的 VPN 路由**。若需要访问境外源（OKX、CoinGecko），必须显式配置：

```bash
docker run -d \
  -e HTTPS_PROXY=http://host.docker.internal:7890 \
  -e HTTP_PROXY=http://host.docker.internal:7890 \
  ...
```

`host.docker.internal` 在 Docker Desktop 上指向宿主机；Linux 需改用 `--add-host=host.docker.internal:host-gateway`。

#### 验证

```bash
curl "http://localhost:8000/v1/quote?code=600519&asset_class=STOCK&market=CN"
curl "http://localhost:8000/healthz"
```

`/healthz` 会报告每个源的可用状态，以及当前是否配置了代理。

#### 日志

```bash
docker logs -f quotestack
```

服务端输出结构化 JSON，事件名可直接 grep：

```bash
docker logs quotestack 2>&1 | grep '"event":"schema_changed"'
```

#### 升级

```bash
docker build -t quotestack:0.2.0 .
docker rm -f quotestack
docker run -d --name quotestack -p 8000:8000 -v quotestack-cache:/data quotestack:0.2.0
```

缓存在命名卷里，升级不丢。回滚同理，用旧 tag 重跑即可。

---

## 配置

库形态下，配置就是构造参数：

```python
client = MarketData(ttl={Capability.QUOTE: 60}, proxy="http://127.0.0.1:7890")
```

服务形态下没有调用方写代码，因此由 **server 读取配置文件与环境变量**，再构造客户端。

**配置解析只在 server 层**——库不读环境变量、不读文件，保持无隐藏输入。

### 优先级

从低到高，后者覆盖前者：

```
1. 代码默认值
2. 配置文件  quotestack.toml
3. 环境变量  QUOTESTACK_*
4. 命令行参数 --port / --host / --config
```

### 配置文件

默认读取工作目录下的 `quotestack.toml`；用 `--config` 或 `QUOTESTACK_CONFIG` 指定其他路径。

```toml
[server]
host = "0.0.0.0"
port = 8000

[cache]
dir = "/data"

[log]
level = "INFO"

[proxy]
url    = "http://127.0.0.1:7890"
bypass = ["eastmoney.com", "qq.com"]

[ttl]
quote     = 30
history   = 3600
nav       = 21600
profile   = 86400
holdings  = "never"     # 历史季度不变，永久缓存
benchmark = 21600
estimate  = 30
fx        = 3600
```

`holdings = "never"` 在加载时转成无穷大。配置文件给人看，可读性优先于类型统一。

### 完整配置项

| 配置键 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| `server.host` | `QUOTESTACK_SERVER_HOST` | `127.0.0.1` | 监听地址 |
| `server.port` | `QUOTESTACK_SERVER_PORT` | `8000` | 监听端口 |
| `cache.dir` | `QUOTESTACK_CACHE_DIR` | `~/.cache/quotestack` | 缓存文件目录 |
| `log.level` | `QUOTESTACK_LOG_LEVEL` | `INFO` | `DEBUG` 输出完整排查信息 |
| `proxy.url` | `QUOTESTACK_PROXY_URL` | 空 | 出站代理 |
| `proxy.bypass` | `QUOTESTACK_PROXY_BYPASS` | 空 | 逗号分隔的域名列表 |
| `ttl.quote` | `QUOTESTACK_TTL_QUOTE` | 30 | 秒 |
| `ttl.history` | `QUOTESTACK_TTL_HISTORY` | 3600 | 秒 |
| `ttl.nav` | `QUOTESTACK_TTL_NAV` | 21600 | 秒 |
| `ttl.profile` | `QUOTESTACK_TTL_PROFILE` | 86400 | 秒 |
| `ttl.holdings` | `QUOTESTACK_TTL_HOLDINGS` | `never` | `never` 或秒数 |
| `ttl.benchmark` | `QUOTESTACK_TTL_BENCHMARK` | 21600 | 秒 |
| `ttl.estimate` | `QUOTESTACK_TTL_ESTIMATE` | 30 | 秒 |
| `ttl.fx` | `QUOTESTACK_TTL_FX` | 3600 | 秒 |

`HTTPS_PROXY` / `HTTP_PROXY` 也会被识别，但优先级低于 `QUOTESTACK_PROXY_URL`。

### 验证配置生效

启动日志会打一条环境快照：

```json
{"event":"startup","version":"0.1.0","proxy":null,
 "ttl":{"quote":60,"history":3600,"holdings":"never"}}
```

`/healthz` 同样返回当前生效的配置，用于确认容器里到底加载了什么：

```json
{"data":{"config":{"ttl":{"quote":60,"holdings":"never"}},"sources":{...}}}
```

改了配置但行为没变时，先看这两处，再看是否重启过。

### 配置校验

加载时校验，非法值直接拒绝启动，不做静默降级：

| 规则 | 示例 |
|---|---|
| TTL 必须为正数或 `never` | `quote = 0` → 启动失败 |
| 端口必须在 1–65535 | `port = 70000` → 启动失败 |
| 未知键 → 警告，不阻断 | `ttl.unknown = 5` → 日志警告 |
| 环境变量类型错误 | `QUOTESTACK_TTL_QUOTE=abc` → 启动失败 |

---

### 为什么不用 docker-compose

compose 解决的是「多个容器怎么编排」。本服务是**单进程、零外部依赖**，只有一个容器就没有编排可做，写一份 compose 只是给单条 `docker run` 包一层。

如果调用方要把它和自己的后端一起编排（比如 Spring Boot + quotestack + Postgres），那应该在调用方的仓库里写 compose，引用本镜像即可——本仓库不替他们做这个决定。

---

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

**库调用时**通过构造参数传入；容器部署的代理设置见上文「形态三：Docker → 联网与代理」。

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
