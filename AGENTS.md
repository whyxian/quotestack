# quotestack AI 开发上下文

> 本文件是 AI 编码助手的入口：**索引 + 红线 + 命令**。
> 详细设计不写在这里，全部在 `docs/design/`。

---

## 1. 项目一句话

**面向 A股 / 美股 / 场外基金 / 加密 的多源适配层**——把四类资产的数据源差异收敛成一套一致的调用方式。

---

## 2. 当前阶段

**M6 已完成**：库、CLI、HTTP 服务、Docker 均可用。下一步 M7 工程质量。

进度见 [docs/ROADMAP.md](docs/ROADMAP.md)，每完成一项会勾选。

**开始任何任务前，先看 ROADMAP 确认当前阶段**——不要跳阶段实现。

---

## 3. 快速命令

```bash
uv sync --extra dev --extra server   # 安装依赖（服务端需要 server extra）
uv run pytest -q                     # 测试（全离线）
uv run pytest --cov=quotestack --cov-fail-under=85   # 带覆盖率
uv run ruff check .                  # lint
uv run ruff format .                 # 格式化
uv run mypy src                      # 类型检查
quotestack quote 600519              # 冒烟：查实时价
quotestack estimate 022430           # 基金盘中估值
quotestack-server --dump-openapi     # 重新生成 OpenAPI（改接口后必做）
```

> 当前全部可用。**提交前钩子已启用**：ruff + format + mypy 由 pre-commit 自动执行。

---

## 4. 文档索引

**设计文档（为什么这么设计）**

| 主题 | 文件 |
|---|---|
| 为什么做这个 / 与竞品差异 | [00-why](docs/design/00-why.md) |
| 定位与边界 | [01-overview](docs/design/01-overview.md) |
| 标识解析（code → secid） | [02-identity](docs/design/02-identity.md) |
| 数据源选型与覆盖率 | [03-sources](docs/design/03-sources.md) |
| 缓存与缓存键 | [04-cache](docs/design/04-cache.md) |
| 接口 / HTTP / CLI / 格式契约 | [05-api](docs/design/05-api.md) |
| 错误模型（11 种） | [06-errors](docs/design/06-errors.md) |
| 基金能力与估值 | [07-funds](docs/design/07-funds.md) |
| 适配器组织与兜底链 | [08-adapters](docs/design/08-adapters.md) |
| 部署 / 代理 / 开发环境 | [09-deployment](docs/design/09-deployment.md) |
| 开源标准与版本策略 | [10-open-source](docs/design/10-open-source.md) |
| 实测证据 | [11-evidence](docs/design/11-evidence.md) |
| 日志与可观测性 | [12-observability](docs/design/12-observability.md) |
| 运行时模型（async/限流/并发） | [13-runtime-model](docs/design/13-runtime-model.md) |
| 测试策略 | [14-testing](docs/design/14-testing.md) |
| 代码规范 | [15-code-style](docs/design/15-code-style.md) |
| 术语表 | [16-glossary](docs/design/16-glossary.md) |

**实现文档（代码长什么样）**

| 主题 | 文件 |
|---|---|
| 模块结构、依赖方向、数据流 | [ARCHITECTURE](docs/harness/ARCHITECTURE.md) |
| **逐文件中文导读（读代码从这里开始）** | [CODE_MAP_ZH](docs/harness/CODE_MAP_ZH.md) |

**接口契约（机器可读）**

| 主题 | 文件 |
|---|---|
| OpenAPI 3.1 规范 + 阅读指南 | [docs/api/README](docs/api/README.md) |

---

## 5. 核心红线

违反任意一条，代码不可合并。

1. **价格、金额、成交量一律用 `str` 传输**，禁止 `float`/`int` 承载金额。理由见 [05-api](docs/design/05-api.md)。
2. **库不得配置 logging handler**，只发结构化事件。配置由调用方负责。
3. **源差异只能关在 `sources/` 内**，上层只见统一模型。`sources` 不得 import `client`。
4. **缓存不得无限期返回旧值**，超过 `max_stale` 必须抛错，不能拿一个月前的价格冒充现价。
5. **禁止一个字段有多种类型**（如 `float | str`），类型必须唯一。

---

## 6. 已知陷阱

写代码前值得知道，都来自真实踩坑：

| 陷阱 | 说明 |
|---|---|
| `000001` 二义性 | 既是平安银行（STOCK）也是华夏成长混合（FUND），必须用 `asset_class + market + code` 三元组定位 |
| ETF 联接基金 | 股票仓位只有 ~2%，90%+ 资产是目标 ETF。估值不能用股票仓位当系数 |
| 成交量单位 | 腾讯给「手」，东财给「股」，Binance 给「币」——统一乘 100 转成最小单位 |
| 中文编码 | 腾讯返回 **GBK**，必须显式转码，否则中文乱码 |
| 交易日 vs 时刻 | K 线的 `date` 是本地交易日（无时区），实时报价的 `ts` 才是带偏移的时刻。不许混用 |
| 场外基金无 K 线 | 场外基金只有每日净值，调用 `history` 应返回 `Unsupported`，不是空数组 |
| 中债指数不可得 | 基金基准里的「中债系列」东财拿不到，按非权益处理 |
| 514 是防爬码 | 东财对 fundf10 页有频率限制：4 req/s 通过，5 req/s 触发 514 |
| 季报有发布延迟 | 回测必须滞后约 20 天才启用某季持仓，否则是未来函数 |
| 基金代码前缀不可靠 | `166002` 是场外基金但前缀是 `16`；不能靠前缀判断场内/场外 |
| 涨跌幅单位 | 东财 `f3` 固定是 0.01%，与价格小数位无关；按 `10^f1` 缩放会错 10 倍 |
| 列表分页 | 东财 `pz` 最大 100，必须用 `data.total` 判断结束，不能靠"这页不满" |

---

## 7. 编码风格

完整规范见 [15-code-style](docs/design/15-code-style.md)。速览：

- ruff（lint + format）+ mypy strict，pre-commit 与 CI 双卡
- 函数 ≤ 40 行、参数 ≤ 5 个、嵌套 ≤ 3 层
- **不设文件行数上限**，拆分只看是否有独立职责与名字
- 注释与 docstring **全英文**，Google Style
- 注释只解释「为什么」，不复述「是什么」
- 禁止：`print`、裸 `except`、可变默认参数、async 里的阻塞调用、裸 `Any`

---

## 8. 提交约定

Conventional Commits，scope 用模块名：

```
feat(eastmoney): add weekly and monthly kline
fix(cache): avoid duplicate fetch when key expires
docs(design): clarify cache key format
test(eastmoney): add schema-changed fixture
```

---

## 9. 常见工作流

**新增一个数据源**

1. 在 `sources/` 新建文件，实现所需 Protocol
2. 声明 `name` / `capabilities` / `markets` / `timeout`
3. 在路由表登记优先级
4. 录制 fixture + 写解析测试（含一个 `schema_changed` 坏样本）
5. 更新 [03-sources](docs/design/03-sources.md) 的覆盖率表

**修一个解析 bug**

1. 先补一个能复现的 fixture
2. 改解析器
3. 跑 `uv run pytest tests/test_<source>.py`
4. 跑每日探测确认线上结构仍匹配

**改设计决策**

设计文档是决策记录，**不要悄悄改代码绕过它**。若实现中发现设计有问题：

1. 先改 `docs/design/` 对应文件
2. 再改代码
3. 在提交信息里说明「设计变更」

**每篇设计文档顶部都有「实现状态」标注**

完成一个里程碑时，同步更新受影响文档的状态：

| 标注 | 含义 |
|---|---|
| ✅ 已实现 | 文档描述与代码一致 |
| 🚧 部分 | 部分实现，需注明缺口 |
| ⬜ 未开始 | 已设计，代码未动 |
| 📄 概念 / 记录 | 非代码文档 |

**文档不得把未实现的功能写得像已存在**——这是最容易被读者当成 bug 的地方。

---

## 10. 工作边界（对所有 AI 助手生效）

| 范围 | 行为 |
|---|---|
| 工作区内（`quotestack/`） | 可自主读写 |
| `/tmp` | 仅临时文件，用完即弃 |
| **工作区外** | **必须先问，说明写什么、占多大、怎么撤销** |

**必须先问的操作**

- 安装软件（brew / uv / python / npm 全局包）
- 写入 `~/.cache`、`~/.local`、`~/.config`、`~/.ssh`
- 修改 shell 配置文件（`.zshrc`、`.bashrc` 等）
- 启动常驻进程或系统服务
- 任何会让机器状态在任务结束后仍然改变的操作

**自我约束**

1. 只装跑通当前任务的最小集合，不装"顺便有用"的工具
2. 不在 `PATH` 里留可执行文件
3. 每项系统级操作前给出：目标路径 / 预计占用 / 撤销命令

---

## 11. 不要做的事

- ❌ 不要跳过 ROADMAP 的阶段顺序
- ❌ 不要在 `sources/` 里写业务逻辑（估值、盈亏属于上层）
- ❌ 不要把多个源的解析逻辑合并成一个"万能函数"
- ❌ 不要为了让测试通过而放宽结构断言
- ❌ 不要提交 `.DS_Store`、`__pycache__`、缓存文件
