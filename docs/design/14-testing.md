# 测试策略

> quotestack 设计决议 · 第 14 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：✅ 测试、fixture 目录、golden、坏样本、分层检查、CI 均已就位

这个库最大的风险不是逻辑复杂，而是**解析代码依赖的外部页面随时会变**。测试策略必须对准这个风险。

---

## 1. 四层测试

| 层 | 测什么 | 联网 | 速度 |
|---|---|---|---|
| **解析器单元测试** | 一段真实响应 → 结构化结果 | ❌ | ms |
| **适配器测试** | 请求构造、响应解析、错误映射 | ❌ mock | ms |
| **客户端集成** | `resolve → quote → history` 全链路 | ❌ fixture | 百 ms |
| **真实探测** | 各源结构断言是否仍成立 | ✅ | 秒级，手动触发 |

前三层在 CI 里离线跑。第四层是手动触发的工作流（见 [10-open-source](10-open-source.md)）——
GitHub 的 runner 在境外，定时跑只会测出 runner 的位置，不会测出源的结构。

---

## 2. fixture 组织

```
tests/fixtures/
├── manifest.json                   索引：录制时间 / URL / 用途
├── eastmoney/
│   ├── search_000001.json          正常：三候选
│   ├── search_560000_empty.json    空响应
│   ├── kline_cn_daily.json
│   ├── kline_cn_week.json
│   └── kline_schema_changed.json   故意坏的
├── tencent/
├── tiantian/
│   └── pingzhongdata_166002.js     裁剪后
└── binance/
```

`manifest.json` 每条记录：

```json
{
  "path": "eastmoney/kline_cn_daily.json",
  "source": "eastmoney",
  "capability": "history",
  "url": "https://push2his...",
  "recorded_at": "2026-11-07",
  "note": "600519 日线前复权，10 根"
}
```

---

## 3. 载荷放在哪

**现状：绝大多数解析测试用内联载荷。**

`tests/fixtures/` 只有目录、加载器和两个坏样本；真实响应写在测试文件里
（`respx` 的 `text=` / `json=`）。这样做的好处是断言的载荷就在断言旁边，
改动时一处可见。

**需要录制时**（例如上游改版后要保留现场），放到 `tests/fixtures/<源>/`，
按 [`tests/fixtures/README.md`](../../tests/fixtures/README.md) 的约定命名。

大文件必须裁剪：`pingzhongdata` 单份可达 **614 KB**（166002，2008 年至今
4,413 个净值点）。保留 `Data_netWorthTrend` 的前 3 条 + 后 3 条 + 一条带
`equityReturn` 的，其余删除，614 KB → 约 2 KB。裁剪过的样本要在文件名或
`note` 里标注「裁剪样本」，否则以后没人知道它不完整。

---

## 4. 坏样本必须保留

`tests/fixtures/bad/` 里的样本「结构不对」是**故意的**，不能删——否则
`SchemaChanged` 分支永远测不到。现有两个：

| 文件 | 断言什么 |
|---|---|
| `eastmoney_quote_no_envelope.json` | 少了 `data` 键 → `SchemaChangedError` |
| `tiantian_holdings_no_quarters.html` | 空 envelope → 空列表，不是错误 |

**每个适配器的结构断言，都必须配一个故意坏掉的 fixture。** 这是错误处理最常见的漏测点。

---

## 5. golden 快照：只做 4 个

判据是「变化概率 × 影响面」：

| 解析器 | 变化概率 | 影响面 | golden |
|---|---|---|---|
| 腾讯实时（`~` 切 53 字段） | 高 | 大 | ✅ |
| 天天基金 `pingzhongdata` | 高 | 中 | ✅ |
| 东财搜索 → `QuoteID` | 中 | **最大**（所有请求入口） | ✅ |
| 东财 K 线（`klines` 逗号串） | 低 | 大 | ✅ |
| Binance klines | 极低（有 API 契约） | 中 | ❌ |
| 东财 ulist（JSON 字段） | 低 | 大 | ❌ |

不铺开全量快照——源一微调就要改一堆 golden，噪音大于收益。

---

## 6. mock 方案

| 库 | 评价 |
|---|---|
| **respx**（选用） | httpx 生态首选，按 URL 匹配，异步支持好 |
| pytest-httpx | 简单，匹配能力弱 |
| vcrpy | 自动录制回放，但与 httpx 配合一般 |

---

## 7. 防腐烂：两道防线

样本是「过去的真实」，今天能过不代表明天源没变。

1. **手动触发真实探测**（`.github/workflows/live-probe.yml`），跑各源结构断言
2. **结构断言写在解析处**：载荷一旦变形，`SchemaChangedError` 立刻抛出，
   不用等探测

**没有 `manifest.json` 和 90 天过期标记**——样本数量还很少，手工记录更简单；
等样本多了再加。也没有自动开 issue：跑探测的人就是看结果的人，当场修即可
（见 [WORKFLOWS](../harness/WORKFLOWS.md) 的「探测失败之后」）。

---

## 8. 覆盖率目标

| 要求 | 门槛 | 现状 |
|---|---|---|
| 全库行覆盖 | **≥ 85%**，CI 卡（`--cov-fail-under=85`） | 93.3% |
| 分支覆盖 | 不设门槛 | 83.6% |
| 错误映射 | 每种错误至少 1 条用例 | 有 |
| 缓存状态机 | 新鲜 / 过期 / stale / 无数据 | 有 |

**分支覆盖为什么不设门槛**：一旦它成为门槛，就容易为了凑数写测试。
分支覆盖率低通常说明只测了 happy path——这个判断靠读测试，不靠卡数字。

剩下 16% 未覆盖的分支主要是两类：极端防御（payload 里出现完全意料之外的类型），
以及需要多源协作才触发的组合路径。补它们要写「为了覆盖率而写」的测试，收益低于成本。

---

## 9. 运行命令

```bash
# 全部单元 + 集成测试（离线）
uv run pytest -q

# 带覆盖率
uv run pytest --cov=quotestack --cov-fail-under=85

# 单个适配器
uv run pytest tests/test_eastmoney.py -q

# 刷新 fixture（会联网，产出可审查的 diff）
uv run python scripts/record_fixtures.py --source eastmoney --capability history
```

---

## 10. 不测的东西

| 不测 | 原因 |
|---|---|
| 上游真实可用性 | 属于手动探测，不是单元测试 |
| 网络抖动 | 用 mock 模拟，不真跑 |
| CLI 的彩色输出 | 收益低，靠人工看 |
| 性能 | 单独基准脚本，不进 CI |

---

← 上一篇：[运行时模型](13-runtime-model.md) ｜ 下一篇：[代码规范](15-code-style.md) →
