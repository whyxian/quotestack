# 开发路线图

> 版本：v1.0 · 2026-11-07
> 更新时间：每完成一项就勾选，并同步「当前进度」

**用法**：从上往下做，一个阶段全部勾完才进入下一阶段。每阶段末尾有「完成标准」，达不到不推进。

---

## 当前进度

```
阶段：M3.6 完成 ✅ → 下一步 M4 基金链路
已完成：11 / 11（累计 51 / 84 项）
下一项：M4-3 基准加权曲线
```

---

## M0 环境与脚手架

> 目标：能跑通 `import quotestack`，工程骨架就位。

- [x] **M0-1** 安装 uv（`brew install uv`；若 PyPI 不可达先配镜像）
- [x] **M0-2** 安装 Python 3.11（`uv python install 3.11`）
- [x] **M0-3** 建立目录结构
  ```
  quotestack/
  ├── src/quotestack/
  ├── tests/
  ├── examples/
  ├── docs/
  └── pyproject.toml
  ```
- [x] **M0-4** 写 `pyproject.toml`（hatchling、依赖、ruff、mypy、scripts）
- [x] **M0-5** 加 `.gitignore`、`LICENSE`（MIT）、`py.typed`
- [x] **M0-6** `git init` + 首次提交
- [x] **M0-7** 配 pre-commit（ruff + ruff-format + mypy）
- [x] **M0-8** 建虚拟环境并验证

**完成标准**

```bash
uv run python -c "import quotestack; print(quotestack.__version__)"
uv run ruff check .      # 通过
uv run mypy src          # 通过
```

**规模**：S（半天内）

---

## M1 最小可用版本（MVP）

> 目标：`quotestack quote 600519` 和 `quotestack history 600519` 能出真实数据。

只做东财一个源，只做三个方法。

- [x] **M1-1** `errors.py`：先做 4 种（`InvalidArgument` / `NotFound` / `Unsupported` / `UpstreamError`）
- [x] **M1-2** `models/`：`Instrument`、`Quote`、`Bar`（价格用 `str`）
- [x] **M1-3** `identity/`：CN 代码前缀规则 → secid
- [x] **M1-4** `sources/base.py`：`Resolver` / `Quoter` / `Historian` 三个 Protocol
- [x] **M1-5** `sources/eastmoney.py`：实时报价（`ulist.np`）
- [x] **M1-6** `sources/eastmoney.py`：K 线（`kline/get`，支持 interval/adjust/limit）
- [x] **M1-7** `cache/memory.py`：带 TTL 的内存缓存
- [x] **M1-8** `client.py`：`resolve` / `quote` / `history` 三个入口
- [x] **M1-9** `cli.py`：`quote`、`history` 两个命令
- [x] **M1-10** 冒烟测试脚本
- [x] **M1-11** 生成 `docs/harness/ARCHITECTURE.md`（as-built，从真实代码提取），并更新 `AGENTS.md` 索引

**完成标准**

```bash
quotestack quote 600519
# → 贵州茅台 1453.00 CNY +0.07%

quotestack history 600519 --limit 5
# → 5 根日 K
```

**规模**：M（1–2 天）

---

## M2 基础能力补齐

> 目标：错误、缓存、日志达到文档规定的水平。

- [x] **M2-1** 错误模型补齐到 11 种 + HTTP 映射
- [x] **M2-2** `SchemaChanged` 检测（每个适配器带结构断言）
- [x] **M2-3** 缓存三态（fresh / stale / miss）+ `max_stale`
- [x] **M2-4** 单飞（并发合并）
- [x] **M2-5** 冷却机制（15 行）
- [x] **M2-6** 上游限流（令牌桶 5 req/s）
- [x] **M2-7** 结构化日志 + `hint` 硬约束
- [x] **M2-8** 缓存键按规范实现（`v1|capability|...`）
- [x] **M2-9** 补全 CLI：`resolve` 与 `health` 两个命令
- [x] **M2-10** 同步包装 `quotestack.sync.SyncMarketData`（后台线程常驻事件循环）
- [x] **M2-11** `max_age` 单次调用覆盖 TTL

**完成标准**

```bash
quotestack health          # 显示各源状态
QUOTESTACK_LOG_LEVEL=DEBUG quotestack quote 600519   # 日志含 cache_lookup / upstream_request
```
拔掉网线后 `quotestack quote 600519` 仍能返回上次结果并标 `stale`。

**规模**：M（1–2 天）

---

## M3 多源与批量

> 目标：一个源挂了不影响使用。

- [x] **M3-1** `sources/tencent.py`：实时报价（A股 + 美股）
- [x] **M3-2** `sources/tiantian.py`：场外基金净值
- [x] **M3-3** 路由表 + 降级链
- [x] **M3-4** `quote_many`（等长同序、单条失败不拖垮整批）
- [x] **M3-5** 美股 secid 解析（东财搜索 `QuoteID`）
- [x] **M3-6** `resolve` 的 `Ambiguous` 分支 + `candidates`（`expected_name` 挪到 M6 的 HTTP 参数）
- [x] **M3-7** `fx` 汇率（USD 基准 + 交叉换算）
- [x] **M3-8** 代理支持（`proxy` / `proxy_bypass`，让 OKX 与 CoinGecko 可达）

**完成标准**

```bash
quotestack quote AAPL --market US --asset-class STOCK
quotestack health          # 东财与腾讯都显示 ok
```
手动禁用东财后，报价自动走腾讯。

**规模**：M（1–2 天）

---

## M3.5 全市场列表

> 目标：让调用方能自己刷新品种库，不依赖人工维护。

- [x] **M3.5-1** `Capability.LIST` + `InstrumentSummary`
- [x] **M3.5-2** 东财列表（A股 / 场内基金 / 美股，分页）
- [x] **M3.5-3** 天天基金全量（28,305 只，带基金类型）
- [x] **M3.5-4** Binance `exchangeInfo`（USDT + TRADING）
- [x] **M3.5-5** `client.iter_instruments` + 路由
- [x] **M3.5-6** `FundClass` 七分类 + `classify_fund_type`（FOF/REITS 暂标 unsupported）

**完成标准**

```python
async for batch in client.iter_instruments(AssetClass.STOCK, Market.CN):
    ...
```

**规模**：S

---

## M3.6 代码重构（技术债）

> 目标：把超出规模红线的文件拆开。M3.5 结束时 `client.py` 708 行、`eastmoney.py` 642 行，都超过 400 行红线。

- [x] **M3.6-1** 拆分 `client.py` → `client/` 包（quote / history / fund / listing / admin）
- [x] **M3.6-2** 拆分 `eastmoney.py` → 行情、列表、搜索三个模块
- [x] **M3.6-3** 补齐 `upstream_request` 与 `batch` 事件埋点

**完成标准**

```bash
find src -name '*.py' -exec wc -l {} + | sort -rn | head -3   # 全部 < 400
```

**规模**：M（半天）

---

## M4 基金链路

> 目标：基金画像、季度持仓、基准曲线可用。

- [x] **M4-1** `profile`：基金类型、跟踪标的、业绩基准、规模
- [x] **M4-2** `holdings`：季度持仓（分页、永久缓存）
- [ ] **M4-3** `benchmark`：基准解析 + 加权曲线 + `effective_start`
- [x] **M4-4** 基准字符串解析器（含权重、可还原判定）
- [x] **M4-5** 权益/非权益判定（三步规则）

**完成标准**

```bash
quotestack profile 166002
quotestack holdings 022430 --limit 2
```
166002 的基准能拆出「中证800×70% + 上证国债×25% + 存款×5%」。

**规模**：L（2–3 天）

---

## M5 估值

> 目标：`estimate` 可用，并带完整假设说明。

- [ ] **M5-1** 指数型公式（跟踪指数 × 非现金债券占比）
- [ ] **M5-2** 主动型公式（前十大 + 剩余按权益基准）
- [ ] **M5-3** 货币基金短路（`basis=none`）
- [ ] **M5-4** `benchmark_assumption` 输出
- [ ] **M5-5** `explanation` 人话生成
- [ ] **M5-6** 回测脚本 `benchmarks/estimate_accuracy.py`

**完成标准**

```bash
quotestack estimate 022430
# → change_pct + basis + coverage + explanation
```
回测脚本对 166002 跑出相关系数与 MAE，写入文档。

**规模**：M（1–2 天）

---

## M6 服务化

> 目标：Java 后端可以通过 HTTP 调用。

- [ ] **M6-1** `quotestack_server`：FastAPI 壳
- [ ] **M6-2** 11 条路由
- [ ] **M6-3** 统一错误响应 + HTTP 状态码映射
- [ ] **M6-4** `/healthz`
- [ ] **M6-5** `/metrics`（`prometheus_client`，放 `[server]` extra）
- [ ] **M6-6** `Dockerfile`（单容器，不写 compose）
- [ ] **M6-7** 事件钩子（库零依赖，server 接 metrics）
- [ ] **M6-8** 生成 `docs/api/openapi.yaml`，CI 校验与代码一致
- [ ] **M6-9** 配置加载（`quotestack.toml` + 环境变量覆盖 + 启动校验）

**完成标准**

```bash
docker build -t quotestack . && docker run -p 8000:8000 quotestack
curl localhost:8000/v1/quote?code=600519&asset_class=STOCK&market=CN
curl localhost:8000/healthz
curl localhost:8000/metrics
```

**规模**：M（1–2 天）

---

## M7 工程质量

> 目标：达到可开源的质量门槛。

- [ ] **M7-1** fixture 录制脚本 + 目录结构
- [ ] **M7-2** 4 个核心解析器的 golden 测试
- [ ] **M7-3** 坏样本（`schema_changed`）测试用例
- [ ] **M7-4** 单测覆盖率 ≥ 85%
- [ ] **M7-5** CI 三段式（PR / 每日探测 / 发布）；探测覆盖每个源×能力
- [ ] **M7-6** `examples/` 三个脚本
- [ ] **M7-7** import-linter 分层检查

**完成标准**

```bash
uv run pytest --cov=quotestack --cov-fail-under=85
```
CI 全绿。

**规模**：L（2–3 天）

---

## M8 开源发布

> 目标：`pip install quotestack` 可用。

- [ ] **M8-1** `README.md`（英文）+ `README.zh-CN.md`
- [ ] **M8-2** `CONTRIBUTING.md`、`SECURITY.md`、`CHANGELOG.md`、`CODE_OF_CONDUCT.md`
- [ ] **M8-3** Issue / PR 模板
- [ ] **M8-4** 发布前检查（个人路径、调试代码、`.DS_Store`）
- [ ] **M8-5** TestPyPI 验证打包
- [ ] **M8-6** PyPI 发布 `0.0.1`
- [ ] **M8-7** 打 tag + GitHub Release

**完成标准**

```bash
pip install quotestack
quotestack quote 600519
```

**规模**：M（1 天）

---

## M9 接入 AssetPilot（后续）

> 以下不属于 quotestack 本身，属于下游接入。

- [ ] **M9-1** Spring Boot 后端接 `quote_many`
- [ ] **M9-2** 三态降级对接（REALTIME / HISTORICAL / UNAVAILABLE）
- [ ] **M9-3** 前端历史走势图接 `history`
- [ ] **M9-4** 基金估值接 `estimate`

---

## 里程碑视图

| 里程碑 | 包含阶段 | 产出 |
|---|---|---|
| **可自用** | M0–M1 | 命令行能查 A 股 |
| **可稳定用** | M0–M3 | 多源、缓存、降级齐全 |
| **可给朋友用** | M0–M5 | 基金完整链路 |
| **可被 Java 调用** | M0–M6 | HTTP 服务 |
| **可开源** | M0–M8 | PyPI 可安装 |

---

## 风险与依赖

| 风险 | 影响 | 应对 |
|---|---|---|
| PyPI 不可达 | M0 卡住 | 用国内镜像（见 09-deployment 故障表） |
| 上游接口改版 | M1/M3 返工 | fixture 测试 + 每日探测 |
| 东财搜索限流 | M3 卡住 | 解析结果缓存 7 天 |
| 估值精度不足 | M5 返工 | 回测数据说话，不承诺精度 |

---

## 更新规则

1. 每完成一项，把 `[ ]` 改成 `[x]`，并更新顶部「当前进度」。
2. 新增任务插到对应阶段，不新建阶段。
3. 阶段完成标准未达成时，不开下一阶段。
4. 若某任务无法完成，写进「风险与依赖」并说明原因，不要静默跳过。
5. **每个阶段结束前必须更新 `AGENTS.md`**：新增的命令、新的红线、新的文档索引项。
6. 实现与设计偏离时，先改 `docs/design/` 再改代码，不要在代码里默默绕过。
