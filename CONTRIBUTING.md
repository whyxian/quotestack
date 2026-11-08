# 参与开发

面向**改这个仓库的人**。想知道项目为什么这么设计，看 [`docs/design/`](docs/design/README.md)；
想知道代码现在长什么样，看 [`docs/harness/`](docs/harness/ARCHITECTURE.md)。

---

## 1. 环境准备

需要 uv（≥ 0.5）。它会自己装 Python，不需要事先准备。

```bash
git clone <repo> && cd quotestack
uv sync --extra dev --extra server
```

**两个 extra 都要**：

| extra | 装什么 | 不装会怎样 |
|---|---|---|
| `dev` | pytest、ruff、mypy、respx | 测试和检查跑不了 |
| `server` | fastapi、uvicorn、prometheus-client | `quotestack-server` 起不来 |

> `uv sync` 会让环境**严格匹配** extras。只写 `--extra server` 会把 pytest 卸掉。

---

## 2. 开发循环

```bash
uv run pytest -q                                    # 测试，全离线
uv run pytest -q --cov=quotestack                   # 带覆盖率，门槛 85%
uv run ruff check . && uv run ruff format .         # 风格
uv run mypy src                                     # 类型
```

**提交前钩子已配好**，`git commit` 会自动跑 ruff + format + mypy：

```bash
uv run pre-commit install   # 新克隆的仓库需要执行一次
```

钩子用的是**本仓库 venv 里的工具**，不是另外下载的版本——避免两个 ruff 对同一份代码
给出不同结论。

---

## 3. 结构速览

```
src/quotestack/
├── client/       MarketData：唯一公开入口 + FetchPolicy（取数机制）
├── sources/      五个数据源，各自的载荷怪癖关在这里
├── models/       纯数据，不碰 IO
├── identity/     代码 → 各源标识，纯规则
├── cache/        三态缓存
├── server/       HTTP 层，只有薄薄一层转换
└── *.py          各一个关注点：funds / benchmark / indexes / estimate / resilience / logging
```

**依赖只能向下**，`tests/test_architecture.py` 会用 AST 校验。想在 `sources/` 里
import `client`，测试会直接失败。

---

## 4. 加一个数据源

1. 在 `sources/` 新建文件，实现需要的方法（`quote` / `history` / `nav` / `list_instruments` …）
2. 声明 `meta`：`name`、`capabilities`、`markets`、`timeout`

   > **实现了什么就要声明什么。** `tests/test_docs.py` 会检查
   > 「有没有 `list_instruments`」与「有没有声明 `LIST`」是否一致。

3. 在 `sources/routing.py` 的 `_ROUTES` 登记优先级
4. **录真实样本**到 `tests/fixtures/<源>/`，写解析测试
5. **再录一个坏样本**到 `tests/fixtures/bad/`，断言解析器抛 `SchemaChangedError`
6. 更新 [`docs/design/03-sources.md`](docs/design/03-sources.md) 的能力表

样本录制与命名的约定见 [`tests/fixtures/README.md`](tests/fixtures/README.md)。

---

## 5. 改接口

顺序不能反：

```bash
# 1. 改代码（Pydantic 模型、路由、字段描述）
# 2. 重新生成契约
uv run quotestack-server --dump-openapi > docs/api/openapi.yaml
# 3. 提交
```

**不要手改 `openapi.yaml`**——它是生成物。`tests/test_server.py` 会重新生成并比对，
忘了重新生成测试就红。

想解释「为什么这么设计」，写到 [`docs/design/05-api.md`](docs/design/05-api.md)，
不是写进 YAML。

---

## 6. 测试约定

| 层次 | 位置 | 说明 |
|---|---|---|
| 单元 | `tests/test_<模块>.py` | 纯函数，无网络 |
| 适配器 | `tests/test_<源>.py` | respx 拦截，读 fixture |
| 端到端 | `tests/test_client_edges.py` | 假源注入，走完整链路 |
| HTTP | `tests/test_server.py` | ASGI 进程内，不开端口 |
| 真实请求 | `tests/test_smoke.py` | 默认跳过，`QUOTESTACK_LIVE=1` 才跑 |

**写测试时优先补"另一侧分支"**：错误路径、缺字段、空结果。
覆盖率指标不是目的——为了数字写的测试没有价值。

### 两个不许做

- ❌ **为了让测试通过而放宽断言**。结构变了就是变了
- ❌ **改坏样本让它通过**。那等于把警报器拆了

---

## 7. 提交信息

[Conventional Commits](https://www.conventionalcommits.org/)，scope 用模块名：

```
feat(tiantian): add quarterly holdings
fix(cache): avoid duplicate fetch when a key expires
docs(api): document the null-versus-zero rule
test(estate): cover the missing-alias branch
```

正文写**为什么**，不写"改了哪些文件"——`git diff` 已经说明后者。

---

## 8. 改动会牵动哪些文档

这个仓库的文档和代码有**强制同步关系**，改代码时顺手看一下：

| 改了 | 必须同步 |
|---|---|
| 能力声明 / 数据源 | `docs/design/03-sources.md`（有测试校验） |
| HTTP 接口 | 重新生成 `docs/api/openapi.yaml`（有测试校验） |
| 模块结构 | `docs/harness/ARCHITECTURE.md` + `CODE_MAP_ZH.md` |
| 测试数量 / 覆盖率 | `docs/design/14-testing.md` |
| 完成里程碑 | `docs/ROADMAP.md` + 相关篇的「实现状态」 |

设计文档是决策记录。**实现里发现设计有问题，先改文档再改代码**，并在提交信息里
说明这是一次设计变更。

---

## 9. 本地跑服务

```bash
uv run quotestack-server                      # 127.0.0.1:8000
uv run quotestack-server --port 9000
uv run quotestack-server --dump-openapi       # 只打印契约
```

```bash
curl 'http://127.0.0.1:8000/v1/quote?code=600519'
curl 'http://127.0.0.1:8000/v1/estimate?code=022430'
curl 'http://127.0.0.1:8000/v1/healthz'
curl 'http://127.0.0.1:8000/metrics'
```

配置见 [`docs/design/09-deployment.md`](docs/design/09-deployment.md) 的「配置」一节。
