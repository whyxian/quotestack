# 约束

违反任意一条，代码不可合并。

---

## 1. 五条红线

| # | 红线 | 反例 | 为什么 |
|---|---|---|---|
| 1 | 价格、金额、成交量、净值一律 `str` | `price: float` | `0.1 + 0.2 != 0.3`，钱不能有浮点误差 |
| 2 | 库不得配置 logging handler | `logging.basicConfig()` 出现在 `src/` | 会污染调用方的日志配置 |
| 3 | 源差异只能关在 `sources/` 内 | `client.py` 里判断"东财返回的是 f2 字段" | 上层只见统一模型 |
| 4 | 缓存不得无限期返回旧值 | 忽略 `max_stale` 直接返回 | 一个月前的价格冒充现价 |
| 5 | 一个字段只能有一种类型 | `price: float \| str` | 调用方无法写分支 |

第 3 条的机械化版本：`tests/test_architecture.py` 用 AST 检查 import 方向，
`sources/` import `client` 会让测试失败。

---

## 2. 编码风格

工具链：**ruff（lint + format）+ mypy strict**，pre-commit 与 CI 双卡。

### 硬指标

| 项 | 上限 |
|---|---|
| 函数长度 | 40 行 |
| 参数个数 | 5 个 |
| 嵌套层数 | 3 层 |
| 文件行数 | **不设上限** |

文件行数不设上限，因为盯着它会让代码被切成"每块都够小、但没人能顺着读完"的碎片。
拆分只看一条：**能不能用一句话说清这个文件是干什么的**。

### 注释

- docstring 与注释**全英文**（社区读者）
- Google Style：`Args:` / `Returns:` / `Raises:`
- 只解释「为什么」，不复述「是什么」

```python
# 好：解释了反直觉的原因
# bool is a subclass of int, so `port = true` would otherwise become 1.
if isinstance(value, bool) or not isinstance(value, int):

# 坏：把代码翻译成英文
# increment the counter
counter += 1
```

### 禁止

| 禁止 | 替代 |
|---|---|
| `print` | `logging` 事件（库内）或 CLI 输出 |
| 裸 `except:` | 捕获具体异常 |
| 可变默认参数 | `None` + 内部构造 |
| async 里的阻塞调用 | `await asyncio.to_thread(...)` |
| 裸 `Any` | 具体类型或 `object` + 收窄 |
| 断言业务逻辑 | 抛 `MarketDataError` 子类 |

---

## 3. 测试约束

| 要求 | 说明 |
|---|---|
| 新功能必须带错误路径测试 | 只测 happy path 的分支覆盖率会停在 70% 左右 |
| 不许为了让测试通过放宽断言 | 结构变了就是变了 |
| 不许改坏样本让它通过 | 那等于把警报器拆了 |
| 覆盖率门槛 | 行覆盖 ≥ 85%（当前 91%） |

---

## 4. 提交约束

Conventional Commits，scope 用模块名：

```
feat(tiantian): add quarterly holdings
fix(cache): avoid duplicate fetch when a key expires
docs(api): document the null-versus-zero rule
```

正文写**为什么**。`git diff` 已经说明了改哪些文件。

**提交前钩子会跑 ruff + format + mypy**，不用 `--no-verify` 绕过。
