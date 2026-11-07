"""Structured logging helpers.

The library never configures handlers, levels or output. It only emits events
with structured fields; the application decides where they go.

Each event carries an ``event`` field so logs can be filtered by name::

    logger.info("batch", extra={"event": "batch", "count": 10})

See ``docs/design/12-observability.md`` for the event catalogue.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ["EVENTS", "event", "get_logger"]

# Event names in use. Keeping them in one place prevents typo drift.
EVENTS = frozenset(
    {
        "startup",
        "resolve",
        "cache_lookup",
        "upstream_request",
        "batch",
        "fallback",
        "stale_served",
        "cooldown",
        "schema_changed",
        "all_sources_failed",
    }
)


def get_logger(name: str) -> logging.Logger:
    """Return the package logger for a module.

    Args:
        name: Short module name, e.g. ``eastmoney``.

    Returns:
        A logger under the ``quotestack`` namespace. No handler is attached.
    """
    return logging.getLogger(f"quotestack.{name}")


def event(logger: logging.Logger, level: int, name: str, /, **fields: Any) -> None:
    """Emit a structured event.

    Args:
        logger: Target logger.
        level: Logging level, e.g. ``logging.INFO``.
        name: Event name, one of :data:`EVENTS`.
        **fields: Structured fields merged into the record.

    Raises:
        ValueError: The event name is not registered.
    """
    if name not in EVENTS:
        msg = f"unknown event {name!r}"
        raise ValueError(msg)
    logger.log(level, name, extra={"event": name, **fields})
