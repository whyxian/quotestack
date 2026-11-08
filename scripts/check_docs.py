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


# Numbers that were typed by hand once and then stopped being true. Prose must
# not restate a count; the generated blocks are the only place a number lives.
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
)


def _prose_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    """Lines that are prose: not fenced code, not inside a generated block."""
    lines = []
    in_code = False
    in_generated = False
    for number, line in enumerate(_all_lines(path), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if "generated:begin" in stripped:
            in_generated = True
            continue
        if "generated:end" in stripped:
            in_generated = False
            continue
        if in_code or in_generated:
            continue
        lines.append((number, line))
    return lines


def check_stale_numbers() -> list[str]:
    """A hand-typed count in prose is a future contradiction."""
    problems = []
    for path in _documents():
        for number, line in _prose_lines(path):
            for phrase in STALE_PHRASES:
                if phrase in line:
                    where = f"{path.relative_to(ROOT)}:{number}"
                    problems.append(f"{where}: hand-typed count '{phrase}' (delete it)")
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
        "no hand-typed counts": check_stale_numbers,
        "status matches roadmap": check_status_against_roadmap,
        "code map covers modules": check_code_map_covers_modules,
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


if __name__ == "__main__":
    raise SystemExit(main())
