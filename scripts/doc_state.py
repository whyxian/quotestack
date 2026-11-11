"""Track which documents have been checked against the code, and when.

A document claiming "this matches the code" goes stale the moment the code
changes. What a document can honestly record is *when a human last confirmed
it*, and *which code it describes* - those are facts that stay true.

This script reports which documents deserve a re-read, and records a
confirmation when you have done one.

Usage::

    uv run python scripts/doc_state.py                    # what needs a look
    uv run python scripts/doc_state.py --init             # register new docs
    uv run python scripts/doc_state.py --confirm docs/design/04-cache.md
    uv run python scripts/doc_state.py --json             # machine readable
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE = ROOT / "docs" / "state.json"

# Documentation sets this file tracks, and the source tree each one is about.
DOC_GLOBS = ("docs/design/*.md", "docs/harness/*.md", "docs/*.md", "guide/*.md")


def _git(*args: str) -> str:
    """Run git in the repository and return stdout."""
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip()


def _documents() -> list[str]:
    """Every tracked document, as repository-relative paths."""
    found: set[str] = set()
    for pattern in DOC_GLOBS:
        for path in ROOT.glob(pattern):
            found.add(str(path.relative_to(ROOT)))
    return sorted(found)


def _describes(relative: str) -> list[str]:
    """Guess which source paths a document talks about.

    A document that names ``cache/base.py`` describes the cache package. When
    the document names nothing specific, the whole library is assumed - it is
    safer to over-report than to claim a document cannot go stale.
    """
    text = (ROOT / relative).read_text(encoding="utf-8")
    packages: set[str] = set()
    for candidate in (
        "client",
        "sources",
        "server",
        "cache",
        "identity",
        "models",
        "resilience",
        "benchmark",
        "estimate",
        "funds",
        "indexes",
        "logging",
        "sync",
        "cli",
        "errors",
    ):
        if f"{candidate}/" in text or f"{candidate}.py" in text:
            packages.add(f"src/quotestack/{candidate}")
    return sorted(packages) or ["src/quotestack"]


def load() -> dict[str, object]:
    """Read the state file, or return an empty skeleton."""
    if not STATE.exists():
        return {"version": 1, "documents": {}}
    return json.loads(STATE.read_text(encoding="utf-8"))


def save(state: dict[str, object]) -> None:
    """Write the state file with stable formatting."""
    STATE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _checked_by(relative: str) -> list[str]:
    """Test functions whose name suggests they guard this document."""
    stem = pathlib.Path(relative).stem
    probe = subprocess.run(
        ["git", "grep", "-l", stem, "--", "tests/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted(set(probe.stdout.split()))


def init(state: dict[str, object]) -> list[str]:
    """Register documents that are not tracked yet.

    A new document starts unconfirmed: ``verified_at`` is the current commit
    with ``confirmed: false``, so nothing pretends it was reviewed.

    Returns:
        The documents added.
    """
    documents: dict[str, dict[str, object]] = state.setdefault("documents", {})  # type: ignore[assignment]
    head = _git("rev-parse", "HEAD")
    added = []
    for relative in _documents():
        if relative in documents:
            continue
        documents[relative] = {
            "verified_at": head,
            "confirmed": False,
            "describes": _describes(relative),
            "checked_by": _checked_by(relative),
        }
        added.append(relative)
    return added


def _stale(entry: dict[str, object]) -> tuple[bool, list[str]]:
    """Whether the described code changed after the document was confirmed."""
    if entry.get("checked_by"):
        return False, []
    verified = str(entry.get("verified_at", ""))
    changed = []
    for path in entry.get("describes", []):  # type: ignore[union-attr]
        last = _git("log", "-1", "--format=%H", "--", str(path))
        if not last or last == verified:
            continue
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", last, verified],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if ancestor.returncode != 0:
            changed.append(str(path))
    return bool(changed), changed


def report(state: dict[str, object]) -> int:
    """Print the document status table.

    Returns:
        ``0`` always: this is a report, not a gate. Failing a build because 30
        documents mention a changed module would train people to ignore it.
    """
    documents: dict[str, dict[str, object]] = state["documents"]  # type: ignore[assignment]
    protected, unconfirmed, fresh, stale = [], [], [], []
    for relative, entry in sorted(documents.items()):
        if entry.get("checked_by"):
            protected.append(relative)
            continue
        if not entry.get("confirmed"):
            # Registered but never actually read against the code: calling this
            # "not stale" would be the same lie as a TTL nobody reads.
            unconfirmed.append(relative)
            continue
        changed, where = _stale(entry)
        (stale if changed else fresh).append((relative, where, entry))

    print(f"受测试保护  {len(protected)} 篇")
    print(f"已复查      {len(fresh)} 篇")
    print(f"待复查      {len(stale)} 篇")
    print(f"从未复查    {len(unconfirmed)} 篇")
    if stale:
        print()
        for relative, where, entry in stale:
            mark = "" if entry.get("confirmed") else "  (从未逐篇复查)"
            print(f"  {relative}{mark}")
            print(f"      涉及: {', '.join(where)}")
    return 0


def confirm(state: dict[str, object], relative: str) -> int:
    """Record that a document was re-read against the current code."""
    documents: dict[str, dict[str, object]] = state["documents"]  # type: ignore[assignment]
    if relative not in documents:
        print(f"{relative} is not tracked; run --init first")
        return 1
    documents[relative]["verified_at"] = _git("rev-parse", "HEAD")
    documents[relative]["confirmed"] = True
    documents[relative]["describes"] = _describes(relative)
    documents[relative]["checked_by"] = _checked_by(relative)
    print(f"confirmed {relative} at {documents[relative]['verified_at'][:7]}")
    return 0


def main() -> int:
    """Entry point."""
    state = load()
    args = sys.argv[1:]

    if "--init" in args:
        added = init(state)
        save(state)
        print(f"registered {len(added)} new document(s)")
        for relative in added:
            print(f"  {relative}")
        return 0

    if "--confirm" in args:
        index = args.index("--confirm")
        if index + 1 >= len(args):
            print("--confirm needs a document path")
            return 1
        code = confirm(state, args[index + 1])
        save(state)
        return code

    if "--json" in args:
        print(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    return report(state)


if __name__ == "__main__":
    raise SystemExit(main())
