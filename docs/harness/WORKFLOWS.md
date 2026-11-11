# 工作流

每个流程的**具体步骤**，以及走完之后哪些文档会变。

---

## 1. 加一个数据源

```
1. sources/ 新建文件，实现需要的方法（quote / history / nav / list_instruments …）
2. 声明 meta：name / capabilities / markets / timeout
      ↑ 实现了什么就声明什么，test_docs.py 会检查两者一致
3. sources/routing.py 的 _ROUTES 登记优先级
4. 录真实样本 → tests/fixtures/<源>/
5. 录一个坏样本 → tests/fixtures/bad/，断言 SchemaChangedError
6. 补错误路径测试：别名缺失 / 404 / 结构变更 / 空结果
7. 更新 docs/design/03-sources.md 的能力表（有测试校验）
```

样本命名与录制方式见 [`tests/fixtures/README.md`](../../tests/fixtures/README.md)。

---

## 2. 修一个解析 bug

```
1. 先补一个能复现的 fixture（从真实响应录，不要手写"大概长这样"）
2. 改解析器
3. uv run pytest tests/test_<源>.py
4. 跑一次真实请求确认线上结构仍匹配
```

**顺序不能反。** 先改代码再补测试，等于用改后的代码定义"正确"。

---

## 3. 改 HTTP 接口

```
1. 改代码（Pydantic 模型、路由、Field 描述）
2. uv run quotestack-server --dump-openapi > docs/api/openapi.yaml
3. 提交
```

**不要手改 YAML。** `tests/test_server.py` 重新生成并比对，忘了生成就红。

要解释「为什么这么设计」，写到 `docs/design/05-api.md`，不是写进 YAML。

---

## 4. 验证上游还能用

GitHub 的 runner 在境外，定时探测只会测出 runner 的位置。所以在**能访问源的网络**上手动跑：

```bash
QUOTESTACK_LIVE=1 uv run pytest tests/test_smoke.py -q -rs
```

判定规则：

| 结果 | 含义 | 该做什么 |
|---|---|---|
| `passed` | 载荷结构没变 | 无事 |
| `skipped` | 连不上源 | 换网络重跑，不是代码问题 |
| `failed` | **载荷结构变了** | 改解析器 + 重录 fixture |

或在 GitHub 上手动触发：Actions → live probe → Run workflow。
勾 `strict` 会让"全部跳过"也算失败，用来确认网络真能连通。

## 5. 改设计决策

```
1. 先改 docs/design/ 对应文件（记录新决策与理由）
2. 再改代码
3. 提交信息里说明"设计变更"
```

设计文档是决策记录。**不要悄悄改代码绕过它**——那会让下一个人以为文档还可信。

---

## 6. 完成一个里程碑

```
1. 勾 docs/ROADMAP.md
2. 更新受影响设计文档顶部的「实现状态」
3. uv run python scripts/sync_docs.py        # 索引状态与事实块会同步
4. 结构变了就改 ARCHITECTURE 的调用路径（文件规模是生成块，不用手改）
```

第 3 步是机械的：索引状态列从各篇自己的标题读，所以**先改标题再跑脚本**。

顺便跑一次 `uv run python scripts/doc_state.py`，看有没有文档因为这次改动而
「描述过的代码变了」——有的话复查一遍，确认后 `--confirm` 掉。

---

## 改动牵动哪些文档

| 改了 | 必须同步 | 谁来保证 |
|---|---|---|
| 能力声明 / 数据源 | `docs/design/03-sources.md` | `test_docs.py` |
| HTTP 接口 | `docs/api/openapi.yaml` | `test_server.py` |
| 事件名 / 字段 | `docs/design/12-observability.md` | `test_observability.py` |
| 错误类层次 | `docs/design/06-errors.md` | `test_docs.py` |
| 缓存 TTL / 是否缓存 | `docs/design/04-cache.md`、`guide/12-reference.md` | `test_docs.py` |
| 示例脚本 | `docs/design/10-open-source.md` | `test_docs.py` |
| CLI 命令 | `docs/design/05-api.md` | `test_docs.py` |
| 方法/路由/错误数量 | `docs/design/README.md` 事实块 | `sync_docs.py --check` |
| 各篇实现状态 | 索引状态列 | `sync_docs.py --check` |
| 模块结构 | `docs/harness/ARCHITECTURE.md` | 人工（`doc_state.py` 报告） |
| 测试数量 / 覆盖率 | `docs/design/14-testing.md` | 人工（`doc_state.py` 报告） |
| 完成里程碑 | `docs/ROADMAP.md` | `sync_docs.py --check`（进度行） |

**上表前九行有测试兜底**。剩下的人工项由 `scripts/doc_state.py` 报告——
它会列出「描述过的代码变了、但没人再确认」的文档，按需复查即可。

### 探测失败之后

跑探测的人就是盯着它的人，所以**不需要给自己开 issue**。按能不能当场修分两种：

| 情况 | 做什么 |
|---|---|
| 能当场修（改解析器 + 重录 fixture） | 直接改，提交信息写清上游变了什么 |
| 暂时修不了（要鉴权、源下线、等对方恢复） | 记进 `CHANGELOG.md` 的「已知限制」，或代码里一行注释说明现状 |

**issue 留给有外部读者的事**——用户报的 bug、别人提的需求。给自己开 issue
只会多一个地方堆积半成品，而那份待办本来就该在 `docs/ROADMAP.md` 里。
