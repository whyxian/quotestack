"""Regenerate the facts that keep drifting out of the documentation.

Documentation rots in a specific way: not prose, but numbers. "10 methods",
"11 routes", "13 error types" were each true once, then silently stopped being
true because they were typed by hand in four places.

This script derives those numbers from the code and writes them into marked
blocks. It also mirrors each design document's own status line into the index
table, so the index cannot disagree with the page it points at.

Usage::

    uv run python scripts/sync_docs.py           # rewrite
    uv run python scripts/sync_docs.py --check   # exit 1 if anything is stale
"""

from __future__ import annotations

import inspect
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs" / "design"
HARNESS = ROOT / "docs" / "harness"
INDEX = DESIGN / "README.md"
ARCHITECTURE = HARNESS / "ARCHITECTURE.md"

BEGIN = "<!-- generated:begin -->"
END = "<!-- generated:end -->"


def _import() -> tuple[object, dict[str, object], list[str], str]:
    """Import the library and collect what the docs need to state."""
    import quotestack
    from quotestack.errors import MarketDataError
    from quotestack.models import Capability
    from quotestack.sources import (
        BinanceSource,
        EastMoneySource,
        FxSource,
        TencentSource,
        TiantianSource,
    )

    sources = [
        source_cls()
        for source_cls in (
            EastMoneySource,
            TencentSource,
            TiantianSource,
            BinanceSource,
            FxSource,
        )
    ]
    # Leaf classes are the ones a caller can actually catch by name; the two
    # bases (MarketDataError and UpstreamError) only exist for grouping.
    classes = [
        value
        for value in vars(__import__("quotestack.errors", fromlist=["x"])).values()
        if isinstance(value, type)
        and issubclass(value, MarketDataError)
        and value is not MarketDataError
    ]
    leaves = sorted(
        cls.code for cls in classes if not any(other.__base__ is cls for other in classes)
    )
    bases = sorted(cls.code for cls in classes if any(o.__base__ is cls for o in classes))
    capabilities = [capability.value for capability in Capability]
    return (
        quotestack,
        {"sources": sources, "leaves": leaves, "bases": bases},
        [],
        "|".join(capabilities),
    )


def _counts() -> dict[str, object]:
    import yaml

    package, extra, _, _ = _import()
    spec = yaml.safe_load((ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    sources = extra["sources"]

    files = sorted((ROOT / "src/quotestack").rglob("*.py"))
    lines = sum(len(path.read_text(encoding="utf-8").splitlines()) for path in files)

    return {
        "version": package.__version__,  # type: ignore[attr-defined]
        "methods": _import_methods(),
        "routes": sorted(spec["paths"]),
        "codes": extra["leaves"],
        "bases": extra["bases"],
        "sources": sorted(source.meta.name for source in sources),
        "capabilities": [
            c.value for c in __import__("quotestack.models", fromlist=["x"]).Capability
        ],
        "files": len(files),
        "lines": lines,
    }


def _import_methods() -> list[str]:
    from quotestack import MarketData

    return sorted(
        name
        for name, value in inspect.getmembers(MarketData, predicate=inspect.isfunction)
        if not name.startswith("_") and name not in {"aclose", "cache_stats", "health"}
    )


def _facts_block(facts: dict[str, object]) -> str:
    methods = facts["methods"]
    routes = facts["routes"]
    codes = facts["codes"]
    sources = facts["sources"]
    capabilities = facts["capabilities"]
    return "\n".join(
        [
            BEGIN,
            "<!-- 由 scripts/sync_docs.py 生成，不要手改 -->",
            "",
            f"**当前事实**（版本 {facts['version']}，源码 {facts['files']} 文件 / "
            f"{facts['lines']:,} 行）",
            "",
            "| 项 | 数量 | 明细 |",
            "|---|---|---|",
            f"| 公开取数方法 | {len(methods)} | {', '.join(f'`{m}`' for m in methods)} |",
            f"| HTTP 路由 | {len(routes)} | {', '.join(f'`{r}`' for r in routes)} |",
            f"| 错误类型 | {len(codes)} | {', '.join(f'`{c}`' for c in codes)} |",
            f"| 错误基类 | {len(facts['bases'])} | {', '.join(f'`{c}`' for c in facts['bases'])} |",
            f"| 数据源 | {len(sources)} | {', '.join(f'`{s}`' for s in sources)} |",
            f"| 能力（Capability） | {len(capabilities)} | {', '.join(f'`{c}`' for c in capabilities)} |",
            "",
            END,
        ]
    )


def _invariants() -> str:
    """Render the short form of every non-negotiable rule.

    AGENTS.md is the only file guaranteed to enter an agent's context, so the
    rules have to be visible there. The table in CONSTRAINTS.md is the source;
    this is generated from it rather than typed twice.
    """
    text = (ROOT / "docs/harness/CONSTRAINTS.md").read_text(encoding="utf-8")
    block = re.search(r"<!-- invariants:begin -->(.*?)<!-- invariants:end -->", text, re.S)
    if block is None:
        return ""

    lines = [
        BEGIN,
        "<!-- 由 scripts/sync_docs.py 从 docs/harness/CONSTRAINTS.md 生成，不要手改 -->",
        "",
        "| ID | 不可协商 | 反例 |",
        "|---|---|---|",
    ]
    for line in block.group(1).splitlines():
        # A cell may contain an escaped pipe (``float \| str``), so protect it
        # before splitting and put it back afterwards.
        protected = line.replace(r"\|", "\x00")
        cells = [
            cell.strip().replace("\x00", r"\|") for cell in protected.strip().strip("|").split("|")
        ]
        if len(cells) == 3 and re.fullmatch(r"R\d+", cells[0]):
            lines.append(f"| {cells[0]} | {cells[1]} | {cells[2]} |")
    lines.extend(["", END])
    return "\n".join(lines)


def _status_of(path: pathlib.Path) -> str:
    """Read a design document's own status line."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^> \*\*实现状态\*\*：(.+)$", text, re.M)
    return match.group(1).strip() if match else "—"


def _sync_index_status(facts_block: str) -> str:
    """Replace the facts block and mirror each page's status into the index."""
    text = INDEX.read_text(encoding="utf-8")

    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        text = head + facts_block + tail
    else:
        text = text.replace("## 文档索引", facts_block + "\n\n## 文档索引", 1)

    def fix_row(match: re.Match[str]) -> str:
        number, target, title, _status, rest = match.groups()
        page = DESIGN / target
        current = _status_of(page) if page.exists() else "—"
        return f"| [{number}]({target}) | **{title}** | {current} |{rest}"

    row = re.compile(r"^\| \[(\d+)\]\(([^)]+\.md)\) \| \*\*(.+?)\*\* \| (.*?) \|(.*)$", re.M)
    return row.sub(fix_row, text)


def _sync_architecture(facts: dict[str, object]) -> str:
    """Keep the size table honest."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    files = sorted(
        (
            (path, len(path.read_text(encoding="utf-8").splitlines()))
            for path in (ROOT / "src/quotestack").rglob("*.py")
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    rows = [
        "| 文件 | 行数 |",
        "|---|---|",
        *(f"| `{path.relative_to(ROOT / 'src')}` | {count} |" for path, count in files[:5]),
        f"| 其余 {len(files) - 5} 个文件 | < {files[5][1]} |" if len(files) > 5 else "",
        "",
        f"**合计**：{facts['lines']:,} 行 / {facts['files']} 文件。",
    ]
    block = "\n".join(
        [BEGIN, "<!-- 由 scripts/sync_docs.py 生成，不要手改 -->", "", *rows, "", END]
    )

    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if pattern.search(text):
        return pattern.sub(lambda _: block, text)
    return text.replace("## 8. 测试布局", block + "\n\n## 8. 测试布局", 1)


def sync() -> list[pathlib.Path]:
    """Rewrite every generated block.

    Returns:
        Paths whose content changed.
    """
    facts = _counts()
    changes = []

    updated = _sync_index_status(_facts_block(facts))
    if updated != INDEX.read_text(encoding="utf-8"):
        INDEX.write_text(updated, encoding="utf-8")
        changes.append(INDEX)

    agents = ROOT / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    block = _invariants()
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if block:
        updated_agents = (
            pattern.sub(lambda _: block, text)
            if pattern.search(text)
            else text.replace("## 5. 三类文档的边界", block + "\n\n## 5. 三类文档的边界", 1)
        )
        if updated_agents != text:
            agents.write_text(updated_agents, encoding="utf-8")
            changes.append(agents)

    updated = _sync_architecture(facts)
    if updated != ARCHITECTURE.read_text(encoding="utf-8"):
        ARCHITECTURE.write_text(updated, encoding="utf-8")
        changes.append(ARCHITECTURE)

    return changes


def main() -> int:
    """Entry point.

    Returns:
        ``0`` when everything is current, ``1`` in check mode when it is not.
    """
    check = "--check" in sys.argv
    if not check:
        for path in sync():
            print(f"updated {path.relative_to(ROOT)}")
        return 0

    agents = ROOT / "AGENTS.md"
    before = {path: path.read_text(encoding="utf-8") for path in (INDEX, ARCHITECTURE, agents)}
    facts = _counts()
    stale = []
    if _sync_index_status(_facts_block(facts)) != before[INDEX]:
        stale.append(INDEX)
    if _sync_architecture(facts) != before[ARCHITECTURE]:
        stale.append(ARCHITECTURE)
    block = _invariants()
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    projected = (
        pattern.sub(lambda _: block, before[agents])
        if block and pattern.search(before[agents])
        else before[agents]
    )
    if projected != before[agents]:
        stale.append(agents)

    for path in stale:
        print(f"stale {path.relative_to(ROOT)}")
    if stale:
        print("run: uv run python scripts/sync_docs.py")
        return 1
    print("docs are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
