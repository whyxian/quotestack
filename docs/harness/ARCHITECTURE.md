# 架构（as-built）

> 反映 **M1 完成时**的真实代码，不是设计意图。
> 设计理由见 `docs/design/`；本文件只描述"代码现在长什么样"。
> 逐文件、逐函数的中文说明见 [CODE_MAP_ZH](CODE_MAP_ZH.md)。
> 更新于 2026-11-08。

---

## 1. 目录结构

```
src/quotestack/
├── __init__.py            公共 API 导出（21 个符号）
├── client.py              MarketData：编排 resolve / quote / history
├── cli.py                 命令行（argparse）
├── errors.py              错误层级
├── models/                Instrument / Quote / Bar / 枚举
├── identity/              规则解析（code → 各源标识）
├── sources/               数据源适配器
│   ├── base.py            SourceMeta + Quoter/Historian Protocol
│   └── eastmoney.py       东财实现（报价 + K 线）
└── cache/                 缓存
    ├── base.py            CacheEntry / 键构造 / 新鲜度判定
    └── memory.py          MemoryCache
```

| 模块 | 行数 |
|---|---|
| `sources/eastmoney.py` | 359 |
| `client.py` | 197 |
| `cli.py` | 172 |
| `identity/resolver.py` | 165 |
| `errors.py` | 139 |
| `cache/base.py` | 113 |
| `sources/base.py` | 105 |
| `models/enums.py` | 100 |
| 其余 | < 100 各自 |

---

## 2. 依赖方向

```
models  ←  errors  ←  identity  ←  sources  ←  client  ←  cli
                        ↑
                      cache ──→ models
```

实际 import 关系：

| 模块 | 依赖 |
|---|---|
| `models` | 无（只有标准库） |
| `errors` | 无 |
| `identity` | `models`, `errors` |
| `cache` | `models` |
| `sources` | `models`, `errors` |
| `client` | `identity`, `sources`, `cache`, `errors`, `models` |
| `cli` | `client`, `models`, `errors` |

**没有反向依赖**：`sources` 不 import `client`，`models` 不 import 任何实现。

---

## 3. 一次 `quote()` 的完整路径

```
client.quote("600519")
  │
  ├─ 1. identity.resolve()
  │      rules.cn_exchange → "sh"
  │      aliases = {eastmoney: "1.600519", tencent: "sh600519"}
  │      返回 Instrument(capabilities={QUOTE, HISTORY})
  │
  ├─ 2. 能力检查
  │      无 QUOTE 能力 → UnsupportedError
  │
  ├─ 3. 查缓存  v1|quote|CN:STOCK:600519
  │      命中且未过期 → 直接返回
  │
  ├─ 4. EastMoneySource.quote([instrument])
  │      GET push2.eastmoney.com/api/qt/ulist.np/get
  │      → data.diff[0]
  │      → f1=2（小数位） f2=145300 → "1453.00"
  │
  ├─ 5. 写缓存（记 fetched_at + source）
  │
  └─ 6. 返回 Quote
```

失败路径：

```
上游报错 → 缓存里有旧值 → 返回旧值 + stale=True
                        → 没有旧值 → 原样抛出
```

---

## 4. 实现要点（都是实测踩出来的）

### 东财价格是放大整数

`f1` 是小数位，真实值 = `f2 / 10 ** f1`：

| 标的 | f1 | f2 | 还原 |
|---|---|---|---|
| 600519 | 2 | 145300 | `1453.00` |
| 510010 | 3 | 1760 | `1.760` |

**不能统一按 ÷100**，ETF 会差 10 倍。

### 东财 K 线是 O-C-H-L 顺序

```
2026-11-05,1446.70,1452.00,1466.00,1430.00,46712,...
           open     close    high     low     volume
```

不是常见的 OHLC。字段顺序写错会导致 high/low 互换，而**不会报错**——只是数据悄悄错了。

### 分钟线用 `date` + `time` 两个字段

`Bar.date` 是交易日（无时区），`Bar.time` 是 `HH:MM`（仅分钟线有）。
合成一个 datetime 会引入时区歧义。

### 缓存键

```
v1|quote|CN:STOCK:600519
v1|history|CN:STOCK:600519|1d|qfq
```

`v1` 是缓存版本，改解析逻辑时递增即可整体失效。

---

## 5. 测试布局

| 文件 | 覆盖 |
|---|---|
| `tests/test_identity.py` | 9 种合法前缀 + 6 种非法输入 |
| `tests/test_eastmoney.py` | 报价解析、小数位、空响应、结构变更；K 线 O-C-H-L、分钟时间、空列表 |
| `tests/test_smoke.py` | 真实请求冒烟（默认跳过） |

运行：

```bash
.venv/bin/pytest -q                              # 28 passed, 3 skipped
QUOTESTACK_LIVE=1 .venv/bin/pytest tests/test_smoke.py -q   # 3 passed
```

---

## 6. 当前限制

| 限制 | 影响 | 计划 |
|---|---|---|
| 只有东财一个源 | 东财挂了就没有数据 | M3 加腾讯兜底 |
| 只有内存缓存 | 进程重启即丢失 | M2 加 SQLite |
| 无单飞、无限流 | 并发请求会放大上游压力 | M2 |
| 缓存未做 `max_stale` | 理论上可能返回很旧的数据 | M2 |
| 无 HTTP 服务 | Java 后端无法调用 | M6 |
| 无基金能力 | `profile` / `holdings` / `estimate` 未实现 | M4 / M5 |
| 美股 K 线不支持 | 缺交易所后缀 | M3 |

---

## 7. 关键文件速查

| 想改什么 | 去哪 |
|---|---|
| 代码 → 各源标识 | `identity/rules.py` |
| 新增数据源 | `sources/`，实现 `Quoter` / `Historian` |
| 错误语义 | `errors.py` |
| 缓存 TTL | `cache/base.py` 的 `_DEFAULT_TTL` |
| CLI 输出格式 | `cli.py` 的 `_emit_*` |
| 公共 API | `__init__.py` 的 `__all__` |
