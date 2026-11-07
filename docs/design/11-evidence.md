# 实测证据

> quotestack 设计决议 · 第 11 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)
> **实现状态**：📄 实测记录，非代码

设计文档里的每条结论都来自真实接口探测，不是二手资料。本文记录**怎么复现**。

> 探测时间：2026-11-07。上游随时可能变化，结论以复现结果为准。

---

## 1. 东方财富

### A股全历史

```bash
curl -s "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600519\
&fields1=f1&fields2=f51,f53&klt=101&fqt=1&lmt=10000&end=20500101" \
| python3 -c "import sys,json; k=json.load(sys.stdin)['data']['klines']; print(len(k), k[0][:10], k[-1][:10])"
```

实测：`6037 根 2001-08-27 2026-11-06`

### 美股全历史

```bash
curl -s "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=105.AAPL\
&fields1=f1&fields2=f51,f53&klt=101&fqt=1&lmt=10000&end=20500101"
```

实测：`10000 根，1987-03-02 起`

### 价格是放大整数

```bash
curl -s "https://push2.eastmoney.com/api/qt/ulist.np/get?secids=1.600519,1.510010&fields=f1,f2"
```

实测：

| 标的 | f1（小数位） | f2（原始值） | 还原 |
|---|---|---|---|
| 600519 | 2 | 145300 | 1453.00 |
| 510010 | 3 | 1760 | 1.760 |

**结论**：不能统一按 ÷100，必须读 `f1`。

### K 线是 O-C-H-L 顺序

```bash
curl -s "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600519\
&fields1=f1&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&lmt=1&end=20500101"
```

实测一行：`2026-11-06,1450.00,1453.00,1457.72,1436.00,42848`

按位置是 **date, open, close, high, low, volume**——不是 OHLC。

### 搜索返回多个候选

```bash
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=000001&type=14&count=5"
```

实测返回三个：`深A:平安银行` / `指数:上证指数` / `基金:华夏成长混合`。

**结论**：必须用 `asset_class` 消歧，不能只靠代码。

### 空响应的真实案例

```bash
curl -s "https://push2.eastmoney.com/api/qt/ulist.np/get?secids=1.560000&fields=f2"
```

实测：`{"rc":100,...,"data":null}` — HTTP 200、结构正常、就是没有这只票。

**结论**：这属于 `EmptyResponse`，重试同源没有意义，应立刻换源。

### 未触发限流

连续 10 次 `ulist.np` 请求，全部 HTTP 200。

---

## 2. 腾讯

### 覆盖东财缺失的美股

```bash
curl -s "https://qt.gtimg.cn/q=usJHG,usBAYA,usDLR" | iconv -f GBK -t UTF-8
```

实测三只全部返回，而东财对 `JHG` / `BAYA` / `DLR` 均无数据。

**结论**：腾讯是美股的必要兜底。

### 返回 GBK 编码

同一命令不加 `iconv` 时中文为乱码。

**结论**：适配器必须显式转码。

---

## 3. 天天基金

### 净值历史深度

```bash
curl -s "https://fund.eastmoney.com/pingzhongdata/166002.js" -H 'User-Agent: Mozilla/5.0' -o /tmp/f.js
du -h /tmp/f.js
grep -o 'Data_netWorthTrend = \[.\{0,80\}' /tmp/f.js
```

实测：文件 614 KB，含 4413 个净值点（2008-07-25 起）。

### 历史季度持仓

```bash
curl -s "https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code=166002&topline=10&year=2020" \
  -H 'User-Agent: Mozilla/5.0' | grep -o '2020年[0-9]季度' | sort -u
```

实测返回 2020 年全部 4 个季度。

### ETF 联接基金的股票仓位极低

```bash
for c in 022430 012733 166002; do
  curl -s "https://fund.eastmoney.com/pingzhongdata/$c.js" -H 'User-Agent: Mozilla/5.0' \
  | grep -o '"name":"股票占净比","type":null,"data":\[[^]]*\]'
done
```

实测：

| 基金 | 股票占净比 |
|---|---|
| 022430（ETF 联接） | 1.91% ~ 2.73% |
| 012733（ETF 联接） | 1.34% ~ 2.24% |
| 166002（主动混合） | 69.69% ~ 75.7% |

**结论**：联接基金不能用股票仓位做估值系数。

---

## 4. Binance

### 国内可达的数据域名

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://api.binance.com/api/v3/time     # 000
curl -s -o /dev/null -w '%{http_code}\n' https://data-api.binance.vision/api/v3/time  # 200
```

**结论**：默认使用 `data-api.binance.vision`。

### 日线深度与翻页

```bash
curl -s "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=1000"
```

实测 1000 根（2024-02-12 起），配合 `endTime` 可继续回溯。

---

## 4.5 基金画像与基准（M4 实测）

从场外基金列表按类型抽样 30 只，逐只抓画像页：

| 指标 | 结果 |
|---|---|
| 画像解析成功 | 30 / 30 |
| 基准缺失 | 0 |
| 基准权重合计 = 100% | 30 / 30 |
| `fund_class` 与基准权益占比矛盾 | **0** |

「矛盾」的判定：`BOND`/`MONEY` 类若基准权益 > 20%，或 `EQUITY` 类若基准权益 < 50%。

**两个必须知道的坑**

1. **画像页少一个 `</td>`**：`<td>166002（前端）<th>基金类型</th>` —— 用
   `<th>…</th><td>…</td>` 直接匹配会吞掉后一个字段，必须先补闭合标签。
2. **514 是防爬状态码**（非标准 HTTP）：
   - 单连接顺序请求，**4 req/s 通过，5 req/s 触发**
   - 触发后同连接后续请求持续 514
   - 令牌桶突发容量必须为 1（等间隔），否则前 10 个请求连发即被封

## 5. 数据现状

来自旧项目数据库（只读，`mode=ro&immutable=1`）：

```bash
sqlite3 "file:data/database/assetpilot.db?mode=ro&immutable=1" \
  "SELECT COUNT(*) FROM asset_varieties;"
```

| 表 | 行数 |
|---|---|
| `asset_varieties` | 45,970 |
| `asset_holdings` | 5 |
| `cash_flows` | 45 |
| `cash_flows` 余额 | CNY 10,900 + USD 476.64 |

---

## 6. 覆盖率抽样

从上述品种库随机抽样，逐个调接口验证：

| 类别 | 样本 | 命中 |
|---|---|---|
| A股股票 | 15 | 东财 15/15 |
| 场内基金 | 15 | 东财 14/15 |
| 场外基金 | 15 | 天天基金 15/15 |
| 美股 | 24 | 东财 21/24 + 腾讯 3 = 24/24 |
| 加密 | 15 | Binance 11/15；加 OKX 后 14/15 |

未命中的：已清盘品种（如 581002）、加密 USDG / MEW / MOODENG / POPCAT。

---

← 上一篇：[开源与版本](10-open-source.md) ｜ 下一篇：[日志与可观测性](12-observability.md) →
