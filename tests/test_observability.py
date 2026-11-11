"""Every registered event must have a place that emits it.

Five of the ten events were registered and never emitted: the registry promised
observability that did not exist, and the Prometheus counters for them would
read zero forever.
"""

from __future__ import annotations

import pathlib
import re

from quotestack.logging import EVENTS

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "quotestack"


def test_every_event_is_emitted_somewhere() -> None:
    """A registered event with no emission site is a lie in the metrics."""
    files = [
        path
        for path in SOURCE.rglob("*.py")
        if path.name != "logging.py" and "__pycache__" not in path.parts
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)

    missing = [name for name in EVENTS if f'"{name}"' not in text]
    assert not missing, f"registered but never emitted: {sorted(missing)}"


def test_emitted_events_are_registered() -> None:
    """An unregistered event raises at runtime, so catch it here instead."""
    files = [
        path
        for path in SOURCE.rglob("*.py")
        if path.name != "logging.py" and "__pycache__" not in path.parts
    ]
    pattern = re.compile(r'event\(\s*_?log,\s*logging\.\w+,\s*"([a-z_]+)"')
    used = set()
    for path in files:
        used.update(pattern.findall(path.read_text(encoding="utf-8")))

    unknown = used - set(EVENTS)
    assert not unknown, f"emitted but not registered: {sorted(unknown)}"


def test_documented_event_fields_match_the_code() -> None:
    """The event table listed fields nobody emitted.

    `batch` was documented with capability, elapsed_ms, ok and failed; the code
    passes only `count`. A reader tuning a log query on those names would get
    nothing, and nothing noticed because only the event names were tested.
    """
    import ast

    root = pathlib.Path(__file__).resolve().parents[1]
    emitted: dict[str, set[str]] = {}
    for path in (root / "src/quotestack").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", "") != "event":
                continue
            if len(node.args) < 3 or not isinstance(node.args[2], ast.Constant):
                continue
            name = str(node.args[2].value)
            fields = {kw.arg for kw in node.keywords if kw.arg and kw.arg != "hint"}
            emitted.setdefault(name, set()).update(fields)

    doc = (root / "docs/design/12-observability.md").read_text(encoding="utf-8")
    section = doc[doc.index("| 事件 | 级别 | 字段 |") :]
    section = section[: section.index("**已实现的事件")]

    documented: dict[str, set[str]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3 or not cells[0].startswith("`"):
            continue
        name = cells[0].strip("`")
        documented[name] = set(re.findall(r"`([a-z_]+)`", cells[2]))

    assert set(documented) == set(emitted), "event list drifted"
    for name, fields in documented.items():
        assert fields == emitted[name], f"{name}: doc {sorted(fields)} code {sorted(emitted[name])}"
