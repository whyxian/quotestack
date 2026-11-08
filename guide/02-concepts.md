# 02 核心概念

看懂五个词，后面的文档就都能读了。

---

## 1. 标的用三元组定位

一个标的由 **代码 + 资产类别 + 市场** 确定，不是只靠代码。

```python
await client.quote("000001", AssetClass.STOCK, Market.CN)  # 平安银行
await client.quote("000001", AssetClass.FUND,  Market.CN)  # 华夏成长混合
```

**同一个代码，完全不同的东西。** 所以每个方法都要这三个参数。

`market` 和 `asset_class` 有默认值（`CN` / `STOCK`），只查 A股时可以不写：

```python
await client.quote("600519")            # 等价于 quote("600519", STOCK, CN)
await client.nav("022430")              # nav 默认是 FUND + CN
```

### `resolve()` 拿到的是什么

```python
instrument = client.resolve("600519", AssetClass.STOCK, Market.CN)

instrument.id            # 'CN:STOCK:600519'
instrument.aliases       # {'eastmoney': '1.600519', 'tencent': 'sh600519'}
instrument.capabilities  # {QUOTE, HISTORY}
```

`aliases` 是各数据源自己的标识——**你不需要用它**，库内部用。之所以暴露出来，
是方便排查"这个标的到底被解析成了什么"。

---

## 2. Capability：这个标的能查什么

不是所有标的都支持所有操作：

| 标的 | 能查什么 |
|---|---|
| `CN:STOCK:600519` | 报价、K 线 |
| `CN:FUND:510010`（场内 ETF） | 报价、K 线、净值、画像、持仓、基准、估值 |
| `CN:FUND:022430`（场外联接） | 净值、画像、持仓、基准、估值（**没有报价**） |
| `CN:CRYPTO:BTCUSDT` | 报价、K 线 |

查了不支持的会抛 `UnsupportedError`，**告诉你它能查什么**：

```python
try:
    await client.quote("022430", AssetClass.FUND, Market.CN)
except UnsupportedError as exc:
    print(exc.context["available"])   # ['BENCHMARK', 'ESTIMATE', 'HOLDINGS', 'NAV', 'PROFILE']
```

> 场外基金没有盘中价格，只有每日净值。这是它的定义，不是我们的缺失。

---

## 3. 价格是字符串，不是数字

```python
quote.price      # '1453.00'   ← str
quote.change_pct # 0.07        ← float
```

**金额用 `str`**，因为 `0.1 + 0.2 != 0.3`，钱不能有浮点误差。需要计算时自己转：

```python
from decimal import Decimal

value = Decimal(quote.price) * 100
```

**涨跌幅用 `float`**——它是比率，不是金额，误差无所谓。

---

## 4. 时间是两种东西

| 字段 | 类型 | 含义 |
|---|---|---|
| `quote.ts` | 带时区的时刻 | 「这个价格是什么时候的」 |
| `bar.date` | 日期，无时区 | 「这个交易日」 |
| `bar.time` | `'14:55'` 或 `None` | 分钟线的时刻；日线为 `None` |

**不要混用。** 交易日是本地概念，时刻是绝对时间。

---

## 5. 缓存与降级：不用你操心

默认行为：

```
先查缓存
  ├─ 新鲜（比如报价 30 秒内）→ 直接返回，不发请求
  ├─ 过期但在容忍范围内     → 尝试回源，失败就用旧值（quote.stale = True）
  └─ 太旧了                 → 必须回源，失败就报错
```

想强制拿最新数据，用 `max_age=0`：

```python
quote = await client.quote("600519", max_age=0)
```

想接受更旧的数据，传秒数：

```python
quote = await client.quote("600519", max_age=300)   # 5 分钟内的都行
```

**判断数据新旧，看 `stale`：**

```python
if quote.stale:
    print("这是缓存值，上游暂时不可用")
```

---

## 6. 错误都是同一种父类

```python
from quotestack.errors import MarketDataError

try:
    await client.quote("999999")
except MarketDataError as exc:
    print(exc.code)     # 'NOT_FOUND'
    print(exc.message)  # 人话
    print(exc.context)  # 结构化细节
```

`code` 是稳定字符串，适合 `switch`；`message` 可能变，别拿来做判断。

具体有哪些错误、怎么处理，看 [08 错误处理](08-errors.md)。

---

## 一句话回顾

| 概念 | 记住这一句 |
|---|---|
| 三元组 | 代码 + 资产类别 + 市场，缺一不可 |
| Capability | 不支持的会明确报错，并告诉你支持什么 |
| 价格 | 是字符串，要算就 `Decimal` |
| 时间 | `date` 是交易日，`ts` 是时刻 |
| 缓存 | 自动的；看 `stale` 判断新旧 |
