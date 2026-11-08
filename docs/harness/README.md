# AI 上下文入口

> 这个目录服务于**一个目标**：让 AI 在改这个仓库之前，拿到足够准确的上下文
> 和约束，直接写出符合项目的代码，而不是先猜、再返工。

---

## 按顺序读

| 顺序 | 文件 | 读完你应该知道 |
|---|---|---|
| 1 | [CONSTRAINTS](CONSTRAINTS.md) | 什么绝对不能做，代码长什么样才算合格 |
| 2 | [ARCHITECTURE](ARCHITECTURE.md) | 代码放在哪、谁能 import 谁、一次调用经过哪些环节 |
| 3 | [PITFALLS](PITFALLS.md) | 这个领域里哪些"看起来对但会错"的地方 |
| 4 | [WORKFLOWS](WORKFLOWS.md) | 加源 / 修 bug / 改接口的具体步骤与文档义务 |
| 5 | [BOUNDARY](BOUNDARY.md) | 哪些操作必须先问人 |

**时间紧就只读 1 和 3。** 那两份决定了大部分返工。

---

## 和 `docs/design/` 的关系

| | `docs/harness/` | `docs/design/` |
|---|---|---|
| 写给谁 | **AI** | **人** |
| 回答 | 怎么写 | 为什么这么写 |
| 形态 | 规则、清单、路径、反例 | 决策记录、取舍分析、实测数据 |
| 变化 | 跟代码一起长 | 决策变更时才改 |

**不要直接跳进 `design/` 找具体章节。** 需要设计背景时，从
[design/README](../design/README.md) 的索引进入——那份索引按主题组织，
能一次看全 17 篇的定位。

`design/` 里的文档是当时的判断，可能已被实现修正；`harness/` 描述的是**现在**。

---

## 缺什么就补什么

`harness/` 不是一次性写好的。发现下面任一情况，**直接把内容补进对应文件**，
不要只在对话里说：

- 踩到一个新的源怪癖 → 补 [PITFALLS](PITFALLS.md)
- 发现自己违反了一条没写下来的规矩 → 补 [CONSTRAINTS](CONSTRAINTS.md)
- 走了三步才搞明白的流程 → 补 [WORKFLOWS](WORKFLOWS.md)
- 有一次操作越界被叫停 → 补 [BOUNDARY](BOUNDARY.md)

**写给人看的中文代码导读在 [docs/CODE_MAP_ZH.md](../CODE_MAP_ZH.md)**，不在这个目录。
