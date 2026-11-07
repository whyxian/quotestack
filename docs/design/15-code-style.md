# 代码规范

> quotestack 设计决议 · 第 15 部分 · v0.8（2026-11-07）
> 返回索引 → [README](README.md)

规矩如果不能自动执行，就等于没有。本文把"工具能强制的"和"需要人判断的"分开。

---

## 1. 三条底线

1. **能被工具抓到的，不靠人记**——ruff + mypy 放在 pre-commit 与 CI，违规无法合入
2. **简洁优先于聪明**——看不懂的代码等于错误代码
3. **一致性优先于个人偏好**——风格问题不争论，按本文执行

---

## 2. 工具链

| 层 | 工具 | 管什么 | 何时跑 |
|---|---|---|---|
| 1 | **ruff**（lint + format） | 风格、导入顺序、常见 bug、async 误用 | pre-commit + CI |
| 2 | **mypy**（strict） | 类型正确性 | pre-commit + CI |
| 3 | 人工审查 | 职责划分、复杂度、命名语义 | PR |

选 ruff 而不选 black + flake8 + isort：一个工具做三件事，一份配置，速度极快。

### 2.1 ruff 配置

```toml
[tool.ruff]
line-length = 100          # 中文注释较多，88 过紧
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = [
  "E",    # pycodestyle errors
  "W",    # pycodestyle warnings
  "F",    # pyflakes
  "I",    # isort
  "N",    # pep8-naming
  "UP",   # pyupgrade
  "B",    # bugbear（可变默认参数等）
  "SIM",  # 可简化写法
  "RET",  # 返回值写法
  "PTH",  # 用 pathlib
  "ASYNC",# async 常见错误
  "RUF",  # ruff 自有规则
  "T20",  # 禁止 print
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101"]       # 测试允许 assert
```

`ASYNC` 这组尤其重要——它能抓出"在 async 函数里调用阻塞 IO"这类最难发现的问题。

### 2.2 mypy 配置

```toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_unreachable = true
warn_no_return = true
```

### 2.3 pre-commit

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0
    hooks:
      - id: mypy
```

---

## 3. 结构硬指标

| 项 | 上限 | 超标意味着 |
|---|---|---|
| 单函数行数 | **40** | 在做两件事 |
| 单文件行数 | **400** | 该类/模块职责太杂 |
| 函数参数个数 | **5** | 应该传 dataclass |
| 嵌套层数 | **3** | 应该用卫语句提前返回 |
| 单个类公共方法 | **12** | 应该拆分 |

### 3.1 分层依赖方向不可逆

```
errors / models  ←  sources  ←  client  ←  server
```

- `sources` 不得 import `client`
- `client` 不得 import `server`
- `models` 不得 import 任何实现层

用 `import-linter` 在 CI 中强制执行：

```toml
[importlinter]
root_packages = ["quotestack"]

[[importlinter.contracts]]
name = "Layered architecture"
type = "layers"
layers = ["quotestack.server", "quotestack.client", "quotestack.sources", "quotestack.models"]
```

---

## 4. 禁止清单

| 禁止 | 原因 | 谁抓 |
|---|---|---|
| `print()` | 库不得写 stdout | ruff `T20` |
| 裸 `except:` | 会吞掉 `KeyboardInterrupt` | ruff `E722` |
| 可变默认参数 `def f(x=[])` | 经典陷阱 | ruff `B006` |
| `assert` 做业务校验 | `-O` 会被剥离 | 审查 |
| async 中调用 `time.sleep` / `requests` | 阻塞整个事件循环 | ruff `ASYNC` |
| 模块级可变全局（缓存单例除外） | 测试串扰 | 审查 |
| `from x import *` | 污染命名空间 | ruff `F403` |
| 裸 `Any`（边界除外） | 类型形同虚设 | mypy |
| 在 `__init__` 中做 I/O | 构造不应有副作用 | 审查 |
| 超过 3 层嵌套 | 可读性急剧下降 | 审查 |

---

## 5. 必须清单

| 必须 | 说明 |
|---|---|
| 公共 API 有完整类型标注与 docstring | 否则 `py.typed` 无意义 |
| 每个公共函数至少一个测试 | 覆盖率 85% 是结果，不是目标 |
| 错误走异常层级 | 不返回错误码 |
| 日志用 `logger.<level>(msg, extra={...})` | 不拼字符串 |
| 私有成员前缀 `_` | 明确边界 |
| 模块显式声明 `__all__` | 控制导出面 |

---

## 6. 注释与 docstring

### 6.1 语言

**全部英文。** 理由：开源项目的代码注释是最容易被国际贡献者审视的部分，中英混杂显得不专业。设计文档可以是中文，但代码面向所有人。

### 6.2 风格

Google Style，与你旧项目保持一致。

```python
async def fetch_history(
    instrument: Instrument,
    interval: Interval = "1d",
    adjust: Adjust = "qfq",
    limit: int = 250,
) -> list[Bar]:
    """Fetch historical bars for an instrument.

    Args:
        instrument: Resolved instrument.
        interval: Bar interval: ``1m``, ``5m``, ``15m``, ``30m``, ``60m``,
            ``1d``, ``1w`` or ``1M``.
        adjust: Price adjustment mode.
        limit: Maximum number of bars to return, counted from the newest bar.

    Returns:
        Bars in ascending date order. An empty list if the source has no data.

    Raises:
        NotFound: The instrument does not exist on any source.
        Unsupported: The instrument has no historical data.
        UpstreamError: All sources failed.
    """
```

### 6.3 注释原则

只解释**为什么**，不解释**是什么**。

```python
# Good: 解释了非显然的取舍
# Binance Vision is reachable from mainland China while api.binance.com is not,
# so we prefer the vision host for all public market data calls.
BINANCE_HOST = "data-api.binance.vision"

# Bad: 复述代码
# Set host to binance vision
BINANCE_HOST = "data-api.binance.vision"
```

---

## 7. 命名

| 对象 | 规则 | 示例 |
|---|---|---|
| 模块 | snake_case，简短 | `eastmoney.py`、`quote_cache.py` |
| 类 | PascalCase | `EastMoneySource`、`Instrument` |
| 函数 | snake_case，动词开头 | `fetch_quotes`、`resolve_instrument` |
| 私有 | 前缀 `_` | `_parse_kline` |
| 常量 | UPPER_SNAKE | `CACHE_VERSION`、`DEFAULT_TIMEOUT` |
| 类型别名 | PascalCase | `InstrumentId = str` |

避免缩写：`qty` → `quantity`，`px` → `price`，`cfg` → `config`。行业通用缩写（`nav`、`fx`、`ohlc`）除外。

---

## 8. 写法偏好

### 8.1 卫语句优先

```python
# Good
def process(instrument: Instrument | None) -> Quote:
    if instrument is None:
        raise InvalidArgument("instrument is required")
    if not instrument.capabilities:
        raise Unsupported(f"{instrument.id} has no capabilities")
    return _fetch(instrument)

# Bad
def process(instrument):
    if instrument is not None:
        if instrument.capabilities:
            return _fetch(instrument)
        else:
            raise Unsupported(...)
    else:
        raise InvalidArgument(...)
```

### 8.2 显式优于隐式

```python
# Good
async def quote(self, code: str, asset_class: AssetClass, market: Market) -> Quote: ...

# Bad
async def quote(self, *args, **kwargs) -> Quote: ...
```

### 8.3 早返回、少可变

- 函数内尽量不重新赋值参数
- 优先用不可变结构（`dataclass(frozen=True)`、tuple）
- 集合推导优先于 `append` 循环

---

## 9. 提交规范

Conventional Commits：

```
<type>(<scope>): <subject>

feat(eastmoney): add weekly and monthly kline
fix(cache): avoid duplicate fetch when key expires
docs(design): clarify cache key format
refactor(sources): extract shared kline parser
test(eastmoney): add schema-changed fixture
chore(ci): pin ruff version
```

| type | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修 bug |
| `docs` | 文档 |
| `refactor` | 重构（不改行为） |
| `test` | 测试 |
| `chore` | 构建/工具 |

**scope 用模块名**，不用人名、不用文件名带后缀。

---

## 10. 审查清单（PR 必过）

- [ ] ruff / mypy 全绿
- [ ] 新增公共 API 有类型标注与 docstring
- [ ] 新增函数有测试
- [ ] 没有新增 `print` / 裸 `except` / 可变默认参数
- [ ] 分层依赖未被破坏
- [ ] 错误使用既有层级，未新增未分类异常
- [ ] 日志为结构化 `extra`，非字符串拼接
- [ ] 函数长度、嵌套层数未超限

---

← 上一篇：[测试策略](14-testing.md) ｜ 下一篇：[术语表](16-glossary.md) →
