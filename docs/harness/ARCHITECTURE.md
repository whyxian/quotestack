# 架构（as-built）

> 反映 **M3.5 完成时**的真实代码，不是设计意图。
> 设计理由见 `docs/design/`；本文件只描述"代码现在长什么样"。
> 逐文件、逐函数的中文说明见 [CODE_MAP_ZH](CODE_MAP_ZH.md)。
> 更新于 2026-11-08。

---

## 1. 目录结构

```
src/quotestack/
├── __init__.py            对外导出 21 个符号
├── client/                ★ 主入口（5 个 mixin）
├── cli.py                 命令行 4 个命令
├── sync.py                同步包装
├── errors.py              14 个错误类
├── logging.py             结构化事件
├── resilience.py          冷却 + 令牌桶
├── funds.py               基金类型归一化
├── models/                数据模型
│   ├── enums.py           7 个枚举
│   ├── instrument.py      Instrument
│   ├── quote.py           Quote
│   ├── bar.py             Bar
│   ├── nav.py             NavPoint
│   ├── summary.py         InstrumentSummary
│   ├── result.py          QuoteResult
│   └── fx.py              FxRate
├── identity/              代码 → 各源标识
│   ├── rules.py           纯规则
│   └── resolver.py        组装 Instrument
├── cache/
│   ├── base.py            三态、键、TTL 表
│   └── memory.py          进程内实现
└── sources/               数据源适配器
    ├── base.py            SourceMeta / Quoter / Historian
    ├── routing.py         路由表
    ├── eastmoney.py       行情 + 列表（642 行，已超标）
    ├── tencent.py         实时兜底
    ├── tiantian.py        净值 + 基金列表
    ├── binance.py         交易对列表
    └── fx.py              汇率
```

---

## 2. 依赖方向

```
models ← errors ← identity ← cache
                    ↑
                 sources ← routing
                    ↑
                 client ← sync / cli
                    ↑
                  funds
```

**规则**：

| 禁止 | 原因 |
|---|---|
| `sources` import `client` | 源不该知道编排逻辑 |
| `models` import 任何上层 | 模型必须是最底层 |
| `identity` 发起网络请求 | 解析必须是纯函数 |

`funds.py` 只依赖 `models.enums`，被 `sources/tiantian.py` 使用。

---

## 3. 一次 `quote()` 的完整路径

```
client.quote("600519")
  │
  ├─ resolve()                        identity/resolver.py
  │    └─ Instrument(aliases={eastmoney: "1.600519", ...})
  │
  ├─ _require(QUOTE)                  能力检查，缺则 Unsupported
  │
  ├─ _cached()                        cache/base.py
  │    ├─ classify() → FRESH?  → 直接返回
  │    └─ STALE / EXPIRED → 继续
  │
  ├─ _single_flight()                 同 key 并发只回源一次
  │
  └─ _fetch_and_store()
       ├─ _candidates()               sources/routing.py 决定顺序
       │    └─ ["eastmoney", "tencent"]
       ├─ cooldown.is_cooling()       冷却中的源跳过
       ├─ bucket.acquire()            令牌桶限流
       ├─ source.quote([inst])        实际 HTTP
       │    └─ eastmoney._to_quote()  价格 ÷10^f1，涨跌幅 ÷100
       ├─ 成功 → cache.set() → 返回
       └─ 失败 → 下一个源
            └─ 全失败 → _fallback()
                 ├─ 有 stale 值 → 标 stale=true 返回
                 └─ 否则 → Unavailable(attempts=[...])
```

---

## 4. 一次 `iter_instruments()` 的路径

```
client.iter_instruments(STOCK, CN)
  │
  ├─ _LISTING_PLAN[(STOCK, CN, None)] → ("eastmoney",)
  │
  └─ source.list_instruments()
       ├─ 东财：_list_page() 翻页，用 data.total 判断结束
       │    └─ _to_summary() 解析板块、上市日、行业
       ├─ 天天：一次拿 3.1MB，本地切片
       └─ Binance：一次拿 17MB，过滤 TRADING + USDT
```

**分页不能用"这页不满"判断结束**——东财 `pz` 最大 100，传 500 会被静默截断。

---

## 5. 四个实现层面的坑

| 坑 | 位置 | 后果 |
|---|---|---|
| 东财价格是小数字放大 | `eastmoney._to_quote` | 用错小数位，ETF 差 10 倍 |
| 东财涨跌幅单位固定 0.01% | `_PCT_DIVISOR` | 按 `10^f1` 缩放，美股错 10 倍 |
| 东财 K 线是 O-C-H-L | `_to_bar` | high/low 互换，不报错 |
| 腾讯返回 GBK | `tencent._parse` | 中文乱码 |

**共同点：全是"不报错但数据错"，靠测试和断言很难发现。**

---

## 6. 缓存键

```
v1|quote|CN:STOCK:600519
v1|history|CN:STOCK:600519|1d|qfq
v1|nav|CN:FUND:166002
```

格式：`v1|capability|instrument_id[|interval|adjust]`

版本前缀 `v1` 用于整体失效——改了序列化格式时递增即可。

---

## 7. 文件规模现状

| 文件 | 行数 | 状态 |
|---|---|---|
| `sources/tiantian.py` | 245 | ✅ 最大单文件 |
| `cli.py` | 242 | ✅ |
| `sources/tencent.py` | 214 | ✅ |
| `client/core.py` | 186 | ✅ |
| `cache/base.py` | 186 | ✅ |
| 其余 36 个文件 | < 190 | ✅ |

**总规模**：4,311 行 / 41 文件。**全部低于 400 行红线。**

---

## 8. 测试布局

```
tests/
├── test_identity.py      解析规则
├── test_eastmoney.py     行情解析 + 缩放
├── test_tencent.py       GBK + 双布局
├── test_tiantian.py      JS 变量解析
├── test_fx.py            汇率交叉
├── test_listing.py       三个源的列表
├── test_funds.py         基金分类
├── test_routing.py       路由与批量
├── test_resilience.py    冷却与限流
├── test_client.py        缓存三态与降级
├── test_cli_sync.py      CLI 与同步包装
└── test_smoke.py         真实请求（默认跳过）
```

**104 个测试**，全离线（respx 拦截 HTTP），3 个 live 用例需 `QUOTESTACK_LIVE=1`。

---

## 9. 快速定位

| 我要改… | 去这里 |
|---|---|
| 新增数据源 | `sources/` + `sources/routing.py` 登记 |
| 改代码 → secid 规则 | `identity/rules.py` |
| 改 TTL / max_stale | `cache/base.py` 的 `_DEFAULT_TTL` / `_DEFAULT_MAX_STALE` |
| 改错误语义 | `errors.py` |
| 改降级顺序 | `sources/routing.py` 的 `_ROUTES` |
| 改基金分类 | `funds.py` 的 `_RULES` |
| 加日志事件 | `logging.py` 的 `EVENTS`（先注册再发） |
| 改 CLI 输出 | `cli.py` 的 `_emit_*` |
