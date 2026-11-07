# 数据源与覆盖率

> quotestack 设计决议 · 第 3 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)


## 数据源选型

所有结论均来自真实接口探测，非文档推断。

| 市场 | 主源 | 兜底 | 已删除 |
|---|---|---|---|
| A股 / ETF | 东方财富 | 腾讯（实时） | 新浪、网易（502） |
| 美股 | 东方财富 | 腾讯 | Yahoo（429）、Stooq（JS 挑战）、新浪美股 |
| 场外基金 | 天天基金 | akshare | — |
| 加密 | Binance `data-api.binance.vision` | OKX / CoinGecko（需代理） | **CoinGlass（无 K 线）** |
| 汇率 | 东财外汇 | GitHub raw | — |

### A股

| 源 | 实时 | 日K深度 | 复权 | 分钟线 | 周/月K | ETF/指数 |
|---|---|---|---|---|---|---|
| **东财** | ✅ 批量 | **6037 根（2001-08 起）** | ✅ 0/1/2 | ✅ 1/5/15/30/60 | ✅ | ✅ |
| 腾讯 | ✅ 批量 | 640 根 | ✅ qfq | ✅ m5 | ✅ | ✅ |
| 新浪 | ✅ 需 Referer | 2000 根（2018 起） | ❌ | ✅ | ✅ | ✅ |
| 网易 | ❌ 502 | — | — | — | — | — |

东财接口：
- 实时 `push2.eastmoney.com/api/qt/ulist.np/get`
- K线 `push2his.eastmoney.com/api/qt/stock/kline/get`（`klt` 101/102/103，`fqt` 0/1/2）
- 连发 10 次未触发限流

### 美股

| 源 | 实时 | K线深度 | 解析 |
|---|---|---|---|
| **东财** | ✅ `105/106/107.` | **10000 根（1987 起）** | 搜索直出 `QuoteID` |
| 腾讯 | ✅ | 1000 根，需 `.OQ/.N` 后缀 | 需后缀映射 |

**东财市场号**：105 = 纳斯达克，106 = 纽交所，107 = NYSE Arca（SPY 在此）。

**东财缺口由腾讯补齐**：抽样 24 只，东财 21/24，腾讯补足剩余 3 只（JHG / BAYA / DLR），合计 24/24。

### 场外基金

- 来源：天天基金 `fund.eastmoney.com/pingzhongdata/{code}.js`
- 净值：4,413 个点（2008-07-25 起）
- 资产配置：`Data_assetAllocation`（股票/债券/现金占净比时序）
- 前十大持仓 secid：`stockCodesNew`（直接给出 `1.688825` 这种）
- 持仓明细：`fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc`（HTML，一年一次请求返回 4 个季度）
- 基金概况：`fundf10.eastmoney.com/jbgk_{code}.html`（跟踪标的、业绩基准、管理人、规模）

### 加密

**关键发现**：`data-api.binance.vision` 是国内可达的官方公开数据域名，接口与 `api.binance.com/api/v3` 完全一致。

- 实时、K线、24hr ticker 全部可用
- 周期：`1m / 15m / 1h / 4h / 1d / 1w / 1M`
- 分页：`endTime` 可回溯
- 连发 15 次未触发限流

**被墙的**：`api.binance.com`、`www.okx.com`、`api.coingecko.com`、`api.huobi.pro`。

**归档通道**：`data.binance.vision` 的 zip 文件也可达，可作历史回补。

### 汇率

- 主源：东财外汇（`133.USDCNH` 美元兑离岸人民币、`120.USDCNYC` 中间价），国内稳定
- 备源：GitHub raw `Sunny-DotNet/ExchangeRates`（实测抖动，首次 000 后重试 200）
- 兜底：磁盘运行时缓存 → 种子文件 → 硬编码常量

---

## 覆盖率现状

| 类别 | 品种库条数 | 覆盖率（抽样） |
|---|---|---|
| A股股票（含科创板/创业板/北交所） | 5,528 | 东财 15/15 |
| 场内基金（ETF/LOF） | 2,637 | 东财 14/15 |
| 场外基金 | 24,343 | 天天基金 15/15 |
| 美股 | 13,379 | 东财 21/24 + 腾讯 = 24/24 |
| 加密 | 83 | Binance 11/15（无代理）/ 14/15（有代理） |

**已知缺口**

- 已清盘 / 退市品种（如 581002 分级基金）
- 加密：USDG / MEW / MOODENG / POPCAT
- 中债系列指数（`中债总指数` 等）不在东财体系内
- 场外基金无盘中实时价，只有 T-1 净值（已验证 `fundgz` 估值接口 404）

---

---

← 上一篇：[标识解析](02-identity.md) ｜ 下一篇：[缓存](04-cache.md) →
