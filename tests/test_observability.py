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
