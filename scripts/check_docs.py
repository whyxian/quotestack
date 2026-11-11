"""Documentation checks that a human reviewer cannot do reliably.

Three failure modes, all of which have happened in this repository:

1. A link to a file that was moved or never existed.
2. A code block that is not valid Python, so copying it fails.
3. The guide referencing the repository, which breaks it as a standalone site.

Usage::

    uv run python scripts/check_docs.py
"""

from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUIDE = ROOT / "guide"

# The installed environment contains its own Markdown, which is not ours.
SKIP_DIRS = {".git", ".venv", "node_modules", "dist", "build", "__pycache__"}

# A block whose first line is this comment is a deliberate fragment: half an
# if/else, an excerpt shown for contrast. It is not meant to be copied whole.
FRAGMENT = "<!-- fragment -->"
LINK = re.compile(r"\]\(([^)\s]+)\)")
CODE_BLOCK = re.compile(r"^```python\n(.*?)^```", re.M | re.S)


def _documents() -> list[pathlib.Path]:
    return sorted(
        path for path in ROOT.rglob("*.md") if not any(part in SKIP_DIRS for part in path.parts)
    )


def _all_lines(path: pathlib.Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def check_links() -> list[str]:
    """Every relative link must resolve from the file that contains it."""
    problems = []
    for path in _documents():
        for line_number, line in enumerate(_all_lines(path), start=1):
            for target in LINK.findall(line):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                resolved = (path.parent / target.split("#")[0]).resolve()
                if not resolved.exists():
                    where = f"{path.relative_to(ROOT)}:{line_number}"
                    problems.append(f"{where}: broken link {target}")
    return problems


def _parses(source: str) -> bool:
    """Whether a snippet is syntactically valid.

    Snippets are written at top level and use ``await``, so they are wrapped in
    an async function before parsing. Indentation is normalised first.
    """
    body = "\n".join(f"    {line}" if line.strip() else "" for line in source.splitlines())
    try:
        ast.parse(f"async def _snippet():\n{body}\n")
    except SyntaxError:
        return False
    return True


def check_code_blocks() -> list[str]:
    """Python blocks must at least parse, unless marked as a fragment."""
    problems = []
    for path in _documents():
        text = path.read_text(encoding="utf-8")
        for match in CODE_BLOCK.finditer(text):
            preceding = text[max(0, match.start() - 200) : match.start()]
            if FRAGMENT in preceding.splitlines()[-2:][0] or preceding.rstrip().endswith(FRAGMENT):
                continue
            snippet = match.group(1)
            if _parses(snippet):
                continue
            line_number = text[: match.start()].count("\n") + 1
            first = snippet.strip().splitlines()[0] if snippet.strip() else "(empty)"
            problems.append(
                f"{path.relative_to(ROOT)}:{line_number}: block does not parse ({first[:50]})"
            )
    return problems


# Numbers that were typed by hand once and then stopped being true. These are
# exact strings from past incidents; the patterns below catch new ones.
STALE_PHRASES = (
    "6,000 行",
    "45 个文件",
    "10 个入口",
    "11 种错误",
    "11 条路由",
    "10 个方法",
    "142 个测试",
    "13 种错误",
    "7,292 行",
    "24 个符号",
    "1028 行",
    "14 个错误类",
)

# Counts describing the current codebase. In these files every such number must
# come from a generated block; a hand-typed one will drift.
FACT_DOCS = {
    "AGENTS.md",
    "docs/CODE_MAP_ZH.md",
    "docs/api/README.md",
    "docs/design/README.md",
    "docs/harness/ARCHITECTURE.md",
}
COUNT_PATTERNS = (
    re.compile(r"\d[\d,]*\s*(?:个|条)?\s*(?:数据)?\s*(?:方法|入口|路由|接口|错误|符号|测试)"),
    re.compile(r"\d[\d,]*\s*行"),
)


def _content_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every line except the generated blocks.

    Code fences are included on purpose: the stale count that started this
    check was inside an ASCII tree, not in prose.
    """
    lines = []
    in_generated = False
    for number, line in enumerate(_all_lines(path), start=1):
        stripped = line.strip()
        if "generated:begin" in stripped:
            in_generated = True
            continue
        if "generated:end" in stripped:
            in_generated = False
            continue
        if not in_generated:
            lines.append((number, line))
    return lines


def check_hand_typed_counts() -> list[str]:
    """Counts belong in generated blocks, not typed by hand."""
    problems = []
    for path in _documents():
        relative = path.relative_to(ROOT).as_posix()
        for number, line in _content_lines(path):
            where = f"{relative}:{number}"
            stale = next((phrase for phrase in STALE_PHRASES if phrase in line), None)
            if stale is not None:
                problems.append(f"{where}: hand-typed count '{stale}' (delete it)")
                continue
            if relative not in FACT_DOCS:
                continue
            for pattern in COUNT_PATTERNS:
                match = pattern.search(line)
                if match is not None:
                    problems.append(f"{where}: hand-typed count '{match.group(0)}' (delete it)")
                    break
    return problems


# Which milestone delivers each design page. A page cannot claim it is not
# started once the milestone that implements it is fully checked off; the
# status column mirrors the page, so both would agree on something untrue.
PAGE_MILESTONES = {
    "02-identity.md": ("M1",),
    "03-sources.md": ("M2", "M3"),
    "04-cache.md": ("M1", "M2"),
    "05-api.md": ("M1", "M6"),
    "06-errors.md": ("M1", "M6"),
    "07-funds.md": ("M4", "M5"),
    "08-adapters.md": ("M2", "M3"),
    "09-deployment.md": ("M6",),
    "10-open-source.md": ("M8",),
    "12-observability.md": ("M6",),
    "13-runtime-model.md": ("M2", "M6"),
    "14-testing.md": ("M7",),
    "15-code-style.md": ("M0",),
}


def _milestone_completion() -> dict[str, int]:
    """Count unfinished items per milestone."""
    text = (ROOT / "docs/ROADMAP.md").read_text(encoding="utf-8")
    remaining = {}
    for match in re.finditer(r"^## (M[\d.]+)\b(.*?)(?=^## |\Z)", text, re.M | re.S):
        remaining[match.group(1)] = len(re.findall(r"^- \[ \]", match.group(2), re.M))
    return remaining


def check_status_against_roadmap() -> list[str]:
    """A page cannot be 'not started' if its milestone is done."""
    remaining = _milestone_completion()
    problems = []
    for name, milestones in PAGE_MILESTONES.items():
        page = ROOT / "docs" / "design" / name
        if not page.exists():
            problems.append(f"docs/design/{name}: listed but missing")
            continue
        status = re.search(r"^> \*\*实现状态\*\*：(.+)$", page.read_text(encoding="utf-8"), re.M)
        if status is None:
            problems.append(f"docs/design/{name}: no status line")
            continue
        claimed = status.group(1)
        if "⬜" not in claimed:
            continue
        finished = [m for m in milestones if remaining.get(m, 1) == 0]
        if finished:
            problems.append(
                f"docs/design/{name}: says not started, but {'/'.join(finished)} is complete"
            )
    return problems


def check_roadmap_progress() -> list[str]:
    """The hand-written progress block must match the checkboxes below it."""
    text = (ROOT / "docs/ROADMAP.md").read_text(encoding="utf-8")
    done = len(re.findall(r"^- \[x\]", text, re.M))
    total = done + len(re.findall(r"^- \[ \]", text, re.M))
    match = re.search(r"累计：(\d+) / (\d+) 项", text)
    if match is None:
        return ["docs/ROADMAP.md: progress block has no '累计：N / M 项'"]
    claimed = (int(match.group(1)), int(match.group(2)))
    if claimed != (done, total):
        return [
            f"docs/ROADMAP.md: progress says {claimed[0]} / {claimed[1]}, "
            f"checkboxes say {done} / {total}"
        ]
    return []


def check_code_map_covers_modules() -> list[str]:
    """Every module must be mentioned somewhere in the code map.

    The map shipped without a server/ chapter: seven files and the entire HTTP
    layer were absent, and nothing noticed.
    """
    code_map = (ROOT / "docs/CODE_MAP_ZH.md").read_text(encoding="utf-8")
    headings = " ".join(re.findall(r"^#{2,3} (.+)$", code_map, re.M))

    units = set()
    for path in (ROOT / "src/quotestack").rglob("*.py"):
        if path.name == "__init__.py":
            continue
        relative = path.relative_to(ROOT / "src/quotestack")
        units.add(relative.parts[0] if len(relative.parts) > 1 else path.stem)

    return [f"CODE_MAP does not mention '{unit}'" for unit in sorted(units) if unit not in headings]


def check_guide_is_standalone() -> list[str]:
    """The guide must not link outside itself, or hosting it breaks."""
    problems = []
    for path in GUIDE.rglob("*.md"):
        for line_number, line in enumerate(_all_lines(path), start=1):
            for target in LINK.findall(line):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                resolved = (path.parent / target.split("#")[0]).resolve()
                if not resolved.exists() or (GUIDE not in resolved.parents and resolved != GUIDE):
                    where = f"{path.relative_to(ROOT)}:{line_number}"
                    problems.append(f"{where}: guide links outside itself: {target}")
    return problems


def main() -> int:
    """Entry point.

    Returns:
        ``0`` when every check passes, ``1`` otherwise.
    """
    checks = {
        "links resolve": check_links,
        "code blocks parse": check_code_blocks,
        "guide is standalone": check_guide_is_standalone,
        "no hand-typed counts": check_hand_typed_counts,
        "status matches roadmap": check_status_against_roadmap,
        "roadmap progress matches checkboxes": check_roadmap_progress,
        "code map covers modules": check_code_map_covers_modules,
        "symbol references exist": check_symbol_references,
    }

    failed = False
    for name, check in checks.items():
        problems = check()
        if problems:
            failed = True
            print(f"FAIL  {name}")
            for problem in problems:
                print(f"      {problem}")
        else:
            print(f"ok    {name}")

    return 1 if failed else 0


def _symbol_index() -> dict[str, set[str]]:
    """Collect the names a document is allowed to reference.

    Returns:
        A mapping of namespace to known members, so ``Capability.QUOTE`` can be
        checked against the enum rather than trusted.
    """
    import ast

    index: dict[str, set[str]] = {"classes": set(), "methods": set(), "modules": set()}
    for path in (ROOT / "src/quotestack").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        index["modules"].add(path.stem)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                index["classes"].add(node.name)
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        index["methods"].add(f"{node.name}.{item.name}")

    from quotestack.models import Capability

    for enum_name in (
        "AssetClass",
        "Market",
        "Interval",
        "Adjust",
        "FundClass",
        "EstimateBasis",
        "QuoteStatus",
        "Capability",
        "Confidence",
    ):
        try:
            module = __import__("quotestack.models", fromlist=[enum_name])
            enum = getattr(module, enum_name)
        except (ImportError, AttributeError):
            continue
        index.setdefault("enums", set()).update(f"{enum_name}.{member.name}" for member in enum)
    index["enums"].add(f"Capability.{Capability.RESOLVE.name}")
    return index


def check_symbol_references() -> list[str]:
    """Backticked code references must exist.

    Prose drifts by keeping a name the code renamed or deleted. Only references
    that carry a namespace are checked (``Capability.QUOTE``, ``client.quote``,
    ``src/...``), because a bare word in backticks is usually prose.
    """
    index = _symbol_index()
    problems = []
    pattern = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*(?:/[A-Za-z0-9_./-]*)?)`")

    for path in _documents():
        if "reviews" in path.parts:
            continue
        in_code = False
        for number, line in enumerate(_all_lines(path), start=1):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                # Fenced blocks carry examples and historical trees; the
                # references that rot are the ones in prose.
                continue
            for token in pattern.findall(line):
                if "/" in token and token.split("/")[0] in {"src", "docs", "guide", "tests"}:
                    if not (ROOT / token).exists():
                        problems.append(f"{path.relative_to(ROOT)}:{number}: no such path {token}")
                    continue
                if "." not in token or token.endswith(".py"):
                    continue
                head, _, tail = token.partition(".")
                if head in {
                    "Capability",
                    "AssetClass",
                    "Market",
                    "Interval",
                    "Adjust",
                    "FundClass",
                    "EstimateBasis",
                    "QuoteStatus",
                    "Confidence",
                }:
                    if token not in index.get("enums", set()):
                        problems.append(
                            f"{path.relative_to(ROOT)}:{number}: unknown enum member {token}"
                        )
                elif head in {"client", "MarketData", "SyncMarketData"}:
                    member = f"MarketData.{tail}"
                    if (
                        member not in index["methods"]
                        and f"SyncMarketData.{tail}" not in index["methods"]
                    ):
                        problems.append(f"{path.relative_to(ROOT)}:{number}: no method {token}")
    return problems


if __name__ == "__main__":
    raise SystemExit(main())
