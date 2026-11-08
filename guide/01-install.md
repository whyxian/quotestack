# 01 安装

## 环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| Python | 3.11+ | 用到 `StrEnum` 和 `Self` |
| uv | ≥ 0.5 | 会自己装 Python，不用预装 |
| 网络 | 能访问东财、天天基金 | 加密还要能访问 Binance |

---

## 安装方式

### 从源码（当前唯一方式）

```bash
git clone https://github.com/whyxian/quotestack.git && cd quotestack
uv sync --extra dev
```

`uv sync` 会建一个 `.venv` 并装好依赖。之后用 `uv run` 或直接 `.venv/bin/python`。

### 需要 HTTP 服务时

```bash
uv sync --extra dev --extra server
```

> ⚠️ **两个 extra 要一起写。**
> `uv sync --extra server` 会让环境**严格匹配**，把 pytest、ruff 一起卸掉。
> 这是 `uv sync` 的语义，不是 bug。

### 发布之后（M8 起）

```bash
pip install quotestack          # 只当库用
pip install "quotestack[server]"  # 要 HTTP 服务
```

---

## 验证装好了

```bash
uv run quotestack quote 600519
```

```
CN:STOCK:600519
-----------------------------
  price   1453.00 CNY   +0.07%
  change  1.00
  source  eastmoney
  time    2026-11-06 16:11:39
```

再到基金估值的冒烟：

```bash
uv run quotestack estimate 022430
```

```
estimate  -1.66%
-----------------------------
  basis     index
  coverage  94.4%
  reason    指数型：跟踪「中证A500指数」实时涨跌 -1.76% × 权益仓位 94.4% = -1.66%
```

两条都出数，说明行情源和基金源都通了。

---

## 网络连不上怎么办

三类源的可达性不一样：

| 源 | 国内直连 | 需要代理 |
|---|---|---|
| 东财（A股/美股/汇率） | ✅ | — |
| 天天基金（场外基金） | ✅ | — |
| 腾讯（实时兜底） | ✅ | — |
| **Binance（加密）** | ⚠️ 时通时断 | 建议 |

**加密列表用 `data-api.binance.vision`**——这是 Binance 的公开数据域名，国内比
主站稳定，但也可能被墙。需要时给客户端配代理：

```python
from quotestack import MarketData

client = MarketData(proxy="http://127.0.0.1:7890")
```

或者用环境变量（服务模式下）：

```bash
export QUOTESTACK_PROXY_URL=http://127.0.0.1:7890
```

---

## 目录里都有什么

```
quotestack/
├── src/quotestack/     库本体
├── tests/              测试（默认全离线）
├── examples/           三个可运行示例
├── guide/              你在看的这份
└── docs/               仓库内部的工程文档（与本指南无关）
```

第一次用建议先跑 `examples/`：

```bash
uv run python examples/01_quote.py
uv run python examples/02_fund_estimate.py
uv run python examples/03_refresh_universe.py
```
