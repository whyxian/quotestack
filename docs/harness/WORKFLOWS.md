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

## 4. 改设计决策

```
1. 先改 docs/design/ 对应文件（记录新决策与理由）
2. 再改代码
3. 提交信息里说明"设计变更"
```

设计文档是决策记录。**不要悄悄改代码绕过它**——那会让下一个人以为文档还可信。

---

## 5. 完成一个里程碑

```
1. 勾 docs/ROADMAP.md
2. 更新受影响设计文档顶部的「实现状态」
3. uv run python scripts/sync_docs.py        # 索引状态与事实块会同步
4. 更新 docs/harness/ARCHITECTURE.md 的文件规模与调用路径（若结构变了）
```

第 3 步是机械的：索引状态列从各篇自己的标题读，所以**先改标题再跑脚本**。

---

## 改动牵动哪些文档

| 改了 | 必须同步 | 谁来保证 |
|---|---|---|
| 能力声明 / 数据源 | `docs/design/03-sources.md` | `test_docs.py` |
| HTTP 接口 | `docs/api/openapi.yaml` | `test_server.py` |
| 方法/路由/错误数量 | `docs/design/README.md` 事实块 | `sync_docs.py --check` |
| 各篇实现状态 | 索引状态列 | `sync_docs.py --check` |
| 模块结构 | `docs/harness/ARCHITECTURE.md` | 人工 |
| 测试数量 / 覆盖率 | `docs/design/14-testing.md` | 人工 |
| 完成里程碑 | `docs/ROADMAP.md` | 人工 |

前三行有测试兜底，后三行只能靠自觉——**所以后三行要写进提交前自查**。
