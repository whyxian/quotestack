# 测试策略

> quotestack 设计决议 · 第 14 部分 · v0.9（2026-11-22）
> 返回索引 → [README](README.md)
> **实现状态**：✅ 六层目录、共享假源、坏样本、契约测试、CI 均已就位

这个库最大的风险不是逻辑复杂，而是**解析代码依赖的外部页面随时会变**。测试策略对准这个风险：
样本会过期，所以真正的防线是「结构断言写在解析处」和「手动真实探测」。

---

## 1. 什么叫测好了

| 要求 | 门槛 | 现状 |
|---|---|---|
| 全库行覆盖 | **≥ 85%**，CI 卡（`--cov-fail-under=85`） | 93.3% |
| 分支覆盖 | 不设门槛 | 83.6% |
| 每种错误 | 至少 1 条用例 | 有 |
| 缓存状态机 | 新鲜 / 过期 / stale / 无数据 | 有 |
| 文档事实 | 表格与代码一致，由 `contracts/` 保证 | 有 |

**分支覆盖为什么不设门槛**：一旦成为门槛，就容易为了凑数写测试。分支覆盖低通常说明只测了
happy path——这个判断靠读测试，不靠卡数字。

**不测的东西**

| 不测 | 原因 |
|---|---|
| 上游真实可用性 | 属于手动探测，不是单元测试 |
| 网络抖动 | 用 respx 模拟，不真跑 |
| CLI 彩色输出 | 收益低，靠人工看 |
| 性能 | 单独基准脚本，不进 CI |

---

## 2. 六层目录

| 目录 | 保证什么 | 允许知道什么 | 联网 |
|---|---|---|---|
| `tests/unit/` | 单个函数或类的行为 | 只需 `quotestack` 的纯函数 | ❌ |
| `tests/sources/` | 一个源的请求构造、解析、错误映射 | 一个适配器 + respx | ❌ |
| `tests/client/` | 多源编排：缓存、降级、批量、估值 | `MarketData` + 假源 | ❌ |
| `tests/interfaces/` | HTTP 契约与 CLI 行为 | ASGI 进程内、argparse | ❌ |
| `tests/contracts/` | 文档、分层、事件与代码一致 | 读源码与 Markdown | ❌ |
| `tests/live/` | 上游结构是否仍成立 | 真实网络 | ✅ 手动 |

**放错层比写错断言更伤**：在 `client/` 里测一个解析细节，失败时你不知道是解析坏了还是编排坏了。

`tests/support/` 与 `tests/fixtures/` 不是测试：前者是工具（`ROOT`、假源、live 策略），
后者是样本。

---

## 3. 命名

| 规则 | 例子 |
|---|---|
| 文件按**被测对象**命名 | `test_eastmoney_klines.py`，不是 `test_klines.py` |
| 用例名是一句**断言** | `test_a_row_with_no_trades_is_not_a_price` |
| 不用描述"写入批次"的后缀 | ~~`_edges`~~、~~`_paths`~~——它们说的是当时补测试的心情 |
| 同名用例只允许出现在不同层 | `test_holdings_rejects_a_bad_cursor`（client）与 `..._over_http`（server） |

**一个文件只服务一个主题**。文件超过 ~400 行是一个信号：测试大概在测两件不同的事。

---

## 4. 共享设施

```
tests/support/
├── __init__.py     ROOT：仓库根路径
├── fakes.py        make_meta / FailingSource / StaticQuoteSource
└── live_policy.py  哪些失败是环境问题（跳过），哪些是信号（失败）
```

`make_meta(name, capabilities, markets)` 消掉了每个假源手写五行的 `SourceMeta`。

**什么该抽、什么留在用例里**

| 抽 | 留 |
|---|---|
| 「返回固定值」「总是抛异常」这类通用假源 | 有特殊行为的假源（schema 变更、按调用返回不同值） |
| 仓库路径、跨文件共享的策略 | 只在一个用例里用的构造 |

抽得过度的信号：为了配置一个假源，读测试的人要跳三个文件。

---

## 5. 样本策略

**现状：绝大多数解析测试用内联载荷。**

`tests/fixtures/` 只有加载器和两个坏样本；真实响应写在测试文件里（respx 的 `text=` / `json=`）。
好处是断言的载荷就在断言旁边。

**需要录制时**放到 `tests/fixtures/<源>/`，按 [`tests/fixtures/README.md`](../../tests/fixtures/README.md)
的约定命名。大文件必须裁剪：`pingzhongdata` 单份可达 614 KB（166002，2008 年至今 4,413 个
净值点），保留 `Data_netWorthTrend` 的前 3 条 + 后 3 条 + 一条带 `equityReturn` 的，其余删除，
614 KB → 约 2 KB。裁剪过的样本要标注，否则以后没人知道它不完整。

### 坏样本必须保留

`tests/fixtures/bad/` 里的「结构不对」是**故意的**，删了 `SchemaChanged` 分支就永远测不到：

| 文件 | 断言什么 |
|---|---|
| `eastmoney_quote_no_envelope.json` | 少了 `data` 键 → `SchemaChangedError` |
| `tiantian_holdings_no_quarters.html` | 空 envelope → 空列表，不是错误 |

**每个适配器的结构断言，都必须配一个故意坏掉的样本。**

---

## 6. 契约测试：守住文档

`tests/contracts/` 不测行为，测**一致性**。它是这一层存在的唯一理由：文档里的表格会过时，
没有人会记得同步。

| 文件 | 防什么漂移 |
|---|---|
| `test_design_docs.py` | 能力表、错误状态表、TTL 表、事件字段、CLI 命令、示例脚本、README 路由 |
| `test_guide.py` | 指南里的能力矩阵、错误码、基金分类、批量请求数 |
| `test_architecture.py` | 谁能 import 谁（AST 检查，不引新依赖） |
| `test_observability.py` | 事件名与字段 |
| `test_fixtures.py` | 样本加载器的约定 |

写这类测试的判据：**这段文字如果和代码不一致，用户会做错事吗？** 会，就值得一条测试。

---

## 7. 运行

```bash
uv run pytest -q                        # 全部离线
uv run pytest tests/unit -q             # 只跑一层
uv run pytest tests/sources/test_eastmoney_klines.py -q   # 只跑一个文件
uv run pytest -q --cov=quotestack       # 带覆盖率
uv run pytest tests/live -q -rs         # 需要 QUOTESTACK_LIVE=1
```

CI 跑 `uv run pytest -q --cov=quotestack`，门槛 85%。

---

## 8. 写新测试前的自查

1. **这属于哪一层？** 放错层会让失败信息指向错误的地方。
2. **能不能测更小的东西？** 能测纯函数就别组装整个客户端。
3. **失败时的信息够不够定位？** 断言消息要说明"期望什么、实际什么"。
4. **它测的是行为还是实现？** 断言 `result.price == "1453.00"`，不要断言私有方法被调用。
5. **有没有对应的坏样本？** 解析器的新分支，通常需要一条"结构不对"的用例。
6. **它会不会在源改版时误报？** 依赖外部文本细节的断言，要写清为什么这个细节重要。

---

## 9. 防腐烂：两道防线

样本是「过去的真实」，今天能过不代表明天源没变。

1. **手动触发真实探测**（`.github/workflows/live-probe.yml`），跑各源结构断言
2. **结构断言写在解析处**：载荷一旦变形，`SchemaChangedError` 立刻抛出，不用等探测

没有 `manifest.json`，也没有过期标记——样本还少，手工记录更简单；
跑探测的人就是看结果的人，当场修即可（见 [WORKFLOWS](../harness/WORKFLOWS.md)）。

---

← 上一篇：[运行时模型](13-runtime-model.md) ｜ 下一篇：[代码规范](15-code-style.md) →
