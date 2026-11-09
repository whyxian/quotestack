"""Map library errors onto HTTP status codes.

The mapping lives in one table so the contract cannot drift per route.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from quotestack.errors import (
    AmbiguousError,
    ClientBrokenError,
    DelistedError,
    EmptyResponseError,
    InternalError,
    InvalidArgumentError,
    MarketDataError,
    NotFoundError,
    RateLimitedError,
    SchemaChangedError,
    TimeoutError,
    UnauthorizedError,
    UnavailableError,
    UnsupportedError,
)

__all__ = ["STATUS_BY_CODE", "install"]

# Every concrete error class maps to exactly one status.
STATUS_BY_CODE: dict[type[MarketDataError], int] = {
    InvalidArgumentError: 400,
    NotFoundError: 404,
    AmbiguousError: 409,
    DelistedError: 410,
    UnsupportedError: 422,
    RateLimitedError: 429,
    SchemaChangedError: 502,
    EmptyResponseError: 502,
    UnavailableError: 502,
    UnauthorizedError: 502,
    TimeoutError: 504,
    ClientBrokenError: 503,
    InternalError: 500,
}


def status_for(error: MarketDataError) -> int:
    """Return the HTTP status for a library error.

    Args:
        error: The raised error.

    Returns:
        A status code; unknown errors become 500 rather than leaking details.
    """
    return STATUS_BY_CODE.get(type(error), 500)


def _envelope(code: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the one response shape every failure uses."""
    return {"data": None, "error": {"code": code, "message": message, "detail": detail or {}}}


def install(app: FastAPI) -> None:
    """Register the exception handlers.

    The envelope is a promise to clients: every failure looks the same, so one
    check is enough. Framework errors used to bypass it and answer
    ``{"detail": ...}``, which a client written against the documented shape
    cannot read.

    Args:
        app: The application to configure.
    """
    log = logging.getLogger("quotestack")

    @app.exception_handler(MarketDataError)
    async def _handle(request: Request, exc: MarketDataError) -> JSONResponse:
        return JSONResponse(
            status_code=status_for(exc),
            content=_envelope(exc.code, exc.message, exc.context),
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        """A malformed request is the caller's mistake, and says which field."""
        return JSONResponse(
            status_code=400,
            content=_envelope(
                "INVALID_ARGUMENT",
                "request validation failed",
                {"errors": exc.errors()},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Routing and method errors, in the same shape."""
        code = "NOT_FOUND" if exc.status_code == 404 else "INVALID_ARGUMENT"
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, str(exc.detail), {"path": request.url.path}),
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Anything unplanned still answers with the envelope, never a traceback."""
        log.exception(
            "unhandled error", extra={"event": "internal_error", "path": request.url.path}
        )
        return JSONResponse(
            status_code=500,
            content=_envelope("INTERNAL", "internal error", {"path": request.url.path}),
        )
