# 测试策略

> quotestack 设计决议 · 第 14 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：🚧 104 个测试通过（3 个 live 用例默认跳过）；fixture 目录、golden、CI 在 M7

这个库最大的风险不是逻辑复杂，而是**解析代码依赖的外部页面随时会变**。测试策略必须对准这个风险。

---

## 1. 四层测试

| 层 | 测什么 | 联网 | 速度 |
|---|---|---|---|
| **解析器单元测试** | 一段真实响应 → 结构化结果 | ❌ | ms |
| **适配器测试** | 请求构造、响应解析、错误映射 | ❌ mock | ms |
| **客户端集成** | `resolve → quote → history` 全链路 | ❌ fixture | 百 ms |
| **真实探测** | 各源结构断言是否仍成立 | ✅ | 秒级，每日 |

前三层在 CI 里离线跑，第四层是每日定时任务（见 [10-open-source](10-open-source.md) 的 CI 三段式）。

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

## 3. 大文件必须裁剪

`pingzhongdata` 单份可达 **614 KB**（166002，2008 年至今 4,413 个净值点），不能原样进仓库。

裁剪规则：保留 `Data_netWorthTrend` 的前 3 条 + 后 3 条 + 一条带 `equityReturn` 的，其余删除。**614 KB → 约 2 KB**，仍能验证解析正确性。

裁剪后的 fixture 在 `note` 里标注「裁剪样本」。

---

## 4. 坏样本必须保留

`kline_schema_changed.json` 这类「结构不对」的样本**不能删**——否则 `SchemaChanged` 分支永远测不到。

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

## 7. 防腐烂：三道防线

fixture 是「过去的真实」，今天能过不代表明天源没变。

1. `manifest.json` 记 `recorded_at`，超过 **90 天**标记 stale
2. 每日真实探测 job 跑各源结构断言
3. 探测失败且连续 2 天 → 更新固定的追踪 issue；恢复时在同一 issue 下评论

---

## 8. 覆盖率目标

| 范围 | 目标 |
|---|---|
| 全库行覆盖 | ≥ **85%** |
| 4 个核心解析器 | 分支覆盖 **100%** |
| 错误映射 | 每种错误至少 1 条用例 |
| 缓存状态机 | 新鲜 / 过期 / stale / 无数据 四态全覆盖 |

覆盖率不达标时 CI 失败（`pytest --cov --cov-fail-under=85`）。

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
| 上游真实可用性 | 属于每日探测，不是单元测试 |
| 网络抖动 | 用 mock 模拟，不真跑 |
| CLI 的彩色输出 | 收益低，靠人工看 |
| 性能 | 单独基准脚本，不进 CI |

---

← 上一篇：[运行时模型](13-runtime-model.md) ｜ 下一篇：[代码规范](15-code-style.md) →
