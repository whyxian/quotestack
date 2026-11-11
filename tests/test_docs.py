"""Contract tests that keep documentation honest about capabilities.

These do not check prose, only the tables a reader would trust at face value.
"""

from __future__ import annotations

import pathlib
import re

from quotestack.identity import resolve
from quotestack.models import AssetClass, Capability, Market
from quotestack.sources import (
    BinanceSource,
    EastMoneySource,
    FxSource,
    TencentSource,
    TiantianSource,
)

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]

_DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "design" / "03-sources.md"

_NAMES = {
    "东方财富": "eastmoney",
    "腾讯": "tencent",
    "天天基金": "tiantian",
    "Binance": "binance",
    "东财外汇": "eastmoney-fx",
}


def _section(start: str, end: str) -> str:
    text = _DOC.read_text(encoding="utf-8")
    return text[text.index(start) : text.index(end)]


def test_source_capability_table_matches_the_code() -> None:
    """The selection table must not drift from SourceMeta."""
    real = {
        source.meta.name: {capability.value for capability in source.meta.capabilities}
        for source in (
            EastMoneySource(),
            TencentSource(),
            TiantianSource(),
            BinanceSource(),
            FxSource(),
        )
    }
    section = _section("## 1. 选型结果", "## 1.1 能力字典")

    seen = 0
    for line in section.splitlines():
        if not line.startswith("| **"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        # The label may carry the registry name in parentheses, e.g.
        # "**东财外汇**（`eastmoney-fx`）"; match on the readable part.
        label = cells[0].split("（")[0].strip("* ")
        source = _NAMES.get(label)
        if source is None:
            continue
        documented = set(re.findall(r"`([A-Z]+)`", cells[2]))
        assert documented == real[source], f"{source} table drifted"
        seen += 1

    assert seen == len(_NAMES), "every source needs a row"


def test_every_capability_appears_in_the_dictionary() -> None:
    """A capability with no explanation is a term the reader cannot decode."""
    section = _section("## 1.1 能力字典", "## 2. 东方财富")

    for capability in Capability:
        assert f"`{capability.value}`" in section, f"{capability.value} is undocumented"


def test_documented_instrument_capabilities_match_the_resolver() -> None:
    """The per-instrument example must be reproducible from the code."""
    section = _section("### 不同标的的能力不同", "## 2. 东方财富")

    cases = {
        "CN:STOCK:600519": ("600519", AssetClass.STOCK, Market.CN),
        "CN:FUND:510010": ("510010", AssetClass.FUND, Market.CN),
        "CN:FUND:022430": ("022430", AssetClass.FUND, Market.CN),
        "US:STOCK:AAPL": ("AAPL", AssetClass.STOCK, Market.US),
    }
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        identifier = cells[0].strip("`")
        if identifier not in cases:
            continue
        code, asset_class, market = cases[identifier]
        expected = {c.value for c in resolve(code, asset_class, market).capabilities}
        documented = set(re.findall(r"`([A-Z]+)`", cells[1]))
        assert documented == expected, f"{identifier} drifted"


def test_sources_declare_list_when_they_implement_it() -> None:
    """A source that can enumerate a market must say so.

    The capability list is what routing and health reporting read, so a source
    that implements ``list_instruments`` but hides the capability looks, from
    the outside, like it cannot list anything.
    """
    for source in (
        EastMoneySource(),
        TencentSource(),
        TiantianSource(),
        BinanceSource(),
        FxSource(),
    ):
        implements = hasattr(source, "list_instruments")
        declares = Capability.LIST in source.meta.capabilities
        assert implements == declares, f"{source.meta.name} disagrees with itself"


def test_guide_status_table_matches_the_spec() -> None:
    """The status codes the guide lists must be the ones the API can return."""
    import yaml

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = yaml.safe_load((root / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    documented = set()
    for operations in spec["paths"].values():
        for operation in operations.values():
            documented.update(
                int(code)
                for code in operation.get("responses", {})
                if code.isdigit() and int(code) >= 400
            )

    guide = (root / "guide/07-service.md").read_text(encoding="utf-8")
    table = guide[guide.index("| 状态 | 错误码") : guide.index("> **不要只看")]
    listed = {int(code) for code in re.findall(r"^\| (\d{3}) \|", table, re.M)}

    # The guide table is an error table, so success codes are out of scope.
    assert listed == documented, f"guide lists {sorted(listed)}, spec declares {sorted(documented)}"


def test_generated_doc_blocks_are_current() -> None:
    """The numbers in the docs must be the ones the code produces.

    Regenerating and comparing is the only way to keep hand-typed counts from
    drifting; four different error counts once lived in this repository.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/sync_docs.py", "--check"],
        cwd=pathlib.Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"docs are stale:\n{result.stdout}\nrun: uv run python scripts/sync_docs.py"
    )


def test_index_status_matches_each_page() -> None:
    """The index table must not claim a status its page contradicts."""
    root = pathlib.Path(__file__).resolve().parents[1]
    design = root / "docs" / "design"
    index = (design / "README.md").read_text(encoding="utf-8")

    for match in re.finditer(r"^\| \[\d+\]\(([^)]+\.md)\) \| \*\*.+?\*\* \| (.+?) \|", index, re.M):
        target, shown = match.group(1), match.group(2).strip()
        page = (design / target).read_text(encoding="utf-8")
        declared = re.search(r"^> \*\*实现状态\*\*：(.+)$", page, re.M)
        if declared is None:
            continue
        assert shown == declared.group(1).strip(), f"{target} status drifted"


def test_error_status_table_matches_the_server() -> None:
    """The HTTP mapping documented in 06-errors must be the one the server uses."""
    from quotestack.server.errors import STATUS_BY_CODE

    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / "docs/design/06-errors.md").read_text(encoding="utf-8")

    documented: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(r"^\| `([A-Za-z]+)` \| .*? \| (\d{3}) \|$", line)
        if match:
            documented[match.group(1)] = int(match.group(2))

    actual = {cls.__name__.removesuffix("Error"): status for cls, status in STATUS_BY_CODE.items()}

    assert documented, "no mapping rows parsed from 06-errors"
    for name, status in documented.items():
        assert actual.get(name) == status, (
            f"{name}: doc says {status}, server says {actual.get(name)}"
        )
    assert set(documented) == set(actual) | {"Delisted"}, (
        f"documented {sorted(documented)} vs server {sorted(actual)}"
    )


def test_sources_listed_in_the_docs_match_the_code() -> None:
    """A source named in the docs must exist; a removed one must not linger."""
    from quotestack.sources import (
        BinanceSource,
        EastMoneySource,
        FxSource,
        TencentSource,
        TiantianSource,
    )

    real = {
        source.meta.name
        for source in (
            EastMoneySource(),
            TencentSource(),
            TiantianSource(),
            BinanceSource(),
            FxSource(),
        )
    }
    root = pathlib.Path(__file__).resolve().parents[1]
    index = (root / "docs/design/README.md").read_text(encoding="utf-8")

    assert "OKX+CoinGecko" not in index, "removed sources still listed as active"
    for name in real:
        assert f"`{name}`" in index


def test_harness_documents_are_reachable_from_the_entry_point() -> None:
    """AGENTS.md is an index; every harness file must be reachable from it."""
    root = pathlib.Path(__file__).resolve().parents[1]
    entry = (root / "AGENTS.md").read_text(encoding="utf-8")
    harness = sorted((root / "docs/harness").glob("*.md"))

    assert harness, "no harness documents"
    for path in harness:
        if path.name == "README.md":
            continue
        assert f"harness/{path.stem}" in entry, f"{path.name} is not linked from AGENTS.md"


def test_harness_does_not_hold_human_only_documents() -> None:
    """harness is AI context; a human code guide belongs elsewhere."""
    root = pathlib.Path(__file__).resolve().parents[1]
    names = {path.name for path in (root / "docs/harness").glob("*.md")}

    assert "CODE_MAP_ZH.md" not in names, "the Chinese code map is human-facing"
    assert (root / "docs/CODE_MAP_ZH.md").exists()


def test_entry_point_stays_an_index() -> None:
    """AGENTS.md should point at rules, not restate them."""
    root = pathlib.Path(__file__).resolve().parents[1]
    lines = len((root / "AGENTS.md").read_text(encoding="utf-8").splitlines())

    assert lines < 130, f"AGENTS.md grew to {lines} lines; move detail into harness/"


def test_sync_wrapper_covers_every_public_method() -> None:
    """The sync facade must not silently expose a subset of the async client.

    It shipped with five of eleven methods: no nav, no profile, no estimate.
    Someone not using asyncio would have concluded the library could not do
    those things.
    """
    import inspect

    from quotestack import MarketData
    from quotestack.sync import SyncMarketData

    def public(cls: type) -> set[str]:
        return {
            name
            for name, value in inspect.getmembers(cls, predicate=inspect.isfunction)
            if not name.startswith("_")
            and name not in {"aclose", "close", "cache_stats", "health", "source_for"}
        }

    missing = public(MarketData) - public(SyncMarketData)
    assert not missing, f"SyncMarketData is missing {sorted(missing)}"


def test_guide_capability_matrix_matches_the_sources() -> None:
    """The matrix in the reference must be what each adapter declares.

    Rows are capabilities, columns are sources.
    """
    from quotestack.models import Capability
    from quotestack.sources import (
        BinanceSource,
        EastMoneySource,
        FxSource,
        TencentSource,
        TiantianSource,
    )

    real = {
        source().meta.name: {c.value for c in source().meta.capabilities}
        for source in (EastMoneySource, TencentSource, TiantianSource, BinanceSource, FxSource)
    }
    labels = {
        "东财": "eastmoney",
        "腾讯": "tencent",
        "天天基金": "tiantian",
        "Binance": "binance",
        "东财外汇": "eastmoney-fx",
    }

    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / "guide/12-reference.md").read_text(encoding="utf-8")
    section = text[text.index("| 能力 | 东财") :]
    section = section[: section.index("\n\n")]

    header: list[str] = []
    checked = 0
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not header:
            header = cells
            continue
        name = cells[0].strip("`")
        if name not in {c.value for c in Capability}:
            continue
        for label, cell in zip(header[1:], cells[1:], strict=False):
            source = labels[label]
            documented = cell == "✅"
            declared = name in real[source]
            assert documented == declared, (
                f"{source}/{name}: guide says {cell}, source declares {'YES' if declared else 'NO'}"
            )
            checked += 1

    assert checked >= 40, f"only {checked} cells parsed; table shape changed"


def test_documentation_fragments_and_links() -> None:
    """Links must resolve and Python blocks must parse.

    Both fail silently: a broken link only matters when a reader clicks it, and
    a block that does not parse only matters when someone copies it. Neither
    shows up in review, which is why they are checked here.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/check_docs.py"],
        cwd=pathlib.Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"documentation checks failed:\n{result.stdout}"


def test_guide_does_not_promise_crypto_quotes() -> None:
    """The guide said crypto has quotes; no route or source serves them."""
    root = pathlib.Path(__file__).resolve().parents[1]
    concepts = (root / "guide/02-concepts.md").read_text(encoding="utf-8")

    assert "只有全市场列表" in concepts
    # The stock row may say "报价、K 线"; the crypto row must not.
    crypto_rows = [line for line in concepts.splitlines() if "CRYPTO:" in line]
    assert crypto_rows
    assert not any("报价、K 线" in line for line in crypto_rows)


def test_guide_rate_limit_matches_the_configured_bucket() -> None:
    """A claim about throughput has to agree with the limiter we ship."""
    from quotestack.resilience import TokenBucket

    bucket = TokenBucket()
    root = pathlib.Path(__file__).resolve().parents[1]
    universe = (root / "guide/06-universe.md").read_text(encoding="utf-8")

    assert f"{bucket._rate:g} 次/秒" in universe, (
        f"guide states a rate that is not the bucket's {bucket._rate:g}/s"
    )


def _doc_ttl_rows() -> dict[str, str]:
    """Parse the TTL tables out of the design and guide documents."""
    root = pathlib.Path(__file__).resolve().parents[1]
    design = (root / "docs/design/04-cache.md").read_text(encoding="utf-8")
    section = design[design.index("| 能力 | 默认 TTL |") :]
    section = section[: section.index("\n\n")]

    rows: dict[str, str] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[0].startswith("`"):
            rows[cells[0].strip("`")] = cells[1]
    return rows


def test_design_ttl_table_matches_the_policy() -> None:
    """The cache table in the design doc must be the code's table.

    It listed `benchmark 6 小时` and a separate 60-second TTL for minute bars.
    Neither was true: benchmark is not cached at all, and history has one TTL.
    """
    from quotestack.cache.base import _CACHE_POLICY
    from quotestack.models import Capability

    rows = _doc_ttl_rows()
    assert set(rows) == {capability.value for capability in Capability}, (
        "design table must have one row per capability"
    )

    for capability, policy in _CACHE_POLICY.items():
        documented = rows[capability.value]
        if policy is None:
            assert "不缓存" in documented, f"{capability.value} is not cached but says {documented}"
        else:
            assert "不缓存" not in documented, f"{capability.value} is cached but says {documented}"


def test_guide_ttl_table_does_not_claim_an_uncached_capability_is_cached() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    guide = (root / "guide/12-reference.md").read_text(encoding="utf-8")
    section = guide[guide.index("| 能力 | 默认 TTL |") :]
    section = section[: section.index("\n\n")]

    for capability in ("BENCHMARK", "LIST"):
        rows = [line for line in section.splitlines() if f"`{capability}`" in line]
        assert rows, f"guide has no row for {capability}"
        assert "不缓存" in rows[0]


def test_cli_command_list_matches_the_parser() -> None:
    """The API doc listed four commands; the parser has five."""
    from quotestack.cli import _build_parser

    parser = _build_parser()
    actions = [
        action
        for action in parser._subparsers._group_actions  # type: ignore[attr-defined]
        if hasattr(action, "choices") and action.choices
    ]
    real = set(actions[0].choices)  # type: ignore[attr-defined]

    root = pathlib.Path(__file__).resolve().parents[1]
    doc = (root / "docs/design/05-api.md").read_text(encoding="utf-8")
    section = doc[doc.index("### 命令集") :]
    section = section[: section.index("### 输出")]
    documented = set(re.findall(r"^\| `([a-z]+)` \|", section, re.M))

    assert documented == real, f"doc {sorted(documented)} vs parser {sorted(real)}"


def test_adapter_doc_lists_the_real_capabilities() -> None:
    """The adapter example claimed Binance serves QUOTE and HISTORY.

    It serves LIST. The section also documented a `_assert_schema` helper that
    no source has, and a routing table naming okx and coingecko.
    """
    from quotestack.sources import (
        BinanceSource,
        EastMoneySource,
        TiantianSource,
    )

    root = pathlib.Path(__file__).resolve().parents[1]
    doc = (root / "docs/design/08-adapters.md").read_text(encoding="utf-8")

    assert "_assert_schema" not in doc
    assert "coingecko" not in doc.lower()
    assert "okx" not in doc.lower()

    for source in (EastMoneySource(), TiantianSource(), BinanceSource()):
        assert f'name="{source.meta.name}"' in doc
        for capability in source.meta.capabilities:
            assert capability.value in doc, f"{source.meta.name} missing {capability.value}"


def test_permission_format_is_defined_once() -> None:
    """The four-item list lives in R11, not also in BOUNDARY.

    It was in both: CONSTRAINTS enumerated the items and BOUNDARY repeated the
    block. Two copies of one rule drift, which is the whole reason the cache
    policy became a single table.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    constraints = (root / "docs/harness/CONSTRAINTS.md").read_text(encoding="utf-8")
    boundary = (root / "docs/harness/BOUNDARY.md").read_text(encoding="utf-8")

    assert "R11" in constraints
    for item in ("改什么", "为什么", "影响", "撤销"):
        assert item in constraints, f"R11 must name {item}"

    # BOUNDARY points at R11 and explains the items rather than re-listing them
    # as a form to copy.
    assert "R11" in boundary
    assert "【申请权限】" in boundary, "the worked example belongs here"
    assert boundary.count("改什么：<") == 0, "BOUNDARY must not redefine the form"


def test_error_tree_matches_the_class_hierarchy() -> None:
    """The tree named three intermediate classes that do not exist.

    `InputError`, `IdentityError` and `CapabilityError` were in the diagram and
    nowhere in the code, while Unauthorized and Internal were missing.
    """
    from quotestack.errors import MarketDataError

    def walk(cls: type) -> set[str]:
        found = set()
        for sub in cls.__subclasses__():
            found.add(sub.__name__)
            found |= walk(sub)
        return found

    real = walk(MarketDataError)

    root = pathlib.Path(__file__).resolve().parents[1]
    doc = (root / "docs/design/06-errors.md").read_text(encoding="utf-8")
    block = doc[doc.index("MarketDataError") : doc.index("### 处置策略")]
    # Only the tree lines: the paragraph below names errors that deliberately
    # do not exist, and those must not count as documented classes.
    tree_lines = [line for line in block.splitlines() if "├──" in line or "└──" in line]
    documented = {
        match for line in tree_lines for match in re.findall(r"([A-Z][A-Za-z]+Error)\b", line)
    }

    assert documented == real, (
        f"only in doc: {sorted(documented - real)}; only in code: {sorted(real - documented)}"
    )


def test_documented_benchmark_classifications_are_real() -> None:
    """Every row in the classification table must reproduce.

    The table listed bare names like `中证800` and called them equity; the
    classifier needs the word 指数, which the real benchmark text carries, so
    the table could not be reproduced from the page.
    """
    from quotestack.benchmark import ComponentKind, classify_component

    root = pathlib.Path(__file__).resolve().parents[1]
    doc = (root / "docs/design/07-funds.md").read_text(encoding="utf-8")
    section = doc[doc.index("| 原始组件文本 | 判定 |") :]
    section = section[: section.index("**裸名字会判成")]

    checked = 0
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        expected_cell = cells[1].strip("`")
        if expected_cell not in {"EQUITY", "NON_EQUITY"}:
            continue
        for name in re.findall(r"`([^`]+)`", cells[0]):
            assert classify_component(name) is ComponentKind[expected_cell], name
            checked += 1

    assert checked >= 10, f"only {checked} rows parsed"


def test_examples_doc_lists_the_real_files() -> None:
    """The examples table named quote.py, history.py and fund_estimate.py.

    None of them exist: the directory holds 01_quote, 02_fund_estimate and
    03_refresh_universe, and nothing imports matplotlib.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    doc = (root / "docs/design/10-open-source.md").read_text(encoding="utf-8")
    section = doc[doc.index("| 示例 | 演示什么 |") :]
    section = section[: section.index("每个示例必须能独立运行")]

    documented = set(re.findall(r"`examples/([0-9a-z_]+\.py)`", section))
    real = {path.name for path in (root / "examples").glob("*.py")}

    assert documented == real, f"doc {sorted(documented)} vs files {sorted(real)}"


def test_guide_fund_classes_match_the_enum() -> None:
    """The guide lists the seven fund classes readers will see."""
    from quotestack.models import FundClass

    root = pathlib.Path(__file__).resolve().parents[1]
    guide = (root / "guide/04-funds.md").read_text(encoding="utf-8")
    section = guide[guide.index("| `fund_class` | 涵盖 | 含义 |") :]
    section = section[: section.index("**未知标签一律归")]

    documented = set(re.findall(r"^\| `([A-Z]+)` \|", section, re.M))
    real = {member.value for member in FundClass}

    assert documented == real, f"guide {sorted(documented)} vs enum {sorted(real)}"


def test_guide_batch_request_count_is_not_a_single_request() -> None:
    """Batching by 50 per market means the count depends on the caller's list.

    The guide said one network request for any batch, which the implementation
    contradicts as soon as a batch spans two markets or exceeds 50 instruments.
    """
    from quotestack.sources.eastmoney.quotes import MAX_BATCH

    root = pathlib.Path(__file__).resolve().parents[1]
    guide = (root / "guide/03-quotes.md").read_text(encoding="utf-8")

    assert f"{MAX_BATCH} 只一批" in guide
    assert "一次网络请求" not in guide


def test_guide_does_not_promise_a_single_request_for_batches() -> None:
    """Batching is per market and per 50 instruments, not one request."""
    root = pathlib.Path(__file__).resolve().parents[1]
    for relative in ("guide/03-quotes.md", "guide/09-recipes.md", "guide/10-sync.md"):
        text = (root / relative).read_text(encoding="utf-8")
        assert "一次网络请求" not in text.replace("一次请求拿一批", ""), relative


def test_code_map_identifiers_exist_in_the_source() -> None:
    """The code map pointed at `_DEFAULT_TTL`, `_wrap` and `_LIST_FILTERS`.

    The first two were removed when the cache policy became one table and the
    envelope got a name; the third lost its leading underscore. A reader
    following the map would grep for names that return nothing.
    """
    import ast

    known: set[str] = set()
    for path in (ROOT_DIR / "src/quotestack").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                known.add(node.name)
            elif isinstance(node, ast.Assign):
                known.update(target.id for target in node.targets if isinstance(target, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                known.add(node.target.id)

    text = (ROOT_DIR / "docs/CODE_MAP_ZH.md").read_text(encoding="utf-8")
    # Only the quick-reference rows: "| `name` | ..." in the lookup table.
    section = text[text.index("| 改缓存时长 |") :]
    section = section[: section.index("\n\n")]

    referenced = {
        token
        for line in section.splitlines()
        for token in re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", line)
    }
    missing = sorted(name for name in referenced if name not in known and not name.endswith(".py"))

    assert not missing, f"code map names identifiers that do not exist: {missing}"
