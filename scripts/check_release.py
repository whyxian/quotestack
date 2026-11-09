"""Pre-release checks.

Catches the things that are embarrassing to ship: personal paths, stray editor
files, debug leftovers, and a version that disagrees with itself.

Usage::

    uv run python scripts/check_release.py
"""

from __future__ import annotations

import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "build"}

# This file names the very patterns it looks for, so it must skip itself.
SELF = pathlib.Path(__file__).resolve()

FORBIDDEN_PATHS = ("/Users/", "/home/", "C:\\Users\\")
DEBUG_MARKERS = ("breakpoint()", "import pdb", "pdb.set_trace()")
JUNK = (".DS_Store", ".pyc", ".pyo", "Thumbs.db")


def _files() -> list[pathlib.Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in SKIP_DIRS for part in path.parts)
        and path.resolve() != SELF
    ]


def check_personal_paths() -> list[str]:
    """Absolute home paths leak the author's machine."""
    problems = []
    for path in _files():
        if path.suffix not in {".py", ".md", ".toml", ".yaml", ".yml", ".json", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in FORBIDDEN_PATHS:
            if marker in text:
                problems.append(f"{path.relative_to(ROOT)}: contains {marker}")
    return problems


def check_junk_files() -> list[str]:
    return [
        str(path.relative_to(ROOT))
        for path in _files()
        if any(str(path).endswith(junk) for junk in JUNK) or path.name == ".DS_Store"
    ]


def check_debug_leftovers() -> list[str]:
    problems = []
    for path in _files():
        if path.suffix != ".py" or (path.parts[-2:-1] and path.parts[-2] == "tests"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in DEBUG_MARKERS:
            if marker in text:
                problems.append(f"{path.relative_to(ROOT)}: {marker}")
    return problems


def check_version() -> list[str]:
    """The version must be identical in pyproject and the package."""
    problems = []
    with (ROOT / "pyproject.toml").open("rb") as handle:
        declared = tomllib.load(handle)["project"]["version"]
    init = (ROOT / "src" / "quotestack" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    if match is None:
        return ["src/quotestack/__init__.py has no __version__"]
    if match.group(1) != declared:
        problems.append(f"version mismatch: pyproject {declared} vs package {match.group(1)}")
    if declared == "0.0.1" and "--allow-0-0-1" not in sys.argv:
        problems.append(f"version is still {declared}")
    return problems


def check_readme_links_are_absolute() -> list[str]:
    """The README becomes the PyPI project page, where relative links die.

    PyPI renders the long description as-is and does not resolve repository
    paths, so every relative link on it becomes a 404 for someone arriving from
    the package index.
    """
    import re

    text = (ROOT / "README.md").read_text(encoding="utf-8")
    problems = []
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        problems.append(f"README links to '{target}', which PyPI cannot resolve")
    return problems


def check_placeholders() -> list[str]:
    """Unresolved placeholders must not reach a release.

    The repository URL is unknown until the project is published, so it is a
    literal placeholder. Shipping one means the changelog links 404.
    """
    if "--allow-placeholders" in sys.argv:
        return []
    problems = []
    for path in _files():
        if path.suffix not in {".md", ".toml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in ("OWNER/", "<repo>"):
            if marker in text:
                problems.append(f"{path.relative_to(ROOT)}: unresolved {marker}")
    return problems


def check_urls_agree() -> list[str]:
    """The repository URL must say the same thing everywhere."""
    if "--allow-placeholders" in sys.argv:
        return []
    with (ROOT / "pyproject.toml").open("rb") as handle:
        urls = tomllib.load(handle)["project"].get("urls", {})
    repository = urls.get("Repository", "")
    if not repository:
        return ["pyproject has no [project.urls] Repository"]

    owner = repository.rstrip("/").split("/")[-2:-1]
    if not owner:
        return [f"cannot parse an owner from {repository}"]

    problems = []
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"{owner[0]}/quotestack" not in changelog:
        problems.append(
            f"CHANGELOG links do not use {owner[0]}/quotestack (repository is {repository})"
        )
    return problems


def check_required_files() -> list[str]:
    required = ("LICENSE", "README.md", "pyproject.toml", "CHANGELOG.md")
    return [f"missing {name}" for name in required if not (ROOT / name).exists()]


def main() -> int:
    checks = {
        "personal paths": check_personal_paths,
        "junk files": check_junk_files,
        "debug leftovers": check_debug_leftovers,
        "version": check_version,
        "placeholders": check_placeholders,
        "url consistency": check_urls_agree,
        "readme links": check_readme_links_are_absolute,
        "required files": check_required_files,
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
