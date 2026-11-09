"""Enforce the layering rules mechanically.

ARCHITECTURE.md states the dependency direction; without a test it is only a
suggestion. These checks read imports from the source tree rather than trusting
reviewers to notice a violation.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "quotestack"

# Packages that may be imported by a given package. Everything in `models` is
# allowed to depend on `models`; a rule here is about direction, not isolation.
#
# ``benchmark`` and ``funds`` are leaf modules: they import nothing from
# quotestack, so they sit *below* models even though their names suggest
# otherwise. That is why models may import benchmark types.
_RULES: dict[str, set[str]] = {
    "models": {"models", "benchmark"},
    "errors": {"models"},
    "identity": {"models", "errors", "identity"},
    "cache": {"models", "errors", "cache"},
    "resilience": {"errors", "resilience"},
    "logging": {"logging"},
    "funds": {"models", "funds"},
    "benchmark": {"benchmark"},
    "indexes": {"indexes"},
    "estimate": {"models", "benchmark", "estimate"},
    # logging is a dependency-free leaf, like benchmark and funds; adapters
    # need it to report a request they are about to make.
    "sources": {
        "models",
        "errors",
        "identity",
        "indexes",
        "benchmark",
        "funds",
        "logging",
        "sources",
    },
    "client": {
        "models",
        "errors",
        "identity",
        "cache",
        "resilience",
        "logging",
        "funds",
        "benchmark",
        "indexes",
        "estimate",
        "sources",
        "client",
    },
    "server": {"models", "errors", "client", "logging", "server"},
    "cli": {"models", "errors", "client", "cli"},
    "sync": {"models", "errors", "client", "sync"},
    # The package root re-exports the public surface, so it may reach into
    # the client; it must not reach into sources or the server.
    "__init__": {"models", "errors", "client", "__init__"},
}


def _module_of(path: pathlib.Path) -> str:
    """Return the top-level package a file belongs to."""
    relative = path.relative_to(_ROOT)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


def _imports(path: pathlib.Path) -> set[str]:
    """Collect the quotestack subpackages a module imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            if not name.startswith("quotestack."):
                continue
            parts = name.split(".")
            if len(parts) >= 2:
                found.add(parts[1])
    return found


def _files() -> list[pathlib.Path]:
    return [p for p in _ROOT.rglob("*.py") if "__pycache__" not in p.parts]


@pytest.mark.parametrize("package", sorted(_RULES))
def test_package_only_imports_allowed_dependencies(package: str) -> None:
    """A package must not reach upward through the layers."""
    allowed = _RULES[package]
    for path in (p for p in _files() if _module_of(p) == package):
        forbidden = _imports(path) - allowed
        assert not forbidden, f"{path.name} imports {sorted(forbidden)}; allowed: {sorted(allowed)}"


def test_every_package_has_a_rule() -> None:
    """A new package without a rule would silently escape the check."""
    known = {_module_of(path) for path in _files()}
    missing = known - set(_RULES) - {"py"}
    assert not missing, f"add a rule for {sorted(missing)}"


def test_sources_never_import_the_client() -> None:
    """The adapters must not know how orchestration works."""
    for path in (p for p in _files() if _module_of(p) == "sources"):
        assert "client" not in _imports(path), f"{path.name} reaches into the client"


def test_models_stay_free_of_io() -> None:
    """Models are plain data; importing httpx or asyncio there is a smell."""
    forbidden = {"httpx", "asyncio", "logging"}
    for path in (p for p in _files() if _module_of(p) == "models"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not (names & forbidden), f"{path.name} imports {sorted(names & forbidden)}"


def test_sources_never_call_http_directly() -> None:
    """Every request must go through sources/transport.send.

    This is the seam where httpx exceptions are translated into the library's
    error model. Adapters used to call the client directly, so a refused
    connection escaped as httpx.ConnectError: callers catching MarketDataError
    caught nothing, the failover loop never saw the failure and could not try
    the next source, and the HTTP layer answered 500 instead of 502.
    """
    forbidden = {"get", "post", "put", "patch", "delete", "request", "stream"}
    offenders = []

    for path in (p for p in _files() if _module_of(p) == "sources"):
        if path.name == "transport.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in forbidden:
                continue
            target = node.func.value
            if isinstance(target, ast.Attribute) and target.attr == "_client":
                offenders.append(f"{path.name}:{node.lineno} calls _client.{node.func.attr}()")

    assert not offenders, (
        "use sources/transport.send instead of calling the HTTP client directly:\n  "
        + "\n  ".join(offenders)
    )


def test_transport_is_the_only_place_that_calls_request() -> None:
    """The conversion must stay in one file, not spread across adapters."""
    hits = []
    for path in (p for p in _files() if _module_of(p) == "sources"):
        text = path.read_text(encoding="utf-8")
        if "client.request(" in text:
            hits.append(path.name)

    assert hits == ["transport.py"], f"client.request used in {hits}"
