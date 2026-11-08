"""Map library errors onto HTTP status codes.

The mapping lives in one table so the contract cannot drift per route.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from quotestack.errors import (
    AmbiguousError,
    ClientBrokenError,
    DelistedError,
    EmptyResponseError,
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
}


def status_for(error: MarketDataError) -> int:
    """Return the HTTP status for a library error.

    Args:
        error: The raised error.

    Returns:
        A status code; unknown errors become 500 rather than leaking details.
    """
    return STATUS_BY_CODE.get(type(error), 500)


def install(app: FastAPI) -> None:
    """Register the exception handlers.

    Args:
        app: The application to configure.
    """

    @app.exception_handler(MarketDataError)
    async def _handle(request: Request, exc: MarketDataError) -> JSONResponse:
        return JSONResponse(
            status_code=status_for(exc),
            content={
                "data": None,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "detail": exc.context,
                },
            },
        )
