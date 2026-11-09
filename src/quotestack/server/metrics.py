"""Prometheus metrics.

The library emits structured log events and never imports a metrics client;
this module is the server-side tap that turns those events into counters.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

__all__ = ["EVENT_COUNTER", "install"]

EVENT_COUNTER = Counter(
    "quotestack_events_total",
    "Library events by name and level",
    labelnames=("event", "level"),
)


class _EventTap(logging.Handler):
    """Counts ``quotestack.*`` log records that carry an ``event`` field."""

    def emit(self, record: logging.LogRecord) -> None:
        name = getattr(record, "event", None)
        if isinstance(name, str):
            EVENT_COUNTER.labels(event=name, level=record.levelname).inc()


def install(app: FastAPI) -> logging.Handler:
    """Attach the event tap and add the metrics route.

    Args:
        app: Application to extend.

    Returns:
        The handler, so the caller can detach it during shutdown.
    """
    handler = _EventTap()
    logger = logging.getLogger("quotestack")
    # The library emits most events at DEBUG. Without raising the level here
    # they never reach a handler, and the counters stay empty.
    if logger.level == logging.NOTSET or logger.level > logging.DEBUG:
        logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return handler
